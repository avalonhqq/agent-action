"""使用 Schema 约束的哔哩哔哩客服意图分类器。"""

from __future__ import annotations

from bili_support.intent.types import IntentDecision
from bili_support.llm.prompts import PromptRegistry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.structured import StructuredOutputParser, StructuredOutputResult
from bili_support.llm.types import LLMRequest


class IntentClassifier:
    """构造一次意图请求，并将 Provider 响应安全解析为领域契约。"""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompt_registry: PromptRegistry,
        model: str,
        prompt_version: int = 1,
        temperature: float = 0.0,
        max_tokens: int = 512,
        timeout_seconds: float = 30.0,
        parse_retries: int = 1,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be blank")
        if prompt_version <= 0:
            raise ValueError("prompt_version must be greater than zero")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0 and 2")
        if max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if not 0 <= parse_retries <= 3:
            raise ValueError("parse_retries must be between 0 and 3")

        # 初始化阶段固定 Prompt 版本和推理参数，避免同一实例在运行中悄悄漂移。
        self._provider = provider
        self._prompt = prompt_registry.get("intent_classification", prompt_version)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout_seconds = timeout_seconds
        self._parse_retries = parse_retries
        self._parser = StructuredOutputParser(IntentDecision)

    def build_request(self, question: str) -> LLMRequest:
        """构造与供应商无关的请求；此方法不访问网络，也不会产生模型费用。"""
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question must not be blank")
        if len(normalized_question) > 4000:
            raise ValueError("question must not exceed 4000 characters")

        # Schema 通过独立字段交给 Provider，用户原文只进入 USER 消息。
        return LLMRequest(
            messages=self._prompt.render({"question": normalized_question}),
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            timeout_seconds=self._timeout_seconds,
            structured_output=self._parser.specification("intent_decision"),
        )

    async def classify(
        self, question: str
    ) -> StructuredOutputResult[IntentDecision]:
        """识别单条问题；成功返回决策，失败返回稳定的结构错误码。"""
        request = self.build_request(question)
        for attempt in range(self._parse_retries + 1):
            # HTTP 重试由 Provider 负责；这里只处理“响应成功但结构不合法”。
            response = await self._provider.complete(request)
            result = self._parser.parse(response.content)
            if result.value is not None or attempt >= self._parse_retries:
                return result
            request = self._repair_request(request)
        raise AssertionError("parse retry loop must return")

    @staticmethod
    def _repair_request(request: LLMRequest) -> LLMRequest:
        """构造受限重试请求，不回传可能包含敏感信息的首次模型原文。"""
        messages = list(request.messages)
        system_message = messages[0]
        messages[0] = system_message.model_copy(
            update={
                "content": (
                    system_message.content
                    + "上一次生成未通过结构校验。请重新独立判断，并确保所有必填字段、"
                    "枚举、空数组和 null 值严格符合上述规则；不要复述或解释错误。"
                )
            }
        )
        # model_copy 保留模型、超时和 Schema，只加强系统约束。
        return request.model_copy(update={"messages": messages})
