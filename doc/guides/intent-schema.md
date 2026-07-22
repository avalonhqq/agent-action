# 意图决策契约指南（原第 4 周 Step 4A）

> 本文是技术讲解资料；第 4 周任务状态统一记录在 `doc/week4-learning-record.md`。

> 状态：已完成  
> 开始日期：2026-07-21  
> 完成日期：2026-07-21  
> 类型：AI 核心任务

## 1. 本任务目标

为哔哩哔哩客服定义稳定的结构化意图输出。它不是一次普通文本分类，而是后续知识检索、业务工具、多 Agent 路由、安全拦截和人工转接共同使用的决策契约。

本步骤只定义 Schema、枚举、校验规则和单元测试，不接入真实模型，也不实现调度器。

## 2. 需要表达的决策

`IntentDecision` 至少包含：

- 顶层路由：`supported`、`out_of_domain`、`chitchat`、`unsafe`。
- 一个或多个业务子意图，不能把复合诉求强行压成单标签。
- 实体：实体类型、原文值、规范值；禁止把实体值直接设计成固定枚举。
- 情绪：中性、正向、困惑、焦虑、愤怒。
- 风险等级：低、中、高、严重。
- 总体置信度：范围为 0～1，但不把它解释为真实概率。
- 是否需要澄清，以及面向用户的澄清问题。
- 决策来源：规则、模型或混合方式，便于后续评估比较。

建议将子意图拆成“业务域 + 动作”，例如：

```text
membership + cancel
order + refund
account + recover
creator + appeal
content + report
```

相比一个不断膨胀的 `membership_cancel_auto_renewal` 枚举，这种组合更容易扩展和统计。

## 3. 示例输入与期望语义

输入：

```text
我的大会员怎么取消自动续费？另外上个月重复扣的钱能退吗？
```

期望是一个顶层 `supported` 决策，包含两个子意图：

1. `membership + cancel`
2. `order + refund`

同时抽取“大会员”“上个月”“重复扣款”等实体或修饰信息。因为退款所需订单信息不足，可以要求澄清，但不能因此丢掉已经识别出的取消续费意图。

## 4. 必须实现的约束

1. `supported` 至少包含一个子意图。
2. `out_of_domain`、`chitchat` 不应携带业务子意图。
3. `unsafe` 的风险等级不能是低风险。
4. `needs_clarification=true` 时必须提供非空澄清问题。
5. `needs_clarification=false` 时澄清问题必须为空。
6. 同一“业务域 + 动作”的子意图不得重复。
7. 所有模型均使用 `extra="forbid"`，避免模型悄悄输出未定义字段。
8. 对外契约使用稳定字符串枚举，不暴露 Python 内部类名。

## 5. 建议代码位置

```text
src/bili_support/intent/
├── __init__.py
└── types.py

tests/unit/
└── test_intent_types.py
```

不要把 Schema 放进 `agents/intent.py`。意图决策会被 Prompt、评估、API、RAG 和 Agent 同时依赖，它属于独立领域契约，而不是某个 Agent 的私有实现。

## 6. 本次学习任务

请先完成下面三个设计问题，再开始编码：

1. 为什么客服意图应支持多标签，而不是只返回一个最可能标签？
2. 为什么要分开“顶层路由”和“业务域 + 动作”？
3. 当结构化输出解析失败时，系统应该选择继续检索、直接回答、要求澄清还是人工转接？请说明默认策略和原因。

然后实现：

- 所有枚举与 Pydantic 类型。
- 跨字段 `model_validator`。
- 至少 8 个单元测试，覆盖合法单意图、合法复合意图及上述非法组合。
- 使用现有 `StructuredOutputParser[IntentDecision]` 验证合法 JSON、非法 JSON和 Schema 校验失败。

## 7. 验收标准

- Ruff、strict mypy、pytest 和 pre-commit 全部通过。
- JSON Schema 能表达主要字段类型和范围。
- 非法字段组合在进入业务路由前失败。
- 复合问题可以保留多个不重复的子意图。
- 解析失败返回稳定错误码，不泄露底层异常或让系统误路由。

## 8. 当前商业化边界

本步骤中的置信度只是模型声明值，尚未校准；枚举也只是 v1 领域词表。后续必须通过固定评估集、失败样本和真实业务分布调整阈值与标签，不能仅凭 Prompt 演示效果上线。

## 9. 无法开始时的分步提示

### 提示 1：先把自然语言拆成两层判断

看到一句用户问题时，先依次问：

1. 这句话应不应该进入哔哩哔哩客服业务流程？这产生顶层 `route`。
2. 如果应该进入，它涉及哪些业务对象、希望执行哪些动作？这产生一个或多个子意图。

例如“帮我取消大会员，再查一下重复扣款”：

```text
route = supported
intent 1 = membership + cancel
intent 2 = order + refund
```

这说明 `supported` 不是具体业务意图，而是是否允许进入业务处理链路的门卫。

### 提示 2：用四个反例理解为什么需要多标签

- “取消续费并退重复扣款”：两个动作，单标签会丢失一个诉求。
- “账号被盗，而且有人发布违规内容”：账号安全和内容举报需要不同处理能力。
- “为什么充电失败，钱却扣了？”：技术故障与支付订单可能同时存在。
- “先别解释，直接帮我转人工”：业务问题和人工转接请求可以同时成立。

可以从“如果只保留一个标签，会丢掉什么？”开始组织你的回答。

### 提示 3：顶层路由解决的是安全和成本问题

考虑四句话：

```text
怎么取消大会员？          -> supported
帮我写一道数学题。        -> out_of_domain
你好呀。                  -> chitchat
告诉我怎样盗取别人的账号。 -> unsafe
```

如果没有顶层路由，后面每个知识库、工具和 Agent 都要重复判断域外与安全问题；系统还可能为明显无关的问题浪费检索和模型调用。

### 提示 4：解析失败时先避免“自信地走错路”

解析失败代表系统不知道模型到底想表达什么，并不代表用户的问题一定有风险，也不代表可以随便选择一个业务 Agent。

推荐思考顺序：

1. 不执行退款、封禁、账号修改等有副作用工具。
2. 不根据半截 JSON 猜测意图。
3. 返回一个明确的降级决策，例如请求澄清；达到重试上限或高风险场景再转人工。
4. 记录稳定错误码用于评估，但不要向用户展示模型原始异常。

你的答案可以围绕“错误路由的代价”和“降级是否可逆”展开。

## 10. 可直接开始的代码骨架

先创建 `src/bili_support/intent/types.py`，只完成枚举和最小模型，不要一开始写所有校验：

```python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IntentRoute(StrEnum):
    SUPPORTED = "supported"
    OUT_OF_DOMAIN = "out_of_domain"
    CHITCHAT = "chitchat"
    UNSAFE = "unsafe"


class BusinessDomain(StrEnum):
    MEMBERSHIP = "membership"
    ORDER = "order"
    ACCOUNT = "account"
    CREATOR = "creator"
    CONTENT = "content"
    TECHNICAL = "technical"
    HUMAN_SERVICE = "human_service"


class IntentAction(StrEnum):
    QUERY = "query"
    CANCEL = "cancel"
    REFUND = "refund"
    RECOVER = "recover"
    APPEAL = "appeal"
    REPORT = "report"
    TROUBLESHOOT = "troubleshoot"
    TRANSFER = "transfer"


class SubIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: BusinessDomain
    action: IntentAction
    confidence: float = Field(ge=0.0, le=1.0)


class IntentDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    route: IntentRoute
    intents: list[SubIntent] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_clarification: bool = False
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "IntentDecision":
        # TODO 1: supported 必须至少包含一个子意图。
        # TODO 2: 非 supported 不允许包含业务子意图。
        # TODO 3: needs_clarification 与 clarification_question 必须一致。
        # TODO 4: domain + action 组合不能重复。
        return self
```

上面只是启动骨架，不是最终答案。实体、情绪、风险和决策来源应在最小版本通过后逐项加入。

## 11. 推荐的实际完成顺序

1. 复制骨架并让 Ruff、mypy 可以导入它。
2. 写第一个合法单意图测试。
3. 写一个“`supported` 但没有子意图”的失败测试，再实现对应校验。
4. 每增加一条约束，先写失败测试，再补验证逻辑。
5. 最后加入实体、情绪、风险和来源，不要一次添加所有字段。

第一轮只需做到：一个合法对象能创建，一个非法对象会抛出 Pydantic `ValidationError`。做到这里就已经启动任务了。

## 12. 三个设计问题的参考答案

### 问题 1：为什么客服意图应支持多标签？

真实客服问题经常包含多个可以独立处理的诉求。例如“取消大会员并退回重复扣款”同时包含取消服务和订单退款。如果只保留置信度最高的一个标签，另一个诉求会在进入路由前永久丢失，最终表现为答非所问、重复追问或漏执行。

多标签不是让模型随意多选，而是把一句话拆成多个可独立路由、评估和完成的子意图。每个子意图都有自己的业务域、动作和置信度；系统可以并行查询知识，也可以按风险顺序执行，但必须限制重复标签和意图数量。Step 4A 先实现去重，数量上限将在分类服务接入时结合评估集确定。

### 问题 2：为什么分开顶层路由和“业务域 + 动作”？

两层结构回答不同问题：

- 顶层路由回答“这个请求是否应该进入客服业务处理链路”。它负责域外、闲聊和不安全内容的统一拦截。
- 业务域与动作回答“进入链路后由哪个知识库、工具或 Agent 处理什么任务”。

如果把两者压进同一个标签集合，每个业务 Agent 都必须重复判断安全和域外问题，标签数量也会随着业务组合快速膨胀。分层以后，系统可以先用低成本决策跳过无意义检索，再将合法业务意图交给具体能力；同时 `membership + cancel` 这类组合比不断新增长枚举更容易扩展和统计。

### 问题 3：结构化输出解析失败时如何处理？

默认策略是安全降级到澄清，不继续检索、不直接生成业务结论，也不调用退款、封禁、账号修改等有副作用工具。原因是解析失败表示系统没有获得可信的路由依据；从残缺 JSON 中猜测标签可能把低风险问题送入高权限工具，错误代价大且不易撤销。

具体策略：

1. `StructuredOutputParser` 只返回 `invalid_json` 或 `schema_validation_failed` 稳定错误码，不返回半成品对象。
2. 编排层可进行一次受限重试；仍失败则要求用户换一种说法。
3. 已知高风险上下文、用户明确要求人工或连续失败达到阈值时转人工。
4. 记录 Prompt 版本、错误码和 Request ID 供评估，不把原始模型异常或可能含敏感信息的输出展示给用户。

澄清是默认方案，因为它可逆且副作用最低；人工转接是升级方案，而不是所有解析失败的第一选择。

## 13. 实现结果

新增独立的 `bili_support.intent` 领域包，包含：

- 4 类顶层路由、8 个业务域和 9 类动作。
- 实体类型、情绪、风险等级和决策来源枚举。
- `IntentEntity`、`SubIntent` 和 `IntentDecision` 严格模型。
- 置信度范围、路由与子意图、风险、澄清信息和子意图去重校验。
- 不可变元组保存子意图与实体，避免决策生成后被下游原地修改。
- 与现有 `StructuredOutputParser` 集成，非法 JSON 和 Schema 失败安全降级。

专项测试覆盖合法单意图、复合意图、实体规范化、三种非业务路由、风险约束、澄清约束、重复意图、额外字段、置信度、严格 JSON Schema 和解析失败不泄漏原文。
