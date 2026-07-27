"""知识入库的数据访问边界；这里只表达查询，不编排业务流程。"""

from __future__ import annotations

from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.models.entities import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    KnowledgeSourceBlock,
)


class KnowledgeRepository:
    """封装知识表查询，使 Service 专注版本、任务和权限规则。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add_document(self, document: KnowledgeDocument) -> None:
        self._session.add(document)

    def add_version(self, version: KnowledgeDocumentVersion) -> None:
        self._session.add(version)

    def add_job(self, job: KnowledgeIngestionJob) -> None:
        self._session.add(job)

    def add_blocks(self, blocks: list[KnowledgeSourceBlock]) -> None:
        self._session.add_all(blocks)

    def add_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        self._session.add_all(chunks)

    async def document(self, document_id: str) -> KnowledgeDocument | None:
        return await self._session.get(KnowledgeDocument, document_id)

    async def active_document_by_identity(
            self,
            *,
            owner_user_id: str,
            title: str,
            business_domain: str,
            knowledge_type: str,
    ) -> KnowledgeDocument | None:
        """按创建人、标题和业务域寻找同一个有效的逻辑文档。"""

        return cast(
            KnowledgeDocument | None,
            await self._session.scalar(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.created_by_user_id == owner_user_id,
                    KnowledgeDocument.title == title,
                    KnowledgeDocument.business_domain == business_domain,
                    KnowledgeDocument.knowledge_type == knowledge_type,
                    KnowledgeDocument.status == "active",
                )
            ),
        )

    async def version(self, version_id: str) -> KnowledgeDocumentVersion | None:
        return await self._session.get(KnowledgeDocumentVersion, version_id)

    async def job(self, job_id: str) -> KnowledgeIngestionJob | None:
        return await self._session.get(KnowledgeIngestionJob, job_id)

    async def latest_job_for_version(
            self,
            version_id: str,
    ) -> KnowledgeIngestionJob | None:
        """返回版本最近的一次任务，供重复上传直接复用现有结果。"""

        return cast(
            KnowledgeIngestionJob | None,
            await self._session.scalar(
                select(KnowledgeIngestionJob)
                .where(KnowledgeIngestionJob.version_id == version_id)
                .order_by(
                    KnowledgeIngestionJob.created_at.desc(),
                    KnowledgeIngestionJob.id.desc(),
                )
            ),
        )

    async def version_by_hash(
            self,
            document_id: str,
            content_sha256: str,
    ) -> KnowledgeDocumentVersion | None:
        """只在同一逻辑文档内按 SHA-256 去重，不跨文档合并知识。"""

        return cast(
            KnowledgeDocumentVersion | None,
            await self._session.scalar(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document_id,
                    KnowledgeDocumentVersion.content_sha256 == content_sha256,
                )
            ),
        )

    async def next_version_number(self, document_id: str) -> int:
        """计算用户可读的递增版本号；数据库唯一约束负责最终兜底。"""

        maximum = await self._session.scalar(
            select(func.max(KnowledgeDocumentVersion.version_number)).where(
                KnowledgeDocumentVersion.document_id == document_id
            )
        )
        return int(maximum or 0) + 1

    async def list_documents(
            self,
            *,
            owner_user_id: str,
    ) -> list[KnowledgeDocument]:
        result = await self._session.scalars(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.created_by_user_id == owner_user_id,
                KnowledgeDocument.status == "active",
            )
            .order_by(
                KnowledgeDocument.updated_at.desc(),
                KnowledgeDocument.id.desc(),
            )
        )
        return list(result)

    async def list_versions(
            self,
            document_id: str,
    ) -> list[KnowledgeDocumentVersion]:
        result = await self._session.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document_id)
            .order_by(KnowledgeDocumentVersion.version_number.desc())
        )
        return list(result)

    async def block_count(self, version_id: str) -> int:
        count = await self._session.scalar(
            select(func.count(KnowledgeSourceBlock.id)).where(
                KnowledgeSourceBlock.version_id == version_id
            )
        )
        return int(count or 0)

    async def chunk_count(self, version_id: str) -> int:
        count = await self._session.scalar(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.version_id == version_id
            )
        )
        return int(count or 0)

    async def list_chunks(
        self,
        version_id: str,
        *,
        kind: str | None = None,
        limit: int = 500,
    ) -> list[KnowledgeChunk]:
        statement = select(KnowledgeChunk).where(
            KnowledgeChunk.version_id == version_id
        )
        if kind is not None:
            statement = statement.where(KnowledgeChunk.kind == kind)
        result = await self._session.scalars(
            statement.order_by(KnowledgeChunk.ordinal).limit(limit)
        )
        return list(result)

    async def chunks_by_ids(
        self,
        *,
        version_id: str,
        chunk_ids: list[str],
    ) -> list[KnowledgeChunk]:
        """在同一版本内批量读取Chunk，调用方不能依赖数据库返回顺序。"""

        if not chunk_ids:
            return []
        result = await self._session.scalars(
            select(KnowledgeChunk).where(
                KnowledgeChunk.version_id == version_id,
                KnowledgeChunk.id.in_(chunk_ids),
            )
        )
        return list(result)

    async def delete_chunks(self, version_id: str) -> None:
        await self._session.execute(
            delete(KnowledgeChunk).where(KnowledgeChunk.version_id == version_id)
        )

    async def delete_blocks(self, version_id: str) -> None:
        # 重试解析时先清理旧结果，确保同一版本不会残留半套或重复结构块。
        await self._session.execute(
            delete(KnowledgeSourceBlock).where(
                KnowledgeSourceBlock.version_id == version_id
            )
        )
