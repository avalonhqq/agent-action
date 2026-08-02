"""第7周7C：Parent批量Rerank的领域契约和安全追踪类型。"""

from __future__ import annotations

from enum import StrEnum
from math import isfinite
from typing import Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RerankProviderKind(StrEnum):
    """可替换的Reranker实现；DISABLED不构造外部依赖。"""

    DISABLED = "disabled"
    MOCK = "mock"
    LLM = "llm"


class RerankErrorCode(StrEnum):
    """对API和页面稳定公开的降级原因，不包含Provider原始异常。"""

    PROVIDER_UNAVAILABLE = "rerank_provider_unavailable"
    TIMEOUT = "rerank_timeout"
    INVALID_RESPONSE = "rerank_invalid_response"
    INTERNAL_ERROR = "rerank_internal_error"


class RerankDocument(BaseModel):
    """一条已通过MySQL复核、准备交给Reranker的完整Parent。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_chunk_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    original_rank: int = Field(ge=1)


class RerankRequest(BaseModel):
    """一次批量重排请求；候选顺序就是RRF失败回退顺序。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    documents: tuple[RerankDocument, ...] = Field(min_length=1, max_length=20)
    top_n: int = Field(ge=1, le=20)
    model: str = Field(min_length=1, max_length=200)
    timeout_seconds: float = Field(gt=0)

    @model_validator(mode="after")
    def candidate_contract(self) -> Self:
        ids = [item.parent_chunk_id for item in self.documents]
        ranks = [item.original_rank for item in self.documents]
        if len(ids) != len(set(ids)):
            raise ValueError("rerank parent_chunk_id must be unique")
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("rerank original_rank must be contiguous")
        if self.top_n > len(self.documents):
            raise ValueError("rerank top_n cannot exceed document count")
        return self


class RerankItem(BaseModel):
    """Provider给一个Parent的相关性分数与新排名。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_chunk_id: str = Field(min_length=1)
    relevance_score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)

    @field_validator("relevance_score")
    @classmethod
    def score_must_be_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("rerank score must be finite")
        return value


class RerankBatchOutput(BaseModel):
    """用于LLM结构化输出的最小JSON契约。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[RerankItem, ...] = Field(min_length=1, max_length=20)


class RerankResponse(BaseModel):
    """Provider无关的批量结果；业务层仍会结合Request做ID集合复核。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[RerankItem, ...] = Field(min_length=1, max_length=20)
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=200)
    latency_ms: float = Field(ge=0)


class RerankTrace(BaseModel):
    """API、SSE、页面和评估共享的安全Rerank摘要。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool
    attempted: bool
    applied: bool
    degraded: bool
    provider: str | None = None
    model: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    returned_count: int = Field(default=0, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    error_code: RerankErrorCode | None = None


class RerankProviderError(RuntimeError):
    """Provider适配器只向业务层暴露稳定错误码。"""

    def __init__(self, code: RerankErrorCode) -> None:
        self.code = code
        super().__init__(code.value)


@runtime_checkable
class RerankProvider(Protocol):
    """Mock、LLM或未来CrossEncoder必须实现的最小批量能力。"""

    @property
    def name(self) -> str: ...

    async def rerank(self, request: RerankRequest) -> RerankResponse: ...


def validate_rerank_response(
    *,
    request: RerankRequest,
    response: RerankResponse,
) -> None:
    """确保Provider没有遗漏、重复、创建候选，也没有伪造不连续排名。"""

    expected_ids = {item.parent_chunk_id for item in request.documents}
    actual_ids = [item.parent_chunk_id for item in response.items]
    actual_ranks = [item.rank for item in response.items]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != expected_ids:
        raise RerankProviderError(RerankErrorCode.INVALID_RESPONSE)
    if sorted(actual_ranks) != list(range(1, len(actual_ranks) + 1)):
        raise RerankProviderError(RerankErrorCode.INVALID_RESPONSE)
    ranked_scores = [
        item.relevance_score
        for item in sorted(response.items, key=lambda item: item.rank)
    ]
    if any(
        left < right
        for left, right in zip(ranked_scores, ranked_scores[1:], strict=False)
    ):
        raise RerankProviderError(RerankErrorCode.INVALID_RESPONSE)
