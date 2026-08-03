"""8A Grounded Answer结构、引用集合和Prompt契约测试。"""

import json

import pytest
from pydantic import ValidationError

from bili_support.knowledge.grounded_answer import (
    GroundedAnswer,
    GroundedAnswerContractError,
    GroundedAnswerEvidenceError,
    validate_grounded_answer_evidence,
)
from bili_support.llm.prompts import create_default_prompt_registry
from bili_support.llm.structured import StructuredOutputError, StructuredOutputParser


def _valid_payload() -> dict[str, object]:
    return {
        "answer": "支付成功后通常立即生效[E1]；超过30分钟可提交订单核查[E2]。",
        "claims": [
            {
                "text": "支付成功后通常立即生效。",
                "evidence_ids": ["E1"],
            },
            {
                "text": "超过30分钟可提交订单核查。",
                "evidence_ids": ["E2"],
            },
        ],
        "used_evidence_ids": ["E1", "E2"],
        "completeness": "complete",
    }


def test_valid_grounded_answer_matches_allowed_evidence() -> None:
    answer = GroundedAnswer.model_validate(_valid_payload())

    validate_grounded_answer_evidence(
        answer,
        allowed_evidence_ids=("E1", "E2", "E3"),
    )

    assert answer.used_evidence_ids == ("E1", "E2")


@pytest.mark.parametrize(
    "field,value",
    [
        ("claims", [{"text": "无引用声明", "evidence_ids": []}]),
        ("used_evidence_ids", []),
    ],
)
def test_empty_references_fail_schema(field: str, value: object) -> None:
    payload = _valid_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate(payload)


def test_answer_claim_and_used_reference_sets_must_match() -> None:
    payload = _valid_payload()
    payload["answer"] = "支付成功后通常立即生效[E1]。"

    with pytest.raises(ValidationError):
        GroundedAnswer.model_validate(payload)


def test_unknown_evidence_id_fails_against_request_context() -> None:
    answer = GroundedAnswer.model_validate(_valid_payload())

    with pytest.raises(GroundedAnswerContractError) as exc_info:
        validate_grounded_answer_evidence(
            answer,
            allowed_evidence_ids=("E1",),
        )

    assert exc_info.value.code is GroundedAnswerEvidenceError.UNKNOWN_EVIDENCE_ID


def test_empty_allowed_evidence_cannot_generate_answer() -> None:
    answer = GroundedAnswer.model_validate(_valid_payload())

    with pytest.raises(GroundedAnswerContractError) as exc_info:
        validate_grounded_answer_evidence(answer, allowed_evidence_ids=())

    assert (
        exc_info.value.code
        is GroundedAnswerEvidenceError.EMPTY_ALLOWED_EVIDENCE
    )


def test_structured_parser_rejects_extra_contract_fields() -> None:
    payload = {**_valid_payload(), "analysis": "不应公开"}
    parsed = StructuredOutputParser(GroundedAnswer).parse(
        json.dumps(payload, ensure_ascii=False)
    )

    assert parsed.value is None
    assert parsed.error_code is StructuredOutputError.SCHEMA_VALIDATION_FAILED


def test_grounded_prompt_v4_is_versioned_and_keeps_evidence_out_of_system() -> None:
    registry = create_default_prompt_registry()
    prompt = registry.get("grounded_support", version=4)
    evidence = '{"evidence":[{"evidence_id":"E1","content":"测试证据"}]}'
    messages = prompt.render({"question": "多久生效？", "evidence": evidence})

    assert prompt.identifier == "grounded_support:v4"
    assert registry.get("grounded_support", version=2).identifier == "grounded_support:v2"
    assert registry.get("grounded_support", version=3).identifier == "grounded_support:v3"
    assert "claims" in messages[0].content
    assert "used_evidence_ids" in messages[0].content
    assert '"claims":[{"text":' in messages[0].content
    assert "四个顶层字段" in messages[0].content
    assert "最小证据集合" in messages[0].content
    assert evidence not in messages[0].content
    assert evidence in messages[1].content


def test_grounded_answer_json_schema_is_strict() -> None:
    schema = GroundedAnswer.model_json_schema()

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "answer",
        "claims",
        "used_evidence_ids",
        "completeness",
    }
