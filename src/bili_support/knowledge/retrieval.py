"""不同召回器共享的Child候选契约，为后续RRF融合隔离底层分数语义。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RetrievalMode(StrEnum):
    """知识检索模式；HYBRID使用RRF融合Vector与BM25的内部排名。"""

    VECTOR = "vector"  # Embedding + Milvus语义召回
    BM25 = "bm25"  # 中文词法BM25召回
    HYBRID = "hybrid"  # Vector + BM25并行召回后做RRF融合


class RetrievalSource(StrEnum):
    """单个候选来自哪个召回器；7B融合后仍保留来源证据。"""

    VECTOR = "vector"
    BM25 = "bm25"
    HYBRID = "hybrid"


class RetrievalChannelEvidence(BaseModel):
    """一个融合候选在某条召回通道中的原始证据。

    raw_score只允许在相同source内比较；RRF使用rank计算贡献，不直接混加原始分数。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: RetrievalSource
    rank: int = Field(ge=1)
    raw_score: float
    rrf_contribution: float = Field(gt=0)


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


class FusedChildRetrievalCandidate(BaseModel):
    """按Chunk身份去重后的RRF候选，保留所有原始通道证据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version_id: str = Field(min_length=1)
    index_version_id: str = Field(min_length=1)
    fused_score: float = Field(gt=0)
    channel_evidence: tuple[RetrievalChannelEvidence, ...] = Field(min_length=1)

    @property
    def source(self) -> RetrievalSource:
        """为统一下游复核契约，将融合候选标记为HYBRID。"""

        return RetrievalSource.HYBRID

    @property
    def score(self) -> float:
        """Small-to-Big沿用score排序；这里返回可比较的RRF融合分数。"""

        return self.fused_score


RankedChildRetrievalCandidate = (
    ChildRetrievalCandidate | FusedChildRetrievalCandidate
)
