"""固定JSONL检索Golden Dataset的严格加载器。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bili_support.evaluation.retrieval_types import RetrievalEvaluationCase


class RetrievalDatasetError(ValueError):
    """数据集不可读、JSON非法或不满足检索金标准契约。"""


def load_retrieval_evaluation_cases(
    path: Path,
) -> tuple[RetrievalEvaluationCase, ...]:
    """逐行加载并拒绝坏行、空数据集和重复Case ID。"""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RetrievalDatasetError(
            f"cannot read retrieval dataset: {path}"
        ) from exc

    cases: list[RetrievalEvaluationCase] = []
    case_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            case = RetrievalEvaluationCase.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RetrievalDatasetError(
                f"invalid retrieval dataset line {line_number}"
            ) from exc
        if case.case_id in case_ids:
            raise RetrievalDatasetError(
                f"duplicate retrieval case_id: {case.case_id}"
            )
        case_ids.add(case.case_id)
        cases.append(case)

    if not cases:
        raise RetrievalDatasetError(
            "retrieval dataset must contain at least one case"
        )
    return tuple(cases)
