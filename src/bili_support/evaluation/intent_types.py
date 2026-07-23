"""意图评估的数据契约：金标准、预测、逐样本结果和聚合报告。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bili_support.intent.types import (
    BusinessDomain,
    DecisionSource,
    IntentAction,
    IntentDecision,
    IntentRoute,
    RiskLevel,
)
from bili_support.llm.structured import StructuredOutputError


class EvaluationStrategy(StrEnum):
    """同一数据集上需要对照的四种分类策略。"""

    ZERO_SHOT_V1 = "zero_shot_v1"
    FEW_SHOT_V2 = "few_shot_v2"
    HYBRID_V1 = "hybrid_v1"
    HYBRID_V2 = "hybrid_v2"


class FailureCategory(StrEnum):
    """把失败拆到可采取行动的层级，供下一步 Prompt 调优使用。"""

    STRUCTURED_OUTPUT = "structured_output"
    ROUTE = "route"
    SUB_INTENT = "sub_intent"
    RISK = "risk"
    CLARIFICATION = "clarification"
    RULE_MISROUTE = "rule_misroute"


class ExpectedSubIntent(BaseModel):
    """金标准只保存稳定的业务域和动作，不保存主观置信度。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: BusinessDomain
    action: IntentAction


class ExpectedIntentOutcome(BaseModel):
    """一条问题的人工标注意图结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: IntentRoute
    intents: tuple[ExpectedSubIntent, ...] = ()
    risk: RiskLevel
    needs_clarification: bool

    @model_validator(mode="after")
    def validate_route_and_intents(self) -> Self:
        if self.route is IntentRoute.SUPPORTED and not self.intents:
            raise ValueError("supported evaluation outcome requires sub-intents")
        if self.route is not IntentRoute.SUPPORTED and self.intents:
            raise ValueError("non-supported evaluation outcome cannot contain sub-intents")
        if self.route is IntentRoute.UNSAFE and self.risk is RiskLevel.LOW:
            raise ValueError("unsafe evaluation outcome cannot have low risk")
        intent_keys = {(item.domain, item.action) for item in self.intents}
        if len(intent_keys) != len(self.intents):
            raise ValueError("evaluation outcome contains duplicate sub-intents")
        return self


class IntentEvaluationCase(BaseModel):
    """JSONL 中一条稳定、可解释的评估样本。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    question: str = Field(min_length=1, max_length=4000)
    expected: ExpectedIntentOutcome
    tags: tuple[str, ...] = Field(min_length=1)
    note: str = Field(min_length=1, max_length=500)

    @field_validator("question", "note")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("evaluation text must not be blank")
        return stripped

    @field_validator("tags")
    @classmethod
    def tags_must_be_unique_and_non_blank(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("evaluation tags must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("evaluation tags must be unique")
        return normalized


class IntentEvaluationPrediction(BaseModel):
    """把模型结果和混合结果归一为评估器可消费的预测。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: IntentDecision | None = None
    error_code: StructuredOutputError | None = None
    rule_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def exactly_one_prediction_result(self) -> Self:
        if (self.decision is None) == (self.error_code is None):
            raise ValueError("exactly one of decision or error_code must be set")
        if self.decision is None and self.rule_id is not None:
            raise ValueError("failed prediction cannot contain rule_id")
        if self.decision is not None:
            is_rule = self.decision.source is DecisionSource.RULE
            if is_rule != (self.rule_id is not None):
                raise ValueError("rule_id must be present exactly for rule predictions")
        return self


class IntentCaseEvaluation(BaseModel):
    """一个策略在单条样本上的预测与失败归因。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: IntentEvaluationCase
    prediction: IntentEvaluationPrediction
    failures: tuple[FailureCategory, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


class ClassMetrics(BaseModel):
    """单个路由标签的 Precision、Recall 和 F1。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    precision: float = Field(ge=0.0, le=1.0)
    recall: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    support: int = Field(ge=0)


class IntentEvaluationMetrics(BaseModel):
    """业务关心的意图评估指标。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_macro_f1: float = Field(ge=0.0, le=1.0)
    route_by_class: dict[IntentRoute, ClassMetrics]
    sub_intent_micro_f1: float = Field(ge=0.0, le=1.0)
    sub_intent_exact_match: float = Field(ge=0.0, le=1.0)
    rule_coverage: float = Field(ge=0.0, le=1.0)
    rule_precision: float = Field(ge=0.0, le=1.0)
    false_rejection_rate: float = Field(ge=0.0, le=1.0)
    high_risk_miss_rate: float = Field(ge=0.0, le=1.0)
    clarification: ClassMetrics
    structured_failure_rate: float = Field(ge=0.0, le=1.0)


class StrategyEvaluationReport(BaseModel):
    """一个策略的配置、指标和逐样本结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: EvaluationStrategy
    prompt_version: int = Field(gt=0)
    rules_enabled: bool
    metrics: IntentEvaluationMetrics
    cases: tuple[IntentCaseEvaluation, ...]


class IntentEvaluationReport(BaseModel):
    """一次批量评估的完整、可序列化结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    case_count: int = Field(gt=0)
    model: str
    strategies: tuple[StrategyEvaluationReport, ...]
