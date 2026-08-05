"""9B运行期依赖：服务放Context，业务数据放State并进入Checkpoint。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict

from bili_support.core.exceptions import AppError
from bili_support.core.security import UserContext
from bili_support.intent.types import BusinessDomain, IntentAction, IntentEntity
from bili_support.knowledge.evidence import KnowledgeRetrievalTrace, build_knowledge_evidence
from bili_support.knowledge.retrieval import RetrievalMode
from bili_support.knowledge.retrieval_policy import RetrievalDecisionKind
from bili_support.llm.context import QueryRewriteResult, StandaloneQueryRewriter
from bili_support.llm.service import (
    ChatCompletionResult,
    ChatService,
    GroundedChatCompletionResult,
)
from bili_support.llm.types import ChatMessage
from bili_support.routing import (
    CustomerServiceRoutePlan,
    CustomerServiceRouter,
    CustomerServiceTarget,
)

if TYPE_CHECKING:
    from bili_support.services.policy_retrieval import PolicyRetrievalResult


class PolicyKnowledgeRetriever(Protocol):
    """Graph所需的策略检索最小接口，避免依赖整个services包。"""

    async def retrieve(
            self,
            *,
            actor: UserContext,
            question: str,
            history: tuple[ChatMessage, ...],
            domain: BusinessDomain,
            actions: tuple[IntentAction, ...],
            entities: tuple[IntentEntity, ...],
            mode: RetrievalMode,
    ) -> PolicyRetrievalResult: ...


class GraphKnowledgeExecution(BaseModel):
    """检索节点的结构化输出；可安全转换成Checkpoint中的JSON。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_plan: CustomerServiceRoutePlan
    evidence_context: str | None = None
    response_override: str | None = None


@dataclass(frozen=True, slots=True)
class CustomerServiceGraphContext:
    """Graph节点共享的真实服务依赖，不参与Checkpoint序列化。

    State只保存问题、路由、证据和回答；Context保存Router、Retriever和ChatService。
    这样恢复Checkpoint时可重新注入健康的连接池与模型客户端。
    """

    router: CustomerServiceRouter
    policy_retriever: PolicyKnowledgeRetriever
    chat: ChatService
    retrieval_mode: RetrievalMode
    query_rewriter: StandaloneQueryRewriter = field(
        default_factory=StandaloneQueryRewriter
    )
    # 只有真实持久化Checkpointer已启动时才允许interrupt，否则保持原确定性提示。
    interrupt_enabled: bool = False

    async def route(self, question: str) -> CustomerServiceRoutePlan:
        """调用现有HybridIntentClassifier及确定性路由策略。"""

        return await self.router.route(question)

    def rewrite(
        self,
        question: str,
        history: list[ChatMessage],
    ) -> QueryRewriteResult:
        """在意图识别前生成可审计的独立问题，解决短省略追问。"""

        return self.query_rewriter.rewrite(question, history)

    async def retrieve(
            self,
            *,
            actor: UserContext,
            question: str,
            history: list[ChatMessage],
            route_plan: CustomerServiceRoutePlan,
    ) -> GraphKnowledgeExecution:
        """按意图业务域执行真实Hybrid检索，并产生有界Parent证据。"""

        if route_plan.summary.target is not CustomerServiceTarget.KNOWLEDGE_RAG:
            return GraphKnowledgeExecution(route_plan=route_plan)
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
        decision = route_plan.intent_decision
        if decision is None:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=domains,
                error_code="missing_intent_decision",
                response="当前缺少可信意图信息，本次未生成无依据答案。",
            )

        results = []
        policy_results: list[PolicyRetrievalResult] = []
        try:
            for domain in domains:
                policy_result = await self.policy_retriever.retrieve(
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
                    mode=self.retrieval_mode,
                )
                policy_results.append(policy_result)
                results.append((domain, policy_result.view))
        except AppError as exc:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=domains,
                error_code=exc.code.value,
                response=(
                    "知识服务暂时不可用，本次没有根据不完整信息生成答案。请稍后重试。"
                ),
            )
        except Exception:
            return self._knowledge_fallback(
                route_plan=route_plan,
                domains=domains,
                error_code="knowledge_retrieval_failed",
                response=(
                    "知识服务暂时不可用，本次没有根据不完整信息生成答案。请稍后重试。"
                ),
            )

        bundle = build_knowledge_evidence(results=results, mode=self.retrieval_mode)
        selected = max(
            policy_results,
            key=lambda item: {
                RetrievalDecisionKind.ANSWER: 0,
                RetrievalDecisionKind.CLARIFY: 1,
                RetrievalDecisionKind.REFUSE: 2,
            }[item.quality.kind],
        )
        trace = bundle.trace.model_copy(
            update={"policy": selected.policy_trace, "coverage": selected.coverage}
        )
        updated_plan = route_plan.model_copy(
            update={"summary": route_plan.summary.model_copy(update={"retrieval": trace})}
        )
        if selected.quality.kind is RetrievalDecisionKind.REFUSE:
            return GraphKnowledgeExecution(
                route_plan=updated_plan,
                response_override=(
                    "当前知识库中没有找到足够依据，或现有依据相关性不足，暂时无法确认该问题。"
                ),
            )
        if selected.quality.kind is RetrievalDecisionKind.CLARIFY:
            return GraphKnowledgeExecution(
                route_plan=updated_plan,
                response_override=(
                        selected.quality.clarification_question
                        or "当前证据不完整，请补充更具体的信息。"
                ),
            )
        return GraphKnowledgeExecution(
            route_plan=updated_plan,
            evidence_context=bundle.context_json,
        )

    async def complete_general(
            self,
            *,
            request_id: str,
            question: str,
            history: list[ChatMessage],
    ) -> ChatCompletionResult:
        """执行现有普通回答模型链路。"""

        return await self.chat.complete(
            request_id=request_id,
            user_message=question,
            history=history,
        )

    async def generate_grounded(
            self,
            *,
            request_id: str,
            question: str,
            history: list[ChatMessage],
            evidence_context: str,
    ) -> GroundedChatCompletionResult:
        """只完成Grounded结构生成和引用白名单校验，NLI留给下一节点。"""

        return await self.chat.complete_grounded(
            request_id=request_id,
            user_message=question,
            history=history,
            evidence_context=evidence_context,
            verify_claims=False,
        )

    async def verify_grounded(
            self,
            *,
            result: GroundedChatCompletionResult,
            evidence_context: str,
    ) -> GroundedChatCompletionResult:
        """调用真实本地NLI校验生成结果，不进行第二次LLM改写。"""

        return await self.chat.verify_grounded_completion(
            result,
            evidence_context=evidence_context,
        )

    def _knowledge_fallback(
            self,
            *,
            route_plan: CustomerServiceRoutePlan,
            domains: tuple[BusinessDomain, ...],
            error_code: str,
            response: str,
    ) -> GraphKnowledgeExecution:
        """检索失败时输出安全Trace，禁止无证据自由回答。"""

        trace = KnowledgeRetrievalTrace(
            mode=self.retrieval_mode,
            business_domains=domains,
            child_hit_count=0,
            evidence_count=0,
            error_code=error_code,
        )
        updated_plan = route_plan.model_copy(
            update={"summary": route_plan.summary.model_copy(update={"retrieval": trace})}
        )
        return GraphKnowledgeExecution(
            route_plan=updated_plan,
            response_override=response,
        )
