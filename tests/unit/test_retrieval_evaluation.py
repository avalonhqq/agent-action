"""6D固定检索数据、Recall计算和失败报告测试。"""

import json
from pathlib import Path

import pytest

from bili_support.evaluation.retrieval_data import (
    RetrievalDatasetError,
    load_retrieval_evaluation_cases,
)
from bili_support.evaluation.retrieval_report import (
    render_retrieval_evaluation_markdown,
)
from bili_support.evaluation.retrieval_runner import (
    _aggregate_metrics,
    _score_case,
)
from bili_support.evaluation.retrieval_types import (
    RelevantParent,
    RetrievalEvaluationCase,
    RetrievalEvaluationReport,
    RetrievedParent,
)
from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.retrieval import RetrievalMode


def _positive_case() -> RetrievalEvaluationCase:
    return RetrievalEvaluationCase(
        case_id="membership_missing_001",
        question="付款了会员没到账怎么办",
        business_domain=BusinessDomain.MEMBERSHIP,
        relevant_parents=(
            RelevantParent(
                relevance_id="missing_membership_faq",
                document_title="大会员开通说明",
                content_contains=("支付状态", "订单号"),
            ),
        ),
    )


def test_recall_uses_first_matching_parent_rank() -> None:
    result = _score_case(
        case=_positive_case(),
        parents=(
            RetrievedParent(
                parent_chunk_id="wrong",
                document_title="其他知识",
                content="无关答案",
                score=0.9,
                rank=1,
            ),
            RetrievedParent(
                parent_chunk_id="correct",
                document_title="大会员开通说明",
                content="先检查支付状态，超过时间后提供订单号。",
                score=0.8,
                rank=2,
            ),
        ),
        latency_ms=12.5,
    )

    assert result.recall_at_1 == 0.0
    assert result.recall_at_3 == 1.0
    assert result.recall_at_5 == 1.0
    assert result.reciprocal_rank == 0.5
    assert result.passed is True


def test_negative_case_fails_when_any_parent_is_returned() -> None:
    case = RetrievalEvaluationCase(
        case_id="negative_ticket_001",
        question="演唱会门票怎么买",
        business_domain=BusinessDomain.MEMBERSHIP,
        expect_empty=True,
    )
    result = _score_case(
        case=case,
        parents=(
            RetrievedParent(
                parent_chunk_id="unexpected",
                document_title="大会员开通说明",
                content="会员价格",
                score=0.1,
                rank=1,
            ),
        ),
        latency_ms=1.0,
    )

    metrics = _aggregate_metrics((result,))
    assert result.passed is False
    assert metrics.negative_accuracy == 0.0
    assert metrics.latency_p95_ms == 1.0


def test_loader_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    item = _positive_case().model_dump(mode="json")
    dataset = tmp_path / "retrieval.jsonl"
    dataset.write_text(
        f"{json.dumps(item, ensure_ascii=False)}\n"
        f"{json.dumps(item, ensure_ascii=False)}\n",
        encoding="utf-8",
    )

    with pytest.raises(RetrievalDatasetError, match="duplicate"):
        load_retrieval_evaluation_cases(dataset)


def test_markdown_contains_metrics_and_failure_details() -> None:
    result = _score_case(
        case=_positive_case(),
        parents=(),
        latency_ms=5.0,
    )
    report = RetrievalEvaluationReport(
        dataset="retrieval.jsonl",
        case_count=1,
        retrieval_mode=RetrievalMode.VECTOR,
        embedding_model="mock-embedding-v1",
        metrics=_aggregate_metrics((result,)),
        cases=(result,),
    )

    markdown = render_retrieval_evaluation_markdown(report)
    assert "Recall@5" in markdown
    assert "membership_missing_001" in markdown
    assert "relevant_parent_missed" in markdown
