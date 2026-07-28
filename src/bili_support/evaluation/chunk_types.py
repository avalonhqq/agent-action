"""Chunk离线评估的数据集、逐样本结果和聚合指标契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bili_support.knowledge.chunking import ChunkDraft, DocumentKnowledgeType
from bili_support.knowledge.types import LoadedSourceBlock


class ChunkEvaluationMode(StrEnum):
    """同一固定数据集上的两个可比较分块方案。"""

    GENERIC_BASELINE = "generic_baseline"  # 不理解业务结构的通用字符/句子基线
    SPECIALIZED = "specialized"  # 通过StrategySelector选择FAQ/Manual等专用策略


class ChunkFailureCategory(StrEnum):
    """失败归因直接对应可调整的分块环节。"""

    # 应共同用于召回的关键词或条件被拆到不同Child。
    CHILD_SEMANTIC_UNIT = "child_semantic_unit"
    # 回答所需的结论、条件或例外没有共同进入一个Parent。
    PARENT_CONTEXT = "parent_context"
    # 文档结构没有被路由到金标准期望的FAQ/Manual/Policy/Table等策略。
    STRATEGY_SELECTION = "strategy_selection"
    # Chunk无法追溯SourceBlock，或者Child引用了不存在的Parent。
    PARENT_CHILD_INTEGRITY = "parent_child_integrity"
    # Parent/Child数量落在人工标注的合理区间之外。
    CHUNK_COUNT = "chunk_count"
    # 策略本身抛出可预期异常；记录单样本失败，而不是终止整批评估。
    STRATEGY_EXECUTION = "strategy_execution"


class ChunkExpectation(BaseModel):
    """人工金标准描述应共同出现的语义，以及合理的Chunk数量范围。

    term_groups使用“组内AND、组间分别计分”：例如
    (("退款", "例外"), ("自动续费", "取消"))要求存在两个匹配Chunk，
    第一个同时包含“退款+例外”，第二个同时包含“自动续费+取消”。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 每一内层tuple中的术语必须共同出现在至少一个Child，评价“是否适合召回”。
    child_term_groups: tuple[tuple[str, ...], ...] = ()
    # 每一内层tuple中的术语必须共同出现在至少一个Parent，评价“回答上下文是否完整”。
    parent_term_groups: tuple[tuple[str, ...], ...] = ()
    # 期望在Child metadata.strategy中观察到的策略名称，可同时要求faq和policy。
    expected_child_strategies: tuple[str, ...] = ()
    # 数量范围用于发现过度合并或过度切碎；None表示不设置上限。
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
        """去除标注文本两端空白，拒绝空组和空术语。"""

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
        """策略名用于集合匹配，因此必须非空且不能重复。"""

        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ValueError("expected child strategies must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("expected child strategies must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_count_ranges(self) -> Self:
        """在加载数据集时阻止最大值小于最小值的自相矛盾金标准。"""

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
    """一条带来源定位和结构金标准的固定分块样本。

    Case直接保存Loader之后的SourceBlock，不依赖真实文件和数据库，使Chunk算法可以快速、
    确定性地离线回归；source_name仍保留人工排障所需的原始来源线索。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")  # 跨版本稳定的机器标识
    source_name: str = Field(min_length=1, max_length=255)  # 原文件或模拟来源名
    knowledge_type: DocumentKnowledgeType  # specialized模式选择策略的入口
    blocks: tuple[LoadedSourceBlock, ...] = Field(min_length=1)  # Chunker真实输入
    expected: ChunkExpectation  # 人工标注的结构和语义金标准
    tags: tuple[str, ...] = Field(min_length=1)  # 按faq/table等维度筛选失败
    note: str = Field(min_length=1, max_length=500)  # 说明该Case保护的业务边界

    @field_validator("source_name", "note")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        """文件名和说明不能用空白绕过Pydantic的min_length。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("chunk evaluation text must not be blank")
        return normalized

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """标签去空白、去歧义，保证后续分组统计稳定。"""

        normalized = tuple(tag.strip() for tag in value)
        if any(not tag for tag in normalized):
            raise ValueError("chunk evaluation tags must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("chunk evaluation tags must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_unique_source_ordinals(self) -> Self:
        """同一Case中ordinal必须唯一，否则Chunk父子ID和失败定位会歧义。"""

        ordinals = [block.ordinal for block in self.blocks]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("chunk evaluation blocks contain duplicate ordinals")
        return self


class ChunkEvaluationFailure(BaseModel):
    """可直接定位回样本文件和SourceBlock的单项失败。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: ChunkFailureCategory  # 可采取行动的失败层级
    expectation: str  # 人工金标准要求，报告中的“期望”列
    observed: str  # 实际Chunk摘要或异常原因，报告中的“实际”列
    source_ordinals: tuple[int, ...]  # 回到原Case SourceBlock的定位信息


class ChunkCaseEvaluation(BaseModel):
    """一个策略在一条样本上的完整可解释结果。

    同时保留分子和分母，而不是只保存比例，方便聚合时做micro average，
    防止“每条Case先求平均”让期望项较少的样本获得过高权重。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_id: str  # 与固定数据集Case一一对应
    source_name: str  # 无需再次联表即可在报告中定位来源
    knowledge_type: DocumentKnowledgeType  # 便于按知识类型分析失败
    # 实际生成数量用于数量范围判定和索引规模观察。
    parent_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
    # 三组“通过数/总数”供聚合器计算全数据集指标。
    child_expectation_total: int = Field(ge=0)
    child_expectation_passed: int = Field(ge=0)
    parent_expectation_total: int = Field(ge=0)
    parent_expectation_passed: int = Field(ge=0)
    strategy_expectation_total: int = Field(ge=0)
    strategy_expectation_passed: int = Field(ge=0)
    traceable_chunk_count: int = Field(ge=0)  # 来源和父引用都有效的Chunk数量
    chunks: tuple[ChunkDraft, ...]  # 保存实际输出，失败报告外还可进行深度复盘
    failures: tuple[ChunkEvaluationFailure, ...] = ()  # 空tuple表示Case通过

    @property
    def passed(self) -> bool:
        """一个Case必须没有任何失败项才算整体通过。"""

        return not self.failures


class ChunkEvaluationMetrics(BaseModel):
    """只评价知识表示质量，不把它冒充第6周的检索Recall@K。

    所有rate均位于[0, 1]；average_*是观察性指标，没有统一“越高越好”方向。
    Parent太多可能上下文碎片化，Child太多则增加索引和候选成本。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    case_pass_rate: float = Field(ge=0.0, le=1.0)  # 无任何失败的Case占比
    child_semantic_recall: float = Field(ge=0.0, le=1.0)  # Child术语组命中率
    parent_context_recall: float = Field(ge=0.0, le=1.0)  # Parent术语组命中率
    strategy_match_rate: float = Field(ge=0.0, le=1.0)  # 预期策略出现率
    traceability_rate: float = Field(ge=0.0, le=1.0)  # 可追溯Chunk/全部Chunk
    average_parent_count: float = Field(ge=0.0)  # 每Case平均Parent数量
    average_child_count: float = Field(ge=0.0)  # 每Case平均Child数量


class ChunkStrategyEvaluation(BaseModel):
    """一个评估模式的聚合指标和全部逐Case明细。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: ChunkEvaluationMode  # generic_baseline或specialized
    metrics: ChunkEvaluationMetrics  # 用于策略横向比较的聚合结果
    cases: tuple[ChunkCaseEvaluation, ...]  # 用于定位指标变化来源


class ChunkEvaluationReport(BaseModel):
    """一次固定数据集评估的顶层可序列化报告。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset: str  # 数据集文件名或版本标识
    case_count: int = Field(gt=0)  # 防止空数据集生成看似正常的100%指标
    strategies: tuple[ChunkStrategyEvaluation, ...]  # 同次运行的策略对比结果
