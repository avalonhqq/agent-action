# enterprise-rag-financial-reports 参考评审

## 1. 参考对象

- 仓库：[stevenfight/enterprise-rag-financial-reports](https://github.com/stevenfight/enterprise-rag-financial-reports)
- 审查日期：2026-07-15
- 审查范围：README、`src`、`tests`、`snippets`、`docs` 和 `openspec`。

## 2. 总体结论

该项目对 BiliSupport AI 的 **知识检索链路很有参考价值**，特别是 Small-to-Big、中文 BM25 词典、意图驱动权重、批量 Rerank、多轮 Query Rewrite、域外拦截和多实体覆盖保障。

它是面向少量金融报告的 RAG 应用，不是完整客服平台。账号/权限、持久化会话、业务工具、安全审计、多 Agent、可靠异步服务和生产数据治理仍需由 BiliSupport AI 自行设计。

## 3. 建议吸收

| 能力 | 参考价值 | BiliSupport AI 适配方式 | 计划位置 |
|---|---|---|---|
| Small-to-Big | 高 | 子块用于召回，父块用于上下文，保留 parent/child/页码关系 | 第 4～5 周 |
| 表格预处理 | 高 | 会员权益、退款时效、规则表格转为自包含文本 | 第 5 周 |
| 中文 BM25 词典 | 高 | 建立大会员、UP 主、稿件、弹幕、充电等领域词典 | 第 7 周 |
| 受控 Query Expansion | 高 | 只使用审核词典，保存命中的扩展词及版本 | 第 7 周 |
| 意图驱动检索策略 | 高 | 不同意图配置 BM25/Vector 权重、Top-K、Rerank 和阈值 | 第 6/8 周 |
| 批量 Rerank | 高 | Provider 批量评分，失败回退融合排序，记录耗时 | 第 7 周 |
| 域外拦截 | 高 | 区分 supported/unsupported/chitchat/unsafe，避免无意义检索 | 第 8/10 周 |
| 多轮指代消解 | 高 | 有界历史 + 摘要生成 standalone query，不拼接无限历史 | 第 2～3 周 |
| 多实体覆盖保障 | 高 | 比较多个会员方案/规则/业务对象时保证证据覆盖和多样性 | 第 7 周 |
| 检索调试接口 | 高 | 返回通道、原始分、融合分、重排分、parent/child、策略版本 | 第 5～6 周 |
| Rerank 降级 | 高 | 云端失败时回退 RRF/hybrid，不伪造 rerank 分数 | 第 6/11 周 |
| 新人指南/上线清单/问题库 | 高 | 增加故障记录、Provider 验证和发布检查清单 | 第 1～12 周 |

## 4. 不应照搬

### 4.1 金融专用规则

公司覆盖、营收数字补充、财经词典和金融意图不可直接进入客服系统。应抽象为：

- `required_entities`
- `coverage_policy`
- `evidence_diversity`
- 领域词典版本

### 4.2 公开思维链

参考项目把 `reasoning/cot_reasoning` 放入结构结果和日志。BiliSupport AI 不保存或返回模型私有思维链，只保存结构化决策字段、简短原因码和必要审计摘要。

### 4.3 内存会话

简单 `ConversationManager` 和全局字典不适合多实例客服系统。BiliSupport AI 使用 MySQL 保存会话/消息、Redis 缓存短期历史，并通过后续 Checkpoint Store 恢复 Graph 状态。

### 4.4 同步调用与单体检索文件

外部模型、Embedding、Rerank 需要异步 Provider、超时、取消和并发限制；检索要拆为召回、融合、重排、覆盖、上下文组装，避免形成超大单体文件。

### 4.5 硬编码置信度

`rerank >= 8` 等规则只能作为初始实验值。客服阈值必须按业务域、风险和评估集校准，并保存策略版本。

### 4.6 内部异常暴露

API 不直接返回 `str(exception)`。外部返回稳定错误码，内部详情只进入脱敏日志和 Trace。

### 4.7 规模与索引

IndexFlatIP 适合小规模准确基线，不代表生产扩展方案。BiliSupport AI 保留 VectorStore 协议，以 FAISS 做 MVP，并能迁移 Qdrant。

## 5. 新增设计：客服版 Small-to-Big

```text
Document
└── ParentChunk（完整条款/完整步骤/完整 FAQ 上下文）
    ├── ChildChunk（精细语义召回）
    ├── ChildChunk
    └── ChildChunk

检索：Child Top-K → 按 Parent 去重/聚合 → Parent Rerank → Parent 进入 LLM
```

Parent 和 Child 都必须保留：文档、章节、页码、版本、权限、业务域、有效期和索引版本。

## 6. 新增设计：RetrievalPolicy

每个意图不直接在代码中写死权重，而使用版本化策略：

```yaml
technical.error_code:
  bm25_weight: 0.7
  vector_weight: 0.3
  child_top_k: 30
  parent_top_k: 10
  rerank_top_n: 5

community.rule_explanation:
  bm25_weight: 0.4
  vector_weight: 0.6
  require_effective_document: true
  direct_answer_threshold: 0.90
```

评估报告必须记录策略版本，保证结果可复现。

## 7. 新增设计：多实体证据覆盖

“比较年度大会员和连续包月权益”不应因为某一对象文本更多而只召回一方。流程为：

1. Query Rewrite 提取 `required_entities`。
2. 每个实体至少独立召回若干候选。
3. 融合与 Rerank 后检查覆盖。
4. 缺失实体允许定向补检索一次。
5. 仍无可靠证据时明确说明缺失，不使用低质量内容凑数。

## 8. 评审后的质量要求

- Small-to-Big 必须与普通分块做 Recall@K/MRR/上下文 Token 对比。
- Rerank 必须批量调用并有超时、并发限制和可识别降级标记。
- Query Rewrite 必须测试指代消解、过度扩展和错误实体注入。
- 多实体问题必须计算 Evidence Coverage。
- 所有检索结果能看到策略版本及每阶段分数。
- 域外拦截既测试召回减少，也测试误拒绝率。
