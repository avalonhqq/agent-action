"""领域词候选、人工审核、版本发布和制品下载端到端测试。"""

from pathlib import Path

from fastapi.testclient import TestClient

from bili_support.core.config import Settings
from bili_support.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=(
            f"sqlite+aiosqlite:///{(tmp_path / 'dictionary.db').as_posix()}"
        ),
        database_auto_create=True,
        knowledge_storage_dir=str(tmp_path / "files"),
        api_token="dictionary-test-token",
        ui_enabled=False,
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer dictionary-test-token",
        "X-User-ID": "dictionary-admin",
        "X-User-Name": "Dictionary Admin",
    }


def _candidate(client: TestClient, term: str, aliases: list[str] | None = None):
    return client.post(
        "/api/v1/knowledge/dictionary/terms",
        headers=_headers(),
        json={
            "term": term,
            "aliases": aliases or [],
            "business_domain": "membership",
            "term_type": "product",
            "frequency": 10000,
            "source_type": "product_catalog",
            "source_reference": "catalog-v1",
        },
    )


def test_candidate_review_publish_and_versioned_artifact(tmp_path: Path) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        created = _candidate(client, "超级大会员", ["超会"])
        duplicate = _candidate(client, "超级大会员")
        term_id = created.json()["data"]["id"]
        reviewed = client.post(
            f"/api/v1/knowledge/dictionary/terms/{term_id}/review",
            headers=_headers(),
            json={"approved": True, "review_note": "产品目录已确认"},
        )
        repeated_review = client.post(
            f"/api/v1/knowledge/dictionary/terms/{term_id}/review",
            headers=_headers(),
            json={"approved": True, "review_note": "重复审核"},
        )
        first_version = client.post(
            "/api/v1/knowledge/dictionary/versions/publish",
            headers=_headers(),
            json={"release_note": "首版产品词"},
        )
        idempotent = client.post(
            "/api/v1/knowledge/dictionary/versions/publish",
            headers=_headers(),
            json={"release_note": "内容未变化"},
        )
        artifact = client.get(
            "/api/v1/knowledge/dictionary/versions/active/artifact",
            headers=_headers(),
        )

    assert created.status_code == 201
    assert duplicate.json()["data"]["id"] == term_id
    assert reviewed.json()["data"]["status"] == "approved"
    assert repeated_review.status_code == 409
    assert first_version.json()["data"]["version_number"] == 1
    assert idempotent.json()["data"]["id"] == first_version.json()["data"]["id"]
    assert artifact.json()["data"]["term_count"] == 2
    assert "超级大会员 10000 nz" in artifact.json()["data"]["artifact_content"]
    assert "超会 10000 nz" in artifact.json()["data"]["artifact_content"]


def test_mock_source_stays_candidate_and_new_release_supersedes_old(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(_settings(tmp_path))) as client:
        mocked = client.post(
            "/api/v1/knowledge/dictionary/candidates/mock",
            headers=_headers(),
            json={
                "terms": ["会员没亮", "会员没亮"],
                "business_domain": "membership",
                "source_type": "conversation_log_mock",
                "source_reference": "mock-batch-001",
            },
        )
        term_id = mocked.json()["data"][0]["id"]
        before_review = client.post(
            "/api/v1/knowledge/dictionary/versions/publish",
            headers=_headers(),
            json={"release_note": "不应成功"},
        )
        client.post(
            f"/api/v1/knowledge/dictionary/terms/{term_id}/review",
            headers=_headers(),
            json={"approved": True, "review_note": "人工确认用户表达"},
        )
        published = client.post(
            "/api/v1/knowledge/dictionary/versions/publish",
            headers=_headers(),
            json={"release_note": "审核后发布"},
        )
        second_term = _candidate(client, "硬核会员")
        client.post(
            "/api/v1/knowledge/dictionary/terms/"
            f"{second_term.json()['data']['id']}/review",
            headers=_headers(),
            json={"approved": True, "review_note": "产品运营确认"},
        )
        second_version = client.post(
            "/api/v1/knowledge/dictionary/versions/publish",
            headers=_headers(),
            json={"release_note": "增加硬核会员"},
        )
        versions = client.get(
            "/api/v1/knowledge/dictionary/versions",
            headers=_headers(),
        )

    assert mocked.status_code == 201
    assert len(mocked.json()["data"]) == 1
    assert mocked.json()["data"][0]["status"] == "candidate"
    assert before_review.status_code == 409
    assert published.status_code == 201
    assert second_version.json()["data"]["version_number"] == 2
    assert versions.json()["data"][0]["status"] == "active"
    assert versions.json()["data"][1]["status"] == "superseded"
