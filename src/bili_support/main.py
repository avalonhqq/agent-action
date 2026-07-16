"""Application entry point.

Configuration is loaded from bili_support.core.config.
"""

from fastapi import FastAPI

from bili_support.api.error_handlers import register_exception_handlers
from bili_support.core.config import Settings, get_settings
from bili_support.core.logging import configure_logging
from bili_support.core.request_context import RequestContextMiddleware
from bili_support.schemas.system import HealthResponse, ReadinessResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application using an explicitly supplied or cached configuration."""
    current_settings = settings or get_settings()
    configure_logging(current_settings.log_level)
    application = FastAPI(
        title=current_settings.app_name,
        version=current_settings.app_version,
    )
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            service=current_settings.app_name,
            version=current_settings.app_version,
        )

    @application.get("/ready", response_model=ReadinessResponse)
    async def ready() -> ReadinessResponse:
        return ReadinessResponse(
            service=current_settings.app_name,
            version=current_settings.app_version,
            checks={"configuration": "ready"},
        )

    return application


app = create_app()
