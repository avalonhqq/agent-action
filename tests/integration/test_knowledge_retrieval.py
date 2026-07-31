"""6C活动索引过滤、MySQL二次复核和Small-to-Big端到端测试。"""

from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from bili_support.core.config import Settings
from bili_support.knowledge.embedding import cosine_similarity
from bili_support.knowledge.vector_store import (
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
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
