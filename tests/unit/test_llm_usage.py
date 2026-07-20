"""Tests for concurrency-safe, content-free model usage records."""

import asyncio

import pytest

from bili_support.llm.types import TokenUsage
from bili_support.llm.usage import InMemoryUsageRecorder, UsageRecord, UsageStatus


@pytest.mark.asyncio
async def test_usage_recorder_keeps_concurrent_records_without_prompt_content() -> None:
    recorder = InMemoryUsageRecorder()
    events = [
        UsageRecord(
            request_id=f"request-{index}",
            operation="complete",
            model="mock-model",
            prompt_version="support_answer:v1",
            latency_ms=1.0,
            status=UsageStatus.SUCCESS,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )
        for index in range(5)
    ]

    await asyncio.gather(*(recorder.record(event) for event in events))
    snapshot = await recorder.snapshot()

    assert len(snapshot) == 5
    assert {item.request_id for item in snapshot} == {f"request-{index}" for index in range(5)}
    assert "prompt" not in UsageRecord.model_fields
    assert "response" not in UsageRecord.model_fields
