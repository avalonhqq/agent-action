"""Unit tests for configuration settings."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic_core import ValidationError

from bili_support.core.config import Environment, Settings, get_settings, reset_settings
from bili_support.main import create_app


@pytest.fixture(autouse=True)
def isolate_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Keep tests independent from the developer's environment and root .env file."""
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("BILI_SUPPORT_"):
            monkeypatch.delenv(key)
    reset_settings()
    yield
    reset_settings()


def test_default_settings() -> None:
    settings = get_settings()
    assert settings.app_name == "BiliSupport AI"
    assert settings.app_version == "0.0.1"
    assert settings.environment == Environment.LOCAL
    assert settings.debug is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8010
    assert settings.log_level.value == "INFO"


def test_port_string_converted_to_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILI_SUPPORT_PORT", "8080")
    reset_settings()
    settings = get_settings()
    assert isinstance(settings.port, int)
    assert settings.port == 8080


def test_invalid_port_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILI_SUPPORT_PORT", "0")
    reset_settings()
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "port" in str(exc_info.value)


def test_invalid_environment_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILI_SUPPORT_ENVIRONMENT", "invalid")
    reset_settings()
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "environment" in str(exc_info.value)


def test_production_debug_prohibited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILI_SUPPORT_ENVIRONMENT", "production")
    monkeypatch.setenv("BILI_SUPPORT_DEBUG", "true")
    reset_settings()
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "debug" in str(exc_info.value).lower() or "production" in str(exc_info.value).lower()


def test_fastapi_title_version_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        app_name="Test App",
        app_version="1.2.3",
    )
    app = create_app(settings)

    assert app.title == settings.app_name
    assert app.version == settings.app_version

    client = TestClient(app)
    response = client.get("/health")
    data = response.json()
    assert data["service"] == settings.app_name
    assert data["version"] == settings.app_version


def test_env_file_isolation(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BILI_SUPPORT_ENVIRONMENT=staging\n"
        "BILI_SUPPORT_PORT=9000\n"
    )

    settings = Settings(_env_file=str(env_file))
    assert settings.environment == Environment.STAGING
    assert settings.port == 9000
