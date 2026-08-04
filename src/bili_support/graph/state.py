"""第9周9A：LangGraph共享状态、生命周期枚举与输入构造器。"""

from __future__ import annotations

import operator
from enum import StrEnum
from typing import Annotated, NotRequired, Required, TypedDict


class GraphRunStatus(StrEnum):
    """一次客服工作流执行的生命周期状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class GraphInputStatus(StrEnum):
    """输入节点的确定性校验结果。"""

    UNKNOWN = "unknown"
    VALID = "valid"
    INVALID = "invalid"


class GraphNextAction(StrEnum):
    """9A结束后应进入的下一项真实业务能力。"""

    INTENT = "intent"
    STOP = "stop"


class GraphErrorCode(StrEnum):
    """Graph边界使用的稳定失败原因，不向外暴露异常原文。"""

    EMPTY_QUESTION = "empty_question"
    QUESTION_TOO_LONG = "question_too_long"
    STEP_LIMIT_EXCEEDED = "step_limit_exceeded"


class CustomerServiceGraphState(TypedDict, total=False):
    """节点共享状态；列表与计数器通过Reducer合并节点的增量写入。"""

    request_id: Required[str]
    thread_id: Required[str]
    user_id: Required[str]
    question: Required[str]

    status: Required[GraphRunStatus]
    input_status: Required[GraphInputStatus]
    current_node: Required[str]
    visited_nodes: Required[Annotated[list[str], operator.add]]
    step_count: Required[Annotated[int, operator.add]]

    normalized_question: NotRequired[str]
    next_action: NotRequired[GraphNextAction]
    error_code: NotRequired[GraphErrorCode]


class GraphStateUpdate(TypedDict, total=False):
    """节点允许返回的部分状态；节点不原地修改整个共享State。"""

    status: GraphRunStatus
    input_status: GraphInputStatus
    current_node: str
    visited_nodes: list[str]
    step_count: int
    normalized_question: str
    next_action: GraphNextAction
    error_code: GraphErrorCode


def create_graph_input(
    *,
    request_id: str,
    thread_id: str,
    user_id: str,
    question: str,
) -> CustomerServiceGraphState:
    """集中构造合法初始State，避免API、测试和后续Service各自补默认值。"""

    return CustomerServiceGraphState(
        request_id=request_id,
        thread_id=thread_id,
        user_id=user_id,
        question=question,
        status=GraphRunStatus.RUNNING,
        input_status=GraphInputStatus.UNKNOWN,
        current_node="",
        visited_nodes=[],
        step_count=0,
    )
