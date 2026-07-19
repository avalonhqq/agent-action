"""Unit tests for provider-neutral LLM message and usage types."""

import pytest
from pydantic import ValidationError

from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    MessageRole,
    StreamChunk,
    TokenUsage,
)


def test_chat_message_accepts_a_supported_role() -> None:
    message = ChatMessage(role=MessageRole.USER, content="如何关闭自动续费？")

    assert message.role is MessageRole.USER
    assert message.content == "如何关闭自动续费？"


@pytest.mark.parametrize("content", ["", "   ", "\t\n"])
def test_chat_message_rejects_blank_content(content: str) -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role=MessageRole.USER, content=content)


def test_chat_message_rejects_an_unknown_role() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="customer", content="测试")  # type: ignore[arg-type]


def test_finish_reason_serializes_as_a_string() -> None:
    assert FinishReason.STOP.value == "stop"
    assert str(FinishReason.TOOL_CALL) == "tool_call"


def test_token_usage_accepts_consistent_non_negative_values() -> None:
    usage = TokenUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20)

    assert usage.total_tokens == 20


def test_token_usage_rejects_negative_values() -> None:
    with pytest.raises(ValidationError):
        TokenUsage(prompt_tokens=-1, completion_tokens=1, total_tokens=0)


def test_token_usage_rejects_an_inconsistent_total() -> None:
    with pytest.raises(ValidationError) as exc_info:
        TokenUsage(prompt_tokens=12, completion_tokens=8, total_tokens=21)

    assert "total_tokens" in str(exc_info.value)


def test_llm_request_accepts_valid_messages_and_defaults() -> None:
    request = LLMRequest(
        messages=[ChatMessage(role=MessageRole.USER, content="如何关闭自动续费？")],
        model="mock-support-model",
    )

    assert request.temperature == 0.0
    assert request.max_tokens == 512
    assert request.timeout_seconds == 30.0


def test_llm_request_rejects_empty_messages() -> None:
    with pytest.raises(ValidationError):
        LLMRequest(messages=[], model="mock-support-model")


@pytest.mark.parametrize("model", ["", "   ", "\t\n"])
def test_llm_request_rejects_blank_model(model: str) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            messages=[ChatMessage(role=MessageRole.USER, content="测试")],
            model=model,
        )


@pytest.mark.parametrize("temperature", [-0.01, 2.01])
def test_llm_request_rejects_temperature_outside_range(temperature: float) -> None:
    with pytest.raises(ValidationError):
        LLMRequest(
            messages=[ChatMessage(role=MessageRole.USER, content="测试")],
            model="mock-support-model",
            temperature=temperature,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("max_tokens", 0), ("timeout_seconds", 0.0)],
)
def test_llm_request_rejects_non_positive_limits(
    field_name: str,
    value: int | float,
) -> None:
    request_data: dict[str, object] = {
        "messages": [ChatMessage(role=MessageRole.USER, content="测试")],
        "model": "mock-support-model",
        field_name: value,
    }

    with pytest.raises(ValidationError):
        LLMRequest.model_validate(request_data)


def test_llm_response_keeps_complete_result() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    response = LLMResponse(
        content="可以在自动续费管理页面关闭。",
        model="mock-support-model",
        finish_reason=FinishReason.STOP,
        usage=usage,
    )

    assert response.content == "可以在自动续费管理页面关闭。"
    assert response.finish_reason is FinishReason.STOP
    assert response.usage is usage


def test_llm_response_rejects_blank_model() -> None:
    with pytest.raises(ValidationError):
        LLMResponse(
            content="测试回复",
            model="   ",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def test_stream_chunk_allows_a_delta_without_completion_metadata() -> None:
    chunk = StreamChunk(delta="自动续费")

    assert chunk.delta == "自动续费"
    assert chunk.finish_reason is None
    assert chunk.usage is None


def test_final_stream_chunk_can_include_finish_reason_and_usage() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    chunk = StreamChunk(finish_reason=FinishReason.STOP, usage=usage)

    assert chunk.delta == ""
    assert chunk.finish_reason is FinishReason.STOP
    assert chunk.usage is usage
