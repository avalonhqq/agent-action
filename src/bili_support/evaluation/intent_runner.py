"""在固定数据集上批量运行模型与混合意图策略。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from bili_support.core.exceptions import AppError
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
from bili_support.intent.policies import HybridIntentPolicy
from bili_support.intent.rules import RuleIntentClassifier
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
        try:
            result = await self._classifier.classify(question)
        except AppError as exc:
            # 单条 Provider 故障必须留在该样本，不能让整批评估丢失进度。
            return IntentEvaluationPrediction(error_code=exc.code)
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
        try:
            result = await self._classifier.classify(question)
        except AppError as exc:
            # 规则未命中后的模型故障按样本记录，后续样本继续执行。
            return IntentEvaluationPrediction(error_code=exc.code)
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


def rescore_intent_evaluation_report(
    *,
    report: IntentEvaluationReport,
    cases: Iterable[IntentEvaluationCase],
) -> IntentEvaluationReport:
    """在不重复调用模型的情况下，使用修订后的金标准重新计算报告。"""
    revised_cases = tuple(cases)
    revised_by_id = {case.case_id: case for case in revised_cases}
    if len(revised_by_id) != len(revised_cases):
        raise ValueError("rescoring cases contain duplicate case_id")

    rescored_strategies: list[StrategyEvaluationReport] = []
    for strategy in report.strategies:
        predictions_by_id = {
            item.case.case_id: item.prediction
            for item in strategy.cases
        }
        if predictions_by_id.keys() != revised_by_id.keys():
            raise ValueError("rescoring cases must match report case_ids exactly")
        case_results = tuple(
            evaluate_intent_case(case, predictions_by_id[case.case_id])
            for case in revised_cases
        )
        rescored_strategies.append(
            StrategyEvaluationReport(
                strategy=strategy.strategy,
                prompt_version=strategy.prompt_version,
                rules_enabled=strategy.rules_enabled,
                metrics=calculate_intent_metrics(case_results),
                cases=case_results,
            )
        )
    return IntentEvaluationReport(
        dataset=report.dataset,
        case_count=len(revised_cases),
        model=report.model,
        strategies=tuple(rescored_strategies),
    )


def replay_hybrid_v3_report(
    *,
    model_report: IntentEvaluationReport,
    rule_classifier: RuleIntentClassifier,
    policy: HybridIntentPolicy,
) -> IntentEvaluationReport:
    """复用真实 v3 预测，离线重放前置规则和后置策略，不再次调用模型。"""
    if len(model_report.strategies) != 1:
        raise ValueError("hybrid replay requires exactly one model strategy")
    model_strategy = model_report.strategies[0]
    if model_strategy.strategy is not EvaluationStrategy.TUNED_V3:
        raise ValueError("hybrid v3 replay requires tuned_v3 predictions")

    case_results = []
    for item in model_strategy.cases:
        rule_match = rule_classifier.match(item.case.question)
        if rule_match is not None:
            prediction = IntentEvaluationPrediction(
                decision=rule_match.decision,
                rule_id=rule_match.rule_id,
            )
        elif item.prediction.decision is not None:
            policy_result = policy.apply(
                question=item.case.question,
                decision=item.prediction.decision,
            )
            prediction = IntentEvaluationPrediction(
                decision=policy_result.decision,
            )
        else:
            prediction = item.prediction
        case_results.append(evaluate_intent_case(item.case, prediction))

    hybrid_strategy = StrategyEvaluationReport(
        strategy=EvaluationStrategy.HYBRID_V3,
        prompt_version=model_strategy.prompt_version,
        rules_enabled=True,
        metrics=calculate_intent_metrics(case_results),
        cases=tuple(case_results),
    )
    return IntentEvaluationReport(
        dataset=model_report.dataset,
        case_count=model_report.case_count,
        model=model_report.model,
        strategies=(hybrid_strategy,),
    )
