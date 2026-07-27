"""知识入库 API 输出契约；避免把 ORM 对象直接暴露给客户端。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from bili_support.knowledge.chunking import ChunkDraft, DocumentKnowledgeType
from bili_support.knowledge.types import LoadedSourceBlock


class KnowledgeDocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    title: str
    business_domain: str
    knowledge_type: str
    access_scope: list[str]
    status: str
    created_at: datetime
    updated_at: datetime


class KnowledgeVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    document_id: str
    version_number: int
    content_sha256: str
    original_filename: str
    media_type: str
    size_bytes: int
    status: str
    created_at: datetime


class KnowledgeIngestionView(BaseModel):
    """一次上传/查询的聚合视图，同时返回文档、版本和任务三个层次。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: KnowledgeDocumentView
    version: KnowledgeVersionView
    job_id: str
    job_status: str
    attempt_count: int = Field(ge=0)
    block_count: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    deduplicated: bool
    error_code: str | None = None


class KnowledgeChunkView(BaseModel):
    """用于管理端检查分块质量，不包含未来的Embedding向量。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    version_id: str
    source_block_id: str | None
    parent_chunk_id: str | None
    kind: str
    ordinal: int
    content: str
    char_count: int
    metadata_json: dict[str, object]


class ChildChunkHitInput(BaseModel):
    """检索层交给Small-to-Big的最小契约；数组顺序就是召回排序。"""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    chunk_id: str = Field(min_length=1)
    score: float = Field(description="归一化相关性分数，数值越大表示越相关")


class SmallToBigExpansionRequest(BaseModel):
    """当前是可调试接口；5C以后由BM25/向量检索器自动构造。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hits: list[ChildChunkHitInput] = Field(min_length=1, max_length=100)


class ParentChunkContextView(BaseModel):
    """去重后的完整Parent，以及触发它的Child命中证据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent: KnowledgeChunkView
    matched_child_ids: list[str]
    best_child_score: float
    first_child_rank: int = Field(ge=1)


class ChunkDebugRequest(BaseModel):
    """不落库的分块实验输入，便于修改SourceBlock后立即观察策略结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge_type: DocumentKnowledgeType
    blocks: tuple[LoadedSourceBlock, ...] = Field(min_length=1, max_length=500)


class ChunkDebugView(BaseModel):
    """分块草稿及最小诊断信息，不包含Embedding或检索分数。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunks: tuple[ChunkDraft, ...]
    parent_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
    strategy_counts: dict[str, int]
    unrepresented_source_ordinals: list[int]
