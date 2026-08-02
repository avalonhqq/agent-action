"""以线上同款PolicyAwareKnowledgeRetriever评估回答门禁。"""

from __future__ import annotations

from math import ceil
from time import perf_counter

from bili_support.core.security import UserContext
from bili_support.evaluation.policy_types import (
    PolicyCaseResult,
    PolicyEvaluationMetrics,
    PolicyEvaluationReport,
)
from bili_support.evaluation.retrieval_types import RetrievalEvaluationCase
from bili_support.intent.types import IntentAction
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.retrieval_policy import RetrievalDecisionKind
from bili_support.knowledge.tokenizers import BM25TokenizerKind
from bili_support.services.policy_retrieval import PolicyAwareKnowledgeRetriever


class PolicyEvaluator:
    """把既有检索正负集复用于“回答/拒答”策略验收。"""

    def __init__(
        self,
        *,
        service: PolicyAwareKnowledgeRetriever,
        actor: UserContext,
        retrieval_mode: RetrievalMode = RetrievalMode.HYBRID,
        bm25_tokenizer: BM25TokenizerKind | None = None,
    ) -> None:
        self._service = service
        self._actor = actor
        self._retrieval_mode = retrieval_mode
        self._bm25_tokenizer = bm25_tokenizer

    async def evaluate(
        self,
        *,
        dataset_name: str,
        cases: tuple[RetrievalEvaluationCase, ...],
    ) -> PolicyEvaluationReport:
        """串行运行，防止并发噪声掩盖单样本策略和延迟。"""

        results = tuple([await self._evaluate_case(case) for case in cases])
        return PolicyEvaluationReport(
            dataset=dataset_name,
            retrieval_mode=self._retrieval_mode,
            bm25_tokenizer=(
                self._bm25_tokenizer
                if self._retrieval_mode in {RetrievalMode.BM25, RetrievalMode.HYBRID}
                else None
            ),
            case_count=len(cases),
            metrics=_aggregate_metrics(results),
            cases=results,
        )

    async def _evaluate_case(self, case: RetrievalEvaluationCase) -> PolicyCaseResult:
        expected = (
            RetrievalDecisionKind.REFUSE
            if case.expect_empty
            else RetrievalDecisionKind.ANSWER
        )
        started = perf_counter()
        try:
            result = await self._service.retrieve(
                actor=self._actor,
                question=case.question,
                history=(),
                domain=case.business_domain,
                actions=(IntentAction.QUERY,),
                entities=(),
                mode=self._retrieval_mode,
            )
            return PolicyCaseResult(
                case=case,
                expected_decision=expected,
                actual_decision=result.quality.kind,
                policy_id=result.policy_trace.policy_id,
                reason_code=result.policy_trace.reason_code,
                score_kind=(
                    result.policy_trace.score_kind.value
                    if result.policy_trace.score_kind is not None
                    else None
                ),
                score=result.policy_trace.score,
                evidence_count=result.quality.evidence_count,
                coverage_ratio=result.coverage.ratio,
                supplemental_query_used=result.coverage.supplemental_query_used,
                latency_ms=(perf_counter() - started) * 1000,
            )
        except Exception as exc:
            # 报告保留单样本基础设施错误，其余样本仍可继续完成。
            return PolicyCaseResult(
                case=case,
                expected_decision=expected,
                latency_ms=(perf_counter() - started) * 1000,
                error_code=type(exc).__name__,
            )


def _aggregate_metrics(
    results: tuple[PolicyCaseResult, ...],
) -> PolicyEvaluationMetrics:
    negatives = tuple(item for item in results if item.case.expect_empty)
    predicted_answers = tuple(
        item for item in results if item.actual_decision is RetrievalDecisionKind.ANSWER
    )
    successful = tuple(item for item in results if item.error_code is None)
    latencies = sorted(item.latency_ms for item in successful)
    return PolicyEvaluationMetrics(
        decision_accuracy=_ratio(sum(item.passed for item in results), len(results)),
        answer_precision=_ratio(
            sum(item.passed for item in predicted_answers), len(predicted_answers)
        ),
        false_answer_rate=_ratio(
            sum(
                item.actual_decision is RetrievalDecisionKind.ANSWER
                for item in negatives
            ),
            len(negatives),
        ),
        refusal_recall=_ratio(
            sum(
                item.actual_decision is RetrievalDecisionKind.REFUSE
                for item in negatives
            ),
            len(negatives),
        ),
        mean_entity_coverage=_mean(tuple(item.coverage_ratio for item in successful)),
        supplemental_query_rate=_mean(
            tuple(
                1.0 if item.supplemental_query_used else 0.0
                for item in successful
            )
        ),
        execution_failure_rate=_ratio(
            sum(item.error_code is not None for item in results), len(results)
        ),
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
    )


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(sorted_values: list[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    rank = max(1, ceil(quantile * len(sorted_values)))
    return sorted_values[rank - 1]
