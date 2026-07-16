"""Tests for framework-independent application exceptions."""

from bili_support.core.exceptions import (
    AppError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    ResourceNotFoundError,
)


def test_resource_not_found_error_has_stable_contract() -> None:
    error = ResourceNotFoundError(details={"resource_type": "video"})

    assert isinstance(error, AppError)
    assert error.code is ErrorCode.RESOURCE_NOT_FOUND
    assert error.status_code == 404
    assert error.details == {"resource_type": "video"}


def test_conflict_error_keeps_only_explicit_public_details() -> None:
    error = ConflictError(details={"operation": "refund", "state": "completed"})

    assert error.code is ErrorCode.CONFLICT
    assert error.status_code == 409
    assert error.details == {"operation": "refund", "state": "completed"}


def test_forbidden_error_is_readable() -> None:
    error = ForbiddenError()

    assert error.code is ErrorCode.FORBIDDEN
    assert error.status_code == 403
    assert str(error) == "无权执行此操作"
    assert "traceback" not in str(error).lower()
