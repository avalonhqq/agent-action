"""published dictionary manifest

Revision ID: 20260802_0007
Revises: 20260801_0006
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260802_0007"
down_revision: str | None = "20260801_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为不可变版本增加规范词与别名关系快照。"""

    op.add_column(
        "knowledge_dictionary_versions",
        sa.Column("manifest_json", sa.Text(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE knowledge_dictionary_versions "
            "SET manifest_json = '[]' WHERE manifest_json IS NULL"
        )
    )
    with op.batch_alter_table("knowledge_dictionary_versions") as batch:
        batch.alter_column(
            "manifest_json",
            existing_type=sa.Text(),
            nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("knowledge_dictionary_versions") as batch:
        batch.drop_column("manifest_json")
