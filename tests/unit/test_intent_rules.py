import pytest

from bili_support.intent.rules import RuleIntentClassifier
from bili_support.intent.types import DecisionSource, IntentRoute


@pytest.mark.parametrize("question", ["你好！", " HELLO? "])
def test_exact_greeting_returns_rule_decision(question: str) -> None:
    result = RuleIntentClassifier().match(question)

    assert result is not None
    assert result.rule_id == "chitchat.exact_greeting:v1"
    assert result.decision.route is IntentRoute.CHITCHAT
    assert result.decision.source is DecisionSource.RULE


def test_compound_greeting_does_not_match_exact_rule() -> None:
    result = RuleIntentClassifier().match("你好，我要退款")

    assert result is None
