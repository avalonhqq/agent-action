"""LangGraph human review audit table

Revision ID: 20260805_0009
Revises: 20260802_0008
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260805_0009"
down_revision: str | None = "20260802_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保存人工中断、审核人和恢复决策，MongoDB只负责执行快照。"""

    op.create_table(
        "graph_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(300), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("user_message_id", sa.String(36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(36), nullable=False),
        sa.Column("reviewed_by_user_id", sa.String(36)),
        sa.Column("thread_id", sa.String(36), nullable=False),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("interrupt_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decision_note", sa.String(500)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'approved', 'rejected')",
            name="ck_graph_reviews_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("execution_id", name="uq_graph_reviews_execution_id"),
    )
    op.create_index(
        "ix_graph_reviews_status_created",
        "graph_reviews",
        ["status", "created_at"],
    )
    for column in (
        "conversation_id",
        "user_message_id",
        "requested_by_user_id",
        "reviewed_by_user_id",
        "thread_id",
        "request_id",
    ):
        op.create_index(f"ix_graph_reviews_{column}", "graph_reviews", [column])


def downgrade() -> None:
    op.drop_table("graph_reviews")
