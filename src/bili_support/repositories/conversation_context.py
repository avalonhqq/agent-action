"""跨轮会话上下文快照的数据访问边界。"""

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.models.entities import ConversationContextSnapshot


class ConversationContextRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(
        self,
        conversation_id: str,
    ) -> ConversationContextSnapshot | None:
        """锁定既有快照，防止同一会话的并发轮次互相覆盖。"""

        return cast(
            ConversationContextSnapshot | None,
            await self._session.scalar(
                select(ConversationContextSnapshot)
                .where(ConversationContextSnapshot.conversation_id == conversation_id)
                .with_for_update()
            ),
        )

    async def get(self, conversation_id: str) -> ConversationContextSnapshot | None:
        return cast(
            ConversationContextSnapshot | None,
            await self._session.scalar(
                select(ConversationContextSnapshot).where(
                    ConversationContextSnapshot.conversation_id == conversation_id
                )
            ),
        )

    def add(self, snapshot: ConversationContextSnapshot) -> None:
        self._session.add(snapshot)
