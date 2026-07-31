"""第六周6C：活动索引解析、向量召回、MySQL复核和Small-to-Big还原。"""

from __future__ import annotations

import asyncio

from bili_support.core.database import Database
from bili_support.core.exceptions import ServiceNotReadyError
from bili_support.core.security import UserContext
from bili_support.knowledge.bm25 import (
    BM25Document,
    BM25Index,
    ChineseSearchTokenizer,
)
from bili_support.knowledge.embedding import EmbeddingProvider, EmbeddingRequest
from bili_support.knowledge.retrieval import (
    ChildRetrievalCandidate,
    RetrievalMode,
    RetrievalSource,
)
from bili_support.knowledge.small_to_big import ChildChunkHit, SmallToBigExpander
from bili_support.knowledge.vector_store import (
    VectorSearchQuery,
    VectorStore,
)
from bili_support.llm.context import QueryRewriteResult, StandaloneQueryRewriter
from bili_support.models import KnowledgeChunk
from bili_support.repositories import KnowledgeRepository, UserRepository
from bili_support.repositories.knowledge import (
    ActiveKnowledgeIndex,
    ValidatedKnowledgeChild,
)
from bili_support.schemas.knowledge import (
    KnowledgeChunkView,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalView,
    RetrievalChildHitView,
    RetrievalParentView,
)


class KnowledgeRetrievalService:
    """执行可解释的单路向量检索；混合召回和Rerank留到第7周。"""

    def __init__(
            self,
            *,
            database: Database,
            embedding_provider: EmbeddingProvider,
            vector_store: VectorStore | None,
            embedding_model: str,
            embedding_dimension: int,
            embedding_timeout_seconds: float,
        collection_name: str,
        rewriter: StandaloneQueryRewriter | None = None,
        small_to_big: SmallToBigExpander | None = None,
        bm25_tokenizer: ChineseSearchTokenizer | None = None,
    ) -> None:
        self._database = database
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._embedding_timeout_seconds = embedding_timeout_seconds
        self._collection_name = collection_name
        self._rewriter = rewriter or StandaloneQueryRewriter()
        self._small_to_big = small_to_big or SmallToBigExpander()
        self._bm25_tokenizer = bm25_tokenizer or ChineseSearchTokenizer()
        # Key是活动索引版本集合；知识版本不可变，因此切换active后自然生成新缓存。
        self._bm25_indexes: dict[tuple[str, ...], BM25Index] = {}
        self._bm25_lock = asyncio.Lock()

    async def retrieve(
            self,
            *,
            actor: UserContext,
            request: KnowledgeRetrievalRequest,
    ) -> KnowledgeRetrievalView:
        """从独立查询到Parent上下文，返回每个可审计中间结果。"""

        rewrite = self._rewriter.rewrite(
            request.query,
            list(request.history),
        )
        targets = await self._active_targets(
            actor=actor,
            business_domain=request.business_domain.value,
            allowed_scopes=request.allowed_scopes,
        )
        compatible_targets = (
            [
                target
                for target in targets
                if (
                    target.index_version.collection_name
                    == self._collection_name
                    and target.index_version.embedding_model
                    == self._embedding_model
                    and target.index_version.embedding_dimension
                    == self._embedding_dimension
                )
            ]
            if request.retrieval_mode is RetrievalMode.VECTOR
            else targets
        )
        incompatible_count = len(targets) - len(compatible_targets)
        active_index_ids = tuple(
            target.index_version.id for target in compatible_targets
        )
        if not active_index_ids:
            return self._empty_view(
                rewrite=rewrite,
                retrieval_mode=request.retrieval_mode,
                incompatible_index_count=incompatible_count,
            )

        # 适度过取候选，为活动状态刚切换或权限副本延迟导致的二次过滤留余量。
        recall_top_k = min(request.child_top_k * 2, 100)
        if request.retrieval_mode is RetrievalMode.VECTOR:
            vector_store = self._require_vector_store()
            embedded = await self._embedding_provider.embed(
                EmbeddingRequest(
                    texts=(rewrite.standalone_query,),
                    model=self._embedding_model,
                    timeout_seconds=self._embedding_timeout_seconds,
                )
            )
            if (
                embedded.dimension != self._embedding_dimension
                or len(embedded.vectors) != 1
            ):
                raise ServiceNotReadyError()
            vector_hits = await vector_store.search(
                VectorSearchQuery(
                    vector=embedded.vectors[0].values,
                    top_k=recall_top_k,
                    business_domain=request.business_domain.value,
                    allowed_scopes=request.allowed_scopes,
                    index_version_ids=active_index_ids,
                )
            )
            raw_hits = tuple(
                ChildRetrievalCandidate(
                    chunk_id=hit.chunk_id,
                    document_id=hit.document_id,
                    version_id=hit.version_id,
                    index_version_id=hit.index_version_id,
                    source=RetrievalSource.VECTOR,
                    score=hit.score,
                )
                for hit in vector_hits
            )
        else:
            bm25_index = await self._bm25_index(compatible_targets)
            raw_hits = bm25_index.search(
                query=rewrite.standalone_query,
                top_k=recall_top_k,
            )
        (
            child_hits,
            parents,
            discarded_child_count,
            discarded_parent_count,
        ) = await self._validate_and_expand(
            raw_hits=raw_hits,
            active_index_ids=active_index_ids,
            owner_external_id=actor.external_id,
            owner_display_name=actor.display_name,
            business_domain=request.business_domain.value,
            allowed_scopes=request.allowed_scopes,
            child_top_k=request.child_top_k,
            parent_top_k=request.parent_top_k,
        )
        return KnowledgeRetrievalView(
            rewrite=rewrite,
            retrieval_mode=request.retrieval_mode,
            embedding_model=(
                self._embedding_model
                if request.retrieval_mode is RetrievalMode.VECTOR
                else None
            ),
            active_index_version_ids=active_index_ids,
            child_hits=child_hits,
            parents=parents,
            incompatible_index_count=incompatible_count,
            discarded_child_count=discarded_child_count,
            discarded_parent_count=discarded_parent_count,
        )

    async def _bm25_index(
        self,
        targets: list[ActiveKnowledgeIndex],
    ) -> BM25Index:
        """按活动索引集合缓存不可变Child语料，避免每次请求重复计算词频。"""

        cache_key = tuple(
            sorted(target.index_version.id for target in targets)
        )
        cached = self._bm25_indexes.get(cache_key)
        if cached is not None:
            return cached
        async with self._bm25_lock:
            cached = self._bm25_indexes.get(cache_key)
            if cached is not None:
                return cached
            target_by_version = {
                target.document_version.id: target for target in targets
            }
            async with self._database.session() as session:
                chunks = await KnowledgeRepository(
                    session
                ).child_chunks_for_versions(list(target_by_version))
            documents = tuple(
                BM25Document(
                    chunk_id=chunk.id,
                    document_id=target_by_version[
                        chunk.version_id
                    ].document.id,
                    version_id=chunk.version_id,
                    index_version_id=target_by_version[
                        chunk.version_id
                    ].index_version.id,
                    content=chunk.content,
                )
                for chunk in chunks
            )
            index = BM25Index(
                documents=documents,
                tokenizer=self._bm25_tokenizer,
            )
            # 本地MVP限制缓存版本数量；正式大规模词法索引可替换为OpenSearch。
            if len(self._bm25_indexes) >= 8:
                oldest_key = next(iter(self._bm25_indexes))
                self._bm25_indexes.pop(oldest_key)
            self._bm25_indexes[cache_key] = index
            return index

    async def _active_targets(
            self,
            *,
            actor: UserContext,
            business_domain: str,
            allowed_scopes: tuple[str, ...],
    ) -> list[ActiveKnowledgeIndex]:
        """先用MySQL事实生成Milvus允许搜索的index_version_id白名单。"""

        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                actor.external_id,
                actor.display_name,
            )
            targets = await KnowledgeRepository(
                session
            ).active_indexes_for_retrieval(
                owner_user_id=owner.id,
                business_domain=business_domain,
            )
            allowed = set(allowed_scopes)
            permitted = [
                target
                for target in targets
                if allowed.intersection(target.document.access_scope)
            ]
            await session.commit()
            return permitted

    async def _validate_and_expand(
            self,
            *,
        raw_hits: tuple[ChildRetrievalCandidate, ...],
            active_index_ids: tuple[str, ...],
            owner_external_id: str,
            owner_display_name: str,
            business_domain: str,
            allowed_scopes: tuple[str, ...],
            child_top_k: int,
            parent_top_k: int,
    ) -> tuple[
        tuple[RetrievalChildHitView, ...],
        tuple[RetrievalParentView, ...],
        int,
        int,
    ]:
        """不信任Milvus冗余元数据，回MySQL复核后再读取Parent。"""

        async with self._database.session() as session:
            owner = await UserRepository(session).get_or_create(
                owner_external_id,
                owner_display_name,
            )
            repository = KnowledgeRepository(session)
            validated = await repository.validate_retrieval_children(
                chunk_ids=list(dict.fromkeys(hit.chunk_id for hit in raw_hits)),
                index_version_ids=list(active_index_ids),
            )
            rows = {
                (row.chunk.id, row.index_version.id): row for row in validated
            }
            allowed = set(allowed_scopes)
            accepted: list[
                tuple[ChildRetrievalCandidate, ValidatedKnowledgeChild]
            ] = []
            for hit in raw_hits:
                row = rows.get((hit.chunk_id, hit.index_version_id))
                if row is None or not self._is_allowed(
                        hit=hit,
                        row=row,
                        owner_user_id=owner.id,
                        business_domain=business_domain,
                        allowed_scopes=allowed,
                ):
                    continue
                accepted.append((hit, row))

            selected = accepted[:child_top_k]
            child_views = tuple(
                RetrievalChildHitView(
                    chunk_id=hit.chunk_id,
                    parent_chunk_id=str(row.chunk.parent_chunk_id),
                    document_id=row.document.id,
                    document_version_id=row.document_version.id,
                    index_version_id=row.index_version.id,
                    source=hit.source,
                    score=hit.score,
                )
                for hit, row in selected
            )
            discarded_children = len(raw_hits) - len(accepted)
            if not selected:
                await session.commit()
                return child_views, (), discarded_children, 0

            plans = self._small_to_big.plan(
                hits=[
                    ChildChunkHit(chunk_id=hit.chunk_id, score=hit.score)
                    for hit, _ in selected
                ],
                child_parent_ids={
                    hit.chunk_id: str(row.chunk.parent_chunk_id)
                    for hit, row in selected
                },
            )[:parent_top_k]
            parents = await repository.chunks_by_ids_any_version(
                [plan.parent_chunk_id for plan in plans]
            )
            parent_by_id = {parent.id: parent for parent in parents}
            row_by_child = {hit.chunk_id: row for hit, row in selected}
            parent_views: list[RetrievalParentView] = []
            for plan in plans:
                parent = parent_by_id.get(plan.parent_chunk_id)
                first_row = row_by_child[plan.matched_child_ids[0]]
                if not self._valid_parent(parent, first_row):
                    continue
                parent_views.append(
                    RetrievalParentView(
                        parent=KnowledgeChunkView.model_validate(parent),
                        document_id=first_row.document.id,
                        document_title=first_row.document.title,
                        document_version_id=first_row.document_version.id,
                        index_version_id=first_row.index_version.id,
                        matched_child_ids=plan.matched_child_ids,
                        best_child_score=plan.best_child_score,
                        first_child_rank=plan.first_child_rank,
                    )
                )
            await session.commit()
            return (
                child_views,
                tuple(parent_views),
                discarded_children,
                len(plans) - len(parent_views),
            )

    @staticmethod
    def _is_allowed(
            *,
        hit: ChildRetrievalCandidate,
            row: ValidatedKnowledgeChild,
            owner_user_id: str,
            business_domain: str,
            allowed_scopes: set[str],
    ) -> bool:
        return bool(
            row.chunk.parent_chunk_id
            and row.document.created_by_user_id == owner_user_id
            and row.document.business_domain == business_domain
            and allowed_scopes.intersection(row.document.access_scope)
            and row.document.id == hit.document_id
            and row.document_version.id == hit.version_id
            and row.index_version.id == hit.index_version_id
        )

    @staticmethod
    def _valid_parent(
            parent: KnowledgeChunk | None,
            child: ValidatedKnowledgeChild,
    ) -> bool:
        return bool(
            parent is not None
            and parent.kind == "parent"
            and parent.version_id == child.document_version.id
            and child.chunk.parent_chunk_id == parent.id
        )

    def _require_vector_store(self) -> VectorStore:
        if self._vector_store is None:
            raise ServiceNotReadyError()
        return self._vector_store

    def _empty_view(
            self,
        *,
        rewrite: QueryRewriteResult,
        retrieval_mode: RetrievalMode,
        incompatible_index_count: int,
    ) -> KnowledgeRetrievalView:
        return KnowledgeRetrievalView(
            rewrite=rewrite,
            retrieval_mode=retrieval_mode,
            embedding_model=(
                self._embedding_model
                if retrieval_mode is RetrievalMode.VECTOR
                else None
            ),
            active_index_version_ids=(),
            child_hits=(),
            parents=(),
            incompatible_index_count=incompatible_index_count,
            discarded_child_count=0,
            discarded_parent_count=0,
        )
