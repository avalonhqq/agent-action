"""检索、Small-to-Big、RRF与Parent Rerank端到端测试。"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from bili_support.core.config import Settings
from bili_support.knowledge.embedding import cosine_similarity
from bili_support.knowledge.lexical_store import (
    LexicalRebuildResult,
    LexicalRecord,
    LexicalSearchHit,
    LexicalSearchQuery,
)
from bili_support.knowledge.reranking import (
    RerankItem,
    RerankRequest,
    RerankResponse,
)
from bili_support.knowledge.vector_store import (
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.types import LLMRequest
from bili_support.main import create_app


class _InMemoryVectorStore:
    """遵守VectorStore协议的内存检索Fake，模拟Milvus过滤和COSINE排序。"""

    def __init__(self) -> None:
        self.records: dict[str, VectorRecord] = {}
        self.search_count = 0
        self.add_forged_hit = False

    async def ensure_collection(self) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        for record in records:
            self.records[record.chunk_id] = record
        return len(records)

    async def search(
        self,
        query: VectorSearchQuery,
    ) -> tuple[VectorSearchHit, ...]:
        self.search_count += 1
        allowed = set(query.allowed_scopes)
        active_indexes = set(query.index_version_ids)
        matches = [
            record
            for record in self.records.values()
            if (
                record.index_version_id in active_indexes
                and (
                    query.business_domain is None
                    or record.business_domain == query.business_domain
                )
                and allowed.intersection(record.access_scope)
            )
        ]
        hits = [
            VectorSearchHit(
                chunk_id=record.chunk_id,
                document_id=record.document_id,
                version_id=record.version_id,
                index_version_id=record.index_version_id,
                score=cosine_similarity(query.vector, record.vector),
            )
            for record in matches
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        if self.add_forged_hit and hits:
            valid = hits[0]
            hits.insert(
                0,
                valid.model_copy(update={"index_version_id": "forged-index"}),
            )
        return tuple(hits[: query.top_k])

    async def delete_version(self, version_id: str) -> None:
        self.records = {
            key: value
            for key, value in self.records.items()
            if value.version_id != version_id
        }

    async def delete_index_version(self, index_version_id: str) -> None:
        self.records = {
            key: value
            for key, value in self.records.items()
            if value.index_version_id != index_version_id
        }

    async def aclose(self) -> None:
        return None


class _InMemoryLexicalStore:
    """模拟ES版本索引，用来验证自动同步与BM25读取边界。"""

    def __init__(self) -> None:
        self.records: tuple[LexicalRecord, ...] = ()
        self.rebuild_count = 0
        self.search_queries: list[LexicalSearchQuery] = []

    async def ping(self) -> None:
        return None

    async def rebuild(
        self,
        *,
        generation: str,
        records: Sequence[LexicalRecord],
    ) -> LexicalRebuildResult:
        self.rebuild_count += 1
        self.records = tuple(records)
        return LexicalRebuildResult(
            physical_index=f"test-{generation[:8]}",
            generation=generation,
            document_count=len(records),
        )

    async def search(
        self,
        query: LexicalSearchQuery,
    ) -> tuple[LexicalSearchHit, ...]:
        self.search_queries.append(query)
        terms = {item for item in query.text.casefold() if not item.isspace()}
        matches = [
            record
            for record in self.records
            if record.document_active
            and record.version_current
            and record.index_active
            and record.owner_user_id == query.owner_user_id
            and record.business_domain == query.business_domain
            and set(record.access_scope).intersection(query.allowed_scopes)
            and terms.intersection(record.content.casefold())
        ]
        return tuple(
            LexicalSearchHit(
                chunk_id=record.chunk_id,
                document_id=record.document_id,
                version_id=record.version_id,
                index_version_id=record.index_version_id,
                score=float(len(matches) - rank),
            )
            for rank, record in enumerate(matches)
        )

    async def aclose(self) -> None:
        return None


class _FailingRebuildLexicalStore(_InMemoryLexicalStore):
    """ES节点可连接但索引同步失败，readiness不能把它误报为可用。"""

    async def rebuild(
        self,
        *,
        generation: str,
        records: Sequence[LexicalRecord],
    ) -> LexicalRebuildResult:
        raise RuntimeError("simulated lexical rebuild failure")


class _RecordingProvider(MockLLMProvider):
    """保留最终回答请求，用于验证Chat真正收到检索证据。"""

    def __init__(self) -> None:
        super().__init__(response_text="根据客服知识，支付成功后通常立即生效[E1]。")
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest):
        self.requests.append(request)
        return await super().complete(request)

    async def stream(self, request: LLMRequest):
        self.requests.append(request)
        async for chunk in super().stream(request):
            yield chunk


class _FailingSearchVectorStore(_InMemoryVectorStore):
    """索引写入仍成功，但查询故障，用于验证Hybrid单路降级。"""

    async def search(
        self,
        query: VectorSearchQuery,
    ) -> tuple[VectorSearchHit, ...]:
        self.search_count += 1
        raise RuntimeError("simulated vector search failure")


class _ReverseRerankProvider:
    """把候选倒序，证明最终Parent顺序确实来自批量Reranker。"""

    name = "test-reverse"

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        reversed_documents = tuple(reversed(request.documents))
        return RerankResponse(
            items=tuple(
                RerankItem(
                    parent_chunk_id=document.parent_chunk_id,
                    relevance_score=1.0 - (rank - 1) / len(reversed_documents),
                    rank=rank,
                )
                for rank, document in enumerate(reversed_documents, start=1)
            ),
            provider=self.name,
            model=request.model,
            latency_ms=2,
        )


class _InvalidRerankProvider:
    """返回未知ID，验证结构成功但业务身份无效时回退RRF。"""

    name = "test-invalid"

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        return RerankResponse(
            items=(
                RerankItem(
                    parent_chunk_id="unknown-parent",
                    relevance_score=1.0,
                    rank=1,
                ),
            ),
            provider=self.name,
            model=request.model,
            latency_ms=1,
        )


class _SlowRerankProvider:
    """超过服务超时预算，用于验证RRF回退。"""

    name = "test-slow"

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        await asyncio.sleep(0.05)
        raise AssertionError("service timeout should cancel this provider call")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=(
            f"sqlite+aiosqlite:///{(tmp_path / 'retrieval.db').as_posix()}"
        ),
        database_auto_create=True,
        knowledge_storage_dir=str(tmp_path / "files"),
        milvus_enabled=False,
        milvus_required=False,
        api_token="retrieval-test-token",
        ui_enabled=False,
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer retrieval-test-token",
        "X-User-ID": "knowledge-admin",
        "X-User-Name": "Knowledge Admin",
    }


def _upload_and_index(
    client: TestClient,
    *,
    title: str,
    content: str,
    access_scope: str,
    business_domain: str = "membership",
) -> tuple[str, str]:
    uploaded = client.post(
        "/api/v1/knowledge/documents",
        headers=_headers(),
        data={
            "title": title,
            "business_domain": business_domain,
            "knowledge_type": "faq",
            "access_scope": access_scope,
        },
        files={"file": (f"{title}.md", content.encode(), "text/markdown")},
    )
    assert uploaded.status_code == 201
    version_id = uploaded.json()["data"]["version"]["id"]
    indexed = client.post(
        f"/api/v1/knowledge/versions/{version_id}/indexes",
        headers=_headers(),
    )
    assert indexed.json()["data"]["job_status"] == "succeeded"
    return version_id, indexed.json()["data"]["index"]["id"]


def test_retrieve_filters_scope_and_expands_child_to_parent(tmp_path: Path) -> None:
    store = _InMemoryVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        _, public_index_id = _upload_and_index(
            client,
            title="大会员到账FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员支付成功后多久生效？\n\n"
                "A：正常情况下立即生效，超过30分钟请提交订单人工核查。\n\n"
                "关键词：支付成功、未到账、生效时间"
            ),
        )
        _upload_and_index(
            client,
            title="内部会员处置手册",
            access_scope="staff",
            content=(
                "# 客服FAQ\n\n"
                "Q：内部人员如何修改会员数据？\n\n"
                "A：只能通过受控后台处理。"
            ),
        )
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "大会员支付成功后多久生效？",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "child_top_k": 5,
                "parent_top_k": 3,
            },
        )

    assert retrieved.status_code == 200
    result = retrieved.json()["data"]
    assert result["active_index_version_ids"] == [public_index_id]
    assert len(result["child_hits"]) == 1
    assert len(result["parents"]) == 1
    assert result["parents"][0]["document_title"] == "大会员到账FAQ"
    assert "超过30分钟" in result["parents"][0]["parent"]["content"]
    assert result["parents"][0]["matched_child_ids"] == [
        result["child_hits"][0]["chunk_id"]
    ]


def test_mysql_post_filter_discards_forged_or_stale_milvus_hit(
    tmp_path: Path,
) -> None:
    store = _InMemoryVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        _upload_and_index(
            client,
            title="会员退款FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员可以退款吗？\n\n"
                "A：重复扣费或系统错误可以提交人工核查。"
            ),
        )
        store.add_forged_hit = True
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "大会员可以退款吗？",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
            },
        )

    result = retrieved.json()["data"]
    assert result["discarded_child_count"] == 1
    assert len(result["child_hits"]) == 1
    assert result["child_hits"][0]["index_version_id"] != "forged-index"


def test_rewrite_is_visible_even_when_domain_has_no_active_index(
    tmp_path: Path,
) -> None:
    store = _InMemoryVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "那联通呢",
                "business_domain": "technical",
                "allowed_scopes": ["public"],
                "history": [
                    {
                        "role": "user",
                        "content": "移动大王卡支持免流吗？",
                    }
                ],
            },
        )

    result = retrieved.json()["data"]
    assert result["rewrite"]["rewritten"] is True
    assert result["rewrite"]["standalone_query"] == "联通大王卡支持免流吗？"
    assert result["active_index_version_ids"] == []
    assert result["parents"] == []
    assert store.search_count == 0


def test_bm25_mode_reuses_mysql_validation_and_small_to_big(
    tmp_path: Path,
) -> None:
    """BM25不调用Milvus搜索，但仍只使用active索引并恢复可信Parent。"""

    store = _InMemoryVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        _upload_and_index(
            client,
            title="会员扣费FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：卸载客户端后还会扣费吗？\n\n"
                "A：卸载客户端不等于取消自动续费，必须在订阅管理确认取消。"
            ),
        )
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "卸载客户端还会自动续费扣钱吗？",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "retrieval_mode": "bm25",
                "child_top_k": 5,
                "parent_top_k": 3,
            },
        )

    assert retrieved.status_code == 200
    result = retrieved.json()["data"]
    assert result["retrieval_mode"] == "bm25"
    assert result["embedding_model"] is None
    assert result["child_hits"][0]["source"] == "bm25"
    assert "卸载客户端不等于取消自动续费" in (
        result["parents"][0]["parent"]["content"]
    )
    assert store.search_count == 0


def test_elasticsearch_bm25_auto_syncs_after_index_activation(
    tmp_path: Path,
) -> None:
    """知识索引激活后自动刷新ES快照，BM25查询不再构建进程内索引。"""

    vector_store = _InMemoryVectorStore()
    lexical_store = _InMemoryLexicalStore()
    with TestClient(
        create_app(
            _settings(tmp_path),
            vector_store=vector_store,
            lexical_store=lexical_store,
        )
    ) as client:
        _upload_and_index(
            client,
            title="大会员到账FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：支付成功但会员没有到账怎么办？\n\n"
                "A：超过30分钟请提供订单号并提交人工核查。"
            ),
        )
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "大会员支付成功未到账",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "retrieval_mode": "bm25",
            },
        )
        records_after_index = lexical_store.records
        deleted = client.delete(
            f"/api/v1/knowledge/documents/{records_after_index[0].document_id}",
            headers=_headers(),
        )

    assert retrieved.status_code == 200
    assert deleted.status_code == 204
    result = retrieved.json()["data"]
    # 启动空快照、索引激活快照、文档删除快照。
    assert lexical_store.rebuild_count >= 3
    assert records_after_index
    assert lexical_store.records == ()
    assert lexical_store.search_queries[0].business_domain == "membership"
    assert result["child_hits"][0]["source"] == "bm25"
    assert "超过30分钟" in result["parents"][0]["parent"]["content"]
    assert vector_store.search_count == 0


def test_required_elasticsearch_is_not_ready_after_sync_failure(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path).model_copy(
        update={
            "elasticsearch_enabled": True,
            "elasticsearch_required": True,
        }
    )
    with TestClient(
        create_app(
            settings,
            vector_store=_InMemoryVectorStore(),
            lexical_store=_FailingRebuildLexicalStore(),
        )
    ) as client:
        response = client.get("/ready")

    assert response.status_code == 503


def test_hybrid_mode_rrf_merges_sources_before_small_to_big(
    tmp_path: Path,
) -> None:
    """两路同时命中的Child只返回一次，并保留原始排名与分数。"""

    store = _InMemoryVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        _upload_and_index(
            client,
            title="会员续费FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：卸载客户端后还会扣费吗？\n\n"
                "A：卸载客户端不等于取消自动续费，必须在订阅管理确认取消。"
            ),
        )
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "卸载客户端还会自动续费扣钱吗？",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "retrieval_mode": "hybrid",
                "child_top_k": 5,
                "parent_top_k": 3,
            },
        )

    assert retrieved.status_code == 200
    result = retrieved.json()["data"]
    assert result["retrieval_mode"] == "hybrid"
    assert result["degraded"] is False
    assert result["failed_sources"] == []
    assert result["child_hits"][0]["source"] == "hybrid"
    assert {item["source"] for item in result["child_hits"][0]["channel_evidence"]} == {
        "vector",
        "bm25",
    }
    assert "取消自动续费" in result["parents"][0]["parent"]["content"]
    assert store.search_count == 1


def test_hybrid_mode_degrades_to_bm25_when_vector_search_fails(
    tmp_path: Path,
) -> None:
    """单路故障不会伪装成完整融合，响应明确记录失败来源。"""

    store = _FailingSearchVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        _upload_and_index(
            client,
            title="会员退款FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员重复扣费怎么办？\n\n"
                "A：重复扣费可以提交订单号和支付流水进行人工核查。"
            ),
        )
        retrieved = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "大会员重复扣费怎么办？",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "retrieval_mode": "hybrid",
            },
        )

    assert retrieved.status_code == 200
    result = retrieved.json()["data"]
    assert result["degraded"] is True
    assert result["failed_sources"] == ["vector"]
    assert result["child_hits"][0]["source"] == "bm25"
    assert result["child_hits"][0]["channel_evidence"] == []
    assert store.search_count == 1


def test_parent_rerank_changes_order_and_preserves_pre_rerank_rank(
    tmp_path: Path,
) -> None:
    store = _InMemoryVectorStore()
    with TestClient(
        create_app(
            _settings(tmp_path),
            vector_store=store,
            rerank_provider=_ReverseRerankProvider(),
        )
    ) as client:
        _upload_and_index(
            client,
            title="会员综合FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员价格是多少？\n"
                "A：套餐价格以结算页面为准。\n\n"
                "Q：大会员重复扣费怎么办？\n"
                "A：请提交订单号和支付流水人工核查。"
            ),
        )
        payload = {
            "query": "大会员重复扣费和价格问题",
            "business_domain": "membership",
            "allowed_scopes": ["public"],
            "retrieval_mode": "hybrid",
            "parent_top_k": 2,
            "rerank_candidate_k": 2,
        }
        baseline = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json=payload,
        ).json()["data"]
        reranked = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={**payload, "rerank_enabled": True},
        ).json()["data"]

    baseline_ids = [item["parent"]["id"] for item in baseline["parents"]]
    reranked_ids = [item["parent"]["id"] for item in reranked["parents"]]
    assert len(baseline_ids) == 2
    assert reranked_ids == list(reversed(baseline_ids))
    assert reranked["reranking"]["applied"] is True
    assert reranked["reranking"]["degraded"] is False
    assert [item["rerank_rank"] for item in reranked["parents"]] == [1, 2]
    assert [item["pre_rerank_rank"] for item in reranked["parents"]] == [2, 1]


def test_invalid_rerank_response_falls_back_without_fake_scores(
    tmp_path: Path,
) -> None:
    store = _InMemoryVectorStore()
    with TestClient(
        create_app(
            _settings(tmp_path),
            vector_store=store,
            rerank_provider=_InvalidRerankProvider(),
        )
    ) as client:
        _upload_and_index(
            client,
            title="会员综合FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员价格是多少？\n"
                "A：套餐价格以结算页面为准。\n\n"
                "Q：大会员退款怎么办？\n"
                "A：重复扣费可以提交订单人工核查。"
            ),
        )
        result = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "大会员价格和退款",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "retrieval_mode": "hybrid",
                "parent_top_k": 2,
                "rerank_enabled": True,
                "rerank_candidate_k": 2,
            },
        ).json()["data"]

    assert result["reranking"]["applied"] is False
    assert result["reranking"]["degraded"] is True
    assert result["reranking"]["error_code"] == "rerank_invalid_response"
    assert all(item["rerank_score"] is None for item in result["parents"])
    assert [item["pre_rerank_rank"] for item in result["parents"]] == [1, 2]


def test_rerank_timeout_falls_back_to_rrf_order(tmp_path: Path) -> None:
    store = _InMemoryVectorStore()
    settings = _settings(tmp_path).model_copy(
        update={"rerank_timeout_seconds": 0.001}
    )
    with TestClient(
        create_app(
            settings,
            vector_store=store,
            rerank_provider=_SlowRerankProvider(),
        )
    ) as client:
        _upload_and_index(
            client,
            title="会员到账FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：会员支付成功后多久生效？\n"
                "A：通常立即生效，超过30分钟请人工核查。"
            ),
        )
        result = client.post(
            "/api/v1/knowledge/retrieve",
            headers=_headers(),
            json={
                "query": "会员支付成功后多久生效？",
                "business_domain": "membership",
                "allowed_scopes": ["public"],
                "retrieval_mode": "hybrid",
                "rerank_enabled": True,
                "parent_top_k": 1,
                "rerank_candidate_k": 1,
            },
        ).json()["data"]

    assert result["reranking"]["degraded"] is True
    assert result["reranking"]["error_code"] == "rerank_timeout"
    assert result["parents"][0]["rerank_score"] is None


def test_chat_routes_to_real_rag_and_streams_grounded_evidence(
    tmp_path: Path,
) -> None:
    store = _InMemoryVectorStore()
    provider = _RecordingProvider()
    with TestClient(
        create_app(
            _settings(tmp_path),
            llm_provider=provider,
            vector_store=store,
        )
    ) as client:
        _upload_and_index(
            client,
            title="大会员到账FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员支付成功后多久生效？\n\n"
                "A：正常情况下立即生效，超过30分钟请提交订单人工核查。"
            ),
        )
        created = client.post(
            "/api/v1/conversations",
            headers=_headers(),
            json={"title": "真实RAG会话"},
        )
        thread_id = created.json()["data"]["thread_id"]
        streamed = client.post(
            f"/api/v1/conversations/{thread_id}/messages/stream",
            headers=_headers(),
            json={"content": "大会员支付成功后多久生效？"},
        )

    assert streamed.status_code == 200
    assert '"target": "knowledge_rag"' in streamed.text
    assert '"mocked_downstream": false' in streamed.text
    assert '"mode": "hybrid"' in streamed.text
    assert '"degraded": false' in streamed.text
    assert '"evidence_count": 1' in streamed.text
    assert '"document_title": "大会员到账FAQ"' in streamed.text
    assert '"used_evidence_ids": ["E1"]' in streamed.text
    assert '"decision": "pass"' in streamed.text
    assert '"excerpt":' in streamed.text
    assert "event: delta" in streamed.text
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert "只能使用knowledge_evidence_json中的事实" in request.messages[0].content
    assert request.structured_output is not None
    assert request.structured_output.name == "grounded_answer"
    assert "超过30分钟" in request.messages[-1].content


def test_policy_refuses_low_quality_evidence_without_calling_answer_model(
    tmp_path: Path,
) -> None:
    """域内但语义无关的问题即使召回候选，也不能让回答模型自由发挥。"""

    store = _InMemoryVectorStore()
    provider = _RecordingProvider()
    with TestClient(
        create_app(_settings(tmp_path), llm_provider=provider, vector_store=store)
    ) as client:
        _upload_and_index(
            client,
            title="大会员到账FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：大会员支付成功后多久生效？\n\n"
                "A：正常情况下立即生效，超过30分钟请提交订单人工核查。"
            ),
        )
        thread_id = client.post(
            "/api/v1/conversations",
            headers=_headers(),
            json={"title": "低质量拒答"},
        ).json()["data"]["thread_id"]
        response = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=_headers(),
            json={"content": "明天上海演唱会的门票在哪里购买？"},
        )

    data = response.json()["data"]
    policy = data["routing"]["retrieval"]["policy"]
    assert response.status_code == 200
    assert policy["decision"] == "refuse"
    assert policy["reason_code"] == "low_quality"
    assert "相关性不足" in data["answer"]
    assert provider.requests == []


def test_policy_clarifies_when_multi_entity_evidence_is_incomplete(
    tmp_path: Path,
) -> None:
    """复合问题缺少其中一个产品证据时，只补检索一次并确定性追问。"""

    store = _InMemoryVectorStore()
    provider = _RecordingProvider()
    with TestClient(
        create_app(_settings(tmp_path), llm_provider=provider, vector_store=store)
    ) as client:
        _upload_and_index(
            client,
            title="连续包月FAQ",
            access_scope="public",
            content=(
                "# 客服FAQ\n\n"
                "Q：连续包月价格是多少？\n\n"
                "A：连续包月价格以购买结算页面显示为准。"
            ),
        )
        thread_id = client.post(
            "/api/v1/conversations",
            headers=_headers(),
            json={"title": "多实体覆盖"},
        ).json()["data"]["thread_id"]
        response = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=_headers(),
            json={"content": "比较连续包月和年度套餐的价格"},
        )

    data = response.json()["data"]
    retrieval = data["routing"]["retrieval"]
    assert response.status_code == 200
    assert retrieval["policy"]["decision"] == "clarify"
    assert retrieval["policy"]["reason_code"] == "missing_entity_coverage"
    assert retrieval["coverage"]["missing"] == ["年度套餐"]
    assert retrieval["coverage"]["supplemental_query_used"] is True
    assert "年度套餐" in data["answer"]
    assert provider.requests == []
