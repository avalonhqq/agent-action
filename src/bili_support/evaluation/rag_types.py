"""第8周8C：RAG生成评估的固定数据、失败分类和报告契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bili_support.knowledge.grounded_answer import GroundedAnswer


class RagExpectedDecision(StrEnum):
    """策略期望：有据回答、补充信息或拒绝无依据回答。"""

    ANSWER = "answer"
    CLARIFY = "clarify"
    REFUSE = "refuse"


class RagEvidence(BaseModel):
    """Golden Case内稳定的证据，不依赖数据库UUID。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    content: str = Field(min_length=1)


class RagPrediction(BaseModel):
    """模型/固定重放统一输出；非answer决策不得伪造GroundedAnswer。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: RagExpectedDecision
    grounded_answer: GroundedAnswer | None = None
    retrieval_error_code: str | None = None
    generation_error_code: str | None = None
    judge_uncertain: bool = False

    @model_validator(mode="after")
    def answer_contract(self) -> Self:
        if (self.decision is RagExpectedDecision.ANSWER) != (
            self.grounded_answer is not None
        ):
            raise ValueError("only answer predictions require grounded_answer")
        return self


class RagEvaluationCase(BaseModel):
    """一条覆盖输入、证据、预期与可选固定预测的JSONL样本。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    question: str = Field(min_length=1, max_length=2000)
    evidence: tuple[RagEvidence, ...] = Field(default=(), max_length=10)
    expected_decision: RagExpectedDecision
    expected_evidence_ids: tuple[str, ...] = ()
    required_answer_terms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    replay_prediction: RagPrediction

    @model_validator(mode="after")
    def case_contract(self) -> Self:
        allowed = {item.evidence_id for item in self.evidence}
        if not set(self.expected_evidence_ids).issubset(allowed):
            raise ValueError("expected evidence IDs must exist in case evidence")
        if self.expected_decision is RagExpectedDecision.ANSWER and not self.evidence:
            raise ValueError("answer cases require evidence")
        if self.expected_decision is not RagExpectedDecision.ANSWER and (
            self.expected_evidence_ids or self.required_answer_terms
        ):
            raise ValueError("non-answer cases cannot require answer evidence or terms")
        return self


class RagFailureKind(StrEnum):
    """报告必须区分链路阶段，不能只给一个笼统失败率。"""

    DECISION_MISMATCH = "decision_mismatch"
    RETRIEVAL_FAILURE = "retrieval_failure"
    GENERATION_FAILURE = "generation_failure"
    CITATION_FAILURE = "citation_failure"
    FAITHFULNESS_FAILURE = "faithfulness_failure"
    ANSWER_RELEVANCY_FAILURE = "answer_relevancy_failure"
    INCOMPLETE_ANSWER = "incomplete_answer"
    JUDGE_UNCERTAIN = "judge_uncertain"


class RagCaseResult(BaseModel):
    """逐样本指标与失败原因，方便直接复盘而非只看均值。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    expected_decision: RagExpectedDecision
    actual_decision: RagExpectedDecision
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevancy: float = Field(ge=0.0, le=1.0)
    citation_precision: float = Field(ge=0.0, le=1.0)
    citation_recall: float = Field(ge=0.0, le=1.0)
    failures: tuple[RagFailureKind, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


class RagEvaluationMetrics(BaseModel):
    """第8周核心生成质量指标。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_accuracy: float = Field(ge=0.0, le=1.0)
    faithfulness: float = Field(ge=0.0, le=1.0)
    answer_relevancy: float = Field(ge=0.0, le=1.0)
    citation_precision: float = Field(ge=0.0, le=1.0)
    citation_recall: float = Field(ge=0.0, le=1.0)
    pass_rate: float = Field(ge=0.0, le=1.0)
    case_count: int = Field(ge=1)


class RagEvaluationReport(BaseModel):
    """可输出JSON和Markdown的可回放评估报告。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    run_mode: str
    metrics: RagEvaluationMetrics
    cases: tuple[RagCaseResult, ...]
