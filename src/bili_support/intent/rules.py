from pydantic import BaseModel, ConfigDict, Field

from bili_support.intent.types import (
    BusinessDomain,
    DecisionSource,
    EntityType,
    IntentAction,
    IntentDecision,
    IntentEntity,
    IntentRoute,
    RiskLevel,
    Sentiment,
    SubIntent,
)

_EXACT_GREETINGS = frozenset(
    {
        "你好",
        "您好",
        "嗨",
        "hi",
        "hello",
    }
)
_EXACT_HUMAN_TRANSFER_REQUESTS = frozenset(
    {
        "转人工",
        "人工客服",
        "联系人工客服",
    }
)
_MEMBERSHIP_PRICE_MARKERS = ("多少钱", "价格", "怎么收费", "费用")


class RuleMatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: str = Field(min_length=1)
    decision: IntentDecision


class RuleIntentClassifier:
    def match(self, question: str) -> RuleMatch | None:
        normalized_question = _normalize_question(question)

        if normalized_question in _EXACT_GREETINGS:
            return _build_low_risk_rule_match(
                rule_id="chitchat.exact_greeting:v1",
                route=IntentRoute.CHITCHAT,
                sentiment=Sentiment.POSITIVE,
            )

        if normalized_question in _EXACT_HUMAN_TRANSFER_REQUESTS:
            return _build_low_risk_rule_match(
                rule_id="human_service.exact_transfer:v1",
                route=IntentRoute.SUPPORTED,
                intents=(
                    SubIntent(
                        domain=BusinessDomain.HUMAN_SERVICE,
                        action=IntentAction.TRANSFER,
                        confidence=1.0,
                    ),
                ),
            )

        # 上下文改写会把“多少钱”补成“大会员多少钱”；这是高精度只读查询，
        # 无需承担一次结构化模型空响应或截断的风险。
        if "大会员" in normalized_question and any(
            marker in normalized_question for marker in _MEMBERSHIP_PRICE_MARKERS
        ):
            return _build_low_risk_rule_match(
                rule_id="membership.price_query:v1",
                route=IntentRoute.SUPPORTED,
                intents=(
                    SubIntent(
                        domain=BusinessDomain.MEMBERSHIP,
                        action=IntentAction.QUERY,
                        confidence=1.0,
                    ),
                ),
                entities=(
                    IntentEntity(
                        type=EntityType.PRODUCT,
                        raw_value="大会员",
                        normalized_value="大会员",
                    ),
                ),
            )

        return None


def _build_low_risk_rule_match(
        *,
        rule_id: str,
        route: IntentRoute,
    intents: tuple[SubIntent, ...] = (),
    entities: tuple[IntentEntity, ...] = (),
        sentiment: Sentiment = Sentiment.NEUTRAL,
) -> RuleMatch:
    return RuleMatch(
        rule_id=rule_id,
        decision=IntentDecision(
            route=route,
            intents=intents,
            entities=entities,
            sentiment=sentiment,
            risk=RiskLevel.LOW,
            confidence=1.0,
            needs_clarification=False,
            clarification_question=None,
            source=DecisionSource.RULE,
        ),
    )


def _normalize_question(question: str) -> str:
    return question.strip().casefold().rstrip("。！？!?").strip()
