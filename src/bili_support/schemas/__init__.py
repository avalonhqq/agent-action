"""Public API schemas."""

from bili_support.schemas.common import ApiResponse, ErrorDetail, ErrorResponse
from bili_support.schemas.system import HealthResponse, ReadinessResponse

__all__ = [
    "ApiResponse",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "ReadinessResponse",
]
