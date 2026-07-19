"""Public contracts and implementations for language model access."""

from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.provider import LLMProvider
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    MessageRole,
    StreamChunk,
    TokenUsage,
)

__all__ = [
    "ChatMessage",
    "FinishReason",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MessageRole",
    "MockLLMProvider",
    "StreamChunk",
    "TokenUsage",
]
