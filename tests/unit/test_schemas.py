"""Tests for stable, typed API response contracts."""

import pytest
from pydantic import BaseModel, ValidationError

from bili_support.core.exceptions import ErrorCode
from bili_support.schemas.common import ApiResponse, ErrorDetail, ErrorResponse


class VideoSummary(BaseModel):
    bvid: str
    title: str


def test_typed_success_response_serializes_nested_model() -> None:
    response = ApiResponse[VideoSummary](
        data=VideoSummary(bvid="BV1xx411c7mD", title="测试视频"),
        request_id="request-1",
    )

    assert response.model_dump() == {
        "success": True,
        "data": {"bvid": "BV1xx411c7mD", "title": "测试视频"},
        "request_id": "request-1",
    }


def test_success_response_rejects_false_discriminator() -> None:
    with pytest.raises(ValidationError):
        ApiResponse[VideoSummary](
            success=False,  # type: ignore[arg-type]
            data=VideoSummary(bvid="BV1xx411c7mD", title="测试视频"),
            request_id="request-1",
        )


def test_error_response_serializes_stable_contract() -> None:
    response = ErrorResponse(
        error=ErrorDetail(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message="请求的资源不存在",
        ),
        request_id="request-2",
    )

    assert response.model_dump(mode="json") == {
        "success": False,
        "error": {
            "code": "RESOURCE_NOT_FOUND",
            "message": "请求的资源不存在",
            "details": None,
        },
        "request_id": "request-2",
    }


def test_error_response_rejects_true_discriminator() -> None:
    with pytest.raises(ValidationError):
        ErrorResponse(
            success=True,  # type: ignore[arg-type]
            error=ErrorDetail(code=ErrorCode.CONFLICT, message="状态冲突"),
            request_id="request-3",
        )
