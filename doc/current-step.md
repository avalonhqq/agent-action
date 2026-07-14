# 当前任务：第 1 周 · Step 1

## 本次目标

理解标准 Python `src` 布局和 ASGI 启动方式，并完成最小健康接口练习。

## 先理解

```text
uvicorn：ASGI Server，监听网络
bili_support.main：Python 模块
app：模块中的 FastAPI 实例
FastAPI：路由、验证、OpenAPI 和响应框架
```

安装项目时使用 editable 模式：

```powershell
cd C:\workspace\agent-action\customer
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

这样 `src/bili_support` 会作为正式包导入，不需要手动修改 `PYTHONPATH`。

## 实践任务

### 1. 运行当前基线

```powershell
source .venv/Scripts/activate  
uvicorn bili_support.main:app --reload --port 8010
```

访问 `/health` 和 `/docs`。

### 2. 扩展 `/health`

修改 `src/bili_support/main.py`，返回：

```json
{
  "status": "ok",
  "service": "bili-support-ai",
  "version": "0.0.1"
}
```

### 3. 更新测试

修改 `tests/unit/test_health.py`，验证 HTTP 200 和三个字段。

### 4. 运行质量检查

```powershell
ruff check .
mypy src/bili_support
pytest
```

## 思考题

1. 为什么 `src` 布局比把包直接放在仓库根目录更能发现导入问题？
2. `uvicorn bili_support.main:app` 的三个组成部分分别是什么？
3. `/health` 和未来 `/ready` 的职责有什么不同？
4. 为什么 `/health` 不应该调用 LLM、PostgreSQL 或向量库？

## 本步验收

- 服务和 `/docs` 可访问。
- 健康响应包含三个字段。
- Ruff、mypy、pytest 通过。
- 能回答四个思考题。

完成后提交你的思路和测试输出，我会评审并进入第 1 周 Step 2：Python 类型系统、Pydantic Settings 和环境配置。

