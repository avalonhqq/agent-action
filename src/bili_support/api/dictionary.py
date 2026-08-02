"""领域词候选、审核、发布和部署制品管理API。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from bili_support.core.security import AuthDependency, UserContext
from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.dictionary import DictionaryTermStatus
from bili_support.schemas.common import ApiResponse
from bili_support.schemas.dictionary import (
    DictionaryArtifactView,
    DictionaryPublishRequest,
    DictionaryTermCreate,
    DictionaryTermReviewRequest,
    DictionaryTermView,
    DictionaryVersionView,
    MockDictionaryCandidatesRequest,
)
from bili_support.services.dictionary import KnowledgeDictionaryService


def create_dictionary_router(
    service: KnowledgeDictionaryService,
    authenticate: AuthDependency,
) -> APIRouter:
    """当前复用知识管理Token；生产环境应在网关追加运营角色权限。"""

    router = APIRouter(
        prefix="/api/v1/knowledge/dictionary",
        tags=["knowledge-dictionary"],
    )

    @router.post(
        "/terms",
        response_model=ApiResponse[DictionaryTermView],
        status_code=201,
    )
    async def create_candidate(
        payload: DictionaryTermCreate,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[DictionaryTermView]:
        return ApiResponse(
            data=await service.create_candidate(actor=actor, payload=payload),
            request_id=_request_id(request),
        )

    @router.post(
        "/candidates/mock",
        response_model=ApiResponse[list[DictionaryTermView]],
        status_code=201,
    )
    async def import_mock_candidates(
        payload: MockDictionaryCandidatesRequest,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[list[DictionaryTermView]]:
        return ApiResponse(
            data=await service.create_mock_candidates(actor=actor, payload=payload),
            request_id=_request_id(request),
        )

    @router.get(
        "/terms",
        response_model=ApiResponse[list[DictionaryTermView]],
    )
    async def list_terms(
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
        business_domain: Annotated[BusinessDomain | None, Query()] = None,
        status: Annotated[DictionaryTermStatus | None, Query()] = None,
    ) -> ApiResponse[list[DictionaryTermView]]:
        del actor
        return ApiResponse(
            data=await service.list_terms(
                business_domain=(
                    business_domain.value if business_domain is not None else None
                ),
                status=status,
            ),
            request_id=_request_id(request),
        )

    @router.post(
        "/terms/{term_id}/review",
        response_model=ApiResponse[DictionaryTermView],
    )
    async def review_term(
        term_id: str,
        payload: DictionaryTermReviewRequest,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[DictionaryTermView]:
        return ApiResponse(
            data=await service.review(
                actor=actor,
                term_id=term_id,
                approved=payload.approved,
                review_note=payload.review_note,
            ),
            request_id=_request_id(request),
        )

    @router.post(
        "/versions/publish",
        response_model=ApiResponse[DictionaryVersionView],
        status_code=201,
    )
    async def publish_version(
        payload: DictionaryPublishRequest,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[DictionaryVersionView]:
        return ApiResponse(
            data=await service.publish(
                actor=actor,
                release_note=payload.release_note,
            ),
            request_id=_request_id(request),
        )

    @router.get(
        "/versions",
        response_model=ApiResponse[list[DictionaryVersionView]],
    )
    async def list_versions(
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[list[DictionaryVersionView]]:
        del actor
        return ApiResponse(
            data=await service.list_versions(),
            request_id=_request_id(request),
        )

    @router.get(
        "/versions/active/artifact",
        response_model=ApiResponse[DictionaryArtifactView],
    )
    async def active_artifact(
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[DictionaryArtifactView]:
        del actor
        return ApiResponse(
            data=await service.active_artifact(),
            request_id=_request_id(request),
        )

    @router.get(
        "/versions/{version_id}/artifact",
        response_model=ApiResponse[DictionaryArtifactView],
    )
    async def version_artifact(
        version_id: str,
        request: Request,
        actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[DictionaryArtifactView]:
        del actor
        return ApiResponse(
            data=await service.artifact(version_id),
            request_id=_request_id(request),
        )

    return router


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))
