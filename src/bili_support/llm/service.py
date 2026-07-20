"""Application service combining prompts, context, providers, and usage."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter

from pydantic import BaseModel, ConfigDict

from bili_support.core.exceptions import AppError
from bili_support.llm.context import (
    BoundedContextBuilder,
    QueryRewriteResult,
    StandaloneQueryRewriter,
)
from bili_support.llm.prompts import PromptRegistry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.types import (
    ChatMessage,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)
from bili_support.llm.usage import UsageRecord, UsageRecorder, UsageStatus


class ChatCompletionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    response: LLMResponse
    rewrite: QueryRewriteResult
    prompt_version: str


class ChatService:
    """Prepare bounded requests and account for every provider call."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        prompt_registry: PromptRegistry,
        usage_recorder: UsageRecorder,
        context_builder: BoundedContextBuilder | None = None,
        rewriter: StandaloneQueryRewriter | None = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._provider = provider
        self._model = model
        self._prompt_registry = prompt_registry
        self._usage_recorder = usage_recorder
        self._context_builder = context_builder or BoundedContextBuilder()
        self._rewriter = rewriter or StandaloneQueryRewriter()
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    @property
    def prompt_version(self) -> str:
        return self._prompt_registry.get("support_answer").identifier

    async def complete(
        self,
        *,
        request_id: str,
        user_message: str,
        history: list[ChatMessage],
    ) -> ChatCompletionResult:
        request, rewrite, prompt_version = self._prepare(user_message, history)
        started = perf_counter()
        try:
            response = await self._provider.complete(request)
        except asyncio.CancelledError:
            await self._record(
                request_id,
                "complete",
                prompt_version,
                started,
                UsageStatus.CANCELLED,
                None,
                "cancelled",
            )
            raise
        except AppError as exc:
            await self._record(
                request_id,
                "complete",
                prompt_version,
                started,
                UsageStatus.ERROR,
                None,
                exc.code.value,
            )
            raise
        except Exception:
            await self._record(
                request_id,
                "complete",
                prompt_version,
                started,
                UsageStatus.ERROR,
                None,
                "unexpected_provider_error",
            )
            raise
        await self._record(
            request_id,
            "complete",
            prompt_version,
            started,
            UsageStatus.SUCCESS,
            response.usage,
            None,
        )
        return ChatCompletionResult(
            response=response,
            rewrite=rewrite,
            prompt_version=prompt_version,
        )

    async def stream(
        self,
        *,
        request_id: str,
        user_message: str,
        history: list[ChatMessage],
    ) -> AsyncGenerator[StreamChunk, None]:
        request, _, prompt_version = self._prepare(user_message, history)
        started = perf_counter()
        usage = None
        status = UsageStatus.CANCELLED
        error_code: str | None = "stream_closed"
        try:
            async for chunk in self._provider.stream(request):
                usage = chunk.usage or usage
                yield chunk
            status = UsageStatus.SUCCESS
            error_code = None
        except asyncio.CancelledError:
            error_code = "cancelled"
            raise
        except AppError as exc:
            status = UsageStatus.ERROR
            error_code = exc.code.value
            raise
        except Exception:
            status = UsageStatus.ERROR
            error_code = "unexpected_provider_error"
            raise
        finally:
            await self._record(
                request_id, "stream", prompt_version, started, status, usage, error_code
            )

    def _prepare(
        self,
        user_message: str,
        history: list[ChatMessage],
    ) -> tuple[LLMRequest, QueryRewriteResult, str]:
        rewrite = self._rewriter.rewrite(user_message, history)
        prompt = self._prompt_registry.get("support_answer")
        rendered = prompt.render({"question": rewrite.standalone_query})
        window = self._context_builder.build(
            system_message=rendered[0],
            history=history,
            current_message=rendered[1],
        )
        request = LLMRequest(
            messages=window.messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout_seconds=self._timeout_seconds,
        )
        return request, rewrite, prompt.identifier

    async def _record(
        self,
        request_id: str,
        operation: str,
        prompt_version: str,
        started: float,
        status: UsageStatus,
        usage: TokenUsage | None,
        error_code: str | None,
    ) -> None:
        await self._usage_recorder.record(
            UsageRecord(
                request_id=request_id,
                operation=operation,
                model=self._model,
                prompt_version=prompt_version,
                latency_ms=(perf_counter() - started) * 1000,
                status=status,
                usage=usage,
                error_code=error_code,
            )
        )
