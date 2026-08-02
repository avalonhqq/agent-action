"""Tests for prompt, context, provider, and usage orchestration."""

import pytest

from bili_support.llm.context import RewriteReason
from bili_support.llm.errors import LLMUnavailableError
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.prompts import create_default_prompt_registry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.service import ChatService
from bili_support.llm.types import ChatMessage, LLMRequest, LLMResponse, MessageRole, StreamChunk
from bili_support.llm.usage import InMemoryUsageRecorder, UsageStatus


def _service(
    provider: LLMProvider,
    recorder: InMemoryUsageRecorder,
) -> ChatService:
    return ChatService(
        provider=provider,
        model="mock-support-model",
        prompt_registry=create_default_prompt_registry(),
        usage_recorder=recorder,
    )


@pytest.mark.asyncio
async def test_complete_rewrites_reference_and_records_safe_usage() -> None:
    recorder = InMemoryUsageRecorder()
    service = _service(MockLLMProvider(response_text="联通也支持。"), recorder)
    history = [ChatMessage(role=MessageRole.USER, content="移动大王卡支持免流吗？")]

    result = await service.complete(
        request_id="request-chat",
        user_message="那联通呢",
        history=history,
    )
    records = await recorder.snapshot()

    assert result.response.content == "联通也支持。"
    assert result.rewrite.standalone_query == "联通大王卡支持免流吗？"
    assert result.rewrite.reason is RewriteReason.ENTITY_SUBSTITUTION
    assert result.prompt_version == "support_answer:v1"
    assert records[0].status is UsageStatus.SUCCESS
    assert records[0].usage == result.response.usage


@pytest.mark.asyncio
async def test_grounded_complete_uses_evidence_prompt_instead_of_free_chat() -> None:
    recorder = InMemoryUsageRecorder()
    service = _service(MockLLMProvider(response_text="依据证据回答[E1]"), recorder)

    result = await service.complete(
        request_id="request-grounded",
        user_message="会员权益说明",
        history=[],
        evidence_context=(
            '{"evidence":[{"evidence_id":"E1",'
            '"content":"会员权益受版权和设备限制"}]}'
        ),
    )

    assert result.response.content == "依据证据回答[E1]"
    assert result.prompt_version == "grounded_support:v1"


class _UnavailableProvider:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMUnavailableError

    def stream(self, request: LLMRequest):
        async def chunks():
            if False:
                yield StreamChunk()
            raise LLMUnavailableError

        return chunks()


@pytest.mark.asyncio
async def test_service_records_safe_error_code_without_exception_text() -> None:
    recorder = InMemoryUsageRecorder()
    service = _service(_UnavailableProvider(), recorder)

    with pytest.raises(LLMUnavailableError):
        await service.complete(request_id="request-error", user_message="测试", history=[])

    records = await recorder.snapshot()
    assert records[0].status is UsageStatus.ERROR
    assert records[0].error_code == "MODEL_UNAVAILABLE"
    assert records[0].usage is None


@pytest.mark.asyncio
async def test_closing_stream_records_cancelled_without_prompt_content() -> None:
    recorder = InMemoryUsageRecorder()
    provider = MockLLMProvider(response_text="这是一段较长的流式回复。", chunk_size=2)
    service = _service(provider, recorder)
    stream = service.stream(request_id="request-close", user_message="测试关闭", history=[])

    first = await anext(stream)
    await stream.aclose()

    records = await recorder.snapshot()
    assert first.delta == "这是"
    assert records[0].status is UsageStatus.CANCELLED
    assert records[0].error_code == "stream_closed"
    assert "测试关闭" not in records[0].model_dump_json()
