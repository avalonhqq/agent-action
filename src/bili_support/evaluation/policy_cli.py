"""使用当前MySQL与Milvus执行7D检索策略评估。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import cast

from bili_support.core.config import get_settings
from bili_support.core.security import UserContext
from bili_support.evaluation.policy_report import render_policy_evaluation_markdown
from bili_support.evaluation.policy_runner import PolicyEvaluator
from bili_support.evaluation.retrieval_data import (
    RetrievalDatasetError,
    load_retrieval_evaluation_cases,
)
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.tokenizers import BM25TokenizerKind
from bili_support.main import create_app
from bili_support.services.policy_retrieval import PolicyAwareKnowledgeRetriever


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BiliSupport 7D检索策略评估")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/evaluation/retrieval_dev_v1.jsonl"),
    )
    parser.add_argument("--user-id", default="demo-user")
    parser.add_argument("--user-name", default="Demo User")
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in RetrievalMode],
        default=RetrievalMode.HYBRID.value,
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("data/evaluation/retrieval_policy_report_v2"),
    )
    parser.add_argument(
        "--bm25-tokenizer",
        choices=[kind.value for kind in BM25TokenizerKind],
        default=None,
        help="覆盖当前配置，用于bigram/jieba策略门禁对照",
    )
    return parser


async def run_cli(arguments: argparse.Namespace) -> int:
    try:
        cases = load_retrieval_evaluation_cases(arguments.dataset)
        settings = get_settings()
        if arguments.bm25_tokenizer is not None:
            settings = settings.model_copy(
                update={
                    "bm25_tokenizer": BM25TokenizerKind(arguments.bm25_tokenizer)
                }
            )
        application = create_app(settings)
        actor = UserContext(
            external_id=arguments.user_id,
            display_name=arguments.user_name,
        )
        async with application.router.lifespan_context(application):
            service = cast(
                PolicyAwareKnowledgeRetriever,
                application.state.policy_retrieval_service,
            )
            report = await PolicyEvaluator(
                service=service,
                actor=actor,
                retrieval_mode=RetrievalMode(arguments.mode),
                bm25_tokenizer=settings.bm25_tokenizer,
            ).evaluate(dataset_name=arguments.dataset.name, cases=cases)

        markdown_path = arguments.output_prefix.with_suffix(".md")
        json_path = arguments.output_prefix.with_suffix(".json")
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_policy_evaluation_markdown(report), encoding="utf-8"
        )
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except (RetrievalDatasetError, OSError, ValueError) as exc:
        print(f"检索策略评估失败：{exc}")
        return 2

    print(f"Markdown 报告：{markdown_path}")
    print(f"JSON 报告：{json_path}")
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(run_cli(create_argument_parser().parse_args())))


if __name__ == "__main__":
    main()
