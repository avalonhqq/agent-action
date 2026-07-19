"""Contract tests for the provider-neutral LLM protocol."""

from collections.abc import AsyncIterator

import pytest

from bili_support.llm.provider import LLMProvider
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    MessageRole,
    StreamChunk,
    TokenUsage,
)


class _ProtocolExampleProvider:
    """A test-only structural implementation, not the Week 2 Mock provider."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        usage = TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        return LLMResponse(
            content="固定测试回复",
            model=request.model,
            finish_reason=FinishReason.STOP,
            usage=usage,
        )

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=request.messages[-1].content)
        yield StreamChunk(finish_reason=FinishReason.STOP)


def _request() -> LLMRequest:
    return LLMRequest(
        messages=[ChatMessage(role=MessageRole.USER, content="测试问题")],
        model="protocol-test-model",
    )


def test_structural_implementation_satisfies_runtime_protocol() -> None:
    provider: LLMProvider = _ProtocolExampleProvider()

    assert isinstance(provider, LLMProvider)


@pytest.mark.asyncio
async def test_protocol_supports_complete_and_direct_async_iteration() -> None:
    provider: LLMProvider = _ProtocolExampleProvider()

    response = await provider.complete(_request())
    chunks = [chunk async for chunk in provider.stream(_request())]

    assert response.content == "固定测试回复"
    assert "".join(chunk.delta for chunk in chunks) == "测试问题"
    assert chunks[-1].finish_reason is FinishReason.STOP
