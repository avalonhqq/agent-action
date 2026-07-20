"""SQLAlchemy repositories for the Week 3 conversation aggregate."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.models.entities import Conversation, Message, ModelCall, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(self, external_id: str, display_name: str) -> User:
        user = await self._session.scalar(select(User).where(User.external_id == external_id))
        if user is not None:
            if user.display_name != display_name:
                user.display_name = display_name
            return user
        user = User(external_id=external_id, display_name=display_name)
        self._session.add(user)
        await self._session.flush()
        return user


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, user_id: str, title: str) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def list_for_user(self, user_id: str) -> list[Conversation]:
        result = await self._session.scalars(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
        return list(result)

    async def get_for_user(self, thread_id: str, user_id: str) -> Conversation | None:
        result = await self._session.scalar(
            select(Conversation).where(
                Conversation.thread_id == thread_id,
                Conversation.user_id == user_id,
            )
        )
        return result

    def touch(self, conversation: Conversation) -> None:
        conversation.updated_at = datetime.now(UTC)


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_conversation(self, conversation_id: str) -> list[Message]:
        result = await self._session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(result)

    def add(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        request_id: str,
    ) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            request_id=request_id,
        )
        self._session.add(message)
        return message


class ModelCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, call: ModelCall) -> None:
        self._session.add(call)
