# BiliSupport AI

全 Python 企业多 Agent 智能客服学习项目，使用仿真哔哩哔哩业务数据实现知识问答、业务查询、事实校验、安全治理和人工技能组接入。

> 本项目仅用于学习与作品演示，不连接、不代表哔哩哔哩真实生产系统。

## 项目状态

前七周已经完成，Milvus 向量检索与 Elasticsearch BM25 已接入：项目具备工程基线、
可替换的 LLM 调用链路、可持久化的多用户客服会话，以及可追溯、可版本化的文档解析能力。

- 已建立标准 `src/bili_support` 工程骨架。
- 已实现类型化配置、应用工厂、健康/就绪探针、统一错误响应、Request ID 和结构化日志。
- 已配置 Ruff、mypy、pytest、pre-commit 和非 root Docker 运行基线。
- 已实现 LLM 内部契约、确定性 Mock、OpenAI-compatible 适配器、Prompt 版本、结构化输出、上下文控制、Chat API、SSE 和安全用量记录。
- 已实现 SQLAlchemy 2 异步数据层、Alembic 迁移、用户/会话/消息/模型调用、简单鉴权、持久化 SSE 和 NiceGUI 页面。
- 已实现 PDF、DOCX、Markdown、TXT 统一 Loader、SHA-256 幂等、文档版本、解析任务和结构块持久化。
- 已实现 `EmbeddingProvider`、Milvus HNSW/COSINE、Elasticsearch 中文BM25、RRF和可降级检索。
- Agent、业务工具与证据校验会按周逐步实现。
- 课程采用“大模型核心学习 + 工程底座自动完成”模式：重点讲解并实验 Prompt、RAG、意图、Agent、安全和评估；CRUD、迁移、鉴权、页面与部署由 Codex 自动实现并通过门禁。

## 最终能力

- FastAPI API、SSE 流式对话和 NiceGUI 客服网站。
- MySQL 会话、消息、知识、FAQ、审计和反馈数据；Redis 缓存模型会话历史。
- PDF、DOCX、Markdown、TXT、CSV 等知识文档入库。
- Small-to-Big、标准问、中文 BM25、向量检索、RRF、批量 Reranker 和多实体覆盖。
- LangGraph 确定性多 Agent 和复合意图处理。
- 会员、订单、稿件、处罚等受控 Mock 业务工具。
- 本地中文NLI Claim Verification、PII 脱敏、权限和 Prompt Injection 防护。
- 低置信度、高风险问题转入 Mock 人工技能组。
- 离线评估、OpenTelemetry、Docker Compose 和完整演示材料。

详细目标见 [最终项目目标](doc/implementation-goals.md)。

## 项目结构

```text
agent-action/
├── Dockerfile                # 非 root 容器运行基线
├── compose.yaml              # API、MySQL、Redis、Milvus、Elasticsearch、MongoDB 编排
├── alembic.ini               # 数据库迁移配置
├── migrations/               # 可追踪 Schema 迁移
├── pyproject.toml             # 项目元数据、依赖和质量工具配置
├── .env.example               # 本地环境变量模板
├── README.md
├── src/
│   └── bili_support/
│       ├── main.py            # FastAPI 应用入口
│       ├── api/               # HTTP、SSE 和管理接口
│       ├── core/              # 配置、异常、日志和安全
│       ├── llm/               # 模型 Provider、Prompt 和用量
│       ├── graph/             # LangGraph 状态和工作流
│       ├── agents/            # Supervisor 与领域 Agent
│       ├── knowledge/         # 解析、分块、索引和混合检索
│       ├── tools/             # 受控业务工具和权限矩阵
│       ├── handoff/           # 人工技能组接口及 Mock
│       ├── models/            # SQLAlchemy 模型
│       ├── repositories/      # 数据访问边界
│       ├── services/          # 会话等应用用例和事务边界
│       ├── schemas/           # Pydantic 模型
│       ├── evaluation/        # 离线评估
│       ├── observability/     # 指标和追踪
│       └── ui/                # NiceGUI 页面
├── tests/
│   ├── unit/                  # 单元测试
│   ├── integration/           # 跨模块和接口测试
│   └── evaluation/            # AI 效果回归测试
├── data/
│   ├── knowledge/             # 本地知识样本，不提交运行产物
│   ├── fixtures/              # 仿真业务数据
│   └── evaluation/            # Golden Dataset
└── doc/                       # 目标、架构、计划、进度和决策
```

## 环境要求

- Windows 10/11、Linux 或 macOS。
- Python 3.12 或更高版本。
- Git，可选但推荐。
- 默认 SQLite/Mock 模式不要求外部服务；启用完整Hybrid知识检索时需要MySQL、Milvus和Elasticsearch；启用LangGraph持久化恢复时需要MongoDB Replica Set。
- Claim语义校验默认使用本地`mDeBERTa-v3-base-mnli-xnli`真实模型；首次问答会下载模型，生产部署应预下载并设置`BILI_SUPPORT_CLAIM_VERIFICATION_LOCAL_FILES_ONLY=true`。
- 使用容器启动时需要 Docker Desktop 或 Docker Engine。

检查 Python：

```powershell
python --version
```

如果 Windows 同时安装了多个 Python，可以使用：

```powershell
py -3.12 --version
```

Python 可从 [python.org](https://www.python.org/downloads/) 安装。Windows 安装时建议勾选 “Add Python to PATH”。

## Windows 安装与启动

### 1. 进入项目

```powershell
cd C:\workspace\agent-action
```

### 2. 创建虚拟环境

```powershell
py -3.12 -m venv .venv
```

如果系统只有一个可用 Python，也可以：

```powershell
python -m venv .venv
```

### 3. 激活虚拟环境

```powershell
.venv\Scripts\Activate.ps1
```

如果 PowerShell 拒绝执行激活脚本，可只为当前进程调整策略：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

也可以不激活，后续命令直接使用 `.venv\Scripts\python.exe`。

### 4. 更新安装工具

```powershell
python -m pip install --upgrade pip
```

### 5. 安装项目及开发依赖

```powershell
python -m pip install -e ".[dev]"
```

有NVIDIA显卡的Windows机器建议安装官方CUDA Torch wheel（版本应与`pyproject.toml`约束一致）：

```powershell
python -m pip install --force-reinstall --no-deps torch==2.13.0+cu130 --index-url https://download.pytorch.org/whl/cu130
```

安装后用`python -c "import torch; print(torch.cuda.is_available())"`确认；输出`False`时仍可使用CPU真实推理，但并发容量较低。

`-e` 表示 editable 安装，修改 `src/bili_support` 后无需重复安装。

如果已安装 [uv](https://docs.astral.sh/uv/)，也可以使用：

```powershell
uv venv --python 3.12
uv pip install -e ".[dev]"
```

### 6. 创建本地配置

```powershell
Copy-Item .env.example .env
```

`.env` 已加入 `.gitignore`，不要提交真实密钥。

### 7. 启动服务

首次运行建议先升级数据库：

```powershell
python -m alembic upgrade head
```

本地默认 SQLite，并开启开发自动建表；Alembic 仍是正式 Schema 演进方式。

```powershell
python -m uvicorn bili_support.main:app --reload --host 127.0.0.1 --port 8010
```

访问：

- 健康检查：<http://127.0.0.1:8010/health>
- 就绪检查：<http://127.0.0.1:8010/ready>
- OpenAPI 文档：<http://127.0.0.1:8010/docs>
- ReDoc：<http://127.0.0.1:8010/redoc>
- NiceGUI 企业客服工作台：<http://127.0.0.1:8010/support/>

停止服务：在终端按 `Ctrl+C`。

默认使用确定性 Mock，不需要 API Key。普通聊天示例：

```powershell
$body = @{ message = "大会员有哪些权益？"; history = @() } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/api/v1/chat `
  -ContentType "application/json" -Body $body
```

观察 SSE：

```powershell
curl.exe -N -X POST http://127.0.0.1:8010/api/v1/chat/stream `
  -H "Content-Type: application/json" `
  -d '{"message":"大会员有哪些权益？","history":[]}'
```

## Windows + WSL2 启动 Milvus

本机使用 `Ubuntu-24.04` WSL2 中的 Docker Engine。项目提供的脚本会：

1. 启动一个隐藏 WSL 保活进程，防止命令结束后 Docker 被一并终止。
2. 启动 Docker daemon。
3. 启动 Milvus Standalone、etcd 和 MinIO。

```powershell
cd C:\workspace\agent-action
powershell -ExecutionPolicy Bypass -File .\scripts\start_milvus.ps1
```

首次拉取镜像后，Milvus 通常还需要约一分钟变为健康状态：

```powershell
wsl -d Ubuntu-24.04 -- sh -lc "cd /mnt/c/workspace/agent-action && docker compose ps milvus"
```

正常状态应显示 `healthy`。服务入口：

- Milvus SDK：<http://127.0.0.1:19530>
- Milvus WebUI/健康服务：<http://127.0.0.1:9091/webui/>
- 健康检查：<http://127.0.0.1:9091/healthz>
- MinIO Console：<http://127.0.0.1:9001>

仅停止 Milvus 组件：

```powershell
wsl -d Ubuntu-24.04 -- sh -lc "cd /mnt/c/workspace/agent-action && docker compose stop milvus milvus-etcd milvus-minio"
```

本地原生 Python API 使用 `BILI_SUPPORT_MILVUS_URI=http://127.0.0.1:19530`；
Compose 内的 API 使用 `http://milvus:19530`。默认 Collection 为
`bili_support_child_v2`，其向量维度必须和 Embedding 模型一致。更换模型或维度时应创建
新 Collection，不要复用不兼容的旧 Schema。

## Windows + WSL2 启动 MongoDB Checkpoint

LangGraph执行状态使用MongoDB保存，业务事实仍在MySQL。开发环境启动单节点Replica Set：

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/workspace/agent-action && docker compose up -d mongodb mongodb-init-replica"
```

确认副本集已经产生可写Primary：

```powershell
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/workspace/agent-action && docker compose exec -T mongodb mongosh --quiet --eval 'db.adminCommand({hello:1}).isWritablePrimary'"
```

本地应用连接地址为
`mongodb://127.0.0.1:27017/?directConnection=true&replicaSet=rs0`。Compose内API使用服务名
`mongodb`。本地实例无认证且仅绑定`127.0.0.1`，不能照搬到生产；生产必须配置认证、TLS、多节点副本集、
密钥管理、备份和恢复演练。Checkpoint载荷支持AES-EAX加密，生产必须通过Secret Manager注入
`BILI_SUPPORT_GRAPH_CHECKPOINT_ENCRYPTION_KEY`（16/24/32字节）。`BILI_SUPPORT_GRAPH_CHECKPOINT_REQUIRED=true`时MongoDB不可用会失败关闭，
不会降级为内存Saver。

执行真实的“写入→关闭连接→新连接恢复”验收：

```powershell
.venv\Scripts\python.exe scripts\verify_mongodb_checkpoint.py
```

## Windows + WSL2 启动 Elasticsearch

Elasticsearch负责生产运行时的中文BM25词法召回，Milvus仍负责向量召回。当前本地实例绑定
`127.0.0.1:9200`且关闭安全认证，只允许开发机使用；生产环境必须开启TLS、账号认证和网络隔离。

```powershell
cd C:\workspace\agent-action
wsl -d Ubuntu-24.04 -- bash -lc "cd /mnt/c/workspace/agent-action && docker compose up -d elasticsearch"
Invoke-RestMethod http://127.0.0.1:9200
```

启用应用侧ES检索：

```dotenv
BILI_SUPPORT_ELASTICSEARCH_ENABLED=true
BILI_SUPPORT_ELASTICSEARCH_REQUIRED=true
BILI_SUPPORT_ELASTICSEARCH_URL=http://127.0.0.1:9200
BILI_SUPPORT_ELASTICSEARCH_INDEX_PREFIX=bili-support-child
BILI_SUPPORT_ELASTICSEARCH_READ_ALIAS=bili-support-child-read
```

首次接入或需要人工修复时执行全量同步：

```powershell
.\.venv\Scripts\python.exe -m bili_support.knowledge.lexical_sync_cli
# 或安装项目后使用：bili-lexical-sync
```

同步读取MySQL中`document active + version current + index active`的Child，并把active领域词典匹配结果写入`domain_terms`。物理索引名包含
快照generation；全部Bulk写入和Refresh成功后，才原子切换`bili-support-child-read`别名。相同generation
重复执行直接复用，失败则保留旧别名。以下事件会自动触发全量同步：

- 应用启动，用于修复停机期间产生的漂移。
- 新知识索引成功激活。
- 新领域词典版本发布并激活。
- 逻辑知识文档被软删除。

查看当前数据：

```powershell
Invoke-RestMethod http://127.0.0.1:9200/_alias/bili-support-child-read
Invoke-RestMethod http://127.0.0.1:9200/bili-support-child-read/_count
```

### 存储职责

- MySQL：文档、版本、权限、Chunk 正文、索引任务的事实来源。
- Milvus：Child Chunk 向量与检索过滤所需的少量冗余元数据。
- Elasticsearch：活动Child的中文BM25副本和领域词命中；可删除重建，不是事实来源。
- MinIO：Milvus 内部对象数据；不是客服知识正文的事实来源。
- etcd：Milvus 内部元数据协调。

因此Milvus和Elasticsearch都只是可重建索引，不替换MySQL。任一通道命中后仍需回MySQL做权限复核、
活动版本校验和Small-to-Big Parent还原。

### 构建知识版本向量索引

先上传并解析文档，得到状态为 `ready` 的 `version_id`，然后调用：

```powershell
$headers = @{
  Authorization = "Bearer local-demo-token"
  "X-User-ID" = "local-admin"
  "X-User-Name" = "Local Admin"
}
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v1/knowledge/versions/<version_id>/indexes" `
  -Headers $headers
```

相关接口：

- `POST /api/v1/knowledge/versions/{version_id}/indexes`：幂等创建并构建索引。
- `GET /api/v1/knowledge/versions/{version_id}/indexes`：查看构建历史。
- `GET /api/v1/knowledge/index-jobs/{job_id}`：查看任务状态和进度。
- `POST /api/v1/knowledge/index-jobs/{job_id}/retry`：重试失败构建。
- `POST /api/v1/knowledge/retrieve`：独立调试Vector、BM25或Hybrid RRF召回和Parent还原。

每条Milvus记录保留`index_version_id`作内部身份。新版本全部写完后，MySQL在一个事务中把旧索引标记为
`superseded`、新索引标记为`active`，并原子切换`KnowledgeDocumentVersion.is_current`。查询方不传版本号；
版本身份只用于服务端白名单、二次复核、引用和审计，失败和构建中的向量不会进入后续检索。

检索示例：

```powershell
$body = @{
  query = "大会员支付成功后多久生效？"
  business_domain = "membership"
  allowed_scopes = @("public")
  retrieval_mode = "hybrid" # 也可指定vector或bm25运行单路基线
  child_top_k = 10
  parent_top_k = 5
  history = @()
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8010/api/v1/knowledge/retrieve" `
  -Headers $headers -ContentType "application/json" -Body $body
```

该接口属于知识运营调试入口：只搜索当前管理身份创建的知识，并将请求权限与文档权限取交集。
正式客服链路从受信任的身份/租户上下文生成权限范围，不接收终端用户自报权限。

## Linux/macOS 安装与启动

```bash
cd /path/to/agent-action
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
python -m uvicorn bili_support.main:app --reload --host 127.0.0.1 --port 8010
```

## 不激活虚拟环境的 Windows 启动方式

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m uvicorn bili_support.main:app --reload --port 8010
```

这种方式不依赖 PowerShell 激活脚本，路径也更明确。

## 测试与代码质量

激活虚拟环境后运行：

```powershell
ruff check .
mypy src/bili_support
pytest
```

安装 Git 提交钩子：

```powershell
pre-commit install
pre-commit run --all-files
```

钩子会依次执行 Ruff、mypy 和 pytest。`scripts/quality.py` 优先使用项目 `.venv`，因此应先安装 `.[dev]`。

自动修复 Ruff 支持的问题：

```powershell
ruff check . --fix
```

只运行健康检查测试：

```powershell
pytest tests/unit/test_health.py
```

## 当前接口

### `GET /health`

当前响应：

```json
{
  "status": "ok",
  "service": "BiliSupport AI",
  "version": "0.0.1"
}
```

### `GET /ready`

就绪探针表达配置、数据库生命周期和模型 Provider 已完成装配：

```json
{
  "status": "ready",
  "service": "BiliSupport AI",
  "version": "0.0.1",
  "checks": {
    "configuration": "ready",
    "database": "ready",
    "llm_provider": "ready"
  }
}
```

### `POST /api/v1/chat`

接受 `message` 和可选的 user/assistant `history`，返回答案、模型、Token 用量、standalone query、改写原因和 Prompt 版本。客户端不能通过 history 注入 system/tool 消息。

### `POST /api/v1/chat/stream`

返回 `text/event-stream`，事件包括 `delta`、`completed` 和安全的 `error`。客户端断开时会关闭上游模型流。

## 持久化会话接口

以下接口需要请求头：

```http
Authorization: Bearer local-demo-token
X-User-ID: demo-user
X-User-Name: 演示用户
```

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/conversations` | 创建会话并获得 Thread ID |
| GET | `/api/v1/conversations` | 列举当前用户会话 |
| GET | `/api/v1/conversations/{thread_id}/messages` | 恢复历史消息 |
| POST | `/api/v1/conversations/{thread_id}/messages` | 普通回复并持久化 |
| POST | `/api/v1/conversations/{thread_id}/messages/stream` | SSE 回复并持久化 |

共享 Demo Token 只用于本地学习。生产环境必须接入 OIDC/OAuth2、企业 SSO 或可信 JWT，并从已验证 claims 获取用户身份。

## 知识文档入库接口

接口使用与会话相同的鉴权请求头。当前解析任务采用进程内同步 Mock 调度；接口和任务状态已按未来
消息队列边界设计，后续可替换为 Celery、Dramatiq 或云任务服务。

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/knowledge/documents` | 上传并解析 PDF、DOCX、Markdown 或 TXT |
| GET | `/api/v1/knowledge/documents` | 查询当前用户创建的有效文档 |
| GET | `/api/v1/knowledge/documents/{document_id}/versions` | 查询文档版本 |
| GET | `/api/v1/knowledge/versions/{version_id}/chunks` | 检查 Parent/Child 分块，可用 `kind=child` 过滤 |
| POST | `/api/v1/knowledge/versions/{version_id}/chunks/expand` | 模拟Child召回并批量还原去重后的Parent上下文 |
| POST | `/api/v1/knowledge/chunks/debug` | 不落库运行SourceBlock分块实验并返回诊断 |
| GET | `/api/v1/knowledge/jobs/{job_id}` | 查询解析状态、错误码和结构块数量 |
| POST | `/api/v1/knowledge/jobs/{job_id}/retry` | 重试失败任务 |
| DELETE | `/api/v1/knowledge/documents/{document_id}` | 软删除文档 |

PowerShell 上传示例：

```powershell
curl.exe -X POST http://127.0.0.1:8010/api/v1/knowledge/documents `
  -H "Authorization: Bearer local-demo-token" `
  -H "X-User-ID: demo-user" `
  -F "file=@.\data\knowledge\membership.md" `
  -F "title=大会员规则" `
  -F "business_domain=membership" `
  -F "knowledge_type=mixed" `
  -F "access_scope=public"
```

同一逻辑文档的相同字节会命中幂等结果；内容变化则创建下一版本。原文件默认保存在
`data/knowledge/files`，大小上限默认 10 MiB，可通过以下配置调整：

```dotenv
BILI_SUPPORT_KNOWLEDGE_STORAGE_DIR=./data/knowledge/files
BILI_SUPPORT_KNOWLEDGE_MAX_FILE_BYTES=10485760
```

`knowledge_type` 可选 `policy`、`manual`、`faq`、`generic` 或 `mixed`。综合 Word 手册通常同时
包含规则、步骤、FAQ 和表格，应使用默认的 `mixed`。上传响应中的 `chunk_count` 应大于 0；
随后用 Chunk 查询接口检查 `metadata_json.strategy` 和 FAQ `keywords`。

### 固定 Chunk 评估

评估集位于 `data/evaluation/chunk_dev_v1.jsonl`，覆盖 Word/Markdown FAQ、操作步骤、跨块政策
例外、表格行、Mixed 路由和无标点长文本。运行：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.chunk_cli
```

也可以在安装项目后使用：

```powershell
bili-chunk-eval
```

报告默认生成到：

```text
data/evaluation/chunk_report_v1.md
data/evaluation/chunk_report_v1.json
```

该评估比较 `generic_baseline` 和 `specialized` 的 Child 语义单元、Parent 上下文、策略匹配和
父子追溯质量。它不调用模型、不产生费用，也不代表第6周向量检索的 Recall@K。

### 固定检索评估

检索评估集位于`data/evaluation/retrieval_dev_v1.jsonl`。它通过完整在线检索服务运行，
因此要求当前`.env`中的MySQL、Milvus和Embedding配置与活动索引一致。

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.retrieval_cli `
  --mode vector `
  --user-id demo-user `
  --user-name "Demo User"
```

运行7A BM25基线：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.retrieval_cli `
  --mode bm25 `
  --user-id demo-user `
  --user-name "Demo User" `
  --output-prefix data/evaluation/retrieval_bm25_report_v1
```

对比二元分词与Jieba搜索分词时增加：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.retrieval_cli `
  --mode bm25 `
  --bm25-tokenizer jieba `
  --output-prefix data/evaluation/retrieval_bm25_jieba_report_v1
```

`--bm25-tokenizer`可选`bigram`或`jieba`，报告会保存实际分词器，防止不同实验结果混淆。

运行7B Hybrid RRF：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.retrieval_cli `
  --mode hybrid `
  --user-id demo-user `
  --user-name "Demo User" `
  --output-prefix data/evaluation/retrieval_hybrid_report_v1
```

运行7C Parent批量Rerank结构基线（默认确定性Mock，不调用真实模型）：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.retrieval_cli `
  --mode hybrid `
  --rerank `
  --rerank-candidate-k 10 `
  --user-id demo-user `
  --user-name "Demo User" `
  --output-prefix data/evaluation/retrieval_hybrid_rerank_mock_report_v1
```

安装项目后也可以运行：

```powershell
bili-retrieval-eval
```

默认输出：

```text
data/evaluation/retrieval_vector_report_v1.md
data/evaluation/retrieval_vector_report_v1.json
data/evaluation/retrieval_bm25_report_v1.md
data/evaluation/retrieval_bm25_report_v1.json
data/evaluation/retrieval_hybrid_report_v1.md
data/evaluation/retrieval_hybrid_report_v1.json
data/evaluation/retrieval_hybrid_rerank_mock_report_v1.md
data/evaluation/retrieval_hybrid_rerank_mock_report_v1.json
```

报告包含Recall@1/3/5、MRR@5、负例准确率、执行失败率、P50/P95及可定位失败样本。首版
Golden Dataset使用“可选文档标题+Parent正文锚点”定位相关知识，不依赖重新导入后会变化的UUID。

### 第8周Grounded Answer与RAG生成评估

知识Chat使用`grounded_support:v4`输出严格JSON；v3保留DeepSeek完整JSON形状和受限结构重试，v4进一步要求每条Claim选择最小、最直接的支持证据，随后依次校验引用集合、当前请求证据白名单和逐Claim支持度。
只有验证结果为`pass`才展示模型答案；`degrade`、`reject`或结构错误统一返回确定性安全文案。页面分别展示
候选证据、实际引用、Word/Markdown章节、PDF页码、Parent原文摘要和声明校验摘要。

运行固定预测重放：

```powershell
bili-rag-eval
```

或者：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.rag_cli
```

默认输出：

```text
data/evaluation/rag_replay_report_v1.md
data/evaluation/rag_replay_report_v1.json
```

`fixed_prediction_replay`只验收数据、校验器、指标和报告链路，不代表真实模型效果。

## 可选：接入 OpenAI-compatible 服务

编辑本地 `.env`，不要提交真实密钥：

```dotenv
BILI_SUPPORT_LLM_PROVIDER=openai_compatible
BILI_SUPPORT_LLM_BASE_URL=https://api.openai.com/v1
BILI_SUPPORT_LLM_MODEL=<你的模型名>
BILI_SUPPORT_LLM_API_KEY=<你的本地密钥>
```

兼容服务必须实现 Chat Completions 风格的 `/chat/completions` 普通和 SSE 响应。默认 Mock 是学习、测试和离线演示的推荐方式。

### 意图识别实验

主要交互入口是客服页面：

```text
http://127.0.0.1:8010/support/
```

工作台包含六个功能页签：

| 页签 | 功能 |
|---|---|
| 工作台 | 展示当前支持的真实能力、Mock边界并跳转到操作页 |
| 智能问答 | 新建会话、意图识别、Hybrid RAG和流式回答 |
| 知识入库 | 上传PDF/DOCX/Markdown/TXT并查看数据库文档 |
| 领域词条 | 创建带业务域、类型、别名、词频和来源的candidate |
| 审核发布 | 批准/拒绝候选、发布词典版本、查看Jieba制品 |
| 能力说明 | 区分真实链路与人工坐席、客服日志等Mock能力 |

打开顶部“连接身份”填写本地Bearer Token和用户信息。领域词条页面的“写入候选词”会直接写入
MySQL `knowledge_dictionary_terms`；审核和发布页面分别更新审核字段并创建
`knowledge_dictionary_versions`不可变快照。

首次初始化领域词候选，可执行幂等导入命令：

```powershell
.\.venv\Scripts\python.exe -m bili_support.knowledge.dictionary_seed
```

默认词表位于`data/fixtures/dictionary_terms_v1.json`，包含8个业务域、48个规范词及其别名。
导入只创建`candidate`，必须在“审核发布”页人工审核后才能进入发布制品；重复执行会跳过已有词。

发布版本同时保存Jieba文本和规范词/别名JSON快照。发布成功后制品会原子同步到
`BILI_SUPPORT_BM25_USER_DICTIONARY_PATH`，并自动重建Elasticsearch活动Child索引的`domain_terms`。
进程内Jieba/BM25继续作为离线对照和无ES测试后端；补检索实体覆盖只读取active版本快照。

在“请输入客服问题”中输入内容，点击“识别意图”，页面会展示顶层路由、子意图、实体、情绪、
风险、置信度、来源和澄清问题。意图识别不会创建会话或写入消息；需要正式客服回答时再点击
“发送并流式回答”。

不配置真实模型时，页面使用确定性 Mock 验证 Prompt、JSON Schema、解析和展示链路，并明确
标注 Mock 不代表真实分类效果。

命令行只保留为开发调试入口：

```powershell
.\.venv\Scripts\python.exe -m bili_support.intent.cli "怎么取消大会员？"
```

切换真实模型时，在本地 `.env` 填写以下配置，不要提交真实 Key：

```dotenv
BILI_SUPPORT_LLM_PROVIDER=openai_compatible
BILI_SUPPORT_LLM_BASE_URL=https://你的兼容服务地址/v1
BILI_SUPPORT_LLM_MODEL=你的模型名
BILI_SUPPORT_LLM_API_KEY=你的本地密钥
BILI_SUPPORT_LLM_TEMPERATURE=0.0
BILI_SUPPORT_LLM_STRUCTURED_OUTPUT_MODE=json_schema
BILI_SUPPORT_INTENT_PROMPT_VERSION=3
```

重启服务并刷新 `/support/` 后，页面会显示 `Provider: openai_compatible` 和配置的模型名。
当前页面使用两段式混合意图链路：精确规则在模型调用前短路；未命中时使用指定版本 Prompt，
随后只允许确定性策略向上提升风险或补充缺参澄清。被策略校正的结果标记为 `source=hybrid`，
页面同时展示策略编号，便于审计和复现。

正式发送消息也会经过同一个 `hybrid_v3` 实例。客服路由当前包括 `safety`、
`out_of_scope`、`clarification`、`human_review_mock`、`human_service_mock`、
`general_chat` 和 `knowledge_rag`。普通低风险业务问题会按意图业务域调用真实
`KnowledgeRetrievalService`，经过Milvus/Elasticsearch BM25召回、MySQL复核和Small-to-Big后，将有界Parent
证据交给`grounded_support:v1`回答。页面展示检索模式、证据数量和实际来源；无证据或检索故障时
不会回退到自由模型。人工坐席仍是Mock；不安全、领域外、澄清和高风险请求使用确定性回复。
流式接口会在文本前发送包含检索Trace的`event: route`。

客服RAG通道可通过配置选择已完成评估的检索器：

```dotenv
BILI_SUPPORT_CUSTOMER_RETRIEVAL_MODE=hybrid
BILI_SUPPORT_BM25_TOKENIZER=jieba
BILI_SUPPORT_BM25_JIEBA_HMM_ENABLED=false
BILI_SUPPORT_BM25_USER_DICTIONARY_PATH=./data/dictionaries/bilibili_support.txt
BILI_SUPPORT_RERANK_PROVIDER=mock
BILI_SUPPORT_RERANK_MODEL=mock-reranker-v1
BILI_SUPPORT_RERANK_TIMEOUT_SECONDS=10
BILI_SUPPORT_RERANK_MAX_CONCURRENCY=4
BILI_SUPPORT_RERANK_CANDIDATE_K=10
BILI_SUPPORT_CUSTOMER_RERANK_ENABLED=false
```

当前可选`vector`、`bm25`或`hybrid`。Hybrid并行运行Vector和BM25，使用RRF按排名融合并保留
每一路的原始排名与分数；单路故障时明确标记降级。权限范围由服务端身份生成，Chat请求体不能
自报`allowed_scopes`。

启用Elasticsearch时，BM25使用ES内置CJK analyzer并通过`domain_terms`融合active领域词典；关闭ES时，
Jieba搜索模式和`bigram`继续作为可重复的进程内对照基线。
固定集显示Jieba在Hybrid中把Recall@1从75%提升到87.5%、MRR@5从85.42%提升到91.67%。
分词器变化也会改变RRF分数，因此默认回答门禁已经发布`membership-query-v2`并重新校准阈值。

领域词典管理接口位于`/api/v1/knowledge/dictionary`：候选词必须经过审核，发布时生成带SHA-256的
不可变Jieba快照；新版本激活后旧版本保留为`superseded`，可下载回放。外部客服日志和工单当前只
提供`conversation_log_mock`与`ticket_mock`候选入口，不能绕过人工审核。

主要接口：

```text
POST /terms                         创建candidate
POST /candidates/mock               导入Mock候选
GET  /terms                         按业务域/状态筛选
POST /terms/{term_id}/review        approve或reject
POST /versions/publish              发布所有approved词
GET  /versions                      查看发布历史
GET  /versions/active/artifact      下载当前Jieba制品
GET  /versions/{version_id}/artifact 下载历史制品
```

Tokenizer不在用户请求中实时查询管理库。部署流水线下载已发布制品，校验`content_sha256`，写入
`BILI_SUPPORT_BM25_USER_DICTIONARY_PATH`指向的文件并重启实例；这样线上分词结果能关联明确版本，
也能通过部署旧制品完成回滚。当前项目复用知识管理Token，真正生产环境还需在网关增加运营角色RBAC。

7C已支持在Small-to-Big恢复Parent后一次性批量Rerank。`mock`只用于验证排序、Trace和降级结构，
固定集出现质量回退，因此正式Chat默认保持关闭。接入真实OpenAI-compatible模型时可设置
`BILI_SUPPORT_RERANK_PROVIDER=llm`，完成真实固定集评估后再决定是否开启
`BILI_SUPPORT_CUSTOMER_RERANK_ENABLED=true`。Reranker超时、无效响应或Provider故障时原样回退
RRF Parent顺序，不生成虚假的Rerank分数。

也可以使用同一条调试命令：

```powershell
.\.venv\Scripts\python.exe -m bili_support.intent.cli "我的账号被盗了，怎么找回？"
```

CLI 只输出通过 `IntentDecision` 校验的 JSON；非法 JSON、Schema 失败和 Provider
错误会返回稳定错误码。当前适配器会在 Base URL 后追加 `/chat/completions`，并要求兼容服务支持
OpenAI 风格的严格 `response_format=json_schema`。如果目标服务只支持 `json_object` 或纯文本 JSON，
需要在明确供应商后增加对应能力配置，不能假设其完全兼容。

### 固定意图评估

评估集位于：

```text
data/evaluation/intent_dev_v1.jsonl
```

使用 Mock 验证四策略批量链路和报告生成：

```powershell
$env:BILI_SUPPORT_LLM_PROVIDER="mock"
$env:BILI_SUPPORT_LLM_MODEL="mock-evaluation-model"
.\.venv\Scripts\python.exe -m bili_support.evaluation.intent_cli
Remove-Item Env:BILI_SUPPORT_LLM_PROVIDER
Remove-Item Env:BILI_SUPPORT_LLM_MODEL
```

生成的 Markdown 和 JSON 报告位于 `data/evaluation/`，属于本地运行产物，不提交版本控制。Mock
使用固定响应，只验证评估管线，分数不代表模型能力。

真实模型批量评估必须显式确认潜在费用。建议先运行少量样本：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.intent_cli `
  --strategies zero_shot_v1 few_shot_v2 `
  --max-cases 5 `
  --allow-paid
```

运行全部 48 条、四种策略时最多产生 192 次模型请求；混合策略的规则短路会减少实际调用。省略
`--allow-paid` 时，CLI 会在任何真实模型请求发出前停止。

失败归因后验证 Prompt v3：

```powershell
.\.venv\Scripts\python.exe -m bili_support.evaluation.intent_cli `
  --strategies tuned_v3 `
  --allow-paid `
  --output data/evaluation/intent_real_v3_report.md
```

`tuned_v3` 只产生最多 48 次新调用；v1/v2 的历史结构化预测可以在金标准修订后离线重新计分，无需
为了比较而重复付费调用。

DeepSeek 使用：

```dotenv
BILI_SUPPORT_LLM_BASE_URL=https://api.deepseek.com
BILI_SUPPORT_LLM_MODEL=deepseek-v4-flash
BILI_SUPPORT_LLM_STRUCTURED_OUTPUT_MODE=json_object
```

`json_object` 只保证返回合法 JSON，最终字段和跨字段关系仍由 `IntentDecision` Pydantic Schema
严格校验；校验失败不会进入路由或工具执行。

所有 HTTP 响应均带有 `X-Request-ID`。合法的调用方 Request ID 会被透传，缺失或非法时由服务生成。

业务错误采用稳定结构，内部异常和被拒绝的原始输入不会返回给客户端：

```json
{
  "success": false,
  "error": {
    "code": "RESOURCE_NOT_FOUND",
    "message": "请求的资源不存在",
    "details": null
  },
  "request_id": "request-example"
}
```

## Docker 启动

构建并启动：

```powershell
docker compose up --build
```

检查状态：

```powershell
docker compose ps
Invoke-RestMethod http://127.0.0.1:8010/health
Invoke-RestMethod http://127.0.0.1:8010/ready
```

停止服务：

```powershell
docker compose down
```

Compose 会启动 MySQL 8 和 Redis 7、等待依赖健康、执行 `alembic upgrade head`，再以非 root 用户运行 API。Docker `HEALTHCHECK` 调用轻量 `/health` 探针。

## 本地 MySQL 与 Redis

当前本地配置使用：

- MySQL `bili_support` 作为用户、会话、消息和模型调用的事实存储。
- Redis DB 0 缓存模型可见的会话历史，默认 TTL 900 秒。
- Redis 缓存异常时回退 MySQL；本地 `/ready` 仍会检查 MySQL 与 Redis。

真实连接密码只保存在 `.env`。建表 SQL和验证记录见 [MySQL/Redis 接入说明](doc/mysql-redis-setup.md) 与 [MySQL Schema](doc/mysql-schema.sql)。

## 常见问题

### `No module named bili_support`

通常是还没有执行 editable 安装：

```powershell
python -m pip install -e ".[dev]"
```

### `python` 或 `py` 找不到

重新安装 Python 并加入 PATH，或使用 Python 的绝对路径创建 `.venv`。

### 端口 8010 已被占用

换一个端口：

```powershell
python -m uvicorn bili_support.main:app --reload --port 8011
```

### FastAPI TestClient 出现上游弃用警告

当前依赖组合可能显示 Starlette TestClient 的弃用提示，不影响测试通过。后续会在依赖升级阶段统一处理，不应通过关闭所有警告掩盖真实问题。

## 学习文档

- [12 周大模型专项学习计划](doc/learning-plan.md)
- [2026-07-20 课程重排记录](doc/course-realignment-2026-07-20.md)
- [本地 MySQL/Redis 接入记录](doc/mysql-redis-setup.md)
- [MySQL 建表 SQL](doc/mysql-schema.sql)
- [当前任务](doc/current-step.md)
- [学习进度](doc/progress.md)
- [最终系统架构](doc/architecture.md)
- [产品与系统流程](doc/product-flow.md)
- [每周质量门禁](doc/quality-gates.md)
- [最终交付物](doc/final-deliverables.md)
- [协作规则](doc/collaboration-guide.md)
- [设计决策](doc/decisions.md)
- [外部计划对齐记录](doc/source-plan-alignment.md)
- [企业 RAG 项目参考评审](doc/reference-enterprise-rag-review.md)

第一周实现与知识问答见 [第一周完成报告](doc/week1-completion.md)。

第二周实现、逐步讲解与知识问答见 [第二周完成报告](doc/week2-completion.md)。

第三周数据层、会话、鉴权、NiceGUI 与知识问答见 [第三周完成报告](doc/week3-completion.md)。

第四周意图契约、Zero-shot、Few-shot 与混合分类任务见
[第四周学习与任务记录](doc/week4-learning-record.md)。

第五周文档解析、结构化Chunk与评估见[第五周学习与任务记录](doc/week5-learning-record.md)。

第六周Embedding、Milvus与Small-to-Big检索见[第六周学习与任务记录](doc/week6-learning-record.md)。

第七周BM25、RRF、Rerank与回答门禁见[第七周学习与任务记录](doc/week7-learning-record.md)。

第八周Grounded Answer、Claim Verification、RAG评估与可定位引用见
[第八周学习与任务记录](doc/week8-learning-record.md)。
