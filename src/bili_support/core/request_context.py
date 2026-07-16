"""ASGI request context, correlation identifiers, and access logging."""

from __future__ import annotations

import re
from time import perf_counter
from uuid import uuid4

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bili_support.core.logging import get_logger

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _new_request_id() -> str:
    return uuid4().hex


def _select_request_id(candidate: str | None) -> tuple[str, str]:
    if candidate and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate, "client"
    return _new_request_id(), "generated"


class RequestContextMiddleware:
    """Attach a safe request ID and emit one structured access-log event."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = get_logger()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id, request_id_source = _select_request_id(headers.get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started_at = perf_counter()
        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            self.logger.info(
                "http_request_completed",
                method=scope["method"],
                path=scope["path"],
                status_code=status_code,
                duration_ms=duration_ms,
                request_id=request_id,
                request_id_source=request_id_source,
            )
            structlog.contextvars.clear_contextvars()
