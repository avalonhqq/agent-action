# 当前进度：第 4 周 Step 4B-2 讲解与验收

> Step 4A 已于 2026-07-21 完成。当前任务见 [Step 4B：Zero-shot 意图分类 Prompt](week4-step4b-zero-shot-prompt.md)。

> 课程采用“大模型专项模式”：非 AI 基础任务由 Codex 自动实现并通过门禁，学习者重点参与大模型核心设计、实验和评估。

## Step 4A 完成结果

| 模块 | 状态 |
|---|---|
| 顶层 `IntentRoute` | 已完成 |
| 业务域与动作组合 | 已完成 |
| 多标签 `SubIntent` | 已完成 |
| 实体、情绪、风险与决策来源 | 已完成 |
| `IntentDecision` 跨字段约束 | 已完成 |
| 严格 JSON Schema | 已完成 |
| 结构化解析安全降级 | 已完成 |
| 18 项专项测试 | 已完成 |

## 验收

- Ruff 通过。
- strict mypy 通过，共检查 87 个源码文件。
- 全量 125 项测试通过。
- 合法复合意图可以保留多个子意图。
- 非法路由、低风险 `unsafe`、澄清字段冲突和重复子意图会在路由前失败。
- 非法 JSON 与 Schema 校验失败只返回稳定错误码，不泄露原始模型内容。

## Step 4B 完成结果

第 4 周 Step 4B：设计 `intent_classification:v1` Zero-shot Prompt。

学习重点：

- System Prompt 与用户输入边界。
- 将 `IntentDecision` JSON Schema 交给 Provider。
- 为枚举、复合意图、实体和澄清条件编写明确指令。
- 防止输出解释文字、Markdown 或未定义字段。
- 建立第一批确定性分类样例，为后续 Few-shot 与评估集准备基线。

4B-1 Prompt 注册与角色隔离、4B-2 分类器调用链和 4B-3 专项测试均已完成。`/support/`
页面已经提供“识别意图”按钮和结构化结果面板，CLI 仅作为开发调试入口。补充 API URL、模型名
和 Key 并重启服务后，页面会使用真实 OpenAI-compatible 模型。

## 下一项任务

当前按学习者要求暂不进入 4C，先完成 Step 4B 文档第 19 节的调用链讲解、五个验收问题和页面
观察任务。完成复盘后再进入 Few-shot 与规则/模型混合分类器。

第 3 周数据库、会话和页面底座的历史记录见 [第 3 周完成报告](week3-completion.md)。
