"""知识入库 API 输出契约；避免把 ORM 对象直接暴露给客户端。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    title: str
    business_domain: str
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
    deduplicated: bool
    error_code: str | None = None
