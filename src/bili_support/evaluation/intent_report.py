"""把意图评估结果渲染为便于评审的 Markdown。"""

from __future__ import annotations

from bili_support.evaluation.intent_types import IntentEvaluationReport


def render_intent_evaluation_markdown(report: IntentEvaluationReport) -> str:
    """生成策略对比、路由分项和失败样本列表。"""
    lines = [
        "# BiliSupport 意图评估报告",
        "",
        f"- 数据集：`{report.dataset}`",
        f"- 样本数：{report.case_count}",
        f"- 模型：`{report.model}`",
        "",
        "## 策略对比",
        "",
        (
            "| 策略 | Route Macro-F1 | 子意图 Micro-F1 | 子意图完全匹配 | "
            "规则覆盖率 | 规则精度 | 误拒绝率 | 高风险漏判率 | 澄清 F1 | 结构失败率 |"
        ),
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy in report.strategies:
        metrics = strategy.metrics
        lines.append(
            f"| {strategy.strategy.value} "
            f"| {_percent(metrics.route_macro_f1)} "
            f"| {_percent(metrics.sub_intent_micro_f1)} "
            f"| {_percent(metrics.sub_intent_exact_match)} "
            f"| {_percent(metrics.rule_coverage)} "
            f"| {_percent(metrics.rule_precision)} "
            f"| {_percent(metrics.false_rejection_rate)} "
            f"| {_percent(metrics.high_risk_miss_rate)} "
            f"| {_percent(metrics.clarification.f1)} "
            f"| {_percent(metrics.structured_failure_rate)} |"
        )

    for strategy in report.strategies:
        lines.extend(
            [
                "",
                f"## {strategy.strategy.value}",
                "",
                f"- Prompt 版本：v{strategy.prompt_version}",
                f"- 规则：{'开启' if strategy.rules_enabled else '关闭'}",
                "",
                "### 路由分项",
                "",
                "| 路由 | Precision | Recall | F1 | Support |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        for route, metric in strategy.metrics.route_by_class.items():
            lines.append(
                f"| {route.value} | {_percent(metric.precision)} "
                f"| {_percent(metric.recall)} | {_percent(metric.f1)} "
                f"| {metric.support} |"
            )

        failed_cases = tuple(case for case in strategy.cases if not case.passed)
        lines.extend(["", f"### 失败样本（{len(failed_cases)}）", ""])
        if not failed_cases:
            lines.append("无。")
            continue
        lines.extend(
            [
                "| Case ID | 问题 | 失败类别 | 预测路由 | Rule ID |",
                "|---|---|---|---|---|",
            ]
        )
        for item in failed_cases:
            prediction = item.prediction
            if prediction.decision is not None:
                predicted_route = prediction.decision.route.value
            else:
                error_code = prediction.error_code
                if error_code is None:
                    raise AssertionError(
                        "failed prediction must contain an error code"
                    )
                predicted_route = f"error:{error_code.value}"
            failure_text = ", ".join(value.value for value in item.failures)
            lines.append(
                f"| {item.case.case_id} | {_escape_cell(item.case.question)} "
                f"| {failure_text} | {predicted_route} "
                f"| {prediction.rule_id or '-'} |"
            )
    return "\n".join(lines) + "\n"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
