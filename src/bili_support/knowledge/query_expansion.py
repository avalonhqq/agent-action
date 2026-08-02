"""7D受控补检索查询：只强调已识别实体，不做自由同义词扩写。"""

from bili_support.knowledge.coverage import RequiredEntity


def build_supplemental_query(
    *,
    question: str,
    missing: tuple[RequiredEntity, ...],
) -> str:
    """将全部缺失实体合并为一次查询，保证补检索次数上限为一。"""

    if not missing:
        raise ValueError("supplemental query requires missing entities")
    names = "、".join(item.name for item in missing)
    return f"{question}\n重点检索对象：{names}"
