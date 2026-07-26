# 第 5 周学习记录：RAG 知识表示与 Chunk

> 开始日期：2026-07-25  
> 学习重点：文档进入模型上下文之前，如何保存结构、语义、权限和可追溯性。

## 1. 本周最终目标

完成哔哩哔哩企业客服知识库的第一段完整链路：

```text
PDF / DOCX / Markdown / TXT
  → 文件校验与幂等
  → 文档解析
  → 结构化块
  → Parent / Child Chunk
  → 数据库存储
  → 可追溯调试结果
```

本周不学习向量数据库和相似度检索，它们属于第六周。当前先保证“放进知识库的内容是正确的”，
否则后续 Embedding 只会更快地召回错误、残缺或失去上下文的文本。

## 2. 模块划分

| Step | 内容 | 学习分工 |
|---|---|---|
| 5A | 文档、版本、解析任务、结构块和 Chunk 契约；Loader 与入库底座 | 工程代码由 Codex 自动完成，重点理解数据契约 |
| 5B | Policy/Manual/FAQ/Table/Generic 分块；Small-to-Big | 本周 AI 核心，重点理解和实现 Chunk 策略 |
| 5C | 固定 Chunk 数据集、策略比较、失败分析和调试接口 | 重点理解如何量化“分块是否正确” |

## 3. Step 5A：文档入库契约与自动工程底座（已完成）

### 3.1 要解决的问题

知识库不能只保存一段纯文本。每个 Chunk 至少要回答：

- 来自哪个文件、哪个版本和哪一页；
- 位于哪个标题路径；
- 是普通段落、FAQ、政策条款还是表格；
- 属于哪个哔哩哔哩业务域；
- 哪些用户或角色可以检索；
- 何时生效、何时失效；
- Child 命中后应返回哪个 Parent；
- 原文件更新后，旧 Chunk 如何失效并重建。

### 3.2 Codex 自动实现范围

- 文档、版本、解析任务、结构块、Chunk 数据模型和迁移；
- PDF、DOCX、Markdown、TXT Loader；
- SHA-256 文件幂等和版本关系；
- 上传、状态、失败重试、版本查询和删除接口；
- 解析错误码、状态机、Fixture 和测试；
- Mock 调度：本阶段不引入真实消息队列；
- 为 5B 提供稳定的结构化解析结果，不提前实现向量检索。

### 3.3 你需要掌握的核心契约

本步骤结束后，需要能够解释：

1. `Document`、`DocumentVersion`、`IngestionJob`、`SourceBlock`、`Chunk` 为什么不能合成一张表；
2. 文件哈希幂等与文档版本管理有什么区别；
3. 为什么 Loader 不应该直接输出最终向量 Chunk；
4. 页码、标题路径、权限和有效期为什么必须在分块前保留；
5. 解析失败为什么要记录稳定错误码并允许重试。

### 3.4 验收标准

- 四种文件类型能够进入同一个结构化 Loader 契约；
- 同一文件重复上传不会重复建版本；
- 文件内容变化会形成新版本；
- 每个结构块能追溯到文件、页码或标题路径；
- 表格不会在 Loader 阶段被压成无法恢复的普通字符串；
- 失败任务可定位、可重试，不影响其他文档；
- 后续 5B 可以只关注 Chunk 策略，不需要修改 Loader 和数据库边界。

## 4. 本步骤开始前的思考题与答案

### 问题一：为什么不能直接把 PDF 全文交给大模型？

全文通常超过上下文预算，而且检索粒度过粗。页眉、页脚、目录和跨页表格还会制造噪声。正确做法
是先保存文档结构，再根据知识类型生成可检索 Child 和可回答 Parent。

### 问题二：Loader 和 Chunker 的区别是什么？

Loader 负责忠实恢复源文档内容和结构；Chunker 负责针对检索目标重新组织文本。Loader 的输出应
尽量可逆，Chunker 的输出则针对召回率、完整性和上下文预算优化。

### 问题三：为什么同一个文件哈希不能代表永久不变的知识？

哈希只能证明字节是否相同。知识是否有效还取决于版本状态、生效时间、业务域、权限和是否已被新
版本替代。因此文件幂等和知识生命周期是两个不同问题。

## 5. Step 5A 实现结论

### 5.1 五个对象各自负责什么

| 对象 | 职责 | 不能合并的原因 |
|---|---|---|
| `KnowledgeDocument` | 逻辑知识、业务域、权限和软删除状态 | 一个逻辑知识可以有多个文件版本 |
| `KnowledgeDocumentVersion` | 一次不可变文件快照、哈希和存储位置 | 幂等、回滚和重建索引都以版本为边界 |
| `KnowledgeIngestionJob` | 一次解析尝试、状态、次数和错误码 | 失败重试不能篡改文件版本本身 |
| `KnowledgeSourceBlock` | Loader 忠实恢复出的标题、段落、列表和表格 | 它描述原文结构，不承担检索优化 |
| `KnowledgeChunk` | Parent/Child 检索单元 | 同一结构块可按不同策略重新分块 |

状态流转为：

```text
Version: pending ───────────────→ ready
              └───────────────→ failed

Job: queued → processing → succeeded
                    └────→ failed → retry → processing
```

### 5.2 Loader 统一契约

四种 Loader 都输出 `LoadedDocument`，内部包含有序 `LoadedSourceBlock`。每个结构块保留：

- `ordinal`：原文顺序；
- `block_type`：heading、paragraph、list 或 table；
- `content`：可读文本；
- `page_number`：PDF 来源页；
- `heading_path`：Markdown/DOCX 的标题层级；
- `metadata`：表格列名、行号等结构信息。

表格采用“每一行重复列名”的规范化表达。例如 `权益 | 有效期` 不会只变成孤立的单元格值，
而会形成 `权益: 1080P；有效期: 31天`。这样后续切成 Child 时仍保留列语义。

### 5.3 幂等和版本的边界

SHA-256 只在同一 `Document` 内判断文件字节是否已经入库：

- 相同标题、业务域和创建人构成同一逻辑文档；
- 相同哈希直接返回已有版本和任务，不重复解析；
- 哈希不同创建递增的新版本；
- 调用方也可以显式传入 `document_id` 为指定文档新增版本。

### 5.4 安全和商业化边界

- 文件名只取安全 basename，存储键由服务端版本 ID 构造；
- 上传读取有硬上限，不会先把无限大请求完整读进内存；
- 业务域由稳定枚举约束；
- 查询、版本、任务、重试和删除都校验创建人隔离；
- 删除采用软删除，为后续审计和索引失效保留依据；
- 对外只返回稳定解析错误码，不泄露解析器内部异常。

当前任务执行仍是进程内同步 Mock，这是有意保留的调度替换点。生产版应把 `_process(job_id)`
交给持久化消息队列，并增加病毒扫描、对象存储、租户级 RBAC、配额、并发幂等锁和孤儿文件清理。

### 5.5 推荐阅读路径

不要从最大的 `service` 文件硬读。推荐先认识数据，再沿一次真实请求倒着拼装：

1. `knowledge/types.py`：先理解 Loader 的统一输出是什么；
2. `models/entities.py`：理解输出最终保存到哪五张表；
3. `knowledge/loaders/base.py`：理解如何选择解析器和归一化错误；
4. `knowledge/loaders/implementations.py`：对比四种文件如何恢复结构；
5. `knowledge/table_normalization.py`：理解表格语义为什么不能丢；
6. `knowledge/storage.py`：理解原文件如何安全、不可变地保存；
7. `repositories/knowledge.py`：观察数据库查询边界；
8. `services/knowledge.py`：串起哈希、版本、任务、解析和失败重试；
9. `api/knowledge.py`：最后看 HTTP 输入如何进入 Service；
10. `main.py`：查看 Loader、文件存储和 Service 如何在应用启动时组装。

### 5.6 跟读一次完整上传请求

假设管理员上传 `membership.md`：

```http
POST /api/v1/knowledge/documents
Authorization: Bearer local-demo-token

title=大会员规则
business_domain=membership
access_scope=public,support
file=# 大会员\n\n## 自动续费\n\n关闭后下月不再扣费。
```

#### 第一站：`api/knowledge.py::upload_document`

阅读时观察四件事：

1. `actor` 不是客户端任意提交的用户 ID，而是鉴权依赖产生的 `UserContext`；
2. `BusinessDomain` 限制业务域只能使用系统支持的枚举；
3. 文件最多读取“配置上限 + 1”字节，Service 因而能判断超限，同时不会无限占用内存；
4. API 不写数据库，只把输入转换后交给 `KnowledgeIngestionService.upload`。

这一层应保持“薄”。如果把哈希、版本查询和文件解析都写在路由里，将来 CLI、后台管理页或消息
消费者就无法复用同一套业务规则。

#### 第二站：`services/knowledge.py::upload`

按以下断点顺序阅读：

```text
清理文件名、校验大小
  → 计算 SHA-256
  → 得到当前数据库用户
  → 查找或校验逻辑 Document
  → 在该 Document 内按哈希查 Version
  → 命中：返回已有 Version
  → 未命中：创建 Version + queued Job + 保存原文件
  → 提交事务
  → 调用 _process(job_id)
```

这里有两个容易混淆的判断：

- `active_document_by_identity` 回答“它属于哪个逻辑知识”；
- `version_by_hash` 回答“这个逻辑知识的相同文件是否已经上传过”。

如果只做哈希去重，不建立 `Document`，那么“两个部门恰好上传同一模板”可能被错误合并；如果只
建立 `Document` 而不做哈希，同一个文件重复点击上传又会产生大量无意义版本。

#### 第三站：`services/knowledge.py::_process`

该方法故意分为两段短事务：

```text
事务 A：Job → processing，attempt_count + 1
             ↓ commit
数据库事务外：读取文件 → Registry 选择 Loader → 解析 LoadedDocument
             ↓
事务 B：清理本版本旧 SourceBlock → 写入完整新结果
        Version → ready，Job → succeeded
```

解析 PDF 或 DOCX 可能耗时较长。如果解析期间一直持有数据库事务，会长期占用连接并扩大锁冲突。
所以数据库只负责保存状态，慢速解析放在事务之外。

解析失败则走 `_mark_failed`：

```text
Version.status = failed
Job.status = failed
Job.error_code = DOCUMENT_SIGNATURE_MISMATCH / DOCUMENT_PARSE_FAILED / ...
```

重试不会创建新文件版本，因为失败的是一次处理尝试，不是文件内容发生了变化。

#### 第四站：`loaders/base.py::DocumentLoaderRegistry.load`

注册表先通过扩展名选择 Loader，然后由具体 Loader 检查文件签名。例如把普通文本改名为
`broken.pdf`，扩展名会选择 `PdfLoader`，但 `%PDF` 签名检查会返回
`DOCUMENT_SIGNATURE_MISMATCH`。

异常分为两类：

- `DocumentLoadError`：已经是稳定业务错误，原样上抛；
- 其他异常：统一转换成 `DOCUMENT_PARSE_FAILED`，不把第三方库异常暴露给 API。

#### 第五站：四种 Loader

逐个对照输入和输出：

| Loader | 自然边界 | 关键追溯信息 |
|---|---|---|
| PDF | 页内文本块、页内表格 | `page_number`、`page_count` |
| DOCX | Word 正文中的标题、段落、列表、表格顺序 | `heading_path` |
| Markdown | `#` 标题、空行段落、Markdown 表格 | `heading_path` |
| TXT | 空行分段 | 编码回退结果 |

此时输出的是 `LoadedSourceBlock`，不是 `KnowledgeChunk`。例如一段 3000 字的政策条款仍可以是
一个 SourceBlock；5B 才决定它要生成几个 Child、返回哪个 Parent。

#### 第六站：`repositories/knowledge.py`

Repository 不判断“谁能访问、失败能否重试”，它只表达持久化操作。重点阅读：

- `active_document_by_identity`：寻找逻辑文档；
- `version_by_hash`：同一文档内去重；
- `next_version_number`：生成展示用版本号；
- `latest_job_for_version`：重复上传时恢复已有任务结果；
- `delete_blocks`：重试成功写入前清理旧解析结果。

业务规则留在 Service、SQL 查询留在 Repository，可以分别测试，也便于以后把 MySQL 查询优化而
不改变 API 行为。

### 5.7 用数据库结果验证你的理解

一次首次成功上传应形成：

```text
knowledge_documents          1 行：逻辑文档
knowledge_document_versions  1 行：文件 v1
knowledge_ingestion_jobs     1 行：succeeded
knowledge_source_blocks      N 行：标题、段落、表格等
knowledge_chunks             0 行：5B 尚未执行分块
```

相同文件再次上传：

```text
Document 数量不变
Version 数量不变
Job 数量不变
响应 deduplicated = true
```

修改文件内容再上传：

```text
Document 数量不变
新增 Version v2
新增一个 Job
新增 v2 对应的 SourceBlock
```

### 5.8 Step 5A 自测题与答案

**问题一：为什么 API 不能直接调用 `PdfLoader`？**

因为 API 不应该知道文件类型实现。它只接收请求，Registry 负责选择 Loader，Service 负责业务
编排。否则新增 DOCX 或后台任务入口时都要修改 HTTP 路由。

**问题二：为什么任务失败后不删除 Version？**

Version 是已经接收过某份文件的事实，也是原文件、哈希和失败记录的载体。保留它才能审计和重
试；删除后只剩一个无法解释的失败日志。

**问题三：为什么 `SourceBlock` 和 `Chunk` 必须分开？**

SourceBlock 追求忠实恢复原文，Chunk 追求检索效果。分开后可以重新实验分块策略，而不用反复解
析原文件，也不会因检索优化破坏文档结构。

**问题四：为什么不能在解析开始前一直保持数据库事务？**

文件读取和 PDF/DOCX 解析属于慢速外部工作。长事务会占用连接、持锁并增加失败回滚范围。两段短
事务能分别可靠记录“开始处理”和“完整结果”。

**问题五：为什么软删除比立即物理删除更合适？**

商业客服需要审计知识何时存在、由谁上传、曾经生成过什么版本。软删除先让知识退出有效集合，
后续再由独立保留策略清理原文件和历史数据。

## 6. 当前任务：Step 5B 结构化 Chunk 与 Small-to-Big

### 6.1 要完成什么

把 `SourceBlock` 转换为两层知识单元：

- **Parent Chunk**：保留足够完整的章节、条款、FAQ 或表格上下文，用于最终回答；
- **Child Chunk**：更短、更聚焦，未来用于关键词和向量召回；
- Child 必须通过 `parent_chunk_id` 找回 Parent；
- 标题路径、业务域、权限、版本、页码等元数据必须继承；
- 不同知识类型使用不同策略，不能只按固定字符数粗暴切割。

### 6.2 本步骤的核心学习问题

1. 为什么“检索文本”和“给模型看的回答上下文”不应总是同一段？
2. 政策条款、操作手册、FAQ 和表格分别应该按什么边界切？
3. 重叠窗口能解决什么问题，又会制造什么重复噪声？
4. 如何保证一个 Child 的命中可以稳定还原到唯一 Parent？

### 6.3 先修正一个分类概念

`Policy`、`Manual`、`FAQ`、`Generic` 描述的是整份文档采用哪类知识组织方式；`Table` 描述的是
文档内部某个 SourceBlock 的结构。它们不应该被放在同一个互斥枚举中：

```text
DocumentKnowledgeType
├── POLICY
├── MANUAL
├── FAQ
└── GENERIC

SourceBlockType
├── HEADING
├── PARAGRAPH
├── LIST
└── TABLE
```

策略选择采用两层规则：

```text
如果 SourceBlock.block_type == TABLE
    使用 TableChunkStrategy
否则
    按 DocumentKnowledgeType 选择 Policy / Manual / FAQ / Generic 策略
```

例如一份操作手册仍可能包含价格表。正文应使用 Manual 策略，表格块则应使用 Table 策略。

### 6.4 5B 只拆成三个实施模块

| 模块 | 内容 | 产出 |
|---|---|---|
| 5B-1 | Chunk 契约、策略接口、Generic 基线 | 一个 SourceBlock 能生成一个 Parent 和多个 Child |
| 5B-2 | Policy、Manual、FAQ、Table 专用策略 | 不同知识结构按自己的语义边界分块 |
| 5B-3 | 持久化接入和 Small-to-Big | 入库成功后写入 Chunk，Child 命中可还原 Parent |

`knowledge_type` 字段、API 参数、数据库迁移、Repository 写入等工程底座由 Codex 自动完成；你重点
理解并实现策略边界，不需要把精力放在 CRUD 上。

## 7. 当前动手任务：5B-1 Chunk 契约与 Generic 基线

### 7.1 写在哪里

主要文件：

```text
src/bili_support/knowledge/chunking.py
```

Small-to-Big 暂时不要写，等 5B-3 再进入：

```text
src/bili_support/knowledge/small_to_big.py
```

### 7.2 先理解输入和输出

输入不是整个 PDF，而是一组已经解析好的 SourceBlock：

```python
[
    LoadedSourceBlock(
        ordinal=0,
        block_type=SourceBlockType.HEADING,
        content="自动续费",
        heading_path=("大会员", "自动续费"),
    ),
    LoadedSourceBlock(
        ordinal=1,
        block_type=SourceBlockType.PARAGRAPH,
        content="大会员到期前一天会自动续费。用户可以在支付渠道关闭续费。",
        heading_path=("大会员", "自动续费"),
    ),
]
```

期望输出：

```text
Parent
  content = 标题路径 + 完整段落
  kind = parent

Child 1
  content = 大会员到期前一天会自动续费。
  parent_ref = Parent

Child 2
  content = 用户可以在支付渠道关闭续费。
  parent_ref = Parent
```

未来检索只索引两个 Child。命中 Child 2 后，不直接把短句交给大模型，而是通过 Parent 返回包含标
题和完整段落的上下文。

### 7.3 建议契约样例

这一段是结构样例，不是要求逐字复制：

```python
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from bili_support.knowledge.types import LoadedSourceBlock


class ChunkKind(StrEnum):
    PARENT = "parent"
    CHILD = "child"


class DocumentKnowledgeType(StrEnum):
    POLICY = "policy"
    MANUAL = "manual"
    FAQ = "faq"
    GENERIC = "generic"


class ChunkDraft(BaseModel):
    """尚未写数据库的分块结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    local_id: str
    kind: ChunkKind
    content: str = Field(min_length=1)
    source_block_ordinal: int = Field(ge=0)
    parent_local_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class ChunkStrategy(Protocol):
    def chunk(
        self,
        *,
        blocks: tuple[LoadedSourceBlock, ...],
    ) -> tuple[ChunkDraft, ...]: ...
```

为什么先使用 `local_id`，而不是直接生成数据库 `parent_chunk_id`？

策略层应该是纯函数，不应该依赖数据库。它先产生：

```text
parent-0
child-0-0 → parent-0
child-0-1 → parent-0
```

5B-3 持久化时再把这些局部引用映射为真正的 UUID。

### 7.4 Generic 策略需要完成的逻辑

`GenericChunkStrategy` 第一版只完成以下规则：

1. 忽略独立 `HEADING` 块，但通过正文的 `heading_path` 把标题写入 Parent；
2. 每个非空正文 SourceBlock 先生成一个 Parent；
3. Parent 内容格式为“标题路径 + 正文”；
4. 正文未超过 `child_max_chars` 时只生成一个 Child；
5. 超过上限时优先按中文句号、问号、叹号和换行切分；
6. 单句仍然过长时，才退化为固定字符窗口；
7. Child 保存 `parent_local_id`、页码、标题路径和源块序号；
8. 不能产生空 Child，也不能丢失非空正文内容。

建议构造参数：

```python
GenericChunkStrategy(
    child_max_chars=160,
    child_overlap_chars=20,
)
```

第一版不要引入 Tokenizer。字符数易于观察，5C 再比较字符切分与 Token 切分的差异。

### 7.5 标题路径的拼接样例

输入：

```python
heading_path = ("大会员", "自动续费")
content = "用户可以在支付渠道关闭自动续费。"
```

Parent：

```text
标题：大会员 > 自动续费
正文：用户可以在支付渠道关闭自动续费。
```

Child 可以保留更紧凑的检索文本：

```text
大会员 / 自动续费：用户可以在支付渠道关闭自动续费。
```

标题词进入 Child 后，用户查询“怎么关闭大会员自动续费”更容易命中；完整 Parent 则为最终回答提
供所属章节和原文上下文。

### 7.6 重叠窗口应该怎么理解

原文：

```text
关闭自动续费后，本月权益不受影响。会员将在当前周期结束后失效。
```

如果边界恰好切在两句之间，第二个 Child 可能只有“会员将在当前周期结束后失效”，缺少“关闭自
动续费”这个条件。少量 overlap 可以把条件带入下一块。

但 overlap 不是越大越好：

- 太小：跨边界语义仍然断裂；
- 太大：索引中出现大量重复文本，多个几乎相同结果挤占 Top-K；
- 第一版建议不超过 Child 大小的 10%～15%；
- 句子边界完整时，不必为了凑固定数值强行重叠。

### 7.7 本任务完成标准

用下面四个输入自行观察输出即可，测试不作为学习门禁：

1. 一个短段落：生成 1 Parent + 1 Child；
2. 一个包含三句话的长段落：生成 1 Parent + 多个 Child；
3. 带两级 `heading_path`：Parent 和 Child 都能看到标题语义；
4. 一个超过上限的无标点长字符串：仍能安全退化切分，不死循环、不丢文本。

### 7.8 5B-1 思考题与答案

**问题一：为什么 Parent 不直接参与第一阶段检索？**

Parent 通常更长，包含更多背景和多个事实，向量或关键词表示容易被稀释。Child 更聚焦，适合提高
召回精度；命中后再扩大到 Parent，兼顾召回和回答完整性。

**问题二：为什么不能每 160 个字符直接切一次？**

固定字符窗口可能从一个术语、条件或句子中间切断。优先在自然句子边界切分，只有单句本身超过上
限时才使用固定窗口，可以减少语义残缺。

**问题三：为什么标题要同时进入元数据和文本？**

元数据用于过滤、展示和追溯，但普通向量模型或 BM25 不一定读取独立元数据字段。把精简标题放进
Child 文本能提升召回；同时保留结构化 `heading_path` 才方便后续展示和策略调整。

**问题四：为什么 Strategy 不直接创建 ORM `KnowledgeChunk`？**

策略是需要频繁实验的纯算法。若直接依赖数据库，会让单元实验、离线评估和策略比较变慢，也把事
务与 UUID 生成混入分块逻辑。`ChunkDraft` 是算法层和持久化层之间的稳定边界。
