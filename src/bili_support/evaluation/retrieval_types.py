"""第六周6D检索评估的固定数据、逐样本结果和聚合报告契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.reranking import RerankErrorCode
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.tokenizers import BM25TokenizerKind


class RelevantParent(BaseModel):
    """一个稳定的相关Parent金标准，不依赖不同环境随机生成的数据库UUID。

    ``document_title`` 可用于限定来源文档；``content_contains`` 中的全部文本必须同时
    出现在Parent正文中。评估集因此可以在重新导入文档后继续使用。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    relevance_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    document_title: str | None = Field(default=None, min_length=1, max_length=200)
    content_contains: tuple[str, ...] = Field(min_length=1, max_length=10)

    @field_validator("document_title")
    @classmethod
    def normalize_optional_title(cls, value: str | None) -> str | None:
        """清理可选标题，并拒绝只包含空白的标题。"""

        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("relevant parent document title must not be blank")
        return normalized

    @field_validator("content_contains")
    @classmethod
    def normalize_content_markers(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """去重并清理正文锚点，防止空锚点匹配所有Parent。"""

        normalized = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item or len(item) > 200 for item in normalized):
            raise ValueError("content markers must contain 1-200 characters")
        return normalized


class RetrievalEvaluationCase(BaseModel):
    """JSONL中的一条检索问题及其期望Parent集合。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    question: str = Field(min_length=1, max_length=2000)
    business_domain: BusinessDomain
    allowed_scopes: tuple[str, ...] = Field(
        default=("public",),
        min_length=1,
        max_length=32,
    )
    relevant_parents: tuple[RelevantParent, ...] = Field(default=(), max_length=5)
    expect_empty: bool = False
    tags: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("retrieval question must not be blank")
        return normalized

    @field_validator("allowed_scopes", "tags")
    @classmethod
    def normalize_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item or len(item) > 64 for item in normalized):
            raise ValueError("retrieval evaluation labels must contain 1-64 characters")
        return normalized

    @model_validator(mode="after")
    def positive_and_negative_contract(self) -> Self:
        """正例必须有相关Parent，负例必须显式声明空结果，二者不能混用。"""

        if self.expect_empty == bool(self.relevant_parents):
            raise ValueError(
                "case must define relevant_parents or expect_empty=true, but not both"
            )
        relevance_ids = [item.relevance_id for item in self.relevant_parents]
        if len(relevance_ids) != len(set(relevance_ids)):
            raise ValueError("relevance_id must be unique inside one case")
        return self


class RetrievedParent(BaseModel):
    """从在线检索服务归一化出的Parent候选。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent_chunk_id: str
    document_title: str
    content: str
    score: float
    rank: int = Field(ge=1)


class RetrievalFailureKind(StrEnum):
    """失败分类用于区分召回问题、负例误召回和基础设施故障。"""

    RELEVANT_PARENT_MISSED = "relevant_parent_missed"
    UNEXPECTED_PARENT = "unexpected_parent"
    EXECUTION_ERROR = "execution_error"


class RetrievalCaseResult(BaseModel):
    """单条样本的候选、指标和失败原因。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: RetrievalEvaluationCase
    parents: tuple[RetrievedParent, ...]
    matched_relevance_ids_at_5: tuple[str, ...]
    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    reciprocal_rank: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    failures: tuple[RetrievalFailureKind, ...]
    error_code: str | None = None
    rerank_applied: bool = False
    rerank_degraded: bool = False
    rerank_error_code: RerankErrorCode | None = None

    @property
    def passed(self) -> bool:
        """没有任何业务或执行失败时，该样本通过。"""

        return not self.failures


class RetrievalEvaluationMetrics(BaseModel):
    """一次运行的核心检索质量与延迟指标。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_3: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    mrr_at_5: float = Field(ge=0.0, le=1.0)
    negative_accuracy: float = Field(ge=0.0, le=1.0)
    execution_failure_rate: float = Field(ge=0.0, le=1.0)
    rerank_degradation_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_p50_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)
    positive_case_count: int = Field(ge=0)
    negative_case_count: int = Field(ge=0)


class RetrievalEvaluationReport(BaseModel):
    """可同时序列化为JSON和Markdown的一次固定检索评估报告。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    case_count: int = Field(ge=1)
    retrieval_mode: RetrievalMode
    bm25_tokenizer: BM25TokenizerKind | None = None
    embedding_model: str | None
    rerank_enabled: bool = False
    rerank_provider: str | None = None
    rerank_model: str | None = None
    metrics: RetrievalEvaluationMetrics
    cases: tuple[RetrievalCaseResult, ...]
