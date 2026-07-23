"""Public intent-classification domain contracts."""

from bili_support.intent.classifier import IntentClassifier
from bili_support.intent.factory import build_intent_provider
from bili_support.intent.hybrid import HybridIntentClassifier, HybridIntentResult
from bili_support.intent.rules import RuleIntentClassifier, RuleMatch
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

__all__ = [
    "BusinessDomain",
    "DecisionSource",
    "EntityType",
    "IntentAction",
    "IntentClassifier",
    "IntentDecision",
    "IntentEntity",
    "IntentRoute",
    "HybridIntentClassifier",
    "HybridIntentResult",
    "RiskLevel",
    "RuleIntentClassifier",
    "RuleMatch",
    "Sentiment",
    "SubIntent",
    "build_intent_provider",
]
