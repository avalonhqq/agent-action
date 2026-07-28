"""固定JSONL Chunk评估集的加载与领域校验。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bili_support.evaluation.chunk_types import ChunkEvaluationCase


class ChunkDatasetError(ValueError):
    """评估集不可读、JSON非法或不满足Chunk金标准契约。"""


def load_chunk_evaluation_cases(path: Path) -> tuple[ChunkEvaluationCase, ...]:
    """逐行读取JSONL，并拒绝坏行、空数据集和重复Case ID。

    JSONL采用“一行一Case”，这样新增样本时Git diff清晰，单行错误也能报告准确行号。
    """

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ChunkDatasetError(f"cannot read chunk dataset: {path}") from exc

    cases: list[ChunkEvaluationCase] = []
    # case_ids独立维护，避免同一业务样本被重复计分而抬高某类结构权重。
    case_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            # 允许文件末尾或人工分组时出现空行，不把空行当成Case。
            continue
        try:
            # json.loads只保证语法，model_validate继续执行枚举、范围和跨字段校验。
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
