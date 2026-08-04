"""第9周9A最小LangGraph的状态、条件边和循环保护测试。"""

import pytest

from bili_support.graph import (
    MAX_GRAPH_STEPS,
    GraphErrorCode,
    GraphInputStatus,
    GraphNextAction,
    GraphRunStatus,
    create_graph_input,
    run_week9a_graph,
)


@pytest.mark.asyncio
async def test_valid_question_reaches_complete() -> None:
    result = await run_week9a_graph(
        create_graph_input(
            request_id="request-graph-valid",
            thread_id="thread-graph-valid",
            user_id="user-graph-valid",
            question="  大会员开通后多久生效？  ",
        )
    )

    assert result["status"] is GraphRunStatus.COMPLETED
    assert result["input_status"] is GraphInputStatus.VALID
    assert result["normalized_question"] == "大会员开通后多久生效？"
    assert result["next_action"] is GraphNextAction.INTENT
    assert result["visited_nodes"] == ["initialize", "validate_input", "complete"]
    assert result["step_count"] == 3
    assert "error_code" not in result


@pytest.mark.asyncio
async def test_blank_question_reaches_fail() -> None:
    result = await run_week9a_graph(
        create_graph_input(
            request_id="request-graph-blank",
            thread_id="thread-graph-blank",
            user_id="user-graph-blank",
            question="   ",
        )
    )

    assert result["status"] is GraphRunStatus.FAILED
    assert result["input_status"] is GraphInputStatus.INVALID
    assert result["error_code"] is GraphErrorCode.EMPTY_QUESTION
    assert result["next_action"] is GraphNextAction.STOP
    assert result["visited_nodes"] == ["initialize", "validate_input", "fail"]
    assert result["step_count"] == 3


@pytest.mark.asyncio
async def test_question_over_limit_fails_without_truncating_input() -> None:
    question = "会" * 2001
    result = await run_week9a_graph(
        create_graph_input(
            request_id="request-graph-long",
            thread_id="thread-graph-long",
            user_id="user-graph-long",
            question=question,
        )
    )

    assert result["error_code"] is GraphErrorCode.QUESTION_TOO_LONG
    assert result["normalized_question"] == question


@pytest.mark.asyncio
async def test_business_step_limit_fails_closed() -> None:
    state = create_graph_input(
        request_id="request-graph-step-limit",
        thread_id="thread-graph-step-limit",
        user_id="user-graph-step-limit",
        question="大会员开通后多久生效？",
    )
    state["step_count"] = MAX_GRAPH_STEPS

    result = await run_week9a_graph(state)

    assert result["status"] is GraphRunStatus.FAILED
    assert result["error_code"] is GraphErrorCode.STEP_LIMIT_EXCEEDED


@pytest.mark.asyncio
async def test_runtime_recursion_limit_must_be_positive() -> None:
    state = create_graph_input(
        request_id="request-graph-invalid-limit",
        thread_id="thread-graph-invalid-limit",
        user_id="user-graph-invalid-limit",
        question="测试",
    )

    with pytest.raises(ValueError, match="recursion_limit must be positive"):
        await run_week9a_graph(state, recursion_limit=0)
