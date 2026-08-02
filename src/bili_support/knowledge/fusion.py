"""第7周7B：确定性的Reciprocal Rank Fusion（RRF）实现。"""

from __future__ import annotations

from collections.abc import Sequence

from bili_support.knowledge.retrieval import (
    ChildRetrievalCandidate,
    FusedChildRetrievalCandidate,
    RetrievalChannelEvidence,
)


class ReciprocalRankFusion:
    """只根据各通道内部排名融合候选，不比较不同通道的原始分数。

    `rank_constant`越大，相邻名次的贡献差距越平缓。首版采用论文和工程中常见的60，
    后续只能依据固定评估集调整，不能针对单个问题手工调参。
    """

    def __init__(self, *, rank_constant: int = 60) -> None:
        if rank_constant < 1:
            raise ValueError("RRF rank_constant must be positive")
        self._rank_constant = rank_constant

    def fuse(
        self,
        rankings: Sequence[Sequence[ChildRetrievalCandidate]],
    ) -> tuple[FusedChildRetrievalCandidate, ...]:
        """按Chunk ID去重，返回携带每路排名、原始分数和RRF贡献的候选。"""

        candidates: dict[str, ChildRetrievalCandidate] = {}
        evidence: dict[str, list[RetrievalChannelEvidence]] = {}
        for ranking in rankings:
            seen_in_channel: set[str] = set()
            for rank, candidate in enumerate(ranking, start=1):
                # 同一召回器重复返回Chunk时只接受第一次，也就是最高排名。
                if candidate.chunk_id in seen_in_channel:
                    continue
                seen_in_channel.add(candidate.chunk_id)
                known = candidates.get(candidate.chunk_id)
                if known is not None and self._identity(known) != self._identity(
                    candidate
                ):
                    raise ValueError(
                        "retrieval channels returned conflicting chunk identity"
                    )
                candidates.setdefault(candidate.chunk_id, candidate)
                evidence.setdefault(candidate.chunk_id, []).append(
                    RetrievalChannelEvidence(
                        source=candidate.source,
                        rank=rank,
                        raw_score=candidate.score,
                        rrf_contribution=1 / (self._rank_constant + rank),
                    )
                )

        fused = tuple(
            FusedChildRetrievalCandidate(
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                version_id=candidate.version_id,
                index_version_id=candidate.index_version_id,
                fused_score=sum(
                    item.rrf_contribution for item in evidence[chunk_id]
                ),
                channel_evidence=tuple(evidence[chunk_id]),
            )
            for chunk_id, candidate in candidates.items()
        )
        return tuple(
            sorted(
                fused,
                key=lambda item: (
                    -item.fused_score,
                    min(part.rank for part in item.channel_evidence),
                    item.chunk_id,
                ),
            )
        )

    @staticmethod
    def _identity(candidate: ChildRetrievalCandidate) -> tuple[str, ...]:
        """同一Chunk跨通道必须指向同一文档、版本和索引版本。"""

        return (
            candidate.chunk_id,
            candidate.document_id,
            candidate.version_id,
            candidate.index_version_id,
        )
