"""固定数据集意图评估命令行入口。"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from bili_support.core.config import LLMProviderKind, Settings, get_settings
from bili_support.core.exceptions import AppError
from bili_support.evaluation.intent_data import (
    IntentDatasetError,
    load_intent_evaluation_cases,
)
from bili_support.evaluation.intent_report import render_intent_evaluation_markdown
from bili_support.evaluation.intent_runner import (
    HybridEvaluationAdapter,
    IntentEvaluationAdapter,
    ModelEvaluationAdapter,
    run_intent_evaluation,
)
from bili_support.evaluation.intent_types import EvaluationStrategy
from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.factory import build_intent_provider
from bili_support.intent.hybrid import HybridIntentClassifier
from bili_support.intent.rules import RuleIntentClassifier
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.prompts import create_default_prompt_registry
from bili_support.llm.provider import LLMProvider

DEFAULT_DATASET = Path("data/evaluation/intent_dev_v1.jsonl")
DEFAULT_MARKDOWN_REPORT = Path("data/evaluation/intent_eval_report.md")


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="在固定数据集上比较 BiliSupport 意图分类策略",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=[item.value for item in EvaluationStrategy],
        default=[item.value for item in EvaluationStrategy],
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        help="只运行前 N 条样本，适合真实模型的小规模冒烟实验",
    )
    parser.add_argument(
        "--allow-paid",
        action="store_true",
        help="允许使用真实 Provider 批量调用；未指定时拒绝潜在付费运行",
    )
    return parser


def build_evaluation_adapters(
    *,
    settings: Settings,
    provider: LLMProvider,
    strategies: Sequence[EvaluationStrategy],
) -> tuple[IntentEvaluationAdapter, ...]:
    """显式创建每个 Prompt/规则组合，避免实验配置隐式漂移。"""
    registry = create_default_prompt_registry()
    model_classifiers: dict[int, IntentClassifier] = {}

    def model_classifier(prompt_version: int) -> IntentClassifier:
        existing = model_classifiers.get(prompt_version)
        if existing is not None:
            return existing
        classifier = IntentClassifier(
            provider=provider,
            prompt_registry=registry,
            model=settings.llm_model,
            prompt_version=prompt_version,
            temperature=0.0,
            max_tokens=settings.llm_max_tokens,
            timeout_seconds=settings.llm_timeout_seconds,
            parse_retries=settings.intent_parse_retries,
        )
        model_classifiers[prompt_version] = classifier
        return classifier

    rule_classifier = RuleIntentClassifier()
    adapters: list[IntentEvaluationAdapter] = []
    for strategy in strategies:
        prompt_version = (
            2
            if strategy in {
                EvaluationStrategy.FEW_SHOT_V2,
                EvaluationStrategy.HYBRID_V2,
            }
            else 1
        )
        classifier = model_classifier(prompt_version)
        if strategy in {
            EvaluationStrategy.ZERO_SHOT_V1,
            EvaluationStrategy.FEW_SHOT_V2,
        }:
            adapters.append(
                ModelEvaluationAdapter(
                    strategy=strategy,
                    prompt_version=prompt_version,
                    classifier=classifier,
                )
            )
            continue
        adapters.append(
            HybridEvaluationAdapter(
                strategy=strategy,
                prompt_version=prompt_version,
                classifier=HybridIntentClassifier(
                    rule_classifier=rule_classifier,
                    model_classifier=classifier,
                ),
            )
        )
    return tuple(adapters)


async def run_cli(arguments: argparse.Namespace, settings: Settings) -> int:
    """加载数据、运行策略并写出 Markdown 与 JSON 报告。"""
    try:
        cases = load_intent_evaluation_cases(arguments.dataset)
    except IntentDatasetError:
        print("评估数据无法读取或未通过字段校验。")
        return 2

    if arguments.max_cases is not None:
        if arguments.max_cases <= 0:
            print("--max-cases 必须大于 0。")
            return 2
        cases = cases[: arguments.max_cases]

    strategy_values = tuple(
        EvaluationStrategy(value)
        for value in dict.fromkeys(arguments.strategies)
    )
    planned_calls = len(cases) * len(strategy_values)
    if (
        settings.llm_provider is not LLMProviderKind.MOCK
        and not arguments.allow_paid
    ):
        print(
            f"当前配置将产生最多 {planned_calls} 次真实模型调用；"
            "确认费用后请显式添加 --allow-paid。"
        )
        return 2

    provider = build_intent_provider(settings)
    try:
        adapters = build_evaluation_adapters(
            settings=settings,
            provider=provider,
            strategies=strategy_values,
        )
        report = await run_intent_evaluation(
            dataset_name=str(arguments.dataset),
            model=settings.llm_model,
            cases=cases,
            adapters=adapters,
        )
    except AppError as exc:
        print(f"评估调用失败：{exc.code.value}")
        return 3
    finally:
        if isinstance(provider, OpenAICompatibleProvider):
            await provider.aclose()

    markdown_path: Path = arguments.output
    json_path = markdown_path.with_suffix(".json")
    try:
        await asyncio.to_thread(
            _write_reports,
            markdown_path,
            json_path,
            render_intent_evaluation_markdown(report),
            report.model_dump_json(indent=2),
        )
    except OSError:
        print("无法写入评估报告。")
        return 4

    print(f"Markdown 报告：{markdown_path}")
    print(f"JSON 报告：{json_path}")
    return 0


def _write_reports(
    markdown_path: Path,
    json_path: Path,
    markdown_content: str,
    json_content: str,
) -> None:
    """在线程中执行同步文件写入，避免阻塞异步模型运行入口。"""
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown_content, encoding="utf-8")
    json_path.write_text(json_content, encoding="utf-8")


def main() -> None:
    """解析参数并运行异步评估。"""
    arguments = create_argument_parser().parse_args()
    raise SystemExit(asyncio.run(run_cli(arguments, get_settings())))


if __name__ == "__main__":
    main()
