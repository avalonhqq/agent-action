"""Public contracts and implementations for language model access."""

from bili_support.llm.context import (
    BoundedContextBuilder,
    QueryRewriteResult,
    RewriteReason,
    StandaloneQueryRewriter,
)
from bili_support.llm.errors import LLMResponseError, LLMUnavailableError
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.prompts import (
    PromptRegistry,
    PromptTemplate,
    create_default_prompt_registry,
)
from bili_support.llm.provider import LLMProvider
from bili_support.llm.service import ChatService
from bili_support.llm.structured import (
    StructuredOutputError,
    StructuredOutputParser,
    StructuredOutputResult,
)
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    MessageRole,
    StreamChunk,
    StructuredOutputSpec,
    TokenUsage,
)
from bili_support.llm.usage import InMemoryUsageRecorder, UsageRecord, UsageStatus

__all__ = [
    "BoundedContextBuilder",
    "ChatMessage",
    "ChatService",
    "FinishReason",
    "InMemoryUsageRecorder",
    "LLMProvider",
    "LLMRequest",
    "LLMResponseError",
    "LLMResponse",
    "LLMUnavailableError",
    "MessageRole",
    "MockLLMProvider",
    "OpenAICompatibleProvider",
    "PromptRegistry",
    "PromptTemplate",
    "QueryRewriteResult",
    "RewriteReason",
    "StandaloneQueryRewriter",
    "StreamChunk",
    "StructuredOutputError",
    "StructuredOutputParser",
    "StructuredOutputResult",
    "StructuredOutputSpec",
    "TokenUsage",
    "UsageRecord",
    "UsageStatus",
    "create_default_prompt_registry",
]
