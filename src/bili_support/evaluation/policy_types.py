"""第7周7D检索策略评估的逐样本结果与聚合指标契约。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bili_support.evaluation.retrieval_types import RetrievalEvaluationCase
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.retrieval_policy import RetrievalDecisionKind
from bili_support.knowledge.tokenizers import BM25TokenizerKind


class PolicyCaseResult(BaseModel):
    """一条问题经过线上同款策略后的可回放结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: RetrievalEvaluationCase
    expected_decision: RetrievalDecisionKind
    actual_decision: RetrievalDecisionKind | None = None
    policy_id: str | None = None
    reason_code: str | None = None
    score_kind: str | None = None
    score: float | None = None
    evidence_count: int = Field(default=0, ge=0)
    coverage_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    supplemental_query_used: bool = False
    latency_ms: float = Field(ge=0.0)
    error_code: str | None = None

    @property
    def passed(self) -> bool:
        """执行成功且策略动作与金标准一致才算通过。"""

        return self.error_code is None and self.actual_decision is self.expected_decision


class PolicyEvaluationMetrics(BaseModel):
    """业务门禁指标；重点观察错误回答，而不是只观察召回。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_accuracy: float = Field(ge=0.0, le=1.0)
    answer_precision: float = Field(ge=0.0, le=1.0)
    false_answer_rate: float = Field(ge=0.0, le=1.0)
    refusal_recall: float = Field(ge=0.0, le=1.0)
    mean_entity_coverage: float = Field(ge=0.0, le=1.0)
    supplemental_query_rate: float = Field(ge=0.0, le=1.0)
    execution_failure_rate: float = Field(ge=0.0, le=1.0)
    latency_p50_ms: float = Field(ge=0.0)
    latency_p95_ms: float = Field(ge=0.0)


class PolicyEvaluationReport(BaseModel):
    """固定数据集、运行模式、指标和样本结果组成的完整报告。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    retrieval_mode: RetrievalMode
    bm25_tokenizer: BM25TokenizerKind | None = None
    case_count: int = Field(ge=1)
    metrics: PolicyEvaluationMetrics
    cases: tuple[PolicyCaseResult, ...]
