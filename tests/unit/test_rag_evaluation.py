"""8C Golden Dataset、指标和失败分类测试。"""

from pathlib import Path

from bili_support.evaluation.rag_data import load_rag_evaluation_cases
from bili_support.evaluation.rag_runner import ReplayRagEvaluator, score_rag_case
from bili_support.evaluation.rag_types import RagFailureKind, RagPrediction
from bili_support.knowledge.grounded_answer import GroundedAnswer


def test_replay_dataset_covers_week8_boundary_cases() -> None:
    cases = load_rag_evaluation_cases(Path("data/evaluation/rag_dev_v1.jsonl"))
    tags = {tag for case in cases for tag in case.tags}
    report = ReplayRagEvaluator().evaluate(dataset_name="rag_dev_v1", cases=cases)

    assert {"answer", "clarify", "refuse", "conflict", "multi_entity"} <= tags
    assert report.run_mode == "fixed_prediction_replay"
    assert report.metrics.pass_rate == 1.0


def test_incomplete_answer_is_classified_separately() -> None:
    case = load_rag_evaluation_cases(Path("data/evaluation/rag_dev_v1.jsonl"))[0]
    answer = GroundedAnswer.model_validate(
        {
            "answer": "支付成功后立即生效[E1]。",
            "claims": [
                {"text": "支付成功后立即生效。", "evidence_ids": ["E1"]}
            ],
            "used_evidence_ids": ["E1"],
            "completeness": "complete",
        }
    )
    prediction = RagPrediction(decision="answer", grounded_answer=answer)

    result = score_rag_case(case, prediction)

    assert RagFailureKind.INCOMPLETE_ANSWER in result.failures
    assert RagFailureKind.ANSWER_RELEVANCY_FAILURE in result.failures
