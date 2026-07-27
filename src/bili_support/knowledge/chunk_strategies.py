"""5B-2面向政策、手册、FAQ和表格的确定性分块策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bili_support.knowledge.chunking import (
    ChunkDraft,
    ChunkKind,
    ChunkStrategy,
    DocumentKnowledgeType,
    GenericChunkStrategy,
)
from bili_support.knowledge.types import LoadedSourceBlock, SourceBlockType

_TABLE_ROW_PREFIX = re.compile(r"^第(\d+)行[：:]\s*")
_FAQ_QUESTION_LINE = re.compile(r"^\s*(?:问|Q)\s*[：:]\s*(.+?)\s*$", re.IGNORECASE)
_FAQ_ANSWER_LINE = re.compile(r"^\s*(?:答|A)\s*[：:]\s*(.*?)\s*$", re.IGNORECASE)
_FAQ_KEYWORDS_LINE = re.compile(
    r"^\s*(?:关键词|关键字|keywords?)\s*[：:]\s*(.*?)\s*$",
    re.IGNORECASE,
)
_FAQ_KEYWORD_SEPARATOR = re.compile(r"[、,，;；]\s*")
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
_FAQ_SECTION_MARKERS = ("faq", "常见问题", "客服问答")
_MANUAL_SECTION_MARKERS = (
    "开通前准备",
    "开通方式",
    "操作步骤",
    "取消自动续费",
    "支付成功但会员未到账",
    "发票申请",
    "故障处理",
    "兑换码开通",
)
_POLICY_SECTION_MARKERS = (
    "服务简介",
    "套餐类型",
    "会员权益",
    "生效时间",
    "有效期",
    "设备规则",
    "自动续费管理",
    "支付、订单",
    "退款",
    "取消规则",
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
    """跨Markdown单块或Word多段落解析多组Q/A/关键词。"""

    def __init__(self, *, fallback: ChunkStrategy | None = None) -> None:
        self._fallback = fallback or GenericChunkStrategy()

    def chunk(
            self,
            *,
            blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        records, fallback_blocks = _parse_faq_records(blocks)
        drafts = [
            draft
            for record_index, record in enumerate(records)
            for draft in _faq_record_drafts(record, record_index=record_index)
        ]
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


class MixedDocumentChunkStrategy:
    """按标题路径把综合Word/PDF的连续章节路由到专用策略。"""

    def __init__(
        self,
        *,
        generic: ChunkStrategy | None = None,
        policy: ChunkStrategy | None = None,
        manual: ChunkStrategy | None = None,
        faq: ChunkStrategy | None = None,
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

    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]:
        drafts: list[ChunkDraft] = []
        current: list[LoadedSourceBlock] = []
        current_type: DocumentKnowledgeType | None = None

        def flush() -> None:
            if not current or current_type is None:
                return
            drafts.extend(self._strategies[current_type].chunk(blocks=tuple(current)))
            current.clear()

        for block in blocks:
            if block.block_type is SourceBlockType.TABLE:
                raise ValueError("TABLE blocks must be delegated to TableChunkStrategy")
            selected_type = _section_knowledge_type(block.heading_path)
            if current_type is not None and selected_type is not current_type:
                flush()
            current_type = selected_type
            current.append(block)
        flush()
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
        self._strategies[DocumentKnowledgeType.MIXED] = MixedDocumentChunkStrategy(
            generic=generic_strategy,
            policy=self._strategies[DocumentKnowledgeType.POLICY],
            manual=self._strategies[DocumentKnowledgeType.MANUAL],
            faq=self._strategies[DocumentKnowledgeType.FAQ],
        )
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


@dataclass(frozen=True, slots=True)
class _FaqRecord:
    """从一个或多个SourceBlock中恢复出的单组FAQ。"""

    question: str
    answer: str
    keywords: tuple[str, ...]
    source_blocks: tuple[LoadedSourceBlock, ...]
    heading_path: tuple[str, ...]


def _parse_faq_records(
    blocks: tuple[LoadedSourceBlock, ...],
) -> tuple[list[_FaqRecord], list[LoadedSourceBlock]]:
    """用逐行状态机同时支持Markdown单块多FAQ与Word跨段FAQ。"""

    records: list[_FaqRecord] = []
    fallback_blocks: list[LoadedSourceBlock] = []
    question: str | None = None
    answer_parts: list[str] = []
    keywords: list[str] = []
    source_blocks: list[LoadedSourceBlock] = []
    heading_path: tuple[str, ...] = ()

    def remember_source(block: LoadedSourceBlock) -> None:
        if all(existing.ordinal != block.ordinal for existing in source_blocks):
            source_blocks.append(block)

    def flush() -> None:
        nonlocal question, heading_path
        if question is None:
            return
        answer = "\n".join(answer_parts).strip()
        if not answer:
            first_ordinal = source_blocks[0].ordinal if source_blocks else "unknown"
            raise ValueError(f"FAQ question at block {first_ordinal} has no answer")
        records.append(
            _FaqRecord(
                question=question,
                answer=answer,
                keywords=tuple(dict.fromkeys(keywords)),
                source_blocks=tuple(source_blocks),
                heading_path=heading_path,
            )
        )
        question = None
        heading_path = ()
        answer_parts.clear()
        keywords.clear()
        source_blocks.clear()

    for block in blocks:
        if block.block_type is SourceBlockType.TABLE:
            raise ValueError("TABLE blocks must be delegated to TableChunkStrategy")

        if block.block_type is SourceBlockType.HEADING:
            if not _looks_like_question(block.content):
                continue
            flush()
            question = _strip_question_label(block.content)
            heading_path = block.heading_path
            remember_source(block)
            continue

        orphan_lines: list[str] = []
        for line in block.content.splitlines():
            normalized = line.strip()
            if not normalized:
                continue

            question_match = _FAQ_QUESTION_LINE.match(normalized)
            if question_match is not None:
                flush()
                question = question_match.group(1).strip()
                if not question:
                    raise ValueError(f"FAQ block {block.ordinal} has an empty question")
                heading_path = block.heading_path
                remember_source(block)
                continue

            answer_match = _FAQ_ANSWER_LINE.match(normalized)
            if answer_match is not None:
                if question is None:
                    raise ValueError(f"FAQ answer at block {block.ordinal} has no question")
                answer = answer_match.group(1).strip()
                if answer:
                    answer_parts.append(answer)
                remember_source(block)
                continue

            keywords_match = _FAQ_KEYWORDS_LINE.match(normalized)
            if keywords_match is not None:
                if question is None:
                    raise ValueError(
                        f"FAQ keywords at block {block.ordinal} have no question"
                    )
                keywords.extend(_parse_keywords(keywords_match.group(1)))
                remember_source(block)
                continue

            if question is not None:
                # 支持Word中“问题标题 + 无A前缀答案段落”，也支持多行答案。
                answer_parts.append(normalized)
                remember_source(block)
            else:
                orphan_lines.append(normalized)

        if orphan_lines:
            # 同一个Markdown块可能先有简介再出现Q/A；只回退未消费的普通文本。
            fallback_blocks.append(
                block.model_copy(update={"content": "\n".join(orphan_lines)})
            )

    flush()
    return records, fallback_blocks


def _faq_record_drafts(
    record: _FaqRecord,
    *,
    record_index: int,
) -> tuple[ChunkDraft, ChunkDraft]:
    first = record.source_blocks[0]
    parent_id = f"faq-parent-{first.ordinal}-{record_index}"
    metadata = {
        **_group_metadata(record.source_blocks, strategy="faq"),
        "question": record.question,
        "keywords": list(record.keywords),
        "faq_index": record_index,
    }
    parent = ChunkDraft(
        local_id=parent_id,
        kind=ChunkKind.PARENT,
        content=f"问题：{record.question}\n答案：{record.answer}",
        source_block_ordinal=first.ordinal,
        metadata=metadata,
    )
    context_path = _faq_context_path(record)
    child_parts = [_heading_prefix(context_path, record.question)]
    if record.keywords:
        child_parts.append("关键词：" + "、".join(record.keywords))
    child_text = "\n".join(child_parts)
    child = ChunkDraft(
        local_id=f"faq-child-{first.ordinal}-{record_index}",
        kind=ChunkKind.CHILD,
        content=child_text,
        source_block_ordinal=first.ordinal,
        parent_local_id=parent_id,
        metadata={
            **metadata,
            "body_char_count": len(record.question),
        },
    )
    return parent, child


def _faq_context_path(record: _FaqRecord) -> tuple[str, ...]:
    """问题本身是Heading时去掉重复的末级标题，只保留所属章节。"""

    if not record.heading_path:
        return ()
    last = _strip_question_label(record.heading_path[-1]).rstrip("？?")
    question = record.question.rstrip("？?")
    if last == question:
        return record.heading_path[:-1]
    return record.heading_path


def _parse_keywords(value: str) -> list[str]:
    return [
        keyword.strip()
        for keyword in _FAQ_KEYWORD_SEPARATOR.split(value)
        if keyword.strip()
    ]


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


def _section_knowledge_type(
    heading_path: tuple[str, ...],
) -> DocumentKnowledgeType:
    heading = " / ".join(heading_path).casefold()
    if any(marker in heading for marker in _FAQ_SECTION_MARKERS):
        return DocumentKnowledgeType.FAQ
    if any(marker in heading for marker in _MANUAL_SECTION_MARKERS):
        return DocumentKnowledgeType.MANUAL
    if any(marker in heading for marker in _POLICY_SECTION_MARKERS):
        return DocumentKnowledgeType.POLICY
    return DocumentKnowledgeType.GENERIC


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
