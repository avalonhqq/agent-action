# 第 2 周 Step 2A 完成记录

> 完成日期：2026-07-19

## 完成内容

- 使用 Pydantic v2 定义 MessageRole、ChatMessage、FinishReason 和 TokenUsage。
- 定义 LLMRequest、LLMResponse 和 StreamChunk，校验消息、模型、temperature、输出限制和超时。
- 使用 Protocol 定义与模型厂商无关的 `LLMProvider`。
- 实现无网络、无随机、无真实等待的 `MockLLMProvider`。
- 完整响应和流式响应使用相同请求契约与 Mock Usage 规则。
- 通过 `bili_support.llm` 提供稳定公共导出。
- 增加 `py.typed`，声明 BiliSupport AI 包提供可供调用方检查的类型信息。

## 设计流程

```text
业务 / Agent
→ LLMRequest
→ LLMProvider
├── MockLLMProvider（当前）
└── OpenAICompatibleProvider（2C）
→ LLMResponse / AsyncIterator[StreamChunk]
```

## 思考题与答案

### 1. 为什么业务层依赖 LLMProvider，而不是直接调用模型 SDK？

Provider 把供应商请求、响应和错误类型隔离在适配器内部。业务、Agent 和 API 只依赖项目内部契约，因此可以在 Mock、OpenAI-compatible、本地模型或其他供应商之间替换，也能在没有 API Key 时测试。直接依赖 SDK 会把模型字段、异常和升级影响扩散到整个系统。

### 2. 为什么 Mock 必须确定性？

自动测试需要相同输入得到相同输出。随机回复或随机分片会制造偶发失败，使回归结果无法解释。Mock 的职责是稳定模拟调用边界，而不是模拟真实模型的创造力。

### 3. 为什么 TokenUsage 不一致要失败，而不是自动重算？

Usage 可能来自真实供应商并影响费用、限额和观测。自动修正会掩盖适配器映射错误或供应商数据异常。快速失败能让错误在进入计费和统计前暴露。当前 Mock 字符计数只用于确定性测试，不宣称等同真实 tokenizer。

### 4. 为什么完整响应和流式响应共享 LLMRequest？

两种模式只是传输方式不同，模型、消息、temperature、最大输出和超时语义应一致。共享请求避免两套参数逐渐分叉，也让调用方只需切换 `complete` 与 `stream`，不必重建业务请求。

### 5. 为什么不能保存或返回私有思维链？

私有推理可能包含不稳定中间判断、敏感上下文、系统提示或无法作为事实依据的内容。系统只保存最终结构化决策、原因码、引用和必要审计摘要，不把 chain-of-thought 当成产品输出或普通日志字段。

## 验收覆盖

1. 合法消息和请求可构造。
2. 空白消息被拒绝。
3. 空消息列表被拒绝。
4. temperature 越界被拒绝。
5. TokenUsage 总数不一致被拒绝。
6. Mock 满足 LLMProvider。
7. complete 返回固定内容、模型、结束原因和用量。
8. stream delta 可还原完整回复且分片稳定。
9. 只有最终 chunk 携带 stop 和 usage。
10. Mock 无网络/随机/等待依赖，重复调用结果一致。
11. complete 与 stream 报告相同 Mock Usage。
12. 公共导出可直接构造协议兼容的 Mock。

## 当前边界

- Mock Usage 是非空白字符计数，不是真实 Token。
- 尚未实现 Prompt 模板与结构化输出。
- 尚未实现真实模型调用、超时、重试和取消。
- 尚未实现 Chat API 与 SSE。
- 不包含或输出模型私有思维链字段。
