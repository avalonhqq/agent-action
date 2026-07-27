import pytest
from pydantic import ValidationError

from bili_support.knowledge.chunking import (
    ChunkDraft,
    ChunkKind,
    GenericChunkStrategy,
)
from bili_support.knowledge.types import LoadedSourceBlock, SourceBlockType


def _block(
    content: str,
    *,
    ordinal: int = 1,
    block_type: SourceBlockType = SourceBlockType.PARAGRAPH,
) -> LoadedSourceBlock:
    return LoadedSourceBlock(
        ordinal=ordinal,
        block_type=block_type,
        content=content,
        page_number=2,
        heading_path=("大会员", "自动续费"),
        metadata={"loader_hint": "fixture"},
    )


def test_short_block_generates_parent_and_child_with_trace_metadata() -> None:
    chunks = GenericChunkStrategy(
        child_max_chars=80,
        child_overlap_chars=8,
    ).chunk(
        blocks=(_block("用户可以在支付渠道关闭自动续费。"),),
    )

    parent, child = chunks
    assert parent.kind is ChunkKind.PARENT
    assert parent.parent_local_id is None
    assert parent.content == (
        "标题：大会员 > 自动续费\n正文：用户可以在支付渠道关闭自动续费。"
    )
    assert child.kind is ChunkKind.CHILD
    assert child.parent_local_id == parent.local_id
    assert child.content == "大会员 / 自动续费：用户可以在支付渠道关闭自动续费。"
    assert child.metadata["page_number"] == 2
    assert child.metadata["heading_path"] == ["大会员", "自动续费"]
    assert child.metadata["source_metadata"] == {"loader_hint": "fixture"}


def test_sentences_are_packed_without_breaking_natural_boundaries() -> None:
    chunks = GenericChunkStrategy(
        child_max_chars=10,
        child_overlap_chars=2,
    ).chunk(
        blocks=(_block("第一句话。第二句话！第三句话？"),),
    )

    children = [chunk for chunk in chunks if chunk.kind is ChunkKind.CHILD]
    assert [chunk.content for chunk in children] == [
        "大会员 / 自动续费：第一句话。第二句话！",
        "大会员 / 自动续费：第三句话？",
    ]
    assert all(int(chunk.metadata["body_char_count"]) <= 10 for chunk in children)


def test_oversized_sentence_falls_back_to_bounded_overlap_windows() -> None:
    chunks = GenericChunkStrategy(
        child_max_chars=5,
        child_overlap_chars=2,
    ).chunk(blocks=(_block("abcdefghijk"),))

    children = [chunk for chunk in chunks if chunk.kind is ChunkKind.CHILD]
    assert [chunk.content for chunk in children] == [
        "大会员 / 自动续费：abcde",
        "大会员 / 自动续费：defgh",
        "大会员 / 自动续费：ghijk",
    ]


def test_line_boundaries_are_preserved_when_short_lines_share_a_child() -> None:
    chunks = GenericChunkStrategy(
        child_max_chars=20,
        child_overlap_chars=2,
    ).chunk(blocks=(_block("步骤一\n步骤二\n步骤三"),))

    child = next(chunk for chunk in chunks if chunk.kind is ChunkKind.CHILD)
    assert child.content == "大会员 / 自动续费：步骤一\n步骤二\n步骤三"


def test_heading_blocks_are_not_emitted_as_standalone_chunks() -> None:
    chunks = GenericChunkStrategy().chunk(
        blocks=(
            _block("大会员", ordinal=0, block_type=SourceBlockType.HEADING),
            _block("会员权益在有效期内可用。", ordinal=1),
        )
    )

    assert {chunk.source_block_ordinal for chunk in chunks} == {1}


def test_duplicate_source_ordinals_fail_before_local_ids_collide() -> None:
    strategy = GenericChunkStrategy()

    with pytest.raises(ValueError, match="duplicate source block ordinal"):
        strategy.chunk(
            blocks=(
                _block("第一段", ordinal=1),
                _block("第二段", ordinal=1),
            )
        )


@pytest.mark.parametrize(
    ("max_chars", "overlap"),
    [(0, 0), (10, -1), (10, 10), (10, 11)],
)
def test_invalid_window_configuration_fails_fast(
    max_chars: int,
    overlap: int,
) -> None:
    with pytest.raises(ValueError):
        GenericChunkStrategy(
            child_max_chars=max_chars,
            child_overlap_chars=overlap,
        )


def test_chunk_contract_requires_correct_parent_reference() -> None:
    with pytest.raises(ValidationError):
        ChunkDraft(
            local_id="child-1-0",
            kind=ChunkKind.CHILD,
            content="正文",
            source_block_ordinal=1,
        )

    with pytest.raises(ValidationError):
        ChunkDraft(
            local_id="parent-1",
            kind=ChunkKind.PARENT,
            content="正文",
            source_block_ordinal=1,
            parent_local_id="parent-0",
        )

    with pytest.raises(ValidationError):
        ChunkDraft(
            local_id="child-1-0",
            kind=ChunkKind.CHILD,
            content="正文",
            source_block_ordinal=1,
            parent_local_id="   ",
        )
