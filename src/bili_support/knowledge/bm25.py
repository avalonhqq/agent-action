"""无需外部服务的中文BM25基线，索引对象与活动知识版本绑定。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from math import log

from bili_support.knowledge.retrieval import (
    ChildRetrievalCandidate,
    RetrievalSource,
)
from bili_support.knowledge.tokenizers import (
    BigramSearchTokenizer,
    SearchTokenizer,
)

# 保留旧导入名，现有7A测试和Mock Reranker仍明确使用二元分词基线。
ChineseSearchTokenizer = BigramSearchTokenizer


@dataclass(frozen=True, slots=True)
class BM25Document:
    """一条可检索Child及复核所需的最小身份字段。"""

    chunk_id: str
    document_id: str
    version_id: str
    index_version_id: str
    content: str


@dataclass(frozen=True, slots=True)
class _IndexedDocument:
    """BM25内部预计算的文档词频和长度。"""

    document: BM25Document
    term_frequencies: Counter[str]
    length: int


class BM25Index:
    """不可变Okapi BM25内存索引，适合作为单进程MVP和质量基线。"""

    def __init__(
        self,
        *,
        documents: Iterable[BM25Document],
        tokenizer: SearchTokenizer,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if k1 <= 0:
            raise ValueError("BM25 k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("BM25 b must be between zero and one")
        source = tuple(documents)
        chunk_ids = [item.chunk_id for item in source]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("BM25 document chunk_id must be unique")
        self._tokenizer = tokenizer
        self._k1 = k1
        self._b = b
        self._documents = tuple(
            _IndexedDocument(
                document=document,
                term_frequencies=Counter(tokenizer.tokenize(document.content)),
                length=len(tokenizer.tokenize(document.content)),
            )
            for document in source
        )
        self._average_length = (
            sum(item.length for item in self._documents) / len(self._documents)
            if self._documents
            else 0.0
        )
        self._document_frequency = Counter(
            token
            for item in self._documents
            for token in item.term_frequencies
        )

    @property
    def document_count(self) -> int:
        return len(self._documents)

    def search(
        self,
        *,
        query: str,
        top_k: int,
    ) -> tuple[ChildRetrievalCandidate, ...]:
        """只返回至少有一个词法重叠的候选，避免无关问题被强制填满Top-K。"""

        if top_k < 1:
            raise ValueError("BM25 top_k must be positive")
        query_terms = tuple(dict.fromkeys(self._tokenizer.tokenize(query)))
        if not query_terms or not self._documents:
            return ()
        scored: list[tuple[float, BM25Document]] = []
        for indexed in self._documents:
            score = sum(
                self._term_score(term=term, document=indexed)
                for term in query_terms
            )
            if score > 0:
                scored.append((score, indexed.document))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return tuple(
            ChildRetrievalCandidate(
                chunk_id=document.chunk_id,
                document_id=document.document_id,
                version_id=document.version_id,
                index_version_id=document.index_version_id,
                source=RetrievalSource.BM25,
                score=score,
            )
            for score, document in scored[:top_k]
        )

    def _term_score(self, *, term: str, document: _IndexedDocument) -> float:
        frequency = document.term_frequencies.get(term, 0)
        if frequency == 0:
            return 0.0
        document_count = len(self._documents)
        document_frequency = self._document_frequency[term]
        # Robertson/Sparck Jones的平滑IDF，常见词仍保持非负。
        inverse_document_frequency = log(
            1
            + (
                document_count
                - document_frequency
                + 0.5
            )
            / (document_frequency + 0.5)
        )
        length_ratio = (
            document.length / self._average_length
            if self._average_length > 0
            else 0.0
        )
        denominator = frequency + self._k1 * (
            1 - self._b + self._b * length_ratio
        )
        return inverse_document_frequency * (
            frequency * (self._k1 + 1) / denominator
        )
