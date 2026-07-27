# 第5周代码阅读指南：RAG 知识表示与 Chunk

---

## 一、本周核心目标

第5周解决的核心问题是：**文档进入模型上下文之前，如何保存结构、语义、权限和可追溯性**。

```text
PDF / DOCX / Markdown / TXT
  → 文件校验与幂等
  → 文档解析 (Loader)
  → 结构化块 (SourceBlock)
  → Parent / Child Chunk
  → 数据库存储
  → Small-to-Big 反向扩大
```

本周不学习向量数据库和相似度检索（第6周内容），当前先保证"放进知识库的内容是正确的"。

---

## 二、整体架构图

### 2.1 模块分层架构

```
┌─────────────────────────────────────────────────────────┐
│                    API 层 (HTTP 接口)                     │
│  api/knowledge.py — 上传、列表、版本、重试、删除            │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                 Service 层 (业务编排)                      │
│  services/knowledge.py — 哈希、版本、任务、解析、重试       │
└────────────┬───────────────────────────┬─────────────────┘
             │                           │
┌────────────▼───────────┐  ┌────────────▼────────────────┐
│   Repository 层         │  │   知识核心层 (AI 算法)        │
│ repositories/knowledge.py│  │                            │
│  数据库持久化操作        │  │  Loaders — 文件解析          │
└────────────┬───────────┘  │  Chunking — 分块策略        │
             │              │  Small-to-Big — 反向扩大     │
┌────────────▼───────────┐  │  Table Normalization — 表格 │
│    Model 层 (ORM)       │  │  Storage — 文件存储         │
│  models/entities.py     │  └────────────────────────────┘
│  5张数据表              │
└────────────────────────┘
```

### 2.2 数据流转全景图

```
原始文件 (PDF/DOCX/MD/TXT)
      │
      ▼
┌─────────────┐
│  文件校验    │  SHA-256 幂等、大小限制、权限校验
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Loader     │  按扩展名选择解析器 → LoadedDocument
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│  LoadedDocument │  统一输出契约
│  LoadedSourceBlock[]
└──────┬──────────┘
       │
       ▼
┌──────────────────────┐
│  StrategySelector    │  选择分块策略
│  (Generic/Policy/    │
│   Manual/FAQ/Table)  │
└──────┬───────────────┘
       │
       ▼
┌──────────────────┐
│  ChunkDraft[]    │  内存中的分块结果
│  Parent + Child  │
└──────┬───────────┘
       │
       ▼
┌──────────────────────┐
│  持久化到数据库       │
│  knowledge_source_blocks
│  knowledge_chunks    │
└──────────────────────┘
       │
       ▼  (第6周)
┌──────────────────────┐
│  Embedding + 向量检索 │
│  BM25 + 混合检索      │
│  Rerank + 回答        │
└──────────────────────┘
```

---

## 三、五层数据模型详解

这是本周最重要的概念：**为什么需要5张表，而不是一张表？**

| 模型 | 表名 | 职责 | 核心字段 |
|------|------|------|----------|
| KnowledgeDocument | knowledge_documents | 逻辑知识、业务域、权限和软删除状态 | title, business_domain, knowledge_type, access_scope |
| KnowledgeDocumentVersion | knowledge_document_versions | 一次不可变文件快照、哈希和存储位置 | document_id, version_number, content_sha256, storage_key |
| KnowledgeIngestionJob | knowledge_ingestion_jobs | 一次解析尝试、状态、次数和错误码 | version_id, status, attempt_count, error_code |
| KnowledgeSourceBlock | knowledge_source_blocks | Loader 忠实恢复出的标题、段落、列表和表格 | version_id, ordinal, block_type, content, heading_path |
| KnowledgeChunk | knowledge_chunks | Parent/Child 检索单元 | version_id, kind, parent_chunk_id, content, char_count |

### 状态流转图

```text
DocumentVersion:  pending ───────────────→ ready
                       └───────────────→ failed

IngestionJob: queued → processing → succeeded
                    └────→ failed → retry → processing
```

**代码位置**：`src/bili_support/models/entities.py`

---

## 四、核心模块逐站阅读

### 第0站：类型契约 — `knowledge/types.py`

**作用**：定义 Loader 和 Chunker 之间的稳定接口，所有解析器输出统一格式。

**关键类型**：

```text
SourceBlockType (枚举)
├── HEADING    — 标题块
├── PARAGRAPH  — 段落块
├── LIST       — 列表块
└── TABLE      — 表格块

LoadedSourceBlock
├── ordinal        — 原文顺序 (从0开始)
├── block_type     — 块类型
├── content        — 可读文本
├── page_number    — 页码 (PDF有，MD/DOCX可能没有)
├── heading_path   — 标题路径 (如 ("大会员", "自动续费"))
└── metadata       — 结构信息 (表格列名等)

LoadedDocument
├── filename       — 文件名
├── media_type     — 媒体类型
├── blocks         — 有序结构块元组
└── metadata       — 文档级元数据
```

**设计亮点**：
- `frozen=True`：不可变，防止后续环节意外修改原文
- `heading_path`：用元组保存标题层级，比字符串更稳定

**代码位置**：`src/bili_support/knowledge/types.py`

---

### 第1站：文件存储 — `knowledge/storage.py`

**作用**：原文件的安全、不可变存储。

**核心方法**：

| 方法 | 作用 | 设计要点 |
|------|------|----------|
| `build_key()` | 生成存储路径 | `ab/完整版本ID.pdf`，两级目录避免文件堆在一起 |
| `write()` | 写入文件 | 先写 `.tmp` 再 `replace`，保证原子性 |
| `read()` | 读取文件 | 只允许读取根目录内的文件，防止路径穿越 |

**安全设计**：
```python
def _resolve_key(self, key: str) -> Path:
    target = (self._root / key).resolve()
    # 防止 ../../ 等路径穿越
    if not target.is_relative_to(self._root):
        raise ValueError("storage key escapes knowledge root")
    return target
```

**代码位置**：`src/bili_support/knowledge/storage.py`

---

### 第2站：Loader 注册表 — `knowledge/loaders/base.py`

**作用**：按文件类型选择解析器，统一错误处理。

**工作流程**：

```
输入: content + filename + media_type
    │
    ▼
  提取扩展名 (.pdf / .docx / .md / .txt)
    │
    ▼
  查找对应 Loader
    │
    ├── 找不到 → UNSUPPORTED_DOCUMENT_TYPE
    │
    ▼
  调用 Loader.load()
    │
    ├── DocumentLoadError → 原样上抛 (稳定错误码)
    └── 其他异常 → DOCUMENT_PARSE_FAILED (隐藏底层细节)
```

**设计模式**：**注册表模式** + **协议(Protocol)**

```python
class DocumentLoader(Protocol):
    extensions: frozenset[str]
    def load(self, *, content: bytes, filename: str, media_type: str) -> LoadedDocument: ...
```

- 用 `frozenset` 存储扩展名，不可变、可哈希、查找快
- 用 Protocol 定义接口，不需要继承，更灵活

**代码位置**：`src/bili_support/knowledge/loaders/base.py`

---

### 第3站：表格规范化 — `knowledge/table_normalization.py`

**作用**：把二维表格转换为"每行都重复表头"的自包含文本。

**为什么需要这个？**

如果直接把表格切成文本：
```
套餐  | 价格
月卡  | 25元
年卡  | 168元
```

切分后 Child 可能只有 `"月卡 25元"`，丢失了"套餐"和"价格"的列语义。

**规范化后**：
```
第1行：套餐=月卡；价格=25元
第2行：套餐=年卡；价格=168元
```

每个 Child 都包含完整的列名，检索时即使只命中一行也能理解含义。

**代码位置**：`src/bili_support/knowledge/table_normalization.py`

---

### 第4站：基础分块 — `knowledge/chunking.py`

**作用**：Generic 基线策略，把 SourceBlock 转换为 Parent + Child。

#### 4.1 核心概念

| 类型 | 作用 | 特点 |
|------|------|------|
| Parent Chunk | 给大模型看的完整上下文 | 保留完整标题路径 + 整段正文 |
| Child Chunk | 用于检索召回的小块 | 更短、更聚焦，带标题前缀 |

#### 4.2 ChunkDraft 契约

```python
class ChunkDraft(BaseModel):
    local_id: str              # 本次分块内的临时ID
    kind: ChunkKind            # PARENT / CHILD
    content: str               # 文本内容
    source_block_ordinal: int  # 来源块序号
    parent_local_id: str | None # 父引用 (Child必有，Parent没有)
    metadata: dict             # 追溯元数据
```

**验证规则**（在 `validate_parent_reference` 中）：
- Parent 不能引用另一个 Parent
- Child 必须引用一个 Parent

#### 4.3 Generic 分块策略流程

```
SourceBlock (PARAGRAPH/LIST)
      │
      ▼
  ┌─────────────────────────┐
  │  生成 Parent             │
  │  标题：大会员 > 自动续费  │
  │  正文：大会员到期前...    │
  └────────────┬────────────┘
               │
               ▼
        正文内容切分
               │
    ┌──────────┴──────────┐
    ▼                     ▼
  句子边界切分          超长句滑窗
  (。！？；)           (overlap 保留边界)
    │                     │
    └──────────┬──────────┘
               │
               ▼
        装箱成 Child
        标题前缀 + 正文
```

#### 4.4 切分三级策略

| 级别 | 策略 | 适用场景 |
|------|------|----------|
| 1级 | 自然句子边界 | 正常的中文段落 |
| 2级 | 相邻短句合并装箱 | 多个短句可以放一起 |
| 3级 | 滑动窗口 (带 overlap) | 超长句、无标点文本 |

**滑窗算法**：
```python
step = child_max_chars - child_overlap_chars
start = 0
while start < len(sentence):
    end = start + child_max_chars
    part = sentence[start:end]
    parts.append(part)
    if end >= len(sentence):
        break
    start += step
```

**overlap 的作用**：保证切分边界处的语义不丢失。

#### 4.5 内容格式化对比

| 类型 | 格式示例 |
|------|----------|
| Parent | `标题：大会员 > 自动续费\n正文：用户可以在支付渠道关闭自动续费。` |
| Child | `大会员 / 自动续费：用户可以在支付渠道关闭自动续费。` |

Parent 更完整，适合模型阅读；Child 更紧凑，适合检索匹配。

**代码位置**：`src/bili_support/knowledge/chunking.py`

---

### 第5站：专用分块策略 — `knowledge/chunk_strategies.py`

**为什么需要专用策略？**

Generic 只知道长度和句子边界，不理解业务结构。例如：

> 第二条 退款条件
> 用户在重复扣费时可以申请退款。
> **但已经消耗的会员权益不支持退款。**

如果按 Generic 切分，"但已经消耗..." 可能被切到另一个 Child，检索只命中"可以退款"时，就会给出错误承诺。

#### 5.1 四种专用策略对比

| 策略 | 适用场景 | 核心思想 |
|------|----------|----------|
| **Table** | 表格 | 整表当Parent，每行当Child，每行重复列名 |
| **FAQ** | 问答文档 | 问题+关键词当Child，完整问答当Parent |
| **Manual** | 操作手册 | 每步带操作目标+前置步骤，完整章节当Parent |
| **Policy** | 政策条款 | 结论+例外绑定在一起，不拆散 |

#### 5.2 Table 策略

```
输入：第1行：套餐=月卡；价格=25元
      第2行：套餐=年卡；价格=168元

输出：
  Parent: 完整表格 (全部行)
  Child 1: 套餐=月卡；价格=25元
  Child 2: 套餐=年卡；价格=168元
```

#### 5.3 FAQ 策略

**状态机解析**（支持三种格式）：
```
等待问题
  ↓  Q：/ 问：/ 标题问句
收集问题
  ↓  A：/ 答：/ 后续段落
收集答案 (允许多行/多段)
  ↓  关键词：
解析关键词
  ↓  下一个Q 或 文件结束
保存一组 FAQ
```

**输出**：
```
Parent: 问题：大会员可以退款吗？
        答案：重复扣费可以申请退款...

Child:  大会员 / 退款：大会员可以退款吗？
        关键词：重复扣费、未使用权益
```

#### 5.4 Manual 策略

**输出特点**：每个步骤 Child 都包含：
- 操作目标
- 当前步骤
- 说明文本
- 前置步骤 (从第2步开始)

这样用户只问"下一步做什么"时，召回结果仍带有完整上下文。

#### 5.5 Policy 策略

**核心机制**：识别例外前缀，把例外绑定到前一个结论。

例外前缀：`但、但是、不过、除非、例外、不适用、不得、不支持`

```
"重复扣费可以申请退款。"
    + "但已消耗权益不支持退款。"
    ↓
  一个 policy-child (包含结论+例外)
```

metadata 中标记 `contains_exception=true`，方便后续评估。

#### 5.6 StrategySelector 与混合策略

```
StrategySelector.select(knowledge_type)
        │
        ▼
  _TableAwareStrategy 包装器
        │
        ├── TABLE 块 → TableChunkStrategy
        └── 非TABLE块 → 文档策略 (Policy/Manual/FAQ/Generic)
```

**Mixed 文档**：按标题路径自动路由到不同策略
```
常见问题 / FAQ    → FAQ策略
操作步骤          → Manual策略
退款规则          → Policy策略
其他              → Generic策略
```

**代码位置**：`src/bili_support/knowledge/chunk_strategies.py`

---

### 第6站：Small-to-Big 反向扩大 — `knowledge/small_to_big.py`

**作用**：Child 命中后，如何还原为可供大模型阅读的 Parent 上下文。

#### 6.1 三个关键规则

1. **一个 Parent 只返回一次** — 避免重复上下文
2. **Parent 顺序 = 第一次 Child 命中的顺序** — 不能依赖数据库 IN 查询的返回顺序
3. **保留证据** — 保存 matched_child_ids、best_child_score、first_child_rank

#### 6.2 算法示例

输入命中列表（按相关性排序）：
```
[
  {chunk_id: "child-a", score: 0.91},  # rank 1
  {chunk_id: "child-c", score: 0.84},  # rank 2
  {chunk_id: "child-b", score: 0.79},  # rank 3
]
```

假设 `child-a` 和 `child-b` 都属于 `parent-1`，`child-c` 属于 `parent-2`：

输出：
```
parent-1:
  matched_child_ids: [child-a, child-b]
  best_child_score: 0.91
  first_child_rank: 1

parent-2:
  matched_child_ids: [child-c]
  best_child_score: 0.84
  first_child_rank: 2
```

#### 6.3 为什么需要这个模块？

这是 RAG 中 **Small-to-Big Retrieval** 的核心实现：

```
用户提问
    ↓
检索 Top-K Child (小块、精确)
    ↓
SmallToBigExpander 聚合
    ↓
去重后的 Parent 列表 (大块、完整)
    ↓
交给大模型生成回答
```

**代码位置**：`src/bili_support/knowledge/small_to_big.py`

---

### 第7站：Service 层业务编排 — `services/knowledge.py`

**作用**：串起整个上传、解析、分块、入库、重试流程。

#### 7.1 upload() — 上传主流程

```
文件名清理 + 大小校验
    ↓
计算 SHA-256
    ↓
获取或创建数据库用户
    ↓
查找或创建逻辑 Document
    ↓
按哈希查 Version
    ├── 命中 → 返回已有 Version (deduplicated=true)
    └── 未命中 → 继续
    ↓
创建 Version + queued Job
    ↓
保存原文件到存储
    ↓
提交事务 A
    ↓
调用 _process(job_id)
```

#### 7.2 _process() — 解析与分块

**两段短事务设计**（非常重要！）：

```
┌─────────────────────────────────────┐
│  事务 A：                            │
│  Job → processing                    │
│  attempt_count + 1                   │
│  记录 started_at                      │
└────────────┬────────────────────────┘
             │ commit
             ▼
┌─────────────────────────────────────┐
│  数据库事务外 (慢速操作)              │
│  读取原文件                           │
│  Loader 解析 → LoadedDocument        │
│  ChunkStrategy → ChunkDraft          │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│  事务 B：                            │
│  删除旧 SourceBlock / Chunk          │
│  写入新 SourceBlock                  │
│  写入 Parent Chunk                   │
│  写入 Child Chunk (关联parent_id)    │
│  Version → ready                     │
│  Job → succeeded                     │
└─────────────────────────────────────┘
```

**为什么两段事务？**

解析 PDF 或 DOCX 可能耗时较长。如果一直持有数据库事务，会长时间占用连接并扩大锁冲突。所以数据库只负责保存状态，慢速解析放在事务之外。

**代码位置**：`src/bili_support/services/knowledge.py`

---

## 五、跟读一次完整上传请求

假设上传一个 Markdown 文件 `membership.md`：

### Step 1: HTTP 入口
`api/knowledge.py::upload_document`
```
POST /api/v1/knowledge/documents
  → authenticate (鉴权)
  → UploadFile (读取上限+1字节)
  → BusinessDomain (枚举校验)
  → service.upload(...)
```

### Step 2: 上传编排
`services/knowledge.py::upload`
```
SHA-256 计算
  → active_document_by_identity (找逻辑文档)
  → version_by_hash (判重)
  → 创建 Version + Job
  → LocalKnowledgeFileStore.write (存原文件)
  → 事务A提交
  → _process(job_id)
```

### Step 3: 解析执行
`services/knowledge.py::_process`
```
Job → processing (事务A)
  → 读取文件 (storage.read)
  → Registry.load (选择Loader)
  → MarkdownLoader.load (解析)
  → LoadedDocument + LoadedSourceBlock
  → StrategySelector.select (选策略)
  → strategy.chunk (分块)
  → 写 SourceBlock + Chunk (事务B)
  → Version ready, Job succeeded
```

### Step 4: 返回结果
```
KnowledgeDocumentView
KnowledgeVersionView
job_id, job_status, block_count, chunk_count
```

---

## 六、关键设计决策总结

| 决策 | 原因 | 位置 |
|------|------|------|
| 5张表分开 | 逻辑文档、文件版本、解析任务、源块、检索单元各有独立生命周期 | entities.py |
| SHA-256 只在 Document 内判重 | 两个部门上传同一模板不应被合并 | services/knowledge.py |
| Loader 不直接输出 Chunk | Loader 忠实还原原文，Chunk 针对检索优化，解耦后可单独实验 | types.py |
| 两段短事务 | 慢速解析不占用数据库连接 | services/knowledge.py |
| local_id 不直接用数据库 UUID | 策略层是纯函数，不依赖数据库，便于测试和离线评估 | chunking.py |
| 软删除而非物理删除 | 商业客服需要审计知识历史 | services/knowledge.py |
| Parent/Child 两层结构 | Child 精确召回，Parent 完整回答，兼顾精度和上下文 | chunking.py |
| 表格每行重复列名 | 切分后每行仍保留列语义，避免孤立数字 | table_normalization.py |

---

## 七、推荐阅读顺序

1. **先看类型契约**：`src/bili_support/knowledge/types.py` — 理解输入输出
2. **再看数据模型**：`src/bili_support/models/entities.py` — 理解5张表
3. **基础分块**：`src/bili_support/knowledge/chunking.py` — Generic 策略
4. **专用策略**：`src/bili_support/knowledge/chunk_strategies.py` — 四种专用策略
5. **Small-to-Big**：`src/bili_support/knowledge/small_to_big.py` — 反向扩大
6. **Loader 注册表**：`src/bili_support/knowledge/loaders/base.py` — 解析器选择
7. **文件存储**：`src/bili_support/knowledge/storage.py` — 原文件存储
8. **表格规范化**：`src/bili_support/knowledge/table_normalization.py` — 表格语义
9. **Service 编排**：`src/bili_support/services/knowledge.py` — 完整流程
10. **API 层**：`src/bili_support/api/knowledge.py` — HTTP 接口

---

## 八、本周核心知识点回顾

| 概念 | 一句话理解 |
|------|------------|
| SourceBlock | Loader 忠实还原的原文结构，不做检索优化 |
| Chunk | 针对检索优化的知识单元，分 Parent 和 Child |
| Small-to-Big | 用小块召回，用大块回答，兼顾精度和完整性 |
| 幂等 | 相同文件重复上传不产生重复版本 |
| 两段事务 | 快速状态变更 + 慢速解析 + 结果写入，分开事务 |
| 策略模式 | 不同知识类型用不同分块策略，统一接口 |
| 注册表模式 | 按扩展名/知识类型动态选择实现 |
| 纯函数 | 分块策略不依赖数据库，方便测试和评估 |

本周的内容是 RAG 系统的基石——如果知识表示做得不好，后续的 Embedding 和检索再优化也只能更快地召回错误答案。
