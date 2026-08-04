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

- `MAX_GRAPH_STEPS=8`用于业务状态审计和提前失败关闭；
- LangGraph调用配置中的`recursion_limit=8`是框架级最后保险；
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
