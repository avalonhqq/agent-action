"""根据配置构造意图识别所需的 Provider。"""

from bili_support.core.config import LLMProviderKind, Settings
from bili_support.llm.factory import build_llm_provider
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.provider import LLMProvider


def build_intent_provider(
    settings: Settings,
    *,
    shared_provider: LLMProvider | None = None,
) -> LLMProvider:
    """本地使用意图 JSON Mock，真实环境使用配置的兼容 Provider。"""
    if settings.llm_provider is LLMProviderKind.MOCK:
        # 客服回答 Mock 是普通文本，不能拿来冒充 IntentDecision JSON。
        return MockLLMProvider(
            response_text=settings.intent_mock_response,
            model=settings.llm_model,
        )
    if shared_provider is not None:
        # 真实模型可与客服回答共享 HTTP 客户端，减少连接池和关闭逻辑。
        return shared_provider
    return build_llm_provider(settings)
