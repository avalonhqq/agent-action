# BiliSupport AI：12 周全 Python 学习计划

## 1. 学习闭环

每周围绕同一主项目完成：

```text
概念学习 → 设计讨论 → 你编码 → 自动测试
→ 演示验收 → 代码评审 → 问题复盘 → 文档留档
```

工作日建议每天 2 小时：40 分钟概念、70 分钟编码、10 分钟记录。周末安排 3～5 小时集成、评估和复盘。

## 2. 12 周总览

| 周 | 主题 | 可演示增量 |
|---|---|---|
| 1 | Python AI 工程基础 | 标准工程、配置、日志、健康检查、Docker |
| 2 | LLM、Prompt、结构化输出 | 普通聊天、SSE、上下文和模型指标 |
| 3 | Web 服务、会话、网站 | 可使用的客服网站雏形 |
| 4 | 文档解析与知识入库 | 可追踪、可重试的知识流水线 |
| 5 | Embedding 与基础 RAG | 带真实引用的知识问答 |
| 6 | FAQ、混合检索与评估 | 三段式客服检索和对比报告 |
| 7 | LangGraph 工作流 | 可回放、可恢复的客服主流程 |
| 8 | 多 Agent 与复合意图 | 专业 Agent 路由和结果聚合 |
| 9 | 受控 Tool Calling | 仿真业务查询、权限、幂等和确认 |
| 10 | 事实校验、安全与人工 | Verification、PII、防注入和交接包 |
| 11 | 评估、观测与生产化 | 一键评估、追踪、限流和 Compose |
| 12 | 完整交付与面试 | 三端页面、Demo、报告、简历和题库 |

## 第 1 周：Python AI 工程基础与项目初始化

### 知识点

类型系统、Enum/dataclass/TypedDict、Pydantic v2、asyncio、FastAPI、配置、异常、structlog、pytest、Ruff、mypy、pre-commit、Docker。

### 实施顺序

1. 理解 `src` 布局、包导入和 ASGI。
2. 完善 `/health`，新增 `/ready`。
3. 实现 Settings 和 local/test/staging/production。
4. 实现统一响应、异常、Request ID 和结构化日志。
5. 配置 Ruff、mypy、pytest、pre-commit。
6. 增加 Dockerfile 和开发启动方式。

### 周产出与验收

- 可运行 FastAPI 工程；Ruff、mypy、pytest 通过。
- `/health` 不依赖外部服务；`/ready` 检查必需依赖。
- production 危险配置启动失败。
- Docker 可启动并通过健康检查。

## 第 2 周：LLM API、Prompt 与结构化输出

### 知识点

消息角色、Token、Temperature、上下文窗口、Prompt、JSON Schema、SSE、超时、重试、取消、历史裁剪和摘要。

### 项目任务

- 定义 `LLMProvider`，实现确定性 Mock 和 OpenAI-compatible Adapter。
- 普通聊天和 SSE 流式接口。
- Pydantic 结构化输出和解析失败降级。
- Prompt 版本管理、Token、耗时和错误记录。

### 验收

客户端断开可取消任务；模型不可用有明确错误/降级；结构化输出可测试。

## 第 3 周：FastAPI 业务服务、会话与 NiceGUI

### 知识点

依赖注入、中间件、SQLAlchemy 2 异步、PostgreSQL、Alembic、Repository/Service、鉴权、SSE 页面。

### 项目任务

- 用户、会话、消息、模型调用表和迁移。
- 创建会话、发送消息、历史查询。
- Thread ID、用户上下文和简单 Token 鉴权。
- NiceGUI 聊天页和流式渲染。

### 验收

用户可继续历史会话；迁移幂等；请求、消息和模型调用可关联追踪。

## 第 4 周：异构文档解析与知识入库

### 知识点

PDF、DOCX、MD、TXT、CSV、HTML，文件签名、哈希、结构恢复、分块、元数据、权限、有效期、任务状态机和幂等。

### 项目任务

- Loader Registry 和统一 ParsedDocument。
- Policy、Manual、FAQ、Table、Generic Chunker。
- 文档、Chunk、任务表；上传、状态、重试和删除接口。
- 保留标题路径、页码、版本、权限和业务域。

### 验收

至少四类文档；Chunk 可回溯原文；重复上传不重复入库；失败可重试。

## 第 5 周：Embedding、FAISS 与基础 RAG

### 知识点

Embedding、余弦相似度、FAISS、Top-K、Query Rewrite、上下文预算、证据约束和引用。

### 项目任务

- `EmbeddingProvider` 与可复现 Mock。
- FAISS 索引和索引版本。
- 向量检索接口和基础 RAG Pipeline。
- 返回标题、章节、页码、版本和 chunk_id。
- 建立首批 Golden Dataset。

### 验收

无证据明确拒答；权限/业务域过滤生效；固定集可计算 Recall@K。

## 第 6 周：FAQ、混合检索、重排与 RAG 评估

### 知识点

标准问、相似问、审核答案、BM25、RRF、Reranker、阈值、MRR、Faithfulness、Answer Relevancy。

### 项目任务

- FAQ 模型、导入和审核状态。
- FAQ + BM25 + Vector 多路召回。
- RRF、去重、Reranker 和元数据过滤。
- 高分直答、中分候选、低分澄清/人工。
- 扩充约 100 条评估数据并生成对比报告。

### 验收

混合检索相对纯向量在 Recall@5/MRR 有实际提升；参数可配置和重跑。

## 第 7 周：LangGraph 确定性工作流

### 知识点

State、Node、Edge、Conditional Edge、Checkpoint、中断恢复、Human-in-the-loop、循环保护和回放。

### 项目任务

建立输入、安全、意图、路由、检索/工具、校验、决策、回答/澄清/人工主流程，并记录节点输入输出摘要。

### 验收

节点独立测试；相同状态可回放；失败进入显式降级；最大步骤有效。

## 第 8 周：多 Agent 与复合意图

### 知识点

Agent/Workflow 边界、多标签意图、实体、情绪、风险、任务拆解、并发和冲突聚合。

### 项目任务

实现 Supervisor、Intent、Knowledge、Membership/Order、Creator、Account、Community、Technical Agent 的输入输出 Schema 和授权范围。

### 验收

复合问题可拆解；Supervisor 不生成业务事实；Agent 不能越权使用工具；路由有评估集。

## 第 9 周：受控 Tool Calling 与仿真业务系统

### 知识点

Function Calling、参数模型、工具注册、权限矩阵、归属、幂等、超时、重试、二次确认和审计。

### 项目任务

实现仿真用户、会员、订单、退款、稿件、处罚、工单工具；禁止任意 SQL。

### 验收

非本人数据被拦截；重复写不重复执行；失败不伪造成功；调用可按 Request ID 审计。

## 第 10 周：事实校验、安全与人工技能组

### 知识点

Prompt Injection、文档注入、PII、RBAC、最小权限、事实校验、冲突和人工降级。

### 项目任务

- 输入、日志、上下文和输出四层脱敏。
- Verification Agent 校验证据有效期、归属、冲突和敏感信息。
- Mock HumanHandoffService 和结构化交接包。

### 验收

无证据不回答；PII 不进入普通日志；高风险自动转人工；不实现坐席排队。

## 第 11 周：评估、可观测、性能与生产化

### 知识点

Golden Dataset、RAGAS、OpenTelemetry、首 Token/总延迟、限流、熔断、缓存、备份和 Docker Compose。

### 项目任务

- 一键运行意图、检索、回答、工具和安全评估。
- 打通 Request→Graph→LLM→Retriever→Tool 链路。
- 指标、超时、限流、降级、压测和 Compose。

### 验收

可定位单次请求；模型不可用有降级；核心接口有集成测试；一条命令启动。

## 第 12 周：完整项目交付、简历与面试

### 项目任务

- 完成聊天端、知识端和评估端。
- 准备 10～15 个演示场景。
- 架构图、时序图、技术取舍、故障案例和真实优化数据。
- 完整 README、运行手册、Demo 视频、简历描述和面试题库。

### 最终验收

网站支持多轮、知识问答、受控业务查询和人工交接；回答有引用；安全与评估可复现；Docker Compose 可启动。

