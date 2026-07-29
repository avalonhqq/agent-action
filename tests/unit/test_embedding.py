from math import isclose, sqrt

import pytest
from pydantic import ValidationError

from bili_support.knowledge.embedding import (
    DeterministicHashEmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingVector,
    cosine_similarity,
)


async def test_hash_embedding_is_reproducible_normalized_and_ordered() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=32)
    request = EmbeddingRequest(
        texts=("大会员怎么取消自动续费", "退款规则是什么"),
        model="mock-hash-embedding-v1",
    )

    first = await provider.embed(request)
    second = await provider.embed(request)

    assert first == second
    assert len(first.vectors) == len(request.texts)
    assert first.dimension == 32
    assert all(
        isclose(
            sqrt(sum(value * value for value in vector.values)),
            1.0,
            abs_tol=1e-9,
        )
        for vector in first.vectors
    )


async def test_hash_embedding_gives_shared_terms_higher_similarity() -> None:
    provider = DeterministicHashEmbeddingProvider(dimension=128)
    response = await provider.embed(
        EmbeddingRequest(
            texts=(
                "怎么取消大会员自动续费",
                "大会员连续包月取消自动续费",
                "稿件被下架如何申诉",
            ),
            model="mock-hash-embedding-v1",
        )
    )
    query, related, unrelated = (item.values for item in response.vectors)

    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


def test_embedding_response_rejects_dimension_mismatch() -> None:
    with pytest.raises(ValidationError, match="dimension mismatch"):
        EmbeddingResponse(
            vectors=(EmbeddingVector(values=(0.1, 0.2)),),
            model="test",
            dimension=3,
        )


def test_embedding_request_rejects_blank_text() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        EmbeddingRequest(texts=("有效文本", "  "), model="test")
