"""Safe model-provider failures exposed to application boundaries."""

from bili_support.core.exceptions import AppError, ErrorCode


class LLMUnavailableError(AppError):
    """The configured model provider is temporarily unavailable."""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.MODEL_UNAVAILABLE,
            message="模型服务暂时不可用",
            status_code=503,
        )


class LLMResponseError(AppError):
    """The provider returned an unsupported or malformed response."""

    def __init__(self) -> None:
        super().__init__(
            code=ErrorCode.MODEL_BAD_RESPONSE,
            message="模型服务返回了无效响应",
            status_code=502,
        )
