"""Pydantic Settings and environment configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
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


class LLMProviderKind(StrEnum):
    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"


class LLMStructuredOutputMode(StrEnum):
    """供应商在线路协议层支持的结构化输出能力。"""

    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"


_DEFAULT_INTENT_MOCK_RESPONSE = (
    '{"route":"supported","intents":[{"domain":"membership",'
    '"action":"query","confidence":0.9}],"entities":[],"sentiment":"neutral",'
    '"risk":"low","confidence":0.9,"needs_clarification":false,'
    '"clarification_question":null,"source":"model"}'
)


class Settings(BaseSettings):
    app_name: str = "BiliSupport AI"
    app_version: str = "0.0.1"
    environment: Environment = Environment.LOCAL
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8010
    log_level: LogLevel = LogLevel.INFO
    llm_provider: LLMProviderKind = LLMProviderKind.MOCK
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
    llm_model: str = "mock-support-model"
    llm_structured_output_mode: LLMStructuredOutputMode = (
        LLMStructuredOutputMode.JSON_SCHEMA
    )
    llm_mock_response: str = "这是来自确定性 Mock Provider 的客服回复。"
    intent_mock_response: str = _DEFAULT_INTENT_MOCK_RESPONSE
    # 结构重试与 HTTP 重试分开计数，防止格式错误导致无限付费调用。
    intent_parse_retries: int = Field(default=1, ge=0, le=3)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    llm_retry_base_delay: float = Field(default=0.1, ge=0)
    llm_temperature: float = Field(default=0.0, ge=0, le=2)
    llm_max_tokens: int = Field(default=512, gt=0)
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    database_url: str = "sqlite+aiosqlite:///./data/bili_support.db"
    database_echo: bool = False
    database_auto_create: bool = True
    redis_enabled: bool = False
    redis_required: bool = False
    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    redis_history_ttl_seconds: int = Field(default=900, gt=0, le=86400)
    redis_history_max_messages: int = Field(default=100, gt=0, le=500)
    api_token: SecretStr = SecretStr("local-demo-token")
    ui_enabled: bool = True
    ui_prefill_demo_credentials: bool = False
    ui_storage_secret: SecretStr = SecretStr("local-ui-storage-secret-change-me")

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

    @field_validator(
        "llm_base_url",
        "llm_model",
        "llm_mock_response",
        "intent_mock_response",
        "database_url",
    )
    @classmethod
    def llm_text_settings_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LLM text settings must not be blank")
        return value

    @model_validator(mode="after")
    def production_debug_prohibited(self, info: ValidationInfo) -> Settings:
        if self.environment == Environment.PRODUCTION and self.debug:
            raise ValueError("debug must be False in production environment")
        if self.environment == Environment.PRODUCTION and self.database_auto_create:
            raise ValueError("database_auto_create must be False in production")
        if self.environment == Environment.PRODUCTION and self.ui_prefill_demo_credentials:
            raise ValueError("ui_prefill_demo_credentials must be False in production")
        if self.redis_required and not self.redis_enabled:
            raise ValueError("redis_required needs redis_enabled=True")
        if self.environment == Environment.PRODUCTION and (
            self.api_token.get_secret_value() == "local-demo-token"
            or self.ui_storage_secret.get_secret_value()
            == "local-ui-storage-secret-change-me"
        ):
            raise ValueError("production secrets must be explicitly configured")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
