"""Application entry point.

Configuration is loaded from bili_support.core.config.
"""

from fastapi import FastAPI

from bili_support.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application using an explicitly supplied or cached configuration."""
    current_settings = settings or get_settings()
    application = FastAPI(
        title=current_settings.app_name,
        version=current_settings.app_version,
    )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": current_settings.app_name,
            "version": current_settings.app_version,
        }

    return application


app = create_app()
