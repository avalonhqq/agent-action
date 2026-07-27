"""5B-2面向政策、手册、FAQ和表格的确定性分块策略。"""

from __future__ import annotations

import re

from bili_support.knowledge.chunking import (
    ChunkDraft,
    ChunkKind,
    ChunkStrategy,
    DocumentKnowledgeType,
    GenericChunkStrategy,
)
from bili_support.knowledge.types import LoadedSourceBlock, SourceBlockType

_TABLE_ROW_PREFIX = re.compile(r"^第(\d+)行[：:]\s*")
_EXPLICIT_QA = re.compile(
    r"(?:^|\n)\s*(?:问|Q)[：:]\s*(?P<question>.+?)"
    r"(?:\n|\s)+(?:答|A)[：:]\s*(?P<answer>.+)",
    re.IGNORECASE | re.DOTALL,
)
_STEP_PREFIX = re.compile(
    r"^\s*(?:(?:第\s*)?(\d+)\s*(?:步|[.、)]))[ \t]*(.+)$"
)
_BULLET_PREFIX = re.compile(r"^\s*[-*•]\s+(.+)$")
_POLICY_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;\n])")
_POLICY_EXCEPTION_PREFIXES = (
    "但",
    "但是",
    "不过",
    "除非",
    "例外",
    "不适用",
    "不得",
    "不支持",
)


class TableChunkStrategy:
    """整表作为Parent、每个保留列语义的数据行作为Child。"""

    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        drafts: list[ChunkDraft] = []
        for block in blocks:
            if block.block_type is not SourceBlockType.TABLE:
                raise ValueError("TableChunkStrategy only accepts TABLE blocks")
            rows = [
                _TABLE_ROW_PREFIX.sub("", line.strip())
                for line in block.content.splitlines()
                if line.strip()
            ]
            if not rows or any(not row for row in rows):
                raise ValueError(f"table block {block.ordinal} has no valid rows")

            parent_id = f"table-parent-{block.ordinal}"
            metadata = _metadata(block, strategy="table")
            drafts.append(
                ChunkDraft(
                    local_id=parent_id,
                    kind=ChunkKind.PARENT,
                    content=_parent_text(block, label="表格"),
                    source_block_ordinal=block.ordinal,
                    metadata={**metadata, "row_count": len(rows)},
                )
            )
            for row_index, row in enumerate(rows):
                drafts.append(
                    ChunkDraft(
                        local_id=f"table-child-{block.ordinal}-{row_index}",
                        kind=ChunkKind.CHILD,
                        content=_child_text(block, row),
                        source_block_ordinal=block.ordinal,
                        parent_local_id=parent_id,
                        metadata={
                            **metadata,
                            "row_index": row_index,
                            "body_char_count": len(row),
                        },
                    )
                )
        return tuple(drafts)


class FaqChunkStrategy:
    """把问题用于召回，把完整问答用于回答；未知结构回退Generic。"""

    def __init__(self, *, fallback: ChunkStrategy | None = None) -> None:
        self._fallback = fallback or GenericChunkStrategy()

    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        drafts: list[ChunkDraft] = []
        fallback_blocks: list[LoadedSourceBlock] = []
        pending_question: str | None = None

        for block in blocks:
            if block.block_type is SourceBlockType.TABLE:
                raise ValueError("TABLE blocks must be delegated to TableChunkStrategy")
            if block.block_type is SourceBlockType.HEADING:
                if _looks_like_question(block.content):
                    pending_question = _strip_question_label(block.content)
                continue

            explicit = _EXPLICIT_QA.search(block.content)
            if explicit is not None:
                drafts.extend(
                    _faq_pair(
                        block,
                        question=_strip_question_label(explicit.group("question")),
                        answer=explicit.group("answer").strip(),
                    )
                )
                pending_question = None
                continue

            if pending_question is not None:
                drafts.extend(
                    _faq_pair(
                        block,
                        question=pending_question,
                        answer=block.content,
                    )
                )
                pending_question = None
                continue

            fallback_blocks.append(block)

        if fallback_blocks:
            drafts.extend(self._fallback.chunk(blocks=tuple(fallback_blocks)))
        return tuple(drafts)


class ManualChunkStrategy:
    """按操作章节组织Parent，并为每个步骤补充目标和前置步骤。"""

    def __init__(self, *, fallback: ChunkStrategy | None = None) -> None:
        self._fallback = fallback or GenericChunkStrategy()

    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        drafts: list[ChunkDraft] = []
        for group in _content_groups(blocks):
            steps, descriptions = _manual_steps(group)
            if not steps:
                drafts.extend(self._fallback.chunk(blocks=group))
                continue

            first = group[0]
            parent_id = f"manual-parent-{first.ordinal}"
            metadata = _group_metadata(group, strategy="manual")
            full_text = "\n".join(block.content for block in group)
            drafts.append(
                ChunkDraft(
                    local_id=parent_id,
                    kind=ChunkKind.PARENT,
                    content=_section_parent_text(first.heading_path, "操作手册", full_text),
                    source_block_ordinal=first.ordinal,
                    metadata={**metadata, "step_count": len(steps)},
                )
            )

            previous_step: str | None = None
            target = " / ".join(first.heading_path) or "操作手册"
            description = "；".join(descriptions)
            for step_index, (source_ordinal, step) in enumerate(steps, start=1):
                parts = [f"操作目标：{target}", f"当前步骤{step_index}：{step}"]
                if description:
                    parts.append(f"说明：{description}")
                if previous_step is not None:
                    parts.append(f"前置步骤：{previous_step}")
                body = "；".join(parts)
                drafts.append(
                    ChunkDraft(
                        local_id=f"manual-child-{first.ordinal}-{step_index - 1}",
                        kind=ChunkKind.CHILD,
                        content=body,
                        source_block_ordinal=source_ordinal,
                        parent_local_id=parent_id,
                        metadata={
                            **metadata,
                            "step_index": step_index,
                            "body_char_count": len(body),
                        },
                    )
                )
                previous_step = step
        return tuple(drafts)


class PolicyChunkStrategy:
    """按政策章节生成Parent，并把例外条款绑定到前一个结论Child。"""

    def __init__(self, *, fallback: ChunkStrategy | None = None) -> None:
        self._fallback = fallback or GenericChunkStrategy()

    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        drafts: list[ChunkDraft] = []
        for group in _content_groups(blocks):
            semantic_units = _policy_units(group)
            if not semantic_units:
                drafts.extend(self._fallback.chunk(blocks=group))
                continue

            first = group[0]
            parent_id = f"policy-parent-{first.ordinal}"
            metadata = _group_metadata(group, strategy="policy")
            full_text = "\n".join(block.content for block in group)
            drafts.append(
                ChunkDraft(
                    local_id=parent_id,
                    kind=ChunkKind.PARENT,
                    content=_section_parent_text(first.heading_path, "政策条款", full_text),
                    source_block_ordinal=first.ordinal,
                    metadata={
                        **metadata,
                        "semantic_unit_count": len(semantic_units),
                    },
                )
            )
            for unit_index, (source_ordinal, unit) in enumerate(semantic_units):
                drafts.append(
                    ChunkDraft(
                        local_id=f"policy-child-{first.ordinal}-{unit_index}",
                        kind=ChunkKind.CHILD,
                        content=_heading_prefix(first.heading_path, unit),
                        source_block_ordinal=source_ordinal,
                        parent_local_id=parent_id,
                        metadata={
                            **metadata,
                            "semantic_unit_index": unit_index,
                            "contains_exception": _contains_exception(unit),
                            "body_char_count": len(unit),
                        },
                    )
                )
        return tuple(drafts)


class StrategySelector:
    """按文档知识类型选择策略，并让TABLE块始终优先使用表格策略。"""

    def __init__(
        self,
        *,
        generic: ChunkStrategy | None = None,
        policy: ChunkStrategy | None = None,
        manual: ChunkStrategy | None = None,
        faq: ChunkStrategy | None = None,
        table: ChunkStrategy | None = None,
    ) -> None:
        generic_strategy = generic or GenericChunkStrategy()
        self._strategies: dict[DocumentKnowledgeType, ChunkStrategy] = {
            DocumentKnowledgeType.GENERIC: generic_strategy,
            DocumentKnowledgeType.POLICY: policy
            or PolicyChunkStrategy(fallback=generic_strategy),
            DocumentKnowledgeType.MANUAL: manual
            or ManualChunkStrategy(fallback=generic_strategy),
            DocumentKnowledgeType.FAQ: faq or FaqChunkStrategy(fallback=generic_strategy),
        }
        self._table = table or TableChunkStrategy()

    def select(self, knowledge_type: DocumentKnowledgeType) -> ChunkStrategy:
        """返回表格感知的组合策略，而不是暴露裸文档策略。"""

        return _TableAwareStrategy(
            document_strategy=self._strategies[knowledge_type],
            table_strategy=self._table,
        )


class _TableAwareStrategy:
    """按原顺序把连续TABLE/非TABLE块分别交给对应策略。"""

    def __init__(
        self,
        *,
        document_strategy: ChunkStrategy,
        table_strategy: ChunkStrategy,
    ) -> None:
        self._document_strategy = document_strategy
        self._table_strategy = table_strategy

    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        drafts: list[ChunkDraft] = []
        current: list[LoadedSourceBlock] = []
        current_is_table: bool | None = None

        def flush() -> None:
            if not current:
                return
            strategy = self._table_strategy if current_is_table else self._document_strategy
            drafts.extend(strategy.chunk(blocks=tuple(current)))
            current.clear()

        for block in blocks:
            is_table = block.block_type is SourceBlockType.TABLE
            if current_is_table is not None and is_table != current_is_table:
                flush()
            current_is_table = is_table
            current.append(block)
        flush()
        return tuple(drafts)


def _faq_pair(
    block: LoadedSourceBlock,
    *,
    question: str,
    answer: str,
) -> tuple[ChunkDraft, ChunkDraft]:
    if not question or not answer:
        raise ValueError(f"FAQ block {block.ordinal} requires question and answer")
    parent_id = f"faq-parent-{block.ordinal}"
    metadata = _metadata(block, strategy="faq")
    parent = ChunkDraft(
        local_id=parent_id,
        kind=ChunkKind.PARENT,
        content=f"问题：{question}\n答案：{answer}",
        source_block_ordinal=block.ordinal,
        metadata={**metadata, "question": question},
    )
    child_text = _heading_prefix(block.heading_path, question)
    child = ChunkDraft(
        local_id=f"faq-child-{block.ordinal}-0",
        kind=ChunkKind.CHILD,
        content=child_text,
        source_block_ordinal=block.ordinal,
        parent_local_id=parent_id,
        metadata={
            **metadata,
            "question": question,
            "body_char_count": len(question),
        },
    )
    return parent, child


def _looks_like_question(value: str) -> bool:
    normalized = _strip_question_label(value)
    return (
        value.strip().startswith(("问：", "问:", "Q:", "Q："))
        or normalized.endswith(("？", "?", "吗", "么"))
        or normalized.startswith(
            ("如何", "怎么", "是否", "什么", "为什么", "哪里", "多久")
        )
    )


def _strip_question_label(value: str) -> str:
    return re.sub(r"^\s*(?:问|Q)[：:]\s*", "", value, flags=re.IGNORECASE).strip()


def _content_groups(
    blocks: tuple[LoadedSourceBlock, ...],
) -> tuple[tuple[LoadedSourceBlock, ...], ...]:
    """按连续heading_path分组；TABLE应在调用前由组合策略取走。"""

    groups: list[tuple[LoadedSourceBlock, ...]] = []
    current: list[LoadedSourceBlock] = []
    current_path: tuple[str, ...] | None = None
    for block in blocks:
        if block.block_type is SourceBlockType.TABLE:
            raise ValueError("TABLE blocks must be delegated to TableChunkStrategy")
        if block.block_type is SourceBlockType.HEADING:
            continue
        if current and block.heading_path != current_path:
            groups.append(tuple(current))
            current = []
        current_path = block.heading_path
        current.append(block)
    if current:
        groups.append(tuple(current))
    return tuple(groups)


def _manual_steps(
    group: tuple[LoadedSourceBlock, ...],
) -> tuple[list[tuple[int, str]], list[str]]:
    steps: list[tuple[int, str]] = []
    descriptions: list[str] = []
    for block in group:
        if block.block_type is SourceBlockType.LIST:
            steps.append((block.ordinal, block.content.strip()))
            continue
        for line in block.content.splitlines():
            normalized = line.strip()
            if not normalized:
                continue
            numbered = _STEP_PREFIX.match(normalized)
            bullet = _BULLET_PREFIX.match(normalized)
            if numbered is not None:
                steps.append((block.ordinal, numbered.group(2).strip()))
            elif bullet is not None:
                steps.append((block.ordinal, bullet.group(1).strip()))
            else:
                descriptions.append(normalized)
    return steps, descriptions


def _policy_units(
    group: tuple[LoadedSourceBlock, ...],
) -> list[tuple[int, str]]:
    units: list[tuple[int, str]] = []
    for block in group:
        fragments = [
            value.strip()
            for value in _POLICY_SENTENCE_BOUNDARY.split(block.content)
            if value.strip()
        ]
        for fragment in fragments:
            if units and _is_exception_fragment(fragment):
                previous_ordinal, previous = units[-1]
                units[-1] = (previous_ordinal, previous + fragment)
            else:
                units.append((block.ordinal, fragment))
    return units


def _contains_exception(value: str) -> bool:
    normalized = value.strip()
    return any(marker in normalized for marker in _POLICY_EXCEPTION_PREFIXES)


def _is_exception_fragment(value: str) -> bool:
    normalized = value.strip()
    return normalized.startswith(_POLICY_EXCEPTION_PREFIXES)


def _metadata(block: LoadedSourceBlock, *, strategy: str) -> dict[str, object]:
    return {
        "strategy": strategy,
        "heading_path": list(block.heading_path),
        "page_number": block.page_number,
        "source_block_type": block.block_type.value,
        "source_metadata": dict(block.metadata),
    }


def _group_metadata(
    group: tuple[LoadedSourceBlock, ...],
    *,
    strategy: str,
) -> dict[str, object]:
    first = group[0]
    return {
        **_metadata(first, strategy=strategy),
        "source_block_ordinals": [block.ordinal for block in group],
        "page_numbers": list(
            dict.fromkeys(
                block.page_number
                for block in group
                if block.page_number is not None
            )
        ),
    }


def _parent_text(block: LoadedSourceBlock, *, label: str) -> str:
    return _section_parent_text(block.heading_path, label, block.content)


def _section_parent_text(
    heading_path: tuple[str, ...],
    label: str,
    content: str,
) -> str:
    heading = " > ".join(heading_path)
    if heading:
        return f"标题：{heading}\n{label}：{content}"
    return f"{label}：{content}"


def _child_text(block: LoadedSourceBlock, body: str) -> str:
    return _heading_prefix(block.heading_path, body)


def _heading_prefix(heading_path: tuple[str, ...], body: str) -> str:
    heading = " / ".join(heading_path)
    if heading:
        return f"{heading}：{body}"
    return body
