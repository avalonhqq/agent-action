"""Redis-backed cache for model-visible conversation history."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Sequence
from typing import Protocol, cast

from redis.asyncio import Redis

from bili_support.llm.types import ChatMessage, MessageRole


class ConversationHistoryCache(Protocol):
    async def get(self, thread_id: str) -> list[ChatMessage] | None: ...

    async def set(self, thread_id: str, messages: Sequence[ChatMessage]) -> None: ...


class NullConversationHistoryCache:
    async def get(self, thread_id: str) -> list[ChatMessage] | None:
        return None

    async def set(self, thread_id: str, messages: Sequence[ChatMessage]) -> None:
        return None


class RedisConversationHistoryCache:
    """Cache history as minimal role/content JSON with a bounded TTL."""

    def __init__(
        self,
        url: str,
        *,
        ttl_seconds: int = 900,
        max_messages: int = 100,
        client: Redis | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_messages <= 0:
            raise ValueError("max_messages must be positive")
        self._owns_client = client is None
        self._redis = client or Redis.from_url(url, decode_responses=True)
        self._ttl_seconds = ttl_seconds
        self._max_messages = max_messages

    async def ping(self) -> None:
        await cast("Awaitable[bool]", self._redis.ping())

    async def get(self, thread_id: str) -> list[ChatMessage] | None:
        raw = await self._redis.get(self._key(thread_id))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            if not isinstance(payload, list):
                return None
            return [ChatMessage.model_validate(item) for item in payload]
        except (json.JSONDecodeError, ValueError, TypeError):
            return None

    async def set(self, thread_id: str, messages: Sequence[ChatMessage]) -> None:
        payload = [
            {"role": message.role.value, "content": message.content}
            for message in messages
            if message.role in {MessageRole.USER, MessageRole.ASSISTANT}
        ][-self._max_messages :]
        await self._redis.set(
            self._key(thread_id),
            json.dumps(payload, ensure_ascii=False),
            ex=self._ttl_seconds,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._redis.aclose()

    @staticmethod
    def _key(thread_id: str) -> str:
        return f"bili-support:conversation:{thread_id}:history"
