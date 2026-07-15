"""Unit tests for configuration settings."""

import os
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic_core import ValidationError

from bili_support.core.config import Environment, get_settings, reset_settings


@pytest.fixture(autouse=True)
def isolate_settings():
    reset_settings()
    env_vars = {k: v for k, v in os.environ.items() if k.startswith("BILI_SUPPORT_")}
    for k in list(os.environ.keys()):
        if k.startswith("BILI_SUPPORT_"):
            del os.environ[k]
    yield
    reset_settings()
    os.environ.update(env_vars)


def test_default_settings():
    settings = get_settings()
    assert settings.app_name == "BiliSupport AI"
    assert settings.app_version == "0.0.1"
    assert settings.environment == Environment.LOCAL
    assert settings.debug is False
    assert settings.host == "127.0.0.1"
    assert settings.port == 8010
    assert settings.log_level.value == "INFO"


def test_port_string_converted_to_int():
    os.environ["BILI_SUPPORT_PORT"] = "8080"
    reset_settings()
    settings = get_settings()
    assert isinstance(settings.port, int)
    assert settings.port == 8080


def test_invalid_port_rejected():
    os.environ["BILI_SUPPORT_PORT"] = "0"
    reset_settings()
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "port" in str(exc_info.value)


def test_invalid_environment_rejected():
    os.environ["BILI_SUPPORT_ENVIRONMENT"] = "invalid"
    reset_settings()
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "environment" in str(exc_info.value)


def test_production_debug_prohibited():
    os.environ["BILI_SUPPORT_ENVIRONMENT"] = "production"
    os.environ["BILI_SUPPORT_DEBUG"] = "true"
    reset_settings()
    with pytest.raises(ValidationError) as exc_info:
        get_settings()
    assert "debug" in str(exc_info.value).lower() or "production" in str(exc_info.value).lower()


def test_fastapi_title_version_from_settings():
    os.environ["BILI_SUPPORT_APP_NAME"] = "Test App"
    os.environ["BILI_SUPPORT_APP_VERSION"] = "1.2.3"
    reset_settings()

    modules_to_reload = [key for key in sys.modules.keys() if key.startswith("bili_support")]
    for module in modules_to_reload:
        del sys.modules[module]

    from bili_support.main import app

    assert app.title == "Test App"
    assert app.version == "1.2.3"

    client = TestClient(app)
    response = client.get("/health")
    data = response.json()
    assert data["service"] == "Test App"
    assert data["version"] == "1.2.3"