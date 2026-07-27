"""把Chunk策略对比渲染成适合失败分析的Markdown。"""

from bili_support.evaluation.chunk_types import ChunkEvaluationReport


def render_chunk_evaluation_markdown(report: ChunkEvaluationReport) -> str:
    lines = [
        "# BiliSupport Chunk 评估报告",
        "",
        f"- 数据集：`{report.dataset}`",
        f"- 样本数：{report.case_count}",
        "- 说明：本报告评价分块表示质量，不代表向量检索 Recall@K。",
        "",
        "## 策略对比",
        "",
        (
            "| 策略 | 样本通过率 | Child语义召回 | Parent上下文召回 | "
            "策略匹配率 | 追溯完整率 | 平均Parent | 平均Child |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in report.strategies:
        metrics = strategy.metrics
        lines.append(
            f"| {strategy.mode.value} | {_percent(metrics.case_pass_rate)} "
            f"| {_percent(metrics.child_semantic_recall)} "
            f"| {_percent(metrics.parent_context_recall)} "
            f"| {_percent(metrics.strategy_match_rate)} "
            f"| {_percent(metrics.traceability_rate)} "
            f"| {metrics.average_parent_count:.2f} "
            f"| {metrics.average_child_count:.2f} |"
        )

    for strategy in report.strategies:
        failed = tuple(case for case in strategy.cases if not case.passed)
        lines.extend(
            [
                "",
                f"## {strategy.mode.value} 失败样本（{len(failed)}）",
                "",
            ]
        )
        if not failed:
            lines.append("无。")
            continue
        lines.extend(
            [
                "| Case ID | 来源 | 类型 | 失败类别 | SourceBlock | 期望 | 实际 |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for case in failed:
            for failure in case.failures:
                lines.append(
                    f"| {case.case_id} | {_escape(case.source_name)} "
                    f"| {case.knowledge_type.value} | {failure.category.value} "
                    f"| {','.join(str(value) for value in failure.source_ordinals)} "
                    f"| {_escape(failure.expectation)} "
                    f"| {_escape(failure.observed)} |"
                )
    return "\n".join(lines) + "\n"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _escape(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
