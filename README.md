# BiliSupport AI

全 Python 企业多 Agent 智能客服学习项目，使用仿真哔哩哔哩业务数据实现知识问答、业务查询、事实校验、安全治理和人工技能组接入。

> 本项目仅用于学习与作品演示，不连接、不代表哔哩哔哩真实生产系统。

## 项目状态

前三周已经完成：项目具备工程基线、可替换的 LLM 调用链路，以及可持久化的多用户客服会话。

- 已建立标准 `src/bili_support` 工程骨架。
- 已实现类型化配置、应用工厂、健康/就绪探针、统一错误响应、Request ID 和结构化日志。
- 已配置 Ruff、mypy、pytest、pre-commit 和非 root Docker 运行基线。
- 已实现 LLM 内部契约、确定性 Mock、OpenAI-compatible 适配器、Prompt 版本、结构化输出、上下文控制、Chat API、SSE 和安全用量记录。
- 已实现 SQLAlchemy 2 异步数据层、Alembic 迁移、用户/会话/消息/模型调用、简单鉴权、持久化 SSE 和 NiceGUI 页面。
- 数据库、知识库、RAG、Agent、业务工具和页面会按周逐步实现。
- 课程采用“大模型核心学习 + 工程底座自动完成”模式：重点讲解并实验 Prompt、RAG、意图、Agent、安全和评估；CRUD、迁移、鉴权、页面与部署由 Codex 自动实现并通过门禁。

## 最终能力

- FastAPI API、SSE 流式对话和 NiceGUI 客服网站。
- MySQL 会话、消息、知识、FAQ、审计和反馈数据；Redis 缓存模型会话历史。
- PDF、DOCX、Markdown、TXT、CSV 等知识文档入库。
- Small-to-Big、标准问、中文 BM25、向量检索、RRF、批量 Reranker 和多实体覆盖。
- LangGraph 确定性多 Agent 和复合意图处理。
- 会员、订单、稿件、处罚等受控 Mock 业务工具。
- Verification 事实校验、PII 脱敏、权限和 Prompt Injection 防护。
- 低置信度、高风险问题转入 Mock 人工技能组。
- 离线评估、OpenTelemetry、Docker Compose 和完整演示材料。

详细目标见 [最终项目目标](doc/implementation-goals.md)。

## 项目结构

```text
agent-action/
├── Dockerfile                # 非 root 容器运行基线
├── compose.yaml              # 当前 API 服务编排
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
- 默认 SQLite 模式不要求 MySQL、Redis、Docker 或模型 API Key；当前本地 `.env` 已切换到 MySQL/Redis。
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
- NiceGUI 客服页：<http://127.0.0.1:8010/support/>

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
```

重启服务并刷新 `/support/` 后，页面会显示 `Provider: openai_compatible` 和配置的模型名。
也可以使用同一条调试命令：

```powershell
.\.venv\Scripts\python.exe -m bili_support.intent.cli "我的账号被盗了，怎么找回？"
```

CLI 只输出通过 `IntentDecision` 校验的 JSON；非法 JSON、Schema 失败和 Provider
错误会返回稳定错误码。当前适配器会在 Base URL 后追加 `/chat/completions`，并要求兼容服务支持
OpenAI 风格的严格 `response_format=json_schema`。如果目标服务只支持 `json_object` 或纯文本 JSON，
需要在明确供应商后增加对应能力配置，不能假设其完全兼容。

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
