"""7D版本化策略选择和回答/澄清/拒答阈值测试。"""

from bili_support.intent.types import BusinessDomain, IntentAction
from bili_support.knowledge.retrieval_policy import (
    RetrievalDecisionKind,
    RetrievalScoreKind,
    create_default_retrieval_policy_registry,
    decide_retrieval_quality,
)


def _membership_policy():
    return create_default_retrieval_policy_registry().select(
        domain=BusinessDomain.MEMBERSHIP,
        actions=(IntentAction.QUERY,),
    )


def test_registry_selects_domain_action_policy_before_global_default() -> None:
    policy = _membership_policy()

    assert policy.policy_id == "membership-query-v2"
    assert policy.version == 2


def test_hybrid_threshold_separates_answer_clarify_and_refuse() -> None:
    policy = _membership_policy()

    answer = decide_retrieval_quality(
        policy=policy,
        score_kind=RetrievalScoreKind.HYBRID_RRF,
        score=0.032,
        evidence_count=3,
        missing_entities=(),
    )
    clarify = decide_retrieval_quality(
        policy=policy,
        score_kind=RetrievalScoreKind.HYBRID_RRF,
        score=0.0295,
        evidence_count=3,
        missing_entities=(),
    )
    refuse = decide_retrieval_quality(
        policy=policy,
        score_kind=RetrievalScoreKind.HYBRID_RRF,
        score=0.0283,
        evidence_count=3,
        missing_entities=(),
    )

    assert answer.kind is RetrievalDecisionKind.ANSWER
    assert clarify.kind is RetrievalDecisionKind.CLARIFY
    assert refuse.kind is RetrievalDecisionKind.REFUSE


def test_missing_entity_coverage_has_priority_over_high_score() -> None:
    decision = decide_retrieval_quality(
        policy=_membership_policy(),
        score_kind=RetrievalScoreKind.HYBRID_RRF,
        score=0.032,
        evidence_count=3,
        missing_entities=("年度套餐",),
    )

    assert decision.kind is RetrievalDecisionKind.CLARIFY
    assert decision.reason_code == "missing_entity_coverage"
    assert "年度套餐" in str(decision.clarification_question)
