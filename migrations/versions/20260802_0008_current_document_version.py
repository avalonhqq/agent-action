"""current document version state

Revision ID: 20260802_0008
Revises: 20260802_0007
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0008"
down_revision: str | None = "20260802_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """以现有active索引回填current内容版本，避免按版本号猜测。"""

    op.add_column(
        "knowledge_document_versions",
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE knowledge_document_versions "
            "SET is_current = true "
            "WHERE EXISTS ("
            "SELECT 1 FROM knowledge_index_versions "
            "WHERE knowledge_index_versions.document_version_id = "
            "knowledge_document_versions.id "
            "AND knowledge_index_versions.status = 'active'"
            ")"
        )
    )
    op.create_index(
        "ix_knowledge_versions_document_current",
        "knowledge_document_versions",
        ["document_id", "is_current"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_versions_document_current",
        table_name="knowledge_document_versions",
    )
    with op.batch_alter_table("knowledge_document_versions") as batch:
        batch.drop_column("is_current")
