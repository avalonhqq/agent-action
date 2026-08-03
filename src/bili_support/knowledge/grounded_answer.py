"""第8周8A：带声明级证据引用的严格Grounded Answer契约。"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ANSWER_CITATION = re.compile(r"\[(E[1-9][0-9]*)\]")


class GroundedCompleteness(StrEnum):
    """模型对已生成答案覆盖程度的声明；最终门禁仍由确定性策略决定。"""

    COMPLETE = "complete"
    PARTIAL = "partial"


class GroundedClaim(BaseModel):
    """答案中的一个可独立核验事实及其直接证据ID。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=10)

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("claim text must not be blank")
        return value

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_must_be_valid_and_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(re.fullmatch(r"E[1-9][0-9]*", item) is None for item in value):
            raise ValueError("claim evidence IDs must use E1...En format")
        if len(set(value)) != len(value):
            raise ValueError("claim evidence IDs must be unique")
        return value


class GroundedAnswer(BaseModel):
    """模型输出契约；字段严格且回答、Claims、引用集合必须彼此一致。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1, max_length=6000)
    claims: tuple[GroundedClaim, ...] = Field(min_length=1, max_length=30)
    used_evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=20)
    completeness: GroundedCompleteness

    @field_validator("answer")
    @classmethod
    def answer_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("grounded answer must not be blank")
        return value

    @field_validator("used_evidence_ids")
    @classmethod
    def used_ids_must_be_valid_and_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(re.fullmatch(r"E[1-9][0-9]*", item) is None for item in value):
            raise ValueError("used evidence IDs must use E1...En format")
        if len(set(value)) != len(value):
            raise ValueError("used evidence IDs must be unique")
        return value

    @model_validator(mode="after")
    def claims_answer_and_used_ids_must_match(self) -> GroundedAnswer:
        claim_ids = {
            evidence_id
            for claim in self.claims
            for evidence_id in claim.evidence_ids
        }
        used_ids = set(self.used_evidence_ids)
        answer_ids = set(_ANSWER_CITATION.findall(self.answer))
        if claim_ids != used_ids:
            raise ValueError("used_evidence_ids must equal the IDs used by claims")
        if answer_ids != used_ids:
            raise ValueError("answer citations must equal used_evidence_ids")
        return self


class GroundedAnswerEvidenceError(StrEnum):
    """结构正确后，与本次真实证据集合比较得到的稳定错误码。"""

    EMPTY_ALLOWED_EVIDENCE = "empty_allowed_evidence"
    UNKNOWN_EVIDENCE_ID = "unknown_evidence_id"


class GroundedAnswerContractError(ValueError):
    """不携带模型原文，只向上层暴露可审计的契约错误码。"""

    def __init__(self, code: GroundedAnswerEvidenceError) -> None:
        super().__init__(code.value)
        self.code = code


def validate_grounded_answer_evidence(
    answer: GroundedAnswer,
    *,
    allowed_evidence_ids: tuple[str, ...],
) -> None:
    """拒绝空证据上下文或模型编造的E编号；语义支持度留给8B。"""

    allowed = set(allowed_evidence_ids)
    if not allowed:
        raise GroundedAnswerContractError(
            GroundedAnswerEvidenceError.EMPTY_ALLOWED_EVIDENCE
        )
    if not set(answer.used_evidence_ids).issubset(allowed):
        raise GroundedAnswerContractError(
            GroundedAnswerEvidenceError.UNKNOWN_EVIDENCE_ID
        )
