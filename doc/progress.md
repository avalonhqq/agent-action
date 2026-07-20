# 12 周学习进度

> 2026-07-20 起采用大模型专项模式。第 1～3 周底座已完成；后续非 AI 基础设施由 Codex 自动实现和校验，不再作为学习者作业。

| 周   | 主题                     | 状态  | 开始         | 完成         | 关键结果                                               |
| --- | ---------------------- | --- | ---------- | ---------- | -------------------------------------------------- |
| 1   | Python AI 工程基础         | 已完成 | 2026-07-14 | 2026-07-17 | 23 项测试；配置、错误边界、Request ID、日志、探针、质量门禁和 Docker 基线    |
| 2   | LLM、Prompt、结构化输出       | 已完成 | 2026-07-18 | 2026-07-19 | 96 项全量测试；Prompt 版本、结构化输出、兼容适配器、聊天/SSE、上下文改写和安全用量记录 |
| 3   | Web 服务、会话、网站           | 已完成 | 2026-07-19 | 2026-07-20 | 106 项全量测试；MySQL/Redis、迁移、持久化会话、简单鉴权、SSE 和 NiceGUI  |
| 4   | 意图识别与结构化决策             | 未开始 |            |            | 多标签意图、实体/风险、Few-shot 和分类评估                         |
| 5   | RAG 知识表示与 Chunk        | 未开始 |            |            | Loader 等自动完成；重点学习结构化分块与 Small-to-Big               |
| 6   | Embedding 与向量检索        | 未开始 |            |            | 向量语义、过滤、Query Rewrite 和 Recall@K                   |
| 7   | 混合检索、Rerank 与策略        | 未开始 |            |            | BM25、RRF、Reranker、策略和覆盖评估                          |
| 8   | 证据生成与 RAG 评估           | 未开始 |            |            | Grounded Prompt、引用、拒答和 Faithfulness                |
| 9   | LangGraph 状态化工作流       | 未开始 |            |            | 可回放、可恢复、有限步的模型工作流                                  |
| 10  | 多 Agent 与 Tool Calling | 未开始 |            |            | 路由、拆解、工具选择、确认和聚合                                   |
| 11  | 校验、安全与模型观测             | 未开始 |            |            | Verification、注入、PII、降级和回归                          |
| 12  | 效果优化与最终交付              | 未开始 |            |            | 端到端误差分析、调优、Demo 和面试表达                              |

## 第 1 周步骤

| Step | 内容 | 状态 | 验收记录 |
|---|---|---|---|
| 1 | src 布局、ASGI、健康接口 | 已完成 | Ruff/mypy/pytest 通过；健康响应与概念问答通过 |
| 2 | 类型系统、Pydantic Settings、多环境配置 | 已完成 | Ruff/mypy/8 项 pytest 通过；完成配置校验、缓存、`.env` 隔离与应用工厂 |
| 3 | 统一响应、异常、Request ID、结构化日志 | 已完成 | 统一错误契约；安全异常边界；Request ID 透传；structlog JSON 访问日志 |
| 4 | `/ready`、质量工具、pre-commit | 已完成 | readiness 配置检查；Ruff/mypy/pytest hook 全部通过 |
| 5 | Docker 基线与第 1 周复盘 | 已完成 | 非 root Docker/Compose 基线；完成报告与 22 道问答；本机未安装 Docker，镜像待构建验证 |

## 第 2 周步骤

| Step | 内容 | 状态 | 验收记录 |
|---|---|---|---|
| 2A | LLM 内部契约、Protocol 与确定性 Mock | 已完成 | 普通/流式契约、严格校验、Mock 用量与公共导出 |
| 2B | Prompt 与结构化输出 | 已完成 | 版本注册、变量校验、JSON Schema 和安全失败原因 |
| 2C | OpenAI-compatible 适配器 | 已完成 | 超时、有限重试、退避、取消、SSE 映射与安全异常 |
| 2D | Chat API 与 SSE | 已完成 | typed JSON、delta/completed/error、断开关闭上游 |
| 2E | 上下文与 Query Rewrite | 已完成 | 有界窗口、确定性摘要、指代替换与保守不改写 |
| 2F | 编排、Usage 与复盘 | 已完成 | Token/耗时/状态/错误码记录；Ruff、mypy、96 tests 通过 |

## 第 3 周步骤

| Step | 内容 | 状态 | 验收记录 |
|---|---|---|---|
| 3A | 异步数据库、四类实体与约束 | 已完成 | SQLite/MySQL URL；显式消息/调用外键；Redis 历史缓存 |
| 3B | Alembic 迁移 | 已完成 | 初始 revision；重复 `upgrade head` 通过 |
| 3C | Repository/Service | 已完成 | 短事务、用户隔离、失败审计和历史恢复 |
| 3D | 会话 API 与鉴权 | 已完成 | Bearer Token、用户上下文、创建/列表/历史/发送 |
| 3E | 持久化 SSE | 已完成 | 流式成功、失败、关闭状态与消息落库 |
| 3F | NiceGUI 与部署 | 已完成 | `/support/` 页面；MySQL/Redis Compose；106 tests；真实本地依赖验收 |

## 第 4 周新安排

| 类型 | 内容 | 状态 |
|---|---|---|
| AI 核心 | `IntentDecision`、多标签意图、实体、情绪、风险和澄清判断 | 待开始 |
| AI 核心 | Zero-shot/Few-shot/混合基线及 Prompt v1/v2 | 待开始 |
| AI 核心 | Macro-F1、混淆矩阵、误拒绝率和高风险漏判率 | 待开始 |
| 自动底座 | 评估数据加载、批量 CLI、结果存储、API 和报告页 | 由 Codex 实现 |
| 自动底座 | Mock Provider、Fixture、日志、错误处理和测试脚手架 | 由 Codex 实现 |

## 每周复盘模板

- 完成的用户能力：
- 完成的工程能力：
- 自动测试与评估结果：
- 遇到的问题和根因：
- 方案取舍：
- 遗留技术债：
- 可演示场景：
- 下一周前置条件：
