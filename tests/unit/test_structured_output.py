"""Tests for strict structured-output parsing and degradation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from bili_support.llm.structured import (
    StructuredOutputError,
    StructuredOutputParser,
)


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["membership", "technical"]
    confidence: float


def test_structured_parser_returns_typed_value() -> None:
    parser = StructuredOutputParser(IntentDecision)
    result = parser.parse(
        '{"intent":"membership","confidence":0.92}'
    )
    specification = parser.specification("intent_decision")

    assert result.error_code is None
    assert result.value == IntentDecision(intent="membership", confidence=0.92)
    assert specification.name == "intent_decision"
    assert specification.schema_definition["type"] == "object"


def test_structured_parser_degrades_invalid_json_to_reason_code() -> None:
    result = StructuredOutputParser(IntentDecision).parse("not-json")

    assert result.value is None
    assert result.error_code is StructuredOutputError.INVALID_JSON


def test_structured_parser_degrades_schema_failure_without_raw_content() -> None:
    secret = "secret-value-must-not-be-copied"
    result = StructuredOutputParser(IntentDecision).parse(
        f'{{"intent":"unknown","confidence":0.2,"secret":"{secret}"}}'
    )

    assert result.value is None
    assert result.error_code is StructuredOutputError.SCHEMA_VALIDATION_FAILED
    assert secret not in result.model_dump_json()
