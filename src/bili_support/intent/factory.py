"""Configuration-driven construction for intent-classification experiments."""

from bili_support.core.config import LLMProviderKind, Settings
from bili_support.llm.factory import build_llm_provider
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.provider import LLMProvider


def build_intent_provider(
    settings: Settings,
    *,
    shared_provider: LLMProvider | None = None,
) -> LLMProvider:
    """Use an intent-shaped Mock locally or the configured compatible provider."""
    if settings.llm_provider is LLMProviderKind.MOCK:
        return MockLLMProvider(
            response_text=settings.intent_mock_response,
            model=settings.llm_model,
        )
    if shared_provider is not None:
        return shared_provider
    return build_llm_provider(settings)
