"""将6D检索评估结果渲染为可评审的Markdown报告。"""

from __future__ import annotations

from bili_support.evaluation.retrieval_types import RetrievalEvaluationReport


def render_retrieval_evaluation_markdown(
    report: RetrievalEvaluationReport,
) -> str:
    """展示核心指标和可直接定位的失败样本。"""

    metrics = report.metrics
    lines = [
        "# BiliSupport 检索评估报告",
        "",
        f"- 数据集：`{report.dataset}`",
        f"- 样本数：{report.case_count}",
        f"- 检索通道：`{report.retrieval_mode.value}`",
        f"- Embedding 模型：`{report.embedding_model or '不适用'}`",
        (
            f"- 正例/负例：{metrics.positive_case_count}/"
            f"{metrics.negative_case_count}"
        ),
        "",
        "## 核心指标",
        "",
        "| Recall@1 | Recall@3 | Recall@5 | MRR@5 | 负例准确率 | 执行失败率 | P50 | P95 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_percent(metrics.recall_at_1)} "
            f"| {_percent(metrics.recall_at_3)} "
            f"| {_percent(metrics.recall_at_5)} "
            f"| {_percent(metrics.mrr_at_5)} "
            f"| {_percent(metrics.negative_accuracy)} "
            f"| {_percent(metrics.execution_failure_rate)} "
            f"| {metrics.latency_p50_ms:.2f} ms "
            f"| {metrics.latency_p95_ms:.2f} ms |"
        ),
        "",
        "## 逐样本结果",
        "",
        "| Case ID | 问题 | R@1 | R@3 | R@5 | 首个相关项RR | 延迟 | 状态 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in report.cases:
        status = (
            "通过"
            if item.passed
            else ", ".join(failure.value for failure in item.failures)
        )
        lines.append(
            f"| `{item.case.case_id}` | {_escape_cell(item.case.question)} "
            f"| {_percent(item.recall_at_1)} "
            f"| {_percent(item.recall_at_3)} "
            f"| {_percent(item.recall_at_5)} "
            f"| {item.reciprocal_rank:.3f} "
            f"| {item.latency_ms:.2f} ms "
            f"| {status} |"
        )

    failed = tuple(item for item in report.cases if not item.passed)
    lines.extend(["", f"## 失败样本（{len(failed)}）", ""])
    if not failed:
        lines.append("无。")
    else:
        for item in failed:
            expected = ", ".join(
                relevant.relevance_id
                for relevant in item.case.relevant_parents
            ) or "应为空"
            returned = ", ".join(
                f"{parent.rank}:{parent.document_title}"
                for parent in item.parents
            ) or "无"
            lines.extend(
                [
                    f"### `{item.case.case_id}`",
                    "",
                    f"- 问题：{item.case.question}",
                    f"- 期望：{expected}",
                    f"- Top-5 返回：{returned}",
                    (
                        "- 已命中金标准："
                        + (
                            ", ".join(item.matched_relevance_ids_at_5)
                            or "无"
                        )
                    ),
                    f"- 错误码：{item.error_code or '-'}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
