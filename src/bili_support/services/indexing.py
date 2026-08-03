"""第六周Child Chunk批量向量化、逻辑索引版本构建与安全切换。"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from bili_support.core.database import Database
from bili_support.core.exceptions import (
    ConflictError,
    ResourceNotFoundError,
    ServiceNotReadyError,
)
from bili_support.core.security import UserContext
from bili_support.knowledge.embedding import (
    EmbeddingProvider,
    EmbeddingRequest,
)
from bili_support.knowledge.vector_store import (
    VectorRecord,
    VectorStore,
)
from bili_support.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeIndexJob,
    KnowledgeIndexVersion,
)
from bili_support.repositories import KnowledgeRepository, UserRepository
from bili_support.schemas.knowledge import (
    KnowledgeIndexingView,
    KnowledgeIndexVersionView,
)
from bili_support.services.lexical_sync import LexicalIndexSyncService


class KnowledgeIndexingService:
    """编排“分页读Child→批量Embedding→Milvus写入→原子激活”。

    当前API请求内同步执行，便于学习和本地调试；任务表和幂等边界已经独立，
    后续换成消息队列只需让Worker调用 ``process(job_id)``。
    """

    def __init__(
            self,
            *,
            database: Database,
            embedding_provider: EmbeddingProvider,
            vector_store: VectorStore | None,
            embedding_provider_name: str,
            embedding_model: str,
            embedding_dimension: int,
            embedding_batch_size: int,
            embedding_timeout_seconds: float,
            collection_name: str,
            chunk_schema_version: str,
            lexical_sync_service: LexicalIndexSyncService | None = None,
    ) -> None:
        self._database = database
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._embedding_provider_name = embedding_provider_name
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._batch_size = embedding_batch_size
        self._embedding_timeout_seconds = embedding_timeout_seconds
        self._collection_name = collection_name
        self._chunk_schema_version = chunk_schema_version
        self._lexical_sync_service = lexical_sync_service

    async def build(
            self,
            *,
            actor: UserContext,
            document_version_id: str,
    ) -> KnowledgeIndexingView:
        """幂等创建索引版本并立即交给当前同步Mock调度器执行。"""

        self._require_vector_store()
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            document, version = await self._owned_version(
                repository=repository,
                owner_user_id=owner.id,
                document_version_id=document_version_id,
            )
            # 同一逻辑文档的并发build请求在这里串行，唯一约束仍做最终兜底。
            locked_document = await repository.lock_document(document.id)
            if locked_document is None:
                raise ResourceNotFoundError("知识文档不存在")
            document = locked_document
            if version.status != "ready":
                raise ConflictError(
                    "只有解析完成的知识版本可以构建向量索引",
                    details={"version_status": version.status},
                )

            build_key = self._build_key(version)
            existing = await repository.index_version_by_build_key(
                document_version_id=version.id,
                build_key=build_key,
            )
            if existing is not None:
                job = await repository.index_job_for_version(existing.id)
                if job is None:
                    raise AssertionError("index version requires an index job")
                return self._view(
                    index_version=existing,
                    job=job,
                    deduplicated=True,
                )

            index_version = KnowledgeIndexVersion(
                document_version_id=version.id,
                collection_name=self._collection_name,
                embedding_provider=self._embedding_provider_name,
                embedding_model=self._embedding_model,
                embedding_dimension=self._embedding_dimension,
                chunk_schema_version=self._chunk_schema_version,
                build_key=build_key,
                status="building",
                total_chunks=0,
                indexed_chunks=0,
            )
            repository.add_index_version(index_version)
            await session.flush()
            job = KnowledgeIndexJob(
                index_version_id=index_version.id,
                status="queued",
                attempt_count=0,
            )
            repository.add_index_job(job)
            await session.flush()
            job_id = job.id
            await session.commit()

        # 6B暂用同步调度。未来队列只发布job_id，状态机与Worker逻辑不变。
        await self.process(job_id)
        return await self.job(actor=actor, job_id=job_id)

    async def job(
            self,
            *,
            actor: UserContext,
            job_id: str,
    ) -> KnowledgeIndexingView:
        """读取任务状态，并用所属文档执行用户隔离。"""

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            job = await repository.index_job(job_id)
            if job is None:
                raise ResourceNotFoundError("索引任务不存在")
            index_version = await repository.index_version(job.index_version_id)
            if index_version is None:
                raise ResourceNotFoundError("索引版本不存在")
            await self._owned_version(
                repository=repository,
                owner_user_id=owner.id,
                document_version_id=index_version.document_version_id,
            )
            return self._view(
                index_version=index_version,
                job=job,
                deduplicated=False,
            )

    async def retry(
            self,
            *,
            actor: UserContext,
            job_id: str,
    ) -> KnowledgeIndexingView:
        """失败任务复用同一index_version_id；处理前只清理该版本的残留向量。"""

        current = await self.job(actor=actor, job_id=job_id)
        if current.job_status != "failed":
            raise ConflictError("只有失败的索引任务可以重试")
        self._require_vector_store()
        await self.process(job_id)
        return await self.job(actor=actor, job_id=job_id)

    async def list_versions(
            self,
            *,
            actor: UserContext,
            document_version_id: str,
    ) -> list[KnowledgeIndexVersionView]:
        """查看同一知识版本因模型或契约变化产生的全部索引版本。"""

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            await self._owned_version(
                repository=repository,
                owner_user_id=owner.id,
                document_version_id=document_version_id,
            )
            versions = await repository.list_index_versions(document_version_id)
            return [
                KnowledgeIndexVersionView.model_validate(index)
                for index in versions
            ]

    async def process(self, job_id: str) -> None:
        """执行一次完整构建；任何失败都落稳定状态，不泄漏异常详情。"""

        vector_store = self._require_vector_store()
        try:
            context = await self._start_attempt(job_id)
            index_version, document, version = context
            if index_version.total_chunks == 0:
                raise ValueError("INDEX_NO_CHILD_CHUNKS")

            await vector_store.ensure_collection()
            # 重试只清理当前building版本，旧active版本继续在线服务。
            await vector_store.delete_index_version(index_version.id)
            await self._write_batches(
                index_version=index_version,
                document=document,
                version=version,
                vector_store=vector_store,
            )
            await self._activate(job_id)
            if self._lexical_sync_service is not None:
                # ES同步失败保留旧Alias；向量索引成功状态不被可降级词法副本反向污染。
                await self._lexical_sync_service.synchronize("knowledge_index_activate")
        except Exception as exc:
            error_code = self._error_code(exc)
            await self._mark_failed(job_id=job_id, error_code=error_code)
            # 删除失败构建是尽力而为；Milvus本身故障时仍以MySQL failed状态隔离。
            try:
                failed_index_id = await self._index_id_for_job(job_id)
                await vector_store.delete_index_version(failed_index_id)
            except Exception:
                pass

    async def _start_attempt(
            self,
            job_id: str,
    ) -> tuple[
        KnowledgeIndexVersion,
        KnowledgeDocument,
        KnowledgeDocumentVersion,
    ]:
        """短事务进入processing并冻结本次构建需要的事实快照。"""

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.index_job(job_id)
            if job is None:
                raise ResourceNotFoundError("索引任务不存在")
            index_version = await repository.index_version(job.index_version_id)
            if index_version is None:
                raise ResourceNotFoundError("索引版本不存在")
            version = await repository.version(index_version.document_version_id)
            if version is None:
                raise ResourceNotFoundError("知识版本不存在")
            document = await repository.document(version.document_id)
            if document is None or document.status != "active":
                raise ResourceNotFoundError("知识文档不存在")
            if version.status != "ready":
                raise ConflictError("知识版本尚未解析完成")

            now = datetime.now(UTC)
            total_chunks = await repository.child_chunk_count(version.id)
            job.status = "processing"
            job.attempt_count += 1
            job.error_code = None
            job.started_at = now
            job.finished_at = None
            index_version.status = "building"
            index_version.total_chunks = total_chunks
            index_version.indexed_chunks = 0
            index_version.activated_at = None
            index_version.finished_at = None
            await session.commit()
            return index_version, document, version

    async def _write_batches(
            self,
            *,
            index_version: KnowledgeIndexVersion,
            document: KnowledgeDocument,
            version: KnowledgeDocumentVersion,
            vector_store: VectorStore,
    ) -> None:
        """游标分页读取不可变Child，并在每批成功后提交进度。"""

        after_ordinal: int | None = None
        while True:
            chunks = await self._child_page(
                document_version_id=version.id,
                after_ordinal=after_ordinal,
            )
            if not chunks:
                return
            response = await self._embedding_provider.embed(
                EmbeddingRequest(
                    texts=tuple(chunk.content for chunk in chunks),
                    model=index_version.embedding_model,
                    timeout_seconds=self._embedding_timeout_seconds,
                )
            )
            self._validate_embedding_response(
                response_dimension=response.dimension,
                vector_count=len(response.vectors),
                chunk_count=len(chunks),
            )
            records = [
                VectorRecord(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    version_id=version.id,
                    index_version_id=index_version.id,
                    business_domain=document.business_domain,
                    access_scope=tuple(document.access_scope),
                    embedding_model=response.model,
                    vector=response.vectors[position].values,
                )
                for position, chunk in enumerate(chunks)
            ]
            written = await vector_store.upsert(records)
            if written != len(records):
                raise ValueError("INDEX_PARTIAL_UPSERT")
            await self._increase_progress(index_version.id, written)
            after_ordinal = chunks[-1].ordinal

    async def _child_page(
            self,
            *,
            document_version_id: str,
            after_ordinal: int | None,
    ) -> list[KnowledgeChunk]:
        async with self._database.session() as session:
            return await KnowledgeRepository(session).child_chunk_page(
                document_version_id=document_version_id,
                after_ordinal=after_ordinal,
                limit=self._batch_size,
            )

    async def _increase_progress(
            self,
            index_version_id: str,
            count: int,
    ) -> None:
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            index_version = await repository.index_version(index_version_id)
            if index_version is None:
                raise ResourceNotFoundError("索引版本不存在")
            index_version.indexed_chunks += count
            if index_version.indexed_chunks > index_version.total_chunks:
                raise ValueError("INDEX_PROGRESS_OVERFLOW")
            await session.commit()

    async def _activate(self, job_id: str) -> None:
        """同一事务先下线旧active，再激活完整新版本。"""

        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.index_job(job_id)
            if job is None:
                raise ResourceNotFoundError("索引任务不存在")
            index_version = await repository.index_version(job.index_version_id)
            if index_version is None:
                raise ResourceNotFoundError("索引版本不存在")
            version = await repository.version(index_version.document_version_id)
            if version is None:
                raise ResourceNotFoundError("知识版本不存在")
            if index_version.indexed_chunks != index_version.total_chunks:
                raise ValueError("INDEX_INCOMPLETE")

            now = datetime.now(UTC)
            # 锁住逻辑文档，使多个不同配置的构建不能同时把自己声明为active。
            document = await repository.lock_document(version.document_id)
            if document is None or document.status != "active":
                raise ResourceNotFoundError("知识文档不存在")
            await repository.supersede_active_indexes(
                document_id=version.document_id,
                except_index_version_id=index_version.id,
                finished_at=now,
            )
            # 用户查询不传版本号；当前内容版本随索引激活在同一事务中切换。
            await repository.switch_current_document_version(
                document_id=version.document_id,
                current_version_id=version.id,
            )
            index_version.status = "active"
            index_version.activated_at = now
            index_version.finished_at = now
            job.status = "succeeded"
            job.error_code = None
            job.finished_at = now
            await session.commit()

    async def _mark_failed(self, *, job_id: str, error_code: str) -> None:
        async with self._database.session() as session:
            repository = KnowledgeRepository(session)
            job = await repository.index_job(job_id)
            if job is None:
                return
            index_version = await repository.index_version(job.index_version_id)
            if index_version is None:
                return
            now = datetime.now(UTC)
            job.status = "failed"
            job.error_code = error_code
            job.finished_at = now
            index_version.status = "failed"
            index_version.finished_at = now
            await session.commit()

    async def _index_id_for_job(self, job_id: str) -> str:
        async with self._database.session() as session:
            job = await KnowledgeRepository(session).index_job(job_id)
            if job is None:
                raise ResourceNotFoundError("索引任务不存在")
            return job.index_version_id

    async def _owned_version(
            self,
            *,
            repository: KnowledgeRepository,
            owner_user_id: str,
            document_version_id: str,
    ) -> tuple[KnowledgeDocument, KnowledgeDocumentVersion]:
        version = await repository.version(document_version_id)
        if version is None:
            raise ResourceNotFoundError("知识版本不存在")
        document = await repository.document(version.document_id)
        if (
                document is None
                or document.status != "active"
                or document.created_by_user_id != owner_user_id
        ):
            # 对其他用户统一表现为不存在，避免泄漏知识资产身份。
            raise ResourceNotFoundError("知识版本不存在")
        return document, version

    def _build_key(self, version: KnowledgeDocumentVersion) -> str:
        """把所有会改变向量结果或物理Schema的因素纳入幂等键。"""

        payload = "|".join(
            (
                version.content_sha256,
                self._embedding_provider_name,
                self._embedding_model,
                str(self._embedding_dimension),
                self._chunk_schema_version,
                self._collection_name,
            )
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def _validate_embedding_response(
            self,
            *,
            response_dimension: int,
            vector_count: int,
            chunk_count: int,
    ) -> None:
        if response_dimension != self._embedding_dimension:
            raise ValueError("INDEX_EMBEDDING_DIMENSION_MISMATCH")
        if vector_count != chunk_count:
            raise ValueError("INDEX_EMBEDDING_COUNT_MISMATCH")

    def _require_vector_store(self) -> VectorStore:
        if self._vector_store is None:
            raise ServiceNotReadyError()
        return self._vector_store

    @staticmethod
    def _error_code(exc: Exception) -> str:
        """只保存稳定原因码；具体异常栈由后续结构化日志/Trace承载。"""

        if isinstance(exc, ValueError):
            message = str(exc)
            if message.startswith("INDEX_"):
                return message[:64]
        if isinstance(exc, (ConflictError, ResourceNotFoundError)):
            return "INDEX_SOURCE_NOT_READY"
        return "INDEX_BUILD_FAILED"

    @staticmethod
    def _view(
            *,
            index_version: KnowledgeIndexVersion,
            job: KnowledgeIndexJob,
            deduplicated: bool,
    ) -> KnowledgeIndexingView:
        return KnowledgeIndexingView(
            index=KnowledgeIndexVersionView.model_validate(index_version),
            job_id=job.id,
            job_status=job.status,
            attempt_count=job.attempt_count,
            deduplicated=deduplicated,
            error_code=job.error_code,
        )
