"""Stable domain contracts for intent classification and downstream routing."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IntentRoute(StrEnum):
    """Top-level decision made before retrieval, tools, or specialist routing."""

    SUPPORTED = "supported"
    OUT_OF_DOMAIN = "out_of_domain"
    CHITCHAT = "chitchat"
    UNSAFE = "unsafe"


class BusinessDomain(StrEnum):
    """Stable Bilibili customer-service business domains."""

    MEMBERSHIP = "membership"
    ORDER = "order"
    ACCOUNT = "account"
    CREATOR = "creator"
    CONTENT = "content"
    COMMUNITY = "community"
    TECHNICAL = "technical"
    HUMAN_SERVICE = "human_service"


class IntentAction(StrEnum):
    """Actions that can be combined with a business domain."""

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
    """Entity categories; entity values intentionally remain open text."""

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
    """Coarse sentiment used for response tone and escalation policy."""

    NEUTRAL = "neutral"
    POSITIVE = "positive"
    CONFUSED = "confused"
    ANXIOUS = "anxious"
    ANGRY = "angry"


class RiskLevel(StrEnum):
    """Business and safety risk declared by the classifier."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DecisionSource(StrEnum):
    """Classifier source retained for comparison and audit."""

    RULE = "rule"
    MODEL = "model"
    HYBRID = "hybrid"


class IntentEntity(BaseModel):
    """An extracted entity with both source text and optional normalized text."""

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
    """One independently routable intent in a potentially compound request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: BusinessDomain
    action: IntentAction
    confidence: float = Field(ge=0.0, le=1.0)


class IntentDecision(BaseModel):
    """Validated classifier result shared by RAG, tools, agents, and evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route: IntentRoute
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
        if self.route is IntentRoute.SUPPORTED and not self.intents:
            raise ValueError("supported route requires at least one sub-intent")
        if self.route is not IntentRoute.SUPPORTED and self.intents:
            raise ValueError("non-supported routes must not contain sub-intents")
        if self.route is IntentRoute.UNSAFE and self.risk is RiskLevel.LOW:
            raise ValueError("unsafe route cannot have low risk")

        has_question = self.clarification_question is not None
        if self.needs_clarification != has_question:
            raise ValueError(
                "clarification_question must be present exactly when clarification is needed"
            )

        intent_keys = {(intent.domain, intent.action) for intent in self.intents}
        if len(intent_keys) != len(self.intents):
            raise ValueError("duplicate domain and action sub-intents are not allowed")
        return self
