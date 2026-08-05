"""9D脱敏Checkpoint回放与恢复策略测试。"""

from langgraph.types import Interrupt, PregelTask, StateSnapshot

from bili_support.graph.replay import build_safe_timeline, recommend_recovery
from bili_support.graph.state import GraphRunStatus
from bili_support.schemas.conversations import GraphRecoveryAction


def _snapshot(
    *,
    checkpoint_id: str,
    step: int,
    current_node: str,
    next_nodes: tuple[str, ...] = (),
    task: PregelTask | None = None,
    status: GraphRunStatus = GraphRunStatus.RUNNING,
) -> StateSnapshot:
    return StateSnapshot(
        values={"current_node": current_node, "status": status},
        next=next_nodes,
        config={
            "configurable": {
                "thread_id": "conversation:request",
                "checkpoint_id": checkpoint_id,
            }
        },
        metadata={"step": step, "source": "loop", "writes": {current_node: {}}},
        created_at=f"2026-08-05T00:00:0{step}+00:00",
        parent_config=None,
        tasks=(task,) if task is not None else (),
        interrupts=(),
    )


def test_timeline_is_chronological_and_does_not_expose_state_values() -> None:
    newest = _snapshot(
        checkpoint_id="cp-2",
        step=2,
        current_node="classify_intent",
        next_nodes=("retrieve_knowledge",),
    )
    oldest = _snapshot(
        checkpoint_id="cp-1",
        step=1,
        current_node="validate_input",
        next_nodes=("resolve_context",),
    )

    timeline = build_safe_timeline([newest, oldest])

    assert [item.checkpoint_id for item in timeline] == ["cp-1", "cp-2"]
    assert timeline[1].written_nodes == ("classify_intent",)
    assert "values" not in timeline[1].model_dump()


def test_interrupted_execution_must_resume_instead_of_retry() -> None:
    interrupted = PregelTask(
        id="task-review",
        name="human_review",
        path=(),
        interrupts=(Interrupt(value={"kind": "human_review"}, id="interrupt-1"),),
    )
    snapshot = _snapshot(
        checkpoint_id="cp-review",
        step=3,
        current_node="classify_intent",
        next_nodes=("human_review",),
        task=interrupted,
    )

    recovery = recommend_recovery(snapshot, audit_error_code=None)

    assert recovery.action is GraphRecoveryAction.RESUME_REVIEW
    assert recovery.retryable is False


def test_transient_failed_task_requires_operator_checkpoint_retry() -> None:
    failed = PregelTask(
        id="task-model",
        name="classify_intent",
        path=(),
        error=RuntimeError("provider detail must not be exposed"),
    )
    snapshot = _snapshot(
        checkpoint_id="cp-failed",
        step=3,
        current_node="resolve_context",
        next_nodes=("classify_intent",),
        task=failed,
    )

    recovery = recommend_recovery(snapshot, audit_error_code="MODEL_UNAVAILABLE")
    timeline = build_safe_timeline([snapshot])

    assert recovery.action is GraphRecoveryAction.RETRY_CHECKPOINT
    assert recovery.retryable is True
    assert recovery.automatic_retry_allowed is False
    assert timeline[0].failed_nodes == ("classify_intent",)
    assert "provider detail" not in timeline[0].model_dump_json()


def test_deterministic_failed_state_requires_corrected_input() -> None:
    snapshot = _snapshot(
        checkpoint_id="cp-invalid",
        step=2,
        current_node="fail",
        status=GraphRunStatus.FAILED,
    )

    recovery = recommend_recovery(snapshot, audit_error_code="VALIDATION_ERROR")

    assert recovery.action is GraphRecoveryAction.CORRECT_INPUT
    assert recovery.retryable is False
