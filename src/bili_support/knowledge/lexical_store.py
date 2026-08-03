"""Elasticsearch词法索引边界，隔离SDK与上层RRF候选契约。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LexicalRecord(BaseModel):
    """一条可写入Elasticsearch的Child及最小过滤元数据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=36)
    parent_chunk_id: str = Field(min_length=1, max_length=36)
    document_id: str = Field(min_length=1, max_length=36)
    version_id: str = Field(min_length=1, max_length=36)
    index_version_id: str = Field(min_length=1, max_length=36)
    owner_user_id: str = Field(min_length=1, max_length=36)
    document_title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    business_domain: str = Field(min_length=1, max_length=32)
    access_scope: tuple[str, ...] = Field(min_length=1, max_length=32)
    document_active: bool
    version_current: bool
    index_active: bool
    domain_terms: tuple[str, ...] = ()

    @field_validator("access_scope", "domain_terms")
    @classmethod
    def values_must_be_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip().casefold() for item in value))
        if any(not item or len(item) > 100 for item in normalized):
            raise ValueError("lexical list values must contain 1-100 characters")
        return normalized


class LexicalSearchQuery(BaseModel):
    """ES检索过滤仍来自MySQL活动索引事实，不能由客户端自由声明。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=20, ge=1, le=100)
    owner_user_id: str = Field(min_length=1, max_length=36)
    business_domain: str = Field(min_length=1, max_length=32)
    allowed_scopes: tuple[str, ...] = Field(min_length=1, max_length=32)
    domain_terms: tuple[str, ...] = Field(default=(), max_length=50)


class LexicalSearchHit(BaseModel):
    """Elasticsearch BM25命中，分数只在该通道内部比较。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    document_id: str
    version_id: str
    index_version_id: str
    score: float = Field(gt=0)


class LexicalRebuildResult(BaseModel):
    """一次全量活动Child重建和Alias切换结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    physical_index: str
    generation: str
    document_count: int = Field(ge=0)
    deduplicated: bool = False


@runtime_checkable
class LexicalStore(Protocol):
    async def ping(self) -> None: ...

    async def rebuild(
        self,
        *,
        generation: str,
        records: Sequence[LexicalRecord],
    ) -> LexicalRebuildResult: ...

    async def search(
        self,
        query: LexicalSearchQuery,
    ) -> tuple[LexicalSearchHit, ...]: ...

    async def aclose(self) -> None: ...
