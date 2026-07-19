"""Tests for the stable public interface of the LLM package."""

import bili_support.llm as llm


def test_llm_package_exports_only_declared_public_names() -> None:
    assert llm.__all__ == [
        "ChatMessage",
        "FinishReason",
        "LLMProvider",
        "LLMRequest",
        "LLMResponse",
        "MessageRole",
        "MockLLMProvider",
        "StreamChunk",
        "TokenUsage",
    ]
    assert all(hasattr(llm, name) for name in llm.__all__)


def test_public_api_can_build_a_protocol_compatible_mock() -> None:
    provider: llm.LLMProvider = llm.MockLLMProvider(response_text="固定回复")
    request = llm.LLMRequest(
        messages=[llm.ChatMessage(role=llm.MessageRole.USER, content="测试问题")],
        model="mock-support-model",
    )

    assert isinstance(provider, llm.LLMProvider)
    assert request.messages[0].role is llm.MessageRole.USER
