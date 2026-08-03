"""运行第8周固定RAG评估并输出JSON/Markdown报告。"""

from __future__ import annotations

import argparse
from pathlib import Path

from bili_support.evaluation.rag_data import RagDatasetError, load_rag_evaluation_cases
from bili_support.evaluation.rag_report import render_rag_evaluation_markdown
from bili_support.evaluation.rag_runner import ReplayRagEvaluator


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BiliSupport第8周RAG生成评估")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/rag_dev_v1.jsonl"),
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("data/evaluation/rag_replay_report_v1"),
    )
    return parser


def run_cli(arguments: argparse.Namespace) -> int:
    try:
        cases = load_rag_evaluation_cases(arguments.dataset)
        report = ReplayRagEvaluator().evaluate(
            dataset_name=arguments.dataset.name,
            cases=cases,
        )
        arguments.output_prefix.parent.mkdir(parents=True, exist_ok=True)
        arguments.output_prefix.with_suffix(".json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        arguments.output_prefix.with_suffix(".md").write_text(
            render_rag_evaluation_markdown(report), encoding="utf-8"
        )
    except (OSError, RagDatasetError, ValueError) as exc:
        print(f"RAG评估失败：{exc}")
        return 2
    print(f"Markdown报告：{arguments.output_prefix.with_suffix('.md')}")
    print(f"JSON报告：{arguments.output_prefix.with_suffix('.json')}")
    return 0


def main() -> None:
    raise SystemExit(run_cli(create_argument_parser().parse_args()))


if __name__ == "__main__":
    main()
