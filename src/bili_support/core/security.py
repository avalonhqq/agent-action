"""Week 3 demo authentication boundary, replaceable by enterprise SSO/JWT."""

import secrets
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bili_support.core.exceptions import UnauthorizedError


class UserContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    external_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    display_name: str = Field(min_length=1, max_length=100)


AuthDependency = Callable[..., Coroutine[Any, Any, UserContext]]


def create_auth_dependency(expected_token: str) -> AuthDependency:
    bearer = HTTPBearer(auto_error=False)

    async def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
        user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
        display_name: Annotated[str | None, Header(alias="X-User-Name")] = None,
    ) -> UserContext:
        supplied = credentials.credentials if credentials else ""
        return authenticate_user(expected_token, supplied, user_id, display_name)

    return authenticate


def authenticate_user(
    expected_token: str,
    supplied_token: str,
    user_id: str | None,
    display_name: str | None = None,
) -> UserContext:
    """Validate demo credentials for HTTP dependencies and the local UI."""
    if not supplied_token or not secrets.compare_digest(supplied_token, expected_token):
        raise UnauthorizedError()
    if user_id is None:
        raise UnauthorizedError("缺少用户标识")
    try:
        return UserContext(external_id=user_id, display_name=display_name or user_id)
    except ValidationError as exc:
        raise UnauthorizedError("用户标识格式无效") from exc
