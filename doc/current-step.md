# 已完成：第 2 周 · Step 2A

> 完成日期：2026-07-19。实现记录、设计答案和验收覆盖见 [Step 2A 完成记录](week2-step2a-completion.md)。

## 主题

LLM 领域契约与确定性 Mock Provider。

## 第 2 周路线

| 检查点 | 内容 | 状态 |
|---|---|---|
| 2A | 消息、请求、响应、用量契约与 Mock Provider | 已完成 |
| 2B | Prompt 版本管理与 Pydantic 结构化输出 | 未开始 |
| 2C | OpenAI-compatible Adapter、超时、重试与取消 | 未开始 |
| 2D | 普通聊天接口与 SSE 流式输出 | 未开始 |
| 2E | 有界上下文、历史摘要与 standalone query 改写 | 未开始 |
| 2F | Token、耗时、错误记录与第二周复盘 | 未开始 |

本阶段不调用真实模型，不需要 API Key。目标是先定义稳定、可测试、可替换的模型边界。

## 学习目标

1. 理解 system/user/assistant/tool 消息角色的职责。
2. 区分模型请求参数、模型响应和 Token 用量。
3. 理解 Python Protocol 如何实现依赖倒置。
4. 理解为什么测试与本地开发需要确定性 Mock。
5. 为后续普通响应和流式响应建立同一 Provider 契约。

## 设计流程

```text
业务/Agent
→ LLMRequest
→ LLMProvider Protocol
→ MockLLMProvider 或未来 OpenAICompatibleProvider
→ LLMResponse / StreamChunk
```

业务层只能依赖 `LLMProvider`，不能直接依赖某个模型 SDK。

## 实践任务

### 任务 1：定义消息与用量模型（已完成）

> 2026-07-18：已实现 MessageRole、FinishReason、ChatMessage 和 TokenUsage，并通过空白内容、非法角色、负 Token 及总数不一致等测试。

新建 `src/bili_support/llm/types.py`，至少实现：

- `MessageRole`：system、user、assistant、tool。
- `ChatMessage`：role、content，可选 name/tool_call_id 只在确有需要时加入。
- `TokenUsage`：prompt_tokens、completion_tokens、total_tokens。
- `FinishReason`：stop、length、tool_call、content_filter、error。

要求：

- 使用 `StrEnum` 和 Pydantic v2。
- content 不允许空字符串。
- Token 数不能为负数。
- 校验 `total_tokens == prompt_tokens + completion_tokens`，不允许静默修正。
- 不定义或保存 chain_of_thought、reasoning_content 等私有思维链字段。

### 任务 2：定义请求、响应和流式分片（已完成）

> 2026-07-18：已实现 LLMRequest、LLMResponse 和 StreamChunk；补齐非空消息/模型、参数范围、正数限制和普通/最终流式分片测试。

至少实现：

- `LLMRequest`
  - `messages: list[ChatMessage]`，至少一条消息。
  - `model: str`，非空。
  - `temperature: float`，限制在 0～2。
  - `max_tokens: int`，大于 0。
  - `timeout_seconds: float`，大于 0。
- `LLMResponse`
  - content、model、finish_reason、usage。
- `StreamChunk`
  - delta、finish_reason、usage。

流式分片中，普通 chunk 可以没有 usage；最终 chunk 可以携带完整 usage。

### 任务 3：定义 Provider 协议（已完成）

> 2026-07-19：已实现 runtime-checkable LLMProvider，使用项目内部请求/响应类型，并通过结构类型、完整响应和直接 async-for 流式调用测试。

完善 `src/bili_support/llm/provider.py`：

```python
class LLMProvider(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    def stream(self, request: LLMRequest) -> AsyncIterator[StreamChunk]: ...
```

要求：

- 接口只使用项目内部类型，不暴露第三方 SDK 类型。
- `complete` 和 `stream` 共享同一个 `LLMRequest`。
- Protocol 只描述能力，不包含网络实现。
- 根据 Python 异步生成器语义正确标注 `stream`，不要为了通过 mypy 使用 `Any`。

### 任务 4：实现确定性 Mock（已完成）

> 2026-07-19：已实现无网络、无随机、无真实等待的 MockLLMProvider；完整响应与流式分片可重复，最终 chunk 携带停止原因和确定性 Mock Usage，非法配置快速失败。

新建 `src/bili_support/llm/mock.py`，实现 `MockLLMProvider`：

- 构造时接收固定回复文本和模型名。
- `complete()` 每次对相同请求返回相同结果。
- `stream()` 按确定规则切分固定回复，所有 delta 拼接后等于完整回复。
- 最终 chunk 携带 finish_reason 和 usage。
- 不使用随机数、不等待真实时间、不访问网络。
- 空回复、非法 chunk size 等配置应尽早失败。

Token 暂时使用明确标注为 Mock 的确定性计算方式，例如按非空字符数统计；不要声称它等于真实模型 tokenizer。

### 任务 5：公共导出（已完成）

> 2026-07-19：已通过 `bili_support.llm` 显式导出协议、类型和 Mock Provider，并增加公共接口与协议兼容测试；内部辅助实现未进入 `__all__`。

更新 `src/bili_support/llm/__init__.py`，显式导出确实属于公共接口的类型和 Provider，不使用通配符导入。

### 任务 6：测试（已完成）

> 2026-07-19：任务书要求的 10 类行为均已覆盖，并补充完整/流式 Usage 一致性、公共导出和 PEP 561 类型包标记检查。

新建：

```text
tests/unit/test_llm_types.py
tests/unit/test_mock_llm.py
```

至少覆盖：

1. 合法消息和请求能构造。
2. 空消息 content 被拒绝。
3. 空 messages 被拒绝。
4. temperature 越界被拒绝。
5. TokenUsage 总数不一致被拒绝。
6. `MockLLMProvider` 满足 `LLMProvider` Protocol。
7. complete 返回固定内容、模型、finish reason 和用量。
8. stream 所有 delta 可以还原完整回复。
9. 最终 chunk 携带 stop 和 usage。
10. Mock 不访问网络，重复调用结果一致。

## 本阶段不做什么

- 不安装 OpenAI SDK，不调用真实 API。
- 不实现 Prompt 模板，留到 2B。
- 不实现重试和超时，留到 2C。
- 不实现 FastAPI chat/SSE，留到 2D。
- 不实现历史摘要和 query rewrite，留到 2E。
- 不估算真实模型费用。

## 思考题

1. 为什么业务层应该依赖 `LLMProvider`，而不是直接调用 OpenAI-compatible SDK？
2. 为什么 Mock 必须确定性，而不能随机生成更“真实”的回复？
3. 为什么 TokenUsage 总数不一致应该校验失败，而不是自动重算？
4. 为什么普通响应和流式响应应该共享同一种 LLMRequest？
5. 为什么不能保存或返回模型的私有思维链字段？

## 运行检查

```powershell
cd C:\workspace\agent-action
.venv\Scripts\Activate.ps1

ruff check .
mypy src/bili_support
pytest
```

## 验收标准

- 新增的 10 类行为测试通过。
- 第一周 23 项测试继续通过。
- Ruff、mypy、pytest 全部通过。
- Mock 不访问网络且结果确定。
- 业务契约不包含第三方 SDK 类型和 `Any`。
- 能回答五道思考题。

完成后告诉我：

> Step 2A 已完成，请评审

建议提交信息：

```text
feat: define LLM contracts and deterministic mock provider
```
