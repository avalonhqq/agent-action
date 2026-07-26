"""5B 结构化分块学习入口。

请按以下顺序实现，不要在本模块访问数据库：

1. 定义 ChunkKind、DocumentKnowledgeType 和 ChunkDraft；
2. 定义 ChunkStrategy Protocol；
3. 实现 GenericChunkStrategy；
4. 先生成 Parent，再生成引用该 Parent local_id 的 Child；
5. 在 5B-2 继续加入 Policy、Manual、FAQ 和 Table 策略。

算法输出保持为纯数据；ORM KnowledgeChunk 的创建与事务处理留给 5B-3。
详细样例见 doc/week5-learning-record.md 的“当前动手任务：5B-1”。
"""
