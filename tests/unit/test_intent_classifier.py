"""Tests for schema-constrained intent model requests and experiments."""

from collections.abc import AsyncIterator

import pytest

from bili_support.core.config import Settings
from bili_support.intent import IntentClassifier, IntentRoute, build_intent_provider
from bili_support.intent.cli import run_experiment
from bili_support.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    MockLLMProvider,
    OpenAICompatibleProvider,
    StreamChunk,
    StructuredOutputError,
    TokenUsage,
    create_default_prompt_registry,
)


class _CapturingProvider:
    def __init__(self, response_content: str | list[str]) -> None:
        self.response_contents = (
            response_content if isinstance(response_content, list) else [response_content]
        )
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        response_index = min(len(self.requests) - 1, len(self.response_contents) - 1)
        return LLMResponse(
            content=self.response_contents[response_index],
            model=request.model,
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        if False:
            yield StreamChunk()


def _classifier(provider: _CapturingProvider) -> IntentClassifier:
    return IntentClassifier(
        provider=provider,
        prompt_registry=create_default_prompt_registry(),
        model="intent-test-model",
        temperature=0.1,
        max_tokens=300,
        timeout_seconds=8.0,
    )


def _valid_decision_json() -> str:
    return (
        '{"route":"supported","intents":[{"domain":"membership",'
        '"action":"cancel","confidence":0.92}],"entities":[],'
        '"sentiment":"neutral","risk":"low","confidence":0.92,'
        '"needs_clarification":false,"clarification_question":null,'
        '"source":"model"}'
    )


@pytest.mark.asyncio
async def test_classifier_builds_schema_constrained_request_and_parses_result() -> None:
    provider = _CapturingProvider(_valid_decision_json())

    result = await _classifier(provider).classify("  怎么取消大会员？  ")

    assert result.error_code is None
    assert result.value is not None
    assert result.value.route is IntentRoute.SUPPORTED
    request = provider.requests[0]
    assert request.model == "intent-test-model"
    assert request.temperature == 0.1
    assert request.max_tokens == 300
    assert request.timeout_seconds == 8.0
    assert request.structured_output is not None
    assert request.structured_output.name == "intent_decision"
    assert request.structured_output.strict is True
    assert request.structured_output.schema_definition["additionalProperties"] is False
    assert request.messages[1].content == "<user_query>\n怎么取消大会员？\n</user_query>"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_error"),
    [
        ("not-json", StructuredOutputError.INVALID_JSON),
        (
            '{"route":"supported","intents":[],"confidence":0.8,"source":"model"}',
            StructuredOutputError.SCHEMA_VALIDATION_FAILED,
        ),
    ],
)
async def test_classifier_safely_degrades_invalid_model_output(
    content: str, expected_error: StructuredOutputError
) -> None:
    result = await _classifier(_CapturingProvider(content)).classify("测试问题")

    assert result.value is None
    assert result.error_code is expected_error


@pytest.mark.asyncio
async def test_classifier_retries_once_and_recovers_schema_failure() -> None:
    provider = _CapturingProvider(
        [
            '{"route":"supported","intents":[],"confidence":0.8,"source":"model"}',
            _valid_decision_json(),
        ]
    )

    result = await _classifier(provider).classify("怎么取消大会员？")

    assert result.value is not None
    assert result.value.route is IntentRoute.SUPPORTED
    assert len(provider.requests) == 2
    assert "上一次生成未通过结构校验" in provider.requests[1].messages[0].content
    assert "上一次生成未通过结构校验" not in provider.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_blank_question_fails_before_provider_call() -> None:
    provider = _CapturingProvider(_valid_decision_json())

    with pytest.raises(ValueError, match="question must not be blank"):
        await _classifier(provider).classify("   ")

    assert provider.requests == []


def test_intent_provider_uses_task_specific_mock_by_default() -> None:
    settings = Settings(_env_file=None)

    provider = build_intent_provider(settings)

    assert isinstance(provider, MockLLMProvider)


def test_real_intent_provider_can_share_the_application_provider() -> None:
    settings = Settings(_env_file=None, llm_provider="openai_compatible")
    shared_provider = _CapturingProvider(_valid_decision_json())

    provider = build_intent_provider(settings, shared_provider=shared_provider)

    assert provider is shared_provider


@pytest.mark.asyncio
async def test_intent_provider_reuses_openai_compatible_configuration() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url="https://provider.example/v1",
        llm_api_key="local-test-key",
        llm_model="provider-model",
    )

    provider = build_intent_provider(settings)

    assert isinstance(provider, OpenAICompatibleProvider)
    await provider.aclose()


@pytest.mark.asyncio
async def test_cli_experiment_works_offline_with_default_mock(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = await run_experiment("怎么取消大会员？", Settings(_env_file=None))

    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"route": "supported"' in output
    assert '"source": "model"' in output
