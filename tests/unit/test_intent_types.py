"""Tests for the multi-label intent decision contract."""

import pytest
from pydantic import ValidationError

from bili_support.intent import (
    BusinessDomain,
    DecisionSource,
    EntityType,
    IntentAction,
    IntentDecision,
    IntentEntity,
    IntentRoute,
    RiskLevel,
    Sentiment,
    SubIntent,
)
from bili_support.llm import StructuredOutputError, StructuredOutputParser


def membership_cancel(*, confidence: float = 0.92) -> SubIntent:
    return SubIntent(
        domain=BusinessDomain.MEMBERSHIP,
        action=IntentAction.CANCEL,
        confidence=confidence,
    )


def test_supported_decision_accepts_one_intent() -> None:
    decision = IntentDecision(
        route=IntentRoute.SUPPORTED,
        intents=(membership_cancel(),),
        confidence=0.92,
        source=DecisionSource.MODEL,
    )

    assert decision.route is IntentRoute.SUPPORTED
    assert decision.intents == (membership_cancel(),)
    assert decision.sentiment is Sentiment.NEUTRAL
    assert decision.risk is RiskLevel.LOW


def test_supported_decision_preserves_compound_intents_and_entities() -> None:
    decision = IntentDecision(
        route=IntentRoute.SUPPORTED,
        intents=(
            membership_cancel(),
            SubIntent(
                domain=BusinessDomain.ORDER,
                action=IntentAction.REFUND,
                confidence=0.84,
            ),
        ),
        entities=(
            IntentEntity(
                type=EntityType.PRODUCT,
                raw_value="  大会员 ",
                normalized_value=" premium_membership ",
            ),
            IntentEntity(type=EntityType.TIME_RANGE, raw_value="上个月"),
        ),
        sentiment=Sentiment.ANXIOUS,
        risk=RiskLevel.MEDIUM,
        confidence=0.88,
        needs_clarification=True,
        clarification_question=" 请提供重复扣款的订单号。 ",
        source=DecisionSource.HYBRID,
    )

    assert len(decision.intents) == 2
    assert decision.entities[0].raw_value == "大会员"
    assert decision.entities[0].normalized_value == "premium_membership"
    assert decision.clarification_question == "请提供重复扣款的订单号。"


def test_supported_route_requires_at_least_one_intent() -> None:
    with pytest.raises(ValidationError, match="requires at least one sub-intent"):
        IntentDecision(
            route=IntentRoute.SUPPORTED,
            confidence=0.5,
            source=DecisionSource.RULE,
        )


@pytest.mark.parametrize(
    "route",
    [IntentRoute.OUT_OF_DOMAIN, IntentRoute.CHITCHAT, IntentRoute.UNSAFE],
)
def test_non_supported_routes_reject_business_intents(route: IntentRoute) -> None:
    with pytest.raises(ValidationError, match="must not contain sub-intents"):
        IntentDecision(
            route=route,
            intents=(membership_cancel(),),
            risk=RiskLevel.HIGH,
            confidence=0.8,
            source=DecisionSource.MODEL,
        )


def test_unsafe_route_rejects_low_risk() -> None:
    with pytest.raises(ValidationError, match="cannot have low risk"):
        IntentDecision(
            route=IntentRoute.UNSAFE,
            risk=RiskLevel.LOW,
            confidence=0.9,
            source=DecisionSource.HYBRID,
        )


def test_unsafe_route_accepts_high_risk_without_business_intents() -> None:
    decision = IntentDecision(
        route=IntentRoute.UNSAFE,
        risk=RiskLevel.HIGH,
        confidence=0.95,
        source=DecisionSource.HYBRID,
    )

    assert decision.intents == ()
    assert decision.risk is RiskLevel.HIGH


@pytest.mark.parametrize(
    ("needs_clarification", "question"),
    [(True, None), (True, "   "), (False, "请提供订单号。")],
)
def test_clarification_flag_and_question_must_be_consistent(
    needs_clarification: bool, question: str | None
) -> None:
    with pytest.raises(ValidationError):
        IntentDecision(
            route=IntentRoute.SUPPORTED,
            intents=(membership_cancel(),),
            confidence=0.7,
            needs_clarification=needs_clarification,
            clarification_question=question,
            source=DecisionSource.MODEL,
        )


def test_duplicate_domain_and_action_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate domain and action"):
        IntentDecision(
            route=IntentRoute.SUPPORTED,
            intents=(membership_cancel(), membership_cancel(confidence=0.6)),
            confidence=0.7,
            source=DecisionSource.MODEL,
        )


def test_unknown_fields_and_out_of_range_confidence_are_rejected() -> None:
    with pytest.raises(ValidationError):
        IntentDecision.model_validate(
            {
                "route": "supported",
                "intents": [
                    {
                        "domain": "membership",
                        "action": "cancel",
                        "confidence": 1.1,
                    }
                ],
                "confidence": 1.1,
                "source": "model",
                "invented_field": "must fail",
            }
        )


def test_entity_values_must_not_be_blank() -> None:
    with pytest.raises(ValidationError, match="raw_value must not be blank"):
        IntentEntity(type=EntityType.ORDER_ID, raw_value="   ")


def test_structured_parser_returns_typed_compound_decision() -> None:
    result = StructuredOutputParser(IntentDecision).parse(
        """{
            "route": "supported",
            "intents": [
                {"domain": "membership", "action": "cancel", "confidence": 0.92},
                {"domain": "order", "action": "refund", "confidence": 0.84}
            ],
            "entities": [],
            "sentiment": "anxious",
            "risk": "medium",
            "confidence": 0.88,
            "needs_clarification": true,
            "clarification_question": "请提供订单号。",
            "source": "model"
        }"""
    )

    assert result.error_code is None
    assert result.value is not None
    assert len(result.value.intents) == 2


def test_structured_parser_safely_degrades_invalid_json() -> None:
    result = StructuredOutputParser(IntentDecision).parse("not-json")

    assert result.value is None
    assert result.error_code is StructuredOutputError.INVALID_JSON


def test_structured_parser_safely_degrades_schema_failure() -> None:
    secret = "raw-model-output-must-not-leak"
    result = StructuredOutputParser(IntentDecision).parse(
        f'{{"route":"supported","confidence":0.8,"source":"model","secret":"{secret}"}}'
    )

    assert result.value is None
    assert result.error_code is StructuredOutputError.SCHEMA_VALIDATION_FAILED
    assert secret not in result.model_dump_json()


def test_json_schema_is_strict_and_exposes_confidence_range() -> None:
    schema = IntentDecision.model_json_schema()
    confidence_schema = schema["properties"]["confidence"]

    assert schema["additionalProperties"] is False
    assert confidence_schema["minimum"] == 0.0
    assert confidence_schema["maximum"] == 1.0
