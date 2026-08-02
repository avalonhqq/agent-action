"""production knowledge dictionary workflow

Revision ID: 20260801_0006
Revises: 20260729_0005
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增候选审核表和不可变Jieba发布版本表。"""

    op.create_table(
        "knowledge_dictionary_terms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("term", sa.String(100), nullable=False),
        sa.Column("normalized_term", sa.String(100), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("business_domain", sa.String(32), nullable=False),
        sa.Column("term_type", sa.String(32), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_reference", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("review_note", sa.String(500)),
        sa.Column("created_by_user_id", sa.String(36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(36)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'rejected')",
            name="ck_dictionary_terms_status_allowed",
        ),
        sa.CheckConstraint(
            "term_type IN ('product', 'feature', 'issue', 'action', "
            "'error_code', 'other')",
            name="ck_dictionary_terms_term_type_allowed",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'knowledge_keyword', 'product_catalog', "
            "'conversation_log_mock', 'ticket_mock')",
            name="ck_dictionary_terms_source_type_allowed",
        ),
        sa.CheckConstraint(
            "frequency > 0",
            name="ck_dictionary_terms_frequency_positive",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "business_domain",
            "normalized_term",
            name="uq_dictionary_terms_domain_normalized",
        ),
    )
    op.create_index(
        "ix_dictionary_terms_domain_status",
        "knowledge_dictionary_terms",
        ["business_domain", "status"],
    )
    op.create_index(
        "ix_knowledge_dictionary_terms_business_domain",
        "knowledge_dictionary_terms",
        ["business_domain"],
    )
    op.create_index(
        "ix_knowledge_dictionary_terms_created_by_user_id",
        "knowledge_dictionary_terms",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_knowledge_dictionary_terms_reviewed_by_user_id",
        "knowledge_dictionary_terms",
        ["reviewed_by_user_id"],
    )

    op.create_table(
        "knowledge_dictionary_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_content", sa.Text(), nullable=False),
        sa.Column("term_count", sa.Integer(), nullable=False),
        sa.Column("published_by_user_id", sa.String(36), nullable=False),
        sa.Column("release_note", sa.String(500)),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_dictionary_versions_status_allowed",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_dictionary_versions_version_positive",
        ),
        sa.CheckConstraint(
            "term_count > 0",
            name="ck_dictionary_versions_term_count_positive",
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "version_number",
            name="uq_dictionary_versions_version_number",
        ),
        sa.UniqueConstraint(
            "content_sha256",
            name="uq_dictionary_versions_content_sha256",
        ),
    )
    op.create_index(
        "ix_dictionary_versions_status_published",
        "knowledge_dictionary_versions",
        ["status", "published_at"],
    )
    op.create_index(
        "ix_knowledge_dictionary_versions_published_by_user_id",
        "knowledge_dictionary_versions",
        ["published_by_user_id"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_dictionary_versions")
    op.drop_table("knowledge_dictionary_terms")
