# BiliSupport AI

全 Python 企业多 Agent 智能客服学习项目，使用仿真哔哩哔哩业务数据实现知识问答、业务查询、事实校验、安全治理和人工技能组接入。

> 本项目仅用于学习与作品演示，不连接、不代表哔哩哔哩真实生产系统。

## 项目状态

当前处于 12 周计划的第 1 周：Python AI 工程基础与项目初始化。

- 已建立标准 `src/bili_support` 工程骨架。
- 当前只实现最小 `/health` 接口。
- LLM、数据库、知识库、RAG、Agent、业务工具和页面会按周逐步实现。
- 项目采用“讲解 → 设计 → 学习者编码 → 测试 → 评审 → 复盘”的方式推进。

## 最终能力

- FastAPI API、SSE 流式对话和 NiceGUI 客服网站。
- PostgreSQL 会话、消息、知识、FAQ、审计和反馈数据。
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
customer/
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
- 当前阶段不要求 PostgreSQL、Docker 或模型 API Key。

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
cd C:\workspace\agent-action\customer
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

### 6. 创建本地配置

```powershell
Copy-Item .env.example .env
```

`.env` 已加入 `.gitignore`，不要提交真实密钥。

### 7. 启动服务

```powershell
python -m uvicorn bili_support.main:app --reload --host 127.0.0.1 --port 8010
```

访问：

- 健康检查：<http://127.0.0.1:8010/health>
- OpenAPI 文档：<http://127.0.0.1:8010/docs>
- ReDoc：<http://127.0.0.1:8010/redoc>

停止服务：在终端按 `Ctrl+C`。

## Linux/macOS 安装与启动

```bash
cd /path/to/customer
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
  "status": "ok"
}
```

第 1 周练习会增加服务名、版本、`/ready`、统一响应和结构化日志。

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

- [12 周学习计划](doc/learning-plan.md)
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

现在请从 [第 1 周 Step 1](doc/current-step.md) 开始，不跨阶段提前实现。
