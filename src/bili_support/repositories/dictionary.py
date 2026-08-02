"""领域词候选、审核状态与不可变发布版本的数据访问边界。"""

from __future__ import annotations

from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.models.entities import (
    KnowledgeDictionaryTerm,
    KnowledgeDictionaryVersion,
)


class KnowledgeDictionaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_term(self, term: KnowledgeDictionaryTerm) -> None:
        self._session.add(term)

    async def term(self, term_id: str) -> KnowledgeDictionaryTerm | None:
        return await self._session.get(KnowledgeDictionaryTerm, term_id)

    async def term_by_identity(
        self,
        *,
        business_domain: str,
        normalized_term: str,
    ) -> KnowledgeDictionaryTerm | None:
        return cast(
            KnowledgeDictionaryTerm | None,
            await self._session.scalar(
                select(KnowledgeDictionaryTerm).where(
                    KnowledgeDictionaryTerm.business_domain == business_domain,
                    KnowledgeDictionaryTerm.normalized_term == normalized_term,
                )
            ),
        )

    async def list_terms(
        self,
        *,
        business_domain: str | None = None,
        status: str | None = None,
    ) -> list[KnowledgeDictionaryTerm]:
        statement = select(KnowledgeDictionaryTerm)
        if business_domain is not None:
            statement = statement.where(
                KnowledgeDictionaryTerm.business_domain == business_domain
            )
        if status is not None:
            statement = statement.where(KnowledgeDictionaryTerm.status == status)
        result = await self._session.scalars(
            statement.order_by(
                KnowledgeDictionaryTerm.business_domain,
                KnowledgeDictionaryTerm.normalized_term,
            )
        )
        return list(result)

    async def approved_terms(self) -> list[KnowledgeDictionaryTerm]:
        return await self.list_terms(status="approved")

    def add_version(self, version: KnowledgeDictionaryVersion) -> None:
        self._session.add(version)

    async def active_version(self) -> KnowledgeDictionaryVersion | None:
        return cast(
            KnowledgeDictionaryVersion | None,
            await self._session.scalar(
                select(KnowledgeDictionaryVersion).where(
                    KnowledgeDictionaryVersion.status == "active"
                )
            ),
        )

    async def version(self, version_id: str) -> KnowledgeDictionaryVersion | None:
        return await self._session.get(KnowledgeDictionaryVersion, version_id)

    async def list_versions(self) -> list[KnowledgeDictionaryVersion]:
        result = await self._session.scalars(
            select(KnowledgeDictionaryVersion).order_by(
                KnowledgeDictionaryVersion.version_number.desc()
            )
        )
        return list(result)

    async def next_version_number(self) -> int:
        latest = await self._session.scalar(
            select(func.max(KnowledgeDictionaryVersion.version_number))
        )
        return int(latest or 0) + 1

    async def supersede_active(self) -> None:
        await self._session.execute(
            update(KnowledgeDictionaryVersion)
            .where(KnowledgeDictionaryVersion.status == "active")
            .values(status="superseded")
        )
