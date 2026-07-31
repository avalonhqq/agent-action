"""不同召回器共享的Child候选契约，为后续RRF融合隔离底层分数语义。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RetrievalMode(StrEnum):
    """7A调试阶段可单独运行的召回通道。"""

    VECTOR = "vector"  # Embedding + Milvus语义召回
    BM25 = "bm25"  # 中文词法BM25召回


class RetrievalSource(StrEnum):
    """单个候选来自哪个召回器；7B融合后仍保留来源证据。"""

    VECTOR = "vector"
    BM25 = "bm25"


class ChildRetrievalCandidate(BaseModel):
    """归一化候选身份和排序，score只允许在同一来源内部比较。

    Vector的score是COSINE，BM25的score是Okapi相关性，两者数值空间不同。
    7B不能直接加权相加，而应使用RRF等基于排名的融合方式。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    index_version_id: str = Field(min_length=1)
    source: RetrievalSource
    score: float
