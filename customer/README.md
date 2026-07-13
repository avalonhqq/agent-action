# BiliSupport AI

面向哔哩哔哩仿真业务的全 Python 企业多 Agent 智能客服学习项目。

项目围绕一个主系统持续迭代，不做互不相关的小练习。最终交付包含客服网站、混合 RAG、LangGraph 多 Agent、受控业务工具、事实校验、安全治理、离线评估、链路观测和 Docker Compose 部署。

> 本项目只使用仿真数据和 Mock 业务接口，不接入或冒充哔哩哔哩真实生产系统。

## 当前状态

- 当前处于第 1 周：Python AI 工程基础与项目初始化。
- 已建立标准 `src/bili_support` 教学骨架。
- 只实现最小 `/health`，其余模块按周逐步完成。
- 旧原型答案代码不保留，学习者负责实现，我负责讲解、评审和留档。

## 文档导航

- [最终项目目标](doc/implementation-goals.md)
- [12 周学习计划](doc/learning-plan.md)
- [最终系统架构](doc/architecture.md)
- [用户与系统流程](doc/product-flow.md)
- [每周质量门禁](doc/quality-gates.md)
- [最终交付物](doc/final-deliverables.md)
- [当前任务](doc/current-step.md)
- [学习进度](doc/progress.md)
- [协作规则](doc/collaboration-guide.md)
- [设计决策](doc/decisions.md)
- [外部计划对齐记录](doc/source-plan-alignment.md)

## 开发环境

要求 Python 3.12+。

```powershell
cd C:\workspace\agent-action\customer
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn bili_support.main:app --reload --port 8010
```

访问：

- `http://127.0.0.1:8010/health`
- `http://127.0.0.1:8010/docs`

## 开发检查

```powershell
ruff check .
mypy src/bili_support
pytest
```

请从 [当前任务](doc/current-step.md) 开始，不跨周提前实现。
