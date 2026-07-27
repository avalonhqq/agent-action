"""把5A的源结构块转换为可召回Child和可回答Parent。

本模块保持为纯算法层：不访问数据库、不生成Embedding，也不依赖向量数据库。
5B-3会把这里产生的local_id映射为真正的KnowledgeChunk数据库ID。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bili_support.knowledge.types import LoadedSourceBlock, SourceBlockType

# 后向断言让标点或换行仍保留在前一个片段中，避免切分时吞掉原文边界。
_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\n])")


class ChunkKind(StrEnum):
    """Small-to-Big中的两种知识单元。"""

    PARENT = "parent"  # 完整上下文，Child命中后交给大模型回答
    CHILD = "child"  # 紧凑检索文本，未来写入BM25和向量索引


class DocumentKnowledgeType(StrEnum):
    """整份文档的知识组织类型；TABLE属于SourceBlockType而非此枚举。"""

    POLICY = "policy"  # 政策、规则、协议：重视条款边界和适用条件
    MANUAL = "manual"  # 操作手册：重视步骤顺序和前置条件
    FAQ = "faq"  # 标准问答：问题适合Child，问答整体适合Parent
    GENERIC = "generic"  # 无明确模板的通用知识，使用自然句子边界


class ChunkDraft(BaseModel):
    """尚未持久化的分块结果，是算法层与数据库层之间的稳定契约。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # local_id只在本次分块结果内唯一，5B-3持久化时再映射为数据库UUID。
    local_id: str = Field(min_length=1)
    kind: ChunkKind
    content: str = Field(min_length=1)
    source_block_ordinal: int = Field(ge=0)
    # Parent没有父引用；Child必须指向同批结果中的一个Parent。
    parent_local_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("local_id", "content")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        """去除边界空白，阻止只包含空白的ID或Chunk进入后续索引。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("chunk text fields must not be blank")
        return normalized

    @field_validator("parent_local_id")
    @classmethod
    def normalize_parent_local_id(cls, value: str | None) -> str | None:
        """可选父引用一旦提供就必须是非空ID。"""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("parent_local_id must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_parent_reference(self) -> Self:
        """在契约层阻止Parent自带父引用或Child没有Parent。"""

        if self.kind is ChunkKind.PARENT and self.parent_local_id is not None:
            raise ValueError("parent chunk must not reference another parent")
        if self.kind is ChunkKind.CHILD and not self.parent_local_id:
            raise ValueError("child chunk must reference a parent")
        return self


class ChunkStrategy(Protocol):
    """所有分块策略都接收相同SourceBlock，并返回相同ChunkDraft。"""

    def chunk(
            self,
            *,
            blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]: ...


class GenericChunkStrategy:
    """按标题上下文和自然句子边界生成通用Parent/Child。"""

    def __init__(
            self,
            *,
            child_max_chars: int = 160,
            child_overlap_chars: int = 20,
    ) -> None:
        if child_max_chars <= 0:
            raise ValueError("child_max_chars must be greater than zero")
        if child_overlap_chars < 0:
            raise ValueError("child_overlap_chars must not be negative")
        if child_overlap_chars >= child_max_chars:
            # 滑窗步长=max-overlap；两者相等会让start不再前进并造成死循环。
            raise ValueError("child_overlap_chars must be smaller than child_max_chars")
        self._child_max_chars = child_max_chars
        self._child_overlap_chars = child_overlap_chars

    def chunk(
            self,
            *,
            blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        """每个非标题SourceBlock生成一个Parent和至少一个Child。"""

        drafts: list[ChunkDraft] = []
        seen_ordinals: set[int] = set()
        for block in blocks:
            # ordinal进入local_id，重复序号会造成父子引用歧义，因此尽早失败。
            if block.ordinal in seen_ordinals:
                raise ValueError(f"duplicate source block ordinal: {block.ordinal}")
            seen_ordinals.add(block.ordinal)

            # 标题语义已经存在后续正文的heading_path中；独立索引短标题只会制造噪声。
            if block.block_type is SourceBlockType.HEADING:
                continue

            parent_local_id = f"parent-{block.ordinal}"
            metadata = _block_metadata(block)
            drafts.append(
                ChunkDraft(
                    local_id=parent_local_id,
                    kind=ChunkKind.PARENT,
                    content=_format_parent_content(block),
                    source_block_ordinal=block.ordinal,
                    metadata={
                        **metadata,
                        "body_char_count": len(block.content),
                    },
                )
            )

            for child_index, body in enumerate(self._split_content(block.content)):
                drafts.append(
                    ChunkDraft(
                        local_id=f"child-{block.ordinal}-{child_index}",
                        kind=ChunkKind.CHILD,
                        content=_format_child_content(block, body),
                        source_block_ordinal=block.ordinal,
                        parent_local_id=parent_local_id,
                        metadata={
                            **metadata,
                            # 上限只约束正文，标题前缀用于增强召回，不计入正文预算。
                            "body_char_count": len(body),
                        },
                    )
                )
        return tuple(drafts)

    def _split_content(self, content: str) -> tuple[str, ...]:
        """优先按自然边界装箱，只有单句超长时才退化为重叠字符窗口。"""

        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        sentences = [
            _normalize_sentence_segment(value)
            for value in _SENTENCE_BOUNDARY.split(normalized)
            if value.strip()
        ]
        return tuple(self._pack_sentences(sentences))

    def _pack_sentences(self, sentences: list[str]) -> list[str]:
        """尽量合并相邻短句，同时保证每个Child正文不超过配置上限。"""

        parts: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > self._child_max_chars:
                # 超长句不能与前一个缓冲区混合，否则边界和上限都会变得难以推理。
                if current:
                    parts.append(current)
                    current = ""
                parts.extend(self._split_oversized_sentence(sentence))
                continue

            candidate = current + sentence
            if len(candidate) <= self._child_max_chars:
                current = candidate
                continue

            if current:
                parts.append(current)
            current = sentence

        if current:
            parts.append(current)
        return parts

    def _split_oversized_sentence(self, sentence: str) -> list[str]:
        """用有界滑窗处理没有自然断点的长句，并保证循环始终前进。"""

        parts: list[str] = []
        step = self._child_max_chars - self._child_overlap_chars
        start = 0
        while start < len(sentence):
            end = start + self._child_max_chars
            part = sentence[start:end].strip()
            if part:
                parts.append(part)
            if end >= len(sentence):
                break
            start += step
        return parts


def _format_parent_content(block: LoadedSourceBlock) -> str:
    """Parent保留完整标题路径和SourceBlock正文，作为最终回答上下文。"""

    heading = " > ".join(block.heading_path)
    if heading:
        return f"标题：{heading}\n正文：{block.content}"
    return f"正文：{block.content}"


def _format_child_content(block: LoadedSourceBlock, body: str) -> str:
    """Child加入紧凑标题前缀，让检索模型能直接看到主题词。"""

    heading = " / ".join(block.heading_path)
    if heading:
        return f"{heading}：{body}"
    return body


def _block_metadata(block: LoadedSourceBlock) -> dict[str, object]:
    """继承5A追溯字段，并把Loader专属元数据放入独立命名空间。"""

    return {
        "heading_path": list(block.heading_path),
        "page_number": block.page_number,
        "source_block_type": block.block_type.value,
        "source_metadata": dict(block.metadata),
    }


def _normalize_sentence_segment(value: str) -> str:
    """清理片段空格，同时保留一个换行以维持列表和表格的行边界。"""

    has_trailing_newline = value.endswith("\n")
    normalized = value.strip()
    return normalized + ("\n" if has_trailing_newline else "")
