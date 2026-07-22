# 第 2 周完成报告：LLM、Prompt、结构化输出与流式聊天

> 完成日期：2026-07-19  
> 范围：第 2 周 2A～2F。默认使用确定性 Mock，不需要真实 API Key。

## 1. 本周完成了什么

第二周把“模型调用”从一个 SDK 请求，升级成了可替换、可测试、可观测的应用能力：

```text
HTTP / SSE
→ ChatService
→ PromptRegistry + QueryRewriter + BoundedContextBuilder
→ LLMProvider
→ MockLLMProvider / OpenAICompatibleProvider
→ LLMResponse / StreamChunk
→ UsageRecorder
```

| 阶段 | 实现结果 | 主要文件 |
|---|---|---|
| 2A | 内部消息、请求、响应、流分片、用量契约；Provider Protocol；确定性 Mock | `llm/types.py`、`provider.py`、`mock.py` |
| 2B | Prompt 名称与版本注册、严格变量渲染、Pydantic 结构化输出与安全失败原因 | `llm/prompts.py`、`structured.py` |
| 2C | OpenAI-compatible 最小适配器、超时、有限重试、指数退避、取消传播、响应校验 | `llm/openai_compatible.py`、`errors.py`、`factory.py` |
| 2D | 普通聊天 API、SSE delta/completed/error 事件、断开后关闭上游流 | `api/chat.py`、`api/router.py` |
| 2E | 有界历史、确定性摘要、低风险 standalone query 改写 | `llm/context.py` |
| 2F | 应用服务编排、Token/耗时/状态/错误码记录、配置接入与完整测试 | `llm/service.py`、`usage.py`、`core/config.py` |

当前接口：

- `POST /api/v1/chat`：一次性 JSON 回复。
- `POST /api/v1/chat/stream`：SSE 流式回复。
- `GET /health`：进程存活。
- `GET /ready`：配置和模型 Provider 已装配。

## 2. 六个阶段逐步讲解

### 2A：先定义内部契约

`ChatMessage` 区分 `system/user/assistant/tool`；`LLMRequest` 统一普通与流式调用所需参数；`LLMResponse` 和 `StreamChunk` 不包含第三方 SDK 对象。`TokenUsage` 会检查总 Token 是否等于输入与输出之和。

`LLMProvider` 是 Protocol。业务只知道“可完成一次调用、可产生异步流”，并不知道 OpenAI、云厂商或本地模型的类。这就是依赖倒置：更换供应商不需要重写业务服务。

Mock 的 Token 是非空字符数，只用于确定性测试，绝不冒充真实 tokenizer。

### 2B：Prompt 也是版本化代码

`PromptTemplate` 使用 `name + version` 标识。注册中心既能获取明确版本，也能获取某名称的最新版本。模板只允许简单占位符，并验证缺少变量、重复版本和复杂属性访问。

结构化输出分为两层：

1. `StructuredOutputSpec` 把 Pydantic 的 JSON Schema 传给兼容 Provider，请模型按结构生成。
2. `StructuredOutputParser` 在边界再次解析和校验，因为模型输出不能仅凭声明就被信任。

失败只返回 `invalid_json` 或 `schema_validation_failed` 等原因码，不把原始模型文本长期保存在结果中。

### 2C：Provider 适配器与失败语义

`OpenAICompatibleProvider` 使用异步 HTTP 调用 `/chat/completions`，把内部类型映射到兼容协议，并把响应重新校验成内部类型。它没有把 `httpx` 或供应商响应对象泄露到业务层。

重试策略刻意保守：

| 情况 | 行为 | 原因 |
|---|---|---|
| 429、500、502、503、504 | 有上限的指数退避重试 | 通常是暂时性失败 |
| 网络传输错误 | 有上限重试 | 连接可能短暂恢复 |
| 其他 4xx | 不重试 | 请求、权限或配置错误不会因等待自动修复 |
| 响应结构非法 | 返回安全的 502 业务错误 | 防止错误数据进入业务层 |
| 协程取消 | 立即向上传播 | 客户端已离开，不应继续占用模型资源 |

流式响应一旦已经向客户端发出内容，后续网络失败不从头重试，否则用户可能收到重复文本。

### 2D：普通聊天与 SSE

普通接口返回答案、模型、结束原因、用量、独立查询、改写原因和 Prompt 版本。流式接口定义三种稳定事件：

- `delta`：新增文本片段。
- `completed`：结束原因、最终用量和 Request ID。
- `error`：安全的业务错误码、公开消息和 Request ID。

使用 `aclosing` 保证客户端断开或服务停止迭代时，`ChatService` 的异步生成器被关闭，其 `finally` 可以完成用量状态记录。

### 2E：上下文窗口与谨慎改写

上下文不是把所有历史无限传给模型。`BoundedContextBuilder`：

- 只接收可信的 system Prompt；用户传入的 history 只允许 user/assistant。
- 超出窗口时生成确定性摘要，并保留最近消息。
- 任何情况下都保持消息数上限，控制 Token、延迟和费用。

`StandaloneQueryRewriter` 采用“高置信度才改写”的基线。例如：

```text
历史：移动大王卡支持免流吗？
当前：那联通呢
结果：联通大王卡支持免流吗？
原因：entity_substitution
```

不满足规则时保留原问并返回原因码，避免为了看起来聪明而改变用户意图。后续 RAG 阶段可以在这个接口后替换成模型改写器，并通过评估集比较效果。

### 2F：编排与安全可观测性

`ChatService` 把 Prompt、改写、上下文、Provider 和 Usage 串在一起。`UsageRecord` 仅记录：

- Request ID、操作类型、模型和 Prompt 版本。
- 延迟、成功/失败/取消状态。
- Token 用量和稳定错误码。

它不记录用户 Prompt、模型回答、私有思维链或底层异常文本。这既减少隐私泄露，也让指标字段稳定。当前是并发安全的内存 Recorder；第三周会将模型调用与会话、消息关联并持久化。

## 3. 如何运行和体验

```powershell
cd C:\workspace\agent-action
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.venv\Scripts\python.exe -m uvicorn bili_support.main:app --reload --port 8010
```

普通请求：

```powershell
$body = @{ message = "大会员有哪些权益？"; history = @() } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8010/api/v1/chat `
  -ContentType "application/json" -Body $body
```

SSE 更适合使用 curl 观察逐块输出：

```powershell
curl.exe -N -X POST http://127.0.0.1:8010/api/v1/chat/stream `
  -H "Content-Type: application/json" `
  -d '{"message":"大会员有哪些权益？","history":[]}'
```

默认 `.env.example` 使用 `mock`。如需接入兼容服务，只在本地 `.env` 或密钥管理器中配置：

```dotenv
BILI_SUPPORT_LLM_PROVIDER=openai_compatible
BILI_SUPPORT_LLM_BASE_URL=https://api.openai.com/v1
BILI_SUPPORT_LLM_MODEL=<你的模型名>
BILI_SUPPORT_LLM_API_KEY=<只放在本地或密钥管理器>
```

本周实现不要求真实网络调用；适配器测试由 `httpx.MockTransport` 验证请求、响应、重试和 SSE 映射。

## 4. 验收结果

```text
Ruff:  All checks passed
mypy:  Success, 76 source files
pytest: 96 passed
```

已覆盖的关键风险包括：类型范围、Prompt 变量、结构化输出失败、密钥遮蔽、可重试/不可重试错误、响应畸形、网络取消、SSE、断流关闭、历史角色注入、上下文上限、指代改写、用量并发记录和安全错误响应。

唯一警告来自当前 FastAPI/Starlette TestClient 对 `httpx` 的上游迁移提示，不影响运行；保留警告以便以后升级处理，没有全局屏蔽。

## 5. 思考题与答案

### 1. 为什么业务层不直接调用模型 SDK？

供应商 SDK 是基础设施细节。依赖内部 `LLMProvider` 后，业务测试可用 Mock，供应商变化只影响适配器，错误、超时和审计语义也能保持统一。

### 2. system、user、assistant、tool 有什么区别？

system 描述应用约束；user 是用户输入；assistant 是模型历史输出；tool 是受控工具结果。角色是信任边界，因此客户端 history 不能伪造 system 或 tool。

### 3. Temperature 越高越好吗？

不是。它控制采样随机性。客服重视一致性和事实性，默认 `0.0` 更容易复现和测试；创意生成才可能适合更高值，但仍需评估。

### 4. 为什么 Prompt 要有版本？

Prompt 会改变行为。版本号使一次回答可回溯、灰度对比和回滚，也能把离线评估结果绑定到明确 Prompt。

### 5. 有 JSON Schema 为什么还要 Pydantic 校验？

Schema 是生成约束，不是信任证明。兼容实现、模型行为或网络数据都可能偏离要求，应用边界仍必须校验。

### 6. 为什么 400 不应像 503 一样重试？

400 通常意味着请求本身错误；重复同一请求只会增加延迟与费用。503 更可能是临时不可用，有限重试才有意义。

### 7. 为什么重试必须有上限和退避？

无限重试会耗尽连接和预算，并加剧供应商故障。指数退避给依赖恢复时间，上限保证请求最终结束。

### 8. 为什么流已经输出后不能从头重试？

客户端无法自动判断第二次相同前缀是重放还是新内容，会出现重复答案。此时应明确终止或报错。

### 9. 客户端断开为什么要取消上游？

继续生成的结果已无人消费，却仍消耗连接、Token 和费用。取消传播是资源治理的一部分。

### 10. 为什么历史不能无限增长？

模型有上下文限制，输入越长通常越慢、越贵，也会引入更多无关信息。有界窗口与摘要在信息保留和成本之间做显式取舍。

### 11. Query Rewrite 为什么要宁可少改？

错误改写会改变检索目标，是隐蔽且严重的错误。规则不确定时保留原问，并让后续澄清或检索策略处理更安全。

### 12. 为什么不记录模型私有思维链？

客服需要的是可审计的输入证据、结构化决策和原因码，不需要模型内部推理文本。保存它增加隐私、安全和稳定性风险，也不能作为可靠业务证据。

### 13. 为什么 Usage 记录 Prompt 版本而不是 Prompt 全文？

版本足以关联代码与评估；全文可能含用户隐私、内部策略或注入内容。最小化记录能降低泄露面。

### 14. `/health` 与 `/ready` 在本周有什么变化？

`/health` 仍只检查进程存活；`/ready` 增加 Provider 已完成装配的状态。它不在每次探测时调用付费模型，以免探针变慢、产生费用或造成误判。

## 6. 已知边界与下一周衔接

- 当前聊天无数据库会话，history 由客户端传入；第三周实现用户、会话和消息持久化。
- 内存 Usage 重启后丢失；第三周迁移到模型调用表。
- 当前摘要与改写是确定性学习基线；第五周结合 RAG 评估后再决定是否引入模型实现。
- 当前答案来自 Mock 或通用模型，尚无企业知识证据；第四至第六周完成知识入库和 RAG。
- Provider 就绪只代表配置与对象装配，不代表外部供应商实时健康；生产阶段将定义低成本、带缓存的依赖健康策略。

下一步进入第 3 周：数据库模型、迁移、Repository/Service、会话 API、消息关联和聊天页面。

## 7. 官方参考

- [OpenAI Chat API reference](https://developers.openai.com/api/reference/resources/chat)
- [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)

## 8. Step 2A 补充问答与验收记录

以下内容原记录在独立的 Step 2A 文档中，现统一并入第 2 周周记录。

### 为什么 Mock 必须确定性？

自动测试需要相同输入得到相同输出。随机回复或随机分片会制造偶发失败，使回归结果无法解释。
Mock 的职责是稳定模拟调用边界，而不是模拟真实模型的创造力。

### 为什么 TokenUsage 不一致要失败，而不是自动重算？

Usage 可能来自真实供应商并影响费用、限额和观测。自动修正会掩盖适配器映射错误或供应商数据
异常。快速失败能让错误在进入计费和统计前暴露。当前 Mock 字符计数只用于确定性测试，不宣称
等同真实 tokenizer。

### 为什么完整响应和流式响应共享 LLMRequest？

两种模式只是传输方式不同，模型、消息、temperature、最大输出和超时语义应一致。共享请求避免
两套参数逐渐分叉，也让调用方只需切换 `complete` 与 `stream`，不必重建业务请求。

### Step 2A 专项验收范围

合法消息、请求和 Provider 协议可以构造；空白消息、空消息列表、越界 temperature 和不一致
TokenUsage 会被拒绝；Mock 的完整响应和流式响应确定且用量一致；最终流分片才携带 stop 与 usage；
公共导出可以直接构造协议兼容的 Mock；系统不保存或输出模型私有思维链。
