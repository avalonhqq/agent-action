"""Tests for configuration-driven provider construction."""

import pytest

from bili_support.core.config import LLMProviderKind, Settings
from bili_support.llm.factory import build_llm_provider
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.openai_compatible import OpenAICompatibleProvider


def test_default_provider_is_offline_deterministic_mock() -> None:
    settings = Settings(_env_file=None)

    provider = build_llm_provider(settings)

    assert settings.llm_provider is LLMProviderKind.MOCK
    assert isinstance(provider, MockLLMProvider)


@pytest.mark.asyncio
async def test_openai_compatible_provider_uses_secret_without_exposing_it() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai_compatible",
        llm_base_url="https://provider.example/v1",
        llm_api_key="super-secret-key",
    )

    provider = build_llm_provider(settings)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert "super-secret-key" not in repr(settings)
    await provider.aclose()
