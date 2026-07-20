"""Transactional conversation use cases built on repositories and ChatService."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from time import perf_counter

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.core.cache import ConversationHistoryCache, NullConversationHistoryCache
from bili_support.core.database import Database
from bili_support.core.exceptions import AppError, ResourceNotFoundError
from bili_support.core.security import UserContext
from bili_support.llm.service import ChatService
from bili_support.llm.types import ChatMessage, MessageRole, StreamChunk, TokenUsage
from bili_support.models.entities import Conversation, Message, ModelCall
from bili_support.repositories import (
    ConversationRepository,
    MessageRepository,
    ModelCallRepository,
    UserRepository,
)
from bili_support.schemas.conversations import ConversationMessageResult


class ConversationService:
    def __init__(
        self,
        database: Database,
        chat_service: ChatService,
        history_cache: ConversationHistoryCache | None = None,
    ) -> None:
        self._database = database
        self._chat = chat_service
        self._history_cache = history_cache or NullConversationHistoryCache()

    async def create(self, actor: UserContext, title: str) -> Conversation:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversation = await ConversationRepository(session).create(user.id, title)
            await session.refresh(conversation)
            await session.commit()
            return conversation

    async def list_conversations(self, actor: UserContext) -> list[Conversation]:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversations = await ConversationRepository(session).list_for_user(user.id)
            await session.commit()
            return conversations

    async def messages(self, actor: UserContext, thread_id: str) -> list[Message]:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversation = await self._owned_conversation(session, thread_id, user.id)
            messages = await MessageRepository(session).list_for_conversation(conversation.id)
            await session.commit()
            return messages

    async def send(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
    ) -> ConversationMessageResult:
        conversation_id, user_message_id, history = await self._save_user_message(
            actor=actor,
            thread_id=thread_id,
            content=content,
            request_id=request_id,
        )
        started = perf_counter()
        try:
            result = await self._chat.complete(
                request_id=request_id,
                user_message=content,
                history=history,
            )
        except asyncio.CancelledError:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation="complete",
                status="cancelled",
                started=started,
                usage=None,
                error_code="cancelled",
            )
            raise
        except AppError as exc:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation="complete",
                status="error",
                started=started,
                usage=None,
                error_code=exc.code.value,
            )
            raise
        except Exception:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation="complete",
                status="error",
                started=started,
                usage=None,
                error_code="INTERNAL_ERROR",
            )
            raise

        await self._persist_outcome(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            request_id=request_id,
            operation="complete",
            status="success",
            started=started,
            usage=result.response.usage,
            assistant_content=result.response.content,
        )
        return ConversationMessageResult(
            thread_id=thread_id,
            answer=result.response.content,
            model=result.response.model,
            finish_reason=result.response.finish_reason,
            usage=result.response.usage,
            prompt_version=result.prompt_version,
        )

    async def stream(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
    ) -> AsyncGenerator[StreamChunk, None]:
        conversation_id, user_message_id, history = await self._save_user_message(
            actor=actor,
            thread_id=thread_id,
            content=content,
            request_id=request_id,
        )
        started = perf_counter()
        answer_parts: list[str] = []
        usage: TokenUsage | None = None
        status = "cancelled"
        error_code: str | None = "stream_closed"
        try:
            async for chunk in self._chat.stream(
                request_id=request_id,
                user_message=content,
                history=history,
            ):
                if chunk.delta:
                    answer_parts.append(chunk.delta)
                usage = chunk.usage or usage
                yield chunk
            status = "success"
            error_code = None
        except asyncio.CancelledError:
            error_code = "cancelled"
            raise
        except AppError as exc:
            status = "error"
            error_code = exc.code.value
            raise
        except Exception:
            status = "error"
            error_code = "INTERNAL_ERROR"
            raise
        finally:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation="stream",
                status=status,
                started=started,
                usage=usage,
                error_code=error_code,
                assistant_content="".join(answer_parts) if status == "success" else None,
            )

    async def _save_user_message(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
    ) -> tuple[str, str, list[ChatMessage]]:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversations = ConversationRepository(session)
            conversation = await self._owned_conversation(session, thread_id, user.id)
            messages = MessageRepository(session)
            cached_history = await self._cached_history(thread_id)
            previous = (
                await messages.list_for_conversation(conversation.id)
                if cached_history is None
                else []
            )
            user_message = messages.add(
                conversation_id=conversation.id,
                role=MessageRole.USER.value,
                content=content,
                request_id=request_id,
            )
            conversations.touch(conversation)
            await session.flush()
            await session.commit()
            history = cached_history or [
                ChatMessage(role=MessageRole(item.role), content=item.content) for item in previous
            ]
            await self._store_history(
                thread_id,
                [*history, ChatMessage(role=MessageRole.USER, content=content)],
            )
            return conversation.id, user_message.id, history

    async def _persist_outcome(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        request_id: str,
        operation: str,
        status: str,
        started: float,
        usage: TokenUsage | None,
        error_code: str | None = None,
        assistant_content: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            assistant_message_id = None
            if assistant_content:
                assistant_message = MessageRepository(session).add(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT.value,
                    content=assistant_content,
                    request_id=request_id,
                )
                await session.flush()
                assistant_message_id = assistant_message.id
            ModelCallRepository(session).add(
                ModelCall(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    request_id=request_id,
                    operation=operation,
                    model=self._chat.model,
                    prompt_version=self._chat.prompt_version,
                    status=status,
                    latency_ms=(perf_counter() - started) * 1000,
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                    error_code=error_code,
                )
            )
            await session.commit()
        if assistant_content:
            cached = await self._cached_history_by_conversation(conversation_id)
            if cached is not None:
                thread_id, history, cache_hit = cached
                await self._store_history(
                    thread_id,
                    history
                    if not cache_hit
                    else [
                        *history,
                        ChatMessage(
                            role=MessageRole.ASSISTANT,
                            content=assistant_content,
                        ),
                    ],
                )

    async def _cached_history(self, thread_id: str) -> list[ChatMessage] | None:
        try:
            return await self._history_cache.get(thread_id)
        except RedisError:
            return None

    async def _store_history(
        self, thread_id: str, history: list[ChatMessage]
    ) -> None:
        try:
            await self._history_cache.set(thread_id, history)
        except RedisError:
            return

    async def _cached_history_by_conversation(
        self, conversation_id: str
    ) -> tuple[str, list[ChatMessage], bool] | None:
        async with self._database.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            history = await self._cached_history(conversation.thread_id)
            cache_hit = history is not None
            if history is None:
                messages = await MessageRepository(session).list_for_conversation(
                    conversation_id
                )
                history = [
                    ChatMessage(role=MessageRole(item.role), content=item.content)
                    for item in messages
                ]
            return conversation.thread_id, history, cache_hit

    @staticmethod
    async def _owned_conversation(
        session: AsyncSession, thread_id: str, user_id: str
    ) -> Conversation:
        conversation = await ConversationRepository(session).get_for_user(thread_id, user_id)
        if conversation is None:
            raise ResourceNotFoundError("会话不存在")
        return conversation
