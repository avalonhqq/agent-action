"""Offline evaluation contracts and helpers."""

from bili_support.evaluation.chunk_data import (
    ChunkDatasetError,
    load_chunk_evaluation_cases,
)
from bili_support.evaluation.chunk_metrics import ChunkEvaluator
from bili_support.evaluation.chunk_types import (
    ChunkEvaluationCase,
    ChunkEvaluationMode,
    ChunkEvaluationReport,
)
from bili_support.evaluation.intent_data import (
    IntentDatasetError,
    load_intent_evaluation_cases,
)
from bili_support.evaluation.intent_types import (
    EvaluationStrategy,
    FailureCategory,
    IntentEvaluationCase,
    IntentEvaluationReport,
)
from bili_support.evaluation.rag_data import RagDatasetError, load_rag_evaluation_cases
from bili_support.evaluation.rag_runner import ReplayRagEvaluator, score_rag_case
from bili_support.evaluation.rag_types import (
    RagEvaluationCase,
    RagEvaluationReport,
)

__all__ = [
    "ChunkDatasetError",
    "ChunkEvaluationCase",
    "ChunkEvaluationMode",
    "ChunkEvaluationReport",
    "ChunkEvaluator",
    "EvaluationStrategy",
    "FailureCategory",
    "IntentDatasetError",
    "IntentEvaluationCase",
    "IntentEvaluationReport",
    "RagDatasetError",
    "RagEvaluationCase",
    "RagEvaluationReport",
    "ReplayRagEvaluator",
    "load_intent_evaluation_cases",
    "load_chunk_evaluation_cases",
    "load_rag_evaluation_cases",
    "score_rag_case",
]
