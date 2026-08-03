"""使用当前MySQL、Embedding Provider和Milvus运行6D固定检索评估。"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import cast

from bili_support.core.config import get_settings
from bili_support.core.security import UserContext
from bili_support.evaluation.retrieval_data import (
    RetrievalDatasetError,
    load_retrieval_evaluation_cases,
)
from bili_support.evaluation.retrieval_report import (
    render_retrieval_evaluation_markdown,
)
from bili_support.evaluation.retrieval_runner import RetrievalEvaluator
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.tokenizers import BM25TokenizerKind
from bili_support.main import create_app
from bili_support.services.retrieval import KnowledgeRetrievalService


def create_argument_parser() -> argparse.ArgumentParser:
    """CLI参数显式记录数据集、知识拥有者和报告位置，方便实验重放。"""

    parser = argparse.ArgumentParser(description="BiliSupport 6D检索评估")
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
        default=RetrievalMode.VECTOR.value,
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("data/evaluation/retrieval_report_v1"),
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="对Small-to-Big Parent候选执行配置的批量Reranker",
    )
    parser.add_argument(
        "--rerank-candidate-k",
        type=int,
        default=10,
        choices=range(5, 21),
    )
    parser.add_argument(
        "--bm25-tokenizer",
        choices=[kind.value for kind in BM25TokenizerKind],
        default=None,
        help="覆盖当前配置，用于bigram/jieba固定集对照",
    )
    return parser


async def run_cli(arguments: argparse.Namespace) -> int:
    """启动应用依赖，运行真实检索链路并写出Markdown与JSON报告。"""

    try:
        cases = load_retrieval_evaluation_cases(arguments.dataset)
        settings = get_settings()
        if arguments.bm25_tokenizer is not None:
            settings = settings.model_copy(
                update={
                    "bm25_tokenizer": BM25TokenizerKind(arguments.bm25_tokenizer),
                    # 显式Tokenizer参数用于回放旧进程内基线；ES使用自己的Analyzer。
                    "elasticsearch_enabled": False,
                    "elasticsearch_required": False,
                }
            )
        application = create_app(settings)
        actor = UserContext(
            external_id=arguments.user_id,
            display_name=arguments.user_name,
        )
        async with application.router.lifespan_context(application):
            service = cast(
                KnowledgeRetrievalService,
                application.state.knowledge_retrieval_service,
            )
            report = await RetrievalEvaluator(
                service=service,
                actor=actor,
                embedding_model=settings.embedding_model,
                retrieval_mode=RetrievalMode(arguments.mode),
                rerank_enabled=arguments.rerank,
                rerank_provider=settings.rerank_provider.value,
                rerank_model=settings.rerank_model,
                rerank_candidate_k=arguments.rerank_candidate_k,
                bm25_tokenizer=(
                    None
                    if settings.elasticsearch_enabled
                    else settings.bm25_tokenizer
                ),
                lexical_backend=(
                    "elasticsearch"
                    if settings.elasticsearch_enabled
                    else "in_memory"
                ),
            ).evaluate(
                dataset_name=arguments.dataset.name,
                cases=cases,
            )

        markdown_path = arguments.output_prefix.with_suffix(".md")
        json_path = arguments.output_prefix.with_suffix(".json")
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(
            render_retrieval_evaluation_markdown(report),
            encoding="utf-8",
        )
        json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    except (RetrievalDatasetError, OSError, ValueError) as exc:
        print(f"检索评估失败：{exc}")
        return 2

    print(f"Markdown 报告：{markdown_path}")
    print(f"JSON 报告：{json_path}")
    return 0


def main() -> None:
    """项目脚本入口。"""

    raise SystemExit(asyncio.run(run_cli(create_argument_parser().parse_args())))


if __name__ == "__main__":
    main()
