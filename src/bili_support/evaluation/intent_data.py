"""固定 JSONL 意图评估集的安全加载。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bili_support.evaluation.intent_types import IntentEvaluationCase


class IntentDatasetError(ValueError):
    """评估数据无法读取、解析或通过领域校验。"""


def load_intent_evaluation_cases(path: Path) -> tuple[IntentEvaluationCase, ...]:
    """逐行加载 JSONL，并拒绝空数据集和重复 case_id。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise IntentDatasetError(f"cannot read intent dataset: {path}") from exc

    cases: list[IntentEvaluationCase] = []
    case_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            case = IntentEvaluationCase.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise IntentDatasetError(
                f"invalid intent dataset line {line_number}"
            ) from exc
        if case.case_id in case_ids:
            raise IntentDatasetError(f"duplicate intent case_id: {case.case_id}")
        case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise IntentDatasetError("intent dataset must contain at least one case")
    return tuple(cases)
