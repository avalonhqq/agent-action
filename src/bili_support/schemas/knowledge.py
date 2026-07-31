"""知识入库 API 输出契约；避免把 ORM 对象直接暴露给客户端。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.chunking import ChunkDraft, DocumentKnowledgeType
from bili_support.knowledge.retrieval import RetrievalMode, RetrievalSource
from bili_support.knowledge.types import LoadedSourceBlock
from bili_support.llm.context import QueryRewriteResult
from bili_support.llm.types import ChatMessage


class KnowledgeDocumentView(BaseModel):
    """逻辑知识文档视图；同一文档可以包含多个不可变文件版本。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str  # 逻辑文档UUID
    title: str  # 管理端展示标题，也是自动识别逻辑文档身份的一部分
    business_domain: str  # membership/order等业务域
    knowledge_type: str  # policy/manual/faq/generic/mixed
    access_scope: list[str]  # 未来检索时再次过滤的权限标签
    status: str  # active/deleted，删除采用软删除以保留审计
    created_at: datetime  # 首次创建时间
    updated_at: datetime  # 新版本或状态变化时间


class KnowledgeVersionView(BaseModel):
    """一次真实上传形成的不可变文件版本视图。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str  # 版本UUID，也是SourceBlock/Chunk所属版本
    document_id: str  # 所属逻辑文档
    version_number: int  # 面向用户的递增版本号，从1开始
    content_sha256: str  # 同一逻辑文档内做字节级幂等
    original_filename: str  # 审计和下载展示使用，不作为存储路径
    media_type: str  # 上传时识别的MIME类型
    size_bytes: int  # 原始文件字节数
    status: str  # pending/ready/failed
    created_at: datetime  # 版本创建时间；内容本身之后不原地修改


class KnowledgeIngestionView(BaseModel):
    """一次上传/查询的聚合视图，同时返回文档、版本和任务三个层次。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document: KnowledgeDocumentView  # 逻辑知识层
    version: KnowledgeVersionView  # 本次命中的文件版本层
    job_id: str  # 可查询、重试和审计的入库任务ID
    job_status: str  # queued/processing/succeeded/failed
    attempt_count: int = Field(ge=0)  # 进入processing的累计次数
    block_count: int = Field(ge=0)  # Loader生成并持久化的SourceBlock数量
    chunk_count: int = Field(ge=0)  # 策略生成并持久化的Parent+Child总数
    deduplicated: bool  # 是否复用了同SHA-256版本
    error_code: str | None = None  # 稳定错误码，不向客户端泄露异常栈


class KnowledgeIndexVersionView(BaseModel):
    """逻辑向量索引版本；活动状态决定检索器允许使用哪批Milvus记录。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str  # 同时写入Milvus的index_version_id
    document_version_id: str  # 被索引的不可变知识版本
    collection_name: str  # 物理Collection Schema版本
    embedding_provider: str  # mock/openai_compatible等Provider类型
    embedding_model: str  # 生成文档向量的模型，查询必须使用相同模型
    embedding_dimension: int  # Collection FLOAT_VECTOR维度
    chunk_schema_version: str  # 生成向量输入的Chunk契约版本
    build_key: str  # 相同内容与配置的构建幂等键
    status: str  # building/active/superseded/failed
    total_chunks: int = Field(ge=0)  # 本次应索引的Child总数
    indexed_chunks: int = Field(ge=0)  # 已成功写入Milvus的Child数
    created_at: datetime
    activated_at: datetime | None
    finished_at: datetime | None


class KnowledgeIndexingView(BaseModel):
    """索引版本与当前构建任务的聚合视图。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: KnowledgeIndexVersionView
    job_id: str
    job_status: str  # queued/processing/succeeded/failed
    attempt_count: int = Field(ge=0)
    deduplicated: bool  # 是否复用了相同build_key的索引版本
    error_code: str | None = None


class KnowledgeRetrievalRequest(BaseModel):
    """检索调试请求；7A可独立对比Vector与BM25通道。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    business_domain: BusinessDomain
    allowed_scopes: tuple[str, ...] = Field(
        default=("public",),
        min_length=1,
        max_length=32,
    )
    history: tuple[ChatMessage, ...] = Field(default=(), max_length=20)
    retrieval_mode: RetrievalMode = RetrievalMode.VECTOR
    child_top_k: int = Field(default=20, ge=1, le=100)
    parent_top_k: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("retrieval query must not be blank")
        return normalized

    @field_validator("allowed_scopes")
    @classmethod
    def scopes_must_be_unique_and_safe(
            cls,
            value: tuple[str, ...],
    ) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(scope.strip() for scope in value))
        if any(not scope or len(scope) > 64 for scope in normalized):
            raise ValueError("allowed scopes must contain 1-64 characters")
        return normalized


class RetrievalChildHitView(BaseModel):
    """经过召回和MySQL二次复核的Child候选。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    parent_chunk_id: str
    document_id: str
    document_version_id: str
    index_version_id: str
    source: RetrievalSource
    score: float


class RetrievalParentView(BaseModel):
    """Small-to-Big还原后的完整Parent及可解释来源。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent: KnowledgeChunkView
    document_id: str
    document_title: str
    document_version_id: str
    index_version_id: str
    matched_child_ids: tuple[str, ...]
    best_child_score: float
    first_child_rank: int = Field(ge=1)


class KnowledgeRetrievalView(BaseModel):
    """检索调试输出；展示通道、Rewrite、活动索引、Child和Parent。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rewrite: QueryRewriteResult
    retrieval_mode: RetrievalMode
    embedding_model: str | None
    active_index_version_ids: tuple[str, ...]
    child_hits: tuple[RetrievalChildHitView, ...]
    parents: tuple[RetrievalParentView, ...]
    incompatible_index_count: int = Field(ge=0)
    discarded_child_count: int = Field(ge=0)
    discarded_parent_count: int = Field(ge=0)


class KnowledgeChunkView(BaseModel):
    """用于管理端检查分块质量，不包含未来的Embedding向量。"""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: str  # 持久化Chunk UUID
    version_id: str  # 所属不可变文档版本
    source_block_id: str | None  # 主来源块；删除来源时允许SET NULL保留审计
    parent_chunk_id: str | None  # Child指向Parent，Parent自身为None
    kind: str  # parent提供上下文，child负责召回
    ordinal: int  # 当前版本内稳定顺序
    content: str  # 真正参与检索或进入模型上下文的文本
    char_count: int  # 当前使用字符预算；真实Token统计留到第6周
    metadata_json: dict[str, object]  # 策略、标题、页码、FAQ关键词等扩展信息


class ChildChunkHitInput(BaseModel):
    """检索层交给Small-to-Big的最小契约；数组顺序就是召回排序。"""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    chunk_id: str = Field(min_length=1)  # 检索器命中的持久化Child UUID
    score: float = Field(description="归一化相关性分数，数值越大表示越相关")


class SmallToBigExpansionRequest(BaseModel):
    """当前是可调试接口；第6周以后由BM25/向量检索器自动构造。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # 数组位置表达召回顺序；上限防止调试接口被超大候选列表滥用。
    hits: list[ChildChunkHitInput] = Field(min_length=1, max_length=100)


class ParentChunkContextView(BaseModel):
    """去重后的完整Parent，以及触发它的Child命中证据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parent: KnowledgeChunkView  # 最终交给生成模型的完整上下文
    matched_child_ids: list[str]  # 触发该Parent的去重Child证据
    best_child_score: float  # 同一Parent下最高的“越大越相关”分数
    first_child_rank: int = Field(ge=1)  # Parent首次出现的Child排名，从1开始


class ChunkDebugRequest(BaseModel):
    """不落库的分块实验输入，便于修改SourceBlock后立即观察策略结果。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    knowledge_type: DocumentKnowledgeType  # 决定专用策略；TABLE仍由组合策略优先
    # 直接接收Loader统一输出，不上传文件、不创建数据库记录。
    blocks: tuple[LoadedSourceBlock, ...] = Field(min_length=1, max_length=500)


class ChunkDebugView(BaseModel):
    """分块草稿及最小诊断信息，不包含Embedding或检索分数。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunks: tuple[ChunkDraft, ...]  # 尚未映射数据库UUID的算法原始输出
    parent_count: int = Field(ge=0)  # 快速观察上下文分组数量
    child_count: int = Field(ge=0)  # 快速观察未来索引候选规模
    strategy_counts: dict[str, int]  # metadata.strategy → Parent+Child数量
    # 非标题SourceBlock若未被任何Chunk或分组元数据覆盖，会列在这里。
    unrepresented_source_ordinals: list[int]
