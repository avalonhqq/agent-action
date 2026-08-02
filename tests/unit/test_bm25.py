"""7A中文Tokenizer和Okapi BM25排序基线测试。"""

from bili_support.knowledge.bm25 import (
    BM25Document,
    BM25Index,
    ChineseSearchTokenizer,
)
from bili_support.knowledge.retrieval import RetrievalSource


def _document(chunk_id: str, content: str) -> BM25Document:
    return BM25Document(
        chunk_id=chunk_id,
        document_id="document-1",
        version_id="version-1",
        index_version_id="index-1",
        content=content,
    )


def test_chinese_tokenizer_keeps_domain_terms_and_unseen_bigrams() -> None:
    tokens = ChineseSearchTokenizer().tokenize(
        "如何取消连续包月，兑换礼品在哪里操作？"
    )

    assert "连续包月" in tokens
    assert "兑换" in tokens
    assert "礼品" in tokens


def test_bm25_ranks_rare_matching_terms_first() -> None:
    index = BM25Index(
        tokenizer=ChineseSearchTokenizer(),
        documents=(
            _document(
                "refund",
                "大会员重复扣费可以提交订单进行退款人工核查。",
            ),
            _document(
                "cancel",
                "连续包月需要在订阅管理中取消自动续费。",
            ),
            _document(
                "video",
                "会员视频受版权和地区限制。",
            ),
        ),
    )

    hits = index.search(query="重复扣费退款怎么办", top_k=3)

    assert hits[0].chunk_id == "refund"
    assert hits[0].source is RetrievalSource.BM25
    assert hits[0].score > 0


def test_bm25_does_not_force_fill_top_k_without_lexical_overlap() -> None:
    index = BM25Index(
        tokenizer=ChineseSearchTokenizer(domain_terms=()),
        documents=(
            _document("membership", "大会员自动续费处理说明"),
        ),
    )

    assert index.search(query="上海演唱会门票", top_k=5) == ()
