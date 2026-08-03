"""8C固定预测重放评估器；真实模型可复用score_rag_case输入契约。"""

from __future__ import annotations

from bili_support.evaluation.rag_types import (
    RagCaseResult,
    RagEvaluationCase,
    RagEvaluationMetrics,
    RagEvaluationReport,
    RagFailureKind,
    RagPrediction,
)
from bili_support.knowledge.claim_verification import (
    ClaimSupportStatus,
    EvidenceRecord,
    verify_grounded_answer,
)
from bili_support.knowledge.grounded_answer import (
    GroundedAnswerContractError,
    validate_grounded_answer_evidence,
)


class ReplayRagEvaluator:
    """不调用模型，只验证数据、指标和报告链路；不得宣称为真实模型效果。"""

    def evaluate(
        self,
        *,
        dataset_name: str,
        cases: tuple[RagEvaluationCase, ...],
    ) -> RagEvaluationReport:
        results = tuple(score_rag_case(case, case.replay_prediction) for case in cases)
        return RagEvaluationReport(
            dataset=dataset_name,
            run_mode="fixed_prediction_replay",
            metrics=_aggregate(results),
            cases=results,
        )


def score_rag_case(case: RagEvaluationCase, prediction: RagPrediction) -> RagCaseResult:
    """从策略、引用、声明支持和答案覆盖四个维度评分。"""

    failures: list[RagFailureKind] = []
    if prediction.decision is not case.expected_decision:
        failures.append(RagFailureKind.DECISION_MISMATCH)
    if prediction.retrieval_error_code:
        failures.append(RagFailureKind.RETRIEVAL_FAILURE)
    if prediction.generation_error_code:
        failures.append(RagFailureKind.GENERATION_FAILURE)
    if prediction.judge_uncertain:
        failures.append(RagFailureKind.JUDGE_UNCERTAIN)

    faithfulness = answer_relevancy = citation_precision = citation_recall = 1.0
    answer = prediction.grounded_answer
    if answer is not None:
        allowed_ids = tuple(item.evidence_id for item in case.evidence)
        try:
            validate_grounded_answer_evidence(answer, allowed_evidence_ids=allowed_ids)
        except GroundedAnswerContractError:
            failures.append(RagFailureKind.CITATION_FAILURE)
            citation_precision = 0.0
        verification = verify_grounded_answer(
            answer,
            evidence=tuple(
                EvidenceRecord(evidence_id=item.evidence_id, content=item.content)
                for item in case.evidence
            ),
        )
        supported = sum(
            item.status is ClaimSupportStatus.SUPPORTED for item in verification.claims
        )
        faithfulness = supported / len(verification.claims)
        if faithfulness < 1.0:
            failures.append(RagFailureKind.FAITHFULNESS_FAILURE)
        expected_ids = set(case.expected_evidence_ids)
        used_ids = set(answer.used_evidence_ids)
        citation_precision = (
            len(used_ids & set(allowed_ids)) / len(used_ids) if used_ids else 0.0
        )
        citation_recall = (
            len(used_ids & expected_ids) / len(expected_ids) if expected_ids else 1.0
        )
        if citation_precision < 1.0 or citation_recall < 1.0:
            failures.append(RagFailureKind.CITATION_FAILURE)
        answer_relevancy = _term_coverage(answer.answer, case.required_answer_terms)
        if answer_relevancy < 1.0:
            failures.extend(
                [RagFailureKind.ANSWER_RELEVANCY_FAILURE, RagFailureKind.INCOMPLETE_ANSWER]
            )
    return RagCaseResult(
        case_id=case.case_id,
        expected_decision=case.expected_decision,
        actual_decision=prediction.decision,
        faithfulness=faithfulness,
        answer_relevancy=answer_relevancy,
        citation_precision=citation_precision,
        citation_recall=citation_recall,
        failures=tuple(dict.fromkeys(failures)),
    )


def _term_coverage(answer: str, required: tuple[str, ...]) -> float:
    if not required:
        return 1.0
    normalized = answer.casefold()
    return sum(item.casefold() in normalized for item in required) / len(required)


def _aggregate(results: tuple[RagCaseResult, ...]) -> RagEvaluationMetrics:
    return RagEvaluationMetrics(
        decision_accuracy=_mean(
            tuple(item.actual_decision is item.expected_decision for item in results)
        ),
        faithfulness=_mean(tuple(item.faithfulness for item in results)),
        answer_relevancy=_mean(tuple(item.answer_relevancy for item in results)),
        citation_precision=_mean(tuple(item.citation_precision for item in results)),
        citation_recall=_mean(tuple(item.citation_recall for item in results)),
        pass_rate=_mean(tuple(item.passed for item in results)),
        case_count=len(results),
    )


def _mean(values: tuple[float | bool, ...]) -> float:
    return sum(float(item) for item in values) / len(values)
