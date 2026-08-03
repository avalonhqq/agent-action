"""7A-2可替换二元/Jieba搜索分词器测试。"""

from pathlib import Path
from typing import cast

import pytest

from bili_support.knowledge.tokenizers import (
    BigramSearchTokenizer,
    BM25TokenizerKind,
    JiebaSearchTokenizer,
    create_search_tokenizer,
)


def test_jieba_search_keeps_reviewed_business_terms() -> None:
    tokenizer = JiebaSearchTokenizer()

    tokens = tokenizer.tokenize("大会员连续包月如何取消自动续费？")

    assert "大会员" in tokens
    assert "连续包月" in tokens
    assert "自动续费" in tokens
    assert "载客" not in tokenizer.tokenize("卸载客户端")


def test_jieba_search_preserves_ascii_identifiers() -> None:
    tokens = JiebaSearchTokenizer().tokenize("订单 UID_12345 支付失败")

    assert "uid_12345" in tokens


def test_jieba_loads_isolated_user_dictionary(tmp_path: Path) -> None:
    dictionary = tmp_path / "business.txt"
    dictionary.write_text("硬核会员 10000 nz\n", encoding="utf-8")

    custom = JiebaSearchTokenizer(user_dictionary_path=dictionary)
    baseline = JiebaSearchTokenizer(domain_terms=())

    assert "硬核会员" in custom.tokenize("硬核会员权益")
    assert "硬核会员" not in baseline.tokenize("硬核会员权益")


def test_factory_keeps_bigram_as_explicit_baseline() -> None:
    tokenizer = cast(
        BigramSearchTokenizer,
        create_search_tokenizer(kind=BM25TokenizerKind.BIGRAM),
    )

    assert isinstance(tokenizer, BigramSearchTokenizer)
    assert "礼品" in tokenizer.tokenize("兑换礼品")


def test_jieba_rejects_missing_user_dictionary(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        JiebaSearchTokenizer(user_dictionary_path=tmp_path / "missing.txt")


def test_jieba_hot_reloads_atomically_replaced_dictionary(tmp_path: Path) -> None:
    dictionary = tmp_path / "business.txt"
    dictionary.write_text("硬核会员 10000 nz\n", encoding="utf-8")
    tokenizer = JiebaSearchTokenizer(user_dictionary_path=dictionary)
    first_version = tokenizer.cache_version

    replacement = tmp_path / "replacement.txt"
    replacement.write_text("花火商单 11000 nz\n", encoding="utf-8")
    replacement.replace(dictionary)

    assert tokenizer.cache_version != first_version
    assert "花火商单" in tokenizer.tokenize("花火商单报价")
