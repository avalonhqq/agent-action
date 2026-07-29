import pytest

from bili_support.knowledge.vector_store import (
    MilvusVectorStore,
    VectorRecord,
    VectorSearchQuery,
)


class _FakeSchema:
    def __init__(self) -> None:
        self.fields: list[dict[str, object]] = []

    def add_field(self, **kwargs: object) -> None:
        self.fields.append(kwargs)


class _FakeIndexParams:
    def __init__(self) -> None:
        self.indexes: list[dict[str, object]] = []

    def add_index(self, **kwargs: object) -> None:
        self.indexes.append(kwargs)


class _FakeMilvusClient:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.schema = _FakeSchema()
        self.index_params = _FakeIndexParams()
        self.created: dict[str, object] | None = None
        self.upserted: list[dict[str, object]] = []
        self.search_kwargs: dict[str, object] | None = None
        self.deleted_filter: str | None = None
        self.closed = False

    def has_collection(self, *, collection_name: str) -> bool:
        assert collection_name == "bili_support_child_v2"
        return self.exists

    def list_collections(self) -> list[str]:
        return ["bili_support_child_v2"] if self.exists else []

    def create_schema(
        self,
        *,
        auto_id: bool,
        enable_dynamic_field: bool,
    ) -> _FakeSchema:
        assert auto_id is False
        assert enable_dynamic_field is False
        return self.schema

    def prepare_index_params(self) -> _FakeIndexParams:
        return self.index_params

    def create_collection(self, **kwargs: object) -> None:
        self.created = kwargs

    def upsert(
        self,
        *,
        collection_name: str,
        data: list[dict[str, object]],
    ) -> object:
        assert collection_name == "bili_support_child_v2"
        self.upserted = data
        return {"upsert_count": len(data)}

    def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
        self.search_kwargs = kwargs
        return [
            [
                {
                    # 真实PyMilvus会使用Collection定义的主键字段名返回命中ID。
                    "chunk_id": "child-1",
                    "distance": 0.91,
                    "entity": {
                        "document_id": "document-1",
                        "version_id": "version-1",
                        "index_version_id": "index-version-1",
                    },
                }
            ]
        ]

    def delete(self, *, collection_name: str, filter: str) -> object:
        assert collection_name == "bili_support_child_v2"
        self.deleted_filter = filter
        return {"delete_count": 1}

    def close(self) -> None:
        self.closed = True


def _store(
    fake: _FakeMilvusClient,
    *,
    dimension: int = 4,
) -> MilvusVectorStore:
    return MilvusVectorStore(
        uri="http://127.0.0.1:19530",
        token="root:Milvus",
        collection_name="bili_support_child_v2",
        dimension=dimension,
        client=fake,
    )


async def test_ensure_collection_creates_scalar_fields_and_hnsw_index() -> None:
    fake = _FakeMilvusClient()

    await _store(fake).ensure_collection()
    await _store(fake).ping()

    assert fake.created is not None
    assert fake.created["consistency_level"] == "Session"
    assert {field["field_name"] for field in fake.schema.fields} == {
        "chunk_id",
        "document_id",
        "version_id",
        "index_version_id",
        "business_domain",
        "access_scope",
        "embedding_model",
        "embedding",
    }
    assert fake.index_params.indexes[0]["index_type"] == "HNSW"
    assert fake.index_params.indexes[0]["metric_type"] == "COSINE"


async def test_upsert_search_filter_and_delete_version() -> None:
    fake = _FakeMilvusClient(exists=True)
    store = _store(fake)
    record = VectorRecord(
        chunk_id="child-1",
        document_id="document-1",
        version_id="version-1",
        index_version_id="index-version-1",
        business_domain="membership",
        access_scope=("public", "support"),
        embedding_model="mock-hash-embedding-v1",
        vector=(0.1, 0.2, 0.3, 0.4),
    )

    assert await store.upsert([record]) == 1
    hits = await store.search(
        VectorSearchQuery(
            vector=(0.1, 0.2, 0.3, 0.4),
            top_k=5,
            business_domain="membership",
            allowed_scopes=("support",),
            version_ids=("version-1",),
            index_version_ids=("index-version-1",),
        )
    )
    await store.delete_version('version-"unsafe')
    await store.delete_index_version('index-"unsafe')
    await store.aclose()

    assert fake.upserted[0]["chunk_id"] == "child-1"
    assert hits[0].chunk_id == "child-1"
    assert hits[0].score == 0.91
    assert fake.search_kwargs is not None
    expression = str(fake.search_kwargs["filter"])
    assert 'ARRAY_CONTAINS_ANY(access_scope, ["support"])' in expression
    assert 'business_domain == "membership"' in expression
    assert 'version_id IN ["version-1"]' in expression
    assert 'index_version_id IN ["index-version-1"]' in expression
    assert fake.deleted_filter == 'index_version_id == "index-\\"unsafe"'
    assert fake.closed is True


async def test_vector_dimension_mismatch_fails_before_sdk_call() -> None:
    fake = _FakeMilvusClient(exists=True)

    with pytest.raises(ValueError, match="dimension"):
        await _store(fake).search(
            VectorSearchQuery(
                vector=(0.1, 0.2, 0.3),
                allowed_scopes=("public",),
                index_version_ids=("index-version-1",),
            )
        )

    assert fake.search_kwargs is None
