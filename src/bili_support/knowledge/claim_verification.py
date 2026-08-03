"""第8周8E：生产级Claim校验，组合确定性硬规则与本地中文NLI模型。"""

from __future__ import annotations

import asyncio
import json
import re
import threading
from collections.abc import Sequence
from enum import StrEnum
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from bili_support.knowledge.grounded_answer import GroundedAnswer

_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:%|分钟|小时|天|元|个月|年)?")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_LATIN_WORD = re.compile(r"[a-z0-9]+")
_NEGATIONS = ("不支持", "不能", "不会", "不得", "无法", "未", "没有", "不可")
_BUSINESS_PREDICATES = {
    "退款",
    "退费",
    "转移",
    "到账",
    "显示",
    "续费",
    "生效",
    "支持",
    "扣费",
    "封禁",
    "登录",
    "支付",
    "取消",
}
_HARD_FAILURE_REASONS = {"missing_evidence_content", "numeric_fact_missing", "negation_conflict"}


class ClaimSupportStatus(StrEnum):
    """单条声明相对于引用证据的结论；unknown表示模型无法可靠裁决。"""

    SUPPORTED = "supported"
    PARTIAL = "partial"  # 兼容第8B历史报告，新NLI路径不再产生此值。
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    UNKNOWN = "unknown"


class GroundedVerificationDecision(StrEnum):
    """答案发布策略：degrade只能发布由已支持Claim重建的安全答案。"""

    PASS = "pass"
    DEGRADE = "degrade"
    REJECT = "reject"


class VerificationMode(StrEnum):
    """shadow只观测语义模型，enforce把语义结论纳入发布门禁。"""

    SHADOW = "shadow"
    ENFORCE = "enforce"


class EvidenceRecord(BaseModel):
    """从本次Prompt证据JSON解析出的最小可信记录。"""

    model_config = ConfigDict(frozen=True, extra="ignore")
    evidence_id: str = Field(pattern=r"^E[1-9][0-9]*$")
    content: str = Field(min_length=1)
    document_title: str | None = None
    business_domain: str | None = None

    def semantic_text(self) -> str:
        """把检索元数据纳入NLI前提，补足“大会员”等省略的业务主语。"""

        prefix = f"关于{self.document_title}：" if self.document_title else ""
        return prefix + self.content


class ClaimVerification(BaseModel):
    """逐Claim裁决以及可审计的三分类概率。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    claim_text: str
    evidence_ids: tuple[str, ...]
    status: ClaimSupportStatus
    support_score: float = Field(ge=0.0, le=1.0)
    reason_code: str
    entailment_score: float | None = Field(default=None, ge=0.0, le=1.0)
    neutral_score: float | None = Field(default=None, ge=0.0, le=1.0)
    contradiction_score: float | None = Field(default=None, ge=0.0, le=1.0)

    @property
    def hard_failure(self) -> bool:
        """硬失败在Shadow模式也不可绕过。"""

        return self.reason_code in _HARD_FAILURE_REASONS


class GroundedVerificationResult(BaseModel):
    """生产审计结果，记录执行模式、真实模型、耗时和逐Claim概率。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    decision: GroundedVerificationDecision
    claims: tuple[ClaimVerification, ...]
    mode: VerificationMode = VerificationMode.ENFORCE
    provider: str = "deterministic"
    model: str | None = None
    latency_ms: float = Field(default=0.0, ge=0.0)
    error_code: str | None = None

    @property
    def supported_count(self) -> int:
        return sum(item.status is ClaimSupportStatus.SUPPORTED for item in self.claims)

    @property
    def partial_count(self) -> int:
        return sum(item.status is ClaimSupportStatus.PARTIAL for item in self.claims)

    @property
    def unsupported_count(self) -> int:
        return sum(item.status is ClaimSupportStatus.UNSUPPORTED for item in self.claims)

    @property
    def conflict_count(self) -> int:
        return sum(item.status is ClaimSupportStatus.CONFLICT for item in self.claims)

    @property
    def unknown_count(self) -> int:
        return sum(item.status is ClaimSupportStatus.UNKNOWN for item in self.claims)

    @property
    def hard_gate_failed(self) -> bool:
        return any(item.hard_failure for item in self.claims)


class ClaimVerifier(Protocol):
    """可替换的异步Claim校验接口；线上实现不能阻塞ASGI事件循环。"""

    async def verify(
        self, answer: GroundedAnswer, *, evidence: tuple[EvidenceRecord, ...]
    ) -> GroundedVerificationResult: ...


class TransformersNliClaimVerifier:
    """本地Transformers NLI校验器；模型延迟加载并在工作线程中串行推理。"""

    def __init__(
        self,
        *,
        model_name: str,
        cache_dir: str,
        device: str = "auto",
        mode: VerificationMode = VerificationMode.ENFORCE,
        entailment_threshold: float = 0.65,
        contradiction_threshold: float = 0.70,
        max_length: int = 512,
        local_files_only: bool = False,
    ) -> None:
        self.model_name = model_name
        self._cache_dir = Path(cache_dir)
        self._device_setting = device
        self._mode = mode
        self._entailment_threshold = entailment_threshold
        self._contradiction_threshold = contradiction_threshold
        self._max_length = max_length
        self._local_files_only = local_files_only
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._device = "cpu"
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()

    @property
    def ready(self) -> bool:
        """模型与Tokenizer均已加载时才可接收生产语义校验流量。"""

        return self._model is not None and self._tokenizer is not None

    async def warmup(self) -> None:
        """启动阶段加载真实模型，并用一条探针校验标签和推理设备。"""

        await asyncio.to_thread(
            self._classify_pairs,
            [("客服知识库用于回答用户问题。", "知识库可以回答用户问题。")],
        )

    async def verify(
        self, answer: GroundedAnswer, *, evidence: tuple[EvidenceRecord, ...]
    ) -> GroundedVerificationResult:
        """先执行硬规则，仅把无法确定的Claim送入真实NLI批量推理。"""

        started = perf_counter()
        by_id = {item.evidence_id: item.semantic_text() for item in evidence}
        results: list[ClaimVerification | None] = []
        unresolved: list[tuple[int, str, str, tuple[str, ...], float]] = []
        for index, claim in enumerate(answer.claims):
            evidence_text = "\n".join(by_id.get(item, "") for item in claim.evidence_ids)
            deterministic = _hard_rule_verification(claim.text, claim.evidence_ids, evidence_text)
            results.append(deterministic)
            if deterministic is None:
                unresolved.append(
                    (
                        index,
                        evidence_text,
                        claim.text,
                        claim.evidence_ids,
                        _token_coverage(claim.text, evidence_text),
                    )
                )

        error_code: str | None = None
        if unresolved:
            try:
                scores = await asyncio.to_thread(
                    self._classify_pairs,
                    [(premise, hypothesis) for _, premise, hypothesis, _, _ in unresolved],
                )
                for item, score in zip(unresolved, scores, strict=True):
                    index, _, claim_text, evidence_ids, coverage = item
                    results[index] = self._semantic_result(
                        claim_text, evidence_ids, coverage, score
                    )
            except Exception:
                # 模型不可用时失败关闭；不回退到词元启发式或Mock结论。
                error_code = "nli_verifier_unavailable"
                for index, _, claim_text, evidence_ids, coverage in unresolved:
                    results[index] = ClaimVerification(
                        claim_text=claim_text,
                        evidence_ids=evidence_ids,
                        status=ClaimSupportStatus.UNKNOWN,
                        support_score=coverage,
                        reason_code=error_code,
                    )

        finalized = tuple(item for item in results if item is not None)
        decision = _verification_decision(answer, finalized)
        return GroundedVerificationResult(
            decision=decision,
            claims=finalized,
            mode=self._mode,
            provider="transformers_nli",
            model=self.model_name,
            latency_ms=(perf_counter() - started) * 1000,
            error_code=error_code,
        )

    def _classify_pairs(self, pairs: Sequence[tuple[str, str]]) -> list[tuple[float, float, float]]:
        self._ensure_loaded()
        assert self._tokenizer is not None and self._model is not None and self._torch is not None
        with self._inference_lock, self._torch.inference_mode():
            encoded = self._tokenizer(
                [pair[0] for pair in pairs],
                [pair[1] for pair in pairs],
                padding=True,
                truncation="only_first",
                max_length=self._max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self._device) for key, value in encoded.items()}
            logits = self._model(**encoded).logits
            probabilities = self._torch.softmax(logits, dim=-1).detach().cpu().tolist()
        label_map = {
            str(value).casefold(): int(key) for key, value in self._model.config.id2label.items()
        }
        return [
            (
                float(row[_label_index(label_map, "entailment")]),
                float(row[_label_index(label_map, "neutral")]),
                float(row[_label_index(label_map, "contradiction")]),
            )
            for row in probabilities
        ]

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            torch = import_module("torch")
            transformers = import_module("transformers")
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            tokenizer = transformers.AutoTokenizer.from_pretrained(
                self.model_name,
                cache_dir=str(self._cache_dir),
                local_files_only=self._local_files_only,
            )
            model = transformers.AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                cache_dir=str(self._cache_dir),
                local_files_only=self._local_files_only,
            )
            device = self._device_setting
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            model.to(device)
            model.eval()
            self._torch, self._tokenizer, self._model, self._device = (
                torch,
                tokenizer,
                model,
                device,
            )

    def _semantic_result(
        self,
        claim_text: str,
        evidence_ids: tuple[str, ...],
        coverage: float,
        scores: tuple[float, float, float],
    ) -> ClaimVerification:
        entailment, neutral, contradiction = scores
        if contradiction >= self._contradiction_threshold and contradiction > entailment:
            status, reason = ClaimSupportStatus.CONFLICT, "nli_contradiction"
        elif entailment >= self._entailment_threshold and entailment > contradiction:
            status, reason = ClaimSupportStatus.SUPPORTED, "nli_entailment"
        else:
            status, reason = ClaimSupportStatus.UNKNOWN, "nli_inconclusive"
        return ClaimVerification(
            claim_text=claim_text,
            evidence_ids=evidence_ids,
            status=status,
            support_score=entailment,
            reason_code=reason,
            entailment_score=entailment,
            neutral_score=neutral,
            contradiction_score=contradiction,
        )


def parse_evidence_records(context_json: str) -> tuple[EvidenceRecord, ...]:
    """只接受顶层evidence数组；格式损坏时安全返回空集合。"""

    try:
        payload = json.loads(context_json)
        rows = payload.get("evidence", []) if isinstance(payload, dict) else []
        return tuple(EvidenceRecord.model_validate(item) for item in rows)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ()


def verify_grounded_answer(
    answer: GroundedAnswer, *, evidence: tuple[EvidenceRecord, ...]
) -> GroundedVerificationResult:
    """兼容离线8B报告的确定性校验；线上ChatService使用异步NLI实现。"""

    started = perf_counter()
    by_id = {item.evidence_id: item.content for item in evidence}
    results = tuple(
        _legacy_verify_claim(
            claim.text,
            claim.evidence_ids,
            "\n".join(by_id.get(item, "") for item in claim.evidence_ids),
        )
        for claim in answer.claims
    )
    return GroundedVerificationResult(
        decision=_verification_decision(answer, results),
        claims=results,
        provider="deterministic_legacy",
        latency_ms=(perf_counter() - started) * 1000,
    )


def _hard_rule_verification(
    claim: str, evidence_ids: tuple[str, ...], evidence_text: str
) -> ClaimVerification | None:
    if not evidence_text.strip():
        return _result(
            claim, evidence_ids, ClaimSupportStatus.UNSUPPORTED, 0.0, "missing_evidence_content"
        )
    normalized_claim = _normalize(claim)
    if normalized_claim and normalized_claim in _normalize(evidence_text):
        return _result(claim, evidence_ids, ClaimSupportStatus.SUPPORTED, 1.0, "exact_match")
    if set(_NUMBER.findall(claim)) - set(_NUMBER.findall(evidence_text)):
        return _result(
            claim, evidence_ids, ClaimSupportStatus.UNSUPPORTED, 0.0, "numeric_fact_missing"
        )
    score = _token_coverage(claim, evidence_text)
    if score >= 0.55 and _polarity_conflict(claim, evidence_text):
        return _result(claim, evidence_ids, ClaimSupportStatus.CONFLICT, score, "negation_conflict")
    return None


def _legacy_verify_claim(
    claim: str, evidence_ids: tuple[str, ...], evidence_text: str
) -> ClaimVerification:
    hard = _hard_rule_verification(claim, evidence_ids, evidence_text)
    if hard is not None:
        return hard
    score = _token_coverage(claim, evidence_text)
    if score >= 0.55:
        return _result(
            claim, evidence_ids, ClaimSupportStatus.SUPPORTED, score, "token_coverage_supported"
        )
    if score >= 0.35:
        return _result(
            claim, evidence_ids, ClaimSupportStatus.PARTIAL, score, "token_coverage_partial"
        )
    return _result(
        claim, evidence_ids, ClaimSupportStatus.UNSUPPORTED, score, "insufficient_token_coverage"
    )


def _verification_decision(
    answer: GroundedAnswer, results: tuple[ClaimVerification, ...]
) -> GroundedVerificationDecision:
    statuses = {item.status for item in results}
    if not results or statuses & {ClaimSupportStatus.CONFLICT, ClaimSupportStatus.UNSUPPORTED}:
        return GroundedVerificationDecision.REJECT
    if (
        statuses & {ClaimSupportStatus.PARTIAL, ClaimSupportStatus.UNKNOWN}
        or answer.completeness.value == "partial"
    ):
        return GroundedVerificationDecision.DEGRADE
    return GroundedVerificationDecision.PASS


def _result(
    claim: str,
    evidence_ids: tuple[str, ...],
    status: ClaimSupportStatus,
    score: float,
    reason: str,
) -> ClaimVerification:
    return ClaimVerification(
        claim_text=claim,
        evidence_ids=evidence_ids,
        status=status,
        support_score=score,
        reason_code=reason,
    )


def _label_index(labels: dict[str, int], target: str) -> int:
    for label, index in labels.items():
        if target in label:
            return index
    raise RuntimeError(f"NLI model is missing required label: {target}")


def _normalize(value: str) -> str:
    return "".join(character.casefold() for character in value if character.isalnum())


def _token_coverage(claim: str, evidence: str) -> float:
    claim_tokens = _semantic_tokens(claim)
    return (
        len(claim_tokens & _semantic_tokens(evidence)) / len(claim_tokens) if claim_tokens else 0.0
    )


def _semantic_tokens(value: str) -> set[str]:
    normalized = value.casefold()
    cjk = "".join(_CJK.findall(normalized))
    tokens = {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}
    tokens.update(_LATIN_WORD.findall(normalized))
    return tokens


def _polarity_conflict(claim: str, evidence_text: str) -> bool:
    """只比较同一业务谓词自身的否定极性，不让相邻句否定范围外溢。"""

    for predicate in _BUSINESS_PREDICATES:
        if predicate not in claim or predicate not in evidence_text:
            continue
        claim_polarities = _predicate_polarities(claim, predicate)
        evidence_polarities = _predicate_polarities(evidence_text, predicate)
        if (
            claim_polarities
            and evidence_polarities
            and claim_polarities.isdisjoint(evidence_polarities)
        ):
            return True
    return False


def _predicate_polarities(value: str, predicate: str) -> set[bool]:
    """True表示谓词被局部否定；按标点切句防止跨句传播。"""

    polarities: set[bool] = set()
    for sentence in re.split(r"[。！？；;\n]", value):
        start = 0
        while (index := sentence.find(predicate, start)) >= 0:
            prefix = sentence[max(0, index - 8) : index]
            polarities.add(any(marker in prefix for marker in _NEGATIONS))
            start = index + len(predicate)
    return polarities
