"""第六周6C：活动索引解析、向量召回、MySQL复核和Small-to-Big还原。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from bili_support.core.database import Database
from bili_support.core.exceptions import ServiceNotReadyError
from bili_support.core.security import UserContext
from bili_support.knowledge.bm25 import (
    BM25Document,
    BM25Index,
)
from bili_support.knowledge.dictionary import match_published_terms
from bili_support.knowledge.embedding import EmbeddingProvider, EmbeddingRequest
from bili_support.knowledge.fusion import ReciprocalRankFusion
from bili_support.knowledge.lexical_store import LexicalSearchQuery, LexicalStore
from bili_support.knowledge.reranking import (
    RerankDocument,
    RerankErrorCode,
    RerankProvider,
    RerankProviderError,
    RerankRequest,
    RerankTrace,
    validate_rerank_response,
)
from bili_support.knowledge.retrieval import (
    ChildRetrievalCandidate,
    FusedChildRetrievalCandidate,
    RankedChildRetrievalCandidate,
    RetrievalMode,
    RetrievalSource,
)
from bili_support.knowledge.small_to_big import ChildChunkHit, SmallToBigExpander
from bili_support.knowledge.tokenizers import BigramSearchTokenizer, SearchTokenizer
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
from bili_support.services.dictionary import KnowledgeDictionaryService


@dataclass(frozen=True, slots=True)
class _RecallOutcome:
    """单条召回通道的内部结果；异常只转成稳定的来源降级信息。"""

    source: RetrievalSource
    hits: tuple[ChildRetrievalCandidate, ...] = ()
    failed: bool = False


class KnowledgeRetrievalService:
    """执行Vector、BM25或RRF Hybrid召回，并统一复核和恢复Parent。"""

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
        bm25_tokenizer: SearchTokenizer | None = None,
        lexical_store: LexicalStore | None = None,
        dictionary_service: KnowledgeDictionaryService | None = None,
        fusion: ReciprocalRankFusion | None = None,
        rerank_provider: RerankProvider | None = None,
        rerank_model: str = "mock-reranker-v1",
        rerank_timeout_seconds: float = 10.0,
        rerank_max_concurrency: int = 4,
    ) -> None:
        if not rerank_model.strip():
            raise ValueError("rerank model must not be blank")
        if rerank_timeout_seconds <= 0:
            raise ValueError("rerank timeout must be positive")
        if rerank_max_concurrency < 1:
            raise ValueError("rerank max concurrency must be positive")
        self._database = database
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store
        self._embedding_model = embedding_model
        self._embedding_dimension = embedding_dimension
        self._embedding_timeout_seconds = embedding_timeout_seconds
        self._collection_name = collection_name
        self._rewriter = rewriter or StandaloneQueryRewriter()
        self._small_to_big = small_to_big or SmallToBigExpander()
        self._bm25_tokenizer = bm25_tokenizer or BigramSearchTokenizer()
        self._lexical_store = lexical_store
        self._dictionary_service = dictionary_service
        self._fusion = fusion or ReciprocalRankFusion()
        self._rerank_provider = rerank_provider
        self._rerank_model = rerank_model
        self._rerank_timeout_seconds = rerank_timeout_seconds
        self._rerank_semaphore = asyncio.Semaphore(rerank_max_concurrency)
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
        vector_targets = [
            target
            for target in targets
            if (
                target.index_version.collection_name == self._collection_name
                and target.index_version.embedding_model == self._embedding_model
                and target.index_version.embedding_dimension
                == self._embedding_dimension
            )
        ]
        compatible_targets = (
            vector_targets
            if request.retrieval_mode is RetrievalMode.VECTOR
            else targets
        )
        incompatible_count = (
            0
            if request.retrieval_mode is RetrievalMode.BM25
            else len(targets) - len(vector_targets)
        )
        active_index_ids = tuple(
            target.index_version.id for target in compatible_targets
        )
        if not active_index_ids:
            return self._empty_view(
                rewrite=rewrite,
                retrieval_mode=request.retrieval_mode,
                incompatible_index_count=incompatible_count,
                rerank_enabled=request.rerank_enabled,
            )

        # 适度过取候选，为活动状态刚切换或权限副本延迟导致的二次过滤留余量。
        recall_top_k = min(request.child_top_k * 2, 100)
        failed_sources: tuple[RetrievalSource, ...] = ()
        if request.retrieval_mode is RetrievalMode.VECTOR:
            raw_hits: tuple[RankedChildRetrievalCandidate, ...] = (
                await self._vector_recall(
                    query=rewrite.standalone_query,
                    targets=vector_targets,
                    business_domain=request.business_domain.value,
                    allowed_scopes=request.allowed_scopes,
                    top_k=recall_top_k,
                )
            )
        elif request.retrieval_mode is RetrievalMode.BM25:
            raw_hits = await self._bm25_recall(
                query=rewrite.standalone_query,
                targets=targets,
                business_domain=request.business_domain.value,
                allowed_scopes=request.allowed_scopes,
                top_k=recall_top_k,
            )
        else:
            vector_outcome, bm25_outcome = await asyncio.gather(
                self._safe_vector_recall(
                    query=rewrite.standalone_query,
                    targets=vector_targets,
                    business_domain=request.business_domain.value,
                    allowed_scopes=request.allowed_scopes,
                    top_k=recall_top_k,
                ),
                self._safe_bm25_recall(
                    query=rewrite.standalone_query,
                    targets=targets,
                    business_domain=request.business_domain.value,
                    allowed_scopes=request.allowed_scopes,
                    top_k=recall_top_k,
                ),
            )
            failed_sources = tuple(
                outcome.source
                for outcome in (vector_outcome, bm25_outcome)
                if outcome.failed
            )
            if len(failed_sources) == 2:
                raise ServiceNotReadyError()
            if failed_sources:
                successful = (
                    bm25_outcome
                    if vector_outcome.failed
                    else vector_outcome
                )
                raw_hits = successful.hits
            else:
                raw_hits = self._fusion.fuse(
                    (vector_outcome.hits, bm25_outcome.hits)
                )
        (
            child_hits,
            parent_candidates,
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
            parent_top_k=(
                request.rerank_candidate_k
                if request.rerank_enabled
                else request.parent_top_k
            ),
        )
        parents, reranking = await self._rerank_parents(
            query=rewrite.standalone_query,
            parents=parent_candidates,
            enabled=request.rerank_enabled,
            top_n=request.parent_top_k,
        )
        return KnowledgeRetrievalView(
            rewrite=rewrite,
            retrieval_mode=request.retrieval_mode,
            embedding_model=(
                self._embedding_model
                if request.retrieval_mode is not RetrievalMode.BM25
                else None
            ),
            active_index_version_ids=active_index_ids,
            child_hits=child_hits,
            parents=parents,
            incompatible_index_count=incompatible_count,
            discarded_child_count=discarded_child_count,
            discarded_parent_count=discarded_parent_count,
            degraded=bool(failed_sources),
            failed_sources=failed_sources,
            reranking=reranking,
        )

    async def _vector_recall(
        self,
        *,
        query: str,
        targets: list[ActiveKnowledgeIndex],
        business_domain: str,
        allowed_scopes: tuple[str, ...],
        top_k: int,
    ) -> tuple[ChildRetrievalCandidate, ...]:
        """执行单次向量召回，并转换为与BM25共享的候选契约。"""

        if not targets:
            return ()
        vector_store = self._require_vector_store()
        embedded = await self._embedding_provider.embed(
            EmbeddingRequest(
                texts=(query,),
                model=self._embedding_model,
                timeout_seconds=self._embedding_timeout_seconds,
            )
        )
        if (
            embedded.dimension != self._embedding_dimension
            or len(embedded.vectors) != 1
        ):
            raise ServiceNotReadyError()
        active_index_ids = tuple(target.index_version.id for target in targets)
        vector_hits = await vector_store.search(
            VectorSearchQuery(
                vector=embedded.vectors[0].values,
                top_k=top_k,
                business_domain=business_domain,
                allowed_scopes=allowed_scopes,
                index_version_ids=active_index_ids,
            )
        )
        return tuple(
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

    async def _bm25_recall(
        self,
        *,
        query: str,
        targets: list[ActiveKnowledgeIndex],
        business_domain: str,
        allowed_scopes: tuple[str, ...],
        top_k: int,
    ) -> tuple[ChildRetrievalCandidate, ...]:
        """执行单次中文BM25召回；不需要Embedding或Milvus。"""

        if not targets:
            return ()
        if self._lexical_store is None:
            bm25_index = await self._bm25_index(targets)
            return bm25_index.search(query=query, top_k=top_k)
        entries = (
            await self._dictionary_service.active_entries(
                business_domain=business_domain,
            )
            if self._dictionary_service is not None
            else ()
        )
        hits = await self._lexical_store.search(
            LexicalSearchQuery(
                text=query,
                top_k=top_k,
                # targets由MySQL按当前actor过滤，ES用owner继续隔离租户但不按版本号查询。
                owner_user_id=targets[0].document.created_by_user_id,
                business_domain=business_domain,
                allowed_scopes=allowed_scopes,
                domain_terms=match_published_terms(query, entries),
            )
        )
        return tuple(
            ChildRetrievalCandidate(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                version_id=item.version_id,
                index_version_id=item.index_version_id,
                source=RetrievalSource.BM25,
                score=item.score,
            )
            for item in hits
        )

    async def _safe_vector_recall(
        self,
        *,
        query: str,
        targets: list[ActiveKnowledgeIndex],
        business_domain: str,
        allowed_scopes: tuple[str, ...],
        top_k: int,
    ) -> _RecallOutcome:
        """Hybrid边界：Vector故障转成可审计降级，不泄露内部异常。"""

        try:
            hits = await self._vector_recall(
                query=query,
                targets=targets,
                business_domain=business_domain,
                allowed_scopes=allowed_scopes,
                top_k=top_k,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return _RecallOutcome(source=RetrievalSource.VECTOR, failed=True)
        return _RecallOutcome(source=RetrievalSource.VECTOR, hits=hits)

    async def _safe_bm25_recall(
        self,
        *,
        query: str,
        targets: list[ActiveKnowledgeIndex],
        business_domain: str,
        allowed_scopes: tuple[str, ...],
        top_k: int,
    ) -> _RecallOutcome:
        """Hybrid边界：BM25故障转成可审计降级，不泄露内部异常。"""

        try:
            hits = await self._bm25_recall(
                query=query,
                targets=targets,
                business_domain=business_domain,
                allowed_scopes=allowed_scopes,
                top_k=top_k,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return _RecallOutcome(source=RetrievalSource.BM25, failed=True)
        return _RecallOutcome(source=RetrievalSource.BM25, hits=hits)

    async def _rerank_parents(
        self,
        *,
        query: str,
        parents: tuple[RetrievalParentView, ...],
        enabled: bool,
        top_n: int,
    ) -> tuple[tuple[RetrievalParentView, ...], RerankTrace]:
        """在数据库事务外批量重排Parent；任何增强故障都回退RRF顺序。"""

        fallback = parents[:top_n]
        provider_name = (
            self._rerank_provider.name
            if self._rerank_provider is not None
            else None
        )
        if not enabled:
            return fallback, RerankTrace(
                enabled=False,
                attempted=False,
                applied=False,
                degraded=False,
                provider=provider_name,
                model=self._rerank_model,
                candidate_count=len(parents),
                returned_count=len(fallback),
            )
        if not parents:
            return (), RerankTrace(
                enabled=True,
                attempted=False,
                applied=False,
                degraded=False,
                provider=provider_name,
                model=self._rerank_model,
            )
        if self._rerank_provider is None:
            return fallback, self._rerank_failure_trace(
                attempted=False,
                candidate_count=len(parents),
                returned_count=len(fallback),
                error_code=RerankErrorCode.PROVIDER_UNAVAILABLE,
            )

        # 将总字符预算平均分配给候选，避免后排Parent因预算耗尽而被静默遗漏。
        per_document_chars = min(1000, max(1, 8000 // len(parents)))
        request = RerankRequest(
            query=query,
            documents=tuple(
                RerankDocument(
                    parent_chunk_id=item.parent.id,
                    title=item.document_title,
                    content=item.parent.content[:per_document_chars],
                    original_rank=rank,
                )
                for rank, item in enumerate(parents, start=1)
            ),
            top_n=min(top_n, len(parents)),
            model=self._rerank_model,
            timeout_seconds=self._rerank_timeout_seconds,
        )
        try:
            # 总超时覆盖等待并发槽位和Provider调用，避免高流量排队无限等待。
            async with asyncio.timeout(self._rerank_timeout_seconds):
                async with self._rerank_semaphore:
                    response = await self._rerank_provider.rerank(request)
            validate_rerank_response(request=request, response=response)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            return fallback, self._rerank_failure_trace(
                attempted=True,
                candidate_count=len(parents),
                returned_count=len(fallback),
                error_code=RerankErrorCode.TIMEOUT,
            )
        except RerankProviderError as exc:
            return fallback, self._rerank_failure_trace(
                attempted=True,
                candidate_count=len(parents),
                returned_count=len(fallback),
                error_code=exc.code,
            )
        except Exception:
            return fallback, self._rerank_failure_trace(
                attempted=True,
                candidate_count=len(parents),
                returned_count=len(fallback),
                error_code=RerankErrorCode.INTERNAL_ERROR,
            )

        parent_by_id = {item.parent.id: item for item in parents}
        ranked = sorted(response.items, key=lambda item: item.rank)
        applied = tuple(
            parent_by_id[item.parent_chunk_id].model_copy(
                update={
                    "rerank_rank": item.rank,
                    "rerank_score": item.relevance_score,
                }
            )
            for item in ranked[:top_n]
        )
        return applied, RerankTrace(
            enabled=True,
            attempted=True,
            applied=True,
            degraded=False,
            provider=response.provider,
            model=response.model,
            candidate_count=len(parents),
            returned_count=len(applied),
            latency_ms=response.latency_ms,
        )

    def _rerank_failure_trace(
        self,
        *,
        attempted: bool,
        candidate_count: int,
        returned_count: int,
        error_code: RerankErrorCode,
    ) -> RerankTrace:
        """构造不包含异常文本的稳定降级Trace。"""

        return RerankTrace(
            enabled=True,
            attempted=attempted,
            applied=False,
            degraded=True,
            provider=(
                self._rerank_provider.name
                if self._rerank_provider is not None
                else None
            ),
            model=self._rerank_model,
            candidate_count=candidate_count,
            returned_count=returned_count,
            error_code=error_code,
        )

    async def _bm25_index(
        self,
        targets: list[ActiveKnowledgeIndex],
    ) -> BM25Index:
        """按活动索引集合缓存不可变Child语料，避免每次请求重复计算词频。"""

        # 词典版本进入缓存key；发布后Jieba热加载会触发Child文档词频整体重建。
        tokenizer_version = getattr(
            self._bm25_tokenizer,
            "cache_version",
            "external-static-v1",
        )
        cache_key = (
            *sorted(target.index_version.id for target in targets),
            f"tokenizer:{tokenizer_version}",
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
        raw_hits: tuple[RankedChildRetrievalCandidate, ...],
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
                tuple[RankedChildRetrievalCandidate, ValidatedKnowledgeChild]
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
                    channel_evidence=(
                        hit.channel_evidence
                        if isinstance(hit, FusedChildRetrievalCandidate)
                        else ()
                    ),
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
                        pre_rerank_rank=len(parent_views) + 1,
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
        hit: RankedChildRetrievalCandidate,
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
        rerank_enabled: bool,
    ) -> KnowledgeRetrievalView:
        return KnowledgeRetrievalView(
            rewrite=rewrite,
            retrieval_mode=retrieval_mode,
            embedding_model=(
                self._embedding_model
                if retrieval_mode is not RetrievalMode.BM25
                else None
            ),
            active_index_version_ids=(),
            child_hits=(),
            parents=(),
            incompatible_index_count=incompatible_index_count,
            discarded_child_count=0,
            discarded_parent_count=0,
            reranking=RerankTrace(
                enabled=rerank_enabled,
                attempted=False,
                applied=False,
                degraded=False,
            ),
        )
