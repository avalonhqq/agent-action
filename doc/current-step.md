# 当前进度：第 3 周已完成

> 完成日期：2026-07-19。完整讲解与问答见 [第 3 周完成报告](week3-completion.md)。

> 课程已于 2026-07-20 调整为“大模型专项模式”：非 AI 基础任务由 Codex 自动实现并通过门禁，学习者只重点参与大模型核心设计、实验和评估。

## 完成状态

| 模块 | 状态 |
|---|---|
| SQLAlchemy 2 异步数据库与 Session 生命周期 | 已完成 |
| User、Conversation、Message、ModelCall 模型 | 已完成 |
| Alembic 初始迁移与重复升级验证 | 已完成 |
| Repository 与 ConversationService | 已完成 |
| Bearer Token、用户上下文和用户隔离 | 已完成 |
| 会话创建、列表、历史和普通消息接口 | 已完成 |
| 持久化 SSE 消息接口 | 已完成 |
| NiceGUI `/support/` 客服页面 | 已完成 |
| SQLite 测试、MySQL 本地/Compose 与 Redis 缓存 | 已完成 |

## 验收

- Ruff、strict mypy、pre-commit 通过。
- 106 项测试通过（包含 MySQL/Redis 缓存单元验证）。
- 用户可以在应用重启后继续历史会话。
- 数据库迁移重复执行不会重复建表。
- Request ID、用户消息、助手消息和模型调用有明确关联。
- 模型失败时保留用户消息并记录安全错误码。

## 下一阶段

第 4 周改为“意图识别与结构化决策”，不再让学习者先编写文档上传和数据库 CRUD。

### AI 核心

- 多标签意图、业务域、动作、实体、情绪和风险等级。
- `supported`、`out_of_domain`、`chitchat`、`unsafe` 顶层路由。
- Pydantic/JSON Schema 结构化输出。
- Zero-shot、Few-shot、规则/模型混合基线。
- Macro-F1、混淆矩阵、误拒绝率和高风险漏判率。

### Codex 自动底座

- 评估数据格式、加载器和批量运行 CLI。
- 结果存储、评估 API、Mock Provider 和报告页面。
- Fixture、错误边界、日志和测试脚手架。

### 开始条件

MySQL/Redis 接入后全量 106 项测试、Ruff、strict mypy、pre-commit 已通过；真实 MySQL 建表、应用读写和 Redis TTL 缓存也已验收，可以直接进入第 4 周 AI 模块。
