"""Persistence entities for users, conversations, messages, and model calls."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from bili_support.models.base import Base, TimestampMixin


def new_id() -> str:
    return str(uuid4())


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    thread_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role_allowed"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        CheckConstraint("status IN ('success', 'error', 'cancelled')", name="status_allowed"),
        CheckConstraint("latency_ms >= 0", name="latency_non_negative"),
        Index("ix_model_calls_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_message_id: Mapped[str] = mapped_column(
        ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    assistant_message_id: Mapped[str | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128), index=True)
    # 路由接入后记录 complete:human_service_mock 等可审计目标。
    operation: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    latency_ms: Mapped[float] = mapped_column(Float)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class KnowledgeDocument(TimestampMixin, Base):
    """逻辑知识文档；文件内容变化只新增版本，不覆盖该身份。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'deleted')", name="status_allowed"),
        CheckConstraint(
            "knowledge_type IN ('policy', 'manual', 'faq', 'generic', 'mixed')",
            name="knowledge_type_allowed",
        ),
        Index("ix_knowledge_documents_domain_status", "business_domain", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    # title + business_domain + created_by_user_id 是当前逻辑文档身份。
    title: Mapped[str] = mapped_column(String(200))
    business_domain: Mapped[str] = mapped_column(String(32), index=True)
    # mixed用于同时包含规则、步骤、FAQ和表格的综合企业文档。
    knowledge_type: Mapped[str] = mapped_column(String(16), default="mixed")
    # 5A 先保存权限标签，真正检索时还必须再次执行权限过滤。
    access_scope: Mapped[list[str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")


class KnowledgeDocumentVersion(Base):
    """不可变文件版本；SHA-256 用于同一逻辑文档内的上传幂等。"""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "content_sha256",
            name="uq_knowledge_versions_document_sha256",
        ),
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_knowledge_versions_document_number",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        Index("ix_knowledge_versions_document_created", "document_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer)
    # 哈希判断字节是否相同；它不能代替业务有效期或权限判断。
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class KnowledgeIngestionJob(Base):
    """可重试的入库任务；第五周使用进程内同步 Mock 调度。"""

    __tablename__ = "knowledge_ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_non_negative"),
        Index("ix_knowledge_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")
    # 每次进入 processing 都递增，用于观察失败重试次数。
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDictionaryTerm(TimestampMixin, Base):
    """可审核领域词；候选和拒绝词不会进入Jieba发布制品。"""

    __tablename__ = "knowledge_dictionary_terms"
    __table_args__ = (
        UniqueConstraint(
            "business_domain",
            "normalized_term",
            name="uq_dictionary_terms_domain_normalized",
        ),
        CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected')",
            name="status_allowed",
        ),
        CheckConstraint(
            "term_type IN ('product', 'feature', 'issue', 'action', "
            "'error_code', 'other')",
            name="term_type_allowed",
        ),
        CheckConstraint(
            "source_type IN ('manual', 'knowledge_keyword', 'product_catalog', "
            "'conversation_log_mock', 'ticket_mock')",
            name="source_type_allowed",
        ),
        CheckConstraint("frequency > 0", name="frequency_positive"),
        Index(
            "ix_dictionary_terms_domain_status",
            "business_domain",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    term: Mapped[str] = mapped_column(String(100))
    normalized_term: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    business_domain: Mapped[str] = mapped_column(String(32), index=True)
    term_type: Mapped[str] = mapped_column(String(32))
    frequency: Mapped[int] = mapped_column(Integer)
    source_type: Mapped[str] = mapped_column(String(32))
    source_reference: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="candidate")
    review_note: Mapped[str | None] = mapped_column(String(500))
    created_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeDictionaryVersion(Base):
    """一次发布的不可变完整词典快照，可按版本下载、回放和回滚。"""

    __tablename__ = "knowledge_dictionary_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'superseded')",
            name="status_allowed",
        ),
        CheckConstraint("version_number > 0", name="version_positive"),
        CheckConstraint("term_count > 0", name="term_count_positive"),
        Index("ix_dictionary_versions_status_published", "status", "published_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_number: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    artifact_content: Mapped[str] = mapped_column(Text)
    term_count: Mapped[int] = mapped_column(Integer)
    published_by_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
    )
    release_note: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )


class KnowledgeSourceBlock(Base):
    """Loader忠实输出的结构块，不等同于最终检索Chunk。"""

    __tablename__ = "knowledge_source_blocks"
    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_source_blocks_version_ordinal"),
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
        CheckConstraint("page_number IS NULL OR page_number > 0", name="page_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    # PDF 使用页码；DOCX/Markdown 主要依靠 heading_path 定位。
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading_path: Mapped[list[str]] = mapped_column(JSON)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgeChunk(Base):
    """Parent/Child检索单元；5A先固定持久化契约，5B实现生成策略。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_ordinal"),
        CheckConstraint("kind IN ('parent', 'child')", name="kind_allowed"),
        CheckConstraint("ordinal >= 0", name="ordinal_non_negative"),
        CheckConstraint("char_count > 0", name="char_count_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        index=True,
    )
    source_block_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_source_blocks.id", ondelete="SET NULL"),
        index=True,
    )
    parent_chunk_id: Mapped[str | None] = mapped_column(
        ForeignKey("knowledge_chunks.id", ondelete="CASCADE"),
        index=True,
    )
    # kind=child 负责精确召回，kind=parent 负责提供完整回答上下文。
    kind: Mapped[str] = mapped_column(String(16))
    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON)


class KnowledgeIndexVersion(Base):
    """一次可独立构建和切换的向量索引版本。

    文档版本描述“原始知识内容”，索引版本描述“某个Embedding模型和分块契约生成的
    检索副本”。两者分离后，更换模型或索引参数不需要篡改文档版本。
    """

    __tablename__ = "knowledge_index_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id",
            "build_key",
            name="uq_knowledge_index_versions_build_key",
        ),
        CheckConstraint(
            "status IN ('building', 'active', 'superseded', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("embedding_dimension > 1", name="dimension_valid"),
        CheckConstraint("total_chunks >= 0", name="total_chunks_non_negative"),
        CheckConstraint("indexed_chunks >= 0", name="indexed_chunks_non_negative"),
        CheckConstraint(
            "indexed_chunks <= total_chunks",
            name="indexed_chunks_not_over_total",
        ),
        Index(
            "ix_knowledge_index_versions_document_status",
            "document_version_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"),
        index=True,
    )
    # Collection名称表达物理Schema版本；index_version_id表达其中的逻辑构建代次。
    collection_name: Mapped[str] = mapped_column(String(128))
    embedding_provider: Mapped[str] = mapped_column(String(32))
    embedding_model: Mapped[str] = mapped_column(String(200))
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    chunk_schema_version: Mapped[str] = mapped_column(String(64))
    # build_key对“内容版本 + 模型 + 维度 + Chunk契约 + Collection”做幂等。
    build_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="building")
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    indexed_chunks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeIndexJob(Base):
    """可重试的索引构建任务；当前同步执行，未来可由队列消费同一job_id。"""

    __tablename__ = "knowledge_index_jobs"
    __table_args__ = (
        UniqueConstraint("index_version_id", name="uq_knowledge_index_jobs_version"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="status_allowed",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_non_negative"),
        Index("ix_knowledge_index_jobs_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    index_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_index_versions.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
