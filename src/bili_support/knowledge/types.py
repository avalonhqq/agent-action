"""文档Loader与后续Chunker之间的稳定知识表示契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceBlockType(StrEnum):
    """Loader 能识别的源文档结构类型；这里不是最终知识分类。"""

    # 标题块：来自 Markdown 的 # 标题或 Word 的“标题 1/2/3”等样式。
    # 标题既保存为独立块，也会进入后续正文块的 heading_path，帮助还原章节层级。
    HEADING = "heading"

    # 普通段落块：连续的正文文本，是政策说明、操作步骤和客服知识最常见的来源。
    # 它只表示原文是正文段落，不代表已经达到最终检索 Chunk 的合适长度。
    PARAGRAPH = "paragraph"

    # 列表块：来自 Word 列表等具有项目关系的内容，例如条件清单或操作步骤。
    # 单独标记后，5B 可以避免把每个短列表项切成失去上下文的孤立 Child。
    LIST = "list"

    # 表格块：保存经过规范化但仍保留表头、行号和列语义的二维数据。
    # 5B 会针对表格采用按行生成 Child、整表或分组行生成 Parent 的专用策略。
    TABLE = "table"


class LoadedSourceBlock(BaseModel):
    """尽量忠实、可追溯的源结构块，不预设最终检索粒度。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=0)
    block_type: SourceBlockType
    content: str = Field(min_length=1)
    page_number: int | None = Field(default=None, gt=0)
    heading_path: tuple[str, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = "\n".join(line.rstrip() for line in value.strip().splitlines())
        if not normalized:
            raise ValueError("source block content must not be blank")
        return normalized


class LoadedDocument(BaseModel):
    """单个 Loader 的统一输出，Service 不需要了解具体文件解析库。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    media_type: str = Field(min_length=1, max_length=100)
    blocks: tuple[LoadedSourceBlock, ...] = ()
    metadata: dict[str, object] = Field(default_factory=dict)
