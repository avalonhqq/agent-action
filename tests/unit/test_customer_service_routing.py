import pytest

from bili_support.intent.hybrid import HybridIntentResult
from bili_support.intent.types import (
    BusinessDomain,
    DecisionSource,
    IntentAction,
    IntentDecision,
    IntentRoute,
    RiskLevel,
    Sentiment,
    SubIntent,
)
from bili_support.llm.structured import StructuredOutputError
from bili_support.routing import CustomerServiceRouter, CustomerServiceTarget


class _Classifier:
    def __init__(self, result: HybridIntentResult) -> None:
        self._result = result

    async def classify(self, question: str) -> HybridIntentResult:
        return self._result


def _decision(
    *,
    route: IntentRoute,
    risk: RiskLevel = RiskLevel.LOW,
    domain: BusinessDomain | None = None,
    action: IntentAction | None = None,
    needs_clarification: bool = False,
) -> IntentDecision:
    intents = (
        (
            SubIntent(
                domain=domain,
                action=action,
                confidence=1.0,
            ),
        )
        if domain is not None and action is not None
        else ()
    )
    return IntentDecision(
        route=route,
        intents=intents,
        sentiment=Sentiment.NEUTRAL,
        risk=risk,
        confidence=1.0,
        needs_clarification=needs_clarification,
        clarification_question=(
            "请提供订单号。" if needs_clarification else None
        ),
        source=DecisionSource.MODEL,
    )


async def _route(decision: IntentDecision):
    router = CustomerServiceRouter(
        _Classifier(HybridIntentResult(decision=decision))  # type: ignore[arg-type]
    )
    return await router.route("测试问题")


@pytest.mark.asyncio
async def test_supported_request_routes_to_knowledge_mock() -> None:
    plan = await _route(
        _decision(
            route=IntentRoute.SUPPORTED,
            domain=BusinessDomain.MEMBERSHIP,
            action=IntentAction.QUERY,
        )
    )

    assert plan.summary.target is CustomerServiceTarget.KNOWLEDGE_MOCK
    assert plan.summary.mocked_downstream is True
    assert plan.use_chat_model is True


@pytest.mark.asyncio
async def test_clarification_short_circuits_answer_model() -> None:
    plan = await _route(
        _decision(
            route=IntentRoute.SUPPORTED,
            domain=BusinessDomain.ORDER,
            action=IntentAction.REFUND,
            needs_clarification=True,
        )
    )

    assert plan.summary.target is CustomerServiceTarget.CLARIFICATION
    assert plan.response_override == "请提供订单号。"
    assert plan.use_chat_model is False


@pytest.mark.asyncio
async def test_high_risk_supported_request_routes_to_human_review_mock() -> None:
    plan = await _route(
        _decision(
            route=IntentRoute.SUPPORTED,
            risk=RiskLevel.HIGH,
            domain=BusinessDomain.ACCOUNT,
            action=IntentAction.RECOVER,
        )
    )

    assert plan.summary.target is CustomerServiceTarget.HUMAN_REVIEW_MOCK
    assert plan.use_chat_model is False


@pytest.mark.asyncio
async def test_unsafe_request_returns_deterministic_safety_response() -> None:
    plan = await _route(
        _decision(
            route=IntentRoute.UNSAFE,
            risk=RiskLevel.CRITICAL,
        )
    )

    assert plan.summary.target is CustomerServiceTarget.SAFETY
    assert plan.summary.mocked_downstream is False
    assert plan.use_chat_model is False


@pytest.mark.asyncio
async def test_invalid_classifier_output_fails_closed_to_human_review() -> None:
    router = CustomerServiceRouter(
        _Classifier(  # type: ignore[arg-type]
            HybridIntentResult(
                error_code=StructuredOutputError.SCHEMA_VALIDATION_FAILED
            )
        )
    )

    plan = await router.route("无法分类的问题")

    assert plan.summary.target is CustomerServiceTarget.HUMAN_REVIEW_MOCK
    assert (
        plan.summary.classification_error
        == StructuredOutputError.SCHEMA_VALIDATION_FAILED.value
    )
    assert plan.use_chat_model is False
