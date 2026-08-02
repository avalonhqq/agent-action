"""把7D策略评估结果渲染为便于复核的Markdown。"""

from bili_support.evaluation.policy_types import PolicyEvaluationReport


def render_policy_evaluation_markdown(report: PolicyEvaluationReport) -> str:
    """报告同时展示安全指标和每条样本的决策依据。"""

    metrics = report.metrics
    lines = [
        "# BiliSupport 检索策略评估报告",
        "",
        f"- 数据集：`{report.dataset}`",
        f"- 样本数：{report.case_count}",
        f"- 检索通道：`{report.retrieval_mode.value}`",
        f"- BM25分词器：`{report.bm25_tokenizer.value if report.bm25_tokenizer else '不适用'}`",
        "",
        "## 核心指标",
        "",
        (
            "| 决策准确率 | 回答精确率 | 错误回答率 | 负例拒答召回 "
            "| 实体覆盖率 | 补检索率 | 执行失败率 | P50 | P95 |"
        ),
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        (
            f"| {_percent(metrics.decision_accuracy)} "
            f"| {_percent(metrics.answer_precision)} "
            f"| {_percent(metrics.false_answer_rate)} "
            f"| {_percent(metrics.refusal_recall)} "
            f"| {_percent(metrics.mean_entity_coverage)} "
            f"| {_percent(metrics.supplemental_query_rate)} "
            f"| {_percent(metrics.execution_failure_rate)} "
            f"| {metrics.latency_p50_ms:.2f} ms "
            f"| {metrics.latency_p95_ms:.2f} ms |"
        ),
        "",
        "## 逐样本决策",
        "",
        "| Case ID | 期望 | 实际 | 策略 | 原因 | 分数 | 证据数 | 状态 |",
        "|---|---|---|---|---|---:|---:|---|",
    ]
    for item in report.cases:
        actual = item.actual_decision.value if item.actual_decision else "执行失败"
        score = "-" if item.score is None else f"{item.score:.6f}"
        lines.append(
            f"| `{item.case.case_id}` | {item.expected_decision.value} | {actual} "
            f"| `{item.policy_id or '-'}` | `{item.reason_code or item.error_code or '-'}` "
            f"| {score} | {item.evidence_count} | {'通过' if item.passed else '失败'} |"
        )
    return "\n".join(lines).rstrip() + "\n"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"
