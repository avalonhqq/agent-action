"""Schemas for lightweight platform probes."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness response: the process can serve HTTP traffic."""

    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Readiness response for currently configured mandatory components."""

    status: Literal["ready"] = "ready"
    service: str
    version: str
    checks: dict[str, Literal["ready", "degraded"]]
