"""Milvus向量存储边界，以及与SDK隔离的领域类型。

MySQL仍是文档、权限、版本和Chunk正文的事实源；Milvus保存Child向量及检索过滤所需的冗余字段。
检索命中只返回Chunk ID，随后必须回MySQL执行权限复核和Small-to-Big。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from math import isfinite
from typing import Any, Protocol, Self, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VectorRecord(BaseModel):
    """一条写入Milvus的Child向量和最小过滤元数据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=36)
    document_id: str = Field(min_length=1, max_length=36)
    version_id: str = Field(min_length=1, max_length=36)
    business_domain: str = Field(min_length=1, max_length=32)
    access_scope: tuple[str, ...] = Field(min_length=1, max_length=32)
    embedding_model: str = Field(min_length=1, max_length=128)
    vector: tuple[float, ...] = Field(min_length=2)

    @field_validator("access_scope")
    @classmethod
    def access_scope_must_be_unique(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        """权限标签去空白并保持首次顺序，防止重复字段浪费ARRAY容量。"""

        normalized = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item or len(item) > 64 for item in normalized):
            raise ValueError("access scope labels must contain 1-64 characters")
        return normalized

    @field_validator("vector")
    @classmethod
    def vector_must_be_finite(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        """在SDK调用前阻止非法浮点数和难排查的服务端错误。"""

        if any(not isfinite(item) for item in value):
            raise ValueError("vector values must be finite")
        return value


class VectorSearchQuery(BaseModel):
    """一次带业务域、权限和可选版本约束的向量检索。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector: tuple[float, ...] = Field(min_length=2)
    top_k: int = Field(default=10, ge=1, le=100)
    business_domain: str | None = Field(default=None, min_length=1, max_length=32)
    allowed_scopes: tuple[str, ...] = Field(min_length=1, max_length=32)
    version_ids: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("vector")
    @classmethod
    def vector_must_be_finite(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(not isfinite(item) for item in value):
            raise ValueError("query vector values must be finite")
        return value

    @field_validator("allowed_scopes", "version_ids")
    @classmethod
    def filter_values_must_be_safe(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        """过滤值由适配器转义；类型层仍拒绝空值和异常长字符串。"""

        normalized = tuple(dict.fromkeys(item.strip() for item in value))
        if any(not item or len(item) > 64 for item in normalized):
            raise ValueError("vector filter values must contain 1-64 characters")
        return normalized


class VectorSearchHit(BaseModel):
    """Milvus返回的Child候选；score遵循越大越相关的COSINE契约。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    document_id: str
    version_id: str
    score: float


@runtime_checkable
class VectorStore(Protocol):
    """业务索引与检索层依赖的向量数据库最小能力。"""

    async def ensure_collection(self) -> None:
        """幂等创建Collection、标量Schema和向量索引。"""

        ...

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """按chunk_id插入或替换Child向量，返回处理数量。"""

        ...

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        """先执行标量权限过滤，再返回有序Child候选。"""

        ...

    async def delete_version(self, version_id: str) -> None:
        """删除指定文档版本的所有向量，供重建和版本下线使用。"""

        ...

    async def aclose(self) -> None:
        """释放SDK连接资源。"""

        ...


class _MilvusClientProtocol(Protocol):
    """只声明适配器实际使用的同步MilvusClient方法，便于Fake测试。"""

    def has_collection(self, *, collection_name: str) -> bool: ...

    def create_schema(
        self,
        *,
        auto_id: bool,
        enable_dynamic_field: bool,
    ) -> Any: ...

    def prepare_index_params(self) -> Any: ...

    def create_collection(self, **kwargs: object) -> None: ...

    def upsert(
        self,
        *,
        collection_name: str,
        data: list[dict[str, object]],
    ) -> object: ...

    def search(self, **kwargs: object) -> list[list[dict[str, object]]]: ...

    def delete(self, *, collection_name: str, filter: str) -> object: ...

    def close(self) -> None: ...


class MilvusVectorStore:
    """使用Milvus 2.6 MilvusClient的异步适配器；阻塞SDK调用转移到线程。"""

    def __init__(
        self,
        *,
        uri: str,
        token: str,
        collection_name: str,
        dimension: int,
        index_m: int = 16,
        index_ef_construction: int = 200,
        search_ef: int = 64,
        client: _MilvusClientProtocol | None = None,
    ) -> None:
        if dimension < 2:
            raise ValueError("Milvus vector dimension must be at least 2")
        if not collection_name.strip():
            raise ValueError("Milvus collection name must not be blank")
        self._collection_name = collection_name
        self._dimension = dimension
        self._index_m = index_m
        self._index_ef_construction = index_ef_construction
        self._search_ef = search_ef
        self._client = client or _create_milvus_client(uri=uri, token=token)

    async def ensure_collection(self) -> None:
        """在线程中执行同步Schema创建；已存在时不破坏线上Collection。"""

        await asyncio.to_thread(self._ensure_collection_sync)

    def _ensure_collection_sync(self) -> None:
        if self._client.has_collection(collection_name=self._collection_name):
            return

        # 延迟导入让纯Mock测试无需启动Milvus服务；pymilvus仍是正式运行依赖。
        from pymilvus import DataType  # type: ignore[import-untyped]

        schema = self._client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
        )
        schema.add_field(
            field_name="chunk_id",
            datatype=DataType.VARCHAR,
            is_primary=True,
            max_length=36,
        )
        schema.add_field(
            field_name="document_id",
            datatype=DataType.VARCHAR,
            max_length=36,
        )
        schema.add_field(
            field_name="version_id",
            datatype=DataType.VARCHAR,
            max_length=36,
        )
        schema.add_field(
            field_name="business_domain",
            datatype=DataType.VARCHAR,
            max_length=32,
        )
        schema.add_field(
            field_name="access_scope",
            datatype=DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=32,
            max_length=64,
        )
        schema.add_field(
            field_name="embedding_model",
            datatype=DataType.VARCHAR,
            max_length=128,
        )
        schema.add_field(
            field_name="embedding",
            datatype=DataType.FLOAT_VECTOR,
            dim=self._dimension,
        )

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_name="embedding_hnsw",
            index_type="HNSW",
            metric_type="COSINE",
            params={
                "M": self._index_m,
                "efConstruction": self._index_ef_construction,
            },
        )
        self._client.create_collection(
            collection_name=self._collection_name,
            schema=schema,
            index_params=index_params,
            consistency_level="Session",
        )

    async def upsert(self, records: Sequence[VectorRecord]) -> int:
        """校验统一维度后批量upsert；空批次是安全的无操作。"""

        if not records:
            return 0
        if any(len(record.vector) != self._dimension for record in records):
            raise ValueError("record vector dimension does not match collection")
        data = [
            {
                "chunk_id": record.chunk_id,
                "document_id": record.document_id,
                "version_id": record.version_id,
                "business_domain": record.business_domain,
                "access_scope": list(record.access_scope),
                "embedding_model": record.embedding_model,
                "embedding": list(record.vector),
            }
            for record in records
        ]
        await asyncio.to_thread(
            self._client.upsert,
            collection_name=self._collection_name,
            data=data,
        )
        return len(records)

    async def search(self, query: VectorSearchQuery) -> tuple[VectorSearchHit, ...]:
        """使用COSINE/HNSW检索，并把SDK响应归一为稳定内部Hit。"""

        if len(query.vector) != self._dimension:
            raise ValueError("query vector dimension does not match collection")
        raw = await asyncio.to_thread(
            self._client.search,
            collection_name=self._collection_name,
            data=[list(query.vector)],
            anns_field="embedding",
            filter=_milvus_filter(query),
            limit=query.top_k,
            output_fields=["document_id", "version_id"],
            search_params={
                "metric_type": "COSINE",
                "params": {"ef": self._search_ef},
            },
            consistency_level="Session",
        )
        rows = raw[0] if raw else []
        return tuple(_parse_hit(row) for row in rows)

    async def delete_version(self, version_id: str) -> None:
        """使用JSON转义构造等值过滤，避免版本ID注入Milvus表达式。"""

        normalized = version_id.strip()
        if not normalized or len(normalized) > 64:
            raise ValueError("version id must contain 1-64 characters")
        await asyncio.to_thread(
            self._client.delete,
            collection_name=self._collection_name,
            filter=f"version_id == {json.dumps(normalized, ensure_ascii=False)}",
        )

    async def aclose(self) -> None:
        await asyncio.to_thread(self._client.close)


def _create_milvus_client(*, uri: str, token: str) -> _MilvusClientProtocol:
    """延迟创建官方SDK客户端，使协议和领域类型不依赖全局连接。"""

    from pymilvus import MilvusClient  # type: ignore[import-untyped]

    factory = cast(Callable[..., _MilvusClientProtocol], MilvusClient)
    return factory(uri=uri, token=token)


def _milvus_filter(query: VectorSearchQuery) -> str:
    """仅用JSON序列化后的字面量拼接白名单字段，构造标量过滤表达式。"""

    scopes = json.dumps(
        list(query.allowed_scopes),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    clauses = [f"ARRAY_CONTAINS_ANY(access_scope, {scopes})"]
    if query.business_domain is not None:
        clauses.append(
            "business_domain == "
            + json.dumps(query.business_domain, ensure_ascii=False)
        )
    if query.version_ids:
        versions = json.dumps(
            list(query.version_ids),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        clauses.append(f"version_id IN {versions}")
    return " AND ".join(clauses)


def _parse_hit(row: dict[str, object]) -> VectorSearchHit:
    """兼容MilvusClient的id/distance/entity结构，并严格检查必需输出字段。"""

    entity = row.get("entity")
    if not isinstance(entity, dict):
        raise ValueError("Milvus search hit is missing entity fields")
    chunk_id = row.get("id")
    score = row.get("distance")
    document_id = entity.get("document_id")
    version_id = entity.get("version_id")
    if (
        not isinstance(chunk_id, str)
        or not isinstance(score, int | float)
        or not isinstance(document_id, str)
        or not isinstance(version_id, str)
    ):
        raise ValueError("Milvus search hit has invalid field types")
    return VectorSearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        version_id=version_id,
        score=float(score),
    )
