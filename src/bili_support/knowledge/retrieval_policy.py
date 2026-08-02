"""第7周7D：版本化检索预算、分数阈值与回答决策。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bili_support.intent.types import BusinessDomain, IntentAction
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.schemas.knowledge import KnowledgeRetrievalView


class RetrievalDecisionKind(StrEnum):
    """检索完成后的确定性执行动作。"""

    ANSWER = "answer"
    CLARIFY = "clarify"
    REFUSE = "refuse"


class RetrievalScoreKind(StrEnum):
    """不同检索阶段的分数空间禁止共用阈值。"""

    VECTOR_COSINE = "vector_cosine"
    BM25_OKAPI = "bm25_okapi"
    HYBRID_RRF = "hybrid_rrf"
    RERANK = "rerank"


class ThresholdBand(BaseModel):
    """回答线必须高于或等于澄清线。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: float = Field(ge=0)
    clarify: float = Field(ge=0)

    @model_validator(mode="after")
    def answer_must_not_be_lower(self) -> Self:
        if self.answer < self.clarify:
            raise ValueError("answer threshold must be at least clarify threshold")
        return self


class RetrievalPolicy(BaseModel):
    """一个可回放的业务域/动作检索策略。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{2,63}$")
    version: int = Field(ge=1)
    business_domain: BusinessDomain | None = None
    action: IntentAction | None = None
    child_top_k: int = Field(ge=1, le=100)
    parent_candidate_k: int = Field(ge=1, le=20)
    parent_top_k: int = Field(ge=1, le=20)
    rerank_enabled: bool = False
    supplemental_query_limit: int = Field(default=1, ge=0, le=1)
    minimum_evidence_count: int = Field(default=1, ge=1, le=20)
    thresholds: dict[RetrievalScoreKind, ThresholdBand]

    @model_validator(mode="after")
    def candidate_budget_must_cover_final_budget(self) -> Self:
        if self.parent_candidate_k < self.parent_top_k:
            raise ValueError("parent candidate budget must cover final parent budget")
        return self


class RetrievalQualityDecision(BaseModel):
    """策略层输出；Conversation据此回答、澄清或拒答。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: RetrievalDecisionKind
    policy_id: str
    policy_version: int
    score_kind: RetrievalScoreKind | None = None
    score: float | None = None
    evidence_count: int = Field(ge=0)
    reason_code: str = Field(min_length=1, max_length=64)
    clarification_question: str | None = Field(default=None, max_length=300)


class RetrievalPolicyTrace(BaseModel):
    """公开Trace不包含完整Intent实体和内部阈值表。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: str
    policy_version: int
    decision: RetrievalDecisionKind
    reason_code: str
    score_kind: RetrievalScoreKind | None = None
    score: float | None = None


class RetrievalPolicyRegistry:
    """按业务域+动作、业务域默认、全局默认的顺序选择策略。"""

    def __init__(self, policies: tuple[RetrievalPolicy, ...]) -> None:
        if not policies:
            raise ValueError("retrieval policy registry cannot be empty")
        keys = [(item.business_domain, item.action) for item in policies]
        if len(keys) != len(set(keys)):
            raise ValueError("retrieval policy keys must be unique")
        self._policies = policies

    def select(
            self,
            *,
            domain: BusinessDomain,
            actions: tuple[IntentAction, ...],
    ) -> RetrievalPolicy:
        for action in actions:
            exact = self._find(domain, action)
            if exact is not None:
                return exact
        return self._find(domain, None) or self._find(None, None) or self._policies[-1]

    def _find(
            self,
            domain: BusinessDomain | None,
            action: IntentAction | None,
    ) -> RetrievalPolicy | None:
        return next(
            (
                item
                for item in self._policies
                if item.business_domain is domain and item.action is action
            ),
            None,
        )


def create_default_retrieval_policy_registry() -> RetrievalPolicyRegistry:
    """v2阈值来自7A-2两种分词对照；只对Hybrid RRF声明已校准区间。"""

    # Jieba使域内负例由0.028372升至0.029116；v2把澄清线提升到0.0295，
    # 同时保留0.030回答线，8条正例最低0.032266，仍有明确安全间隔。
    hybrid = ThresholdBand(answer=0.030, clarify=0.0295)
    conservative = {
        RetrievalScoreKind.HYBRID_RRF: hybrid,
        RetrievalScoreKind.VECTOR_COSINE: ThresholdBand(answer=0.75, clarify=0.60),
        RetrievalScoreKind.BM25_OKAPI: ThresholdBand(answer=2.0, clarify=1.0),
        RetrievalScoreKind.RERANK: ThresholdBand(answer=0.75, clarify=0.50),
    }
    return RetrievalPolicyRegistry(
        (
            RetrievalPolicy(
                policy_id="membership-query-v2",
                version=2,
                business_domain=BusinessDomain.MEMBERSHIP,
                action=IntentAction.QUERY,
                child_top_k=20,
                parent_candidate_k=10,
                parent_top_k=5,
                thresholds=conservative,
            ),
            RetrievalPolicy(
                policy_id="global-conservative-v2",
                version=2,
                child_top_k=20,
                parent_candidate_k=10,
                parent_top_k=5,
                thresholds=conservative,
            ),
        )
    )


def score_retrieval_view(
        view: KnowledgeRetrievalView,
) -> tuple[RetrievalScoreKind | None, float | None]:
    """选择本次真正生效阶段的Top-1分数，不跨空间归一化。"""

    if not view.parents:
        return None, None
    first = view.parents[0]
    if view.reranking.applied and first.rerank_score is not None:
        return RetrievalScoreKind.RERANK, first.rerank_score
    kind = {
        RetrievalMode.VECTOR: RetrievalScoreKind.VECTOR_COSINE,
        RetrievalMode.BM25: RetrievalScoreKind.BM25_OKAPI,
        RetrievalMode.HYBRID: RetrievalScoreKind.HYBRID_RRF,
    }[view.retrieval_mode]
    return kind, first.best_child_score


def decide_retrieval_quality(
        *,
        policy: RetrievalPolicy,
        score_kind: RetrievalScoreKind | None,
        score: float | None,
        evidence_count: int,
        missing_entities: tuple[str, ...],
) -> RetrievalQualityDecision:
    """先检查证据与覆盖，再按同分数空间阈值做确定性决策。"""

    if evidence_count < policy.minimum_evidence_count or score is None:
        return RetrievalQualityDecision(
            kind=RetrievalDecisionKind.REFUSE,
            reason_code="no_evidence",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            score_kind=score_kind,
            score=score,
            evidence_count=evidence_count,
        )
    if missing_entities:
        names = "、".join(missing_entities)
        return RetrievalQualityDecision(
            kind=RetrievalDecisionKind.CLARIFY,
            reason_code="missing_entity_coverage",
            clarification_question=f"当前资料尚未覆盖：{names}。请确认要重点了解哪一项？",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            score_kind=score_kind,
            score=score,
            evidence_count=evidence_count,
        )
    band = policy.thresholds.get(score_kind) if score_kind is not None else None
    if band is None or score < band.clarify:
        return RetrievalQualityDecision(
            kind=RetrievalDecisionKind.REFUSE,
            reason_code="low_quality",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            score_kind=score_kind,
            score=score,
            evidence_count=evidence_count,
        )
    if score < band.answer:
        return RetrievalQualityDecision(
            kind=RetrievalDecisionKind.CLARIFY,
            reason_code="weak_evidence",
            clarification_question="当前证据相关性有限，请补充更具体的产品、套餐或问题现象。",
            policy_id=policy.policy_id,
            policy_version=policy.version,
            score_kind=score_kind,
            score=score,
            evidence_count=evidence_count,
        )
    return RetrievalQualityDecision(
        kind=RetrievalDecisionKind.ANSWER,
        reason_code="quality_accepted",
        policy_id=policy.policy_id,
        policy_version=policy.version,
        score_kind=score_kind,
        score=score,
        evidence_count=evidence_count,
    )
