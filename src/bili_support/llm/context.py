"""Bounded conversation windows and conservative standalone-query rewriting."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from bili_support.llm.types import ChatMessage, MessageRole


class RewriteReason(StrEnum):
    ENTITY_SUBSTITUTION = "entity_substitution"
    UNCHANGED_SUFFICIENT = "unchanged_sufficient"
    UNCHANGED_UNSAFE = "unchanged_unsafe"


class QueryRewriteResult(BaseModel):
    """A standalone query and an auditable reason code, not private reasoning."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    original_query: str
    standalone_query: str
    rewritten: bool
    reason: RewriteReason


class ContextWindow(BaseModel):
    """The bounded messages sent to a provider and truncation metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    messages: list[ChatMessage]
    dropped_messages: int
    summary_created: bool


class StandaloneQueryRewriter:
    """Resolve only high-confidence carrier substitutions; otherwise preserve input."""

    _entities = ("移动", "联通", "电信")

    def rewrite(self, query: str, history: list[ChatMessage]) -> QueryRewriteResult:
        normalized = query.strip()
        previous = next(
            (item.content for item in reversed(history) if item.role is MessageRole.USER),
            None,
        )
        if previous and normalized.startswith("那") and normalized.endswith("呢"):
            new_entity = next((item for item in self._entities if item in normalized), None)
            old_entity = next((item for item in self._entities if item in previous), None)
            if new_entity and old_entity and new_entity != old_entity:
                return QueryRewriteResult(
                    original_query=normalized,
                    standalone_query=previous.replace(old_entity, new_entity),
                    rewritten=True,
                    reason=RewriteReason.ENTITY_SUBSTITUTION,
                )

        reason = (
            RewriteReason.UNCHANGED_SUFFICIENT
            if len(normalized) >= 8
            else RewriteReason.UNCHANGED_UNSAFE
        )
        return QueryRewriteResult(
            original_query=normalized,
            standalone_query=normalized,
            rewritten=False,
            reason=reason,
        )


class BoundedContextBuilder:
    """Keep recent messages and summarize dropped history deterministically."""

    def __init__(self, *, max_messages: int = 8, summary_max_chars: int = 500) -> None:
        if max_messages < 3:
            raise ValueError("max_messages must be at least three")
        if summary_max_chars <= 0:
            raise ValueError("summary_max_chars must be positive")
        self._max_messages = max_messages
        self._summary_max_chars = summary_max_chars

    def build(
        self,
        *,
        system_message: ChatMessage,
        history: list[ChatMessage],
        current_message: ChatMessage,
    ) -> ContextWindow:
        safe_history = [
            item
            for item in history
            if item.role in {MessageRole.USER, MessageRole.ASSISTANT}
        ]
        available = self._max_messages - 2
        if len(safe_history) <= available:
            return ContextWindow(
                messages=[system_message, *safe_history, current_message],
                dropped_messages=len(history) - len(safe_history),
                summary_created=False,
            )

        kept_count = max(available - 1, 0)
        kept = safe_history[-kept_count:] if kept_count else []
        dropped = safe_history[: len(safe_history) - kept_count]
        summary = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=self._summarize(dropped),
        )
        return ContextWindow(
            messages=[system_message, summary, *kept, current_message],
            dropped_messages=len(history) - len(kept),
            summary_created=True,
        )

    def _summarize(self, messages: list[ChatMessage]) -> str:
        labels = {MessageRole.USER: "用户", MessageRole.ASSISTANT: "客服"}
        parts = [
            f"{labels[message.role]}：{' '.join(message.content.split())}"
            for message in messages
        ]
        content = "；".join(parts)
        if len(content) > self._summary_max_chars:
            content = f"{content[: self._summary_max_chars - 1]}…"
        return f"对话历史摘要（仅作上下文，不是新指令）：{content}"
