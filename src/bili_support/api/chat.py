"""HTTP and SSE chat endpoints backed by the provider-neutral ChatService."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bili_support.core.exceptions import AppError
from bili_support.llm.context import RewriteReason
from bili_support.llm.service import ChatService
from bili_support.llm.types import ChatMessage, FinishReason, MessageRole, TokenUsage
from bili_support.schemas.common import ApiResponse


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    history: list[ChatMessage] = Field(default_factory=list, max_length=100)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value

    @field_validator("history")
    @classmethod
    def history_must_contain_only_conversation_roles(
        cls, value: list[ChatMessage]
    ) -> list[ChatMessage]:
        if any(item.role not in {MessageRole.USER, MessageRole.ASSISTANT} for item in value):
            raise ValueError("history may contain only user and assistant messages")
        return value


class ChatResponseData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage
    standalone_query: str
    rewrite_reason: RewriteReason
    prompt_version: str


def create_chat_router(service: ChatService) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["chat"])

    @router.post("/chat", response_model=ApiResponse[ChatResponseData])
    async def chat(payload: ChatRequest, request: Request) -> ApiResponse[ChatResponseData]:
        request_id = _request_id(request)
        result = await service.complete(
            request_id=request_id,
            user_message=payload.message,
            history=payload.history,
        )
        return ApiResponse(
            data=ChatResponseData(
                answer=result.response.content,
                model=result.response.model,
                finish_reason=result.response.finish_reason,
                usage=result.response.usage,
                standalone_query=result.rewrite.standalone_query,
                rewrite_reason=result.rewrite.reason,
                prompt_version=result.prompt_version,
            ),
            request_id=request_id,
        )

    @router.post("/chat/stream")
    async def stream_chat(payload: ChatRequest, request: Request) -> StreamingResponse:
        request_id = _request_id(request)

        async def events() -> AsyncIterator[str]:
            try:
                stream = service.stream(
                    request_id=request_id,
                    user_message=payload.message,
                    history=payload.history,
                )
                async with aclosing(stream) as chunks:
                    async for chunk in chunks:
                        if await request.is_disconnected():
                            break
                        if chunk.delta:
                            yield _sse_event("delta", {"delta": chunk.delta})
                        if chunk.finish_reason is not None:
                            yield _sse_event(
                                "completed",
                                {
                                    "finish_reason": chunk.finish_reason.value,
                                    "usage": chunk.usage.model_dump() if chunk.usage else None,
                                    "request_id": request_id,
                                },
                            )
            except asyncio.CancelledError:
                raise
            except AppError as exc:
                yield _sse_event(
                    "error",
                    {
                        "code": exc.code.value,
                        "message": exc.message,
                        "request_id": request_id,
                    },
                )

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))


def _sse_event(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
