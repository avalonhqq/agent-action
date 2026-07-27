import pytest

from bili_support.knowledge import (
    ChunkKind,
    DocumentKnowledgeType,
    FaqChunkStrategy,
    ManualChunkStrategy,
    PolicyChunkStrategy,
    StrategySelector,
    TableChunkStrategy,
)
from bili_support.knowledge.types import LoadedSourceBlock, SourceBlockType


def _block(
    content: str,
    *,
    ordinal: int,
    block_type: SourceBlockType = SourceBlockType.PARAGRAPH,
    heading_path: tuple[str, ...] = ("大会员",),
) -> LoadedSourceBlock:
    return LoadedSourceBlock(
        ordinal=ordinal,
        block_type=block_type,
        content=content,
        page_number=3,
        heading_path=heading_path,
        metadata={"fixture": True},
    )


def test_table_strategy_keeps_full_table_and_creates_one_child_per_row() -> None:
    chunks = TableChunkStrategy().chunk(
        blocks=(
            _block(
                "第1行：套餐=月卡；价格=25元\n第2行：套餐=年卡；价格=168元",
                ordinal=3,
                block_type=SourceBlockType.TABLE,
                heading_path=("大会员", "套餐价格"),
            ),
        )
    )

    parent, first, second = chunks
    assert parent.kind is ChunkKind.PARENT
    assert "第1行：套餐=月卡；价格=25元" in parent.content
    assert first.content == "大会员 / 套餐价格：套餐=月卡；价格=25元"
    assert second.content == "大会员 / 套餐价格：套餐=年卡；价格=168元"
    assert first.parent_local_id == parent.local_id == second.parent_local_id
    assert first.metadata["row_index"] == 0


def test_table_strategy_rejects_non_table_blocks() -> None:
    with pytest.raises(ValueError, match="only accepts TABLE"):
        TableChunkStrategy().chunk(blocks=(_block("普通正文", ordinal=1),))


def test_faq_strategy_uses_question_for_child_and_full_answer_for_parent() -> None:
    chunks = FaqChunkStrategy().chunk(
        blocks=(
            _block(
                "问：大会员可以退款吗？\n答：重复扣费可以申请退款，已消耗权益不支持退款。",
                ordinal=4,
            ),
        )
    )

    parent, child = chunks
    assert parent.content == (
        "问题：大会员可以退款吗？\n"
        "答案：重复扣费可以申请退款，已消耗权益不支持退款。"
    )
    assert child.content == "大会员：大会员可以退款吗？"
    assert child.parent_local_id == parent.local_id


def test_faq_strategy_pairs_question_heading_with_following_answer() -> None:
    chunks = FaqChunkStrategy().chunk(
        blocks=(
            _block(
                "如何关闭自动续费？",
                ordinal=0,
                block_type=SourceBlockType.HEADING,
                heading_path=("如何关闭自动续费？",),
            ),
            _block(
                "请在签约的支付渠道关闭自动扣款服务。",
                ordinal=1,
                heading_path=("如何关闭自动续费？",),
            ),
        )
    )

    assert len(chunks) == 2
    assert chunks[0].content.startswith("问题：如何关闭自动续费？")
    assert chunks[1].parent_local_id == chunks[0].local_id


def test_faq_strategy_parses_multiple_pairs_and_keywords_from_one_block() -> None:
    chunks = FaqChunkStrategy().chunk(
        blocks=(
            _block(
                "Q：大会员开通后多久生效？\n"
                "A：支付成功后立即生效。\n"
                "关键词：生效时间、未到账、支付成功\n"
                "Q：开通大会员需要多少钱？\n"
                "A：真实价格以结算页面为准。\n"
                "关键词：价格、套餐、优惠",
                ordinal=7,
                heading_path=("客服FAQ",),
            ),
        )
    )

    first_parent, first_child, second_parent, second_child = chunks
    assert first_parent.content == (
        "问题：大会员开通后多久生效？\n答案：支付成功后立即生效。"
    )
    assert first_child.content == (
        "客服FAQ：大会员开通后多久生效？\n关键词：生效时间、未到账、支付成功"
    )
    assert first_child.metadata["keywords"] == [
        "生效时间",
        "未到账",
        "支付成功",
    ]
    assert second_parent.content == (
        "问题：开通大会员需要多少钱？\n答案：真实价格以结算页面为准。"
    )
    assert second_child.metadata["keywords"] == ["价格", "套餐", "优惠"]
    assert first_child.parent_local_id == first_parent.local_id
    assert second_child.parent_local_id == second_parent.local_id


def test_faq_strategy_parses_question_answer_keywords_across_blocks() -> None:
    chunks = FaqChunkStrategy().chunk(
        blocks=(
            _block("Q：连续包月怎么取消？", ordinal=10),
            _block("A：进入原支付渠道取消订阅。", ordinal=11),
            _block("关键词：自动续费、取消订阅", ordinal=12),
        )
    )

    parent, child = chunks
    assert parent.content == (
        "问题：连续包月怎么取消？\n答案：进入原支付渠道取消订阅。"
    )
    assert child.metadata["source_block_ordinals"] == [10, 11, 12]
    assert child.metadata["keywords"] == ["自动续费", "取消订阅"]


def test_explicit_faq_question_without_answer_fails() -> None:
    with pytest.raises(ValueError, match="has no answer"):
        FaqChunkStrategy().chunk(
            blocks=(_block("Q：这个问题没有答案？", ordinal=13),)
        )


def test_manual_strategy_keeps_complete_steps_and_previous_step_context() -> None:
    chunks = ManualChunkStrategy().chunk(
        blocks=(
            _block(
                "关闭前请确认签约渠道。\n"
                "1. 打开支付渠道。\n"
                "2. 找到自动扣款服务。\n"
                "3. 选择哔哩哔哩并关闭服务。",
                ordinal=5,
                heading_path=("大会员", "关闭自动续费"),
            ),
        )
    )

    parent, first, second, third = chunks
    assert "1. 打开支付渠道。" in parent.content
    assert "操作目标：大会员 / 关闭自动续费" in first.content
    assert "前置步骤" not in first.content
    assert "前置步骤：打开支付渠道。" in second.content
    assert "前置步骤：找到自动扣款服务。" in third.content
    assert all(
        child.parent_local_id == parent.local_id
        for child in (first, second, third)
    )


def test_policy_strategy_binds_exception_to_previous_conclusion() -> None:
    chunks = PolicyChunkStrategy().chunk(
        blocks=(
            _block(
                "重复扣费可以申请退款。但已经消耗的会员权益不支持退款。"
                "申请应在扣费后七日内提交。",
                ordinal=6,
                heading_path=("大会员", "退款规则"),
            ),
        )
    )

    parent, first, second = chunks
    assert parent.kind is ChunkKind.PARENT
    assert first.content == (
        "大会员 / 退款规则：重复扣费可以申请退款。"
        "但已经消耗的会员权益不支持退款。"
    )
    assert first.metadata["contains_exception"] is True
    assert second.content.endswith("申请应在扣费后七日内提交。")


def test_selector_always_delegates_table_blocks_to_table_strategy() -> None:
    chunks = StrategySelector().select(DocumentKnowledgeType.POLICY).chunk(
        blocks=(
            _block(
                "重复扣费可以申请退款。",
                ordinal=1,
                heading_path=("退款规则",),
            ),
            _block(
                "第1行：类型=重复扣费；结果=可以退款",
                ordinal=2,
                block_type=SourceBlockType.TABLE,
                heading_path=("退款规则", "处理表"),
            ),
        )
    )

    assert any(chunk.local_id.startswith("policy-parent-") for chunk in chunks)
    assert any(chunk.local_id.startswith("table-parent-") for chunk in chunks)
    assert any(chunk.local_id.startswith("table-child-") for chunk in chunks)


def test_unrecognized_manual_content_falls_back_to_generic() -> None:
    chunks = ManualChunkStrategy().chunk(
        blocks=(_block("这是一段没有步骤编号的说明。", ordinal=9),)
    )

    assert chunks[0].local_id == "parent-9"
    assert chunks[1].local_id == "child-9-0"
