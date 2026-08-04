"""第9周9A：可真实编译、异步执行且有限步的最小LangGraph。"""

from __future__ import annotations

from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from bili_support.graph.routing import route_after_input_validation
from bili_support.graph.state import (
    CustomerServiceGraphState,
    GraphErrorCode,
    GraphInputStatus,
    GraphNextAction,
    GraphRunStatus,
    GraphStateUpdate,
)

MAX_QUESTION_CHARS = 2000
MAX_GRAPH_STEPS = 8

Week9AGraph = CompiledStateGraph[
    CustomerServiceGraphState,
    None,
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


def build_week9a_graph(
    *, checkpointer: BaseCheckpointSaver[str] | None = None
) -> Week9AGraph:
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
