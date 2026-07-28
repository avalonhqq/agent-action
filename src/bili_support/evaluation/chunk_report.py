"""把Chunk策略对比渲染成适合失败分析的Markdown。"""

from bili_support.evaluation.chunk_types import ChunkEvaluationReport


def render_chunk_evaluation_markdown(report: ChunkEvaluationReport) -> str:
    """先输出策略横向指标，再逐策略列出可定位的失败明细。"""

    # 报告顶部只放最适合横向比较的聚合指标，避免读者先陷入单条Chunk细节。
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
        # 每个strategy占一行，使Generic与专用策略的收益可以直接对照。
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
        # 明细只展示失败Case；完整成功输出仍保留在JSON报告的cases/chunks中。
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
                # 一个Case可能同时存在语义、策略和数量失败，每个失败独占一行。
                lines.append(
                    f"| {case.case_id} | {_escape(case.source_name)} "
                    f"| {case.knowledge_type.value} | {failure.category.value} "
                    f"| {','.join(str(value) for value in failure.source_ordinals)} "
                    f"| {_escape(failure.expectation)} "
                    f"| {_escape(failure.observed)} |"
                )
    return "\n".join(lines) + "\n"


def _percent(value: float) -> str:
    """统一百分比精度，避免同一报告出现不一致的小数位。"""

    return f"{value * 100:.2f}%"


def _escape(value: str) -> str:
    """转义Markdown表格分隔符，并把多行Chunk压成单行预览。"""

    return value.replace("|", "\\|").replace("\n", " ")
