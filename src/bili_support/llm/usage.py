"""Provider-neutral latency, token, and error accounting."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from bili_support.llm.types import TokenUsage


class UsageStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class UsageRecord(BaseModel):
    """One safe observability record without prompts or model responses."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    latency_ms: float = Field(ge=0)
    status: UsageStatus
    usage: TokenUsage | None = None
    error_code: str | None = None


class UsageRecorder(Protocol):
    """Storage boundary for model-call observability."""

    async def record(self, event: UsageRecord) -> None: ...


class InMemoryUsageRecorder:
    """Concurrency-safe recorder used until persistent observability arrives."""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = asyncio.Lock()

    async def record(self, event: UsageRecord) -> None:
        async with self._lock:
            self._records.append(event)

    async def snapshot(self) -> tuple[UsageRecord, ...]:
        async with self._lock:
            return tuple(self._records)
