"""Minimal async adapter for the OpenAI Chat Completions-compatible contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bili_support.core.config import LLMStructuredOutputMode
from bili_support.llm.errors import LLMResponseError, LLMUnavailableError
from bili_support.llm.types import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class _RetryableStatusError(Exception):
    pass


class _ProviderUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class _ProviderMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None


class _ProviderChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _ProviderMessage
    finish_reason: str


class _CompletionEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model: str
    choices: list[_ProviderChoice] = Field(min_length=1)
    usage: _ProviderUsage


class _ProviderDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None


class _StreamChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta: _ProviderDelta
    finish_reason: str | None = None


class _StreamEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    choices: list[_StreamChoice] = Field(default_factory=list)
    usage: _ProviderUsage | None = None


class OpenAICompatibleProvider:
    """Map the compatible HTTP wire format to internal LLM contracts."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        structured_output_mode: LLMStructuredOutputMode = (
            LLMStructuredOutputMode.JSON_SCHEMA
        ),
        max_retries: int = 2,
        retry_base_delay: float = 0.1,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not base_url.strip():
            raise ValueError("base_url must not be blank")
        if max_retries < 0:
            raise ValueError("max_retries must not be negative")
        if retry_base_delay < 0:
            raise ValueError("retry_base_delay must not be negative")

        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._structured_output_mode = structured_output_mode
        self._sleep = sleep
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient()

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = self._payload(request, stream=False)
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                    timeout=request.timeout_seconds,
                )
                self._check_status(response)
                return self._parse_completion(response)
            except (httpx.TransportError, _RetryableStatusError) as exc:
                if attempt >= self._max_retries:
                    raise LLMUnavailableError() from exc
                await self._sleep(self._retry_base_delay * (2**attempt))
        raise AssertionError("retry loop must return or raise")

    async def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        payload = self._payload(request, stream=True)
        emitted = False
        for attempt in range(self._max_retries + 1):
            try:
                async with self._client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                    timeout=request.timeout_seconds,
                ) as response:
                    if response.status_code in _RETRYABLE_STATUS_CODES:
                        await response.aread()
                        raise _RetryableStatusError
                    if response.is_error:
                        raise LLMResponseError

                    saw_finish = False
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line.removeprefix("data:").strip()
                        if not data or data == "[DONE]":
                            continue
                        chunk = self._parse_stream_event(data)
                        if chunk is None:
                            continue
                        emitted = True
                        saw_finish = saw_finish or chunk.finish_reason is not None
                        yield chunk
                    if not saw_finish:
                        raise LLMResponseError
                    return
            except (httpx.TransportError, _RetryableStatusError) as exc:
                if emitted or attempt >= self._max_retries:
                    raise LLMUnavailableError() from exc
                await self._sleep(self._retry_base_delay * (2**attempt))
        raise AssertionError("retry loop must return or raise")

    async def aclose(self) -> None:
        """Close only a client created and owned by this adapter."""
        if self._owns_client:
            await self._client.aclose()

    def _payload(self, request: LLMRequest, *, stream: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": request.model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if request.structured_output is not None:
            if self._structured_output_mode is LLMStructuredOutputMode.JSON_OBJECT:
                payload["response_format"] = {"type": "json_object"}
            else:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": request.structured_output.name,
                        "strict": request.structured_output.strict,
                        "schema": request.structured_output.schema_definition,
                    },
                }
        return payload

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        if response.status_code in _RETRYABLE_STATUS_CODES:
            raise _RetryableStatusError
        if response.is_error:
            raise LLMResponseError

    @staticmethod
    def _parse_completion(response: httpx.Response) -> LLMResponse:
        try:
            envelope = _CompletionEnvelope.model_validate(response.json())
            choice = envelope.choices[0]
            usage = _to_usage(envelope.usage)
            finish_reason = _to_finish_reason(choice.finish_reason)
            if not choice.message.content or not choice.message.content.strip():
                raise ValueError("provider returned blank content")
            return LLMResponse(
                content=choice.message.content,
                model=envelope.model,
                finish_reason=finish_reason,
                usage=usage,
            )
        except (ValidationError, ValueError) as exc:
            raise LLMResponseError() from exc

    @staticmethod
    def _parse_stream_event(data: str) -> StreamChunk | None:
        try:
            envelope = _StreamEnvelope.model_validate_json(data)
            choice = envelope.choices[0] if envelope.choices else None
            delta = choice.delta.content or "" if choice else ""
            finish_reason = (
                _to_finish_reason(choice.finish_reason)
                if choice and choice.finish_reason
                else None
            )
            usage = _to_usage(envelope.usage) if envelope.usage else None
        except (ValidationError, ValueError) as exc:
            raise LLMResponseError() from exc
        if not delta and finish_reason is None and usage is None:
            return None
        return StreamChunk(delta=delta, finish_reason=finish_reason, usage=usage)


def _to_usage(usage: _ProviderUsage) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
    )


def _to_finish_reason(value: str) -> FinishReason:
    mapping = {
        "stop": FinishReason.STOP,
        "length": FinishReason.LENGTH,
        "tool_calls": FinishReason.TOOL_CALL,
        "function_call": FinishReason.TOOL_CALL,
        "content_filter": FinishReason.CONTENT_FILTER,
        "error": FinishReason.ERROR,
    }
    try:
        return mapping[value]
    except KeyError as exc:
        raise ValueError("unsupported finish reason") from exc
