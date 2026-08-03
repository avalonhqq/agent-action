"""8B声明支持、数字事实和降级测试。"""

from bili_support.knowledge.claim_verification import (
    ClaimSupportStatus,
    EvidenceRecord,
    GroundedVerificationDecision,
    verify_grounded_answer,
)
from bili_support.knowledge.grounded_answer import GroundedAnswer


def _answer(claim: str, *, completeness: str = "complete") -> GroundedAnswer:
    return GroundedAnswer.model_validate(
        {
            "answer": f"{claim}[E1]",
            "claims": [{"text": claim, "evidence_ids": ["E1"]}],
            "used_evidence_ids": ["E1"],
            "completeness": completeness,
        }
    )


def test_supported_paraphrase_is_accepted() -> None:
    result = verify_grounded_answer(
        _answer("大会员在支付成功后立即生效。"),
        evidence=(EvidenceRecord(evidence_id="E1", content="支付成功后立即生效。"),),
    )

    assert result.decision is GroundedVerificationDecision.PASS
    assert result.claims[0].status is ClaimSupportStatus.SUPPORTED


def test_number_not_present_in_evidence_is_rejected() -> None:
    result = verify_grounded_answer(
        _answer("支付成功后10分钟生效。"),
        evidence=(EvidenceRecord(evidence_id="E1", content="支付成功后立即生效。"),),
    )

    assert result.decision is GroundedVerificationDecision.REJECT
    assert result.claims[0].reason_code == "numeric_fact_missing"


def test_partial_model_answer_is_not_directly_publishable() -> None:
    result = verify_grounded_answer(
        _answer("支付成功后立即生效。", completeness="partial"),
        evidence=(EvidenceRecord(evidence_id="E1", content="支付成功后立即生效。"),),
    )

    assert result.decision is GroundedVerificationDecision.DEGRADE


def test_missing_evidence_content_is_rejected() -> None:
    result = verify_grounded_answer(_answer("支持退款。"), evidence=())

    assert result.decision is GroundedVerificationDecision.REJECT
    assert result.claims[0].status is ClaimSupportStatus.UNSUPPORTED


def test_unrelated_negative_sentence_does_not_conflict_with_positive_claim() -> None:
    result = verify_grounded_answer(
        _answer("大会员在支付成功后立即生效。"),
        evidence=(
            EvidenceRecord(
                evidence_id="E1",
                content=(
                    "正常情况下支付成功后立即生效。若未显示请刷新；"
                    "超过30分钟仍未到账时提交订单人工核查。"
                ),
            ),
        ),
    )

    assert result.decision is GroundedVerificationDecision.PASS
    assert result.claims[0].status is ClaimSupportStatus.SUPPORTED


def test_not_immediately_displayed_does_not_negate_immediate_activation() -> None:
    result = verify_grounded_answer(
        _answer("大会员支付成功后通常立即生效。"),
        evidence=(
            EvidenceRecord(
                evidence_id="E1",
                content=(
                    "正常情况下，支付成功后会员状态会立即生效。"
                    "若未立即显示，可等待1～5分钟后重新登录。"
                ),
            ),
        ),
    )

    assert result.decision is GroundedVerificationDecision.PASS
    assert result.claims[0].status is ClaimSupportStatus.SUPPORTED


def test_same_topic_negation_is_still_a_conflict() -> None:
    result = verify_grounded_answer(
        _answer("成功开通后支持无理由退款。"),
        evidence=(
            EvidenceRecord(
                evidence_id="E1",
                content="成功开通后不支持无理由退款。",
            ),
        ),
    )

    assert result.decision is GroundedVerificationDecision.REJECT
    assert result.claims[0].status is ClaimSupportStatus.CONFLICT
