"""7B RRF融合的确定性、去重和可解释证据测试。"""

import pytest

from bili_support.knowledge.fusion import ReciprocalRankFusion
from bili_support.knowledge.retrieval import (
    ChildRetrievalCandidate,
    RetrievalSource,
)


def _candidate(
    chunk_id: str,
    *,
    source: RetrievalSource,
    score: float,
    document_id: str = "document-1",
) -> ChildRetrievalCandidate:
    return ChildRetrievalCandidate(
        chunk_id=chunk_id,
        document_id=document_id,
        version_id="version-1",
        index_version_id="index-1",
        source=source,
        score=score,
    )


def test_rrf_deduplicates_and_promotes_candidates_seen_by_both_channels() -> None:
    fused = ReciprocalRankFusion(rank_constant=60).fuse(
        (
            (
                _candidate("a", source=RetrievalSource.VECTOR, score=0.99),
                _candidate("b", source=RetrievalSource.VECTOR, score=0.80),
                _candidate("c", source=RetrievalSource.VECTOR, score=0.70),
            ),
            (
                _candidate("b", source=RetrievalSource.BM25, score=12.0),
                _candidate("d", source=RetrievalSource.BM25, score=8.0),
                _candidate("a", source=RetrievalSource.BM25, score=7.0),
            ),
        )
    )

    assert [item.chunk_id for item in fused] == ["b", "a", "d", "c"]
    assert [part.source for part in fused[0].channel_evidence] == [
        RetrievalSource.VECTOR,
        RetrievalSource.BM25,
    ]
    assert [part.rank for part in fused[0].channel_evidence] == [2, 1]
    assert fused[0].score == fused[0].fused_score
    assert fused[0].source is RetrievalSource.HYBRID


def test_rrf_order_uses_ranks_instead_of_incompatible_raw_score_scales() -> None:
    fusion = ReciprocalRankFusion()
    first = fusion.fuse(
        (
            (_candidate("a", source=RetrievalSource.VECTOR, score=0.1),),
            (_candidate("b", source=RetrievalSource.BM25, score=1_000_000),),
        )
    )
    second = fusion.fuse(
        (
            (_candidate("a", source=RetrievalSource.VECTOR, score=999.0),),
            (_candidate("b", source=RetrievalSource.BM25, score=0.001),),
        )
    )

    assert [item.chunk_id for item in first] == ["a", "b"]
    assert [item.chunk_id for item in second] == ["a", "b"]


def test_rrf_rejects_conflicting_identity_for_the_same_chunk() -> None:
    with pytest.raises(ValueError, match="conflicting chunk identity"):
        ReciprocalRankFusion().fuse(
            (
                (_candidate("a", source=RetrievalSource.VECTOR, score=0.9),),
                (
                    _candidate(
                        "a",
                        source=RetrievalSource.BM25,
                        score=9.0,
                        document_id="other-document",
                    ),
                ),
            )
        )
