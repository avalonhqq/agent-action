"""从逐样本预测计算意图分类业务指标与失败类别。"""

from __future__ import annotations

from collections.abc import Iterable

from bili_support.evaluation.intent_types import (
    ClassMetrics,
    FailureCategory,
    IntentCaseEvaluation,
    IntentEvaluationCase,
    IntentEvaluationMetrics,
    IntentEvaluationPrediction,
)
from bili_support.intent.types import IntentRoute, RiskLevel


def evaluate_intent_case(
    case: IntentEvaluationCase,
    prediction: IntentEvaluationPrediction,
) -> IntentCaseEvaluation:
    """比较一条预测，并给出可用于失败分析的类别。"""
    if prediction.decision is None:
        return IntentCaseEvaluation(
            case=case,
            prediction=prediction,
            failures=(FailureCategory.STRUCTURED_OUTPUT,),
        )

    decision = prediction.decision
    failures: list[FailureCategory] = []
    expected_intents = _expected_intent_keys(case)
    predicted_intents = _predicted_intent_keys(prediction)
    if decision.route is not case.expected.route:
        failures.append(FailureCategory.ROUTE)
    if predicted_intents != expected_intents:
        failures.append(FailureCategory.SUB_INTENT)
    if decision.risk is not case.expected.risk:
        failures.append(FailureCategory.RISK)
    if decision.needs_clarification is not case.expected.needs_clarification:
        failures.append(FailureCategory.CLARIFICATION)
    if prediction.rule_id is not None and (
        decision.route is not case.expected.route
        or predicted_intents != expected_intents
    ):
        failures.append(FailureCategory.RULE_MISROUTE)
    return IntentCaseEvaluation(
        case=case,
        prediction=prediction,
        failures=tuple(failures),
    )


def calculate_intent_metrics(
    evaluations: Iterable[IntentCaseEvaluation],
) -> IntentEvaluationMetrics:
    """计算路由、子意图、规则、安全、澄清和结构失败指标。"""
    items = tuple(evaluations)
    if not items:
        raise ValueError("intent metrics require at least one evaluation")

    route_by_class = {
        route: _route_class_metrics(items, route)
        for route in IntentRoute
    }
    route_macro_f1 = sum(metric.f1 for metric in route_by_class.values()) / len(
        route_by_class
    )

    sub_intent_tp = 0
    sub_intent_fp = 0
    sub_intent_fn = 0
    supported_exact = 0
    supported_count = 0
    for item in items:
        expected = _expected_intent_keys(item.case)
        predicted = _predicted_intent_keys(item.prediction)
        sub_intent_tp += len(expected & predicted)
        sub_intent_fp += len(predicted - expected)
        sub_intent_fn += len(expected - predicted)
        if item.case.expected.route is IntentRoute.SUPPORTED:
            supported_count += 1
            supported_exact += int(expected == predicted)

    sub_intent_precision = _ratio(
        sub_intent_tp,
        sub_intent_tp + sub_intent_fp,
    )
    sub_intent_recall = _ratio(
        sub_intent_tp,
        sub_intent_tp + sub_intent_fn,
    )
    sub_intent_micro_f1 = _f1(sub_intent_precision, sub_intent_recall)

    rule_items = tuple(item for item in items if item.prediction.rule_id is not None)
    correct_rule_items = sum(
        1
        for item in rule_items
        if item.prediction.decision is not None
        and item.prediction.decision.route is item.case.expected.route
        and _predicted_intent_keys(item.prediction) == _expected_intent_keys(item.case)
    )

    supported_items = tuple(
        item for item in items if item.case.expected.route is IntentRoute.SUPPORTED
    )
    false_rejections = sum(
        1
        for item in supported_items
        if item.prediction.decision is None
        or item.prediction.decision.route is not IntentRoute.SUPPORTED
    )

    high_risk_items = tuple(
        item
        for item in items
        if item.case.expected.risk in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    )
    high_risk_misses = sum(
        1
        for item in high_risk_items
        if item.prediction.decision is None
        or item.prediction.decision.risk not in {RiskLevel.HIGH, RiskLevel.CRITICAL}
    )

    clarification = _clarification_metrics(items)
    structured_failures = sum(
        1 for item in items if item.prediction.decision is None
    )
    return IntentEvaluationMetrics(
        route_macro_f1=route_macro_f1,
        route_by_class=route_by_class,
        sub_intent_micro_f1=sub_intent_micro_f1,
        sub_intent_exact_match=_ratio(supported_exact, supported_count),
        rule_coverage=_ratio(len(rule_items), len(items)),
        rule_precision=_ratio(correct_rule_items, len(rule_items)),
        false_rejection_rate=_ratio(false_rejections, len(supported_items)),
        high_risk_miss_rate=_ratio(high_risk_misses, len(high_risk_items)),
        clarification=clarification,
        structured_failure_rate=_ratio(structured_failures, len(items)),
    )


def _route_class_metrics(
    items: tuple[IntentCaseEvaluation, ...],
    route: IntentRoute,
) -> ClassMetrics:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    support = 0
    for item in items:
        expected_positive = item.case.expected.route is route
        predicted_positive = (
            item.prediction.decision is not None
            and item.prediction.decision.route is route
        )
        support += int(expected_positive)
        true_positive += int(expected_positive and predicted_positive)
        false_positive += int(not expected_positive and predicted_positive)
        false_negative += int(expected_positive and not predicted_positive)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return ClassMetrics(
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        support=support,
    )


def _clarification_metrics(
    items: tuple[IntentCaseEvaluation, ...],
) -> ClassMetrics:
    true_positive = 0
    false_positive = 0
    false_negative = 0
    support = 0
    for item in items:
        expected_positive = item.case.expected.needs_clarification
        predicted_positive = (
            item.prediction.decision is not None
            and item.prediction.decision.needs_clarification
        )
        support += int(expected_positive)
        true_positive += int(expected_positive and predicted_positive)
        false_positive += int(not expected_positive and predicted_positive)
        false_negative += int(expected_positive and not predicted_positive)
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return ClassMetrics(
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        support=support,
    )


def _expected_intent_keys(
    case: IntentEvaluationCase,
) -> set[tuple[str, str]]:
    return {
        (item.domain.value, item.action.value)
        for item in case.expected.intents
    }


def _predicted_intent_keys(
    prediction: IntentEvaluationPrediction,
) -> set[tuple[str, str]]:
    if prediction.decision is None:
        return set()
    return {
        (item.domain.value, item.action.value)
        for item in prediction.decision.intents
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _f1(precision: float, recall: float) -> float:
    return (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
