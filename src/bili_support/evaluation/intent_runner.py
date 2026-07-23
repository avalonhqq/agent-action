"""在固定数据集上批量运行模型与混合意图策略。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from bili_support.evaluation.intent_metrics import (
    calculate_intent_metrics,
    evaluate_intent_case,
)
from bili_support.evaluation.intent_types import (
    EvaluationStrategy,
    IntentEvaluationCase,
    IntentEvaluationPrediction,
    IntentEvaluationReport,
    StrategyEvaluationReport,
)
from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.hybrid import HybridIntentClassifier
from bili_support.intent.types import DecisionSource
from bili_support.llm.structured import StructuredOutputError


class IntentEvaluationAdapter(Protocol):
    """把不同分类器统一为评估所需的预测接口。"""

    strategy: EvaluationStrategy
    prompt_version: int
    rules_enabled: bool

    async def predict(self, question: str) -> IntentEvaluationPrediction: ...


class ModelEvaluationAdapter:
    """适配只使用模型的 Zero-shot/Few-shot 分类器。"""

    def __init__(
        self,
        *,
        strategy: EvaluationStrategy,
        prompt_version: int,
        classifier: IntentClassifier,
    ) -> None:
        self.strategy = strategy
        self.prompt_version = prompt_version
        self.rules_enabled = False
        self._classifier = classifier

    async def predict(self, question: str) -> IntentEvaluationPrediction:
        result = await self._classifier.classify(question)
        if result.value is not None:
            if result.value.source is not DecisionSource.MODEL:
                return IntentEvaluationPrediction(
                    error_code=StructuredOutputError.SCHEMA_VALIDATION_FAILED
                )
            return IntentEvaluationPrediction(decision=result.value)
        if result.error_code is None:
            raise AssertionError("model result must contain value or error_code")
        return IntentEvaluationPrediction(error_code=result.error_code)


class HybridEvaluationAdapter:
    """适配规则优先、模型兜底的混合分类器。"""

    def __init__(
        self,
        *,
        strategy: EvaluationStrategy,
        prompt_version: int,
        classifier: HybridIntentClassifier,
    ) -> None:
        self.strategy = strategy
        self.prompt_version = prompt_version
        self.rules_enabled = True
        self._classifier = classifier

    async def predict(self, question: str) -> IntentEvaluationPrediction:
        result = await self._classifier.classify(question)
        return IntentEvaluationPrediction(
            decision=result.decision,
            error_code=result.error_code,
            rule_id=result.rule_id,
        )


async def run_intent_evaluation(
    *,
    dataset_name: str,
    model: str,
    cases: Iterable[IntentEvaluationCase],
    adapters: Iterable[IntentEvaluationAdapter],
) -> IntentEvaluationReport:
    """按策略顺序运行同一批样本，保证实验输入完全一致。"""
    fixed_cases = tuple(cases)
    if not fixed_cases:
        raise ValueError("intent evaluation requires at least one case")

    strategy_reports: list[StrategyEvaluationReport] = []
    for adapter in adapters:
        case_results = []
        for case in fixed_cases:
            prediction = await adapter.predict(case.question)
            case_results.append(evaluate_intent_case(case, prediction))
        strategy_reports.append(
            StrategyEvaluationReport(
                strategy=adapter.strategy,
                prompt_version=adapter.prompt_version,
                rules_enabled=adapter.rules_enabled,
                metrics=calculate_intent_metrics(case_results),
                cases=tuple(case_results),
            )
        )
    if not strategy_reports:
        raise ValueError("intent evaluation requires at least one strategy")
    return IntentEvaluationReport(
        dataset=dataset_name,
        case_count=len(fixed_cases),
        model=model,
        strategies=tuple(strategy_reports),
    )
