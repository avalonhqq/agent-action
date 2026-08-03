"""Deterministic LLM provider for tests and local development."""

from __future__ import annotations

import json
import re
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
        response_text = self._response_for(request)
        return LLMResponse(
            content=response_text,
            model=self._model,
            finish_reason=FinishReason.STOP,
            usage=self._calculate_usage(request, response_text=response_text),
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
        *,
        response_text: str | None = None,
    ) -> TokenUsage:
        """Return deterministic character counts labeled as mock usage."""
        prompt_tokens = sum(
            self._mock_token_count(message.content) for message in request.messages
        )
        completion_tokens = self._mock_token_count(response_text or self._response_text)

        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    @staticmethod
    def _mock_token_count(text: str) -> int:
        """Count non-whitespace characters; this is not a real tokenizer."""
        return sum(1 for character in text if not character.isspace())

    def _response_for(self, request: LLMRequest) -> str:
        """Grounded结构化请求生成可校验本地样例，其余请求仍返回配置文本。"""

        if request.structured_output is None or request.structured_output.name != "grounded_answer":
            return self._response_text
        user_content = request.messages[-1].content
        match = re.search(
            r"<knowledge_evidence_json>\s*(.*?)\s*</knowledge_evidence_json>",
            user_content,
            flags=re.DOTALL,
        )
        if match is None:
            return self._response_text
        try:
            payload = json.loads(match.group(1))
            evidence = payload["evidence"][0]
            evidence_id = str(evidence["evidence_id"])
            claim = str(evidence["content"]).strip()
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return self._response_text
        return json.dumps(
            {
                "answer": f"{claim}[{evidence_id}]",
                "claims": [{"text": claim, "evidence_ids": [evidence_id]}],
                "used_evidence_ids": [evidence_id],
                "completeness": "complete",
            },
            ensure_ascii=False,
        )
