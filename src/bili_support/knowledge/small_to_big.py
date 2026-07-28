"""把精确命中的Child聚合为可供大模型阅读的Parent上下文。

本模块只处理ID、分数和顺序，不访问数据库，也不知道命中来自BM25还是向量检索。
数据库批量读取和资源权限校验由KnowledgeIngestionService负责。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class ChildChunkHit:
    """一个检索器返回的Child命中；列表位置就是相关性排序。

    score必须统一为“越大越相关”。如果底层向量库返回距离，检索适配器应先完成转换。
    """

    chunk_id: str  # 已持久化的Child UUID，而不是ChunkDraft.local_id
    score: float  # 统一后的相关性分数；必须有限且越大越相关

    def __post_init__(self) -> None:
        """在进入聚合算法前阻止空ID和NaN/Infinity破坏排序与JSON输出。"""

        if not self.chunk_id.strip():
            raise ValueError("child chunk id must not be blank")
        if not isfinite(self.score):
            raise ValueError("child hit score must be finite")


@dataclass(frozen=True, slots=True)
class ParentExpansionPlan:
    """一个Parent的回溯计划，尚未携带数据库中的Parent正文。

    算法先生成Plan，Service再一次性批量读取所有Parent，避免每个Child各查一次数据库。
    """

    parent_chunk_id: str  # 第二次批量查询需要的Parent UUID
    matched_child_ids: tuple[str, ...]  # 去重且保持命中顺序的Child证据
    best_child_score: float  # 该Parent关联Child中的最高相关性
    # 从1开始，便于直接展示和排查检索排序。
    first_child_rank: int


@dataclass(slots=True)
class _MutableParentPlan:
    """聚合过程中的内部可变状态，结束后会转换成不可变公开契约。

    该类型以下划线开头，不属于跨模块公共契约；可变list只存在于一次plan调用内部。
    """

    matched_child_ids: list[str]  # 遍历命中时追加同Parent下的新Child
    best_child_score: float  # 每次聚合取max
    first_child_rank: int  # 创建后不变，用来稳定Parent排序


class SmallToBigExpander:
    """按首次Child命中顺序聚合Parent，同时保留父级下的命中证据。"""

    def plan(
        self,
        *,
        hits: Sequence[ChildChunkHit],
        child_parent_ids: Mapping[str, str],
    ) -> tuple[ParentExpansionPlan, ...]:
        """生成批量读取Parent所需的稳定计划。

        同一Child重复出现时只记录一次；同一Parent被多个Child命中时只返回一次。
        Parent的顺序取它第一次被命中的位置，分数取所属Child命中的最高分。
        """

        mutable: dict[str, _MutableParentPlan] = {}
        # 检索融合可能重复返回同一Child，先按首次出现去重以免证据和分数重复计入。
        seen_child_ids: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            if hit.chunk_id in seen_child_ids:
                continue
            seen_child_ids.add(hit.chunk_id)

            parent_id = child_parent_ids.get(hit.chunk_id)
            if parent_id is None:
                raise ValueError(f"child chunk has no resolved parent: {hit.chunk_id}")

            current = mutable.get(parent_id)
            if current is None:
                # Python dict保持插入顺序，因此首次Parent出现顺序就是最终输出顺序。
                mutable[parent_id] = _MutableParentPlan(
                    matched_child_ids=[hit.chunk_id],
                    best_child_score=hit.score,
                    first_child_rank=rank,
                )
                continue

            current.matched_child_ids.append(hit.chunk_id)
            # 同一Parent的解释分数采用最高Child分数，但不据此重排首次命中顺序。
            current.best_child_score = max(current.best_child_score, hit.score)

        return tuple(
            ParentExpansionPlan(
                parent_chunk_id=parent_id,
                matched_child_ids=tuple(values.matched_child_ids),
                best_child_score=values.best_child_score,
                first_child_rank=values.first_child_rank,
            )
            for parent_id, values in mutable.items()
        )
