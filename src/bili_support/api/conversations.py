"""Authenticated persisted conversation and message endpoints."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from bili_support.core.exceptions import AppError
from bili_support.core.security import AuthDependency, UserContext
from bili_support.schemas.common import ApiResponse
from bili_support.schemas.conversations import (
    ConversationMessageResult,
    ConversationView,
    CreateConversationRequest,
    MessageView,
    SendMessageRequest,
)
from bili_support.services.conversations import ConversationService


def create_conversation_router(
    service: ConversationService,
    authenticate: AuthDependency,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

    @router.post("", response_model=ApiResponse[ConversationView], status_code=201)
    async def create_conversation(
        payload: CreateConversationRequest,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[ConversationView]:
        conversation = await service.create(actor, payload.title)
        return ApiResponse(
            data=ConversationView.model_validate(conversation),
            request_id=_request_id(request),
        )

    @router.get("", response_model=ApiResponse[list[ConversationView]])
    async def list_conversations(
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[list[ConversationView]]:
        conversations = await service.list_conversations(actor)
        return ApiResponse(
            data=[ConversationView.model_validate(item) for item in conversations],
            request_id=_request_id(request),
        )

    @router.get("/{thread_id}/messages", response_model=ApiResponse[list[MessageView]])
    async def list_messages(
        thread_id: str,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[list[MessageView]]:
        messages = await service.messages(actor, thread_id)
        return ApiResponse(
            data=[MessageView.model_validate(item) for item in messages],
            request_id=_request_id(request),
        )

    @router.post(
        "/{thread_id}/messages",
        response_model=ApiResponse[ConversationMessageResult],
    )
    async def send_message(
        thread_id: str,
        payload: SendMessageRequest,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[ConversationMessageResult]:
        request_id = _request_id(request)
        result = await service.send(
            actor=actor,
            thread_id=thread_id,
            content=payload.content,
            request_id=request_id,
        )
        return ApiResponse(data=result, request_id=request_id)

    @router.post("/{thread_id}/messages/stream")
    async def stream_message(
        thread_id: str,
        payload: SendMessageRequest,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> StreamingResponse:
        request_id = _request_id(request)

        async def events() -> AsyncIterator[str]:
            try:
                stream = service.stream(
                    actor=actor,
                    thread_id=thread_id,
                    content=payload.content,
                    request_id=request_id,
                )
                async with aclosing(stream) as chunks:
                    async for chunk in chunks:
                        if await request.is_disconnected():
                            break
                        if chunk.delta:
                            yield _event("delta", {"delta": chunk.delta})
                        if chunk.finish_reason is not None:
                            yield _event(
                                "completed",
                                {
                                    "thread_id": thread_id,
                                    "request_id": request_id,
                                    "finish_reason": chunk.finish_reason.value,
                                    "usage": chunk.usage.model_dump() if chunk.usage else None,
                                },
                            )
            except asyncio.CancelledError:
                raise
            except AppError as exc:
                yield _event(
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


def _event(name: str, data: dict[str, object]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
