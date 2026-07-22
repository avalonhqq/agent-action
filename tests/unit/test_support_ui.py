"""Smoke test for the NiceGUI page mounted on the production app."""

from fastapi.testclient import TestClient

from bili_support.main import app


def test_support_ui_is_mounted() -> None:
    response = TestClient(app).get("/support/")

    assert response.status_code == 200
    assert "BiliSupport AI" in response.text
    assert "识别意图" in response.text
    assert "意图识别实验" in response.text
