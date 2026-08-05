"""第9周9D：把LangGraph Checkpoint转换成脱敏时间线和确定性恢复建议。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from langgraph.types import StateSnapshot

from bili_support.graph.state import CustomerServiceGraphState, GraphRunStatus
from bili_support.schemas.conversations import (
    GraphRecoveryAction,
    GraphRecoveryRecommendation,
    GraphTimelineStep,
)

# 这些错误表示依赖暂时不可用。底层Provider已经完成短退避重试，因此Graph层只建议
# 运营从最后成功Checkpoint恢复，不再自动叠加重试，避免放大模型调用和外部副作用。
_CHECKPOINT_RETRYABLE_ERRORS = frozenset(
    {
        "MODEL_UNAVAILABLE",
        "SERVICE_NOT_READY",
        "INTERNAL_ERROR",
    }
)


def build_safe_timeline(
    snapshots: Sequence[StateSnapshot],
) -> tuple[GraphTimelineStep, ...]:
    """按时间正序构建流程回放；只公开节点级元数据。"""

    # LangGraph原生history按最新优先返回，页面阅读则使用最早到最新。
    return tuple(_safe_step(item) for item in reversed(snapshots))


def recommend_recovery(
    latest: StateSnapshot,
    *,
    audit_error_code: str | None,
) -> GraphRecoveryRecommendation:
    """依据Checkpoint和MySQL审计事实分级，不解析异常原文。"""

    if _snapshot_interrupted(latest):
        return GraphRecoveryRecommendation(
            action=GraphRecoveryAction.RESUME_REVIEW,
            retryable=False,
            automatic_retry_allowed=False,
            reason="执行正在等待人工审核，应使用受控resume接口继续，不能当作失败重跑。",
            error_code=audit_error_code,
        )

    failed_nodes = _failed_nodes(latest)
    if failed_nodes:
        if audit_error_code in _CHECKPOINT_RETRYABLE_ERRORS:
            return GraphRecoveryRecommendation(
                action=GraphRecoveryAction.RETRY_CHECKPOINT,
                retryable=True,
                automatic_retry_allowed=False,
                reason=(
                    "依赖型故障可从最后成功Checkpoint恢复；当前项目要求运营确认，"
                    "防止LLM、工具或外部业务动作重复执行。"
                ),
                error_code=audit_error_code,
            )
        return GraphRecoveryRecommendation(
            action=GraphRecoveryAction.OPERATOR_INSPECT,
            retryable=False,
            automatic_retry_allowed=False,
            reason="故障类型不在可重试白名单，需要运营检查依赖和审计记录。",
            error_code=audit_error_code,
        )

    state = cast(CustomerServiceGraphState, latest.values)
    if state.get("status") == GraphRunStatus.FAILED:
        return GraphRecoveryRecommendation(
            action=GraphRecoveryAction.CORRECT_INPUT,
            retryable=False,
            automatic_retry_allowed=False,
            reason="输入或确定性策略已经拒绝本次执行，应修正请求后创建新执行。",
            error_code=audit_error_code,
        )

    return GraphRecoveryRecommendation(
        action=GraphRecoveryAction.NONE,
        retryable=False,
        automatic_retry_allowed=False,
        reason="执行已经安全结束，无需恢复。",
        error_code=audit_error_code,
    )


def snapshot_has_failure(snapshot: StateSnapshot) -> bool:
    """同时识别显式FAILED状态和LangGraph task异常。"""

    state = cast(CustomerServiceGraphState, snapshot.values)
    return bool(_failed_nodes(snapshot)) or state.get("status") == GraphRunStatus.FAILED


def _safe_step(snapshot: StateSnapshot) -> GraphTimelineStep:
    metadata = snapshot.metadata if isinstance(snapshot.metadata, Mapping) else {}
    configurable = snapshot.config.get("configurable", {})
    checkpoint_id = str(configurable.get("checkpoint_id", ""))
    writes = metadata.get("writes")
    written_nodes = (
        tuple(sorted(str(item) for item in writes)) if isinstance(writes, Mapping) else ()
    )
    state = cast(CustomerServiceGraphState, snapshot.values)
    return GraphTimelineStep(
        checkpoint_id=checkpoint_id,
        step=int(metadata.get("step", -1)),
        source=str(metadata.get("source", "unknown")),
        created_at=snapshot.created_at,
        current_node=state.get("current_node", ""),
        next_nodes=tuple(snapshot.next),
        written_nodes=written_nodes,
        failed_nodes=_failed_nodes(snapshot),
        interrupted=_snapshot_interrupted(snapshot),
    )


def _failed_nodes(snapshot: StateSnapshot) -> tuple[str, ...]:
    return tuple(sorted({task.name for task in snapshot.tasks if task.error is not None}))


def _snapshot_interrupted(snapshot: StateSnapshot) -> bool:
    return bool(snapshot.interrupts) or any(task.interrupts for task in snapshot.tasks)
