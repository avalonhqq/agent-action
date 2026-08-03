"""知识文档版本管理，以及进程内 Mock 解析任务编排。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from bili_support.core.database import Database
from bili_support.core.exceptions import ConflictError, ResourceNotFoundError
from bili_support.core.security import UserContext
from bili_support.knowledge.chunk_strategies import StrategySelector
from bili_support.knowledge.chunking import ChunkKind, DocumentKnowledgeType
from bili_support.knowledge.loaders import (
    DocumentLoaderRegistry,
    DocumentLoadError,
)
from bili_support.knowledge.small_to_big import ChildChunkHit, SmallToBigExpander
from bili_support.knowledge.storage import LocalKnowledgeFileStore
from bili_support.knowledge.types import LoadedSourceBlock, SourceBlockType
from bili_support.models.entities import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIngestionJob,
    KnowledgeSourceBlock,
    new_id,
)
from bili_support.repositories import KnowledgeRepository, UserRepository
from bili_support.schemas.knowledge import (
    ChildChunkHitInput,
    ChunkDebugView,
    KnowledgeChunkView,
    KnowledgeDocumentView,
    KnowledgeIngestionView,
    KnowledgeVersionView,
    ParentChunkContextView,
)
from bili_support.services.lexical_sync import LexicalIndexSyncService


class KnowledgeIngestionService:
    """先持久化任务，再执行有边界的进程内解析；未来可替换为消息队列。"""

    def __init__(
            self,
            *,
            database: Database,
            loaders: DocumentLoaderRegistry,
            chunk_strategies: StrategySelector,
            file_store: LocalKnowledgeFileStore,
            max_file_bytes: int,
            small_to_big: SmallToBigExpander | None = None,
            lexical_sync_service: LexicalIndexSyncService | None = None,
    ) -> None:
        self._database = database
        self._loaders = loaders
        self._chunk_strategies = chunk_strategies
        self._file_store = file_store
        self._max_file_bytes = max_file_bytes
        self._small_to_big = small_to_big or SmallToBigExpander()
        self._lexical_sync_service = lexical_sync_service

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
            knowledge_type: DocumentKnowledgeType,
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
        backfilled_existing = False

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
                    knowledge_type=knowledge_type.value,
                )
                if document is None:
                    document = KnowledgeDocument(
                        created_by_user_id=owner.id,
                        title=title,
                        business_domain=business_domain,
                        knowledge_type=knowledge_type.value,
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
                if document.knowledge_type != knowledge_type.value:
                    raise ConflictError("文档知识类型与已有文档不一致")

            existing = await repository.version_by_hash(document.id, content_hash)
            if existing is not None:
                # 相同字节直接返回已有版本；幂等不等于重新执行一次解析。
                job = await repository.latest_job_for_version(existing.id)
                if job is None:
                    raise AssertionError("knowledge version requires an ingestion job")
                # 兼容5A时期已经成功解析但尚未生成Chunk的旧版本：相同文件再次
                # 上传时原地补建索引，而不是被SHA-256幂等永久挡在旧结果上。
                needs_chunk_backfill = (
                    job.status == "succeeded"
                    and await repository.block_count(existing.id) > 0
                    and await repository.chunk_count(existing.id) == 0
                )
                if needs_chunk_backfill:
                    backfilled_existing = True
                    job_id = job.id
                    await session.commit()
                else:
                    result = await self._view(
                        repository,
                        document=document,
                        version=existing,
                        job=job,
                        deduplicated=True,
                    )
                    await session.commit()
                    return result
            else:
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
        result = await self.job(actor=actor, job_id=job_id)
        if backfilled_existing:
            return result.model_copy(update={"deduplicated": True})
        return result

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

    async def chunks(
        self,
        *,
        actor: UserContext,
        version_id: str,
        kind: str | None,
    ) -> list[KnowledgeChunkView]:
        """返回当前用户版本的分块结果，供上传后直接检查解析质量。"""

        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            repository = KnowledgeRepository(session)
            version = await repository.version(version_id)
            document = (
                await repository.document(version.document_id)
                if version is not None
                else None
            )
            if (
                    document is None
                    or document.status != "active"
                    or document.created_by_user_id != owner.id
            ):
                raise ResourceNotFoundError("知识版本不存在")
            chunks = await repository.list_chunks(version_id, kind=kind)
            result = [KnowledgeChunkView.model_validate(chunk) for chunk in chunks]
            await session.commit()
            return result

    async def expand_child_hits(
        self,
        *,
        actor: UserContext,
        version_id: str,
        hits: list[ChildChunkHitInput],
    ) -> list[ParentChunkContextView]:
        """把有序Child命中批量回溯成去重Parent上下文。"""

        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            repository = KnowledgeRepository(session)
            version = await repository.version(version_id)
            document = (
                await repository.document(version.document_id)
                if version is not None
                else None
            )
            if (
                document is None
                or document.status != "active"
                or document.created_by_user_id != owner.id
            ):
                raise ResourceNotFoundError("知识版本不存在")

            # 第一次批量查询：校验所有检索命中确实是本版本的Child。
            child_ids = list(dict.fromkeys(hit.chunk_id for hit in hits))
            children = await repository.chunks_by_ids(
                version_id=version_id,
                chunk_ids=child_ids,
            )
            children_by_id = {chunk.id: chunk for chunk in children}
            invalid_child_ids = [
                chunk_id
                for chunk_id in child_ids
                if (
                    (chunk := children_by_id.get(chunk_id)) is None
                    or chunk.kind != ChunkKind.CHILD.value
                    or chunk.parent_chunk_id is None
                )
            ]
            if invalid_child_ids:
                raise ConflictError(
                    "Small-to-Big只能接收当前版本中带Parent的Child命中",
                    details={"invalid_chunk_ids": invalid_child_ids},
                )

            plans = self._small_to_big.plan(
                hits=[
                    ChildChunkHit(chunk_id=hit.chunk_id, score=hit.score)
                    for hit in hits
                ],
                child_parent_ids={
                    child.id: str(child.parent_chunk_id) for child in children
                },
            )

            # 第二次批量查询：一次取回所有Parent；最终顺序由plan恢复而非SQL决定。
            parents = await repository.chunks_by_ids(
                version_id=version_id,
                chunk_ids=[plan.parent_chunk_id for plan in plans],
            )
            parents_by_id = {chunk.id: chunk for chunk in parents}
            invalid_parent_ids = [
                plan.parent_chunk_id
                for plan in plans
                if (
                    (parent := parents_by_id.get(plan.parent_chunk_id)) is None
                    or parent.kind != ChunkKind.PARENT.value
                )
            ]
            if invalid_parent_ids:
                raise ConflictError(
                    "Child关联的Parent不存在或类型错误",
                    details={"invalid_parent_ids": invalid_parent_ids},
                )

            result = [
                ParentChunkContextView(
                    parent=KnowledgeChunkView.model_validate(
                        parents_by_id[plan.parent_chunk_id]
                    ),
                    matched_child_ids=list(plan.matched_child_ids),
                    best_child_score=plan.best_child_score,
                    first_child_rank=plan.first_child_rank,
                )
                for plan in plans
            ]
            await session.commit()
            return result

    def debug_chunks(
        self,
        *,
        knowledge_type: DocumentKnowledgeType,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> ChunkDebugView:
        """直接运行确定性策略但不写数据库，供5C逐块调试。"""

        try:
            chunks = self._chunk_strategies.select(knowledge_type).chunk(
                blocks=blocks
            )
        except ValueError as exc:
            raise ConflictError(
                "分块策略无法处理当前SourceBlock",
                details={"reason": str(exc)},
            ) from exc

        parent_count = sum(chunk.kind is ChunkKind.PARENT for chunk in chunks)
        child_count = sum(chunk.kind is ChunkKind.CHILD for chunk in chunks)
        strategy_counts: dict[str, int] = {}
        represented_ordinals: set[int] = set()
        for chunk in chunks:
            represented_ordinals.add(chunk.source_block_ordinal)
            # FAQ/Manual/Policy可能把多个SourceBlock合并成一个Parent，完整来源
            # 会保存在source_block_ordinals中，不能只看主source_block_ordinal。
            grouped_ordinals = chunk.metadata.get("source_block_ordinals")
            if isinstance(grouped_ordinals, list):
                represented_ordinals.update(
                    value for value in grouped_ordinals if isinstance(value, int)
                )
            strategy = str(chunk.metadata.get("strategy", "unknown"))
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        # 标题已经进入后续正文的heading_path，不单独生成Chunk属于正常设计。
        unrepresented = [
            block.ordinal
            for block in blocks
            if (
                block.block_type is not SourceBlockType.HEADING
                and block.ordinal not in represented_ordinals
            )
        ]
        return ChunkDebugView(
            chunks=chunks,
            parent_count=parent_count,
            child_count=child_count,
            strategy_counts=strategy_counts,
            unrepresented_source_ordinals=unrepresented,
        )

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
        if self._lexical_sync_service is not None:
            await self._lexical_sync_service.synchronize("knowledge_document_delete")

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
            document = await repository.document(version.document_id)
            if document is None:
                raise ResourceNotFoundError("知识文档不存在")
            job.status = "processing"
            job.attempt_count += 1
            job.error_code = None
            job.started_at = datetime.now(UTC)
            job.finished_at = None
            await session.commit()
            storage_key = version.storage_key
            filename = version.original_filename
            media_type = version.media_type
            knowledge_type = document.knowledge_type

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
            drafts = self._chunk_strategies.select(
                DocumentKnowledgeType(knowledge_type)
            ).chunk(blocks=loaded.blocks)
            if not drafts:
                raise ValueError("chunk strategy returned no drafts")
        except (DocumentLoadError, OSError, ValueError) as exc:
            # 对外只落稳定错误码；底层堆栈保留在异常链/日志处理范围内。
            error_code = (
                exc.code
                if isinstance(exc, DocumentLoadError)
                else (
                    "DOCUMENT_STORAGE_UNAVAILABLE"
                    if isinstance(exc, OSError)
                    else "DOCUMENT_CHUNK_FAILED"
                )
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
            await repository.delete_chunks(version.id)
            await repository.delete_blocks(version.id)
            source_blocks = [
                KnowledgeSourceBlock(
                    id=new_id(),
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
            repository.add_blocks(source_blocks)
            await session.flush()
            source_ids = {block.ordinal: block.id for block in source_blocks}
            chunk_ids = {draft.local_id: new_id() for draft in drafts}

            def build_chunk(index: int) -> KnowledgeChunk:
                draft = drafts[index]
                parent_id = (
                    chunk_ids[draft.parent_local_id]
                    if draft.parent_local_id is not None
                    else None
                )
                return KnowledgeChunk(
                    id=chunk_ids[draft.local_id],
                    version_id=version.id,
                    source_block_id=source_ids[draft.source_block_ordinal],
                    parent_chunk_id=parent_id,
                    kind=draft.kind.value,
                    ordinal=index,
                    content=draft.content,
                    char_count=len(draft.content),
                    metadata_json=draft.metadata,
                )

            parent_chunks = [
                build_chunk(index)
                for index, draft in enumerate(drafts)
                if draft.kind is ChunkKind.PARENT
            ]
            child_chunks = [
                build_chunk(index)
                for index, draft in enumerate(drafts)
                if draft.kind is ChunkKind.CHILD
            ]
            repository.add_chunks(parent_chunks)
            await session.flush()
            repository.add_chunks(child_chunks)
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
            chunk_count=await repository.chunk_count(version.id),
            deduplicated=deduplicated,
            error_code=job.error_code,
        )
