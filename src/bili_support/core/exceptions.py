"""Framework-independent application errors with stable public error codes."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Machine-readable error codes that form part of the public API contract."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    CONFLICT = "CONFLICT"
    MODEL_BAD_RESPONSE = "MODEL_BAD_RESPONSE"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    SERVICE_NOT_READY = "SERVICE_NOT_READY"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """An expected application failure containing only client-safe information."""

    def __init__(
        self,
        *,
        code: ErrorCode,
        message: str,
        status_code: int,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class ResourceNotFoundError(AppError):
    """An expected lookup failure for a resource visible to the caller."""

    def __init__(
        self,
        message: str = "请求的资源不存在",
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message=message,
            status_code=404,
            details=details,
        )


class ConflictError(AppError):
    """A conflict with the current state, such as a duplicate operation."""

    def __init__(
        self,
        message: str = "请求与资源当前状态冲突",
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.CONFLICT,
            message=message,
            status_code=409,
            details=details,
        )


class ForbiddenError(AppError):
    """An authenticated caller is not allowed to perform the operation."""

    def __init__(
        self,
        message: str = "无权执行此操作",
        *,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=ErrorCode.FORBIDDEN,
            message=message,
            status_code=403,
            details=details,
        )


class UnauthorizedError(AppError):
    """Authentication credentials are missing or invalid."""

    def __init__(self, message: str = "身份凭证无效或缺失") -> None:
        super().__init__(
            code=ErrorCode.UNAUTHORIZED,
            message=message,
            status_code=401,
        )


class ServiceNotReadyError(AppError):
    """A mandatory dependency is not ready to serve traffic."""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.SERVICE_NOT_READY,
            message="服务依赖尚未就绪",
            status_code=503,
        )
