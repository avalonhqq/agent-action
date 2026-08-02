"""生产词典管理使用的稳定枚举与Jieba发布制品生成规则。"""

from __future__ import annotations

from enum import StrEnum


class DictionaryTermStatus(StrEnum):
    """候选词必须经过人工审核后才能进入发布版本。"""

    CANDIDATE = "candidate"
    APPROVED = "approved"
    REJECTED = "rejected"


class DictionaryTermType(StrEnum):
    """领域词的业务角色，用于运营筛选和后续差异化权重。"""

    PRODUCT = "product"
    FEATURE = "feature"
    ISSUE = "issue"
    ACTION = "action"
    ERROR_CODE = "error_code"
    OTHER = "other"


class DictionarySourceType(StrEnum):
    """词条候选来源；真实外部系统未接入的来源必须显式标记Mock。"""

    MANUAL = "manual"
    KNOWLEDGE_KEYWORD = "knowledge_keyword"
    PRODUCT_CATALOG = "product_catalog"
    CONVERSATION_LOG_MOCK = "conversation_log_mock"
    TICKET_MOCK = "ticket_mock"


class DictionaryVersionStatus(StrEnum):
    """同一时刻只有最新发布版本是active，旧版本保留用于回放。"""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


def render_jieba_dictionary(
    entries: tuple[tuple[str, tuple[str, ...], int], ...],
) -> str:
    """把审核词和别名去重为确定性Jieba文本，便于计算哈希和回滚。"""

    frequencies: dict[str, int] = {}
    for term, aliases, frequency in entries:
        for value in (term, *aliases):
            normalized = value.strip().casefold()
            if normalized:
                frequencies[normalized] = max(
                    frequency,
                    frequencies.get(normalized, 0),
                )
    return "".join(
        f"{term} {frequency} nz\n"
        for term, frequency in sorted(frequencies.items())
    )
