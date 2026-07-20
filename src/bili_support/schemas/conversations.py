"""API contracts for persisted conversations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bili_support.llm.types import FinishReason, TokenUsage


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="新会话", max_length=120)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=4000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value.strip()


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    role: str
    content: str
    request_id: str
    created_at: datetime


class ConversationMessageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    answer: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage
    prompt_version: str
