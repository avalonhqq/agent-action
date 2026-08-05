"""LangGraph人工审核记录的数据访问边界。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.models.entities import GraphReview


class GraphReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def by_execution(self, execution_id: str) -> GraphReview | None:
        return cast(
            GraphReview | None,
            await self._session.scalar(
                select(GraphReview).where(GraphReview.execution_id == execution_id)
            ),
        )

    async def list_pending(self) -> list[GraphReview]:
        result = await self._session.scalars(
            select(GraphReview)
            .where(GraphReview.status == "pending")
            .order_by(GraphReview.created_at.asc(), GraphReview.id.asc())
        )
        return list(result)

    def add(self, review: GraphReview) -> None:
        self._session.add(review)

    async def claim(
        self,
        execution_id: str,
        *,
        reviewed_by_user_id: str,
    ) -> GraphReview | None:
        """原子领取pending审核，防止两个审核员重复恢复同一Checkpoint。"""

        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                update(GraphReview)
                .where(
                    GraphReview.execution_id == execution_id,
                    GraphReview.status == "pending",
                )
                .values(
                    status="processing",
                    reviewed_by_user_id=reviewed_by_user_id,
                    updated_at=datetime.now(UTC),
                )
            )
        )
        if result.rowcount != 1:
            return None
        return await self.by_execution(execution_id)

    @staticmethod
    def release_claim(review: GraphReview) -> None:
        review.status = "pending"
        review.reviewed_by_user_id = None

    @staticmethod
    def resolve(
        review: GraphReview,
        *,
        approved: bool,
        reviewed_by_user_id: str,
        note: str,
    ) -> None:
        review.status = "approved" if approved else "rejected"
        review.reviewed_by_user_id = reviewed_by_user_id
        review.decision_note = note
        review.reviewed_at = datetime.now(UTC)
