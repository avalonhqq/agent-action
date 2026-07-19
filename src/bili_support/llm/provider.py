"""Provider-neutral language model capability contract."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from bili_support.llm.types import LLMRequest, LLMResponse, StreamChunk


@runtime_checkable
class LLMProvider(Protocol):
    """Capabilities required from every language model provider."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate one complete response for a validated request."""
        ...

    def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]:
        """Return an asynchronous sequence of response chunks."""
        ...
