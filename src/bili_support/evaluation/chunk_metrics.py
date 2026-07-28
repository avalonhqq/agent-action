"""在固定样本上比较Generic基线与结构化分块策略。"""

from __future__ import annotations

from collections.abc import Iterable

from bili_support.evaluation.chunk_types import (
    ChunkCaseEvaluation,
    ChunkEvaluationCase,
    ChunkEvaluationFailure,
    ChunkEvaluationMetrics,
    ChunkEvaluationMode,
    ChunkEvaluationReport,
    ChunkFailureCategory,
    ChunkStrategyEvaluation,
)
from bili_support.knowledge.chunk_strategies import StrategySelector
from bili_support.knowledge.chunking import (
    ChunkDraft,
    ChunkKind,
    ChunkStrategy,
    GenericChunkStrategy,
)


class ChunkEvaluator:
    """运行确定性分块并输出语义、上下文、策略和追溯四类指标。"""

    def __init__(self, *, selector: StrategySelector | None = None) -> None:
        """允许测试或未来实验注入另一版Selector，默认使用生产分块策略。"""

        self._selector = selector or StrategySelector()

    def evaluate(
        self,
        *,
        dataset_name: str,
        cases: tuple[ChunkEvaluationCase, ...],
        modes: tuple[ChunkEvaluationMode, ...] = (
            ChunkEvaluationMode.GENERIC_BASELINE,
            ChunkEvaluationMode.SPECIALIZED,
        ),
    ) -> ChunkEvaluationReport:
        """让每个模式运行完全相同的Case，再组合成可比较报告。"""

        if not cases:
            raise ValueError("chunk evaluation requires at least one case")
        if not modes:
            raise ValueError("chunk evaluation requires at least one mode")

        strategies = tuple(
            self._evaluate_mode(mode=mode, cases=cases) for mode in modes
        )
        return ChunkEvaluationReport(
            dataset=dataset_name,
            case_count=len(cases),
            strategies=strategies,
        )

    def _evaluate_mode(
        self,
        *,
        mode: ChunkEvaluationMode,
        cases: tuple[ChunkEvaluationCase, ...],
    ) -> ChunkStrategyEvaluation:
        """运行单一模式并将逐Case计数聚合为全数据集指标。"""

        results = tuple(
            self._evaluate_case(
                case=case,
                strategy=self._strategy(mode=mode, case=case),
            )
            for case in cases
        )
        return ChunkStrategyEvaluation(
            mode=mode,
            metrics=_aggregate_metrics(results),
            cases=results,
        )

    def _strategy(
        self,
        *,
        mode: ChunkEvaluationMode,
        case: ChunkEvaluationCase,
    ) -> ChunkStrategy:
        """基线固定使用Generic；实验组遵循Case声明的knowledge_type。"""

        if mode is ChunkEvaluationMode.GENERIC_BASELINE:
            return GenericChunkStrategy()
        return self._selector.select(case.knowledge_type)

    @staticmethod
    def _evaluate_case(
        *,
        case: ChunkEvaluationCase,
        strategy: ChunkStrategy,
    ) -> ChunkCaseEvaluation:
        """运行一条Case，并按语义、策略、关系和数量四层归因。"""

        try:
            chunks = strategy.chunk(blocks=case.blocks)
        except ValueError as exc:
            # 坏文档或策略边界错误只影响当前Case，批量评估必须继续处理其余样本。
            source_ordinals = tuple(block.ordinal for block in case.blocks)
            return ChunkCaseEvaluation(
                case_id=case.case_id,
                source_name=case.source_name,
                knowledge_type=case.knowledge_type,
                parent_count=0,
                child_count=0,
                child_expectation_total=len(
                    case.expected.child_term_groups
                ),
                child_expectation_passed=0,
                parent_expectation_total=len(
                    case.expected.parent_term_groups
                ),
                parent_expectation_passed=0,
                strategy_expectation_total=len(
                    case.expected.expected_child_strategies
                ),
                strategy_expectation_passed=0,
                traceable_chunk_count=0,
                chunks=(),
                failures=(
                    ChunkEvaluationFailure(
                        category=ChunkFailureCategory.STRATEGY_EXECUTION,
                        expectation="策略成功生成Parent/Child",
                        observed=str(exc),
                        source_ordinals=source_ordinals,
                    ),
                ),
            )
        # Parent和Child职责不同，必须分开匹配人工期望，不能用全部Chunk混合计分。
        parents = tuple(chunk for chunk in chunks if chunk.kind is ChunkKind.PARENT)
        children = tuple(chunk for chunk in chunks if chunk.kind is ChunkKind.CHILD)
        failures: list[ChunkEvaluationFailure] = []
        source_ordinals = tuple(block.ordinal for block in case.blocks)

        child_passed = _term_group_pass_count(
            case.expected.child_term_groups,
            children,
            failures=failures,
            category=ChunkFailureCategory.CHILD_SEMANTIC_UNIT,
            source_ordinals=source_ordinals,
        )
        parent_passed = _term_group_pass_count(
            case.expected.parent_term_groups,
            parents,
            failures=failures,
            category=ChunkFailureCategory.PARENT_CONTEXT,
            source_ordinals=source_ordinals,
        )

        # 一个mixed Case可能同时期望faq和policy，所以这里使用集合而非单一策略值。
        child_strategies = {
            str(chunk.metadata.get("strategy", "")) for chunk in children
        }
        strategy_passed = 0
        for expected_strategy in case.expected.expected_child_strategies:
            if expected_strategy in child_strategies:
                strategy_passed += 1
            else:
                failures.append(
                    ChunkEvaluationFailure(
                        category=ChunkFailureCategory.STRATEGY_SELECTION,
                        expectation=f"Child strategy包含{expected_strategy}",
                        observed=",".join(sorted(child_strategies)) or "无Child",
                        source_ordinals=source_ordinals,
                    )
                )

        # 即使语义匹配，也必须验证来源和父子关系，否则线上无法引用或Small-to-Big。
        traceable_count, integrity_failures = _check_integrity(
            chunks=chunks,
            source_ordinals=set(source_ordinals),
        )
        failures.extend(integrity_failures)
        _check_count_range(
            label="Parent",
            actual=len(parents),
            minimum=case.expected.min_parent_count,
            maximum=case.expected.max_parent_count,
            source_ordinals=source_ordinals,
            failures=failures,
        )
        _check_count_range(
            label="Child",
            actual=len(children),
            minimum=case.expected.min_child_count,
            maximum=case.expected.max_child_count,
            source_ordinals=source_ordinals,
            failures=failures,
        )

        return ChunkCaseEvaluation(
            case_id=case.case_id,
            source_name=case.source_name,
            knowledge_type=case.knowledge_type,
            parent_count=len(parents),
            child_count=len(children),
            child_expectation_total=len(case.expected.child_term_groups),
            child_expectation_passed=child_passed,
            parent_expectation_total=len(case.expected.parent_term_groups),
            parent_expectation_passed=parent_passed,
            strategy_expectation_total=len(
                case.expected.expected_child_strategies
            ),
            strategy_expectation_passed=strategy_passed,
            traceable_chunk_count=traceable_count,
            chunks=chunks,
            failures=tuple(failures),
        )


def _term_group_pass_count(
    term_groups: tuple[tuple[str, ...], ...],
    chunks: tuple[ChunkDraft, ...],
    *,
    failures: list[ChunkEvaluationFailure],
    category: ChunkFailureCategory,
    source_ordinals: tuple[int, ...],
) -> int:
    """计算“组内所有术语出现在同一Chunk”的期望通过数。

    这里有意不做模糊匹配或Embedding相似度：5C金标准检查确定性结构边界，
    语义检索能力留到第6周Recall@K评估。
    """

    passed = 0
    for terms in term_groups:
        if any(all(term in chunk.content for term in terms) for chunk in chunks):
            passed += 1
            continue
        failures.append(
            ChunkEvaluationFailure(
                category=category,
                expectation="同一Chunk包含：" + " + ".join(terms),
                observed=_chunk_preview(chunks),
                source_ordinals=source_ordinals,
            )
        )
    return passed


def _check_integrity(
    *,
    chunks: tuple[ChunkDraft, ...],
    source_ordinals: set[int],
) -> tuple[int, list[ChunkEvaluationFailure]]:
    """验证Chunk能回到当前Case的SourceBlock，且Child引用同批有效Parent。"""

    parent_ids = {
        chunk.local_id for chunk in chunks if chunk.kind is ChunkKind.PARENT
    }
    traceable = 0
    failures: list[ChunkEvaluationFailure] = []
    for chunk in chunks:
        valid_source = chunk.source_block_ordinal in source_ordinals
        valid_parent = (
            chunk.parent_local_id is None
            if chunk.kind is ChunkKind.PARENT
            else chunk.parent_local_id in parent_ids
        )
        if valid_source and valid_parent:
            traceable += 1
            continue
        failures.append(
            ChunkEvaluationFailure(
                category=ChunkFailureCategory.PARENT_CHILD_INTEGRITY,
                expectation=f"{chunk.local_id}可追溯到SourceBlock和有效Parent",
                observed=(
                    f"source_valid={valid_source}, parent_valid={valid_parent}"
                ),
                source_ordinals=(chunk.source_block_ordinal,),
            )
        )
    return traceable, failures


def _check_count_range(
    *,
    label: str,
    actual: int,
    minimum: int,
    maximum: int | None,
    source_ordinals: tuple[int, ...],
    failures: list[ChunkEvaluationFailure],
) -> None:
    """把过度合并/切碎转换为统一CHUNK_COUNT失败。"""

    if actual >= minimum and (maximum is None or actual <= maximum):
        return
    upper = "∞" if maximum is None else str(maximum)
    failures.append(
        ChunkEvaluationFailure(
            category=ChunkFailureCategory.CHUNK_COUNT,
            expectation=f"{label}数量在[{minimum}, {upper}]",
            observed=str(actual),
            source_ordinals=source_ordinals,
        )
    )


def _aggregate_metrics(
    results: tuple[ChunkCaseEvaluation, ...],
) -> ChunkEvaluationMetrics:
    """用全量分子/分母计算micro指标，并保留每Case平均规模。"""

    total_chunks = sum(len(item.chunks) for item in results)
    return ChunkEvaluationMetrics(
        case_pass_rate=_ratio(sum(item.passed for item in results), len(results)),
        child_semantic_recall=_ratio(
            sum(item.child_expectation_passed for item in results),
            sum(item.child_expectation_total for item in results),
        ),
        parent_context_recall=_ratio(
            sum(item.parent_expectation_passed for item in results),
            sum(item.parent_expectation_total for item in results),
        ),
        strategy_match_rate=_ratio(
            sum(item.strategy_expectation_passed for item in results),
            sum(item.strategy_expectation_total for item in results),
        ),
        traceability_rate=_ratio(
            sum(item.traceable_chunk_count for item in results),
            total_chunks,
        ),
        average_parent_count=sum(item.parent_count for item in results) / len(results),
        average_child_count=sum(item.child_count for item in results) / len(results),
    )


def _ratio(numerator: int, denominator: int) -> float:
    """无期望项时返回1，含义是“没有该维度的失败”，避免除零。"""

    return numerator / denominator if denominator else 1.0


def _chunk_preview(chunks: Iterable[ChunkDraft]) -> str:
    """限制失败报告体积，只展示前三个Chunk各80字符。"""

    values = [chunk.content.replace("\n", " ")[:80] for chunk in chunks]
    return " | ".join(values[:3]) or "无Chunk"
