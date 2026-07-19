"""Provider-neutral LLM messages and token accounting types."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MessageRole(StrEnum):
    """Roles supported by the internal conversation contract."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(StrEnum):
    """Stable reasons why a model response stopped generating."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALL = "tool_call"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"


class ChatMessage(BaseModel):
    """A single immutable message sent to or returned by an LLM provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: MessageRole
    content: str

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value


class TokenUsage(BaseModel):
    """Validated token accounting reported by an LLM provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def total_must_match_parts(self) -> TokenUsage:
        expected_total = self.prompt_tokens + self.completion_tokens
        if self.total_tokens != expected_total:
            raise ValueError(
                "total_tokens must equal prompt_tokens + completion_tokens"
            )
        return self


class LLMRequest(BaseModel):
    """A validated, provider-neutral request for text generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1)
    model: str
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0.0)

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must not be blank")
        return value


class LLMResponse(BaseModel):
    """A complete response returned by an LLM provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage

    @field_validator("model")
    @classmethod
    def model_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must not be blank")
        return value


class StreamChunk(BaseModel):
    """One incremental piece of a streaming response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delta: str = ""
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None
