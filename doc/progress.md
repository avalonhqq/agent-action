# 12 周学习进度

> 2026-07-20 起采用大模型专项模式。第 1～3 周底座已完成；后续非 AI 基础设施由 Codex 自动实现和校验，不再作为学习者作业。

| 周   | 主题                     | 状态  | 开始         | 完成         | 关键结果                                               |
| --- | ---------------------- | --- | ---------- | ---------- | -------------------------------------------------- |
| 1   | Python AI 工程基础         | 已完成 | 2026-07-14 | 2026-07-17 | 23 项测试；配置、错误边界、Request ID、日志、探针、质量门禁和 Docker 基线    |
| 2   | LLM、Prompt、结构化输出       | 已完成 | 2026-07-18 | 2026-07-19 | 96 项全量测试；Prompt 版本、结构化输出、兼容适配器、聊天/SSE、上下文改写和安全用量记录 |
| 3   | Web 服务、会话、网站           | 已完成 | 2026-07-19 | 2026-07-20 | 106 项全量测试；MySQL/Redis、迁移、持久化会话、简单鉴权、SSE 和 NiceGUI  |
| 4   | 意图识别与结构化决策             | 已完成 | 2026-07-21 | 2026-07-25 | hybrid_v3；48 条真实复验；路由/澄清 100%，高风险漏判 0%              |
| 5   | RAG 知识表示与 Chunk        | 已完成 | 2026-07-25 | 2026-07-28 | 结构化分块、Small-to-Big、固定数据集与可解释Chunk评估               |
| 6   | Embedding 与向量检索        | 已完成 | 2026-07-28 | 2026-07-31 | Milvus索引/检索、Small-to-Big；10条真实评估Recall@5 100%       |
| 7   | 混合检索、Rerank 与策略        | 已完成 | 2026-07-31 | 2026-08-01 | Jieba+词典；Hybrid MRR 91.67%；策略v2错误回答率0%                 |
| 8   | 证据生成与 RAG 评估           | 未开始 |            |            | Grounded Prompt、引用、拒答和 Faithfulness                |
| 9   | LangGraph 状态化工作流       | 进行中 | 2026-08-04 |            | 9A最小图完成；下一步接入真实Intent、RAG和Verifier                    |
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
| AI 核心 | `IntentDecision`、多标签意图、实体、情绪、风险和澄清判断 | 已完成 |
| AI 核心 | Zero-shot/Few-shot/混合基线及 Prompt v1/v2/v3 | 已完成 |
| AI 核心 | Macro-F1、子意图、误拒绝率和高风险漏判率 | 已完成 |
| 自动底座 | 评估数据加载、批量 CLI、结果存储、API 和报告页 | 由 Codex 实现 |
| 自动底座 | Mock Provider、Fixture、日志、错误处理和测试脚手架 | 由 Codex 实现 |

### 第 4 周步骤

| Step | 内容 | 状态 | 验收记录 |
|---|---|---|---|
| 4A | `IntentDecision`、枚举、实体与跨字段约束 | 已完成 | 18 项专项测试；全量 125 tests；Ruff、mypy 通过 |
| 4B | `intent_classification:v1` Zero-shot Prompt | 已完成 | Prompt、严格 Schema、分类器、Mock/真实 Provider、页面与 CLI |
| 4C | Few-shot 与规则/模型混合分类器 | 已完成 | 规则短路、模型回退、页面来源与规则编号展示 |
| 4D | 固定评估集、指标与批量运行底座 | 已完成 | 48 条开发集、四策略、业务指标、失败报告 |
| 4E | 失败样本分析与 Prompt v3 | 已完成 | 真实预测重放、独立复验、失败归因和确定性风险兜底 |
| 4F | 接入客服路由与复盘 | 已完成 | 正式消息先过 hybrid_v3；七类目标、SSE route、页面和审计接线 |

## 第 5 周新安排

| Step | 内容 | 状态 | 验收目标 |
|---|---|---|---|
| 5A | 文档入库契约与自动工程底座 | 已完成 | PDF/DOCX/Markdown/TXT 可追踪入库，重复文件幂等 |
| 5B | 结构化 Chunk 与 Small-to-Big | 已完成 | Child 可召回、Parent 可批量还原，标题和表格语义不丢失 |
| 5C | Chunk 数据集、评估与知识库调试接口 | 已完成 | 8条固定样本比较策略，失败可定位来源文件和SourceBlock |

## 第 6 周新安排

| Step | 内容 | 状态 | 验收目标 |
|---|---|---|---|
| 6A | Embedding 契约与 Milvus 边界 | 已完成 | Mock 可复现；Collection、HNSW/COSINE、过滤与真实读写可用 |
| 6B | 批量索引、索引版本与安全切换 | 已完成 | Child 分页批量写入；失败可重试；MySQL 原子切换活动版本 |
| 6C | 向量检索与 Small-to-Big | 已完成 | Rewrite、活动索引/权限过滤、MySQL复核与Parent还原 |
| 6D | Golden Dataset 与 Recall@K | 已完成 | 8正2负；R@1/3/5=75%/87.5%/100%；定位域内无答案误召回 |

## 第 7 周新安排

| Step | 内容 | 状态 | 验收目标 |
|---|---|---|---|
| 7A | 中文Tokenizer与BM25单路基线 | 已完成 | 活动Child词法召回、统一复核/Parent恢复；与Vector固定集对比 |
| 7A-RAG | Chat接入真实知识检索与Grounded Prompt | 已完成 | `knowledge_rag`、有界Parent证据、引用Trace、无证据禁止自由回答 |
| 7B | Vector + BM25 RRF融合 | 已完成 | Hybrid R@1/3/5=75%/100%/100%，MRR@5=85.42% |
| 7C | 批量Reranker与降级 | 已完成 | Parent单次批量评分；超时/无效响应回退RRF；Mock质量回退故默认关闭 |
| 7D | RetrievalPolicy、阈值与覆盖 | 已完成 | 意图驱动预算；一次补检索；无答案拒答；多实体覆盖可评估 |
| 7A-2 | Jieba搜索分词优化 | 已完成 | 可替换Tokenizer；受控业务词典；Bigram/Jieba固定集对照 |
| 7A-3 | 生产级领域词典管理 | 已完成 | 候选、审核、不可变版本、Mock来源、制品导出与回滚边界 |
| 7UI | 统一企业客服工作台 | 已完成 | 问答、知识上传、词条写库、审核发布、制品预览和能力边界 |
| 7DATA | 首批领域词候选 | 已完成 | 8个业务域、48个候选词、幂等导入、保留人工审核门禁 |
| 7DICT-RUNTIME | 发布词典接入运行时 | 已完成 | Manifest快照、原子部署、Jieba热加载、BM25缓存重建、补检索覆盖 |
| 7E | Elasticsearch BM25与自动同步 | 已完成 | ES 9.4.2；175个活动Child；版本索引、Alias切换、启动/激活/发布同步 |
| 8A | Grounded Output Contract | 已完成 | 严格Claims、三方引用集合一致、v2 Prompt和证据ID白名单校验 |
| 8B | Claim Verification | 已完成 | 声明支持度、数字事实、否定冲突、完整性和安全降级 |
| 8C | RAG Evaluation | 已完成 | 6类固定集、Faithfulness、Relevancy、Citation指标和报告 |
| 8D | 产品接入与复盘 | 已完成 | v4 Chat、最小直接引用、DeepSeek兼容重试和分层验证降级 |
| 9A | 最小LangGraph与Checkpoint底座 | 已完成 | 类型化State、条件边、有限循环、MongoDB Replica Set、AES/TTL、跨Saver恢复 |
| 9B | 真实客服能力Graph化 | 已完成 | Intent、Hybrid RAG、Grounded生成、本地NLI、会话API与SSE统一接线 |
| 9C | 人工中断与断点恢复 | 已完成 | MongoDB interrupt/resume、MySQL审核事实、原子领取、恢复API与流程审核页 |
| 9C-Context | 多轮主题解析 | 已完成 | 主题栈、槽位兼容、结构化模型消歧、安全澄清、MySQL快照与Redis缓存 |
| 9D | 流程回放与失败恢复策略 | 已完成 | 脱敏Checkpoint时间线、Task失败识别、恢复动作分级与工作台展示 |

## 第10周新安排

| Step | 内容 | 状态 | 验收目标 |
|---|---|---|---|
| 10A | Supervisor控制平面 | 进行中 | 强类型任务、结构化规划、依赖波次、结果聚合和Graph影子接入 |
| 10B | 受控Tool平台 | 未开始 | MySQL业务数据、权限、归属、二次确认、幂等和审计 |
| 10C | 领域Agent执行 | 未开始 | Agent授权、并行分派、工具/RAG调用、Verification和冲突处理 |
| 10D | 产品接入与评估 | 未开始 | 正式Graph、工作台、固定评估集和第10周复盘 |

## 每周复盘模板

- 完成的用户能力：
- 完成的工程能力：
- 自动测试与评估结果：
- 遇到的问题和根因：
- 方案取舍：
- 遗留技术债：
- 可演示场景：
- 下一周前置条件：
