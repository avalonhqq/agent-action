"""API contracts for persisted conversations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bili_support.conversation_context import ContextResolution
from bili_support.llm.types import FinishReason, TokenUsage
from bili_support.routing import CustomerServiceRouteSummary


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="新会话", max_length=120)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=4000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value.strip()


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    thread_id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str
    role: str
    content: str
    request_id: str
    created_at: datetime


class GraphExecutionStatus(StrEnum):
    """对外可见的Graph执行状态。"""

    INTERRUPTED = "interrupted"
    COMPLETED = "completed"
    FAILED = "failed"


class GraphExecutionView(BaseModel):
    """不暴露完整Checkpoint、历史消息或模型原文的安全调试视图。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_id: str
    thread_id: str
    request_id: str
    status: GraphExecutionStatus
    current_node: str
    next_nodes: tuple[str, ...] = ()
    visited_nodes: tuple[str, ...] = ()
    route_target: str | None = None
    review_status: str | None = None
    interrupt: dict[str, object] | None = None
    answer: str | None = None


class GraphRecoveryAction(StrEnum):
    """9D根据执行事实给出的恢复动作；不是由模型自由生成。"""

    NONE = "none"  # 已完成，无需恢复
    RESUME_REVIEW = "resume_review"  # 等待人工审核后Command.resume
    RETRY_CHECKPOINT = "retry_checkpoint"  # 可由运营从最后成功Checkpoint重试
    CORRECT_INPUT = "correct_input"  # 输入/策略失败，应修正后创建新请求
    OPERATOR_INSPECT = "operator_inspect"  # 未知或永久错误，需要运营排障


class GraphRecoveryRecommendation(BaseModel):
    """确定性恢复建议，明确是否允许自动重试以及副作用边界。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: GraphRecoveryAction
    retryable: bool
    automatic_retry_allowed: bool
    reason: str
    error_code: str | None = None


class GraphTimelineStep(BaseModel):
    """单个Checkpoint的脱敏视图，不暴露问题、历史、证据或模型原文。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_id: str
    step: int
    source: str
    created_at: str | None = None
    current_node: str
    next_nodes: tuple[str, ...] = ()
    written_nodes: tuple[str, ...] = ()
    failed_nodes: tuple[str, ...] = ()
    interrupted: bool = False


class GraphExecutionTimeline(BaseModel):
    """9D只读流程回放和失败恢复建议。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution: GraphExecutionView
    steps: tuple[GraphTimelineStep, ...]
    recovery: GraphRecoveryRecommendation


class ResumeGraphRequest(BaseModel):
    """审核人员恢复中断Graph时提交的受控命令。"""

    model_config = ConfigDict(extra="forbid")

    decision: str = Field(pattern=r"^(approve|reject)$")
    note: str = Field(min_length=1, max_length=500)


class PendingGraphReviewView(BaseModel):
    """运营审核列表使用的MySQL事实视图。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    execution_id: str
    thread_id: str
    request_id: str
    target: str
    reason: str
    status: str
    created_at: datetime


class ConversationMessageResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    answer: str
    model: str
    finish_reason: FinishReason
    usage: TokenUsage
    prompt_version: str
    routing: CustomerServiceRouteSummary
    execution: GraphExecutionView | None = None
    context_resolution: ContextResolution | None = None
