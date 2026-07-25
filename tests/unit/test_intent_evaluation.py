from collections import Counter
from pathlib import Path

import pytest

from bili_support.core.exceptions import ErrorCode
from bili_support.evaluation.intent_data import load_intent_evaluation_cases
from bili_support.evaluation.intent_metrics import (
    calculate_intent_metrics,
    evaluate_intent_case,
)
from bili_support.evaluation.intent_runner import ModelEvaluationAdapter
from bili_support.evaluation.intent_types import (
    EvaluationStrategy,
    IntentEvaluationPrediction,
)
from bili_support.intent.types import (
    DecisionSource,
    IntentDecision,
    IntentRoute,
    Sentiment,
    SubIntent,
)
from bili_support.llm.errors import LLMResponseError

DATASET = Path("data/evaluation/intent_dev_v1.jsonl")


class _FailingClassifier:
    async def classify(self, question: str) -> None:
        raise LLMResponseError


def test_fixed_intent_dataset_has_planned_route_distribution() -> None:
    cases = load_intent_evaluation_cases(DATASET)

    assert len(cases) == 48
    assert Counter(case.expected.route for case in cases) == {
        IntentRoute.SUPPORTED: 24,
        IntentRoute.CHITCHAT: 8,
        IntentRoute.OUT_OF_DOMAIN: 8,
        IntentRoute.UNSAFE: 8,
    }


def test_perfect_predictions_produce_perfect_semantic_metrics() -> None:
    cases = load_intent_evaluation_cases(DATASET)
    evaluations = []
    for case in cases:
        decision = IntentDecision(
            route=case.expected.route,
            intents=tuple(
                SubIntent(
                    domain=item.domain,
                    action=item.action,
                    confidence=1.0,
                )
                for item in case.expected.intents
            ),
            entities=(),
            sentiment=Sentiment.NEUTRAL,
            risk=case.expected.risk,
            confidence=1.0,
            needs_clarification=case.expected.needs_clarification,
            clarification_question=(
                "请补充处理该诉求所需的信息。"
                if case.expected.needs_clarification
                else None
            ),
            source=DecisionSource.MODEL,
        )
        evaluations.append(
            evaluate_intent_case(
                case,
                IntentEvaluationPrediction(decision=decision),
            )
        )

    metrics = calculate_intent_metrics(evaluations)

    assert metrics.route_macro_f1 == 1.0
    assert metrics.sub_intent_micro_f1 == 1.0
    assert metrics.sub_intent_exact_match == 1.0
    assert metrics.false_rejection_rate == 0.0
    assert metrics.high_risk_miss_rate == 0.0
    assert metrics.clarification.f1 == 1.0
    assert metrics.structured_failure_rate == 0.0


@pytest.mark.asyncio
async def test_model_provider_failure_is_recorded_per_case() -> None:
    adapter = ModelEvaluationAdapter(
        strategy=EvaluationStrategy.TUNED_V3,
        prompt_version=3,
        classifier=_FailingClassifier(),  # type: ignore[arg-type]
    )

    prediction = await adapter.predict("测试模型失败")

    assert prediction.decision is None
    assert prediction.error_code is ErrorCode.MODEL_BAD_RESPONSE
