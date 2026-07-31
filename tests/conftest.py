"""全局测试隔离：任何测试都不能意外读取开发者真实.env或模型密钥。"""

import os
from collections.abc import Iterator

import pytest

from bili_support.core.config import reset_settings


@pytest.fixture(autouse=True)
def isolate_project_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """清理pytest-dotenv或Shell注入的BILI_SUPPORT变量。

    具体测试仍可在fixture开始后用monkeypatch.setenv显式声明所需配置。
    """

    for key in list(os.environ):
        if key.startswith("BILI_SUPPORT_"):
            monkeypatch.delenv(key)
    reset_settings()
    yield
    reset_settings()
