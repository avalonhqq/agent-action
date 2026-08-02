"""领域词候选、审核、发布和制品下载的API契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.dictionary import (
    DictionarySourceType,
    DictionaryTermStatus,
    DictionaryTermType,
    DictionaryVersionStatus,
)


class DictionaryTermCreate(BaseModel):
    """人工或受控上游提交的一条候选词。"""

    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=100)
    aliases: tuple[str, ...] = Field(default=(), max_length=20)
    business_domain: BusinessDomain
    term_type: DictionaryTermType = DictionaryTermType.OTHER
    frequency: int = Field(default=6000, ge=1, le=100_000_000)
    source_type: DictionarySourceType = DictionarySourceType.MANUAL
    source_reference: str | None = Field(default=None, max_length=255)

    @field_validator("term", "source_reference")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized or any(char in normalized for char in "\r\n\t"):
            raise ValueError("dictionary text must be non-blank and single-line")
        return normalized

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip().casefold() for item in value))
        if any(
            not item or len(item) > 100 or any(char in item for char in "\r\n\t")
            for item in normalized
        ):
            raise ValueError("dictionary aliases must be 1-100 single-line characters")
        return normalized


class MockDictionaryCandidatesRequest(BaseModel):
    """模拟客服日志或工单候选源；不会绕过candidate状态。"""

    model_config = ConfigDict(extra="forbid")

    terms: tuple[str, ...] = Field(min_length=1, max_length=100)
    business_domain: BusinessDomain
    source_type: DictionarySourceType
    source_reference: str = Field(min_length=1, max_length=255)

    @field_validator("source_type")
    @classmethod
    def source_must_be_mock(cls, value: DictionarySourceType) -> DictionarySourceType:
        if value not in {
            DictionarySourceType.CONVERSATION_LOG_MOCK,
            DictionarySourceType.TICKET_MOCK,
        }:
            raise ValueError("mock candidate endpoint only accepts mock sources")
        return value

    @field_validator("terms")
    @classmethod
    def normalize_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item or len(item) > 100 for item in normalized):
            raise ValueError("mock candidate terms must contain 1-100 characters")
        return normalized


class DictionaryTermReviewRequest(BaseModel):
    """人工审核动作；审核完成后词条不可原地修改。"""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    review_note: str = Field(min_length=1, max_length=500)


class DictionaryPublishRequest(BaseModel):
    """从全部approved词条生成一个不可变版本。"""

    model_config = ConfigDict(extra="forbid")

    release_note: str = Field(min_length=1, max_length=500)


class DictionaryTermView(BaseModel):
    """管理页面可展示的词条审计视图。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    term: str
    normalized_term: str
    aliases: list[str]
    business_domain: BusinessDomain
    term_type: DictionaryTermType
    frequency: int
    source_type: DictionarySourceType
    source_reference: str | None
    status: DictionaryTermStatus
    review_note: str | None
    created_by_user_id: str
    reviewed_by_user_id: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DictionaryVersionView(BaseModel):
    """发布版本元数据，不默认返回可能较大的完整词典文本。"""

    model_config = ConfigDict(from_attributes=True)

    id: str
    version_number: int
    status: DictionaryVersionStatus
    content_sha256: str
    term_count: int
    published_by_user_id: str
    release_note: str | None
    published_at: datetime


class DictionaryArtifactView(DictionaryVersionView):
    """供部署流水线下载的Jieba不可变制品。"""

    artifact_content: str
