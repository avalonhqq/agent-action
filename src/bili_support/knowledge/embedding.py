"""第六周Embedding内部契约与无需外部模型的确定性Hash Mock。

业务层只依赖EmbeddingProvider，不直接依赖某个云厂商SDK。Hash Mock用于测试管线、
维度校验和小规模检索实验，不代表真实语义模型效果。
"""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from collections.abc import Sequence
from hashlib import sha256
from math import isfinite, sqrt
from typing import Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]")


class EmbeddingRequest(BaseModel):
    """一次批量Embedding请求；数组顺序必须与返回向量顺序一一对应。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    texts: tuple[str, ...] = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=200)
    timeout_seconds: float = Field(default=30.0, gt=0.0)

    @field_validator("texts")
    @classmethod
    def normalize_texts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """去除边界空白，并阻止空文本进入模型或向量索引。"""

        normalized = tuple(text.strip() for text in value)
        if any(not text for text in normalized):
            raise ValueError("embedding texts must not be blank")
        return normalized


class EmbeddingVector(BaseModel):
    """单条有限浮点向量；维度由具体Provider和索引版本共同决定。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    values: tuple[float, ...] = Field(min_length=2)

    @field_validator("values")
    @classmethod
    def values_must_be_finite(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """Milvus FLOAT_VECTOR不应接收NaN或Infinity。"""

        if any(not isfinite(item) for item in value):
            raise ValueError("embedding values must be finite")
        return value


class EmbeddingResponse(BaseModel):
    """Provider无关的批量响应，强制数量和维度在入库前一致。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vectors: tuple[EmbeddingVector, ...] = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)
    dimension: int = Field(gt=1)

    @model_validator(mode="after")
    def vector_dimensions_must_match(self) -> Self:
        """同一响应中的每条向量必须符合声明维度。"""

        if any(len(vector.values) != self.dimension for vector in self.vectors):
            raise ValueError("embedding vector dimension mismatch")
        return self


@runtime_checkable
class EmbeddingProvider(Protocol):
    """真实模型与Mock都必须实现的最小异步Embedding能力。"""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """按输入顺序返回等量向量。"""

        ...


class DeterministicHashEmbeddingProvider:
    """用字符/词特征生成可复现单位向量，专门用于无Key开发和测试。"""

    def __init__(self, *, dimension: int = 128) -> None:
        if dimension < 8:
            raise ValueError("mock embedding dimension must be at least 8")
        self._dimension = dimension

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """在线程中计算Hash向量，并保持与请求texts完全相同的顺序。"""

        vectors = await asyncio.to_thread(
            lambda: tuple(self._embed_text(text) for text in request.texts)
        )
        return EmbeddingResponse(
            vectors=tuple(EmbeddingVector(values=vector) for vector in vectors),
            model=request.model,
            dimension=self._dimension,
        )

    def _embed_text(self, text: str) -> tuple[float, ...]:
        """将词、中文单字和相邻二元组Hash到固定桶后做L2归一化。"""

        tokens = _tokens(text)
        features = tokens + [
            tokens[index] + tokens[index + 1]
            for index in range(len(tokens) - 1)
        ]
        counts = Counter(features)
        values = [0.0] * self._dimension
        for feature, count in counts.items():
            digest = sha256(feature.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            values[bucket] += sign * count

        norm = sqrt(sum(value * value for value in values))
        if norm == 0:
            # EmbeddingRequest已经禁止空白；这里只防御无法被Tokenizer识别的特殊字符。
            fallback = sha256(text.encode("utf-8")).digest()
            values[int.from_bytes(fallback[:8], "big") % self._dimension] = 1.0
            norm = 1.0
        return tuple(value / norm for value in values)


def _tokens(text: str) -> list[str]:
    """提取英文词/数字和中文单字；中文二元组在上层补充局部语义特征。"""

    return [token.casefold() for token in _TOKEN_PATTERN.findall(text)]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """计算两个等维向量的余弦相似度，供教学与Mock评估解释使用。"""

    if len(left) != len(right) or not left:
        raise ValueError("cosine vectors must have the same non-zero dimension")
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("cosine vectors must not be zero vectors")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
            left_norm * right_norm
    )
