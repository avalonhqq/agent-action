# BiliSupport AI：12 周大模型专项学习计划

> 课程模式自 2026-07-20 起调整为“大模型核心由学习者重点掌握，非 AI 工程底座由 Codex 自动实现并通过质量门禁”。

## 1. 新的学习边界

你只需要重点学习和参与以下内容：

- Prompt 设计、结构化输出、模型参数和上下文治理。
- 意图识别、实体抽取、置信度与错误分析。
- 文档语义表示、Chunk 策略、Embedding、检索、Rerank 和 RAG。
- LangGraph、Agent、Tool Calling、记忆和状态管理。
- 幻觉控制、事实校验、安全、模型评估和效果优化。

下列基础任务默认由 Codex 自动完成，不再作为你的编码作业：

- FastAPI CRUD、Pydantic 请求响应、SQLAlchemy、Alembic 和 Repository。
- 文件上传、任务状态、分页、鉴权接线和普通管理页面。
- Docker/Compose、配置、日志、指标接线和测试脚手架。
- Mock 数据、Fixture、CLI、迁移和重复性工程代码。

自动完成不代表降低标准。所有自动底座仍需通过 Ruff、strict mypy、pytest、迁移验证和必要的集成测试，然后才进入 AI 实验。

## 2. 新的学习闭环

```text
Codex 自动补齐工程前置
→ 全量质量门禁
→ 大模型概念讲解
→ AI Schema / Prompt / Policy 设计
→ 小规模实验
→ 指标与失败样本分析
→ 改进与回归
→ 文档留档
```

你每个模块主要完成四件事：

1. 能解释核心原理和方案取舍。
2. 参与 AI 接口、Prompt、状态或检索策略设计。
3. 阅读评估结果并分析失败样本。
4. 对关键 AI 代码做小范围修改和实验，而不是编写通用 CRUD。

## 3. 12 周重新安排

| 周   | 学习主题                   | 你的大模型重点                                             | 自动完成的基础配套                          | 状态   |
| --- | ---------------------- | --------------------------------------------------- | ---------------------------------- | ---- |
| 1   | Python AI 工程基线         | 理解类型、安全边界和异步调用                                      | 工程、配置、日志、探针、Docker                 | 已完成  |
| 2   | LLM 调用与 Prompt         | Provider、Prompt、结构化输出、SSE、上下文                       | HTTP 适配、错误映射、配置接线                  | 已完成  |
| 3   | 持久化对话与记忆底座             | 理解消息历史如何进入模型上下文                                     | 数据库、迁移、鉴权、会话 API、NiceGUI           | 已完成  |
| 4   | 意图识别与结构化决策             | 多标签意图、实体、风险、置信度、Few-shot、评估                         | 数据集读写、评估 CLI/API、报告页面              | 下一阶段 |
| 5   | RAG 知识表示与 Chunk        | 结构恢复、Small-to-Big、表格语义、元数据                          | PDF/DOCX/MD/TXT Loader、任务表、上传和重试接口 | 未开始  |
| 6   | Embedding 与向量检索        | 向量语义、相似度、Top-K、Query Rewrite、过滤                     | FAISS 持久化、索引版本、调试接口                | 未开始  |
| 7   | 混合检索、Rerank 与策略        | BM25、RRF、Reranker、RetrievalPolicy、多实体覆盖             | FAQ CRUD、领域词典管理、评估报表               | 未开始  |
| 8   | 证据约束生成与 RAG 评估         | Grounded Prompt、引用、拒答、Faithfulness、Answer Relevancy | 引用接口、Golden Dataset 管理、批量运行器       | 未开始  |
| 9   | LangGraph 状态化工作流       | State、Node、Edge、Checkpoint、循环保护和恢复                  | Checkpoint 存储、流程调试页和持久化接线          | 未开始  |
| 10  | 多 Agent 与 Tool Calling | Supervisor、任务拆解、并发聚合、工具选择和确认                        | Mock 业务服务、权限表、审计表和管理接口             | 未开始  |
| 11  | 校验、安全与模型观测             | Verification、注入防护、PII、降级、模型指标和回归                    | OpenTelemetry、限流、告警、压测和运维页面        | 未开始  |
| 12  | 效果优化与最终交付              | 端到端误差分析、策略调优、模型选型和面试表达                              | Demo 包装、部署脚本、运行手册和展示页面             | 未开始  |

## 4. 第 1～3 周：已完成前置

### 第 1 周：工程基线

已完成类型化配置、错误边界、Request ID、结构化日志、探针、质量门禁和 Docker 基线。这些内容不再作为后续课程重点，只在影响模型可靠性时解释。

### 第 2 周：LLM 调用基础

已完成内部 `LLMProvider`、确定性 Mock、OpenAI-compatible Adapter、Prompt 版本、Pydantic 结构化输出、超时重试、SSE、上下文窗口、Query Rewrite 和安全 Usage 记录。

需要保留的 AI 基础知识：消息角色、Temperature、Token、结构化输出双重校验、Prompt 版本、取消传播和不保存私有思维链。

### 第 3 周：对话记忆底座

已自动完成用户、会话、消息、模型调用、迁移、Repository/Service、简单鉴权、持久化 SSE 和 NiceGUI。你只需理解：数据库历史不是模型记忆，只有经过裁剪、摘要和权限过滤后放入请求的内容才是模型可见上下文。

## 5. 第 4 周：意图识别与结构化决策

### 你的学习重点

- 单标签与多标签意图的区别。
- `supported`、`out_of_domain`、`chitchat`、`unsafe` 顶层判定。
- 业务域、动作、实体、情绪、风险等级和是否需要澄清。
- Pydantic/JSON Schema 约束模型输出。
- Zero-shot、Few-shot 和规则/模型混合路由。
- 置信度不是事实概率：阈值必须通过评估校准。
- Accuracy、Macro-F1、混淆矩阵、误拒绝率和高风险漏判率。

### AI 实践

1. 定义 `IntentDecision` 和业务意图枚举。
2. 设计 `intent_classification:v1` Prompt。
3. 为复合问题输出多个子意图和实体。
4. 建立包含域外、闲聊、注入和模糊表达的评估集。
5. 对比规则基线、Zero-shot 和 Few-shot。
6. 分析至少 10 个失败样本并迭代 v2。

### Codex 自动完成

- 评估数据文件格式、加载器、批量运行器和 CLI。
- 结果落库、评估 API、混淆矩阵数据和报告页面。
- Mock 分类 Provider、Fixture、日志接线和测试脚手架。

### 验收

- 结构化输出解析失败可安全降级。
- 域外问题默认跳过知识检索。
- 复合意图不会被强行压成单标签。
- 固定评估集输出 Macro-F1、误拒绝率和高风险漏判率。
- Prompt v1/v2 的变化和指标差异可回溯。

## 6. 第 5 周：RAG 知识表示与 Chunk

### 你的学习重点

- 文档结构为何影响检索，而不仅是字符切片。
- Parent/Child Small-to-Big：Child 召回、Parent 提供完整上下文。
- Policy、Manual、FAQ、Table 和 Generic 的不同分块策略。
- 标题路径、页码、版本、权限、业务域和有效期元数据。
- 表格如何转成包含表头、行标签、单位和业务对象的自包含文本。

### Codex 自动完成

PDF、DOCX、Markdown、TXT Loader，文件哈希、上传/状态/重试/删除接口，文档/任务/Chunk 表及迁移。

### 验收

至少四类文档可入库；Parent/Child 可追溯；表格语义不丢失；重复文件幂等；失败任务可重试。

## 7. 第 6 周：Embedding 与向量检索

### 你的学习重点

Embedding 语义、余弦相似度、Top-K、维度和归一化；Query Rewrite；元数据过滤；上下文预算；召回率与延迟取舍。

### AI 实践

- `EmbeddingProvider` 和可复现 Mock。
- Child Chunk 建索引、Parent 聚合。
- 独立 `/retrieve` 调试输出。
- 首批 Golden Dataset 和 Recall@K。

### Codex 自动完成

FAISS 文件管理、索引版本、数据库映射、重建任务、管理 API 和页面。

## 8. 第 7 周：混合检索、Rerank 与策略

### 你的学习重点

中文 BM25、审核词典、Query Expansion、RRF、去重、批量 Reranker、阈值校准、意图驱动 RetrievalPolicy 和多实体 Evidence Coverage。

### AI 实践

- FAQ + BM25 + Vector 三路召回。
- 意图对应候选预算和权重。
- Rerank 失败时回退融合排序。
- 比较纯向量、混合检索和 Rerank 后的 Recall@5/MRR。

### Codex 自动完成

FAQ 管理、词典存储、批量任务、结果持久化和对比报告页面。

## 9. 第 8 周：证据约束生成与 RAG 评估

### 你的学习重点

Grounded Generation、引用格式、证据冲突、无证据拒答、答案完整性、Faithfulness、Answer Relevancy 和 LLM-as-Judge 的偏差。

### AI 实践

- 只允许使用检索证据的回答 Prompt。
- 引用声明和证据映射的结构化输出。
- 高分回答、中分澄清、低分拒答/人工策略。
- 批量评估并人工复核失败样本。

### Codex 自动完成

评估任务、结果存储、引用展示、报告导出和回归脚本。

## 10. 第 9 周：LangGraph 状态化工作流

### 你的学习重点

State、Node、Conditional Edge、Checkpoint、中断恢复、Human-in-the-loop、有限循环和可回放性。重点理解“确定性工作流控制模型”，而不是让模型自由决定所有步骤。

### AI 实践

建立输入、安全、意图、检索/工具、Verification、决策和回答/澄清/人工节点；定义每个节点的结构化输入输出。

### Codex 自动完成

Checkpoint 数据库、运行记录、流程调试 API、可视化页面和恢复接线。

## 11. 第 10 周：多 Agent 与 Tool Calling

### 你的学习重点

Agent 与 Workflow 边界、Supervisor、复合任务拆解、并发聚合、冲突处理、Function Calling、工具选择、参数约束、二次确认和工具结果不可伪造。

### AI 实践

- Intent、Knowledge、Membership/Order、Creator、Account、Community、Technical、Verification Agent。
- Agent 授权范围和输出 Schema。
- 会员、订单、稿件、处罚等受控工具。
- 复合问题拆解与结果合并评估。

### Codex 自动完成

Mock 业务数据、工具 CRUD、权限矩阵存储、幂等键、审计接口和管理页面。

## 12. 第 11 周：校验、安全与模型观测

### 你的学习重点

Prompt Injection、文档注入、PII、事实有效期、证据归属、输出校验、降级、首 Token 延迟、总延迟、Token、成本、模型兼容性和回归漂移。

### AI 实践

- Verification Agent 和结构化原因码。
- 输入/上下文/输出安全策略。
- 模型、Prompt、检索策略版本联合回归。
- 高风险自动人工交接。

### Codex 自动完成

脱敏工具接线、OpenTelemetry、限流、熔断、压测、告警、Mock 人工服务和运维页面。

## 13. 第 12 周：优化与最终交付

### 你的学习重点

- 从意图、召回、重排、生成、工具和安全六层定位错误。
- 比较模型、Prompt、Chunk、检索策略和阈值。
- 用真实评估数据说明取舍，而不是只展示成功案例。
- 能清晰讲述架构、失败案例、优化过程和边界。

### 最终验收

- 知识答案有可访问引用，无证据明确拒答。
- 复合意图、受控工具和人工交接可演示。
- 固定数据集可一键评估并对比版本。
- 单次请求可追踪 Intent、Retriever、Reranker、LLM、Agent 和 Tool。
- README、架构图、运行手册、Demo、简历描述和面试题库完整。

## 14. 每个模块的固定交付物

每个后续模块都必须留下：

1. AI 目标与核心原理。
2. 自动完成的工程底座清单。
3. Prompt、Schema、Policy 或 Graph 版本。
4. Golden Dataset 或针对性测试集。
5. 指标结果与失败样本。
6. 设计决策、已知边界和下一步。
7. Ruff、mypy、pytest 和专项评估结果。
