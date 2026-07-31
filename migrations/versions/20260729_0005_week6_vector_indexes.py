"""week6 versioned vector index jobs

Revision ID: 20260729_0005
Revises: 20260728_0004
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0005"
down_revision: str | None = "20260728_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增逻辑索引版本和可重试任务，不修改第五周不可变文档/Chunk。"""

    op.create_table(
        "knowledge_index_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("document_version_id", sa.String(36), nullable=False),
        sa.Column("collection_name", sa.String(128), nullable=False),
        sa.Column("embedding_provider", sa.String(32), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("chunk_schema_version", sa.String(64), nullable=False),
        sa.Column("build_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total_chunks", sa.Integer(), nullable=False),
        sa.Column("indexed_chunks", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('building', 'active', 'superseded', 'failed')",
            name="ck_knowledge_index_versions_status_allowed",
        ),
        sa.CheckConstraint(
            "embedding_dimension > 1",
            name="ck_knowledge_index_versions_dimension_valid",
        ),
        sa.CheckConstraint(
            "total_chunks >= 0",
            name="ck_knowledge_index_versions_total_chunks_non_negative",
        ),
        sa.CheckConstraint(
            "indexed_chunks >= 0",
            name="ck_knowledge_index_versions_indexed_chunks_non_negative",
        ),
        sa.CheckConstraint(
            "indexed_chunks <= total_chunks",
            name="ck_knowledge_index_versions_indexed_chunks_not_over_total",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id"],
            ["knowledge_document_versions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "build_key",
            name="uq_knowledge_index_versions_build_key",
        ),
    )
    op.create_index(
        "ix_knowledge_index_versions_document_version_id",
        "knowledge_index_versions",
        ["document_version_id"],
    )
    op.create_index(
        "ix_knowledge_index_versions_document_status",
        "knowledge_index_versions",
        ["document_version_id", "status"],
    )

    op.create_table(
        "knowledge_index_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("index_version_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed')",
            name="ck_knowledge_index_jobs_status_allowed",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_knowledge_index_jobs_attempt_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["index_version_id"],
            ["knowledge_index_versions.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "index_version_id",
            name="uq_knowledge_index_jobs_version",
        ),
    )
    op.create_index(
        "ix_knowledge_index_jobs_index_version_id",
        "knowledge_index_jobs",
        ["index_version_id"],
    )
    op.create_index(
        "ix_knowledge_index_jobs_status_created",
        "knowledge_index_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_index_jobs")
    op.drop_table("knowledge_index_versions")
