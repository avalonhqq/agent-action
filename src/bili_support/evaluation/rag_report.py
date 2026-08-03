"""把8C评估结果渲染为适合失败样本复盘的Markdown。"""

from bili_support.evaluation.rag_types import RagEvaluationReport


def render_rag_evaluation_markdown(report: RagEvaluationReport) -> str:
    """报告明确标注运行模式，防止把固定重放当成真实模型实验。"""

    metrics = report.metrics
    lines = [
        "# BiliSupport RAG生成评估报告",
        "",
        f"- 数据集：`{report.dataset}`",
        f"- 运行模式：`{report.run_mode}`",
        f"- 样本数：{metrics.case_count}",
        "",
        "> `fixed_prediction_replay`只验收数据、校验器和报告链路，不代表真实模型质量。",
        "",
        "## 核心指标",
        "",
        "| 决策准确率 | Faithfulness | Answer Relevancy | 引用精确率 | 引用召回率 | 通过率 |",
        "|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_percent(metrics.decision_accuracy)} | {_percent(metrics.faithfulness)} "
            f"| {_percent(metrics.answer_relevancy)} | {_percent(metrics.citation_precision)} "
            f"| {_percent(metrics.citation_recall)} | {_percent(metrics.pass_rate)} |"
        ),
        "",
        "## 逐样本结果",
        "",
        "| Case | 期望/实际决策 | Faithfulness | Relevancy | 引用P/R | 状态 |",
        "|---|---|---:|---:|---:|---|",
    ]
    for item in report.cases:
        status = "通过" if item.passed else "、".join(value.value for value in item.failures)
        lines.append(
            f"| `{item.case_id}` | {item.expected_decision.value}/{item.actual_decision.value} "
            f"| {_percent(item.faithfulness)} | {_percent(item.answer_relevancy)} "
            f"| {_percent(item.citation_precision)}/{_percent(item.citation_recall)} "
            f"| {status} |"
        )
    failed = tuple(item for item in report.cases if not item.passed)
    lines.extend(["", f"## 失败样本（{len(failed)}）", ""])
    failure_lines = "\n".join(
        f"- `{item.case_id}`："
        + "、".join(value.value for value in item.failures)
        for item in failed
    )
    lines.append("无。" if not failed else failure_lines)
    return "\n".join(lines).rstrip() + "\n"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"
