"""通过真实6C Service运行Golden Dataset并计算Recall、MRR和延迟。"""

from __future__ import annotations

from math import ceil
from time import perf_counter

from bili_support.core.security import UserContext
from bili_support.evaluation.retrieval_types import (
    RelevantParent,
    RetrievalCaseResult,
    RetrievalEvaluationCase,
    RetrievalEvaluationMetrics,
    RetrievalEvaluationReport,
    RetrievalFailureKind,
    RetrievedParent,
)
from bili_support.knowledge.reranking import RerankErrorCode
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.tokenizers import BM25TokenizerKind
from bili_support.schemas.knowledge import KnowledgeRetrievalRequest
from bili_support.services.retrieval import KnowledgeRetrievalService

_EVALUATION_TOP_K = 5


class RetrievalEvaluator:
    """评估完整在线检索链路，而不是绕过权限和版本控制直接查询Milvus。"""

    def __init__(
        self,
        *,
        service: KnowledgeRetrievalService,
        actor: UserContext,
        embedding_model: str,
        retrieval_mode: RetrievalMode = RetrievalMode.VECTOR,
        rerank_enabled: bool = False,
        rerank_provider: str | None = None,
        rerank_model: str | None = None,
        rerank_candidate_k: int = 10,
        bm25_tokenizer: BM25TokenizerKind | None = None,
        lexical_backend: str = "in_memory",
    ) -> None:
        self._service = service
        self._actor = actor
        self._embedding_model = embedding_model
        self._retrieval_mode = retrieval_mode
        self._rerank_enabled = rerank_enabled
        self._rerank_provider = rerank_provider
        self._rerank_model = rerank_model
        self._rerank_candidate_k = rerank_candidate_k
        self._bm25_tokenizer = bm25_tokenizer
        self._lexical_backend = lexical_backend

    async def evaluate(
        self,
        *,
        dataset_name: str,
        cases: tuple[RetrievalEvaluationCase, ...],
    ) -> RetrievalEvaluationReport:
        """串行运行固定集，避免并发把本地延迟和Milvus吞吐混为一谈。"""

        results = tuple([await self._evaluate_case(case) for case in cases])
        return RetrievalEvaluationReport(
            dataset=dataset_name,
            case_count=len(cases),
            retrieval_mode=self._retrieval_mode,
            lexical_backend=self._lexical_backend,
            bm25_tokenizer=(
                self._bm25_tokenizer
                if self._retrieval_mode in {RetrievalMode.BM25, RetrievalMode.HYBRID}
                else None
            ),
            embedding_model=(
                self._embedding_model
                if self._retrieval_mode is not RetrievalMode.BM25
                else None
            ),
            rerank_enabled=self._rerank_enabled,
            rerank_provider=self._rerank_provider if self._rerank_enabled else None,
            rerank_model=self._rerank_model if self._rerank_enabled else None,
            metrics=_aggregate_metrics(results),
            cases=results,
        )

    async def _evaluate_case(
        self,
        case: RetrievalEvaluationCase,
    ) -> RetrievalCaseResult:
        started = perf_counter()
        try:
            response = await self._service.retrieve(
                actor=self._actor,
                request=KnowledgeRetrievalRequest(
                    query=case.question,
                    business_domain=case.business_domain,
                    allowed_scopes=case.allowed_scopes,
                    retrieval_mode=self._retrieval_mode,
                    child_top_k=20,
                    parent_top_k=_EVALUATION_TOP_K,
                    rerank_enabled=self._rerank_enabled,
                    rerank_candidate_k=self._rerank_candidate_k,
                ),
            )
            latency_ms = (perf_counter() - started) * 1000
            parents = tuple(
                RetrievedParent(
                    parent_chunk_id=item.parent.id,
                    document_title=item.document_title,
                    content=item.parent.content,
                    score=(
                        item.rerank_score
                        if item.rerank_score is not None
                        else item.best_child_score
                    ),
                    rank=rank,
                )
                for rank, item in enumerate(response.parents, start=1)
            )
            return _score_case(
                case=case,
                parents=parents,
                latency_ms=latency_ms,
                rerank_applied=response.reranking.applied,
                rerank_degraded=response.reranking.degraded,
                rerank_error_code=response.reranking.error_code,
            )
        except Exception as exc:
            # 单个Provider/数据库故障保留为失败样本，不能让整份报告消失。
            return RetrievalCaseResult(
                case=case,
                parents=(),
                matched_relevance_ids_at_5=(),
                recall_at_1=0.0,
                recall_at_3=0.0,
                recall_at_5=0.0,
                reciprocal_rank=0.0,
                latency_ms=(perf_counter() - started) * 1000,
                failures=(RetrievalFailureKind.EXECUTION_ERROR,),
                error_code=type(exc).__name__,
            )


def _score_case(
    *,
    case: RetrievalEvaluationCase,
    parents: tuple[RetrievedParent, ...],
    latency_ms: float,
    rerank_applied: bool = False,
    rerank_degraded: bool = False,
    rerank_error_code: RerankErrorCode | None = None,
) -> RetrievalCaseResult:
    """正例计算宏平均Recall，负例检查Top-5必须为空。"""

    if case.expect_empty:
        failures = (
            (RetrievalFailureKind.UNEXPECTED_PARENT,) if parents else ()
        )
        return RetrievalCaseResult(
            case=case,
            parents=parents,
            matched_relevance_ids_at_5=(),
            recall_at_1=0.0,
            recall_at_3=0.0,
            recall_at_5=0.0,
            reciprocal_rank=0.0,
            latency_ms=latency_ms,
            failures=failures,
            rerank_applied=rerank_applied,
            rerank_degraded=rerank_degraded,
            rerank_error_code=rerank_error_code,
        )

    ranks = {
        relevant.relevance_id: _first_match_rank(relevant, parents)
        for relevant in case.relevant_parents
    }
    recall_at_1 = _recall_at(ranks, 1)
    recall_at_3 = _recall_at(ranks, 3)
    recall_at_5 = _recall_at(ranks, 5)
    first_rank = min(
        (rank for rank in ranks.values() if rank is not None),
        default=None,
    )
    failures = (
        ()
        if recall_at_5 == 1.0
        else (RetrievalFailureKind.RELEVANT_PARENT_MISSED,)
    )
    return RetrievalCaseResult(
        case=case,
        parents=parents,
        matched_relevance_ids_at_5=tuple(
            relevance_id
            for relevance_id, rank in ranks.items()
            if rank is not None and rank <= 5
        ),
        recall_at_1=recall_at_1,
        recall_at_3=recall_at_3,
        recall_at_5=recall_at_5,
        reciprocal_rank=0.0 if first_rank is None else 1.0 / first_rank,
        latency_ms=latency_ms,
        failures=failures,
        rerank_applied=rerank_applied,
        rerank_degraded=rerank_degraded,
        rerank_error_code=rerank_error_code,
    )


def _first_match_rank(
    relevant: RelevantParent,
    parents: tuple[RetrievedParent, ...],
) -> int | None:
    """标题可选精确匹配，正文锚点采用不区分大小写的全部包含关系。"""

    markers = tuple(marker.casefold() for marker in relevant.content_contains)
    for parent in parents:
        if (
            relevant.document_title is not None
            and parent.document_title != relevant.document_title
        ):
            continue
        normalized_content = parent.content.casefold()
        if all(marker in normalized_content for marker in markers):
            return parent.rank
    return None


def _recall_at(ranks: dict[str, int | None], k: int) -> float:
    matched = sum(rank is not None and rank <= k for rank in ranks.values())
    return matched / len(ranks)


def _aggregate_metrics(
    results: tuple[RetrievalCaseResult, ...],
) -> RetrievalEvaluationMetrics:
    positives = tuple(item for item in results if not item.case.expect_empty)
    negatives = tuple(item for item in results if item.case.expect_empty)
    successful_latencies = sorted(
        item.latency_ms
        for item in results
        if RetrievalFailureKind.EXECUTION_ERROR not in item.failures
    )
    return RetrievalEvaluationMetrics(
        recall_at_1=_mean(tuple(item.recall_at_1 for item in positives)),
        recall_at_3=_mean(tuple(item.recall_at_3 for item in positives)),
        recall_at_5=_mean(tuple(item.recall_at_5 for item in positives)),
        mrr_at_5=_mean(tuple(item.reciprocal_rank for item in positives)),
        negative_accuracy=_mean(
            tuple(1.0 if item.passed else 0.0 for item in negatives)
        ),
        execution_failure_rate=(
            sum(
                RetrievalFailureKind.EXECUTION_ERROR in item.failures
                for item in results
            )
            / len(results)
        ),
        rerank_degradation_rate=_mean(
            tuple(1.0 if item.rerank_degraded else 0.0 for item in results)
        ),
        latency_p50_ms=_percentile(successful_latencies, 0.50),
        latency_p95_ms=_percentile(successful_latencies, 0.95),
        positive_case_count=len(positives),
        negative_case_count=len(negatives),
    )


def _mean(values: tuple[float, ...]) -> float:
    """无对应样本时返回0，报告同时展示正负例数量以避免误读。"""

    return sum(values) / len(values) if values else 0.0


def _percentile(sorted_values: list[float], quantile: float) -> float:
    """使用nearest-rank定义，样本少时也容易手工复算。"""

    if not sorted_values:
        return 0.0
    rank = max(1, ceil(quantile * len(sorted_values)))
    return sorted_values[rank - 1]
