"""领域词典发布制品的确定性生成规则。"""

from bili_support.knowledge.dictionary import render_jieba_dictionary


def test_render_dictionary_deduplicates_aliases_and_keeps_highest_frequency() -> None:
    content = render_jieba_dictionary(
        (
            ("大会员", ("会员",), 10000),
            ("会员权益", ("会员",), 8000),
        )
    )

    assert content == "会员 10000 nz\n会员权益 8000 nz\n大会员 10000 nz\n"
