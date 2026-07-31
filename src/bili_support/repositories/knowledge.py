"""知识入库的数据访问边界；这里只表达查询，不编排业务流程。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.models.entities import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexJob,
    KnowledgeIndexVersion,
    KnowledgeIngestionJob,
    KnowledgeSourceBlock,
)


@dataclass(frozen=True, slots=True)
class ActiveKnowledgeIndex:
    """检索前从MySQL解析出的活动索引和知识权限事实。"""

    index_version: KnowledgeIndexVersion
    document_version: KnowledgeDocumentVersion
    document: KnowledgeDocument


@dataclass(frozen=True, slots=True)
class ValidatedKnowledgeChild:
    """Milvus候选回MySQL复核后的Child及其活动索引上下文。"""

    chunk: KnowledgeChunk
    index_version: KnowledgeIndexVersion
    document_version: KnowledgeDocumentVersion
    document: KnowledgeDocument


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

    def add_index_version(self, index_version: KnowledgeIndexVersion) -> None:
        """登记一个尚未激活的逻辑索引版本。"""

        self._session.add(index_version)

    def add_index_job(self, job: KnowledgeIndexJob) -> None:
        """登记索引任务；调度和状态迁移由Service负责。"""

        self._session.add(job)

    async def document(self, document_id: str) -> KnowledgeDocument | None:
        return await self._session.get(KnowledgeDocument, document_id)

    async def lock_document(
        self,
        document_id: str,
    ) -> KnowledgeDocument | None:
        """锁定逻辑文档行，串行化同一文档的索引创建和活动版本切换。"""

        return cast(
            KnowledgeDocument | None,
            await self._session.scalar(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.id == document_id)
                .with_for_update()
            ),
        )

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

    async def index_version(
        self,
        index_version_id: str,
    ) -> KnowledgeIndexVersion | None:
        return await self._session.get(KnowledgeIndexVersion, index_version_id)

    async def index_job(self, job_id: str) -> KnowledgeIndexJob | None:
        return await self._session.get(KnowledgeIndexJob, job_id)

    async def index_job_for_version(
        self,
        index_version_id: str,
    ) -> KnowledgeIndexJob | None:
        return cast(
            KnowledgeIndexJob | None,
            await self._session.scalar(
                select(KnowledgeIndexJob).where(
                    KnowledgeIndexJob.index_version_id == index_version_id
                )
            ),
        )

    async def index_version_by_build_key(
        self,
        *,
        document_version_id: str,
        build_key: str,
    ) -> KnowledgeIndexVersion | None:
        """相同文档内容和索引配置只创建一个构建版本。"""

        return cast(
            KnowledgeIndexVersion | None,
            await self._session.scalar(
                select(KnowledgeIndexVersion).where(
                    KnowledgeIndexVersion.document_version_id
                    == document_version_id,
                    KnowledgeIndexVersion.build_key == build_key,
                )
            ),
        )

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

    async def child_chunk_count(self, document_version_id: str) -> int:
        """只统计会写入向量库的Child，不把Parent重复建向量。"""

        count = await self._session.scalar(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.version_id == document_version_id,
                KnowledgeChunk.kind == "child",
            )
        )
        return int(count or 0)

    async def child_chunk_page(
        self,
        *,
        document_version_id: str,
        after_ordinal: int | None,
        limit: int,
    ) -> list[KnowledgeChunk]:
        """按不可变ordinal游标分页，避免大文档一次加载进内存。"""

        statement = select(KnowledgeChunk).where(
            KnowledgeChunk.version_id == document_version_id,
            KnowledgeChunk.kind == "child",
        )
        if after_ordinal is not None:
            statement = statement.where(KnowledgeChunk.ordinal > after_ordinal)
        result = await self._session.scalars(
            statement.order_by(KnowledgeChunk.ordinal).limit(limit)
        )
        return list(result)

    async def child_chunks_for_versions(
        self,
        document_version_ids: list[str],
    ) -> list[KnowledgeChunk]:
        """批量读取活动版本的全部Child，供单进程BM25索引构建。

        第7周MVP以索引版本ID缓存不可变语料；超大知识库应替换为OpenSearch等外部词法索引，
        但上层仍使用相同候选契约。
        """

        if not document_version_ids:
            return []
        result = await self._session.scalars(
            select(KnowledgeChunk)
            .where(
                KnowledgeChunk.version_id.in_(document_version_ids),
                KnowledgeChunk.kind == "child",
            )
            .order_by(KnowledgeChunk.version_id, KnowledgeChunk.ordinal)
        )
        return list(result)

    async def list_index_versions(
        self,
        document_version_id: str,
    ) -> list[KnowledgeIndexVersion]:
        result = await self._session.scalars(
            select(KnowledgeIndexVersion)
            .where(
                KnowledgeIndexVersion.document_version_id
                == document_version_id
            )
            .order_by(
                KnowledgeIndexVersion.created_at.desc(),
                KnowledgeIndexVersion.id.desc(),
            )
        )
        return list(result)

    async def active_indexes_for_retrieval(
        self,
        *,
        owner_user_id: str,
        business_domain: str,
    ) -> list[ActiveKnowledgeIndex]:
        """返回当前运营用户在指定业务域下的活动索引。

        权限标签包含JSON数组，跨MySQL/SQLite的交集语法并不统一，因此先在SQL中完成
        用户、状态和业务域过滤，再由Service用集合交集执行权限判断。
        """

        rows = (
            await self._session.execute(
                select(
                    KnowledgeIndexVersion,
                    KnowledgeDocumentVersion,
                    KnowledgeDocument,
                )
                .join(
                    KnowledgeDocumentVersion,
                    KnowledgeDocumentVersion.id
                    == KnowledgeIndexVersion.document_version_id,
                )
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id
                    == KnowledgeDocumentVersion.document_id,
                )
                .where(
                    KnowledgeIndexVersion.status == "active",
                    KnowledgeDocumentVersion.status == "ready",
                    KnowledgeDocument.status == "active",
                    KnowledgeDocument.created_by_user_id == owner_user_id,
                    KnowledgeDocument.business_domain == business_domain,
                )
                .order_by(
                    KnowledgeIndexVersion.activated_at.desc(),
                    KnowledgeIndexVersion.id,
                )
            )
        ).all()
        return [
            ActiveKnowledgeIndex(
                index_version=row[0],
                document_version=row[1],
                document=row[2],
            )
            for row in rows
        ]

    async def validate_retrieval_children(
        self,
        *,
        chunk_ids: list[str],
        index_version_ids: list[str],
    ) -> list[ValidatedKnowledgeChild]:
        """二次校验候选仍属于active索引和有效知识，不信任Milvus冗余字段。"""

        if not chunk_ids or not index_version_ids:
            return []
        rows = (
            await self._session.execute(
                select(
                    KnowledgeChunk,
                    KnowledgeIndexVersion,
                    KnowledgeDocumentVersion,
                    KnowledgeDocument,
                )
                .join(
                    KnowledgeDocumentVersion,
                    KnowledgeDocumentVersion.id == KnowledgeChunk.version_id,
                )
                .join(
                    KnowledgeDocument,
                    KnowledgeDocument.id
                    == KnowledgeDocumentVersion.document_id,
                )
                .join(
                    KnowledgeIndexVersion,
                    KnowledgeIndexVersion.document_version_id
                    == KnowledgeDocumentVersion.id,
                )
                .where(
                    KnowledgeChunk.id.in_(chunk_ids),
                    KnowledgeChunk.kind == "child",
                    KnowledgeIndexVersion.id.in_(index_version_ids),
                    KnowledgeIndexVersion.status == "active",
                    KnowledgeDocumentVersion.status == "ready",
                    KnowledgeDocument.status == "active",
                )
            )
        ).all()
        return [
            ValidatedKnowledgeChild(
                chunk=row[0],
                index_version=row[1],
                document_version=row[2],
                document=row[3],
            )
            for row in rows
        ]

    async def chunks_by_ids_any_version(
        self,
        chunk_ids: list[str],
    ) -> list[KnowledgeChunk]:
        """跨文档版本批量读取Parent；UUID主键保证全局唯一。"""

        if not chunk_ids:
            return []
        result = await self._session.scalars(
            select(KnowledgeChunk).where(KnowledgeChunk.id.in_(chunk_ids))
        )
        return list(result)

    async def supersede_active_indexes(
        self,
        *,
        document_id: str,
        except_index_version_id: str,
        finished_at: datetime,
    ) -> None:
        """同一逻辑文档只保留一个活动向量版本。

        通过文档版本表关联逻辑文档，在同一MySQL事务内完成旧版下线和新版激活。
        """

        document_version_ids = select(KnowledgeDocumentVersion.id).where(
            KnowledgeDocumentVersion.document_id == document_id
        )
        await self._session.execute(
            update(KnowledgeIndexVersion)
            .where(
                KnowledgeIndexVersion.document_version_id.in_(
                    document_version_ids
                ),
                KnowledgeIndexVersion.status == "active",
                KnowledgeIndexVersion.id != except_index_version_id,
            )
            .values(status="superseded", finished_at=finished_at)
        )

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
