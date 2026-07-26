"""知识文档版本管理，以及进程内 Mock 解析任务编排。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from bili_support.core.database import Database
from bili_support.core.exceptions import ConflictError, ResourceNotFoundError
from bili_support.core.security import UserContext
from bili_support.knowledge.loaders import (
    DocumentLoaderRegistry,
    DocumentLoadError,
)
from bili_support.knowledge.storage import LocalKnowledgeFileStore
from bili_support.models.entities import (
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    KnowledgeSourceBlock,
    new_id,
)
from bili_support.repositories import KnowledgeRepository, UserRepository
from bili_support.schemas.knowledge import (
    KnowledgeDocumentView,
    KnowledgeIngestionView,
    KnowledgeVersionView,
)


class KnowledgeIngestionService:
    """先持久化任务，再执行有边界的进程内解析；未来可替换为消息队列。"""

    def __init__(
            self,
            *,
            database: Database,
            loaders: DocumentLoaderRegistry,
            file_store: LocalKnowledgeFileStore,
            max_file_bytes: int,
    ) -> None:
        self._database = database
        self._loaders = loaders
        self._file_store = file_store
        self._max_file_bytes = max_file_bytes

    @property
    def max_file_bytes(self) -> int:
        """Return the configured upload ceiling so the transport can bound reads."""

        return self._max_file_bytes

    async def upload(
            self,
            *,
            actor: UserContext,
            content: bytes,
            filename: str,
            media_type: str,
            title: str,
            business_domain: str,
            access_scope: list[str],
            document_id: str | None,
    ) -> KnowledgeIngestionView:
        """校验文件、解析逻辑文档身份、执行幂等判断并创建入库任务。"""

        normalized_filename = Path(filename).name.strip()
        if not normalized_filename or not content:
            raise ConflictError("上传文件不能为空")
        if len(content) > self._max_file_bytes:
            raise ConflictError("上传文件超过大小限制")
        content_hash = sha256(content).hexdigest()

        # 第一段事务只保存“文档、版本、任务”事实，不在数据库事务内执行慢速文件解析。
        async with self._database.session() as session:
            users = UserRepository(session)
            owner = await users.get_or_create(actor.external_id, actor.display_name)
            repository = KnowledgeRepository(session)
            if document_id is None:
                # 未显式指定文档时，创建人 + 标题 + 业务域共同确定逻辑文档。
                document = await repository.active_document_by_identity(
                    owner_user_id=owner.id,
                    title=title,
                    business_domain=business_domain,
                )
                if document is None:
                    document = KnowledgeDocument(
                        created_by_user_id=owner.id,
                        title=title,
                        business_domain=business_domain,
                        access_scope=access_scope,
                        status="active",
                    )
                    repository.add_document(document)
                    await session.flush()
            else:
                # 显式版本更新只能操作自己创建且仍有效的文档。
                document = await repository.document(document_id)
                if (
                        document is None
                        or document.status != "active"
                        or document.created_by_user_id != owner.id
                ):
                    raise ResourceNotFoundError("知识文档不存在")

            existing = await repository.version_by_hash(document.id, content_hash)
            if existing is not None:
                # 相同字节直接返回已有版本；幂等不等于重新执行一次解析。
                job = await repository.latest_job_for_version(existing.id)
                if job is None:
                    raise AssertionError("knowledge version requires an ingestion job")
                result = await self._view(
                    repository,
                    document=document,
                    version=existing,
                    job=job,
                    deduplicated=True,
                )
                await session.commit()
                return result

            version_id = new_id()
            # 存储 key 由服务端生成，不采用用户文件名作为路径。
            storage_key = self._file_store.build_key(
                version_id=version_id,
                filename=normalized_filename,
            )
            version = KnowledgeDocumentVersion(
                id=version_id,
                document_id=document.id,
                version_number=await repository.next_version_number(document.id),
                content_sha256=content_hash,
                original_filename=normalized_filename,
                media_type=media_type or "application/octet-stream",
                size_bytes=len(content),
                storage_key=storage_key,
                status="pending",
            )
            job = KnowledgeIngestionJob(
                version_id=version.id,
                status="queued",
                attempt_count=0,
            )
            repository.add_version(version)
            repository.add_job(job)
            # 文件系统调用是阻塞 I/O，通过线程执行，避免阻塞 FastAPI 事件循环。
            await asyncio.to_thread(
                self._file_store.write,
                key=storage_key,
                content=content,
            )
            await session.commit()
            job_id = job.id

        # 5A 使用同步 Mock 调度。替换消息队列时，这里只需发布 job_id。
        await self._process(job_id)
        return await self.job(actor=actor, job_id=job_id)

    async def job(
            self,
            *,
            actor: UserContext,
            job_id: str,
    ) -> KnowledgeIngestionView:
        """读取任务聚合状态，并用文档创建人执行资源级隔离。"""

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.job(job_id)
            if job is None:
                raise ResourceNotFoundError("入库任务不存在")
            version = await repository.version(job.version_id)
            if version is None:
                raise ResourceNotFoundError("知识版本不存在")
            document = await repository.document(version.document_id)
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            if document is None or document.created_by_user_id != owner.id:
                # 对无权访问的资源同样返回不存在，避免泄露资源 ID 是否有效。
                raise ResourceNotFoundError("入库任务不存在")
            result = await self._view(
                repository,
                document=document,
                version=version,
                job=job,
                deduplicated=False,
            )
            await session.commit()
            return result

    async def retry(
            self,
            *,
            actor: UserContext,
            job_id: str,
    ) -> KnowledgeIngestionView:
        """仅允许失败任务重试；成功或执行中的任务不能重复触发。"""

        current = await self.job(actor=actor, job_id=job_id)
        if current.job_status != "failed":
            raise ConflictError("只有失败的入库任务可以重试")
        await self._process(job_id)
        return await self.job(actor=actor, job_id=job_id)

    async def list_documents(
            self,
            *,
            actor: UserContext,
    ) -> list[KnowledgeDocumentView]:
        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            documents = await KnowledgeRepository(session).list_documents(
                owner_user_id=owner.id
            )
            result = [
                KnowledgeDocumentView.model_validate(document)
                for document in documents
            ]
            await session.commit()
            return result

    async def versions(
            self,
            *,
            actor: UserContext,
            document_id: str,
    ) -> list[KnowledgeVersionView]:
        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            repository = KnowledgeRepository(session)
            document = await repository.document(document_id)
            if (
                    document is None
                    or document.status != "active"
                    or document.created_by_user_id != owner.id
            ):
                raise ResourceNotFoundError("知识文档不存在")
            versions = await repository.list_versions(document_id)
            result = [
                KnowledgeVersionView.model_validate(version)
                for version in versions
            ]
            await session.commit()
            return result

    async def delete(
            self,
            *,
            actor: UserContext,
            document_id: str,
    ) -> None:
        """软删除逻辑文档，保留版本、原文件和任务作为审计依据。"""

        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            document = await KnowledgeRepository(session).document(document_id)
            if (
                    document is None
                    or document.status != "active"
                    or document.created_by_user_id != owner.id
            ):
                raise ResourceNotFoundError("知识文档不存在")
            document.status = "deleted"
            document.updated_at = datetime.now(UTC)
            await session.commit()

    async def _process(self, job_id: str) -> None:
        """执行一次解析尝试；用两段短事务包围数据库外的文件解析。"""

        # 第一段短事务：把 queued/failed 任务声明为 processing 并记录尝试次数。
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.job(job_id)
            if job is None:
                raise ResourceNotFoundError("入库任务不存在")
            version = await repository.version(job.version_id)
            if version is None:
                raise ResourceNotFoundError("知识版本不存在")
            job.status = "processing"
            job.attempt_count += 1
            job.error_code = None
            job.started_at = datetime.now(UTC)
            job.finished_at = None
            await session.commit()
            storage_key = version.storage_key
            filename = version.original_filename
            media_type = version.media_type

        # 文件读取和第三方解析不占用数据库事务，避免长时间持锁。
        try:
            content = await asyncio.to_thread(self._file_store.read, storage_key)
            loaded = await asyncio.to_thread(
                self._loaders.load,
                content=content,
                filename=filename,
                media_type=media_type,
            )
            if not loaded.blocks:
                raise DocumentLoadError("DOCUMENT_EMPTY")
        except (DocumentLoadError, OSError) as exc:
            # 对外只落稳定错误码；底层堆栈保留在异常链/日志处理范围内。
            error_code = (
                exc.code
                if isinstance(exc, DocumentLoadError)
                else "DOCUMENT_STORAGE_UNAVAILABLE"
            )
            await self._mark_failed(job_id, error_code)
            return

        # 第二段短事务：用本次完整解析结果替换旧块，然后原子地标记成功。
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.job(job_id)
            if job is None:
                raise ResourceNotFoundError("入库任务不存在")
            version = await repository.version(job.version_id)
            if version is None:
                raise ResourceNotFoundError("知识版本不存在")
            await repository.delete_blocks(version.id)
            repository.add_blocks(
                [
                    KnowledgeSourceBlock(
                        version_id=version.id,
                        ordinal=block.ordinal,
                        block_type=block.block_type.value,
                        content=block.content,
                        page_number=block.page_number,
                        heading_path=list(block.heading_path),
                        metadata_json=block.metadata,
                    )
                    for block in loaded.blocks
                ]
            )
            version.status = "ready"
            job.status = "succeeded"
            job.error_code = None
            job.finished_at = datetime.now(UTC)
            await session.commit()

    async def _mark_failed(self, job_id: str, error_code: str) -> None:
        """让版本和任务状态一起失败，避免出现任务失败但版本仍 pending。"""

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.job(job_id)
            if job is None:
                raise ResourceNotFoundError("入库任务不存在")
            version = await repository.version(job.version_id)
            if version is None:
                raise ResourceNotFoundError("知识版本不存在")
            version.status = "failed"
            job.status = "failed"
            job.error_code = error_code
            job.finished_at = datetime.now(UTC)
            await session.commit()

    @staticmethod
    async def _view(
            repository: KnowledgeRepository,
            *,
            document: KnowledgeDocument,
            version: KnowledgeDocumentVersion,
            job: KnowledgeIngestionJob,
            deduplicated: bool,
    ) -> KnowledgeIngestionView:
        """把三个持久化层次聚合成稳定 API 视图。"""

        return KnowledgeIngestionView(
            document=KnowledgeDocumentView.model_validate(document),
            version=KnowledgeVersionView.model_validate(version),
            job_id=job.id,
            job_status=job.status,
            attempt_count=job.attempt_count,
            block_count=await repository.block_count(version.id),
            deduplicated=deduplicated,
            error_code=job.error_code,
        )
