"""第9周9A：可真实编译、异步执行且有限步的最小LangGraph。"""

from __future__ import annotations

from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from bili_support.conversation_context import (
    ContextResolutionKind,
    ConversationContextState,
    advance_conversation_context,
)
from bili_support.core.exceptions import AppError
from bili_support.core.security import UserContext
from bili_support.graph.answer_policy import (
    attach_grounding_trace,
    publish_grounded_answer,
)
from bili_support.graph.context import CustomerServiceGraphContext
from bili_support.graph.routing import route_after_input_validation
from bili_support.graph.state import (
    CustomerServiceGraphState,
    GraphErrorCode,
    GraphInputStatus,
    GraphNextAction,
    GraphRunStatus,
    GraphStateUpdate,
)
from bili_support.intent.types import IntentDecision
from bili_support.llm.service import GroundedChatCompletionResult
from bili_support.llm.types import ChatMessage, FinishReason, TokenUsage
from bili_support.routing import (
    CustomerServiceRoutePlan,
    CustomerServiceRouteSummary,
    CustomerServiceTarget,
)

MAX_QUESTION_CHARS = 2000
# 完整知识问答链路包含初始化、输入校验、上下文解析、意图识别、检索、
# 回答生成、声明校验与收尾。这里留出少量余量，避免正常路径触碰递归上限。
MAX_GRAPH_STEPS = 12

Week9AGraph = CompiledStateGraph[
    CustomerServiceGraphState,
    None,
    CustomerServiceGraphState,
    CustomerServiceGraphState,
]

Week9BGraph = CompiledStateGraph[
    CustomerServiceGraphState,
    CustomerServiceGraphContext,
    CustomerServiceGraphState,
    CustomerServiceGraphState,
]


async def initialize_node(
    state: CustomerServiceGraphState,
) -> GraphStateUpdate:
    """初始化运行期字段；9A不调用模型、检索、数据库或伪造客服回答。"""

    del state
    return GraphStateUpdate(
        status=GraphRunStatus.RUNNING,
        input_status=GraphInputStatus.UNKNOWN,
        current_node="initialize",
        visited_nodes=["initialize"],
        step_count=1,
    )


async def validate_input_node(
    state: CustomerServiceGraphState,
) -> GraphStateUpdate:
    """校验空白、长度与业务步数；失败只返回稳定原因码。"""

    normalized_question = state["question"].strip()
    common = GraphStateUpdate(
        current_node="validate_input",
        visited_nodes=["validate_input"],
        step_count=1,
        normalized_question=normalized_question,
    )
    if state["step_count"] >= MAX_GRAPH_STEPS:
        common["input_status"] = GraphInputStatus.INVALID
        common["error_code"] = GraphErrorCode.STEP_LIMIT_EXCEEDED
    elif not normalized_question:
        common["input_status"] = GraphInputStatus.INVALID
        common["error_code"] = GraphErrorCode.EMPTY_QUESTION
    elif len(normalized_question) > MAX_QUESTION_CHARS:
        common["input_status"] = GraphInputStatus.INVALID
        common["error_code"] = GraphErrorCode.QUESTION_TOO_LONG
    else:
        common["input_status"] = GraphInputStatus.VALID
    return common


async def complete_node(
    state: CustomerServiceGraphState,
) -> GraphStateUpdate:
    """完成9A输入阶段，并声明9B应进入真实Intent节点。"""

    del state
    return GraphStateUpdate(
        status=GraphRunStatus.COMPLETED,
        next_action=GraphNextAction.INTENT,
        current_node="complete",
        visited_nodes=["complete"],
        step_count=1,
    )


async def fail_node(
    state: CustomerServiceGraphState,
) -> GraphStateUpdate:
    """输入不合法时确定性结束，不触发任何高成本或有副作用能力。"""

    del state
    return GraphStateUpdate(
        status=GraphRunStatus.FAILED,
        next_action=GraphNextAction.STOP,
        current_node="fail",
        visited_nodes=["fail"],
        step_count=1,
    )


async def classify_intent_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """调用真实HybridIntent与确定性CustomerServiceRouter。"""

    question = _effective_question(state)
    plan = await runtime.context.route(question)
    decision = plan.intent_decision
    resolution = state["context_resolution"]
    next_context = advance_conversation_context(
        ConversationContextState.model_validate(state["conversation_context"]),
        decision=decision,
        standalone_query=question,
        reset_context=bool(resolution.get("reset_context", False)),
    )
    return GraphStateUpdate(
        route_plan=plan.model_dump(mode="json"),
        intent_decision=(decision.model_dump(mode="json") if decision else None),
        next_conversation_context=next_context.model_dump(mode="json"),
        current_node="classify_intent",
        visited_nodes=["classify_intent"],
        step_count=1,
    )


async def resolve_context_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """在Intent前解析跨轮主题；歧义时直接生成确定性澄清计划。"""

    resolution = await runtime.context.resolve_context(
        state["normalized_question"],
        _history(state),
        ConversationContextState.model_validate(state["conversation_context"]),
    )
    update = GraphStateUpdate(
        context_resolution=resolution.model_dump(mode="json"),
        current_node="resolve_context",
        visited_nodes=["resolve_context"],
        step_count=1,
    )
    if resolution.standalone_query is not None:
        update["standalone_question"] = resolution.standalone_query
        update["query_rewrite"] = {
            "original_query": resolution.original_query,
            "standalone_query": resolution.standalone_query,
            "rewritten": resolution.kind is ContextResolutionKind.RESOLVED,
            "reason": resolution.kind.value,
        }
        return update
    plan = CustomerServiceRoutePlan(
        summary=CustomerServiceRouteSummary(
            target=CustomerServiceTarget.CLARIFICATION,
            mocked_downstream=False,
            needs_clarification=True,
        ),
        use_chat_model=False,
        response_override=resolution.clarification_question,
    )
    update["route_plan"] = plan.model_dump(mode="json")
    update["intent_decision"] = None
    update["response_override"] = resolution.clarification_question or "请补充具体主题。"
    update["next_conversation_context"] = state["conversation_context"]
    return update


def route_after_context_resolution(state: CustomerServiceGraphState) -> str:
    """上下文不唯一时禁止猜测，直接进入确定性澄清。"""

    return (
        "deterministic_response"
        if state["context_resolution"].get("kind") == ContextResolutionKind.AMBIGUOUS.value
        else "classify_intent"
    )


def route_after_intent(state: CustomerServiceGraphState) -> str:
    """模型只产出类型化决策；条件边依据RouteTarget确定性选路。"""

    target = _route_plan(state).summary.target
    if target is CustomerServiceTarget.KNOWLEDGE_RAG:
        return "retrieve_knowledge"
    if target is CustomerServiceTarget.GENERAL_CHAT:
        return "general_chat"
    if target in {
        CustomerServiceTarget.HUMAN_REVIEW_MOCK,
        CustomerServiceTarget.HUMAN_SERVICE_MOCK,
    }:
        return "human_review"
    return "deterministic_response"


class HumanReviewResume(BaseModel):
    """恢复命令的严格契约，拒绝任意字段进入Graph状态。"""

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(approve|reject)$")
    note: str = Field(min_length=1, max_length=500)
    reviewer_id: str = Field(min_length=1, max_length=64)


async def human_review_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """在高风险/人工路由处暂停；恢复命令到达后才继续执行。"""

    plan = _route_plan(state)
    if not runtime.context.interrupt_enabled:
        # 测试或显式关闭Checkpoint时不能伪造可恢复能力，保持原路由固定提示。
        return GraphStateUpdate(
            response_override=plan.response_override or "当前人工服务暂不可用。",
            review_status="disabled",
            current_node="human_review",
            visited_nodes=["human_review"],
            step_count=1,
        )

    resume_payload = interrupt(
        {
            "kind": "human_review",
            "request_id": state["request_id"],
            "conversation_thread_id": state["thread_id"],
            "target": plan.summary.target.value,
            "risk": plan.summary.risk.value if plan.summary.risk is not None else None,
            "question": state["normalized_question"],
            "reason": plan.response_override or "该请求需要人工确认。",
        }
    )
    decision = HumanReviewResume.model_validate(resume_payload)
    approved = decision.decision == "approve"
    return GraphStateUpdate(
        response_override=(
            "人工审核已批准。当前学习环境的人工业务下游仍为Mock，未自动执行真实业务操作。"
            if approved
            else "人工审核未通过，本次请求已终止，未执行任何业务操作。"
        ),
        review_status="approved" if approved else "rejected",
        review_decision=decision.decision,
        review_note=decision.note,
        reviewed_by=decision.reviewer_id,
        current_node="human_review",
        visited_nodes=["human_review"],
        step_count=1,
    )


async def retrieve_knowledge_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """执行策略感知Hybrid RAG，证据不足时在此失败关闭。"""

    execution = await runtime.context.retrieve(
        actor=_actor(state),
        question=_effective_question(state),
        history=_history(state),
        route_plan=_route_plan(state),
    )
    update = GraphStateUpdate(
        route_plan=execution.route_plan.model_dump(mode="json"),
        current_node="retrieve_knowledge",
        visited_nodes=["retrieve_knowledge"],
        step_count=1,
    )
    if execution.evidence_context is not None:
        update["evidence_context"] = execution.evidence_context
    if execution.response_override is not None:
        update["response_override"] = execution.response_override
    return update


def route_after_retrieval(state: CustomerServiceGraphState) -> str:
    """只有存在有界证据时才允许进入Grounded生成。"""

    return (
        "deterministic_response"
        if state.get("response_override") is not None
        else "generate_grounded"
    )


async def generate_grounded_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """生成严格Grounded JSON；本节点不提前发布，也不执行NLI。"""

    evidence_context = state.get("evidence_context")
    if evidence_context is None:
        raise RuntimeError("grounded generation requires evidence context")
    try:
        result = await runtime.context.generate_grounded(
            request_id=state["request_id"],
            question=_effective_question(state),
            history=_history(state),
            evidence_context=evidence_context,
        )
    except AppError as exc:
        plan = _route_plan(state)
        retrieval = plan.summary.retrieval
        if retrieval is not None:
            plan = plan.model_copy(
                update={
                    "summary": plan.summary.model_copy(
                        update={
                            "retrieval": retrieval.model_copy(
                                update={"grounding_error_code": exc.code.value}
                            )
                        }
                    )
                }
            )
        return GraphStateUpdate(
            route_plan=plan.model_dump(mode="json"),
            response_override=("知识回答模型暂时不可用，本次没有展示未经验证的内容。请稍后重试。"),
            execution_error_code=exc.code.value,
            current_node="generate_grounded",
            visited_nodes=["generate_grounded"],
            step_count=1,
        )
    return GraphStateUpdate(
        grounded_result=result.model_dump(mode="json"),
        current_node="generate_grounded",
        visited_nodes=["generate_grounded"],
        step_count=1,
    )


def route_after_grounded_generation(state: CustomerServiceGraphState) -> str:
    """模型依赖故障时安全降级；成功生成才进入真实NLI。"""

    return (
        "deterministic_response" if state.get("response_override") is not None else "verify_claims"
    )


async def verify_claims_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """调用真实NLI，并依据8E策略确定性发布或安全拦截。"""

    evidence_context = state.get("evidence_context")
    payload = state.get("grounded_result")
    if evidence_context is None or payload is None:
        raise RuntimeError("claim verification requires grounded result and evidence")
    generated = GroundedChatCompletionResult.model_validate(payload)
    verified = await runtime.context.verify_grounded(
        result=generated,
        evidence_context=evidence_context,
    )
    plan = attach_grounding_trace(_route_plan(state), verified)
    return GraphStateUpdate(
        route_plan=plan.model_dump(mode="json"),
        grounded_result=verified.model_dump(mode="json"),
        answer=publish_grounded_answer(verified),
        model=verified.response.model,
        finish_reason=verified.response.finish_reason.value,
        usage=verified.response.usage.model_dump(mode="json"),
        prompt_version=verified.prompt_version,
        current_node="verify_claims",
        visited_nodes=["verify_claims"],
        step_count=1,
    )


async def general_chat_node(
    state: CustomerServiceGraphState,
    runtime: Runtime[CustomerServiceGraphContext],
) -> GraphStateUpdate:
    """闲聊路径调用真实回答Provider，不进入知识与NLI链路。"""

    result = await runtime.context.complete_general(
        request_id=state["request_id"],
        question=_effective_question(state),
        history=_history(state),
    )
    return GraphStateUpdate(
        answer=result.response.content,
        model=result.response.model,
        finish_reason=result.response.finish_reason.value,
        usage=result.response.usage.model_dump(mode="json"),
        prompt_version=result.prompt_version,
        current_node="general_chat",
        visited_nodes=["general_chat"],
        step_count=1,
    )


async def deterministic_response_node(
    state: CustomerServiceGraphState,
) -> GraphStateUpdate:
    """安全、澄清、人工Mock或无证据路径直接返回策略文本。"""

    plan = _route_plan(state)
    answer = state.get("response_override") or plan.response_override
    if answer is None:
        raise RuntimeError("deterministic route requires response text")
    knowledge_path = plan.summary.target is CustomerServiceTarget.KNOWLEDGE_RAG
    usage = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
    return GraphStateUpdate(
        answer=answer,
        model="deterministic-knowledge" if knowledge_path else "deterministic-routing",
        finish_reason=FinishReason.STOP.value,
        usage=usage.model_dump(mode="json"),
        prompt_version=(
            "knowledge_retrieval:v1" if knowledge_path else "customer_service_router:v1"
        ),
        current_node="deterministic_response",
        visited_nodes=["deterministic_response"],
        step_count=1,
    )


async def finalize_node(state: CustomerServiceGraphState) -> GraphStateUpdate:
    """确认最终回答字段齐全后完成一次9B执行。"""

    required = ("answer", "model", "finish_reason", "usage", "prompt_version")
    if any(state.get(field) is None for field in required):
        raise RuntimeError("graph completed without a full response contract")
    return GraphStateUpdate(
        status=GraphRunStatus.COMPLETED,
        current_node="finalize",
        visited_nodes=["finalize"],
        step_count=1,
    )


def _route_plan(state: CustomerServiceGraphState) -> CustomerServiceRoutePlan:
    """从Checkpoint JSON恢复内部RoutePlan，并重新附加非公开IntentDecision。"""

    payload = dict(state["route_plan"])
    decision_payload = state.get("intent_decision")
    payload["intent_decision"] = (
        IntentDecision.model_validate(decision_payload) if decision_payload is not None else None
    )
    return CustomerServiceRoutePlan.model_validate(payload)


def _actor(state: CustomerServiceGraphState) -> UserContext:
    """恢复经过API鉴权的用户上下文。"""

    return UserContext.model_validate(state["actor"])


def _history(state: CustomerServiceGraphState) -> list[ChatMessage]:
    """恢复最多20条对话历史供Rewrite与Prompt使用。"""

    return [ChatMessage.model_validate(item) for item in state.get("history", [])]


def _effective_question(state: CustomerServiceGraphState) -> str:
    """优先使用上下文化独立问题；原问题仍保留在State用于页面和审计。"""

    return state.get("standalone_question", state["normalized_question"])


def build_week9a_graph(*, checkpointer: BaseCheckpointSaver[str] | None = None) -> Week9AGraph:
    """声明节点和边；传入真实Saver后由thread_id隔离并持久化状态。"""

    builder = StateGraph(CustomerServiceGraphState)
    builder.add_node("initialize", initialize_node)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("complete", complete_node)
    builder.add_node("fail", fail_node)

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_input_validation,
        {"complete": "complete", "fail": "fail"},
    )
    builder.add_edge("complete", END)
    builder.add_edge("fail", END)
    return builder.compile(checkpointer=checkpointer)


def build_week9b_graph(*, checkpointer: BaseCheckpointSaver[str] | None = None) -> Week9BGraph:
    """编译9B真实客服Graph；外部服务通过context_schema注入。"""

    builder = StateGraph(
        CustomerServiceGraphState,
        context_schema=CustomerServiceGraphContext,
    )
    builder.add_node("initialize", initialize_node)
    builder.add_node("validate_input", validate_input_node)
    builder.add_node("resolve_context", resolve_context_node)
    builder.add_node("classify_intent", classify_intent_node)
    builder.add_node("retrieve_knowledge", retrieve_knowledge_node)
    builder.add_node("generate_grounded", generate_grounded_node)
    builder.add_node("verify_claims", verify_claims_node)
    builder.add_node("general_chat", general_chat_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("deterministic_response", deterministic_response_node)
    builder.add_node("finalize", finalize_node)
    builder.add_node("fail", fail_node)

    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "validate_input")
    builder.add_conditional_edges(
        "validate_input",
        route_after_input_validation,
        {"complete": "resolve_context", "fail": "fail"},
    )
    builder.add_conditional_edges(
        "resolve_context",
        route_after_context_resolution,
        {
            "classify_intent": "classify_intent",
            "deterministic_response": "deterministic_response",
        },
    )
    builder.add_conditional_edges(
        "classify_intent",
        route_after_intent,
        {
            "retrieve_knowledge": "retrieve_knowledge",
            "general_chat": "general_chat",
            "human_review": "human_review",
            "deterministic_response": "deterministic_response",
        },
    )
    builder.add_conditional_edges(
        "retrieve_knowledge",
        route_after_retrieval,
        {
            "generate_grounded": "generate_grounded",
            "deterministic_response": "deterministic_response",
        },
    )
    builder.add_conditional_edges(
        "generate_grounded",
        route_after_grounded_generation,
        {
            "verify_claims": "verify_claims",
            "deterministic_response": "deterministic_response",
        },
    )
    builder.add_edge("verify_claims", "finalize")
    builder.add_edge("general_chat", "finalize")
    builder.add_edge("human_review", "deterministic_response")
    builder.add_edge("deterministic_response", "finalize")
    builder.add_edge("finalize", END)
    builder.add_edge("fail", END)
    return builder.compile(checkpointer=checkpointer)


async def run_week9a_graph(
    state: CustomerServiceGraphState,
    *,
    recursion_limit: int = MAX_GRAPH_STEPS,
    checkpointer: BaseCheckpointSaver[str] | None = None,
) -> CustomerServiceGraphState:
    """统一异步调用入口，始终带框架级循环上限。"""

    if recursion_limit < 1:
        raise ValueError("recursion_limit must be positive")
    config: RunnableConfig = {"recursion_limit": recursion_limit}
    if checkpointer is not None:
        # thread_id是Checkpoint分区键；相同会话可续跑，不同会话严格隔离。
        config["configurable"] = {"thread_id": state["thread_id"]}
    result = await build_week9a_graph(checkpointer=checkpointer).ainvoke(
        state,
        config=config,
    )
    return cast(CustomerServiceGraphState, result)
