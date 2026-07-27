"""运行无需模型调用、无需数据库的固定Chunk策略评估。"""

from __future__ import annotations

import argparse
from pathlib import Path

from bili_support.evaluation.chunk_data import (
    ChunkDatasetError,
    load_chunk_evaluation_cases,
)
from bili_support.evaluation.chunk_metrics import ChunkEvaluator
from bili_support.evaluation.chunk_report import render_chunk_evaluation_markdown
from bili_support.evaluation.chunk_types import ChunkEvaluationMode


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BiliSupport Chunk离线评估")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/chunk_dev_v1.jsonl"),
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[mode.value for mode in ChunkEvaluationMode],
        default=[mode.value for mode in ChunkEvaluationMode],
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("data/evaluation/chunk_report_v1"),
    )
    return parser


def run_cli(arguments: argparse.Namespace) -> int:
    try:
        cases = load_chunk_evaluation_cases(arguments.dataset)
        report = ChunkEvaluator().evaluate(
            dataset_name=arguments.dataset.name,
            cases=cases,
            modes=tuple(ChunkEvaluationMode(value) for value in arguments.modes),
        )
        markdown_path = arguments.output_prefix.with_suffix(".md")
        json_path = arguments.output_prefix.with_suffix(".json")
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_chunk_evaluation_markdown(report),
            encoding="utf-8",
        )
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except (ChunkDatasetError, OSError, ValueError) as exc:
        print(f"Chunk评估失败：{exc}")
        return 2

    print(f"Markdown 报告：{markdown_path}")
    print(f"JSON 报告：{json_path}")
    return 0


def main() -> None:
    raise SystemExit(run_cli(create_argument_parser().parse_args()))


if __name__ == "__main__":
    main()
