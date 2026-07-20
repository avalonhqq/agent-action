"""Tests for minimal and bounded Redis conversation-history caching."""

import json
from typing import cast

import pytest
from redis.asyncio import Redis

from bili_support.core.cache import RedisConversationHistoryCache
from bili_support.llm.types import ChatMessage, MessageRole


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.last_ttl: int | None = None

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.last_ttl = ex
        return True


@pytest.mark.asyncio
async def test_redis_cache_stores_only_conversation_roles_with_ttl() -> None:
    fake = _FakeRedis()
    cache = RedisConversationHistoryCache(
        "redis://unused",
        ttl_seconds=60,
        max_messages=2,
        client=cast(Redis, fake),
    )
    history = [
        ChatMessage(role=MessageRole.SYSTEM, content="内部指令"),
        ChatMessage(role=MessageRole.USER, content="用户问题"),
        ChatMessage(role=MessageRole.ASSISTANT, content="客服回答"),
    ]

    await cache.set("thread-1", history)
    restored = await cache.get("thread-1")

    assert restored == history[1:]
    assert fake.last_ttl == 60
    payload = json.loads(fake.values["bili-support:conversation:thread-1:history"])
    assert payload == [
        {"role": "user", "content": "用户问题"},
        {"role": "assistant", "content": "客服回答"},
    ]


@pytest.mark.asyncio
async def test_corrupt_cache_is_treated_as_a_miss() -> None:
    fake = _FakeRedis()
    fake.values["bili-support:conversation:thread-2:history"] = "not-json"
    cache = RedisConversationHistoryCache(
        "redis://unused",
        client=cast(Redis, fake),
    )

    assert await cache.get("thread-2") is None
    await cache.ping()
