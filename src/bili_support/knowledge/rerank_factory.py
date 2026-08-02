"""根据配置装配Rerank Provider，业务检索服务不感知具体实现。"""

from __future__ import annotations

from bili_support.core.config import Settings
from bili_support.knowledge.rerank_providers import (
    LLMRerankProvider,
    MockRerankProvider,
)
from bili_support.knowledge.reranking import RerankProvider, RerankProviderKind
from bili_support.llm.prompts import PromptRegistry
from bili_support.llm.provider import LLMProvider


def build_rerank_provider(
    *,
    settings: Settings,
    llm_provider: LLMProvider,
    prompt_registry: PromptRegistry,
) -> RerankProvider | None:
    """DISABLED返回None；Mock和LLM都遵循相同批量契约。"""

    if settings.rerank_provider is RerankProviderKind.DISABLED:
        return None
    if settings.rerank_provider is RerankProviderKind.MOCK:
        return MockRerankProvider(model=settings.rerank_model)
    return LLMRerankProvider(
        provider=llm_provider,
        prompt_registry=prompt_registry,
        parse_retries=settings.rerank_parse_retries,
    )
