"""Aggregation boundary for application API routers."""

from fastapi import APIRouter

from bili_support.api.chat import create_chat_router
from bili_support.api.conversations import create_conversation_router
from bili_support.core.security import AuthDependency
from bili_support.llm.service import ChatService
from bili_support.services.conversations import ConversationService


def create_api_router(
    chat_service: ChatService,
    conversation_service: ConversationService,
    authenticate: AuthDependency,
) -> APIRouter:
    router = APIRouter()
    router.include_router(create_chat_router(chat_service))
    router.include_router(create_conversation_router(conversation_service, authenticate))
    return router
