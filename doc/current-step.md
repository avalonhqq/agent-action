# 当前学习入口

前八周已经完成，第9周9A、9B与9C已完成：最小Graph、MongoDB Checkpoint、真实Intent、Hybrid RAG、
Grounded Answer、本地NLI、人工中断、审核队列与断点恢复已经进入同一条状态化工作流。当前下一步为9D流程
回放、失败恢复策略与第9周复盘；实施前先讲思路并等待确认。

第7周补充完成统一企业客服工作台：`/support/`现已覆盖问答、知识上传、领域词条、审核发布、
版本制品和能力边界展示。

领域词典运行时闭环已补齐：只有active发布版本会同步Jieba并参与补检索实体覆盖，发布后BM25缓存会按
词典版本重建。48条初始化词已由用户审核并发布为active v1，运行时制品包含规范词和别名共144行。

第7周补充7E已完成：生产BM25运行时迁移到Elasticsearch 9.4.2，当前MySQL活动知识的175个Child已写入
版本索引；知识索引激活、词典发布和应用启动均会自动同步，读取Alias只在完整写入成功后原子切换。

检索资格已改为状态驱动：用户查询不传版本号；MySQL使用`document.active + version.is_current +
index.active`选择当前知识，ES使用对应布尔字段和owner过滤，版本ID只保留作内部复核、引用和审计。

任务目标、实现提示、思考题、问题记录和实现结论统一维护在：

- [第 5 周学习与任务记录](week5-learning-record.md)
- [5B-3 持久化接入与 Small-to-Big](week5-learning-record.md#9-5b-3-持久化接入与-small-to-big已完成)
- [5B 完整代码阅读顺序](week5-learning-record.md#97-5b-完整代码阅读顺序)
- [5C 固定数据集、评估与调试接口](week5-learning-record.md#10-5c-固定数据集评估与调试接口已完成)
- [第 6 周学习与任务记录](week6-learning-record.md)
- [6A Embedding 契约与 Milvus 边界](week6-learning-record.md#3-6aembedding-契约与-milvus-边界已完成)
- [6B 批量索引与版本重建](week6-learning-record.md#4-6b批量索引与版本重建已完成)
- [6C 向量检索与 Small-to-Big](week6-learning-record.md#5-6c检索过滤与-small-to-big已完成)
- [6D Golden Dataset 与 Recall@K](week6-learning-record.md#6-6dgolden-dataset-与-recallk已完成)
- [第7周学习与任务记录](week7-learning-record.md)
- [第8周学习与任务记录](week8-learning-record.md)
- [第9周学习与任务记录](week9-learning-record.md)
- [7A 中文Tokenizer与BM25基线](week7-learning-record.md#2-7a中文tokenizer与bm25单路基线已完成)
- [7A-2 Jieba搜索分词优化](week7-learning-record.md#210-7a-2jieba搜索分词优化已完成)
- [7A-3 生产级领域词典管理](week7-learning-record.md#211-7a-3生产级领域词典管理已完成)
- [Chat接入真实RAG](week7-learning-record.md#3-chat接入真实rag已完成)
- [7B Vector与BM25 RRF融合](week7-learning-record.md#4-7bvector--bm25-rrf融合已完成)
- [7C Parent批量Rerank与失败降级](week7-learning-record.md#5-7cparent批量rerank与失败降级已完成)
- [7D RetrievalPolicy、阈值与多实体覆盖](week7-learning-record.md#6-7dretrievalpolicy阈值与多实体覆盖已完成)
- [7E Elasticsearch BM25与自动同步](week7-learning-record.md#8-7eelasticsearch-bm25与自动同步已完成)

本文只提供入口，不重复保存每周任务内容。
