# 第 1 周完成报告：Python AI 工程基础

> 完成日期：2026-07-17

## 1. 本周交付结果

第一周建立的不是客服业务功能，而是后续 LLM、RAG、多 Agent 和业务工具共同依赖的工程底座。

### 1.1 标准 Python 工程

- 使用 `src/bili_support` 布局，避免测试从仓库根目录“意外导入”未安装源码。
- 使用 `pyproject.toml` 统一管理包信息、运行依赖、开发依赖和质量工具。
- 使用应用工厂 `create_app(settings)`，生产环境读取统一配置，测试可以显式注入配置。

### 1.2 类型化配置

- `Environment` 限定 local/test/staging/production。
- `LogLevel` 限定合法日志级别。
- `Settings` 集中管理服务名、版本、环境、debug、host、port 和日志级别。
- 环境变量统一使用 `BILI_SUPPORT_` 前缀。
- 端口限制为 1～65535。
- production 与 debug=true 的危险组合在启动时失败。
- `get_settings()` 缓存应用生命周期内的配置，测试负责清理缓存。

### 1.3 稳定 API 契约与异常边界

- `ApiResponse[T]` 保留成功数据的具体类型。
- `ErrorResponse` 使用稳定的 `code/message/details/request_id` 结构。
- 核心层 `AppError` 不依赖 FastAPI。
- 404、403、409 等预期业务异常在 API 边界转换成公开响应。
- 请求校验错误不回显被拒绝的原始值。
- 未知异常只返回 `INTERNAL_ERROR` 和通用提示，普通日志只记录异常类型与 Request ID，不记录原始异常文本。
- `/health`、`/ready` 是平台探针，不套普通业务响应外壳。

### 1.4 Request ID 与结构化日志

- 每个 HTTP 请求都有 `X-Request-ID`。
- 格式合法的上游 ID 会被透传，否则生成 32 位随机 ID。
- Request ID 同时进入响应头、错误响应和访问日志。
- structlog 输出 JSON，记录 method、path、status_code、duration_ms 和 Request ID。
- 访问日志只记录 URL path，不记录 query value、请求体和密钥。
- ContextVar 为后续异步 Agent/Tool 调用提供请求上下文传播基础。

### 1.5 健康检查与就绪检查

- `/health` 表示进程存活并能响应 HTTP。
- `/ready` 表示当前强制依赖已经初始化。
- 第一周尚无数据库、模型和索引强制依赖，因此 readiness 只报告启动时已验证的配置。
- 后续增加强制依赖时扩展 `checks`，而不是让 `/health` 查询外部系统。

### 1.6 质量门禁和容器基线

- Ruff 检查代码风格和常见错误。
- mypy strict 检查核心包类型。
- pytest 覆盖配置、响应模型、异常、安全错误边界、Request ID、日志和探针。
- pre-commit 在提交前执行 Ruff、mypy、pytest。
- Docker 镜像使用 Python 3.12 slim 和非 root 用户。
- `.dockerignore` 排除虚拟环境、缓存、开发文档和运行数据。
- Docker `HEALTHCHECK` 使用轻量 `/health`。
- `compose.yaml` 提供当前 API 的一键启动入口。

## 2. 当前请求处理流程

```text
HTTP 请求
→ RequestContextMiddleware 校验或生成 Request ID
→ 绑定 structlog ContextVar
→ FastAPI 参数校验与路由
→ 成功响应，或 AppError/未知异常处理器
→ 响应头写入 X-Request-ID
→ 输出不含请求敏感值的结构化访问日志
```

## 3. 第一周遇到的问题与修复

### 3.1 测试受到本机 `.env` 影响

- 根因：`Settings` 默认从当前工作目录读取 `.env`。
- 修复：测试使用 `tmp_path` 切换到临时目录，并用 `monkeypatch` 管理环境变量。
- 经验：测试通过不等于测试隔离；必须主动验证外部配置来源。

### 3.2 FastAPI app 在模块导入时固化配置

- 根因：修改环境变量和清理配置缓存不会重建已创建的 `app`。
- 修复：增加 `create_app(settings)`，测试直接注入 Settings。
- 经验：应用工厂提升可测试性，也为未来集成测试和多配置启动提供边界。

### 3.3 删除 `sys.modules` 重载应用过于脆弱

- 根因：强制删除模块可能产生同名但不同身份的类，并污染其他测试。
- 修复：使用依赖注入，不再修改 Python 模块缓存。

### 3.4 pre-commit 调用了 Conda Python

- 根因：`language: system` 使用 PATH 中的 Python，当时不是项目 `.venv`。
- 修复：`scripts/quality.py` 跨平台查找项目 `.venv`，再运行三个质量门禁。
- 经验：自动化脚本必须明确运行时，不应依赖开发者当前终端状态。

### 3.5 ContextVar 测试捕获模式不自动合并字段

- 根因：structlog 的测试捕获处理器会临时替换正常 processor 链。
- 修复：访问日志除绑定 ContextVar 外，也显式写入 `request_id`。
- 经验：关键日志字段应形成可直接测试的稳定契约。

## 4. 第一周问题与参考答案

### 4.1 工程与 ASGI

#### 问题 1：为什么采用 src 布局？

核心原因是防止“意外通过”。源码不因位于仓库根目录就自动可导入，测试应验证安装后的包。它还能提前发现包配置、缺失文件和错误导入路径。

#### 问题 2：`uvicorn bili_support.main:app` 分别表示什么？

Uvicorn 是监听 HTTP 连接并调用 ASGI 应用的服务器；`bili_support.main` 是 Python 模块；`app` 是模块中的 FastAPI ASGI 实例。

#### 问题 3：`/health` 和 `/ready` 有什么区别？

`/health` 是存活探针，只判断进程是否能工作；`/ready` 是就绪探针，判断服务是否具备接收业务流量所需的强制依赖。依赖暂时故障通常应摘除流量，而不是重启进程。

#### 问题 4：为什么健康探针必须快速且职责单一？

探针被高频调用，慢响应会造成误判。若存活探针绑定数据库等外部依赖，外部故障可能触发大量无效重启，形成级联故障或重启风暴。

### 4.2 配置系统

#### 问题 5：为什么业务代码依赖 Settings，而不是到处调用 `os.getenv()`？

Settings 集中提供类型转换、默认值、枚举和范围校验，形成单一事实来源。业务代码获得的是已验证对象，mypy 和 IDE 也能检查字段引用；`os.getenv()` 只有字符串或 None，容易产生重复解析和不一致规则。

#### 问题 6：为什么 production + debug=true 应启动失败？

这是快速失败。自动改成 false 会掩盖部署错误；debug 可能暴露堆栈和内部信息。启动失败能迫使配置在接收流量前得到修正。

#### 问题 7：为什么缓存 `get_settings()`，测试又为什么清缓存？

配置在单次应用生命周期内通常不变，缓存保证所有模块看到同一个配置对象并避免重复解析。测试会改变环境变量，如果不清缓存就会继续读到前一用例的配置，破坏隔离。

#### 问题 8：StrEnum 与 Literal 如何选择？

StrEnum 适合跨模块复用、有明确业务语义、需要遍历或增加方法的值；Literal 适合局部、简单的有限字面量集合。两者都能辅助静态检查，也都能由 Pydantic 做运行时校验。实际项目无需把微小内存差异作为主要决策依据。

#### 问题 9：`.env` 和 `.env.example` 应提交哪个？

提交不含真实秘密的 `.env.example`，让开发者知道需要哪些变量；不提交本机 `.env`，因为它可能包含密钥、密码和环境专属值，并应加入 `.gitignore`。

### 4.3 响应与异常

#### 问题 10：HTTP 404 已表示不存在，为什么还需要 `RESOURCE_NOT_FOUND`？

HTTP 状态码粒度较粗，客户端可能需要稳定业务分支。业务错误码允许前端、监控和调用方区分相同 HTTP 状态下的不同业务原因，同时不依赖自然语言 message。

#### 问题 11：为什么 AppError 不继承 FastAPI HTTPException？

核心业务不应依赖具体 Web 框架。AppError 可以被 HTTP、任务队列、CLI 或 Agent 工作流共同使用，API 边界再决定如何映射 HTTP 状态和响应。

#### 问题 12：为什么 details 是可选结构化数据，而不是任意字符串？

结构化字段便于客户端稳定解析、测试和脱敏审查。任意字符串容易混入 SQL、路径、堆栈和用户敏感值，也迫使客户端解析不稳定文本。

#### 问题 13：泛型 `ApiResponse[VideoSummary]` 有什么价值？

它保留 data 的字段类型，IDE、mypy、Pydantic 和 OpenAPI 都能理解具体结构。使用 `dict[str, object]` 会丢失必填字段、嵌套类型和重构检查。

#### 问题 14：为什么未知异常不能直接返回 `str(exception)`？

异常文本可能包含数据库结构、文件路径、凭据、第三方响应或用户数据。客户端只接收稳定通用信息，普通日志只记录异常类型和 Request ID；后续由受控 Trace/错误监控保存经过治理的诊断信息。

### 4.4 Request ID 与日志

#### 问题 15：为什么要校验调用方传入的 Request ID？

完全信任外部字符串可能导致超长日志、换行注入和不可检索字符。只透传长度与字符集安全的 ID，其余情况生成新 ID。

#### 问题 16：为什么 Request ID 要同时出现在响应头、错误体和日志？

响应头适合网关和通用客户端传播；错误体方便业务前端展示报障编号；日志使用同一 ID 才能把用户报障与内部链路对应起来。

#### 问题 17：为什么不能默认记录 query 和请求体？

客服输入、token、用户标识和业务参数可能包含 PII 或凭据。访问日志默认只记录方法、path、状态和耗时；确需记录的业务字段应经过白名单、脱敏和审计设计。

#### 问题 18：ContextVar 为什么适合异步请求上下文？

同一线程中可能并发执行多个 asyncio 任务，线程局部变量无法区分它们。ContextVar 会随异步上下文传播，使不同请求的 Request ID 保持隔离，并能传给后续 Agent/Tool 调用。

### 4.5 质量与 Docker

#### 问题 19：pre-commit 能代替 CI 吗？

不能。pre-commit 提供开发者本地快速反馈，也可能被跳过；CI 在干净、统一环境中执行，是合并代码前的最终门禁。两者运行相同核心命令，形成快反馈与强制校验的两层保障。

#### 问题 20：为什么容器使用非 root 用户？

如果应用或依赖被利用，非 root 用户能降低攻击者对容器文件系统和运行环境的控制范围，是最小权限原则的基础措施。

#### 问题 21：`.dockerignore` 有什么作用？

它减少构建上下文和镜像意外输入，避免把 `.env`、Git 历史、虚拟环境、缓存和本地数据发送给 Docker daemon 或复制进镜像。

#### 问题 22：为什么容器 CMD 使用 `exec`？

`sh -c` 用于展开端口环境变量，`exec` 再让 Python/Uvicorn 成为容器主进程，从而正确接收 SIGTERM 等停止信号，支持优雅退出。

## 5. 验收结果

| 门禁 | 结果 |
|---|---|
| Ruff | 通过 |
| mypy strict | 通过 |
| pytest | 23 项通过 |
| pre-commit | Ruff、mypy、pytest 全部通过 |
| Dockerfile | 已完成静态审查；当前机器未安装 Docker，未执行镜像构建 |
| 敏感信息边界 | 校验输入和未知异常不回显；访问日志不记录 query value/body |

测试中的 Starlette `TestClient` 弃用警告来自当前上游依赖组合，不影响第一周功能；未通过全局关闭 warning 的方式掩盖。

## 6. 当前商业化边界

- `/ready` 目前只有配置检查，后续数据库、索引和必要 Provider 接入后必须扩展。
- 当前仅应用访问日志结构化，Uvicorn 自身日志统一将在生产化阶段完善。
- Request ID 是单服务相关 ID，后续 OpenTelemetry 接入后还会增加 trace/span。
- 第一周没有鉴权、PII 全链路脱敏、限流、数据库或真实模型，不能作为真实哔哩哔哩生产服务上线。
