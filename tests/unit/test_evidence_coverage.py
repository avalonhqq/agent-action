"""7D受控实体提取与证据覆盖基础测试。"""

from bili_support.intent.types import EntityType, IntentEntity
from bili_support.knowledge.coverage import extract_required_entities
from bili_support.knowledge.query_expansion import build_supplemental_query


def test_controlled_lexicon_and_validated_intent_entities_are_merged() -> None:
    entities = extract_required_entities(
        question="比较连续包月和年度套餐",
        intent_entities=(
            IntentEntity(
                type=EntityType.PRODUCT,
                raw_value="会员",
                normalized_value="大会员",
            ),
        ),
    )

    assert [item.name for item in entities] == [
        "大会员",
        "连续包月",
        "年度套餐",
    ]


def test_supplemental_query_combines_missing_entities_into_one_request() -> None:
    entities = extract_required_entities(
        question="连续包月和年度套餐有什么区别",
        intent_entities=(),
    )
    query = build_supplemental_query(
        question="连续包月和年度套餐有什么区别",
        missing=entities,
    )

    assert query.count("重点检索对象") == 1
    assert "连续包月、年度套餐" in query
