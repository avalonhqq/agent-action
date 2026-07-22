# 第 4 周学习与任务记录：意图识别与结构化决策

> 开始日期：2026-07-21  
> 当前阶段：Step 4C-3 规则优先、模型兜底的混合编排器  
> 记录规则：本周目标、任务、问题、答案、验收结果和阶段结论只在本文持续追加。

## 1. 本周目标

把用户自然语言稳定转换为可供 RAG、工具和 Agent 使用的 `IntentDecision`，依次建立：

1. 严格、可校验的意图领域契约；
2. Zero-shot v1 基线；
3. Few-shot v2 边界样例；
4. 高精度规则分类器；
5. 规则优先、模型兜底的混合编排；
6. 固定评估集和可量化指标；
7. 页面接入、来源展示和质量门禁。

本周只产生“决策”，不直接执行退款、封禁、转人工等业务动作。

## 2. 任务进度

| Step | 内容 | 状态 | 验收结果 |
|---|---|---|---|
| 4A | `IntentDecision`、枚举、实体和跨字段约束 | 已完成 | 18 项专项测试；全量 125 tests |
| 4B | Zero-shot v1、分类器、Provider、页面与 CLI | 已完成 | 真实模型链路可用；结构失败有限重试 |
| 4C-1 | Few-shot v2 与六个边界样例 | 已完成 | Ruff、mypy、15 项相关测试、全量 139 tests |
| 4C-2 | 高精度规则分类器 | 已完成 | 问候与人工精确规则；测试不作为推进门禁 |
| 4C-3 | 规则优先、模型兜底的混合编排 | 进行中 | 先设计统一结果契约 |
| 4C-4 | 页面接入与决策来源记录 | 待开始 | |
| 4D | 固定评估集、指标和批量运行 | 待开始 | |
| 4E | 失败分析和 Prompt 调优 | 待开始 | |
| 4F | 客服路由接入、复盘和门禁 | 待开始 | |

## 3. Step 4A 完成记录

完成 `IntentRoute`、`BusinessDomain`、`IntentAction`、实体、情绪、风险、决策来源、多子意图和
`IntentDecision`。关键约束包括：

- `supported` 必须有业务子意图；其他路由不能携带业务子意图；
- `unsafe` 不能是低风险；
- 澄清标记与澄清问题必须一致；
- 同一 domain/action 组合不能重复；
- 冻结对象并拒绝未知字段，防止路由过程中契约漂移。

详细原理与练习见 [意图决策契约指南](guides/intent-schema.md)。

## 4. Step 4B 完成记录

完成 `intent_classification:v1`、SYSTEM/USER 角色隔离、严格 Schema、结构化解析、一次结构修复、
Mock/真实 Provider 装配、CLI 和 `/support/` 页面识别入口。

关键结论：Provider 的 `json_object` 只能保证 JSON 语法，不能代替 Pydantic 业务校验；HTTP 重试
与结构重试必须分开限制；用户输入只能作为 USER 数据，不能拼进 SYSTEM 指令。

详细调用链、问题答案和代码阅读路径见
[Zero-shot 意图分类指南](guides/intent-zero-shot-prompt.md)。

## 5. Step 4C-1 完成记录

保留 Zero-shot v1，新增包含六个边界的 Few-shot v2：

1. 自己账号被盗：`supported/account/recover`；
2. 请求盗取别人账号：`unsafe`；
3. 取消大会员并了解账号找回：两个子意图；
4. 订单退款缺少订单号：需要澄清；
5. 简单问候：`chitchat`；
6. 明确转人工：`supported/human_service/transfer`。

六个示例均通过 `IntentDecision.model_validate_json()`。分类器仍显式默认 v1，在固定评估集完成前
不自动切换页面版本。详细 Prompt 与实现提示见
[Few-shot 与混合分类指南](guides/intent-few-shot-hybrid.md)。

### 4C-1 实施中发现的问题

- SYSTEM 模板由 `str.format_map()` 渲染，示例 JSON 的源码花括号必须写成 `{{` 和 `}}`；
- v2 工厂一度被重复定义，已删除重复项；
- “我想退款”无法确定 membership 或 order，当前契约无法无猜测地给出子意图，因此暂不作为
  Few-shot 金标准，留给评估与契约讨论。

## 6. 当前任务：Step 4C-2 高精度规则分类器

### 6.1 学习目标

理解规则在混合分类系统中的正确定位：只接管少量确定性场景，以降低延迟和费用并提高可审计性；
不使用关键词堆砌代替模型语义理解。

### 6.2 需要创建的代码

```text
src/bili_support/intent/rules.py
tests/unit/test_intent_rules.py
```

建议接口：

```python
class RuleMatch(BaseModel):
    rule_id: str
    decision: IntentDecision


class RuleIntentClassifier:
    def match(self, question: str) -> RuleMatch | None:
        ...
```

命中时返回稳定 `rule_id` 和 `source=rule` 的合法决策；未命中必须返回 `None`。

### 6.3 首版规则范围

完整规范化输入属于以下集合时，返回 `chitchat`：

```text
你好、您好、嗨、hi、hello
```

完整规范化输入属于以下集合时，返回 `human_service/transfer`：

```text
转人工、人工客服、联系人工客服
```

“你好，我要退款”“人工客服能退款吗”不能命中规则，必须留给模型。

### 6.4 第一个实现动作：输入规范化

先只实现一个模块内私有函数：

```python
_TRAILING_PUNCTUATION = "。！？!?"


def _normalize_question(question: str) -> str:
    return question.strip().casefold().rstrip(_TRAILING_PUNCTUATION).strip()
```

此函数只去除首尾空白、统一英文大小写和删除末尾问答标点。不要删除中间标点，不做包含匹配、正则
扩展或相似度匹配。

### 6.5 当前先完成的测试

先写规范化行为对应的公开结果测试，不必直接测试私有函数：

1. `你好！` 命中问候规则；
2. ` HELLO? ` 命中问候规则；
3. `转人工。` 命中人工规则；
4. `你好，我要退款` 返回 `None`；
5. `人工客服能退款吗` 返回 `None`；
6. 空白输入返回 `None`。

### 6.6 完成标准

- `RuleMatch` 和 `RuleIntentClassifier` 已实现；
- 只包含两组完整匹配规则；
- 所有结果通过 `IntentDecision` 构造，不返回裸字典；
- `rule_id` 稳定并带版本，例如 `chitchat.exact_greeting:v1`；
- 没有 Provider、Prompt、数据库或页面依赖；
- Ruff、strict mypy、专项测试和全量 pytest 通过。

### 6.7 思考题

1. 为什么规则应匹配完整规范化输入，而不是关键词包含？
2. 为什么未命中返回 `None`，而不是低置信度决策？
3. 为什么 `rule_id` 需要版本号？
4. 为什么首版不使用规则识别 `unsafe`？
5. 规则和模型的 `confidence=1.0` 能否直接比较？

## 7. 下一步

完成 `rules.py` 和专项测试后进行代码评审。评审通过再进入 4C-3，由混合编排器先调用规则，规则
未命中时调用现有 `IntentClassifier`，并用 Mock 证明规则命中时模型调用次数为 0。

## 8. 4C-2 引导记录

### 检查点 1：规则契约与问候规则

已创建 `intent/rules.py`，并完成 `_normalize_question()` 的初版。当前先完成以下内容：

1. 从 `bili_support.intent.types` 直接导入领域类型，避免未来从包入口反向导出规则类时产生循环导入；
2. 为 `RuleMatch` 增加 `frozen=True`、`extra="forbid"` 和非空 `rule_id` 约束；
3. 定义问候完整匹配集合；
4. 构造一个 `source=rule` 的 `chitchat` 决策；
5. `match()` 在问候命中时返回 `RuleMatch`，其他情况返回 `None`；
6. 先通过三个测试：`你好！`、` HELLO? ` 命中，`你好，我要退款` 不命中。

此检查点暂不加入人工客服规则。完成并评审问候分支后，再用相同结构加入人工客服分支，观察如何
消除重复构造代码。

### 检查点 1 首次评审

评审结果：代码部分通过，专项测试尚未提交。

- 已直接从 `intent.types` 导入领域类型，不存在包入口反向依赖；
- `RuleMatch` 已设置冻结、拒绝额外字段和非空 `rule_id`；
- 问候使用 `frozenset` 完整匹配；
- 命中结果是合法的 `chitchat` 决策且 `source=rule`；
- 未命中返回 `None`；
- Ruff 与单文件 strict mypy 通过；
- `tests/unit/test_intent_rules.py` 不存在，因此边界行为尚未形成回归保护。

当前只需补齐三个测试：`你好！` 和 ` HELLO? ` 命中，`你好，我要退款` 不命中。测试通过后，
检查点 1 才正式完成。

### 检查点 1 完成记录

已补充 `tests/unit/test_intent_rules.py`。问候、大小写与末尾标点规范化、复合问题不误命中的三个
专项测试通过；Ruff、strict mypy 和全量 144 项测试通过。检查点 1 完成。

### 检查点 2：明确转人工与决策构造复用

当前目标是加入第二组完整匹配规则：

```text
转人工、人工客服、联系人工客服
```

需要从 `intent.types` 增加导入 `BusinessDomain`、`IntentAction` 和 `SubIntent`。命中结果应满足：

```text
route = supported
intents = (human_service, transfer)
source = rule
risk = low
needs_clarification = false
```

为避免问候与人工分支各自复制所有低风险公共字段，可以新增一个命名明确的私有辅助函数：

```python
def _build_low_risk_rule_match(
    *,
    rule_id: str,
    route: IntentRoute,
    intents: tuple[SubIntent, ...] = (),
    sentiment: Sentiment = Sentiment.NEUTRAL,
) -> RuleMatch:
    ...
```

辅助函数只负责本阶段的低风险确定性规则，因此名称中保留 `low_risk`。未来如果加入高风险规则，
不能无意识继承这里的 `risk=low` 默认值。

匹配顺序建议保持直白：规范化一次，先检查问候集合，再检查人工集合，最后返回 `None`。不要使用
正则或关键词包含，也不要在本步骤调用模型。

本检查点新增测试：

1. `转人工。`、` 人工客服 `、`联系人工客服！` 均命中；
2. `rule_id` 为 `human_service.exact_transfer:v1`；
3. 路由为 `supported`，唯一子意图为 `human_service/transfer`；
4. `source=rule`；
5. `人工客服能退款吗` 返回 `None`；
6. 空白输入返回 `None`。

完成后运行专项测试并提交评审，通过后进入检查点 3：公共导出、契约负例和 4C-2 收尾。

### 检查点 2 首次评审

人工转接的业务实现方向正确，但本次尚未通过：

- `intent.types` 导入块保留了旧导入，又追加了新导入，产生 5 个重复名称；Ruff 报 6 项错误；
- `_build_low_risk_rule_match()` 尚未使用 `*` 限制关键字参数；虽然类型检查通过，但调用方可能按
  位置传错 `rule_id` 与 `route`，降低可读性；
- 测试文件仍只有检查点 1 的三个测试，没有覆盖人工客服、负例和空白输入；
- 现有 3 项测试和 mypy 通过，只能证明旧问候行为没有回归，不能证明新分支正确。

下一次提交前需要：整理成一个无重复的导入块；为辅助函数加入 `*`；增加人工规则的参数化测试、
子意图断言、包含额外语义时不命中测试和空白输入测试。

### 检查点 2 第二次评审

重复导入已经清理，辅助函数已经使用 `*` 限制关键字参数；Ruff、strict mypy 和现有 3 项问候测试
通过。人工规则实现本身已就绪，但测试文件仍未出现人工转接、额外语义负例和空白输入用例，因此
本检查点仍等待测试补齐。

### Step 4C-2 思考题与答案

#### 1. 为什么规则应匹配完整规范化输入，而不是关键词包含？

关键词出现不等于整句话只有该意图。“你好，我要退款”包含“你好”，但核心诉求是退款；“人工客服
能退款吗”包含“人工客服”，但它可能是在咨询能力，而不是要求立即转接。完整匹配让规则只接管
少量确定性表达，把包含额外语义的句子交给模型，牺牲少量召回率换取更高精度。

#### 2. 为什么未命中返回 `None`，而不是低置信度决策？

`None` 表示规则层主动弃权，混合编排器可以明确继续调用模型。低置信度决策仍然是一个看似有效的
业务结果，下游容易误用，还需要再定义阈值和冲突处理。规则层的职责只有“确定命中”或“未命中”，
不能伪造一个它并不知道的分类。

#### 3. 为什么 `rule_id` 需要版本号？

规则集合、规范化方式和输出可能随时间变化。稳定版本号使日志和评估结果可以重放，能够回答某次
路由由哪版规则产生，也支持比较新旧效果和在误判上升时回滚。只有名称而没有版本，历史结果会因
同名规则内容变化而失去可解释性。

#### 4. 为什么首版不使用规则识别 `unsafe`？

安全语义高度依赖上下文。“账号被盗”可能是受害者求助，也可能是攻击方法请求；简单关键词既会
误伤正常用户，也可能漏掉不含预设词的危险表达。首版规则只处理低风险确定性场景，`unsafe` 继续
由模型和契约判断；后续安全模块应采用专门分类、策略校验和人工升级等多层防护，而不是一条关键词
规则承担全部责任。

#### 5. 规则和模型的 `confidence=1.0` 能否直接比较？

不能。规则的 `1.0` 表示输入完全满足预先定义的匹配条件；模型的 `1.0` 是模型对本次语义判断的
自报确定度，通常不是经过校准的真实概率。两者来源、尺度和错误分布不同。评估时应分别统计规则
精度与覆盖率、模型分类指标；只有经过校准后才能设计可比较的统一阈值。

### 学习归档约定

从本检查点开始，每个学习任务的思考题都会在实现或评审后给出参考答案，并归档到当周唯一学习
记录中。后续答案如因实验数据或业务决策发生变化，将在原答案下追加修订原因和日期，不静默覆盖。

### 测试门禁规则调整（2026-07-23）

从当前检查点起，测试用例不再作为进入下一学习步骤的门禁。学习者无需因缺少单元测试停留在当前
步骤；Codex 根据商业项目风险在后台补充或运行必要验证，并如实记录结果。测试仍是工程质量工具，
但不再等同于课程完成条件。

按此规则，人工转接分支的业务代码、类型边界和静态检查均符合目标，Step 4C-2 视为完成。尚未补齐
的人工规则测试记录为后台质量待办，不阻塞进入下一阶段。

## 9. 当前任务：Step 4C-3 混合编排器

### 9.1 本步骤目标

实现以下固定控制流：

```text
question
  -> RuleIntentClassifier.match
       -> 命中：直接返回规则决策和 rule_id，不调用模型
       -> 未命中：调用 IntentClassifier.classify
                    -> 返回模型决策或结构化错误码
```

混合编排器不修改规则结果、不与模型投票，也不把单一路径的 `source` 改成 `hybrid`。只有未来真正
融合两个结果时才允许使用 `DecisionSource.HYBRID`。

### 9.2 第一个设计任务：统一结果契约

规则分类器返回 `RuleMatch`，模型分类器返回 `StructuredOutputResult[IntentDecision]`。两者不能直接
作为同一个接口的返回类型，否则页面要用 `isinstance` 猜测结果来源。建议在
`src/bili_support/intent/hybrid.py` 定义：

```python
class HybridIntentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: IntentDecision | None = None
    error_code: StructuredOutputError | None = None
    rule_id: str | None = None
```

它需要满足三条跨字段约束：

1. `decision` 与 `error_code` 必须恰好出现一个；
2. `rule_id` 只能在 `decision.source == rule` 时出现；
3. `decision.source == rule` 时必须有 `rule_id`，模型结果不能伪造规则编号。

当前先实现这个结果契约及校验器，不急着写异步编排方法。需要思考：为什么不直接让混合编排器继续
返回 `StructuredOutputResult[IntentDecision]`？完成契约后再进入控制流实现。
