"""跨轮主题栈、槽位兼容和安全澄清测试。"""

import pytest

from bili_support.conversation_context import (
    ContextResolutionKind,
    ConversationContextResolver,
    ConversationContextState,
    ConversationTopic,
    ModelContextResolution,
    advance_conversation_context,
)
from bili_support.intent.types import (
    BusinessDomain,
    DecisionSource,
    IntentAction,
    IntentDecision,
    IntentRoute,
    RiskLevel,
    Sentiment,
    SubIntent,
)


class _ModelResolver:
    def __init__(self, result: ModelContextResolution | None) -> None:
        self.result = result
        self.calls = 0

    async def resolve(self, **_kwargs) -> ModelContextResolution | None:
        self.calls += 1
        return self.result


def _topic(
    label: str,
    domain: BusinessDomain,
    *,
    turn: int,
) -> ConversationTopic:
    return ConversationTopic(
        key=f"{domain.value}:query:{label}",
        label=label,
        domain=domain,
        action="query",
        last_turn=turn,
        confidence=0.95,
    )


@pytest.mark.asyncio
async def test_price_slot_selects_membership_not_most_recent_technical_topic() -> None:
    context = ConversationContextState(
        active_topics=(
            _topic("电视端播放", BusinessDomain.TECHNICAL, turn=3),
            _topic("大会员", BusinessDomain.MEMBERSHIP, turn=1),
        )
    )

    result = await ConversationContextResolver().resolve(
        question="多少钱",
        history=[],
        context=context,
    )

    assert result.kind is ContextResolutionKind.RESOLVED
    assert result.standalone_query == "大会员多少钱"
    assert result.referenced_turns == (1,)


@pytest.mark.asyncio
async def test_multiple_price_topics_are_clarified_when_model_cannot_resolve() -> None:
    context = ConversationContextState(
        active_topics=(
            _topic("大会员", BusinessDomain.MEMBERSHIP, turn=2),
            _topic("订单套餐", BusinessDomain.ORDER, turn=1),
        )
    )

    result = await ConversationContextResolver().resolve(
        question="多少钱",
        history=[],
        context=context,
    )

    assert result.kind is ContextResolutionKind.AMBIGUOUS
    assert result.standalone_query is None
    assert "大会员" in (result.clarification_question or "")
    assert "订单套餐" in (result.clarification_question or "")


@pytest.mark.asyncio
async def test_model_may_choose_only_a_whitelisted_topic() -> None:
    selected = _topic("订单套餐", BusinessDomain.ORDER, turn=2)
    model = _ModelResolver(
        ModelContextResolution(
            kind=ContextResolutionKind.RESOLVED,
            standalone_query="订单套餐多少钱",
            inherited_topic_key=selected.key,
            confidence=0.88,
        )
    )
    context = ConversationContextState(
        active_topics=(
            _topic("大会员", BusinessDomain.MEMBERSHIP, turn=2),
            selected,
        )
    )

    result = await ConversationContextResolver(model=model).resolve(
        question="多少钱",
        history=[],
        context=context,
    )

    assert result.source == "model"
    assert result.inherited_topic_key == selected.key
    assert model.calls == 1


def test_context_advance_keeps_topic_stack_and_explicit_reset_clears_it() -> None:
    previous = ConversationContextState(
        active_topics=(_topic("大会员", BusinessDomain.MEMBERSHIP, turn=1),),
        context_version=1,
    )
    decision = IntentDecision(
        route=IntentRoute.SUPPORTED,
        intents=(
            SubIntent(
                domain=BusinessDomain.ACCOUNT,
                action=IntentAction.RECOVER,
                confidence=0.9,
            ),
        ),
        sentiment=Sentiment.NEUTRAL,
        risk=RiskLevel.MEDIUM,
        confidence=0.9,
        source=DecisionSource.MODEL,
    )

    result = advance_conversation_context(
        previous,
        decision=decision,
        standalone_query="账号怎么找回",
        reset_context=True,
    )

    assert [item.domain for item in result.active_topics] == [BusinessDomain.ACCOUNT]
    assert result.context_version == 2
