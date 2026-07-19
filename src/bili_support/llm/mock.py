"""Deterministic LLM provider for tests and local development."""

from __future__ import annotations

from collections.abc import AsyncIterator

from bili_support.llm.types import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    StreamChunk,
    TokenUsage,
)


class MockLLMProvider:
    """Return a fixed response without network access or randomness."""

    def __init__(
        self,
        *,
        response_text: str,
        model: str = "mock-support-model",
        chunk_size: int = 4,
    ) -> None:
        if not response_text.strip():
            raise ValueError("response_text must not be blank")

        if not model.strip():
            raise ValueError("model must not be blank")

        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")

        self._response_text = response_text
        self._model = model
        self._chunk_size = chunk_size

    async def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        """Return the configured response as one complete result."""
        return LLMResponse(
            content=self._response_text,
            model=self._model,
            finish_reason=FinishReason.STOP,
            usage=self._calculate_usage(request),
        )

    async def stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[StreamChunk]:
        """Yield deterministic text chunks followed by final metadata."""
        for start in range(
            0,
            len(self._response_text),
            self._chunk_size,
        ):
            yield StreamChunk(
                delta=self._response_text[start : start + self._chunk_size]
            )

        yield StreamChunk(
            finish_reason=FinishReason.STOP,
            usage=self._calculate_usage(request),
        )

    def _calculate_usage(
        self,
        request: LLMRequest,
    ) -> TokenUsage:
        """Return deterministic character counts labeled as mock usage."""
        prompt_tokens = sum(
            self._mock_token_count(message.content) for message in request.messages
        )
        completion_tokens = self._mock_token_count(self._response_text)

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    @staticmethod
    def _mock_token_count(text: str) -> int:
        """Count non-whitespace characters; this is not a real tokenizer."""
        return sum(1 for character in text if not character.isspace())
