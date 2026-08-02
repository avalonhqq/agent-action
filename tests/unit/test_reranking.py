"""7C批量Parent Rerank契约、Mock排序和结构化LLM适配测试。"""

import pytest

from bili_support.knowledge.rerank_providers import (
    LLMRerankProvider,
    MockRerankProvider,
)
from bili_support.knowledge.reranking import (
    RerankDocument,
    RerankErrorCode,
    RerankItem,
    RerankProviderError,
    RerankRequest,
    RerankResponse,
    validate_rerank_response,
)
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.prompts import create_default_prompt_registry


def _request() -> RerankRequest:
    return RerankRequest(
        query="大会员重复扣费怎么办？",
        documents=(
            RerankDocument(
                parent_chunk_id="price",
                title="会员价格",
                content="大会员套餐价格以结算页面为准。",
                original_rank=1,
            ),
            RerankDocument(
                parent_chunk_id="refund",
                title="重复扣费",
                content="重复扣费请提交订单号和支付流水人工核查。",
                original_rank=2,
            ),
        ),
        top_n=2,
        model="mock-reranker-v1",
        timeout_seconds=1,
    )


async def test_mock_reranker_scores_all_parents_in_one_batch() -> None:
    request = _request()
    response = await MockRerankProvider().rerank(request)

    validate_rerank_response(request=request, response=response)
    assert [item.parent_chunk_id for item in response.items] == ["refund", "price"]
    assert response.items[0].relevance_score > response.items[1].relevance_score


def test_response_validation_rejects_unknown_or_missing_parent_ids() -> None:
    request = _request()
    response = RerankResponse(
        items=(
            RerankItem(parent_chunk_id="unknown", relevance_score=0.9, rank=1),
            RerankItem(parent_chunk_id="price", relevance_score=0.5, rank=2),
        ),
        provider="fake",
        model="fake-model",
        latency_ms=1,
    )

    with pytest.raises(RerankProviderError) as error:
        validate_rerank_response(request=request, response=response)
    assert error.value.code is RerankErrorCode.INVALID_RESPONSE


async def test_llm_reranker_uses_strict_batch_schema() -> None:
    provider = MockLLMProvider(
        response_text=(
            '{"items":['
            '{"parent_chunk_id":"refund","relevance_score":0.95,"rank":1},'
            '{"parent_chunk_id":"price","relevance_score":0.20,"rank":2}'
            "]}"
        ),
        model="real-compatible-model",
    )
    reranker = LLMRerankProvider(
        provider=provider,
        prompt_registry=create_default_prompt_registry(),
    )

    response = await reranker.rerank(_request())

    assert response.provider == "llm"
    assert response.model == "real-compatible-model"
    assert [item.parent_chunk_id for item in response.items] == ["refund", "price"]
