"""Chunk离线评估的数据集、逐样本结果和聚合指标契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bili_support.knowledge.chunking import ChunkDraft, DocumentKnowledgeType
from bili_support.knowledge.types import LoadedSourceBlock


class ChunkEvaluationMode(StrEnum):
    """同一固定数据集上的两个可比较分块方案。"""

    GENERIC_BASELINE = "generic_baseline"
    SPECIALIZED = "specialized"


class ChunkFailureCategory(StrEnum):
    """失败归因直接对应可调整的分块环节。"""

    CHILD_SEMANTIC_UNIT = "child_semantic_unit"
    PARENT_CONTEXT = "parent_context"
    STRATEGY_SELECTION = "strategy_selection"
    PARENT_CHILD_INTEGRITY = "parent_child_integrity"
    CHUNK_COUNT = "chunk_count"
    STRATEGY_EXECUTION = "strategy_execution"


class ChunkExpectation(BaseModel):
    """人工金标准描述应当共同出现在一个Chunk中的语义要素。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    child_term_groups: tuple[tuple[str, ...], ...] = ()
    parent_term_groups: tuple[tuple[str, ...], ...] = ()
    expected_child_strategies: tuple[str, ...] = ()
    min_parent_count: int = Field(default=1, ge=0)
    max_parent_count: int | None = Field(default=None, ge=0)
    min_child_count: int = Field(default=1, ge=0)
    max_child_count: int | None = Field(default=None, ge=0)

    @field_validator("child_term_groups", "parent_term_groups")
    @classmethod
    def normalize_term_groups(
        cls,
        value: tuple[tuple[str, ...], ...],
    ) -> tuple[tuple[str, ...], ...]:
        normalized = tuple(
            tuple(term.strip() for term in group) for group in value
        )
        if any(not group or any(not term for term in group) for group in normalized):
            raise ValueError("chunk expectation term groups must not be blank")
        return normalized

    @field_validator("expected_child_strategies")
    @classmethod
    def normalize_expected_strategies(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("expected child strategies must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("expected child strategies must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_count_ranges(self) -> Self:
        if (
            self.max_parent_count is not None
            and self.max_parent_count < self.min_parent_count
        ):
            raise ValueError("max_parent_count must not be smaller than minimum")
        if (
            self.max_child_count is not None
            and self.max_child_count < self.min_child_count
        ):
            raise ValueError("max_child_count must not be smaller than minimum")
        return self


class ChunkEvaluationCase(BaseModel):
    """一条带来源定位和结构金标准的固定分块样本。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    source_name: str = Field(min_length=1, max_length=255)
    knowledge_type: DocumentKnowledgeType
    blocks: tuple[LoadedSourceBlock, ...] = Field(min_length=1)
    expected: ChunkExpectation
    tags: tuple[str, ...] = Field(min_length=1)
    note: str = Field(min_length=1, max_length=500)

    @field_validator("source_name", "note")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("chunk evaluation text must not be blank")
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(tag.strip() for tag in value)
        if any(not tag for tag in normalized):
            raise ValueError("chunk evaluation tags must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("chunk evaluation tags must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_unique_source_ordinals(self) -> Self:
        ordinals = [block.ordinal for block in self.blocks]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("chunk evaluation blocks contain duplicate ordinals")
        return self


class ChunkEvaluationFailure(BaseModel):
    """可直接定位回样本文件和SourceBlock的单项失败。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: ChunkFailureCategory
    expectation: str
    observed: str
    source_ordinals: tuple[int, ...]


class ChunkCaseEvaluation(BaseModel):
    """一个策略在一条样本上的完整可解释结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str
    source_name: str
    knowledge_type: DocumentKnowledgeType
    parent_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
    child_expectation_total: int = Field(ge=0)
    child_expectation_passed: int = Field(ge=0)
    parent_expectation_total: int = Field(ge=0)
    parent_expectation_passed: int = Field(ge=0)
    strategy_expectation_total: int = Field(ge=0)
    strategy_expectation_passed: int = Field(ge=0)
    traceable_chunk_count: int = Field(ge=0)
    chunks: tuple[ChunkDraft, ...]
    failures: tuple[ChunkEvaluationFailure, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures


class ChunkEvaluationMetrics(BaseModel):
    """只评价知识表示质量，不把它冒充第6周的检索Recall@K。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_pass_rate: float = Field(ge=0.0, le=1.0)
    child_semantic_recall: float = Field(ge=0.0, le=1.0)
    parent_context_recall: float = Field(ge=0.0, le=1.0)
    strategy_match_rate: float = Field(ge=0.0, le=1.0)
    traceability_rate: float = Field(ge=0.0, le=1.0)
    average_parent_count: float = Field(ge=0.0)
    average_child_count: float = Field(ge=0.0)


class ChunkStrategyEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: ChunkEvaluationMode
    metrics: ChunkEvaluationMetrics
    cases: tuple[ChunkCaseEvaluation, ...]


class ChunkEvaluationReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str
    case_count: int = Field(gt=0)
    strategies: tuple[ChunkStrategyEvaluation, ...]
