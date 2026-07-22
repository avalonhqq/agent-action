"""Tests for the minimal OpenAI Chat Completions-compatible adapter."""

import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from bili_support.core.config import LLMStructuredOutputMode
from bili_support.llm.errors import LLMResponseError, LLMUnavailableError
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.structured import StructuredOutputParser
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    MessageRole,
)


class _StructuredAnswer(BaseModel):
    answer: str


def _request() -> LLMRequest:
    return LLMRequest(
        messages=[ChatMessage(role=MessageRole.USER, content="测试问题")],
        model="compatible-test-model",
        temperature=0.2,
        max_tokens=128,
        timeout_seconds=3.0,
    )


def _completion_response() -> dict[str, object]:
    return {
        "model": "compatible-test-model",
        "choices": [
            {
                "message": {"content": "固定兼容回复"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 4,
            "total_tokens": 7,
        },
    }


@pytest.mark.asyncio
async def test_complete_maps_internal_request_and_provider_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://models.example/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert payload["model"] == "compatible-test-model"
        assert payload["messages"] == [{"role": "user", "content": "测试问题"}]
        assert payload["stream"] is False
        return httpx.Response(200, json=_completion_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1/",
        api_key="test-key",
        client=client,
    )

    response = await provider.complete(_request())

    assert response.content == "固定兼容回复"
    assert response.model == "compatible-test-model"
    assert response.finish_reason is FinishReason.STOP
    assert response.usage.total_tokens == 7
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_maps_provider_neutral_json_schema_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        response_format = payload["response_format"]
        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "support_answer"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["schema"]["type"] == "object"
        return httpx.Response(200, json=_completion_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        client=client,
    )
    base_request = _request()
    request = base_request.model_copy(
        update={
            "structured_output": StructuredOutputParser(_StructuredAnswer).specification(
                "support_answer"
            )
        }
    )

    await provider.complete(request)
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_can_map_structured_request_to_json_object_mode() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json=_completion_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://api.deepseek.com",
        structured_output_mode=LLMStructuredOutputMode.JSON_OBJECT,
        client=client,
    )
    request = _request().model_copy(
        update={
            "structured_output": StructuredOutputParser(_StructuredAnswer).specification(
                "support_answer"
            )
        }
    )

    await provider.complete(request)
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_retries_transient_status_with_exponential_delays() -> None:
    attempts = 0
    delays: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=_completion_response())

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        max_retries=2,
        retry_base_delay=0.25,
        client=client,
        sleep=fake_sleep,
    )

    response = await provider.complete(_request())

    assert response.content == "固定兼容回复"
    assert attempts == 3
    assert delays == [0.25, 0.5]
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_retries_transport_error_then_reports_unavailable() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    async def no_sleep(delay: float) -> None:
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        max_retries=1,
        client=client,
        sleep=no_sleep,
    )

    with pytest.raises(LLMUnavailableError):
        await provider.complete(_request())

    assert attempts == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_does_not_retry_non_transient_client_error() -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, json={"error": {"message": "sensitive provider detail"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        client=client,
    )

    with pytest.raises(LLMResponseError) as exc_info:
        await provider.complete(_request())

    assert attempts == 1
    assert "sensitive provider detail" not in str(exc_info.value)
    await client.aclose()


@pytest.mark.asyncio
async def test_complete_rejects_malformed_success_response() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []}))
    )
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        client=client,
    )

    with pytest.raises(LLMResponseError):
        await provider.complete(_request())

    await client.aclose()


@pytest.mark.asyncio
async def test_complete_rejects_blank_provider_content() -> None:
    response_body = {
        "model": "test-model",
        "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1},
    }
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=response_body)
        )
    )
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        client=client,
    )

    with pytest.raises(LLMResponseError):
        await provider.complete(_request())

    await client.aclose()


@pytest.mark.asyncio
async def test_stream_maps_sse_delta_finish_and_usage() -> None:
    body = "\n".join(
        [
            'data: {"choices":[{"delta":{"content":"你好"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{"content":"客服"},"finish_reason":null}]}',
            (
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
                '"usage":{"prompt_tokens":2,"completion_tokens":2,"total_tokens":4}}'
            ),
            "data: [DONE]",
            "",
        ]
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}
        return httpx.Response(200, text=body, headers={"Content-Type": "text/event-stream"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        client=client,
    )

    chunks = [chunk async for chunk in provider.stream(_request())]

    assert "".join(chunk.delta for chunk in chunks) == "你好客服"
    assert chunks[-1].finish_reason is FinishReason.STOP
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 4
    await client.aclose()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_retry() -> None:
    started = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.Event().wait()
        return httpx.Response(200, json=_completion_response())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="https://models.example/v1",
        client=client,
    )

    task: asyncio.Task[object] = asyncio.create_task(provider.complete(_request()))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    await client.aclose()


def test_invalid_adapter_configuration_fails_fast() -> None:
    async def no_sleep(delay: float) -> None:
        return None

    invalid: list[dict[str, object]] = [
        {"base_url": ""},
        {"base_url": "https://models.example/v1", "max_retries": -1},
        {"base_url": "https://models.example/v1", "retry_base_delay": -0.1},
    ]
    for arguments in invalid:
        with pytest.raises(ValueError):
            OpenAICompatibleProvider(**arguments, sleep=no_sleep)  # type: ignore[arg-type]
