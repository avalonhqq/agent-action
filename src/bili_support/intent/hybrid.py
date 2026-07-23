from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.rules import RuleIntentClassifier
from bili_support.intent.types import DecisionSource, IntentDecision
from bili_support.llm.structured import StructuredOutputError


class HybridIntentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: IntentDecision | None = None
    error_code: StructuredOutputError | None = None
    rule_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        # 成功决策和错误码必须恰好出现一个。
        if (self.decision is None) == (self.error_code is None):
            raise ValueError(
                "exactly one of decision or error_code must be set"
            )

        # 错误结果不是规则命中，不能携带规则编号。
        if self.decision is None:
            if self.rule_id is not None:
                raise ValueError(
                    "failed result must not contain rule_id"
                )
            return self

        is_rule_decision = self.decision.source is DecisionSource.RULE
        has_rule_id = self.rule_id is not None

        # 规则决策必须带 rule_id；模型决策不能伪造 rule_id。
        if is_rule_decision != has_rule_id:
            raise ValueError(
                "rule_id must be present exactly for rule decisions"
            )

        return self


class HybridIntentClassifier:
    def __init__(
        self,
        *,
        rule_classifier: RuleIntentClassifier,
        model_classifier: IntentClassifier,
    ) -> None:
        self._rule_classifier = rule_classifier
        self._model_classifier = model_classifier

    async def classify(self, question: str) -> HybridIntentResult:
        """优先使用高精度规则，规则弃权后再调用模型分类器。"""
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question must not be blank")
        if len(normalized_question) > 4000:
            raise ValueError("question must not exceed 4000 characters")

        # 规则命中后立即短路，既避免模型费用，也保证一次请求只有一个真实来源。
        rule_match = self._rule_classifier.match(normalized_question)
        if rule_match is not None:
            return HybridIntentResult(
                decision=rule_match.decision,
                rule_id=rule_match.rule_id,
            )
        model_result = await self._model_classifier.classify(normalized_question)
        if model_result.value is not None:
            model_decision = model_result.value
            # source 描述实际调用路径，不能信任模型自行声明 rule 或 hybrid。
            if model_decision.source is not DecisionSource.MODEL:
                return HybridIntentResult(
                    error_code=StructuredOutputError.SCHEMA_VALIDATION_FAILED
                )
            return HybridIntentResult(decision=model_decision)

        # StructuredOutputResult 已保证成功值和错误码恰好存在一个。
        error_code = model_result.error_code
        if error_code is None:
            raise AssertionError("model result must contain value or error_code")
        return HybridIntentResult(error_code=error_code)
