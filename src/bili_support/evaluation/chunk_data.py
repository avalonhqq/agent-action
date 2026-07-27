"""固定JSONL Chunk评估集的加载与领域校验。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bili_support.evaluation.chunk_types import ChunkEvaluationCase


class ChunkDatasetError(ValueError):
    """评估集不可读、JSON非法或不满足Chunk金标准契约。"""


def load_chunk_evaluation_cases(path: Path) -> tuple[ChunkEvaluationCase, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ChunkDatasetError(f"cannot read chunk dataset: {path}") from exc

    cases: list[ChunkEvaluationCase] = []
    case_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = ChunkEvaluationCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ChunkDatasetError(
                f"invalid chunk dataset line {line_number}"
            ) from exc
        if case.case_id in case_ids:
            raise ChunkDatasetError(f"duplicate chunk case_id: {case.case_id}")
        case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise ChunkDatasetError("chunk dataset must contain at least one case")
    return tuple(cases)
