"""把检索Parent转换为有界、可引用且可安全展示的客服证据。"""

from __future__ import annotations

import json
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.coverage import EvidenceCoverage
from bili_support.knowledge.reranking import RerankTrace
from bili_support.knowledge.retrieval import RetrievalMode, RetrievalSource
from bili_support.knowledge.retrieval_policy import RetrievalPolicyTrace
from bili_support.schemas.knowledge import KnowledgeRetrievalView


class KnowledgeCitation(BaseModel):
    """返回给页面的证据来源，不包含内部存储路径或向量。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    parent_chunk_id: str
    document_id: str
    document_title: str
    document_version_id: str
    business_domain: BusinessDomain
    score: float


class KnowledgeRetrievalTrace(BaseModel):
    """SSE、页面与审计共享的安全检索摘要。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: RetrievalMode
    business_domains: tuple[BusinessDomain, ...]
    child_hit_count: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    citations: tuple[KnowledgeCitation, ...] = ()
    degraded: bool = False
    failed_sources: tuple[RetrievalSource, ...] = ()
    reranking: RerankTrace | None = None
    policy: RetrievalPolicyTrace | None = None
    coverage: EvidenceCoverage | None = None
    error_code: str | None = None


class KnowledgeEvidenceBundle(BaseModel):
    """内部Grounded Prompt上下文与可公开Trace的组合。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_json: str
    trace: KnowledgeRetrievalTrace


def build_knowledge_evidence(
    *,
    results: Sequence[tuple[BusinessDomain, KnowledgeRetrievalView]],
    mode: RetrievalMode,
    max_parents: int = 5,
    max_parent_chars: int = 2000,
    max_total_chars: int = 6000,
) -> KnowledgeEvidenceBundle:
    """跨业务域去重Parent，并在字符预算内生成JSON证据上下文。"""

    if max_parents < 1 or max_parent_chars < 1 or max_total_chars < 1:
        raise ValueError("knowledge evidence budgets must be positive")
    evidence_rows: list[dict[str, object]] = []
    citations: list[KnowledgeCitation] = []
    seen_parent_ids: set[str] = set()
    used_chars = 0
    child_hit_count = sum(len(view.child_hits) for _, view in results)
    for domain, view in results:
        for item in view.parents:
            parent_id = item.parent.id
            if parent_id in seen_parent_ids or len(citations) >= max_parents:
                continue
            remaining = max_total_chars - used_chars
            if remaining <= 0:
                break
            content = item.parent.content[: min(max_parent_chars, remaining)]
            if not content.strip():
                continue
            seen_parent_ids.add(parent_id)
            used_chars += len(content)
            evidence_id = f"E{len(citations) + 1}"
            citation = KnowledgeCitation(
                evidence_id=evidence_id,
                parent_chunk_id=parent_id,
                document_id=item.document_id,
                document_title=item.document_title,
                document_version_id=item.document_version_id,
                business_domain=domain,
                score=item.best_child_score,
            )
            citations.append(citation)
            evidence_rows.append(
                {
                    "evidence_id": evidence_id,
                    "document_title": item.document_title,
                    "business_domain": domain.value,
                    "content": content,
                }
            )

    domains = tuple(dict.fromkeys(domain for domain, _ in results))
    failed_sources = tuple(
        dict.fromkeys(
            source
            for _, view in results
            for source in view.failed_sources
        )
    )
    rerank_traces = tuple(view.reranking for _, view in results)
    enabled_rerank_traces = tuple(
        item for item in rerank_traces if item.enabled
    )
    reranking = (
        RerankTrace(
            enabled=any(item.enabled for item in rerank_traces),
            attempted=any(item.attempted for item in rerank_traces),
            applied=bool(enabled_rerank_traces)
            and all(item.applied for item in enabled_rerank_traces),
            degraded=any(item.degraded for item in rerank_traces),
            provider=next(
                (item.provider for item in rerank_traces if item.provider),
                None,
            ),
            model=next(
                (item.model for item in rerank_traces if item.model),
                None,
            ),
            candidate_count=sum(item.candidate_count for item in rerank_traces),
            returned_count=sum(item.returned_count for item in rerank_traces),
            latency_ms=sum(
                item.latency_ms or 0.0 for item in rerank_traces
            ),
            error_code=next(
                (item.error_code for item in rerank_traces if item.error_code),
                None,
            ),
        )
        if rerank_traces
        else None
    )
    trace = KnowledgeRetrievalTrace(
        mode=mode,
        business_domains=domains,
        child_hit_count=child_hit_count,
        evidence_count=len(citations),
        citations=tuple(citations),
        degraded=any(view.degraded for _, view in results),
        failed_sources=failed_sources,
        reranking=reranking,
    )
    return KnowledgeEvidenceBundle(
        context_json=json.dumps(
            {"evidence": evidence_rows},
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        trace=trace,
    )
