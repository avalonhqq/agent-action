"""Smoke test for the NiceGUI page mounted on the production app."""

from fastapi.testclient import TestClient

from bili_support.main import app


def test_support_ui_is_mounted() -> None:
    response = TestClient(app).get("/support/")

    assert response.status_code == 200
    assert "BiliSupport AI" in response.text
    assert "识别意图" in response.text
    assert "企业智能客服能力中心" in response.text
    assert "知识入库" in response.text
    assert "领域词条" in response.text
    assert "审核发布" in response.text
    assert "写入候选词" in response.text
    assert "发布新版本" in response.text
    assert "选择 PDF / DOCX / Markdown / TXT" in response.text
