"""Integration tests for Week 1 API boundaries and request context."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from bili_support.core.config import Settings
from bili_support.core.exceptions import ResourceNotFoundError
from bili_support.main import create_app


def _test_app() -> FastAPI:
    return create_app(Settings(_env_file=None, app_name="Test App", app_version="1.0.0"))


def test_ready_reports_initialized_configuration() -> None:
    response = TestClient(_test_app()).get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "Test App",
        "version": "1.0.0",
        "checks": {
            "configuration": "ready",
            "database": "ready",
            "llm_provider": "ready",
        },
    }


def test_request_id_is_generated_and_returned() -> None:
    response = TestClient(_test_app()).get("/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert request_id.isalnum()


def test_valid_client_request_id_is_propagated() -> None:
    response = TestClient(_test_app()).get(
        "/health",
        headers={"X-Request-ID": "gateway:request-123"},
    )

    assert response.headers["X-Request-ID"] == "gateway:request-123"


def test_invalid_client_request_id_is_replaced() -> None:
    response = TestClient(_test_app()).get(
        "/health",
        headers={"X-Request-ID": "invalid id with spaces"},
    )

    assert response.headers["X-Request-ID"] != "invalid id with spaces"


def test_app_error_uses_public_error_contract() -> None:
    application = _test_app()

    @application.get("/test/missing")
    async def missing() -> None:
        raise ResourceNotFoundError(details={"resource_type": "video"})

    response = TestClient(application).get(
        "/test/missing",
        headers={"X-Request-ID": "request-not-found"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "request-not-found"
    assert response.json() == {
        "success": False,
        "error": {
            "code": "RESOURCE_NOT_FOUND",
            "message": "请求的资源不存在",
            "details": {"resource_type": "video"},
        },
        "request_id": "request-not-found",
    }


def test_validation_error_does_not_echo_rejected_input() -> None:
    application = _test_app()

    @application.get("/test/videos/{video_id}")
    async def video(video_id: int) -> dict[str, int]:
        return {"video_id": video_id}

    secret_input = "secret-value-that-must-not-be-echoed"
    response = TestClient(application).get(f"/test/videos/{secret_input}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert secret_input not in response.text


def test_unexpected_error_hides_internal_exception() -> None:
    application = _test_app()

    @application.get("/test/failure")
    async def failure() -> None:
        raise RuntimeError("database password=never-return-this")

    with capture_logs() as logs:
        response = TestClient(application, raise_server_exceptions=False).get(
            "/test/failure",
            headers={"X-Request-ID": "request-internal-error"},
        )

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "request-internal-error"
    assert response.json()["error"] == {
        "code": "INTERNAL_ERROR",
        "message": "服务暂时不可用",
        "details": None,
    }
    assert "never-return-this" not in response.text
    assert "never-return-this" not in str(logs)
    error_log = next(log for log in logs if log["event"] == "unhandled_exception")
    assert error_log["exception_type"] == "RuntimeError"
    assert error_log["request_id"] == "request-internal-error"


def test_access_log_contains_request_context_without_query_values() -> None:
    application = _test_app()

    with capture_logs() as logs:
        response = TestClient(application).get(
            "/health?token=must-not-be-logged",
            headers={"X-Request-ID": "request-log-test"},
        )

    assert response.status_code == 200
    completed = next(log for log in logs if log["event"] == "http_request_completed")
    assert completed["request_id"] == "request-log-test"
    assert completed["method"] == "GET"
    assert completed["path"] == "/health"
    assert completed["status_code"] == 200
    assert isinstance(completed["duration_ms"], float)
    assert "must-not-be-logged" not in str(completed)
