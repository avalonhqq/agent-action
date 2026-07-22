"""意图识别及下游路由共享的稳定领域契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IntentRoute(StrEnum):
    """进入检索、工具或专业 Agent 前必须先完成的顶层路由。"""

    SUPPORTED = "supported"
    OUT_OF_DOMAIN = "out_of_domain"
    CHITCHAT = "chitchat"
    UNSAFE = "unsafe"


class BusinessDomain(StrEnum):
    """哔哩哔哩客服使用的稳定业务域。"""

    MEMBERSHIP = "membership"
    ORDER = "order"
    ACCOUNT = "account"
    CREATOR = "creator"
    CONTENT = "content"
    COMMUNITY = "community"
    TECHNICAL = "technical"
    HUMAN_SERVICE = "human_service"


class IntentAction(StrEnum):
    """可与业务域组合的动作，避免为每个组合创建膨胀的枚举。"""

    QUERY = "query"
    CANCEL = "cancel"
    REFUND = "refund"
    RECOVER = "recover"
    APPEAL = "appeal"
    REPORT = "report"
    TROUBLESHOOT = "troubleshoot"
    MODIFY = "modify"
    TRANSFER = "transfer"


class EntityType(StrEnum):
    """实体类型受枚举约束，但实体值有意保留为开放文本。"""

    PRODUCT = "product"
    ORDER_ID = "order_id"
    TRANSACTION_ID = "transaction_id"
    ACCOUNT_ID = "account_id"
    CREATOR_ID = "creator_id"
    CONTENT_ID = "content_id"
    TIME_RANGE = "time_range"
    AMOUNT = "amount"
    PAYMENT_CHANNEL = "payment_channel"
    ISSUE = "issue"
    OTHER = "other"


class Sentiment(StrEnum):
    """用于回复语气和升级策略的粗粒度情绪。"""

    NEUTRAL = "neutral"
    POSITIVE = "positive"
    CONFUSED = "confused"
    ANXIOUS = "anxious"
    ANGRY = "angry"


class RiskLevel(StrEnum):
    """分类器声明的业务及安全风险等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionSource(StrEnum):
    """保留决策来源，便于比较规则、模型与混合策略并进行审计。"""

    RULE = "rule"
    MODEL = "model"
    HYBRID = "hybrid"


class IntentEntity(BaseModel):
    """抽取实体：同时保存用户原文和可选的规范化值。"""

    # 冻结对象防止路由过程中被原地修改；拒绝未知字段防止模型悄悄扩展协议。
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: EntityType
    raw_value: str = Field(min_length=1, max_length=200)
    normalized_value: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("raw_value")
    @classmethod
    def raw_value_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("raw_value must not be blank")
        return stripped

    @field_validator("normalized_value")
    @classmethod
    def normalized_value_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("normalized_value must not be blank")
        return stripped


class SubIntent(BaseModel):
    """复合问题中一个可以独立路由的“业务域 + 动作”。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: BusinessDomain
    action: IntentAction
    confidence: float = Field(ge=0.0, le=1.0)


class IntentDecision(BaseModel):
    """经校验后供 RAG、工具、Agent 和评估共同使用的决策。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: IntentRoute
    # 使用 tuple 才能真正保持集合不可变；frozen=True 不会递归冻结 list。
    intents: tuple[SubIntent, ...] = ()
    entities: tuple[IntentEntity, ...] = ()
    sentiment: Sentiment = Sentiment.NEUTRAL
    risk: RiskLevel = RiskLevel.LOW
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_question: str | None = Field(default=None, min_length=1, max_length=300)
    source: DecisionSource

    @field_validator("clarification_question")
    @classmethod
    def clarification_question_must_not_be_blank(
            cls, value: str | None
    ) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("clarification_question must not be blank")
        return stripped

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        # 顶层路由是业务闸门：只有 supported 才允许进入具体业务处理。
        if self.route is IntentRoute.SUPPORTED and not self.intents:
            raise ValueError("supported route requires at least one sub-intent")
        if self.route is not IntentRoute.SUPPORTED and self.intents:
            raise ValueError("non-supported routes must not contain sub-intents")
        if self.route is IntentRoute.UNSAFE and self.risk is RiskLevel.LOW:
            raise ValueError("unsafe route cannot have low risk")

        # 布尔标记与问题文本必须成对出现，避免页面或 Agent 猜测是否要追问。
        has_question = self.clarification_question is not None
        if self.needs_clarification != has_question:
            raise ValueError(
                "clarification_question must be present exactly when clarification is needed"
            )

        # 同一业务域和动作只保留一次，置信度差异不能制造重复任务。
        intent_keys = {(intent.domain, intent.action) for intent in self.intents}
        if len(intent_keys) != len(self.intents):
            raise ValueError("duplicate domain and action sub-intents are not allowed")
        return self
