from fastapi.testclient import TestClient

from bili_support.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "BiliSupport AI"
    assert data["version"] == "0.0.1"

