# 第9周：LangGraph状态化工作流学习记录

## 1. 本周目标

把当前隐含在Service中的顺序调用逐步迁移为显式、有限步、可回放和可恢复的LangGraph工作流。本周先学习
State、Node、Conditional Edge与编译执行，再接入真实Intent、RAG、Grounded Answer和本地NLI，最后实现
生产Checkpoint、中断恢复及流程调试。

本周不提前实现第10周的Supervisor、多Agent和Tool Calling，也不会用内存Saver或占位回答冒充生产能力。

## 2. 9A：最小可运行Graph

### 2.1 实现目标

```text
START
→ initialize
→ validate_input
→ valid   → complete → END
→ invalid → fail     → END
```

9A只验证工作流机制，不调用LLM、检索、数据库或业务工具。合法问题完成输入阶段并把`next_action`设置为
`intent`，表示9B应接入真实意图节点；非法输入返回稳定错误码并失败关闭。

### 2.2 State设计

- `CustomerServiceGraphState`使用`TypedDict`描述节点共享状态；
- `request_id/thread_id/user_id/question`是必填执行身份；
- `visited_nodes`通过`operator.add` Reducer追加节点名；
- `step_count`通过`operator.add` Reducer累计每个节点的一次增量；
- 节点返回`GraphStateUpdate`部分状态，不原地修改并返回整个State；
- 条件边只读取`GraphInputStatus`，不调用LLM自由选择下一节点。

### 2.3 双层循环保护

- `MAX_GRAPH_STEPS=12`用于业务状态审计和提前失败关闭，并容纳上下文解析后的完整RAG链路；
- LangGraph调用配置中的`recursion_limit=12`是框架级最后保险；
- 两者职责不同，不能只依赖异常作为正常业务分支。

### 2.4 当前边界

9A尚未接入Checkpoint，因此不声称支持进程重启恢复。官方`InMemorySaver`只适合实验，本项目生产模式不会
使用它冒充持久化；9C将选择本机可运行的正式数据库Checkpointer。

## 3. 9A代码阅读顺序

```text
graph/state.py       枚举、共享State、Reducer和统一输入构造器
→ graph/routing.py   结构化条件边
→ graph/workflow.py  节点、边、compile和有限步调用入口
→ tests/unit/test_graph_workflow.py  正常、空白、超长和超步数路径
```

## 4. 9A思考题与答案

### 问题1：为什么Node返回部分State，而不是修改并返回整个State？

答案：部分更新让字段所有权清晰，Reducer可以稳定合并并行或连续写入，也避免节点把其他节点已经产生的数据
意外覆盖。它还使每个Checkpoint能够记录该节点真正写入了什么。

### 问题2：Conditional Edge为什么不再次调用LLM？

答案：输入节点已经产生类型化`GraphInputStatus`，条件边只是执行确定性Policy。再次调用模型会增加成本和延迟，
并让相同状态可能走向不同分支，降低可回放性。

### 问题3：`StateGraph`和`CompiledStateGraph`有什么区别？

答案：`StateGraph`是声明节点和边的Builder，不能直接执行；`compile()`会检查图结构并生成支持`invoke`、
`ainvoke`和`stream`的`CompiledStateGraph`。Checkpoint也在编译阶段接入。

### 问题4：为什么同时保留`step_count`和`recursion_limit`？

答案：`step_count`是可展示、可持久化的业务指标，可以在达到策略上限前主动降级；`recursion_limit`由LangGraph
在图无法停止时抛出异常，是防无限循环的最后保险。

## 5. Checkpoint存储决策：MongoDB而不是MySQL

### 5.1 结论

本项目采用`langgraph-checkpoint-mongodb 0.4.x`保存LangGraph Checkpoint，MySQL继续保存用户、会话、
消息、知识、审核等业务事实。选择MongoDB的主要原因不是“文档型数据库一定更快”，而是该实现属于LangGraph
官方集成目录、由MongoDB与LangChain相关团队维护，并原生提供Checkpoint、pending writes、复合唯一索引和
TTL生命周期能力。社区`langgraph-checkpoint-mysql`可以复用现有MySQL，且有真正的`AIOMySQLSaver`，但目前
是单维护者兼容实现，不作为本项目关键恢复链路的第一选择。

需要如实理解一个边界：当前MongoDB Python Saver虽然提供`aget_tuple/aput/alist/aput_writes`异步接口，
底层仍将同步PyMongo操作放入线程池；它不是原生AsyncMongoClient实现。以本项目当前并发量可接受，后续压测
若发现线程池饱和，应评估官方实现升级、隔离执行器或改用PostgreSQL等原生异步Saver。

### 5.2 数据职责

```text
MySQL（事实源）                 MongoDB（执行恢复状态）
用户/会话/消息                  checkpoint快照
文档/Chunk/索引版本             pending writes
审核/反馈/审计                  thread_id执行历史
长期保存、关系约束              TTL自动清理（本地默认7天）
```

Checkpoint不是聊天记录的替代品。删除MongoDB不应删除业务事实，但会失去未完成Graph的恢复与时间旅行能力；
删除MySQL则无法通过MongoDB恢复完整客服业务数据。

### 5.3 运行语义与安全边界

- 必须传`configurable.thread_id`，它是Checkpoint的隔离分区键；
- 使用Replica Set，而非普通Standalone `mongod`；本地Compose为单节点`rs0`；
- 本地端口只绑定`127.0.0.1`且无认证，仅限开发；
- 生产必须使用多节点Replica Set、TLS、认证账号、Secret Manager、备份与恢复演练；
- Checkpoint载荷使用AES-EAX加密，反序列化只允许Graph声明的状态枚举；生产缺少密钥会拒绝启动；
- `graph_checkpoint_required=true`时连接失败会阻止应用启动或使`/ready`失败，不回退内存Saver；
- Checkpoint与pending writes默认保留604800秒（7天），避免运行状态无限增长。

### 5.4 代码阅读顺序

```text
core/config.py
  → graph/checkpoints.py       MongoClient、Replica Set检查、Saver和生命周期
  → graph/workflow.py          compile(checkpointer=...)与thread_id配置
  → main.py                    启动、就绪探测、关闭和失败关闭策略
  → compose.yaml               MongoDB rs0和一次性初始化容器
```

## 6. 9B：真实客服能力进入LangGraph

### 6.1 实现目标

9A只验证Graph基本结构；9B把项目已有的真实意图、检索、Grounded Answer和本地NLI接入节点。业务链路现在是：

```text
initialize → validate_input → classify_intent
  ├─ knowledge_rag → retrieve_knowledge
  │    ├─ 有证据 → generate_grounded → verify_claims → finalize
  │    └─ 无证据/依赖降级 → deterministic_response → finalize
  ├─ general_chat → general_chat → finalize
  └─ 安全/澄清/人工Mock/超范围 → deterministic_response → finalize
```

Intent模型只产生类型化语义结果；下一节点由确定性条件边选择。高风险、分类失败、证据不足、Grounded模型故障
均失败关闭，不允许退回无证据自由回答。

### 6.2 State和Context为什么分开

`CustomerServiceGraphState`只保存可JSON序列化的数据：问题、用户身份快照、有界历史、路由计划、证据JSON、
Grounded对象、NLI结论和最终响应。它会经过AES加密后写入MongoDB。

`CustomerServiceGraphContext`保存运行期服务：`CustomerServiceRouter`、`PolicyAwareKnowledgeRetriever`和
`ChatService`。数据库连接、Milvus客户端、ES客户端、模型Provider不能进入Checkpoint；恢复时由应用重新注入
健康的新实例。

### 6.3 节点职责

| 节点 | 输入 | 真实能力 | 输出 |
|---|---|---|---|
| `classify_intent` | 标准化问题 | Hybrid规则+LLM意图及路由策略 | RoutePlan、IntentDecision |
| `retrieve_knowledge` | 意图、用户、历史 | Milvus+ES+MySQL复核、Policy、覆盖判断 | Parent证据、引用Trace或安全回复 |
| `generate_grounded` | 问题、证据JSON | 结构化LLM、Schema和证据ID白名单 | 未发布Grounded对象 |
| `verify_claims` | Grounded对象、证据 | 本地mDeBERTa NLI与8E发布策略 | 已验证回答、实际引用、校验Trace |
| `general_chat` | 闲聊与历史 | 普通ChatService | 模型回答 |
| `deterministic_response` | 策略固定文本 | 不调用回答模型 | 安全、澄清、拒答或人工Mock提示 |
| `finalize` | 完整响应字段 | 响应契约检查 | completed状态 |

### 6.4 Grounded生成与NLI为什么拆成两个节点

原`ChatService.complete_grounded()`一次完成生成和NLI，不利于观察中间状态。9B增加`verify_claims=False`以及
`verify_grounded_completion()`：生成节点只完成JSON结构和引用白名单，Checkpoint记录未发布对象；验证节点再
调用本地NLI。只有验证节点完成后，回答才进入最终State和页面。

这样未来可以在两节点之间加入人工中断、重试或更换校验模型，而不重复执行检索。

### 6.5 会话、执行与Checkpoint身份

MySQL中的`conversation.thread_id`表示长期业务会话；MongoDB中的Checkpoint线程使用：

```text
{conversation_thread_id}:{request_id}
```

一条用户消息对应一个独立Graph执行分区。这样为9C按某条消息的最近节点恢复提供准确定位，同时避免
`visited_nodes`和`step_count` Reducer跨多轮累计。9B已经支持状态读取，尚未开放自动恢复API；历史对话仍从
Redis/MySQL加载，最多20条作为本轮State快照。

### 6.6 ConversationService的新职责

`ConversationService`不再手工编排Intent、RAG和NLI，只负责：

1. 校验会话归属并把用户消息写入MySQL；
2. 构造9B State并调用Graph；
3. 把Graph的强类型结果写入助手消息和ModelCall审计；
4. 更新Redis历史缓存；
5. 保持HTTP与SSE接口兼容。

Grounded知识回答必须整体通过校验后再发布，所以SSE不会逐Token泄露未经验证的模型内容，而是在校验完成后
发送一条安全的`delta`。

### 6.7 示例：大会员到账时间

```text
问题：大会员支付成功后多久生效？
意图：supported → membership/query
路由：knowledge_rag
检索：Hybrid，获得E1～E5
生成：严格Grounded JSON
校验：本地NLI逐Claim验证
发布：正常情况下立即生效[E1]；异常等待和人工核查均保留引用
结束：finalize
```

### 6.8 9B代码阅读顺序

```text
graph/state.py
  → graph/context.py
  → graph/workflow.py
  → graph/answer_policy.py
  → llm/service.py
  → services/conversations.py
  → main.py
  → scripts/verify_week9b_graph.py
```

### 6.9 思考题与答案

**问题1：为什么不把Retriever直接保存在State中？**

答案：State需要序列化和跨进程恢复，Retriever包含连接池与客户端，既无法安全序列化也可能恢复出失效连接；
它属于Context。

**问题2：为什么模型故障不回退普通Chat？**

答案：知识问题的普通Chat没有证据约束，会把依赖故障变成幻觉风险。9B只返回确定性服务不可用提示，并在
Retrieval Trace记录稳定错误码。

**问题3：为什么页面流式回答可能只有一个delta？**

答案：普通闲聊可以逐Token展示，但Grounded JSON在结构、引用和NLI完成前都不可信。当前统一Graph执行采用
验证后发布策略，优先保证不泄露未验证内容；后续可使用LangGraph custom stream只发送节点级进度。

**问题4：MongoDB能否替代MySQL聊天记录？**

答案：不能。Checkpoint用于短期执行恢复，默认7天TTL；MySQL消息和审计是长期业务事实。两者必须分别治理。

## 7. 9C：人工中断、审核与断点恢复

### 7.1 实现目标

9C把原来“提示已转人工”的终点改为真正可暂停、可审核、可恢复的工作流。高风险支持类请求和分类失败请求
到达`human_review`节点后调用LangGraph `interrupt()`，应用立即返回待审核状态；审核员作出决定后，系统使用
`Command(resume=...)`从原MongoDB Checkpoint继续，而不是重新跑意图和检索。

```text
classify_intent
  → human_review
      → interrupt（MongoDB保存断点）
      → 人工批准/拒绝（MySQL原子领取审核任务）
      → Command(resume=decision)
      → deterministic_response
      → finalize
```

当前人工业务下游仍明确标记为Mock：批准只代表“允许工作流继续”，不会真的修改账号、退款或创建外部工单。
中断、持久化、权限、并发领取和恢复链路均为真实实现。

### 7.2 为什么同时使用MongoDB和MySQL

| 数据 | 存储 | 原因 |
|---|---|---|
| 节点状态、下一节点、Interrupt载荷、Reducer结果 | MongoDB | LangGraph Saver原生恢复执行 |
| 待办状态、申请人、审核人、决定、意见、时间 | MySQL `graph_reviews` | 运营查询、关系约束和长期审计 |
| 用户消息、暂停提示、恢复结果、模型调用 | MySQL | 客服业务事实不能依赖短期Checkpoint |

MongoDB回答“程序从哪里继续”，MySQL回答“谁在什么时候批准了什么”。两者不互相替代。

### 7.3 并发与权限边界

- `pending → processing`使用带状态条件的单条SQL Update原子领取，只有一个审核员能获得处理权；
- 恢复异常时任务退回`pending`，允许安全重试；恢复完成后状态只能进入`approved/rejected`；
- 重复恢复已处理执行返回409，不会重复写助手消息或重复执行下游；
- 会话所有者只能查看自己的执行状态，审核队列和恢复接口仅允许审核员；
- 本地由`BILI_SUPPORT_GRAPH_REVIEW_ADMIN_USER_IDS`提供白名单，生产必须替换成企业SSO/JWT RBAC声明。

### 7.4 接口与页面

```text
GET  /api/v1/conversations/reviews/pending
GET  /api/v1/conversations/{thread_id}/executions/{request_id}
POST /api/v1/conversations/{thread_id}/executions/{request_id}/resume
```

统一工作台新增“流程审核”页：审核员可以刷新待办、填写意见、批准或拒绝，并查看恢复后的最终状态和回答。
SSE新增`execution`事件，前端可以区分`interrupted/completed/failed`，不必从回答文本猜测流程状态。

### 7.5 代码阅读顺序

```text
graph/state.py                         审核字段与interrupted状态
→ graph/context.py                     是否允许真实中断的运行期开关
→ graph/workflow.py                    interrupt()与恢复载荷校验
→ models/entities.py                   graph_reviews长期审核事实
→ repositories/graph_reviews.py        查询、原子领取、释放和完成
→ services/conversations.py            Checkpoint查询、Command恢复和事务审计
→ api/conversations.py                 待办、状态与恢复HTTP接口
→ ui/support.py                        流程审核工作台
```

### 7.6 示例：账号找回高风险请求

```text
用户：我的账号被盗，需要找回
意图：supported + account/recover + high
路由：human_review_mock
Graph：在human_review节点暂停
页面：显示待审核任务
审核员：批准，意见“身份材料已核验”
Graph：从human_review恢复，不重复执行classify_intent
结果：写入批准回复、审核记录和ModelCall审计
```

### 7.7 思考题与答案

**问题1：为什么不在收到高风险请求时直接返回，然后由审核接口重新发起Graph？**

答案：重新发起会重复调用模型和检索，输入数据或模型版本变化后还可能得到不同路径。`interrupt/resume`恢复的是
同一执行快照，语义更准确，也便于审计“恢复前已经完成了哪些节点”。

**问题2：为什么审核决定必须经过Pydantic校验？**

答案：`Command(resume=...)`属于外部输入。限制decision枚举、意见长度和审核员标识，可以防止任意对象污染State，
并确保恢复节点只处理明确的批准或拒绝语义。

**问题3：为什么审核任务需要`processing`中间状态？**

答案：如果两个审核员同时读取`pending`后都调用恢复，可能重复执行后续节点。条件更新先把唯一处理权交给一个审核员，
其他请求得到冲突响应；这是恢复操作幂等性的一部分。

**问题4：Checkpoint不可用时为什么不自动换成内存Saver？**

答案：内存Saver在进程重启后丢失，自动回退会让页面错误地声称请求可恢复。项目在未启用真实Saver时保留原确定性
人工提示；生产配置为required时则失败关闭，不伪装持久化能力。

## 8. 9C联调问题：推理模型结构化JSON被截断

页面曾出现同一个会员问题偶发`invalid_json`并进入人工审核，或检索成功后返回`MODEL_BAD_RESPONSE`。实际原始
响应表明，`deepseek-v4-flash`会消耗隐藏推理预算；原先意图和Grounded结构化任务共用512个输出Token，模型
多次以`finish_reason=length`结束，只返回半个JSON，原格式重试继续沿用相同预算，因此可能再次失败。

修正后的预算按任务拆分：普通回答仍使用`LLM_MAX_TOKENS`，短结构意图使用
`LLM_INTENT_MAX_TOKENS=1024`，包含Claims和引用的Grounded回答使用`LLM_GROUNDED_MAX_TOKENS=2048`。
`length`不再被笼统记录成`invalid_json`，而是明确标记`truncated_response`并进入有限格式重试；供应商返回200但
正文为空时，结构化任务也允许在既有重试预算内重新独立生成。重试不回传失败原文，避免敏感文本扩散。

这项修正只提高结构输出完整率，不放松Grounded Schema、证据ID白名单或本地NLI门禁。

## 9. 9C补充：生产型多轮上下文解析

### 9.1 为什么“只向上找一条”不够

联调中用户先问“大会员能做什么”，再问“多少钱”。只检查最近一条用户消息能修复这个例子，却无法处理用户在
会员、订单、客户端等多个主题之间切换后再追问，也无法在“大会员套餐”和“订单套餐”都可能有价格时识别歧义。
这类方案会把“最近”误当成“所指对象”，在生产客服中容易错路由甚至错执行。

### 9.2 新的语义状态

系统为每个会话维护一个有界`ConversationContextState`：

- `active_topics`：最近确认的最多5个主题，而不是原始对话的无界摘要；
- `primary_domain`：当前主业务域；
- `confirmed_entity_values`：可安全长期保存的产品实体；
- `unresolved_slots`：待澄清槽位；
- `last_standalone_query`与`context_version`：追踪上一次完整问题及并发版本。

主题只从通过严格Schema的`IntentDecision`推进，不从助手自由文本中抽取事实。订单号、账号、交易号等敏感标识
不复制进主题快照；如确有业务需要，应从受权限保护的消息事实中读取，或接入专门的加密槽位存储。

### 9.3 解析算法

```text
当前短问句“多少钱”
  → 识别为价格槽位追问
  → 从全部活动主题筛选 membership/order 兼容主题
      ├─ 唯一候选：规则补全，例如“大会员多少钱”
      ├─ 多个候选：结构化模型只能从候选 topic key 中选择
      └─ 模型失败/仍不唯一：生成确定性澄清问题，禁止猜测
  → 完整问题进入 Intent → Retrieval → Grounded Answer
```

显式输入“换个问题：账号怎么找回”会清空旧主题后再建立账号主题。普通完整问句不需要模型解析，直接进入意图
识别。模型只负责指代消解，不回答业务问题，也不能创建候选之外的主题或事实。

### 9.4 Graph、MySQL、Redis与MongoDB的分工

`resolve_context`已成为`validate_input`和`classify_intent`之间的正式Graph节点。解析结果和本轮快照进入MongoDB
Checkpoint，支持解释某次执行为什么继承了某个主题；最新长期快照以MySQL
`conversation_context_snapshots`为事实源，并与助手消息、模型审计在同一事务内提交；Redis只保存有TTL的热缓存，
缓存失效后回源MySQL。

```text
MySQL：最新会话语义事实快照        Redis：低延迟热缓存
MongoDB：某次Graph执行过程         原始messages：完整对话事实
```

页面和SSE会展示`standalone/resolved/ambiguous`、解析来源与补全问题；受会话所有权保护的
`GET /api/v1/conversations/{thread_id}/context`可用于运营排障。

### 9.5 贯穿示例

```text
第1轮：大会员能做什么
Intent：membership/query + product=大会员
Context：active_topics=[大会员]，version=1

第2轮：多少钱
Resolver：价格槽位只有“大会员”兼容 → 大会员多少钱
Intent：命中 membership.price_query:v1
Context：主题更新，version=2

另一场景：同时存在“大会员套餐”和“订单套餐”后询问“多少钱”
Resolver：两个兼容主题 → 模型在白名单中消歧；不确定则询问具体指哪一个
```

### 9.6 代码阅读顺序

```text
conversation_context.py              状态、规则、模型白名单与安全推进
→ graph/state.py                     可持久化字段
→ graph/context.py                   运行期Resolver注入
→ graph/workflow.py                  resolve_context节点与条件边
→ services/conversations.py          MySQL事务、Redis回源和版本持久化
→ core/cache.py                      上下文热缓存
→ api/conversations.py / ui/support.py  可解释输出
```

### 9.7 思考题与答案

**问题1：为什么不直接把全部历史交给意图模型？**

答案：历史越长成本和歧义越高，而且模型输出无法作为稳定的长期状态。主题栈负责有界、可审计的语义记忆，近期历史
只在多个候选需要消歧时作为辅助证据。

**问题2：为什么规则判断后还需要模型？**

答案：规则擅长识别“价格”“退款”等槽位，却不能在多个兼容主题中理解自然语言指代。结构化模型补足长尾表达，但
被候选key白名单约束；二者都不能确定时由用户澄清。

**问题3：为什么MySQL和Redis都保存上下文？**

答案：MySQL负责持久和事务一致性，Redis负责低延迟读取。Redis丢失不会丢事实，MySQL不可用时也不会把缓存冒充
持久化真值。

## 10. 9D：流程回放、失败恢复策略与本周复盘

### 10.1 实现目标

9D把MongoDB中已有的Checkpoint历史转换为可供客服运营阅读的节点时间线。接口不会返回原始State、用户问题、
历史消息、证据正文或异常原文，只展示节点、前后关系、写入节点、失败节点和中断标记。

```text
input → initialize → validate_input → resolve_context → classify_intent
      → retrieve_knowledge → generate_grounded → verify_claims → finalize
```

### 10.2 为什么只读回放不等于重新执行

LangGraph真正的Replay会从指定`checkpoint_id`重新运行其后的节点。LLM、检索API、业务工具和Interrupt都会再次
触发，结果可能变化，也可能造成重复副作用。因此客服工作台默认提供只读时间线，而不是无条件的“一键重跑”。

恢复策略由确定性代码根据Checkpoint任务状态和MySQL `model_calls.error_code`生成：

| 当前事实 | 建议动作 | 是否自动重试 |
|---|---|---|
| 已完成 | `none` | 否 |
| 等待人工Interrupt | `resume_review` | 否，使用受控Command.resume |
| 临时依赖错误 | `retry_checkpoint` | 否，需运营确认副作用边界 |
| 输入或策略拒绝 | `correct_input` | 否，修正后创建新请求 |
| 未知/永久错误 | `operator_inspect` | 否，先排障 |

可从Checkpoint重试的错误白名单只包含`MODEL_UNAVAILABLE`、`SERVICE_NOT_READY`和`INTERNAL_ERROR`。模型响应格式
错误、权限错误、冲突和业务拒绝不会自动重跑。底层模型Provider已有有限退避重试，Graph层不再叠加自动重试，
避免重试风暴和成本放大。

### 10.3 安全时间线字段

每个`GraphTimelineStep`只包含：

- `checkpoint_id`、`step`、`source`和创建时间；
- `current_node`和`next_nodes`；
- `written_nodes`、`failed_nodes`和`interrupted`；
- 不包含Checkpoint的`values`和Task异常文本。

接口：

```text
GET /api/v1/conversations/{thread_id}/executions/{request_id}/timeline
```

接口执行原有会话所有权校验。流程审核页面的“查看回放”会展示时间线和恢复建议。

### 10.4 代码阅读顺序

```text
schemas/conversations.py       时间线和恢复动作契约
→ graph/replay.py              脱敏映射、失败识别和恢复策略
→ services/conversations.py   所有权、MongoDB history与MySQL错误码合并
→ api/conversations.py         timeline HTTP接口
→ ui/support.py                运营工作台时间线
```

### 10.5 思考题与答案

**问题1：为什么恢复判断不能只看Graph State中的`status`？**

答案：节点抛异常时可能来不及把业务状态写成`failed`，但LangGraph Task已经保存错误和pending writes。9D同时检查
显式状态与Task错误，避免把异常执行误判为完成。

**问题2：为什么不把异常字符串直接展示给页面？**

答案：异常可能包含Provider地址、请求片段、账号或基础设施信息。页面只展示稳定错误码和失败节点，详细堆栈留在
受控日志系统中。

**问题3：为什么临时错误也不直接自动Replay？**

答案：Replay会重新执行后续节点。第10周接入真实工具后，这些节点可能创建工单、退款或修改账号；未确认幂等键和
副作用边界前，自动重跑不安全。

### 10.6 第9周复盘

第9周完成了从线性Service调用到状态化工作流的迁移：9A建立有限步Graph，9B接入真实Intent、RAG与NLI，9C
完成MongoDB持久化、人工Interrupt/Resume和多轮主题上下文，9D补齐安全回放与恢复决策。第10周可以在这些边界上
引入Supervisor、多Agent和工具调用，而无需把路由、记忆、审核和恢复重新塞回一个大函数。
