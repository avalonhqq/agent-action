"""Minimal application entry point for Week 1.

Only the learning baseline is implemented. Business modules remain skeletons.
"""

from fastapi import FastAPI

app = FastAPI(title="BiliSupport AI", version="0.0.1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "bili-support-ai", "version": "0.0.1"}
