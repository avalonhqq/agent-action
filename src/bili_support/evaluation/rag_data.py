"""加载8C JSONL Golden Dataset并拒绝重复Case ID。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bili_support.evaluation.rag_types import RagEvaluationCase


class RagDatasetError(ValueError):
    """数据集格式、Schema或唯一性错误。"""


def load_rag_evaluation_cases(path: Path) -> tuple[RagEvaluationCase, ...]:
    """逐行解析，错误中保留行号但不吞掉损坏样本。"""

    cases: list[RagEvaluationCase] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RagDatasetError(str(exc)) from exc
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            cases.append(RagEvaluationCase.model_validate_json(raw))
        except (ValidationError, json.JSONDecodeError) as exc:
            raise RagDatasetError(f"line {line_number}: {exc}") from exc
    if not cases:
        raise RagDatasetError("RAG evaluation dataset must not be empty")
    ids = [item.case_id for item in cases]
    if len(ids) != len(set(ids)):
        raise RagDatasetError("RAG evaluation case_id must be unique")
    return tuple(cases)
