"""Build the configured provider behind the internal LLM protocol."""

from bili_support.core.config import LLMProviderKind, Settings
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.provider import LLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Create a deterministic Mock or an OpenAI-compatible adapter."""
    if settings.llm_provider is LLMProviderKind.MOCK:
        return MockLLMProvider(
            response_text=settings.llm_mock_response,
            model=settings.llm_model,
        )
    api_key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=api_key,
        max_retries=settings.llm_max_retries,
        retry_base_delay=settings.llm_retry_base_delay,
    )
