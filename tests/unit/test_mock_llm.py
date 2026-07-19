"""Tests for the deterministic Mock LLM provider."""

import pytest

from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.provider import LLMProvider
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    MessageRole,
)


def _request() -> LLMRequest:
    return LLMRequest(
        messages=[
            ChatMessage(role=MessageRole.SYSTEM, content="你是客服助手。"),
            ChatMessage(role=MessageRole.USER, content="怎么关闭自动续费？"),
        ],
        model="mock-support-model",
    )


def test_mock_provider_satisfies_llm_provider_protocol() -> None:
    provider: LLMProvider = MockLLMProvider(response_text="固定回复")

    assert isinstance(provider, LLMProvider)


@pytest.mark.asyncio
async def test_complete_returns_configured_response_and_mock_usage() -> None:
    provider = MockLLMProvider(
        response_text="可以 关闭自动续费。",
        model="test-mock-model",
    )

    response = await provider.complete(_request())

    assert response.content == "可以 关闭自动续费。"
    assert response.model == "test-mock-model"
    assert response.finish_reason is FinishReason.STOP
    assert response.usage.prompt_tokens == 16
    assert response.usage.completion_tokens == 9
    assert response.usage.total_tokens == 25


@pytest.mark.asyncio
async def test_complete_is_deterministic_for_the_same_request() -> None:
    provider = MockLLMProvider(response_text="固定回复")
    request = _request()

    first = await provider.complete(request)
    second = await provider.complete(request)

    assert first == second


@pytest.mark.asyncio
async def test_stream_reconstructs_response_with_stable_chunks() -> None:
    response_text = "可以关闭自动续费。"
    provider = MockLLMProvider(response_text=response_text, chunk_size=3)

    first_chunks = [chunk async for chunk in provider.stream(_request())]
    second_chunks = [chunk async for chunk in provider.stream(_request())]

    assert first_chunks == second_chunks
    assert "".join(chunk.delta for chunk in first_chunks) == response_text
    assert [chunk.delta for chunk in first_chunks[:-1]] == [
        "可以关",
        "闭自动",
        "续费。",
    ]


@pytest.mark.asyncio
async def test_only_final_chunk_contains_finish_reason_and_usage() -> None:
    provider = MockLLMProvider(response_text="固定回复", chunk_size=2)

    chunks = [chunk async for chunk in provider.stream(_request())]

    assert all(chunk.finish_reason is None for chunk in chunks[:-1])
    assert all(chunk.usage is None for chunk in chunks[:-1])
    assert chunks[-1].delta == ""
    assert chunks[-1].finish_reason is FinishReason.STOP
    assert chunks[-1].usage is not None


@pytest.mark.asyncio
async def test_complete_and_stream_report_the_same_mock_usage() -> None:
    provider = MockLLMProvider(response_text="固定回复", chunk_size=2)
    request = _request()

    response = await provider.complete(request)
    chunks = [chunk async for chunk in provider.stream(request)]

    assert chunks[-1].usage == response.usage


@pytest.mark.parametrize(
    ("response_text", "model", "chunk_size"),
    [
        ("", "mock-model", 4),
        ("   ", "mock-model", 4),
        ("固定回复", "", 4),
        ("固定回复", "   ", 4),
        ("固定回复", "mock-model", 0),
        ("固定回复", "mock-model", -1),
    ],
)
def test_invalid_mock_configuration_fails_fast(
    response_text: str,
    model: str,
    chunk_size: int,
) -> None:
    with pytest.raises(ValueError):
        MockLLMProvider(
            response_text=response_text,
            model=model,
            chunk_size=chunk_size,
        )
