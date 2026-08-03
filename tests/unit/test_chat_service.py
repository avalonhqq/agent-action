"""Tests for prompt, context, provider, and usage orchestration."""

import pytest

from bili_support.llm.context import RewriteReason
from bili_support.llm.errors import LLMUnavailableError
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.prompts import create_default_prompt_registry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.service import ChatService
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    MessageRole,
    StreamChunk,
    TokenUsage,
)
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


@pytest.mark.asyncio
async def test_grounded_v2_is_parsed_and_verified_before_publish() -> None:
    recorder = InMemoryUsageRecorder()
    service = _service(MockLLMProvider(response_text="普通Mock回复"), recorder)

    result = await service.complete_grounded(
        request_id="request-grounded-v2",
        user_message="多久生效？",
        history=[],
        evidence_context=(
            '{"evidence":[{"evidence_id":"E1","document_title":"大会员说明",'
            '"business_domain":"membership","content":"支付成功后立即生效。"}]}'
        ),
    )

    assert result.prompt_version == "grounded_support:v4"
    assert result.grounded_answer is not None
    assert result.grounded_answer.used_evidence_ids == ("E1",)
    assert result.verification is not None
    assert result.verification.decision.value == "pass"


class _GroundedSequenceProvider:
    """先返回损坏结构、再返回合法Grounded对象，验证专用格式重试。"""

    def __init__(self, responses: tuple[str, ...]) -> None:
        self._responses = responses
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        content = self._responses[len(self.requests) - 1]
        return LLMResponse(
            content=content,
            model="sequence-model",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    def stream(self, request: LLMRequest):
        async def chunks():
            if False:
                yield StreamChunk()

        return chunks()


@pytest.mark.asyncio
async def test_grounded_structure_failure_retries_once_without_failed_raw_text() -> None:
    valid = (
        '{"answer":"支付成功后立即生效[E1]。","claims":['
        '{"text":"支付成功后立即生效。","evidence_ids":["E1"]}],'
        '"used_evidence_ids":["E1"],"completeness":"complete"}'
    )
    provider = _GroundedSequenceProvider(("不是JSON的失败原文", valid))
    recorder = InMemoryUsageRecorder()
    service = _service(provider, recorder)

    result = await service.complete_grounded(
        request_id="request-grounded-repair",
        user_message="多久生效？",
        history=[],
        evidence_context=(
            '{"evidence":[{"evidence_id":"E1",'
            '"content":"支付成功后立即生效。"}]}'
        ),
    )
    records = await recorder.snapshot()

    assert result.error_code is None
    assert result.grounded_answer is not None
    assert result.response.usage.total_tokens == 30
    assert len(provider.requests) == 2
    assert records[0].error_code == "invalid_json"
    assert records[1].operation == "complete:grounded_repair"
    repair_system = provider.requests[1].messages[0].content
    assert "上一次生成未通过JSON结构校验" in repair_system
    assert "不是JSON的失败原文" not in repair_system


@pytest.mark.asyncio
async def test_grounded_unknown_evidence_is_not_treated_as_format_retry() -> None:
    invented = (
        '{"answer":"支持退款[E9]。","claims":['
        '{"text":"支持退款。","evidence_ids":["E9"]}],'
        '"used_evidence_ids":["E9"],"completeness":"complete"}'
    )
    provider = _GroundedSequenceProvider((invented,))
    service = _service(provider, InMemoryUsageRecorder())

    result = await service.complete_grounded(
        request_id="request-grounded-invented-id",
        user_message="能退款吗？",
        history=[],
        evidence_context=(
            '{"evidence":[{"evidence_id":"E1",'
            '"content":"成功开通后通常不支持无理由退款。"}]}'
        ),
    )

    assert result.error_code == "unknown_evidence_id"
    assert len(provider.requests) == 1


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
