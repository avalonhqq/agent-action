"""应用入口：从配置装配数据库、模型、意图分类器、API 与页面。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from bili_support.api.error_handlers import register_exception_handlers
from bili_support.api.router import create_api_router
from bili_support.core.cache import (
    ConversationHistoryCache,
    RedisConversationHistoryCache,
)
from bili_support.core.config import Settings, get_settings
from bili_support.core.database import Database
from bili_support.core.exceptions import ServiceNotReadyError
from bili_support.core.logging import configure_logging
from bili_support.core.request_context import RequestContextMiddleware
from bili_support.core.security import create_auth_dependency
from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.factory import build_intent_provider
from bili_support.intent.hybrid import HybridIntentClassifier
from bili_support.intent.policies import HybridIntentPolicy
from bili_support.intent.rules import RuleIntentClassifier
from bili_support.knowledge.chunk_strategies import StrategySelector
from bili_support.knowledge.embedding import (
    DeterministicHashEmbeddingProvider,
    EmbeddingProvider,
)
from bili_support.knowledge.loaders import create_default_loader_registry
from bili_support.knowledge.rerank_factory import build_rerank_provider
from bili_support.knowledge.reranking import RerankProvider
from bili_support.knowledge.storage import LocalKnowledgeFileStore
from bili_support.knowledge.tokenizers import (
    BM25TokenizerKind,
    SearchTokenizer,
    create_search_tokenizer,
)
from bili_support.knowledge.vector_store import (
    MilvusVectorStore,
    VectorStore,
)
from bili_support.llm.context import BoundedContextBuilder, StandaloneQueryRewriter
from bili_support.llm.factory import build_llm_provider
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.prompts import create_default_prompt_registry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.service import ChatService
from bili_support.llm.usage import InMemoryUsageRecorder, UsageRecorder
from bili_support.routing import CustomerServiceRouter
from bili_support.schemas.system import HealthResponse, ReadinessResponse
from bili_support.services.conversations import ConversationService
from bili_support.services.dictionary import KnowledgeDictionaryService
from bili_support.services.indexing import KnowledgeIndexingService
from bili_support.services.knowledge import KnowledgeIngestionService
from bili_support.services.policy_retrieval import PolicyAwareKnowledgeRetriever
from bili_support.services.retrieval import KnowledgeRetrievalService
from bili_support.ui import register_support_ui


def create_app(
        settings: Settings | None = None,
        *,
        llm_provider: LLMProvider | None = None,
        intent_provider: LLMProvider | None = None,
        usage_recorder: UsageRecorder | None = None,
        database: Database | None = None,
        history_cache: ConversationHistoryCache | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_store: VectorStore | None = None,
        rerank_provider: RerankProvider | None = None,
        bm25_tokenizer: SearchTokenizer | None = None,
) -> FastAPI:
    """使用显式注入或缓存配置创建完整 FastAPI 应用。"""
    current_settings = settings or get_settings()
    configure_logging(current_settings.log_level)
    # 普通客服回答和意图识别在真实环境可共享 Provider；测试仍可分别注入。
    provider = llm_provider or build_llm_provider(current_settings)
    current_intent_provider = intent_provider or build_intent_provider(
        current_settings,
        shared_provider=provider,
    )
    # 同一 Registry 保证回答与意图 Prompt 的版本解析方式一致。
    prompt_registry = create_default_prompt_registry()
    current_rerank_provider = (
        rerank_provider
        or build_rerank_provider(
            settings=current_settings,
            llm_provider=provider,
            prompt_registry=prompt_registry,
        )
    )
    recorder = usage_recorder or InMemoryUsageRecorder()
    current_database = database or Database(
        current_settings.database_url,
        echo=current_settings.database_echo,
    )
    redis_cache = (
        RedisConversationHistoryCache(
            current_settings.redis_url.get_secret_value(),
            ttl_seconds=current_settings.redis_history_ttl_seconds,
            max_messages=current_settings.redis_history_max_messages,
        )
        if current_settings.redis_enabled
        else None
    )
    current_history_cache = history_cache or redis_cache
    # ChatService 负责生成客服答案；它与下面的 IntentClassifier 职责独立。
    chat_service = ChatService(
        provider=provider,
        model=current_settings.llm_model,
        prompt_registry=prompt_registry,
        usage_recorder=recorder,
        context_builder=BoundedContextBuilder(),
        rewriter=StandaloneQueryRewriter(),
        temperature=current_settings.llm_temperature,
        max_tokens=current_settings.llm_max_tokens,
        timeout_seconds=current_settings.llm_timeout_seconds,
    )
    # 模型分类器负责开放语义；混合分类器在调用前短路精确规则，调用后执行安全兜底。
    model_intent_classifier = IntentClassifier(
        provider=current_intent_provider,
        prompt_registry=prompt_registry,
        model=current_settings.llm_model,
        prompt_version=current_settings.intent_prompt_version,
        temperature=current_settings.llm_temperature,
        max_tokens=current_settings.llm_max_tokens,
        timeout_seconds=current_settings.llm_timeout_seconds,
        parse_retries=current_settings.intent_parse_retries,
    )
    intent_classifier = HybridIntentClassifier(
        rule_classifier=RuleIntentClassifier(),
        model_classifier=model_intent_classifier,
        policy=HybridIntentPolicy(),
    )
    knowledge_service = KnowledgeIngestionService(
        database=current_database,
        # Loader 注册表封装文件类型差异，Service 始终只处理统一 LoadedDocument。
        loaders=create_default_loader_registry(),
        chunk_strategies=StrategySelector(),
        # 当前使用本地文件系统；替换对象存储只需实现相同读写边界。
        file_store=LocalKnowledgeFileStore(
            Path(current_settings.knowledge_storage_dir)
        ),
        max_file_bytes=current_settings.knowledge_max_file_bytes,
    )
    dictionary_service = KnowledgeDictionaryService(current_database)
    # 6B默认使用确定性Hash Mock验证索引管线；真实Embedding Provider在后续模型实验接入。
    current_embedding_provider = embedding_provider or (
        DeterministicHashEmbeddingProvider(
            dimension=current_settings.embedding_dimension
        )
    )
    # 测试和纯SQLite模式不建立Milvus连接；开启后使用新的v2 Collection Schema。
    current_vector_store = vector_store or (
        MilvusVectorStore(
            uri=current_settings.milvus_uri,
            token=current_settings.milvus_token.get_secret_value(),
            collection_name=current_settings.milvus_collection,
            dimension=current_settings.embedding_dimension,
            index_m=current_settings.milvus_index_m,
            index_ef_construction=(
                current_settings.milvus_index_ef_construction
            ),
            search_ef=current_settings.milvus_search_ef,
            consistency_level=(
                current_settings.milvus_consistency_level.value
            ),
        )
        if current_settings.milvus_enabled
        else None
    )
    knowledge_indexing_service = KnowledgeIndexingService(
        database=current_database,
        embedding_provider=current_embedding_provider,
        vector_store=current_vector_store,
        embedding_provider_name=current_settings.embedding_provider.value,
        embedding_model=current_settings.embedding_model,
        embedding_dimension=current_settings.embedding_dimension,
        embedding_batch_size=current_settings.embedding_batch_size,
        embedding_timeout_seconds=current_settings.embedding_timeout_seconds,
        collection_name=current_settings.milvus_collection,
        chunk_schema_version=(
            current_settings.knowledge_index_chunk_schema_version
        ),
    )
    knowledge_retrieval_service = KnowledgeRetrievalService(
        database=current_database,
        embedding_provider=current_embedding_provider,
        vector_store=current_vector_store,
        embedding_model=current_settings.embedding_model,
        embedding_dimension=current_settings.embedding_dimension,
        embedding_timeout_seconds=current_settings.embedding_timeout_seconds,
        collection_name=current_settings.milvus_collection,
        rewriter=StandaloneQueryRewriter(),
        bm25_tokenizer=(
            bm25_tokenizer
            or create_search_tokenizer(
                kind=current_settings.bm25_tokenizer,
                user_dictionary_path=(
                    current_settings.bm25_user_dictionary_path
                    if current_settings.bm25_tokenizer is BM25TokenizerKind.JIEBA
                    else None
                ),
                jieba_hmm_enabled=current_settings.bm25_jieba_hmm_enabled,
            )
        ),
        rerank_provider=current_rerank_provider,
        rerank_model=current_settings.rerank_model,
        rerank_timeout_seconds=current_settings.rerank_timeout_seconds,
        rerank_max_concurrency=current_settings.rerank_max_concurrency,
    )
    # 7D策略编排复用同一个基础检索服务；会话与离线评估因此执行完全相同的门禁。
    policy_retrieval_service = PolicyAwareKnowledgeRetriever(
        knowledge_retrieval_service,
        customer_rerank_enabled=current_settings.customer_rerank_enabled,
    )
    # 正式消息先完成意图路由；普通知识问题再进入真实检索和Grounded Prompt。
    customer_service_router = CustomerServiceRouter(intent_classifier)
    conversation_service = ConversationService(
        current_database,
        chat_service,
        router=customer_service_router,
        knowledge_retrieval_service=knowledge_retrieval_service,
        policy_retrieval_service=policy_retrieval_service,
        customer_retrieval_mode=current_settings.customer_retrieval_mode,
        customer_rerank_enabled=current_settings.customer_rerank_enabled,
        rerank_candidate_k=current_settings.rerank_candidate_k,
        history_cache=current_history_cache,
    )
    authenticate = create_auth_dependency(current_settings.api_token.get_secret_value())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """管理数据库、Redis 和模型客户端的应用级生命周期。"""
        if current_settings.database_auto_create:
            await current_database.create_schema()
        try:
            yield
        finally:
            # 共享 Provider 只关闭一次；独立意图 Provider 才需要额外关闭。
            if isinstance(provider, OpenAICompatibleProvider):
                await provider.aclose()
            if (
                    current_intent_provider is not provider
                    and isinstance(current_intent_provider, OpenAICompatibleProvider)
            ):
                await current_intent_provider.aclose()
            if redis_cache is not None:
                await redis_cache.aclose()
            if current_vector_store is not None:
                await current_vector_store.aclose()
            await current_database.dispose()

    application = FastAPI(
        title=current_settings.app_name,
        version=current_settings.app_version,
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(
        create_api_router(
            chat_service,
            conversation_service,
            knowledge_service,
            knowledge_indexing_service,
            knowledge_retrieval_service,
            dictionary_service,
            authenticate,
        )
    )
    # 页面和后续路由复用同一个混合分类器，不在请求中重复创建规则或模型客户端。
    application.state.usage_recorder = recorder
    application.state.database = current_database
    application.state.conversation_service = conversation_service
    application.state.intent_classifier = intent_classifier
    application.state.knowledge_service = knowledge_service
    application.state.knowledge_indexing_service = knowledge_indexing_service
    application.state.knowledge_retrieval_service = knowledge_retrieval_service
    application.state.dictionary_service = dictionary_service
    application.state.policy_retrieval_service = policy_retrieval_service

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            service=current_settings.app_name,
            version=current_settings.app_version,
        )

    @application.get("/ready", response_model=ReadinessResponse)
    async def ready() -> ReadinessResponse:
        try:
            await current_database.ping()
        except (SQLAlchemyError, RuntimeError) as exc:
            # MySQL 驱动缺少认证依赖等初始化错误也必须表现为“未就绪”，而不是 500。
            raise ServiceNotReadyError() from exc
        checks: dict[str, Literal["ready", "degraded"]] = {
            "configuration": "ready",
            "database": "ready",
            "llm_provider": "ready",
        }
        if redis_cache is not None:
            try:
                await redis_cache.ping()
                checks["redis"] = "ready"
            except RedisError as exc:
                if current_settings.redis_required:
                    raise ServiceNotReadyError() from exc
                checks["redis"] = "degraded"
        if current_vector_store is not None:
            try:
                await current_vector_store.ping()
                checks["milvus"] = "ready"
            except Exception as exc:
                if current_settings.milvus_required:
                    raise ServiceNotReadyError() from exc
                checks["milvus"] = "degraded"
        return ReadinessResponse(
            service=current_settings.app_name,
            version=current_settings.app_version,
            checks=checks,
        )

    return application


_settings = get_settings()
app = create_app(_settings)
if _settings.ui_enabled:
    # UI 只是调用已经装配好的服务，不直接读取 Key 或构造 Provider。
    register_support_ui(
        app,
        service=app.state.conversation_service,
        intent_classifier=app.state.intent_classifier,
        knowledge_service=app.state.knowledge_service,
        dictionary_service=app.state.dictionary_service,
        expected_token=_settings.api_token.get_secret_value(),
        storage_secret=_settings.ui_storage_secret.get_secret_value(),
        prefill_demo_credentials=_settings.ui_prefill_demo_credentials,
        intent_provider_name=_settings.llm_provider.value,
        intent_model=_settings.llm_model,
    )
