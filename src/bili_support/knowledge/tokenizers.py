"""BM25使用的可替换中文搜索分词器与装配工厂。"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import jieba  # type: ignore[import-untyped]

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u4e00-\u9fff]+")
DEFAULT_DOMAIN_TERMS = frozenset(
    {
        "大会员",
        "连续包月",
        "自动续费",
        "订阅管理",
        "支付成功",
        "未到账",
        "订单号",
        "支付流水",
        "无理由退款",
        "重复扣费",
        "会员权益",
        "有效期",
        "兑换码",
        "电视端",
        "客户端",
        "版权限制",
        "人工核查",
        "账号申诉",
        "创作激励",
        "账号",
        "退款",
        "扣费",
        "套餐",
        "视频",
        "会员",
    }
)


class BM25TokenizerKind(StrEnum):
    """可通过配置和评估CLI选择的中文BM25分词实现。"""

    BIGRAM = "bigram"  # 领域词 + 中文相邻二元组，作为确定性实验基线
    JIEBA = "jieba"  # Jieba搜索模式 + 受控哔哩哔哩业务词典


class SearchTokenizer(Protocol):
    """BM25只依赖稳定分词契约，不感知Jieba或二元组实现。"""

    def tokenize(self, text: str) -> tuple[str, ...]:
        """把查询或Child正文转成有序、可重复的搜索Token。"""


class BigramSearchTokenizer:
    """领域词与字符二元组结合的7A确定性分词基线。"""

    def __init__(
        self,
        domain_terms: Iterable[str] = DEFAULT_DOMAIN_TERMS,
    ) -> None:
        self._domain_terms = _normalize_domain_terms(domain_terms)

    def tokenize(self, text: str) -> tuple[str, ...]:
        """英文按词、中文按领域词和相邻二元组切分。"""

        tokens: list[str] = []
        for span in _TOKEN_PATTERN.findall(text.casefold()):
            if span.isascii():
                tokens.append(span)
                continue
            tokens.extend(term for term in self._domain_terms if term in span)
            if len(span) == 1:
                tokens.append(span)
            else:
                tokens.extend(
                    span[index : index + 2]
                    for index in range(len(span) - 1)
                )
        return tuple(tokens)


class JiebaSearchTokenizer:
    """使用Jieba搜索模式，并加载受控业务词典的中文分词器。

    每个实例使用独立``jieba.Tokenizer``，避免测试或其他模块修改Jieba全局词典。
    默认关闭HMM，确保固定词典和输入可以稳定重放。
    """

    def __init__(
        self,
        *,
        domain_terms: Iterable[str] = DEFAULT_DOMAIN_TERMS,
        user_dictionary_path: str | Path | None = None,
        hmm_enabled: bool = False,
    ) -> None:
        self._tokenizer = jieba.Tokenizer()
        self._hmm_enabled = hmm_enabled
        for term in _normalize_domain_terms(domain_terms):
            self._tokenizer.add_word(term)
        if user_dictionary_path is not None:
            path = _resolve_user_dictionary_path(user_dictionary_path)
            if not path.is_file():
                raise ValueError(f"BM25 Jieba user dictionary does not exist: {path}")
            self._tokenizer.load_userdict(str(path))

    def tokenize(self, text: str) -> tuple[str, ...]:
        """英文数字保持完整，中文使用适合倒排索引的搜索模式。"""

        tokens: list[str] = []
        for span in _TOKEN_PATTERN.findall(text.casefold()):
            if span.isascii():
                tokens.append(span)
                continue
            tokens.extend(
                token.strip()
                for token in self._tokenizer.cut_for_search(
                    span,
                    HMM=self._hmm_enabled,
                )
                if token.strip()
            )
        return tuple(tokens)


def create_search_tokenizer(
    *,
    kind: BM25TokenizerKind,
    user_dictionary_path: str | Path | None = None,
    jieba_hmm_enabled: bool = False,
) -> SearchTokenizer:
    """集中装配实现，应用和离线评估共享完全相同的选择规则。"""

    if kind is BM25TokenizerKind.BIGRAM:
        return BigramSearchTokenizer()
    return JiebaSearchTokenizer(
        user_dictionary_path=user_dictionary_path,
        hmm_enabled=jieba_hmm_enabled,
    )


def _normalize_domain_terms(domain_terms: Iterable[str]) -> tuple[str, ...]:
    normalized = {term.strip().casefold() for term in domain_terms if term.strip()}
    return tuple(sorted(normalized, key=lambda item: (-len(item), item)))


def _resolve_user_dictionary_path(value: str | Path) -> Path:
    """相对路径先按启动目录解析，再按项目根解析，兼容CLI和隔离测试。"""

    path = Path(value)
    if path.is_absolute() or path.is_file():
        return path
    project_relative = Path(__file__).resolve().parents[3] / path
    return project_relative if project_relative.is_file() else path
