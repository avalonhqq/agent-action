"""7D策略感知检索编排：预算、覆盖、一次补检索和质量决策。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from bili_support.core.security import UserContext
from bili_support.intent.types import (
    BusinessDomain,
    IntentAction,
    IntentEntity,
)
from bili_support.knowledge.coverage import (
    EvidenceCoverage,
    coverage_aware_parent_order,
    evaluate_coverage,
    extract_required_entities,
)
from bili_support.knowledge.query_expansion import build_supplemental_query
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.retrieval_policy import (
    RetrievalPolicyRegistry,
    RetrievalPolicyTrace,
    RetrievalQualityDecision,
    create_default_retrieval_policy_registry,
    decide_retrieval_quality,
    score_retrieval_view,
)
from bili_support.llm.types import ChatMessage
from bili_support.schemas.knowledge import (
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalView,
    RetrievalChildHitView,
    RetrievalParentView,
)
from bili_support.services.dictionary import KnowledgeDictionaryService
from bili_support.services.retrieval import KnowledgeRetrievalService


class PolicyRetrievalResult(BaseModel):
    """Conversation需要的可信证据、策略决策和公开覆盖摘要。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    view: KnowledgeRetrievalView
    quality: RetrievalQualityDecision
    policy_trace: RetrievalPolicyTrace
    coverage: EvidenceCoverage


class PolicyAwareKnowledgeRetriever:
    """包装基础召回器，不复制Vector/BM25/MySQL安全链路。"""

    def __init__(
        self,
        service: KnowledgeRetrievalService,
        *,
        registry: RetrievalPolicyRegistry | None = None,
        customer_rerank_enabled: bool = False,
        dictionary_service: KnowledgeDictionaryService | None = None,
    ) -> None:
        self._service = service
        self._registry = registry or create_default_retrieval_policy_registry()
        self._customer_rerank_enabled = customer_rerank_enabled
        self._dictionary_service = dictionary_service

    async def retrieve(
        self,
        *,
        actor: UserContext,
        question: str,
        history: tuple[ChatMessage, ...],
        domain: BusinessDomain,
        actions: tuple[IntentAction, ...],
        entities: tuple[IntentEntity, ...],
        mode: RetrievalMode,
    ) -> PolicyRetrievalResult:
        policy = self._registry.select(domain=domain, actions=actions)
        view = await self._service.retrieve(
            actor=actor,
            request=KnowledgeRetrievalRequest(
                query=question,
                business_domain=domain,
                allowed_scopes=("public",),
                history=history,
                retrieval_mode=mode,
                child_top_k=policy.child_top_k,
                parent_top_k=policy.parent_candidate_k,
                rerank_enabled=(
                    policy.rerank_enabled or self._customer_rerank_enabled
                ),
                rerank_candidate_k=policy.parent_candidate_k,
            ),
        )
        published_entries = (
            await self._dictionary_service.active_entries(
                business_domain=domain.value,
            )
            if self._dictionary_service is not None
            else ()
        )
        required = extract_required_entities(
            question=question,
            intent_entities=entities,
            published_entries=published_entries,
        )
        coverage = evaluate_coverage(entities=required, parents=view.parents)

        if coverage.missing and policy.supplemental_query_limit:
            missing = tuple(
                item for item in required if item.name in coverage.missing
            )
            supplemental = await self._service.retrieve(
                actor=actor,
                request=KnowledgeRetrievalRequest(
                    query=build_supplemental_query(
                        question=question,
                        missing=missing,
                    ),
                    business_domain=domain,
                    allowed_scopes=("public",),
                    history=history,
                    retrieval_mode=mode,
                    child_top_k=policy.child_top_k,
                    parent_top_k=policy.parent_candidate_k,
                    rerank_enabled=(
                        policy.rerank_enabled or self._customer_rerank_enabled
                    ),
                    rerank_candidate_k=policy.parent_candidate_k,
                ),
            )
            supplemental_kind, supplemental_score = score_retrieval_view(
                supplemental
            )
            supplemental_band = (
                policy.thresholds.get(supplemental_kind)
                if supplemental_kind is not None
                else None
            )
            if (
                supplemental_score is not None
                and supplemental_band is not None
                and supplemental_score >= supplemental_band.clarify
            ):
                view = self._merge_views(view, supplemental)
            coverage = evaluate_coverage(
                entities=required,
                parents=view.parents,
                supplemental_query_used=True,
            )

        ordered = coverage_aware_parent_order(
            entities=required,
            parents=view.parents,
            top_k=policy.parent_top_k,
        )
        view = view.model_copy(update={"parents": ordered})
        score_kind, score = score_retrieval_view(view)
        quality = decide_retrieval_quality(
            policy=policy,
            score_kind=score_kind,
            score=score,
            evidence_count=len(view.parents),
            missing_entities=coverage.missing,
        )
        return PolicyRetrievalResult(
            view=view,
            quality=quality,
            policy_trace=RetrievalPolicyTrace(
                policy_id=policy.policy_id,
                policy_version=policy.version,
                decision=quality.kind,
                reason_code=quality.reason_code,
                score_kind=quality.score_kind,
                score=quality.score,
            ),
            coverage=coverage,
        )

    @staticmethod
    def _merge_views(
        first: KnowledgeRetrievalView,
        second: KnowledgeRetrievalView,
    ) -> KnowledgeRetrievalView:
        """按ID合并一次补检索结果，保持首次出现顺序和安全Trace。"""

        children = _dedupe_children(first.child_hits + second.child_hits)
        parents = _dedupe_parents(first.parents + second.parents)
        return first.model_copy(
            update={
                "child_hits": children,
                "parents": parents,
                "active_index_version_ids": tuple(
                    dict.fromkeys(
                        first.active_index_version_ids
                        + second.active_index_version_ids
                    )
                ),
                "degraded": first.degraded or second.degraded,
                "failed_sources": tuple(
                    dict.fromkeys(first.failed_sources + second.failed_sources)
                ),
                "discarded_child_count": (
                    first.discarded_child_count + second.discarded_child_count
                ),
                "discarded_parent_count": (
                    first.discarded_parent_count + second.discarded_parent_count
                ),
            }
        )


def _dedupe_children(
    items: tuple[RetrievalChildHitView, ...],
) -> tuple[RetrievalChildHitView, ...]:
    seen: set[str] = set()
    result: list[RetrievalChildHitView] = []
    for item in items:
        if item.chunk_id in seen:
            continue
        seen.add(item.chunk_id)
        result.append(item)
    return tuple(result)


def _dedupe_parents(
    items: tuple[RetrievalParentView, ...],
) -> tuple[RetrievalParentView, ...]:
    seen: set[str] = set()
    result: list[RetrievalParentView] = []
    for item in items:
        if item.parent.id in seen:
            continue
        seen.add(item.parent.id)
        result.append(item)
    return tuple(result)
