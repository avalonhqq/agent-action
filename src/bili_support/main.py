"""Application entry point.

Configuration is loaded from bili_support.core.config.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from bili_support.llm.context import BoundedContextBuilder, StandaloneQueryRewriter
from bili_support.llm.factory import build_llm_provider
from bili_support.llm.openai_compatible import OpenAICompatibleProvider
from bili_support.llm.prompts import create_default_prompt_registry
from bili_support.llm.provider import LLMProvider
from bili_support.llm.service import ChatService
from bili_support.llm.usage import InMemoryUsageRecorder, UsageRecorder
from bili_support.schemas.system import HealthResponse, ReadinessResponse
from bili_support.services.conversations import ConversationService
from bili_support.ui import register_support_ui


def create_app(
    settings: Settings | None = None,
    *,
    llm_provider: LLMProvider | None = None,
    usage_recorder: UsageRecorder | None = None,
    database: Database | None = None,
    history_cache: ConversationHistoryCache | None = None,
) -> FastAPI:
    """Create an application using an explicitly supplied or cached configuration."""
    current_settings = settings or get_settings()
    configure_logging(current_settings.log_level)
    provider = llm_provider or build_llm_provider(current_settings)
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
    chat_service = ChatService(
        provider=provider,
        model=current_settings.llm_model,
        prompt_registry=create_default_prompt_registry(),
        usage_recorder=recorder,
        context_builder=BoundedContextBuilder(),
        rewriter=StandaloneQueryRewriter(),
        temperature=current_settings.llm_temperature,
        max_tokens=current_settings.llm_max_tokens,
        timeout_seconds=current_settings.llm_timeout_seconds,
    )
    conversation_service = ConversationService(
        current_database,
        chat_service,
        history_cache=current_history_cache,
    )
    authenticate = create_auth_dependency(current_settings.api_token.get_secret_value())

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if current_settings.database_auto_create:
            await current_database.create_schema()
        try:
            yield
        finally:
            if isinstance(provider, OpenAICompatibleProvider):
                await provider.aclose()
            if redis_cache is not None:
                await redis_cache.aclose()
            await current_database.dispose()

    application = FastAPI(
        title=current_settings.app_name,
        version=current_settings.app_version,
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(
        create_api_router(chat_service, conversation_service, authenticate)
    )
    application.state.usage_recorder = recorder
    application.state.database = current_database
    application.state.conversation_service = conversation_service

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
        except SQLAlchemyError as exc:
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
        return ReadinessResponse(
            service=current_settings.app_name,
            version=current_settings.app_version,
            checks=checks,
        )

    return application


_settings = get_settings()
app = create_app(_settings)
if _settings.ui_enabled:
    register_support_ui(
        app,
        service=app.state.conversation_service,
        expected_token=_settings.api_token.get_secret_value(),
        storage_secret=_settings.ui_storage_secret.get_secret_value(),
        prefill_demo_credentials=_settings.ui_prefill_demo_credentials,
    )
