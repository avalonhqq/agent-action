"""week5 knowledge ingestion foundation

Revision ID: 20260725_0003
Revises: 20260725_0002
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0003"
down_revision: str | None = "20260725_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("business_domain", sa.String(32), nullable=False),
        sa.Column("access_scope", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'deleted')", name="ck_knowledge_documents_status_allowed"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_knowledge_documents_created_by_user_id", "knowledge_documents", ["created_by_user_id"]
    )
    op.create_index(
        "ix_knowledge_documents_business_domain", "knowledge_documents", ["business_domain"]
    )
    op.create_index(
        "ix_knowledge_documents_domain_status", "knowledge_documents", ["business_domain", "status"]
    )

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="ck_knowledge_document_versions_status_allowed",
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_knowledge_document_versions_size_positive"),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "document_id", "content_sha256", name="uq_knowledge_versions_document_sha256"
        ),
        sa.UniqueConstraint(
            "document_id", "version_number", name="uq_knowledge_versions_document_number"
        ),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_knowledge_document_versions_document_id", "knowledge_document_versions", ["document_id"]
    )
    op.create_index(
        "ix_knowledge_document_versions_content_sha256",
        "knowledge_document_versions",
        ["content_sha256"],
    )
    op.create_index(
        "ix_knowledge_versions_document_created",
        "knowledge_document_versions",
        ["document_id", "created_at"],
    )

    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="ck_knowledge_ingestion_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_knowledge_ingestion_jobs_attempt_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["knowledge_document_versions.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_knowledge_ingestion_jobs_version_id", "knowledge_ingestion_jobs", ["version_id"]
    )
    op.create_index(
        "ix_knowledge_jobs_status_created", "knowledge_ingestion_jobs", ["status", "created_at"]
    )

    op.create_table(
        "knowledge_source_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer()),
        sa.Column("heading_path", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_source_blocks_ordinal_non_negative"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0",
            name="ck_knowledge_source_blocks_page_positive",
        ),
        sa.ForeignKeyConstraint(
            ["version_id"], ["knowledge_document_versions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_source_blocks_version_ordinal"),
    )
    op.create_index(
        "ix_knowledge_source_blocks_version_id", "knowledge_source_blocks", ["version_id"]
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("source_block_id", sa.String(36)),
        sa.Column("parent_chunk_id", sa.String(36)),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.CheckConstraint("kind IN ('parent', 'child')", name="ck_knowledge_chunks_kind_allowed"),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_chunks_ordinal_non_negative"),
        sa.CheckConstraint("char_count > 0", name="ck_knowledge_chunks_char_count_positive"),
        sa.ForeignKeyConstraint(
            ["version_id"], ["knowledge_document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_block_id"], ["knowledge_source_blocks.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["knowledge_chunks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_chunks_version_ordinal"),
    )
    op.create_index("ix_knowledge_chunks_version_id", "knowledge_chunks", ["version_id"])
    op.create_index("ix_knowledge_chunks_source_block_id", "knowledge_chunks", ["source_block_id"])
    op.create_index("ix_knowledge_chunks_parent_chunk_id", "knowledge_chunks", ["parent_chunk_id"])


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_source_blocks")
    op.drop_table("knowledge_ingestion_jobs")
    op.drop_table("knowledge_document_versions")
    op.drop_table("knowledge_documents")
