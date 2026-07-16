"""Stable response envelopes used by business-facing API endpoints."""

from typing import Literal

from pydantic import BaseModel, Field

from bili_support.core.exceptions import ErrorCode


class ApiResponse[T](BaseModel):
    """A typed successful API response."""

    success: Literal[True] = True
    data: T
    request_id: str = Field(min_length=1)


class ErrorDetail(BaseModel):
    """A safe, machine-readable error description."""

    code: ErrorCode
    message: str = Field(min_length=1)
    details: dict[str, object] | None = None


class ErrorResponse(BaseModel):
    """A failed API response without internal exception information."""

    success: Literal[False] = False
    error: ErrorDetail
    request_id: str = Field(min_length=1)
