"""Transactional conversation use cases built on repositories and ChatService."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from time import perf_counter

from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from bili_support.core.cache import ConversationHistoryCache, NullConversationHistoryCache
from bili_support.core.database import Database
from bili_support.core.exceptions import AppError, ResourceNotFoundError
from bili_support.core.security import UserContext
from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.evidence import (
    KnowledgeRetrievalTrace,
    build_knowledge_evidence,
)
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.retrieval_policy import RetrievalDecisionKind
from bili_support.llm.service import ChatService
from bili_support.llm.types import (
    ChatMessage,
    FinishReason,
    MessageRole,
    TokenUsage,
)
from bili_support.models.entities import Conversation, Message, ModelCall
from bili_support.repositories import (
    ConversationRepository,
    MessageRepository,
    ModelCallRepository,
    UserRepository,
)
from bili_support.routing import (
    CustomerServiceRoutePlan,
    CustomerServiceRouter,
    CustomerServiceStreamChunk,
    CustomerServiceTarget,
)
from bili_support.schemas.conversations import ConversationMessageResult
from bili_support.services.policy_retrieval import (
    PolicyAwareKnowledgeRetriever,
    PolicyRetrievalResult,
)
from bili_support.services.retrieval import KnowledgeRetrievalService


@dataclass(frozen=True, slots=True)
class _KnowledgeExecution:
    """一次路由完成后的知识执行准备；非知识路由保持三个默认值。"""

    route_plan: CustomerServiceRoutePlan
    evidence_context: str | None = None
    response_override: str | None = None


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
    ) -> None:
        if not 1 <= rerank_candidate_k <= 20:
            raise ValueError("rerank_candidate_k must be between 1 and 20")
        self._database = database
        self._chat = chat_service
        self._router = router
        self._customer_retrieval_mode = customer_retrieval_mode
        self._policy_retrieval = (
            policy_retrieval_service
            or PolicyAwareKnowledgeRetriever(
                knowledge_retrieval_service,
                customer_rerank_enabled=customer_rerank_enabled,
            )
        )
        # 未提供缓存时使用空实现，避免到处判 None。
        self._history_cache = history_cache or NullConversationHistoryCache()

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
            route_plan = await self._router.route(content)
            execution = await self._prepare_knowledge_execution(
                actor=actor,
                question=content,
                history=history,
                route_plan=route_plan,
            )
            route_plan = execution.route_plan
            if execution.response_override is not None:
                answer = execution.response_override
                model = "deterministic-knowledge"
                finish_reason = FinishReason.STOP
                usage = TokenUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                )
                prompt_version = "knowledge_retrieval:v1"
            elif route_plan.use_chat_model:
                # LLM 路径：调用 ChatService 生成回答。
                result = await self._chat.complete(
                    request_id=request_id,
                    user_message=content,
                    history=history,
                    evidence_context=execution.evidence_context,
                )
                answer = result.response.content
                model = result.response.model
                finish_reason = result.response.finish_reason
                usage = result.response.usage
                prompt_version = result.prompt_version
            else:
                # 确定性路径：路由直接返回固定回复（安全拦截/澄清/转人工等）。
                answer = _required_override(route_plan)
                model = "deterministic-routing"
                finish_reason = FinishReason.STOP
                usage = TokenUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                )
                prompt_version = "customer_service_router:v1"
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
            route_plan = await self._router.route(content)
            execution = await self._prepare_knowledge_execution(
                actor=actor,
                question=content,
                history=history,
                route_plan=route_plan,
            )
            route_plan = execution.route_plan
            yield CustomerServiceStreamChunk(routing=route_plan.summary)
            if execution.response_override is not None:
                response = execution.response_override
                model = "deterministic-knowledge"
                prompt_version = "knowledge_retrieval:v1"
                usage = TokenUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                )
                answer_parts.append(response)
                yield CustomerServiceStreamChunk(delta=response)
                yield CustomerServiceStreamChunk(
                    finish_reason=FinishReason.STOP,
                    usage=usage,
                )
            elif route_plan.use_chat_model:
                # LLM 流式路径。
                model = self._chat.model
                prompt_version = (
                    self._chat.grounded_prompt_version
                    if execution.evidence_context is not None
                    else self._chat.prompt_version
                )
                async for chunk in self._chat.stream(
                        request_id=request_id,
                        user_message=content,
                        history=history,
                        evidence_context=execution.evidence_context,
                ):
                    if chunk.delta:
                        answer_parts.append(chunk.delta)
                    usage = chunk.usage or usage
                    yield CustomerServiceStreamChunk(
                        delta=chunk.delta,
                        finish_reason=chunk.finish_reason,
                        usage=chunk.usage,
                    )
            else:
                # 确定性流式路径：一次性返回固定回复。
                response = _required_override(route_plan)
                model = "deterministic-routing"
                prompt_version = "customer_service_router:v1"
                usage = TokenUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                )
                answer_parts.append(response)
                yield CustomerServiceStreamChunk(delta=response)
                yield CustomerServiceStreamChunk(
                    finish_reason=FinishReason.STOP,
                    usage=usage,
                )
            status = "success"
            error_code = None
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

    async def _prepare_knowledge_execution(
        self,
        *,
        actor: UserContext,
        question: str,
        history: list[ChatMessage],
        route_plan: CustomerServiceRoutePlan,
    ) -> _KnowledgeExecution:
        """知识路由先取可信Parent；无证据或依赖故障时禁止自由模型回答。"""

        if route_plan.summary.target is not CustomerServiceTarget.KNOWLEDGE_RAG:
            return _KnowledgeExecution(route_plan=route_plan)
        domains = route_plan.summary.business_domains
        if not domains:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=(),
                error_code="missing_business_domain",
                response=(
                    "当前无法确定需要查询的知识领域，本次未生成无依据答案。"
                    "请补充你要咨询的具体业务。"
                ),
            )

        results = []
        policy_results: list[PolicyRetrievalResult] = []
        decision = route_plan.intent_decision
        if decision is None:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=domains,
                error_code="missing_intent_decision",
                response="当前缺少可信意图信息，本次未生成无依据答案。",
            )
        try:
            for domain in domains:
                policy_result = await self._policy_retrieval.retrieve(
                    actor=actor,
                    question=question,
                    domain=domain,
                    actions=tuple(
                        item.action
                        for item in decision.intents
                        if item.domain is domain
                    ),
                    entities=decision.entities,
                    history=tuple(history[-20:]),
                    mode=self._customer_retrieval_mode,
                )
                policy_results.append(policy_result)
                results.append((domain, policy_result.view))
        except AppError as exc:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=domains,
                error_code=exc.code.value,
                response=(
                    "知识服务暂时不可用，本次没有根据不完整信息生成答案。"
                    "请稍后重试。"
                ),
            )
        except Exception:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=domains,
                error_code="knowledge_retrieval_failed",
                response=(
                    "知识服务暂时不可用，本次没有根据不完整信息生成答案。"
                    "请稍后重试。"
                ),
            )

        bundle = build_knowledge_evidence(
            results=results,
            mode=self._customer_retrieval_mode,
        )
        selected_policy_result = max(
            policy_results,
            key=lambda item: {
                RetrievalDecisionKind.ANSWER: 0,
                RetrievalDecisionKind.CLARIFY: 1,
                RetrievalDecisionKind.REFUSE: 2,
            }[item.quality.kind],
        )
        trace = bundle.trace.model_copy(
            update={
                "policy": selected_policy_result.policy_trace,
                "coverage": selected_policy_result.coverage,
            }
        )
        updated_plan = route_plan.model_copy(
            update={
                "summary": route_plan.summary.model_copy(
                    update={"retrieval": trace}
                )
            }
        )
        if selected_policy_result.quality.kind is RetrievalDecisionKind.REFUSE:
            return _KnowledgeExecution(
                route_plan=updated_plan,
                response_override=(
                    "当前知识库中没有找到足够依据，或现有依据相关性不足，"
                    "暂时无法确认该问题。"
                ),
            )
        if selected_policy_result.quality.kind is RetrievalDecisionKind.CLARIFY:
            return _KnowledgeExecution(
                route_plan=updated_plan,
                response_override=(
                    selected_policy_result.quality.clarification_question
                    or "当前证据不完整，请补充更具体的信息。"
                ),
            )
        return _KnowledgeExecution(
            route_plan=updated_plan,
            evidence_context=bundle.context_json,
        )

    def _knowledge_fallback(
        self,
        *,
        route_plan: CustomerServiceRoutePlan,
        domains: tuple[BusinessDomain, ...],
        error_code: str,
        response: str,
    ) -> _KnowledgeExecution:
        """把检索错误压缩成安全Trace，不泄露Provider异常或数据库细节。"""

        trace = KnowledgeRetrievalTrace(
            mode=self._customer_retrieval_mode,
            business_domains=domains,
            child_hit_count=0,
            evidence_count=0,
            error_code=error_code,
        )
        updated_plan = route_plan.model_copy(
            update={
                "summary": route_plan.summary.model_copy(
                    update={"retrieval": trace}
                )
            }
        )
        return _KnowledgeExecution(
            route_plan=updated_plan,
            response_override=response,
        )

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

    async def _store_history(
            self, thread_id: str, history: list[ChatMessage]
    ) -> None:
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
                messages = await MessageRepository(session).list_for_conversation(
                    conversation_id
                )
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


def _required_override(route_plan: CustomerServiceRoutePlan) -> str:
    """提取确定性路由的固定回复文本，为 None 时说明路由配置错误。"""
    response = route_plan.response_override
    if response is None:
        raise AssertionError("deterministic route requires response_override")
    return response


def _routed_operation(
        base: str,
        route_plan: CustomerServiceRoutePlan | None,
) -> str:
    """生成 ModelCall 的 operation 标识：base:target 或 base:routing_error。"""
    if route_plan is None:
        return f"{base}:routing_error"
    return f"{base}:{route_plan.summary.target.value}"
