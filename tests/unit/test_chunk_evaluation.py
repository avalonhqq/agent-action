import argparse
from pathlib import Path

import pytest

from bili_support.evaluation.chunk_cli import run_cli
from bili_support.evaluation.chunk_data import (
    ChunkDatasetError,
    load_chunk_evaluation_cases,
)
from bili_support.evaluation.chunk_metrics import ChunkEvaluator
from bili_support.evaluation.chunk_report import render_chunk_evaluation_markdown
from bili_support.evaluation.chunk_types import ChunkEvaluationMode

DATASET = Path("data/evaluation/chunk_dev_v1.jsonl")


def test_fixed_dataset_compares_generic_and_specialized_strategies() -> None:
    cases = load_chunk_evaluation_cases(DATASET)
    report = ChunkEvaluator().evaluate(
        dataset_name=DATASET.name,
        cases=cases,
    )

    assert len(cases) == 8
    generic, specialized = report.strategies
    assert generic.mode is ChunkEvaluationMode.GENERIC_BASELINE
    assert generic.metrics.child_semantic_recall < 1.0
    assert generic.metrics.parent_context_recall < 1.0
    assert specialized.mode is ChunkEvaluationMode.SPECIALIZED
    assert specialized.metrics.case_pass_rate == 1.0
    assert specialized.metrics.child_semantic_recall == 1.0
    assert specialized.metrics.parent_context_recall == 1.0
    assert specialized.metrics.traceability_rate == 1.0

    failed = next(
        case
        for case in generic.cases
        if case.case_id == "faq_word_cross_paragraph"
    )
    assert failed.source_name == "大会员FAQ.docx"
    assert any(
        failure.source_ordinals == (0, 1, 2) for failure in failed.failures
    )


def test_chunk_report_separates_representation_from_retrieval_metrics() -> None:
    report = ChunkEvaluator().evaluate(
        dataset_name=DATASET.name,
        cases=load_chunk_evaluation_cases(DATASET),
        modes=(ChunkEvaluationMode.SPECIALIZED,),
    )

    markdown = render_chunk_evaluation_markdown(report)

    assert "不代表向量检索 Recall@K" in markdown
    assert "specialized" in markdown
    assert "100.00%" in markdown


def test_chunk_dataset_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    first_line = DATASET.read_text(encoding="utf-8").splitlines()[0]
    invalid = tmp_path / "duplicate.jsonl"
    invalid.write_text(f"{first_line}\n{first_line}\n", encoding="utf-8")

    with pytest.raises(ChunkDatasetError, match="duplicate chunk case_id"):
        load_chunk_evaluation_cases(invalid)


def test_chunk_cli_writes_markdown_and_json_reports(tmp_path: Path) -> None:
    output_prefix = tmp_path / "chunk-report"
    exit_code = run_cli(
        argparse.Namespace(
            dataset=DATASET,
            modes=[ChunkEvaluationMode.SPECIALIZED.value],
            output_prefix=output_prefix,
        )
    )

    assert exit_code == 0
    assert output_prefix.with_suffix(".md").exists()
    assert output_prefix.with_suffix(".json").exists()
