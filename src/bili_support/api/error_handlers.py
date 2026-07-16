"""FastAPI boundary that converts failures into the public error contract."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from bili_support.core.exceptions import AppError, ErrorCode
from bili_support.core.logging import get_logger
from bili_support.core.request_context import REQUEST_ID_HEADER
from bili_support.schemas.common import ErrorDetail, ErrorResponse

logger = get_logger()


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))


def _response(error: ErrorDetail, request_id: str, status_code: int) -> JSONResponse:
    payload = ErrorResponse(error=error, request_id=request_id)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={REQUEST_ID_HEADER: request_id},
    )


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    """Return an expected application error without exposing internals."""
    if not isinstance(exc, AppError):
        raise TypeError("handle_app_error requires AppError")
    request_id = _request_id(request)
    logger.info("application_error", error_code=exc.code, status_code=exc.status_code)
    return _response(
        ErrorDetail(code=exc.code, message=exc.message, details=exc.details),
        request_id,
        exc.status_code,
    )


async def handle_validation_error(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Return validation locations and types, never the rejected input value."""
    if not isinstance(exc, RequestValidationError):
        raise TypeError("handle_validation_error requires RequestValidationError")
    issues: list[dict[str, object]] = []
    for error in exc.errors():
        issues.append(
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "type": error["type"],
            }
        )
    return _response(
        ErrorDetail(
            code=ErrorCode.VALIDATION_ERROR,
            message="请求参数校验失败",
            details={"issues": issues},
        ),
        _request_id(request),
        422,
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    """Log an unexpected exception and expose only a stable generic response."""
    request_id = _request_id(request)
    logger.error(
        "unhandled_exception",
        exception_type=type(exc).__name__,
        request_id=request_id,
    )
    return _response(
        ErrorDetail(code=ErrorCode.INTERNAL_ERROR, message="服务暂时不可用"),
        request_id,
        500,
    )


def register_exception_handlers(application: FastAPI) -> None:
    """Install all API-boundary exception mappings."""
    application.add_exception_handler(AppError, handle_app_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(Exception, handle_unexpected_error)
