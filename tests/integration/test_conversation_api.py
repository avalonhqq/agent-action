"""End-to-end tests for authenticated, persisted Week 3 conversations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from bili_support.core.config import Settings
from bili_support.llm.errors import LLMUnavailableError
from bili_support.llm.mock import MockLLMProvider
from bili_support.llm.types import LLMRequest, LLMResponse, StreamChunk
from bili_support.main import create_app


def _settings(database_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        database_auto_create=True,
        api_token="test-token",
        ui_enabled=False,
    )


def _headers(user_id: str = "user-a", request_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer test-token",
        "X-User-ID": user_id,
        "X-User-Name": f"name-{user_id}",
    }
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


class _UnavailableProvider:
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMUnavailableError

    async def stream(self, request: LLMRequest):
        raise LLMUnavailableError
        yield StreamChunk()


def test_conversation_requires_valid_credentials(tmp_path: Path) -> None:
    app = create_app(_settings(tmp_path / "auth.db"))

    with TestClient(app) as client:
        missing = client.get("/api/v1/conversations")
        invalid = client.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer wrong", "X-User-ID": "user-a"},
        )
        malformed_user = client.get(
            "/api/v1/conversations",
            headers={"Authorization": "Bearer test-token", "X-User-ID": "bad user"},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert malformed_user.status_code == 401
    assert missing.json()["error"]["code"] == "UNAUTHORIZED"


def test_readiness_fails_safely_when_database_is_unreachable(tmp_path: Path) -> None:
    missing_parent = tmp_path / "does-not-exist" / "database.db"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{missing_parent.as_posix()}",
        database_auto_create=False,
        ui_enabled=False,
    )
    app = create_app(settings)

    response = TestClient(app, raise_server_exceptions=False).get("/ready")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"
    assert str(missing_parent) not in response.text


def test_user_can_continue_history_and_cannot_read_another_user_thread(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "conversation.db"
    app = create_app(
        _settings(database_path),
        llm_provider=MockLLMProvider(response_text="固定客服回答", chunk_size=2),
    )

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "会员咨询"},
            headers=_headers(request_id="create-1"),
        )
        thread_id = created.json()["data"]["thread_id"]

        first = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "你好"},
            headers=_headers(request_id="message-1"),
        )
        second = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "hello"},
            headers=_headers(request_id="message-2"),
        )
        history = client.get(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=_headers(),
        )
        own_list = client.get("/api/v1/conversations", headers=_headers())
        other_list = client.get(
            "/api/v1/conversations", headers=_headers(user_id="user-b")
        )
        forbidden_by_hiding = client.get(
            f"/api/v1/conversations/{thread_id}/messages",
            headers=_headers(user_id="user-b"),
        )

    assert created.status_code == 201
    assert first.status_code == 200
    assert second.status_code == 200
    assert [item["role"] for item in history.json()["data"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert own_list.json()["data"][0]["thread_id"] == thread_id
    assert other_list.json()["data"] == []
    assert forbidden_by_hiding.status_code == 404

    with sqlite3.connect(database_path) as connection:
        model_calls = connection.execute(
            "SELECT request_id, status, total_tokens FROM model_calls ORDER BY created_at"
        ).fetchall()
        linked_messages = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE request_id IN ('message-1', 'message-2')"
        ).fetchone()
        explicit_links = connection.execute(
            "SELECT COUNT(*) FROM model_calls mc "
            "JOIN messages u ON u.id = mc.user_message_id "
            "JOIN messages a ON a.id = mc.assistant_message_id "
            "WHERE u.role = 'user' AND a.role = 'assistant'"
        ).fetchone()
    assert [(item[0], item[1]) for item in model_calls] == [
        ("message-1", "success"),
        ("message-2", "success"),
    ]
    assert all(item[2] > 0 for item in model_calls)
    assert linked_messages == (4,)
    assert explicit_links == (2,)


def test_stream_is_persisted_and_database_survives_app_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "restart.db"
    settings = _settings(database_path)

    first_app = create_app(
        settings,
        llm_provider=MockLLMProvider(response_text="流式持久化", chunk_size=2),
    )
    with TestClient(first_app) as client:
        created = client.post(
            "/api/v1/conversations", json={"title": "流式会话"}, headers=_headers()
        )
        thread_id = created.json()["data"]["thread_id"]
        streamed = client.post(
            f"/api/v1/conversations/{thread_id}/messages/stream",
            json={"content": "你好"},
            headers=_headers(request_id="stream-persist-1"),
        )
    assert "event: delta" in streamed.text
    assert "event: route" in streamed.text
    assert '"target": "general_chat"' in streamed.text
    assert "event: completed" in streamed.text

    second_app = create_app(settings)
    with TestClient(second_app) as client:
        history = client.get(
            f"/api/v1/conversations/{thread_id}/messages", headers=_headers()
        )

    assert history.status_code == 200
    assert [item["content"] for item in history.json()["data"]] == [
        "你好",
        "流式持久化",
    ]
    with sqlite3.connect(database_path) as connection:
        call = connection.execute(
            "SELECT operation, status FROM model_calls WHERE request_id = ?",
            ("stream-persist-1",),
        ).fetchone()
    assert call == ("stream:general_chat", "success")


def test_model_failure_preserves_user_message_and_auditable_error(tmp_path: Path) -> None:
    database_path = tmp_path / "failure.db"
    app = create_app(_settings(database_path), llm_provider=_UnavailableProvider())

    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/api/v1/conversations", json={"title": "失败审计"}, headers=_headers()
        )
        thread_id = created.json()["data"]["thread_id"]
        failed = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "你好"},
            headers=_headers(request_id="failed-call-1"),
        )
        history = client.get(
            f"/api/v1/conversations/{thread_id}/messages", headers=_headers()
        )

    assert failed.status_code == 503
    assert [item["role"] for item in history.json()["data"]] == ["user"]
    with sqlite3.connect(database_path) as connection:
        call = connection.execute(
            "SELECT status, error_code, user_message_id, assistant_message_id "
            "FROM model_calls WHERE request_id = ?",
            ("failed-call-1",),
        ).fetchone()
    assert call is not None
    assert call[0:2] == ("error", "MODEL_UNAVAILABLE")
    assert call[2] is not None
    assert call[3] is None


def test_knowledge_route_without_evidence_does_not_call_free_model(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "no-evidence.db"
    app = create_app(_settings(database_path), llm_provider=_UnavailableProvider())

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "无证据保护"},
            headers=_headers(),
        )
        thread_id = created.json()["data"]["thread_id"]
        response = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "会员权益说明"},
            headers=_headers(request_id="no-evidence-1"),
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["routing"]["target"] == "knowledge_rag"
    assert data["routing"]["retrieval"]["evidence_count"] == 0
    assert "没有找到足够依据" in data["answer"]
    with sqlite3.connect(database_path) as connection:
        call = connection.execute(
            "SELECT operation, model, total_tokens FROM model_calls "
            "WHERE request_id = ?",
            ("no-evidence-1",),
        ).fetchone()
    assert call == ("complete:knowledge_rag", "deterministic-knowledge", 0)


def test_unsafe_route_skips_answer_model_and_is_auditable(tmp_path: Path) -> None:
    database_path = tmp_path / "unsafe-route.db"
    settings = _settings(database_path).model_copy(
        update={
            "intent_mock_response": (
                '{"route":"unsafe","intents":[],"entities":[],'
                '"sentiment":"neutral","risk":"critical","confidence":1.0,'
                '"needs_clarification":false,"clarification_question":null,'
                '"source":"model"}'
            )
        }
    )
    app = create_app(settings, llm_provider=_UnavailableProvider())

    with TestClient(app) as client:
        created = client.post(
            "/api/v1/conversations",
            json={"title": "安全路由"},
            headers=_headers(),
        )
        thread_id = created.json()["data"]["thread_id"]
        response = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "危险请求"},
            headers=_headers(request_id="unsafe-route-1"),
        )

    assert response.status_code == 200
    assert response.json()["data"]["routing"]["target"] == "safety"
    assert "不能协助" in response.json()["data"]["answer"]
    with sqlite3.connect(database_path) as connection:
        call = connection.execute(
            "SELECT operation, model, total_tokens FROM model_calls "
            "WHERE request_id = ?",
            ("unsafe-route-1",),
        ).fetchone()
    assert call == ("complete:safety", "deterministic-routing", 0)


def test_graph_interrupt_review_and_resume_is_persisted(tmp_path: Path) -> None:
    """9C主路径：真实interrupt → 审核员领取 → Command恢复 → 审计落库。"""

    database_path = tmp_path / "graph-review.db"
    settings = _settings(database_path).model_copy(
        update={
            "graph_review_admin_user_ids": "review-admin",
            "intent_mock_response": (
                '{"route":"supported","intents":[{"domain":"account",'
                '"action":"recover","confidence":0.99}],"entities":[],'
                '"sentiment":"anxious","risk":"high","confidence":0.99,'
                '"needs_clarification":false,"clarification_question":null,'
                '"source":"model"}'
            ),
        }
    )
    app = create_app(settings, llm_provider=_UnavailableProvider())

    with TestClient(app) as client:
        # 测试使用内存Saver验证LangGraph协议；生产装配仍使用MongoDB Saver。
        app.state.conversation_service.configure_graph_checkpoint(InMemorySaver())
        created = client.post(
            "/api/v1/conversations",
            json={"title": "账号找回审核"},
            headers=_headers(),
        )
        thread_id = created.json()["data"]["thread_id"]
        interrupted = client.post(
            f"/api/v1/conversations/{thread_id}/messages",
            json={"content": "我的账号被盗，需要找回"},
            headers=_headers(request_id="graph-interrupt-1"),
        )
        owner_status = client.get(
            f"/api/v1/conversations/{thread_id}/executions/graph-interrupt-1",
            headers=_headers(),
        )
        ordinary_pending = client.get(
            "/api/v1/conversations/reviews/pending",
            headers=_headers(),
        )
        pending = client.get(
            "/api/v1/conversations/reviews/pending",
            headers=_headers(user_id="review-admin"),
        )
        resumed = client.post(
            f"/api/v1/conversations/{thread_id}/executions/graph-interrupt-1/resume",
            json={"decision": "approve", "note": "身份材料已由客服核验"},
            headers=_headers(user_id="review-admin", request_id="graph-resume-1"),
        )
        duplicate = client.post(
            f"/api/v1/conversations/{thread_id}/executions/graph-interrupt-1/resume",
            json={"decision": "approve", "note": "重复提交必须被拒绝"},
            headers=_headers(user_id="review-admin", request_id="graph-resume-2"),
        )

    assert interrupted.status_code == 200
    interrupted_data = interrupted.json()["data"]
    assert interrupted_data["execution"]["status"] == "interrupted"
    assert interrupted_data["execution"]["next_nodes"] == ["human_review"]
    assert interrupted_data["routing"]["target"] == "human_review_mock"
    assert owner_status.status_code == 200
    assert owner_status.json()["data"]["interrupt"]["kind"] == "human_review"
    assert ordinary_pending.status_code == 403
    assert pending.status_code == 200
    assert pending.json()["data"][0]["request_id"] == "graph-interrupt-1"
    assert resumed.status_code == 200
    resumed_data = resumed.json()["data"]
    assert resumed_data["execution"]["status"] == "completed"
    assert resumed_data["execution"]["review_status"] == "approved"
    assert "人工审核已批准" in resumed_data["answer"]
    assert duplicate.status_code == 409

    with sqlite3.connect(database_path) as connection:
        review = connection.execute(
            "SELECT status, decision_note FROM graph_reviews WHERE request_id = ?",
            ("graph-interrupt-1",),
        ).fetchone()
        resume_call = connection.execute(
            "SELECT operation, status FROM model_calls WHERE request_id = ?",
            ("graph-resume-1",),
        ).fetchone()
    assert review == ("approved", "身份材料已由客服核验")
    assert resume_call == ("resume:human_review_mock", "success")
