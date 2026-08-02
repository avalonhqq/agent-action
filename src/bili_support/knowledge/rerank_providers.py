"""7C Rerank Provider实现：确定性Mock与结构化LLM批量评分。"""

from __future__ import annotations

import json
from time import perf_counter

from bili_support.knowledge.bm25 import ChineseSearchTokenizer
from bili_support.knowledge.reranking import (
    RerankBatchOutput,
    RerankErrorCode,
    RerankItem,
    RerankProviderError,
    RerankRequest,
    RerankResponse,
)
from bili_support.llm.prompts import PromptRegistry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.structured import StructuredOutputParser
from bili_support.llm.types import LLMRequest


class MockRerankProvider:
    """使用Token集合覆盖率做可复现排序，只验证管线，不代表真实模型质量。"""

    name = "mock"

    def __init__(self, *, model: str = "mock-reranker-v1") -> None:
        if not model.strip():
            raise ValueError("rerank model must not be blank")
        self._model = model
        self._tokenizer = ChineseSearchTokenizer()

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        started = perf_counter()
        query_tokens = set(self._tokenizer.tokenize(request.query))
        scored = []
        for document in request.documents:
            document_tokens = set(
                self._tokenizer.tokenize(f"{document.title}\n{document.content}")
            )
            overlap = len(query_tokens.intersection(document_tokens))
            score = overlap / len(query_tokens) if query_tokens else 0.0
            scored.append((score, document.original_rank, document.parent_chunk_id))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        return RerankResponse(
            items=tuple(
                RerankItem(
                    parent_chunk_id=parent_id,
                    relevance_score=score,
                    rank=rank,
                )
                for rank, (score, _, parent_id) in enumerate(scored, start=1)
            ),
            provider=self.name,
            model=self._model,
            latency_ms=(perf_counter() - started) * 1000,
        )


class LLMRerankProvider:
    """通过现有OpenAI-compatible LLM一次性为全部Parent生成严格结构分数。"""

    name = "llm"

    def __init__(
        self,
        *,
        provider: LLMProvider,
        prompt_registry: PromptRegistry,
        parse_retries: int = 1,
    ) -> None:
        if not 0 <= parse_retries <= 2:
            raise ValueError("rerank parse_retries must be between zero and two")
        self._provider = provider
        self._prompt = prompt_registry.get("parent_rerank", 1)
        self._parser = StructuredOutputParser(RerankBatchOutput)
        self._parse_retries = parse_retries

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        started = perf_counter()
        payload = json.dumps(
            {
                "query": request.query,
                "documents": [
                    {
                        "parent_chunk_id": item.parent_chunk_id,
                        "title": item.title,
                        "content": item.content,
                        "original_rank": item.original_rank,
                    }
                    for item in request.documents
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        llm_request = LLMRequest(
            messages=self._prompt.render({"rerank_input": payload}),
            model=request.model,
            temperature=0.0,
            max_tokens=1024,
            timeout_seconds=request.timeout_seconds,
            structured_output=self._parser.specification("parent_rerank_result"),
        )
        for attempt in range(self._parse_retries + 1):
            response = await self._provider.complete(llm_request)
            parsed = self._parser.parse(response.content)
            if parsed.value is not None:
                return RerankResponse(
                    items=parsed.value.items,
                    provider=self.name,
                    model=response.model,
                    latency_ms=(perf_counter() - started) * 1000,
                )
            if attempt < self._parse_retries:
                system = llm_request.messages[0]
                messages = list(llm_request.messages)
                messages[0] = system.model_copy(
                    update={
                        "content": system.content
                        + "上一次输出未通过结构校验，请重新独立评分并严格返回完整JSON。"
                    }
                )
                llm_request = llm_request.model_copy(update={"messages": messages})
        raise RerankProviderError(RerankErrorCode.INVALID_RESPONSE)
