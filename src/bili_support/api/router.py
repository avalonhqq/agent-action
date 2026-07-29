"""Aggregation boundary for application API routers."""

from fastapi import APIRouter

from bili_support.api.chat import create_chat_router
from bili_support.api.conversations import create_conversation_router
from bili_support.api.knowledge import create_knowledge_router
from bili_support.core.security import AuthDependency
from bili_support.llm.service import ChatService
from bili_support.services.conversations import ConversationService
from bili_support.services.indexing import KnowledgeIndexingService
from bili_support.services.knowledge import KnowledgeIngestionService
from bili_support.services.retrieval import KnowledgeRetrievalService


def create_api_router(
    chat_service: ChatService,
    conversation_service: ConversationService,
    knowledge_service: KnowledgeIngestionService,
    knowledge_indexing_service: KnowledgeIndexingService,
    knowledge_retrieval_service: KnowledgeRetrievalService,
    authenticate: AuthDependency,
) -> APIRouter:
    router = APIRouter()
    router.include_router(create_chat_router(chat_service))
    router.include_router(create_conversation_router(conversation_service, authenticate))
    router.include_router(
        create_knowledge_router(
            knowledge_service,
            knowledge_indexing_service,
            knowledge_retrieval_service,
            authenticate,
        )
    )
    return router
