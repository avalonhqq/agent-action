"""Pydantic Settings and environment configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings

from bili_support.knowledge.reranking import RerankProviderKind
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.tokenizers import BM25TokenizerKind


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


class EmbeddingProviderKind(StrEnum):
    """Child文本转稠密向量的Provider类型。"""

    MOCK = "mock"
    OPENAI_COMPATIBLE = "openai_compatible"


class VectorStoreKind(StrEnum):
    """当前商业化方案统一使用Milvus，不再保留FAISS运行分支。"""

    MILVUS = "milvus"


class MilvusConsistencyLevel(StrEnum):
    """Milvus读写可见性级别；第六周默认同会话写后可读。"""

    STRONG = "Strong"
    BOUNDED = "Bounded"
    SESSION = "Session"
    EVENTUALLY = "Eventually"


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
    # 页面默认使用当前已评估的 Prompt；历史版本仍由离线评估器显式选择。
    intent_prompt_version: int = Field(default=3, ge=1)
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
    knowledge_storage_dir: str = "./data/knowledge/files"
    knowledge_max_file_bytes: int = Field(
        default=10 * 1024 * 1024,
        gt=0,
        le=100 * 1024 * 1024,
    )
    embedding_provider: EmbeddingProviderKind = EmbeddingProviderKind.MOCK
    embedding_model: str = "mock-hash-embedding-v1"
    embedding_dimension: int = Field(default=128, ge=8, le=65536)
    embedding_batch_size: int = Field(default=64, ge=1, le=256)
    embedding_timeout_seconds: float = Field(default=30.0, gt=0)
    # Chunk契约变化会改变向量输入，必须进入索引build_key。
    knowledge_index_chunk_schema_version: str = "small-to-big-v1"
    vector_store: VectorStoreKind = VectorStoreKind.MILVUS
    milvus_enabled: bool = False
    milvus_required: bool = False
    milvus_uri: str = "http://127.0.0.1:19530"
    milvus_token: SecretStr = SecretStr("root:Milvus")
    # v2新增index_version_id字段；不原地修改已存在的v1 Collection。
    milvus_collection: str = "bili_support_child_v2"
    milvus_consistency_level: MilvusConsistencyLevel = MilvusConsistencyLevel.SESSION
    milvus_index_m: int = Field(default=16, ge=2, le=2048)
    milvus_index_ef_construction: int = Field(default=200, ge=8, le=4096)
    milvus_search_ef: int = Field(default=64, ge=1, le=4096)
    # 7A-2默认使用Jieba搜索模式；bigram保留为可重放的对照基线。
    bm25_tokenizer: BM25TokenizerKind = BM25TokenizerKind.JIEBA
    bm25_jieba_hmm_enabled: bool = False
    bm25_user_dictionary_path: str = "./data/dictionaries/bilibili_support.txt"
    # 7B固定集确认RRF无质量回退后，正式客服RAG默认使用Hybrid双路召回。
    customer_retrieval_mode: RetrievalMode = RetrievalMode.HYBRID
    # Rerank默认只提供可显式开启的Mock管线；真实LLM评估后再决定正式开启。
    rerank_provider: RerankProviderKind = RerankProviderKind.MOCK
    rerank_model: str = "mock-reranker-v1"
    rerank_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    rerank_max_concurrency: int = Field(default=4, ge=1, le=64)
    rerank_candidate_k: int = Field(default=10, ge=1, le=20)
    rerank_parse_retries: int = Field(default=1, ge=0, le=2)
    customer_rerank_enabled: bool = False
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
        "knowledge_storage_dir",
        "embedding_model",
        "knowledge_index_chunk_schema_version",
        "milvus_uri",
        "milvus_collection",
        "bm25_user_dictionary_path",
        "rerank_model",
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
        if self.milvus_required and not self.milvus_enabled:
            raise ValueError("milvus_required needs milvus_enabled=True")
        if self.milvus_search_ef < self.milvus_index_m:
            raise ValueError("milvus_search_ef must be at least milvus_index_m")
        if (
            self.customer_rerank_enabled
            and self.rerank_provider is RerankProviderKind.DISABLED
        ):
            raise ValueError("customer_rerank_enabled needs a rerank provider")
        if self.customer_rerank_enabled and self.rerank_candidate_k < 5:
            raise ValueError("customer rerank candidate budget must be at least 5")
        if self.environment == Environment.PRODUCTION and (
            self.api_token.get_secret_value() == "local-demo-token"
            or self.ui_storage_secret.get_secret_value()
            == "local-ui-storage-secret-change-me"
        ):
            raise ValueError("production secrets must be explicitly configured")
        if (
            self.environment == Environment.PRODUCTION
            and self.milvus_enabled
            and self.milvus_token.get_secret_value() == "root:Milvus"
        ):
            raise ValueError("production Milvus token must be explicitly configured")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    get_settings.cache_clear()
