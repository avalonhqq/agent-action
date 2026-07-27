"""add knowledge document type

Revision ID: 20260728_0004
Revises: 20260725_0003
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260728_0004"
down_revision: str | None = "20260725_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.add_column(
            sa.Column(
                "knowledge_type",
                sa.String(16),
                nullable=False,
                server_default="mixed",
            )
        )
        batch.create_check_constraint(
            "ck_knowledge_documents_knowledge_type_allowed",
            "knowledge_type IN ('policy', 'manual', 'faq', 'generic', 'mixed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_documents") as batch:
        batch.drop_constraint(
            "ck_knowledge_documents_knowledge_type_allowed",
            type_="check",
        )
        batch.drop_column("knowledge_type")
