"""需要鉴权的知识入库管理接口；HTTP 层只做输入转换和输出包装。"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile

from bili_support.core.security import AuthDependency, UserContext
from bili_support.intent.types import BusinessDomain
from bili_support.schemas.common import ApiResponse
from bili_support.schemas.knowledge import (
    KnowledgeDocumentView,
    KnowledgeIngestionView,
    KnowledgeVersionView,
)
from bili_support.services.knowledge import KnowledgeIngestionService


def create_knowledge_router(
        service: KnowledgeIngestionService,
        authenticate: AuthDependency,
) -> APIRouter:
    """通过依赖注入绑定 Service 和鉴权，路由本身不直接访问数据库。"""

    router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])

    @router.post(
        "/documents",
        response_model=ApiResponse[KnowledgeIngestionView],
        status_code=201,
    )
    async def upload_document(
            request: Request,
            actor: Annotated[UserContext, Depends(authenticate)],
            file: Annotated[UploadFile, File()],
            title: Annotated[str, Form(min_length=1, max_length=200)],
            business_domain: Annotated[BusinessDomain, Form()],
            access_scope: Annotated[str, Form()] = "public",
            document_id: Annotated[str | None, Form()] = None,
    ) -> ApiResponse[KnowledgeIngestionView]:
        # 只读取“上限 + 1”字节，避免恶意大文件先耗尽进程内存再被业务层拒绝。
        content = await file.read(service.max_file_bytes + 1)
        result = await service.upload(
            actor=actor,
            content=content,
            filename=file.filename or "unnamed",
            media_type=file.content_type or "application/octet-stream",
            title=title.strip(),
            business_domain=business_domain.value,
            access_scope=_access_scope(access_scope),
            # 不传表示按标题/领域寻找逻辑文档；传入则明确给指定文档新增版本。
            document_id=document_id,
        )
        return ApiResponse(data=result, request_id=_request_id(request))

    @router.get(
        "/documents",
        response_model=ApiResponse[list[KnowledgeDocumentView]],
    )
    async def list_documents(
            request: Request,
            actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[list[KnowledgeDocumentView]]:
        return ApiResponse(
            data=await service.list_documents(actor=actor),
            request_id=_request_id(request),
        )

    @router.get(
        "/documents/{document_id}/versions",
        response_model=ApiResponse[list[KnowledgeVersionView]],
    )
    async def list_versions(
            document_id: str,
            request: Request,
            actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[list[KnowledgeVersionView]]:
        return ApiResponse(
            data=await service.versions(actor=actor, document_id=document_id),
            request_id=_request_id(request),
        )

    @router.get(
        "/jobs/{job_id}",
        response_model=ApiResponse[KnowledgeIngestionView],
    )
    async def job_status(
            job_id: str,
            request: Request,
            actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[KnowledgeIngestionView]:
        return ApiResponse(
            data=await service.job(actor=actor, job_id=job_id),
            request_id=_request_id(request),
        )

    @router.post(
        "/jobs/{job_id}/retry",
        response_model=ApiResponse[KnowledgeIngestionView],
    )
    async def retry_job(
            job_id: str,
            request: Request,
            actor: Annotated[UserContext, Depends(authenticate)],
    ) -> ApiResponse[KnowledgeIngestionView]:
        return ApiResponse(
            data=await service.retry(actor=actor, job_id=job_id),
            request_id=_request_id(request),
        )

    @router.delete("/documents/{document_id}", status_code=204)
    async def delete_document(
            document_id: str,
            actor: Annotated[UserContext, Depends(authenticate)],
    ) -> Response:
        await service.delete(actor=actor, document_id=document_id)
        return Response(status_code=204)

    return router


def _access_scope(value: str) -> list[str]:
    """把逗号分隔权限标签去空、去重，并为缺省值回退到 public。"""

    normalized = list(
        dict.fromkeys(item.strip() for item in value.split(",") if item.strip())
    )
    return normalized or ["public"]


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unavailable"))
