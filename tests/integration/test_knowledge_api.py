from pathlib import Path

from fastapi.testclient import TestClient

from bili_support.core.config import Settings
from bili_support.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'knowledge.db').as_posix()}",
        database_auto_create=True,
        knowledge_storage_dir=str(tmp_path / "files"),
        api_token="knowledge-test-token",
        ui_enabled=False,
    )


def _headers(user_id: str = "knowledge-admin") -> dict[str, str]:
    return {
        "Authorization": "Bearer knowledge-test-token",
        "X-User-ID": user_id,
        "X-User-Name": user_id,
    }


def _upload(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "membership.md",
) -> object:
    return client.post(
        "/api/v1/knowledge/documents",
        headers=_headers(),
        data={
            "title": "大会员规则",
            "business_domain": "membership",
            "access_scope": "public,support",
        },
        files={"file": (filename, content, "text/markdown")},
    )


def test_upload_is_idempotent_and_changed_content_creates_version(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        first = _upload(client, b"# Membership\n\nVersion one.")
        duplicate = _upload(client, b"# Membership\n\nVersion one.")
        changed = _upload(client, b"# Membership\n\nVersion two.")
        document_id = first.json()["data"]["document"]["id"]
        versions = client.get(
            f"/api/v1/knowledge/documents/{document_id}/versions",
            headers=_headers(),
        )

    assert first.status_code == 201
    assert first.json()["data"]["job_status"] == "succeeded"
    assert first.json()["data"]["block_count"] == 2
    assert duplicate.json()["data"]["deduplicated"] is True
    assert duplicate.json()["data"]["version"]["id"] == first.json()["data"]["version"]["id"]
    assert changed.json()["data"]["version"]["version_number"] == 2
    assert len(versions.json()["data"]) == 2


def test_failed_document_can_retry_and_remains_auditable(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        failed = _upload(client, b"not-a-pdf", filename="broken.pdf")
        job_id = failed.json()["data"]["job_id"]
        retried = client.post(
            f"/api/v1/knowledge/jobs/{job_id}/retry",
            headers=_headers(),
        )

    assert failed.status_code == 201
    assert failed.json()["data"]["job_status"] == "failed"
    assert failed.json()["data"]["error_code"] == "DOCUMENT_SIGNATURE_MISMATCH"
    assert retried.status_code == 200
    assert retried.json()["data"]["job_status"] == "failed"
    assert retried.json()["data"]["attempt_count"] == 2


def test_document_is_isolated_by_owner_and_soft_deleted(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        uploaded = _upload(client, b"# Account\n\nRecovery.")
        document_id = uploaded.json()["data"]["document"]["id"]
        hidden = client.get(
            f"/api/v1/knowledge/documents/{document_id}/versions",
            headers=_headers("other-admin"),
        )
        deleted = client.delete(
            f"/api/v1/knowledge/documents/{document_id}",
            headers=_headers(),
        )
        documents = client.get(
            "/api/v1/knowledge/documents",
            headers=_headers(),
        )

    assert hidden.status_code == 404
    assert deleted.status_code == 204
    assert documents.json()["data"] == []
