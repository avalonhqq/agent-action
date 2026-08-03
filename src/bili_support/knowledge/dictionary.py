"""生产词典管理使用的稳定枚举与Jieba发布制品生成规则。"""

from __future__ import annotations

import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from bili_support.intent.types import BusinessDomain


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


class PublishedDictionaryEntry(BaseModel):
    """随发布版本冻结的规范词、别名和运营元数据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    term: str = Field(min_length=1, max_length=100)
    aliases: tuple[str, ...] = Field(default=(), max_length=20)
    business_domain: BusinessDomain
    term_type: DictionaryTermType
    frequency: int = Field(ge=1, le=100_000_000)


def render_dictionary_manifest(
    entries: tuple[PublishedDictionaryEntry, ...],
) -> str:
    """生成确定性JSON快照，避免运行时读取尚未发布的approved词。"""

    ordered = sorted(
        entries,
        key=lambda item: (item.business_domain.value, item.term.casefold()),
    )
    return json.dumps(
        [item.model_dump(mode="json") for item in ordered],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def parse_dictionary_manifest(value: str) -> tuple[PublishedDictionaryEntry, ...]:
    """读取已发布快照；数据库内容损坏时立即失败，不静默扩大覆盖范围。"""

    raw = json.loads(value)
    if not isinstance(raw, list):
        raise ValueError("dictionary manifest must be a JSON list")
    return tuple(PublishedDictionaryEntry.model_validate(item) for item in raw)


def match_published_terms(
    text: str,
    entries: tuple[PublishedDictionaryEntry, ...],
) -> tuple[str, ...]:
    """把文本中的规范词或别名稳定映射为规范词，供ES精确字段使用。"""

    normalized = text.casefold()
    matched = [
        entry.term
        for entry in entries
        if any(
            surface.casefold() in normalized
            for surface in (entry.term, *entry.aliases)
        )
    ]
    return tuple(dict.fromkeys(matched))


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
