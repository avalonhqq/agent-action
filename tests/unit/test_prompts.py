"""Tests for versioned prompt registration and rendering."""

import pytest

from bili_support.llm.prompts import (
    DuplicatePromptError,
    PromptNotFoundError,
    PromptRegistry,
    PromptRenderError,
    PromptTemplate,
    create_default_prompt_registry,
)
from bili_support.llm.types import MessageRole


def _prompt(version: int) -> PromptTemplate:
    return PromptTemplate(
        name="intent_detection",
        version=version,
        system_template="识别用户意图。版本 {version}",
        user_template="问题：{question}",
    )


def test_registry_resolves_explicit_and_latest_versions() -> None:
    registry = PromptRegistry()
    registry.register(_prompt(1))
    registry.register(_prompt(2))

    assert registry.get("intent_detection", 1).version == 1
    assert registry.get("intent_detection").version == 2


def test_registry_rejects_duplicate_name_and_version() -> None:
    registry = PromptRegistry()
    registry.register(_prompt(1))

    with pytest.raises(DuplicatePromptError):
        registry.register(_prompt(1))


def test_registry_reports_missing_prompt_without_fallback() -> None:
    with pytest.raises(PromptNotFoundError):
        PromptRegistry().get("missing")


def test_prompt_renders_provider_neutral_messages() -> None:
    messages = _prompt(2).render({"version": "2", "question": "如何关闭自动续费？"})

    assert [message.role for message in messages] == [MessageRole.SYSTEM, MessageRole.USER]
    assert messages[0].content == "识别用户意图。版本 2"
    assert messages[1].content == "问题：如何关闭自动续费？"


def test_prompt_rejects_missing_or_complex_variables() -> None:
    with pytest.raises(PromptRenderError):
        _prompt(1).render({"version": "1"})

    complex_prompt = PromptTemplate(
        name="unsafe",
        version=1,
        system_template="{user.name}",
        user_template="{question}",
    )
    with pytest.raises(PromptRenderError):
        complex_prompt.render({"user.name": "value", "question": "test"})


def test_default_registry_has_versioned_support_prompt() -> None:
    prompt = create_default_prompt_registry().get("support_answer")

    assert prompt.identifier == "support_answer:v1"
