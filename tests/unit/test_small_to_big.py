import pytest

from bili_support.knowledge.small_to_big import (
    ChildChunkHit,
    SmallToBigExpander,
)


def test_expansion_deduplicates_parents_and_preserves_first_hit_order() -> None:
    plans = SmallToBigExpander().plan(
        hits=[
            ChildChunkHit(chunk_id="child-a", score=0.82),
            ChildChunkHit(chunk_id="child-c", score=0.79),
            ChildChunkHit(chunk_id="child-b", score=0.91),
            ChildChunkHit(chunk_id="child-a", score=0.99),
        ],
        child_parent_ids={
            "child-a": "parent-1",
            "child-b": "parent-1",
            "child-c": "parent-2",
        },
    )

    assert [plan.parent_chunk_id for plan in plans] == ["parent-1", "parent-2"]
    assert plans[0].matched_child_ids == ("child-a", "child-b")
    assert plans[0].best_child_score == 0.91
    assert plans[0].first_child_rank == 1
    assert plans[1].first_child_rank == 2


def test_expansion_rejects_child_without_resolved_parent() -> None:
    with pytest.raises(ValueError, match="has no resolved parent"):
        SmallToBigExpander().plan(
            hits=[ChildChunkHit(chunk_id="missing", score=0.8)],
            child_parent_ids={},
        )


@pytest.mark.parametrize("score", [float("inf"), float("-inf"), float("nan")])
def test_child_hit_rejects_non_finite_score(score: float) -> None:
    with pytest.raises(ValueError, match="must be finite"):
        ChildChunkHit(chunk_id="child-a", score=score)
