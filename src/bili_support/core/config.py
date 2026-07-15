"""Pydantic Settings and environment configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class Settings(BaseSettings):
    app_name: str = "BiliSupport AI"
    app_version: str = "0.0.1"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8010
    log_level: LogLevel = LogLevel.INFO

    model_config = {
        "env_prefix": "BILI_SUPPORT_",
        "env_file": ".env",
        "extra": "ignore",
    }

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not (1 <= value <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return value

    @model_validator(mode="after")
    def production_debug_prohibited(self, info: ValidationInfo) -> Settings:
        if self.environment == Environment.PRODUCTION and self.debug:
            raise ValueError("debug must be False in production environment")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
