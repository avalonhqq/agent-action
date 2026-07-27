"""expand model call operation for customer-service route targets

Revision ID: 20260725_0002
Revises: 20260719_0001
Create Date: 2026-07-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0002"
down_revision: str | None = "20260719_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # batch 模式同时兼容本地 SQLite 迁移测试和真实 MySQL。
    with op.batch_alter_table("model_calls") as batch_op:
        batch_op.alter_column(
            "operation",
            existing_type=sa.String(length=16),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("model_calls") as batch_op:
        batch_op.alter_column(
            "operation",
            existing_type=sa.String(length=64),
            type_=sa.String(length=16),
            existing_nullable=False,
        )
