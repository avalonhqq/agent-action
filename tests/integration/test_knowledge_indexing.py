"""第六周索引版本、批量写入、失败重试和安全切换集成测试。"""

from collections.abc import Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from bili_support.core.config import Settings
from bili_support.knowledge.vector_store import (
    VectorRecord,
    VectorSearchHit,
    VectorSearchQuery,
)
from bili_support.main import create_app


class _FakeVectorStore:
    """不依赖Milvus进程的协议Fake，保留每次写入供业务断言。"""

    def __init__(self) -> None:
        self.ensure_count = 0
        self.batches: list[tuple[VectorRecord, ...]] = []
        self.deleted_index_versions: list[str] = []
        self.fail_next_upsert = False
        self.closed = False

    async def ensure_collection(self) -> None:
        self.ensure_count += 1

    async def ping(self) -> None:
        return None

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        if self.fail_next_upsert:
            self.fail_next_upsert = False
            raise RuntimeError("simulated vector database failure")
        batch = tuple(records)
        self.batches.append(batch)
        return len(batch)

    async def search(
        self,
        query: VectorSearchQuery,
    ) -> tuple[VectorSearchHit, ...]:
        del query
        return ()

    async def delete_version(self, version_id: str) -> None:
        del version_id

    async def delete_index_version(self, index_version_id: str) -> None:
        self.deleted_index_versions.append(index_version_id)

    async def aclose(self) -> None:
        self.closed = True


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=(
            f"sqlite+aiosqlite:///{(tmp_path / 'indexing.db').as_posix()}"
        ),
        database_auto_create=True,
        knowledge_storage_dir=str(tmp_path / "files"),
        embedding_batch_size=1,
        milvus_enabled=False,
        milvus_required=False,
        api_token="index-test-token",
        ui_enabled=False,
    )


def _headers(user_id: str = "knowledge-admin") -> dict[str, str]:
    return {
        "Authorization": "Bearer index-test-token",
        "X-User-ID": user_id,
        "X-User-Name": user_id,
    }


def _upload(
    client: TestClient,
    content: str,
    *,
    document_id: str | None = None,
) -> dict[str, object]:
    data = {
        "title": "大会员索引测试",
        "business_domain": "membership",
        "knowledge_type": "generic",
        "access_scope": "public,support",
    }
    if document_id is not None:
        data["document_id"] = document_id
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=_headers(),
        data=data,
        files={"file": ("membership.md", content.encode(), "text/markdown")},
    )
    assert response.status_code == 201
    return response.json()["data"]


def test_index_build_batches_and_deduplicates_same_configuration(
    tmp_path: Path,
) -> None:
    store = _FakeVectorStore()
    app = create_app(_settings(tmp_path), vector_store=store)
    body = ("会员支付成功后应立即生效，请刷新页面并核对账号。" * 45)

    with TestClient(app) as client:
        uploaded = _upload(client, f"# 大会员\n\n{body}")
        version_id = uploaded["version"]["id"]
        built = client.post(
            f"/api/v1/knowledge/versions/{version_id}/indexes",
            headers=_headers(),
        )
        duplicate = client.post(
            f"/api/v1/knowledge/versions/{version_id}/indexes",
            headers=_headers(),
        )

    assert built.status_code == 201
    result = built.json()["data"]
    assert result["job_status"] == "succeeded"
    assert result["index"]["status"] == "active"
    assert result["index"]["indexed_chunks"] == result["index"]["total_chunks"]
    assert result["index"]["total_chunks"] > 1
    assert len(store.batches) == result["index"]["total_chunks"]
    assert all(len(batch) == 1 for batch in store.batches)
    assert all(
        record.index_version_id == result["index"]["id"]
        for batch in store.batches
        for record in batch
    )
    assert duplicate.json()["data"]["deduplicated"] is True
    assert duplicate.json()["data"]["index"]["id"] == result["index"]["id"]
    assert store.closed is True


def test_new_document_version_atomically_supersedes_old_active_index(
    tmp_path: Path,
) -> None:
    store = _FakeVectorStore()
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        first_upload = _upload(client, "# 大会员\n\n第一版会员规则。")
        document_id = first_upload["document"]["id"]
        first_version_id = first_upload["version"]["id"]
        first_index = client.post(
            f"/api/v1/knowledge/versions/{first_version_id}/indexes",
            headers=_headers(),
        ).json()["data"]["index"]

        second_upload = _upload(
            client,
            "# 大会员\n\n第二版会员规则，增加支付到账说明。",
            document_id=str(document_id),
        )
        second_version_id = second_upload["version"]["id"]
        second_index = client.post(
            f"/api/v1/knowledge/versions/{second_version_id}/indexes",
            headers=_headers(),
        ).json()["data"]["index"]
        old_history = client.get(
            f"/api/v1/knowledge/versions/{first_version_id}/indexes",
            headers=_headers(),
        )

    assert first_index["status"] == "active"
    assert second_index["status"] == "active"
    assert old_history.json()["data"][0]["status"] == "superseded"


def test_failed_index_job_can_retry_without_deleting_active_generation(
    tmp_path: Path,
) -> None:
    store = _FakeVectorStore()
    store.fail_next_upsert = True
    with TestClient(
        create_app(_settings(tmp_path), vector_store=store)
    ) as client:
        uploaded = _upload(client, "# 大会员\n\n支付后立即生效。")
        version_id = uploaded["version"]["id"]
        failed = client.post(
            f"/api/v1/knowledge/versions/{version_id}/indexes",
            headers=_headers(),
        )
        job_id = failed.json()["data"]["job_id"]
        retried = client.post(
            f"/api/v1/knowledge/index-jobs/{job_id}/retry",
            headers=_headers(),
        )

    assert failed.json()["data"]["job_status"] == "failed"
    assert failed.json()["data"]["error_code"] == "INDEX_BUILD_FAILED"
    assert retried.json()["data"]["job_status"] == "succeeded"
    assert retried.json()["data"]["attempt_count"] == 2
    index_id = retried.json()["data"]["index"]["id"]
    # 首次构建前、失败清理、重试前都会只针对自己的逻辑索引版本。
    assert set(store.deleted_index_versions) == {index_id}


def test_index_build_requires_configured_vector_store(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        uploaded = _upload(client, "# 大会员\n\n支付后立即生效。")
        version_id = uploaded["version"]["id"]
        response = client.post(
            f"/api/v1/knowledge/versions/{version_id}/indexes",
            headers=_headers(),
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
