"""Command-line experiment for schema-constrained intent classification."""

from __future__ import annotations

import argparse
import asyncio
import json

from bili_support.core.config import Settings, get_settings
from bili_support.core.exceptions import AppError
from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.factory import build_intent_provider
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.prompts import create_default_prompt_registry


def _create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用当前 LLM 配置试验 BiliSupport 意图识别",
    )
    parser.add_argument("question", help="需要识别的单条客服问题")
    return parser


async def run_experiment(question: str, settings: Settings) -> int:
    """Run one classification and print only safe structured output."""
    provider = build_intent_provider(settings)
    classifier = IntentClassifier(
        provider=provider,
        prompt_registry=create_default_prompt_registry(),
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        parse_retries=settings.intent_parse_retries,
    )
    try:
        result = await classifier.classify(question)
    except AppError as exc:
        print(
            json.dumps(
                {"success": False, "error_code": exc.code.value, "message": exc.message},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    except ValueError:
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": "VALIDATION_ERROR",
                    "message": "问题不能为空且长度不能超过 4000 个字符",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    finally:
        if isinstance(provider, OpenAICompatibleProvider):
            await provider.aclose()

    if result.value is None:
        error_code = result.error_code
        if error_code is None:
            raise AssertionError("structured output result must contain an error code")
        print(
            json.dumps(
                {
                    "success": False,
                    "error_code": error_code.value,
                    "message": "模型输出未通过意图 Schema 校验",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 3

    print(result.value.model_dump_json(indent=2))
    return 0


def main() -> None:
    """Parse arguments and run the asynchronous experiment."""
    arguments = _create_argument_parser().parse_args()
    raise SystemExit(asyncio.run(run_experiment(arguments.question, get_settings())))


if __name__ == "__main__":
    main()
