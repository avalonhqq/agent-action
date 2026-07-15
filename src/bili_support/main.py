"""Application entry point.

Configuration is loaded from bili_support.core.config.
"""

from fastapi import FastAPI

from bili_support.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }