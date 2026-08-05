"""Transactional conversation use cases built on repositories and ChatService."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, replace
from time import perf_counter
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command, StateSnapshot
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.core.cache import ConversationHistoryCache, NullConversationHistoryCache
from bili_support.core.database import Database
from bili_support.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    ResourceNotFoundError,
)
from bili_support.core.security import UserContext
from bili_support.graph.context import CustomerServiceGraphContext
from bili_support.graph.state import (
    CustomerServiceGraphState,
    GraphRunStatus,
    create_week9b_graph_input,
)
from bili_support.graph.workflow import MAX_GRAPH_STEPS, Week9BGraph, build_week9b_graph
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.llm.service import ChatService
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    MessageRole,
    TokenUsage,
)
from bili_support.models.entities import Conversation, GraphReview, Message, ModelCall
from bili_support.repositories import (
    ConversationRepository,
    GraphReviewRepository,
    MessageRepository,
    ModelCallRepository,
    UserRepository,
)
from bili_support.routing import (
    CustomerServiceRoutePlan,
    CustomerServiceRouter,
    CustomerServiceStreamChunk,
)
from bili_support.schemas.conversations import (
    ConversationMessageResult,
    GraphExecutionStatus,
    GraphExecutionView,
    PendingGraphReviewView,
)
from bili_support.services.policy_retrieval import (
    PolicyAwareKnowledgeRetriever,
)
from bili_support.services.retrieval import KnowledgeRetrievalService


@dataclass(frozen=True, slots=True)
class _GraphExecutionOutcome:
    """9B Graph返回给事务层的完整、已验证响应契约。"""

    route_plan: CustomerServiceRoutePlan
    answer: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage
    prompt_version: str
    execution: GraphExecutionView


class ConversationService:
    """会话服务：创建会话、发送消息、流式回答，统一的事务性入口。

    依赖关系：Database（持久化）→ ChatService（LLM）→ CustomerServiceRouter（路由）
    → ConversationHistoryCache（Redis 缓存加速历史加载）。
    """

    def __init__(
        self,
        database: Database,
        chat_service: ChatService,
        router: CustomerServiceRouter,
        knowledge_retrieval_service: KnowledgeRetrievalService,
        policy_retrieval_service: PolicyAwareKnowledgeRetriever | None = None,
        customer_retrieval_mode: RetrievalMode = RetrievalMode.VECTOR,
        customer_rerank_enabled: bool = False,
        rerank_candidate_k: int = 10,
        history_cache: ConversationHistoryCache | None = None,
        review_admin_user_ids: str = "review-admin",
    ) -> None:
        if not 1 <= rerank_candidate_k <= 20:
            raise ValueError("rerank_candidate_k must be between 1 and 20")
        self._database = database
        self._chat = chat_service
        policy_retriever = policy_retrieval_service or PolicyAwareKnowledgeRetriever(
            knowledge_retrieval_service,
            customer_rerank_enabled=customer_rerank_enabled,
        )
        # 未提供缓存时使用空实现，避免到处判 None。
        self._history_cache = history_cache or NullConversationHistoryCache()
        self._graph_context = CustomerServiceGraphContext(
            router=router,
            policy_retriever=policy_retriever,
            chat=chat_service,
            retrieval_mode=customer_retrieval_mode,
        )
        self._graph: Week9BGraph = build_week9b_graph()
        self._review_admin_user_ids = frozenset(
            item.strip() for item in review_admin_user_ids.split(",") if item.strip()
        )

    @property
    def graph(self) -> Week9BGraph:
        """返回当前已编译Graph，供应用调试页与状态查询复用。"""

        return self._graph

    def configure_graph_checkpoint(
        self,
        checkpointer: BaseCheckpointSaver[str] | None,
    ) -> None:
        """应用启动探测成功后重新编译Graph；None表示明确关闭持久化。"""

        self._graph_context = replace(
            self._graph_context,
            interrupt_enabled=checkpointer is not None,
        )
        self._graph = build_week9b_graph(checkpointer=checkpointer)

    async def create(self, actor: UserContext, title: str) -> Conversation:
        """创建新会话。"""
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversation = await ConversationRepository(session).create(user.id, title)
            await session.refresh(conversation)
            await session.commit()
            return conversation

    async def list_conversations(self, actor: UserContext) -> list[Conversation]:
        """列出当前用户的所有会话。"""
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversations = await ConversationRepository(session).list_for_user(user.id)
            await session.commit()
            return conversations

    async def messages(self, actor: UserContext, thread_id: str) -> list[Message]:
        """获取指定会话的消息历史。"""
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversation = await self._owned_conversation(session, thread_id, user.id)
            messages = await MessageRepository(session).list_for_conversation(conversation.id)
            await session.commit()
            return messages

    async def list_pending_reviews(
        self,
        actor: UserContext,
    ) -> list[PendingGraphReviewView]:
        """列出待审核执行；只有配置的运营审核员可访问。"""

        self._require_reviewer(actor)
        async with self._database.session() as session:
            rows = await GraphReviewRepository(session).list_pending()
            return [PendingGraphReviewView.model_validate(item) for item in rows]

    async def execution(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        execution_request_id: str,
    ) -> GraphExecutionView:
        """读取安全Graph状态；会话所有者或审核员可查看。"""

        await self._authorize_execution_access(actor, thread_id)
        if not self._graph_context.interrupt_enabled:
            raise ResourceNotFoundError("Graph持久化未启用，无法查询历史执行")
        config = _graph_config(thread_id, execution_request_id, actor.external_id)
        snapshot = await self._graph.aget_state(config)
        if not snapshot.values:
            raise ResourceNotFoundError("Graph执行不存在或已过期")
        return _execution_view_from_snapshot(
            snapshot,
            thread_id=thread_id,
            request_id=execution_request_id,
        )

    async def resume_execution(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        execution_request_id: str,
        decision: str,
        note: str,
        request_id: str,
    ) -> ConversationMessageResult:
        """审核员原子领取任务，并用Command(resume=...)恢复原MongoDB Checkpoint。"""

        self._require_reviewer(actor)
        execution_id = _execution_id(thread_id, execution_request_id)
        async with self._database.session() as session:
            users = UserRepository(session)
            reviewer = await users.get_or_create(actor.external_id, actor.display_name)
            conversation = await ConversationRepository(session).get_by_thread_id(thread_id)
            if conversation is None:
                raise ResourceNotFoundError("会话不存在")
            reviews = GraphReviewRepository(session)
            review = await reviews.by_execution(execution_id)
            if review is None or review.conversation_id != conversation.id:
                raise ResourceNotFoundError("待审核Graph执行不存在")
            claimed = await reviews.claim(
                execution_id,
                reviewed_by_user_id=reviewer.id,
            )
            if claimed is None:
                raise ConflictError("该Graph执行已被其他审核员处理")
            await session.commit()

        started = perf_counter()
        config = _graph_config(thread_id, execution_request_id, actor.external_id)
        try:
            result = await self._graph.ainvoke(
                Command(
                    resume={
                        "decision": decision,
                        "note": note,
                        "reviewer_id": actor.external_id,
                    }
                ),
                config=config,
                context=self._graph_context,
            )
        except Exception:
            await self._release_review_claim(execution_id)
            raise

        if _first_interrupt_payload(result.get("__interrupt__", ())) is not None:
            await self._release_review_claim(execution_id)
            raise ConflictError("Graph恢复后再次中断，请刷新执行状态")
        state = cast(CustomerServiceGraphState, result)
        route_plan = _route_plan_from_state(state)
        snapshot = await self._graph.aget_state(config)
        execution = _execution_view_from_snapshot(
            snapshot,
            thread_id=thread_id,
            request_id=execution_request_id,
        )
        outcome = _GraphExecutionOutcome(
            route_plan=route_plan,
            answer=state["answer"],
            model=state["model"],
            finish_reason=FinishReason(state["finish_reason"]),
            usage=TokenUsage.model_validate(state["usage"]),
            prompt_version=state["prompt_version"],
            execution=execution,
        )
        await self._persist_resume_outcome(
            actor=actor,
            execution_id=execution_id,
            request_id=request_id,
            decision=decision,
            note=note,
            outcome=outcome,
            started=started,
        )
        return ConversationMessageResult(
            thread_id=thread_id,
            answer=outcome.answer,
            model=outcome.model,
            finish_reason=outcome.finish_reason,
            usage=outcome.usage,
            prompt_version=outcome.prompt_version,
            routing=outcome.route_plan.summary,
            execution=outcome.execution,
        )

    async def send(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
    ) -> ConversationMessageResult:
        """非流式发送消息：路由 → 生成回答 → 持久化 → 返回结果。

        流程：
        1. 保存用户消息到数据库并加载对话历史。
        2. 调用 CustomerServiceRouter 获取路由计划。
        3. 根据路由计划选择 LLM 生成回答或返回确定性回复。
        4. 持久化结果（消息 + ModelCall 记录）。
        5. 无论成功/失败/取消，都会写入 ModelCall 审计记录。
        """
        conversation_id, user_message_id, history = await self._save_user_message(
            actor=actor,
            thread_id=thread_id,
            content=content,
            request_id=request_id,
        )
        started = perf_counter()
        route_plan: CustomerServiceRoutePlan | None = None
        try:
            outcome = await self._run_graph(
                actor=actor,
                thread_id=thread_id,
                content=content,
                request_id=request_id,
                history=history,
            )
            route_plan = outcome.route_plan
            answer = outcome.answer
            model = outcome.model
            finish_reason = outcome.finish_reason
            usage = outcome.usage
            prompt_version = outcome.prompt_version
        except asyncio.CancelledError:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation=_routed_operation("complete", route_plan),
                status="cancelled",
                started=started,
                usage=None,
                error_code="cancelled",
                model=None,
                prompt_version=None,
            )
            raise
        except AppError as exc:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation=_routed_operation("complete", route_plan),
                status="error",
                started=started,
                usage=None,
                error_code=exc.code.value,
                model=None,
                prompt_version=None,
            )
            raise
        except Exception:
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation=_routed_operation("complete", route_plan),
                status="error",
                started=started,
                usage=None,
                error_code="INTERNAL_ERROR",
                model=None,
                prompt_version=None,
            )
            raise

        await self._persist_outcome(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            request_id=request_id,
            operation=_routed_operation("complete", route_plan),
            status="success",
            started=started,
            usage=usage,
            assistant_content=answer,
            model=model,
            prompt_version=prompt_version,
        )
        if outcome.execution.status is GraphExecutionStatus.INTERRUPTED:
            await self._ensure_pending_review(
                actor=actor,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                route_plan=outcome.route_plan,
                execution=outcome.execution,
            )
        if route_plan is None:
            raise AssertionError("successful response requires a route plan")
        return ConversationMessageResult(
            thread_id=thread_id,
            answer=answer,
            model=model,
            finish_reason=finish_reason,
            usage=usage,
            prompt_version=prompt_version,
            routing=route_plan.summary,
            execution=outcome.execution,
        )

    async def stream(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
    ) -> AsyncGenerator[CustomerServiceStreamChunk, None]:
        """流式发送消息：首帧返回路由摘要，后续帧返回增量文本。

        与 send() 的区别：
        - 首个 chunk 携带 routing，让前端尽早展示路由信息。
        - 后续 chunk 逐字输出增量文本。
        - 持久化在 finally 块中完成，确保即使流中断也写入审计记录。
        """
        conversation_id, user_message_id, history = await self._save_user_message(
            actor=actor,
            thread_id=thread_id,
            content=content,
            request_id=request_id,
        )
        started = perf_counter()
        answer_parts: list[str] = []
        usage: TokenUsage | None = None
        status = "cancelled"
        error_code: str | None = "stream_closed"
        route_plan: CustomerServiceRoutePlan | None = None
        model: str | None = None
        prompt_version: str | None = None
        try:
            # 9B统一执行Graph；SSE仍保持route→delta→completed协议。知识回答必须在
            # Grounded结构和NLI全部通过后才能一次性发布，因此不流出未经验证的Token。
            outcome = await self._run_graph(
                actor=actor,
                thread_id=thread_id,
                content=content,
                request_id=request_id,
                history=history,
            )
            route_plan = outcome.route_plan
            model = outcome.model
            prompt_version = outcome.prompt_version
            usage = outcome.usage
            if outcome.execution.status is GraphExecutionStatus.INTERRUPTED:
                await self._ensure_pending_review(
                    actor=actor,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    route_plan=outcome.route_plan,
                    execution=outcome.execution,
                )
            answer_parts.append(outcome.answer)
            yield CustomerServiceStreamChunk(
                routing=route_plan.summary,
                execution_status=outcome.execution.status.value,
                execution_id=outcome.execution.execution_id,
            )
            yield CustomerServiceStreamChunk(delta=outcome.answer)
            yield CustomerServiceStreamChunk(
                finish_reason=outcome.finish_reason,
                usage=usage,
            )
            status = "success"
            error_code = None
            return
        except asyncio.CancelledError:
            error_code = "cancelled"
            raise
        except AppError as exc:
            status = "error"
            error_code = exc.code.value
            raise
        except Exception:
            status = "error"
            error_code = "INTERNAL_ERROR"
            raise
        finally:
            # 无论流正常结束还是异常中断，都写入审计记录。
            await self._persist_outcome(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                request_id=request_id,
                operation=_routed_operation("stream", route_plan),
                status=status,
                started=started,
                usage=usage,
                error_code=error_code,
                assistant_content="".join(answer_parts) if status == "success" else None,
                model=model,
                prompt_version=prompt_version,
            )

    async def _run_graph(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
        history: list[ChatMessage],
    ) -> _GraphExecutionOutcome:
        """执行9C Graph；可能完成，也可能在真实interrupt处返回待审核状态。"""

        graph_input = create_week9b_graph_input(
            request_id=request_id,
            thread_id=thread_id,
            user_id=actor.external_id,
            display_name=actor.display_name,
            question=content,
            history=[item.model_dump(mode="json") for item in history],
        )
        # 每条消息是独立Graph执行单元；conversation_id保留业务会话语义，request_id
        # 防止多轮Reducer相互污染，也便于按请求恢复和审计。
        execution_id = f"{thread_id}:{request_id}"
        config = _graph_config(thread_id, request_id, actor.external_id)
        result = await self._graph.ainvoke(
            graph_input,
            config=config,
            context=self._graph_context,
        )
        raw_interrupts = result.get("__interrupt__", ())
        state = cast(CustomerServiceGraphState, result)
        route_payload = dict(state["route_plan"])
        route_payload["intent_decision"] = state.get("intent_decision")
        route_plan = CustomerServiceRoutePlan.model_validate(route_payload)
        interrupt_payload = _first_interrupt_payload(raw_interrupts)
        snapshot = (
            await self._graph.aget_state(config)
            if self._graph_context.interrupt_enabled
            else None
        )
        if interrupt_payload is not None:
            if snapshot is None:  # pragma: no cover - interrupt只会在持久化模式启用
                raise AssertionError("interrupt requires a persistent checkpointer")
            execution = GraphExecutionView(
                execution_id=execution_id,
                thread_id=thread_id,
                request_id=request_id,
                status=GraphExecutionStatus.INTERRUPTED,
                current_node=state.get("current_node", "classify_intent"),
                next_nodes=tuple(snapshot.next),
                visited_nodes=tuple(state.get("visited_nodes", ())),
                route_target=route_plan.summary.target.value,
                review_status="pending",
                interrupt=interrupt_payload,
            )
            return _GraphExecutionOutcome(
                route_plan=route_plan,
                answer="该请求已安全暂停，正在等待人工审核；审核前不会执行后续操作。",
                model="deterministic-workflow",
                finish_reason=FinishReason.STOP,
                usage=TokenUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                ),
                prompt_version="human_interrupt:v1",
                execution=execution,
            )
        execution = GraphExecutionView(
            execution_id=execution_id,
            thread_id=thread_id,
            request_id=request_id,
            status=GraphExecutionStatus.COMPLETED,
            current_node=state["current_node"],
            next_nodes=tuple(snapshot.next) if snapshot is not None else (),
            visited_nodes=tuple(state.get("visited_nodes", ())),
            route_target=route_plan.summary.target.value,
            review_status=state.get("review_status"),
            answer=state.get("answer"),
        )
        return _GraphExecutionOutcome(
            route_plan=route_plan,
            answer=state["answer"],
            model=state["model"],
            finish_reason=FinishReason(state["finish_reason"]),
            usage=TokenUsage.model_validate(state["usage"]),
            prompt_version=state["prompt_version"],
            execution=execution,
        )

    async def _ensure_pending_review(
        self,
        *,
        actor: UserContext,
        conversation_id: str,
        user_message_id: str,
        route_plan: CustomerServiceRoutePlan,
        execution: GraphExecutionView,
    ) -> None:
        """把MongoDB中断同步成MySQL运营任务，重复调用保持幂等。"""

        payload = execution.interrupt or {}
        # 原问题只保存在加密Checkpoint和既有消息表，审核表不再复制一份可能含PII的文本。
        audit_payload = {
            key: payload[key]
            for key in (
                "kind",
                "request_id",
                "conversation_thread_id",
                "target",
                "risk",
            )
            if key in payload
        }
        async with self._database.session() as session:
            users = UserRepository(session)
            requester = await users.get_or_create(actor.external_id, actor.display_name)
            reviews = GraphReviewRepository(session)
            if await reviews.by_execution(execution.execution_id) is None:
                reviews.add(
                    GraphReview(
                        execution_id=execution.execution_id,
                        conversation_id=conversation_id,
                        user_message_id=user_message_id,
                        requested_by_user_id=requester.id,
                        thread_id=execution.thread_id,
                        request_id=execution.request_id,
                        target=route_plan.summary.target.value,
                        reason=str(
                            payload.get("reason")
                            or route_plan.response_override
                            or "该请求需要人工审核。"
                        )[:500],
                        interrupt_payload=audit_payload,
                        status="pending",
                    )
                )
            await session.commit()

    async def _persist_resume_outcome(
        self,
        *,
        actor: UserContext,
        execution_id: str,
        request_id: str,
        decision: str,
        note: str,
        outcome: _GraphExecutionOutcome,
        started: float,
    ) -> None:
        """在同一MySQL事务中结束审核、写助手消息和ModelCall审计。"""

        async with self._database.session() as session:
            users = UserRepository(session)
            reviewer = await users.get_or_create(actor.external_id, actor.display_name)
            reviews = GraphReviewRepository(session)
            review = await reviews.by_execution(execution_id)
            if review is None or review.status != "processing":
                raise ConflictError("审核任务状态已变化")
            GraphReviewRepository.resolve(
                review,
                approved=decision == "approve",
                reviewed_by_user_id=reviewer.id,
                note=note,
            )
            assistant = MessageRepository(session).add(
                conversation_id=review.conversation_id,
                role=MessageRole.ASSISTANT.value,
                content=outcome.answer,
                request_id=request_id,
            )
            await session.flush()
            ModelCallRepository(session).add(
                ModelCall(
                    conversation_id=review.conversation_id,
                    user_message_id=review.user_message_id,
                    assistant_message_id=assistant.id,
                    request_id=request_id,
                    operation=f"resume:{outcome.route_plan.summary.target.value}",
                    model=outcome.model,
                    prompt_version=outcome.prompt_version,
                    status="success",
                    latency_ms=(perf_counter() - started) * 1000,
                    prompt_tokens=outcome.usage.prompt_tokens,
                    completion_tokens=outcome.usage.completion_tokens,
                    total_tokens=outcome.usage.total_tokens,
                    error_code=None,
                )
            )
            conversation_id = review.conversation_id
            await session.commit()
        cached = await self._cached_history_by_conversation(conversation_id)
        if cached is not None:
            thread_id, history, cache_hit = cached
            await self._store_history(
                thread_id,
                history
                if not cache_hit
                else [
                    *history,
                    ChatMessage(role=MessageRole.ASSISTANT, content=outcome.answer),
                ],
            )

    async def _release_review_claim(self, execution_id: str) -> None:
        """恢复失败时把processing任务退回pending，允许安全重试。"""

        async with self._database.session() as session:
            review = await GraphReviewRepository(session).by_execution(execution_id)
            if review is not None and review.status == "processing":
                GraphReviewRepository.release_claim(review)
                await session.commit()

    async def _authorize_execution_access(
        self,
        actor: UserContext,
        thread_id: str,
    ) -> None:
        """会话所有者可查看；运营审核员可以跨用户查看。"""

        async with self._database.session() as session:
            users = UserRepository(session)
            user = await users.get_or_create(actor.external_id, actor.display_name)
            if actor.external_id not in self._review_admin_user_ids:
                await self._owned_conversation(session, thread_id, user.id)
            elif await ConversationRepository(session).get_by_thread_id(thread_id) is None:
                raise ResourceNotFoundError("会话不存在")
            await session.commit()

    def _require_reviewer(self, actor: UserContext) -> None:
        """本地白名单RBAC；生产应由SSO/JWT角色映射替换。"""

        if actor.external_id not in self._review_admin_user_ids:
            raise ForbiddenError("只有客服审核员可以恢复Graph执行")

    async def _save_user_message(
        self,
        *,
        actor: UserContext,
        thread_id: str,
        content: str,
        request_id: str,
    ) -> tuple[str, str, list[ChatMessage]]:
        """保存用户消息并返回 (会话ID, 消息ID, 对话历史)。

        历史加载优先级：Redis 缓存 → 数据库。
        保存后同步更新 Redis 缓存。
        """
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            conversations = ConversationRepository(session)
            conversation = await self._owned_conversation(session, thread_id, user.id)
            messages = MessageRepository(session)
            # 优先从 Redis 缓存加载历史，减少数据库查询。
            cached_history = await self._cached_history(thread_id)
            previous = (
                await messages.list_for_conversation(conversation.id)
                if cached_history is None
                else []
            )
            user_message = messages.add(
                conversation_id=conversation.id,
                role=MessageRole.USER.value,
                content=content,
                request_id=request_id,
            )
            conversations.touch(conversation)
            await session.flush()
            await session.commit()
            history = cached_history or [
                ChatMessage(role=MessageRole(item.role), content=item.content) for item in previous
            ]
            # 更新缓存：追加当前用户消息。
            await self._store_history(
                thread_id,
                [*history, ChatMessage(role=MessageRole.USER, content=content)],
            )
            return conversation.id, user_message.id, history

    async def _persist_outcome(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        request_id: str,
        operation: str,
        status: str,
        started: float,
        usage: TokenUsage | None,
        error_code: str | None = None,
        assistant_content: str | None = None,
        model: str | None = None,
        prompt_version: str | None = None,
    ) -> None:
        """持久化本次请求的结果：助手消息 + ModelCall 审计记录。

        成功时写入助手消息和 model_call；失败时只写入 model_call（含错误码）。
        写入后同步更新 Redis 缓存中的对话历史。
        """
        async with self._database.session() as session:
            assistant_message_id = None
            if assistant_content:
                assistant_message = MessageRepository(session).add(
                    conversation_id=conversation_id,
                    role=MessageRole.ASSISTANT.value,
                    content=assistant_content,
                    request_id=request_id,
                )
                await session.flush()
                assistant_message_id = assistant_message.id
            ModelCallRepository(session).add(
                ModelCall(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    request_id=request_id,
                    operation=operation,
                    model=model or self._chat.model,
                    prompt_version=prompt_version or self._chat.prompt_version,
                    status=status,
                    latency_ms=(perf_counter() - started) * 1000,
                    prompt_tokens=usage.prompt_tokens if usage else None,
                    completion_tokens=usage.completion_tokens if usage else None,
                    total_tokens=usage.total_tokens if usage else None,
                    error_code=error_code,
                )
            )
            await session.commit()
        # 如果有助手回复，更新 Redis 缓存。
        if assistant_content:
            cached = await self._cached_history_by_conversation(conversation_id)
            if cached is not None:
                thread_id, history, cache_hit = cached
                await self._store_history(
                    thread_id,
                    history
                    if not cache_hit
                    else [
                        *history,
                        ChatMessage(
                            role=MessageRole.ASSISTANT,
                            content=assistant_content,
                        ),
                    ],
                )

    async def _cached_history(self, thread_id: str) -> list[ChatMessage] | None:
        """从 Redis 获取缓存对话历史，失败时静默返回 None。"""
        try:
            return await self._history_cache.get(thread_id)
        except RedisError:
            return None

    async def _store_history(self, thread_id: str, history: list[ChatMessage]) -> None:
        """将对话历史写入 Redis 缓存，失败时静默忽略。"""
        try:
            await self._history_cache.set(thread_id, history)
        except RedisError:
            return

    async def _cached_history_by_conversation(
        self, conversation_id: str
    ) -> tuple[str, list[ChatMessage], bool] | None:
        """通过 conversation_id 获取 (thread_id, 历史, 是否缓存命中)。

        缓存未命中时回退到数据库查询。
        """
        async with self._database.session() as session:
            conversation = await session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            history = await self._cached_history(conversation.thread_id)
            cache_hit = history is not None
            if history is None:
                messages = await MessageRepository(session).list_for_conversation(conversation_id)
                history = [
                    ChatMessage(role=MessageRole(item.role), content=item.content)
                    for item in messages
                ]
            return conversation.thread_id, history, cache_hit

    @staticmethod
    async def _owned_conversation(
        session: AsyncSession, thread_id: str, user_id: str
    ) -> Conversation:
        """校验会话归属，不匹配时抛出 ResourceNotFoundError。"""
        conversation = await ConversationRepository(session).get_for_user(thread_id, user_id)
        if conversation is None:
            raise ResourceNotFoundError("会话不存在")
        return conversation


def _routed_operation(
    base: str,
    route_plan: CustomerServiceRoutePlan | None,
) -> str:
    """生成 ModelCall 的 operation 标识：base:target 或 base:routing_error。"""
    if route_plan is None:
        return f"{base}:routing_error"
    return f"{base}:{route_plan.summary.target.value}"


def _execution_id(thread_id: str, request_id: str) -> str:
    return f"{thread_id}:{request_id}"


def _graph_config(
    thread_id: str,
    request_id: str,
    actor_external_id: str,
) -> RunnableConfig:
    """集中构造Checkpoint身份和可检索元数据。"""

    return {
        "recursion_limit": MAX_GRAPH_STEPS,
        "configurable": {"thread_id": _execution_id(thread_id, request_id)},
        "metadata": {
            "user_id": actor_external_id,
            "conversation_thread_id": thread_id,
            "request_id": request_id,
        },
    }


def _route_plan_from_state(state: CustomerServiceGraphState) -> CustomerServiceRoutePlan:
    payload = dict(state["route_plan"])
    payload["intent_decision"] = state.get("intent_decision")
    return CustomerServiceRoutePlan.model_validate(payload)


def _first_interrupt_payload(raw_interrupts: object) -> dict[str, object] | None:
    """兼容LangGraph Interrupt对象，并只公开字典型安全载荷。"""

    if not isinstance(raw_interrupts, (tuple, list)) or not raw_interrupts:
        return None
    value = getattr(raw_interrupts[0], "value", raw_interrupts[0])
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _snapshot_interrupt(snapshot: StateSnapshot) -> dict[str, object] | None:
    for task in snapshot.tasks:
        payload = _first_interrupt_payload(task.interrupts)
        if payload is not None:
            return payload
    return None


def _execution_view_from_snapshot(
    snapshot: StateSnapshot,
    *,
    thread_id: str,
    request_id: str,
) -> GraphExecutionView:
    state = cast(CustomerServiceGraphState, snapshot.values)
    payload = _snapshot_interrupt(snapshot)
    if payload is not None:
        status = GraphExecutionStatus.INTERRUPTED
    elif state.get("status") == GraphRunStatus.FAILED:
        status = GraphExecutionStatus.FAILED
    else:
        status = GraphExecutionStatus.COMPLETED
    route_payload = state.get("route_plan") or {}
    summary = route_payload.get("summary")
    route_target = summary.get("target") if isinstance(summary, dict) else None
    return GraphExecutionView(
        execution_id=_execution_id(thread_id, request_id),
        thread_id=thread_id,
        request_id=request_id,
        status=status,
        current_node=state.get("current_node", ""),
        next_nodes=tuple(snapshot.next),
        visited_nodes=tuple(state.get("visited_nodes", ())),
        route_target=str(route_target) if route_target is not None else None,
        review_status=("pending" if payload is not None else state.get("review_status")),
        interrupt=payload,
        answer=state.get("answer"),
    )
