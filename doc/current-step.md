# 已完成：第 1 周 · Step 2

> 验收日期：2026-07-16。Ruff、mypy 和 8 项 pytest 全部通过；五道思考题通过。

## 主题

Python 类型系统、Pydantic Settings 与多环境配置。

## 本次目标

把散落在代码中的服务名、版本、运行环境、地址和日志级别集中到一个经过类型校验的配置对象中，并让 `.env`、系统环境变量和测试参数能够安全覆盖默认值。

## 需要理解的知识点

### 1. 类型提示不是运行时校验

```python
port: int
```

普通 Python 类型提示主要服务于 IDE 和 mypy，本身不会自动阻止字符串进入变量。Pydantic 会在运行时解析、转换和校验外部配置。

### 2. Enum/Literal 的作用

运行环境不能接受任意字符串，只允许：

```text
local / test / staging / production
```

本练习建议使用继承自 `str, Enum` 的 `Environment`，理解它与 `Literal` 的差异。

### 3. 配置来源优先级

需要理解以下来源如何覆盖：

```text
代码默认值 < .env < 系统环境变量 < 显式初始化参数
```

测试不应依赖开发者本机的 `.env`。

### 4. 配置错误应尽早失败

生产环境的危险配置不应等到请求到达才报错，而应在应用启动阶段失败。例如：

```text
environment=production 且 debug=true → 配置无效
```

## 实践任务

### 任务 1：实现 Environment

在 `src/bili_support/core/config.py` 中定义四个环境：

- `local`
- `test`
- `staging`
- `production`

要求：

- 可与字符串比较或序列化。
- 非法环境值会触发 Pydantic 校验错误。

### 任务 2：实现 Settings

使用 `pydantic-settings` 实现配置类，至少包含：

| 字段 | 类型 | 默认值 |
|---|---|---|
| `app_name` | `str` | `BiliSupport AI` |
| `app_version` | `str` | `0.0.1` |
| `environment` | `Environment` | `local` |
| `debug` | `bool` | `False` |
| `host` | `str` | `127.0.0.1` |
| `port` | 受约束整数 | `8010` |
| `log_level` | 受限字符串或 Enum | `INFO` |

配置要求：

- 环境变量前缀为 `BILI_SUPPORT_`。
- 默认读取项目根目录 `.env`。
- 忽略 `.env` 中暂时还没有模型字段的额外配置。
- `port` 限制在 `1～65535`。
- production 环境禁止 `debug=True`。

### 任务 3：实现 get_settings

提供统一入口：

```python
get_settings() -> Settings
```

思考是否需要缓存，以及缓存对测试环境变量修改有什么影响。

### 任务 4：让应用读取配置

修改 `src/bili_support/main.py`：

- FastAPI 的 `title` 来自 Settings。
- FastAPI 的 `version` 来自 Settings。
- `/health` 的 `service` 和 `version` 来自同一个 Settings 对象。
- 不再在多个位置重复写 `BiliSupport AI` 或 `0.0.1`。

### 任务 5：更新 `.env.example`

确保变量名与实际 Settings 字段一致，至少包含：

```dotenv
BILI_SUPPORT_ENVIRONMENT=local
BILI_SUPPORT_DEBUG=false
BILI_SUPPORT_HOST=127.0.0.1
BILI_SUPPORT_PORT=8010
BILI_SUPPORT_LOG_LEVEL=INFO
```

不要创建或提交包含真实密钥的 `.env`。

### 任务 6：编写测试

新增 `tests/unit/test_config.py`，至少覆盖：

1. 默认配置正确。
2. 环境变量能把端口字符串转换为整数。
3. 非法端口被拒绝。
4. 非法 environment 被拒绝。
5. production + debug 被拒绝。
6. FastAPI title/version 和 `/health` 使用同一配置来源。

测试必须隔离本机 `.env`，并处理 `get_settings` 缓存，防止用例相互污染。

## 设计约束

- 当前不加入数据库、LLM、Embedding 配置，避免跨阶段。
- 当前不实现 `/ready`，它属于后续步骤。
- 不在业务模块中直接调用 `os.getenv()`。
- 不把密钥写入默认值、日志或测试断言。
- 配置校验错误不应被静默替换成默认值。

## 思考题

1. 为什么业务代码应依赖 `Settings`，而不是到处调用 `os.getenv()`？
2. 为什么 production + debug 应在启动时失败，而不是自动改成 false？
3. 为什么 `get_settings()` 适合缓存？测试时为什么又要清理缓存？
4. `Environment(str, Enum)` 与 `Literal[...]` 各有什么优缺点？
5. `.env` 与 `.env.example` 分别应该提交哪一个？为什么？

## 运行检查

```powershell
cd C:\workspace\agent-action
.venv\Scripts\Activate.ps1

ruff check .
mypy src/bili_support
pytest
```

## 本步验收标准

- 六类配置测试全部通过。
- 现有健康测试继续通过。
- Ruff 和 mypy 通过。
- 配置只有一个事实来源。
- 能回答五个思考题。

完成后执行 Git 提交，并告诉我“Step 2 已完成，请评审”。

建议提交信息：

```text
feat: add typed application settings
```
