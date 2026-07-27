from bili_support.knowledge import (
    ChunkKind,
    DocumentKnowledgeType,
    GenericChunkStrategy,
    StrategySelector,
)
from bili_support.knowledge.loaders import create_default_loader_registry


def test_markdown_loader_output_can_flow_into_generic_chunking() -> None:
    """验收5A与5B-1边界：Loader输出无需改写即可交给ChunkStrategy。"""

    loaded = create_default_loader_registry().load(
        content="""# 大会员

## 自动续费

大会员到期前一天会自动续费。
用户可以在支付渠道关闭自动续费。
""".encode(),
        filename="membership.md",
        media_type="text/markdown",
    )

    chunks = GenericChunkStrategy(
        child_max_chars=18,
        child_overlap_chars=2,
    ).chunk(blocks=loaded.blocks)

    parents = [chunk for chunk in chunks if chunk.kind is ChunkKind.PARENT]
    children = [chunk for chunk in chunks if chunk.kind is ChunkKind.CHILD]

    assert len(parents) == 1
    assert len(children) == 2
    assert all(child.parent_local_id == parents[0].local_id for child in children)
    assert parents[0].content.startswith("标题：大会员 > 自动续费")
    assert all(child.content.startswith("大会员 / 自动续费：") for child in children)
    assert {chunk.source_block_ordinal for chunk in chunks} == {2}


def test_markdown_policy_with_table_uses_document_and_table_strategies() -> None:
    loaded = create_default_loader_registry().load(
        content="""# 退款规则

重复扣费可以申请退款。但已消耗权益不支持退款。

| 类型 | 处理结果 |
|---|---|
| 重复扣费 | 可以退款 |
""".encode(),
        filename="refund-policy.md",
        media_type="text/markdown",
    )

    chunks = StrategySelector().select(DocumentKnowledgeType.POLICY).chunk(
        blocks=loaded.blocks
    )

    assert any(chunk.local_id.startswith("policy-child-") for chunk in chunks)
    assert any(chunk.local_id.startswith("table-child-") for chunk in chunks)
    policy_child = next(
        chunk for chunk in chunks if chunk.local_id.startswith("policy-child-")
    )
    assert "但已消耗权益不支持退款" in policy_child.content
