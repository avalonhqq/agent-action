"""官方异步客户端实现的版本化Elasticsearch BM25适配器。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from elasticsearch import AsyncElasticsearch, NotFoundError
from elasticsearch.helpers import async_bulk

from bili_support.knowledge.lexical_store import (
    LexicalRebuildResult,
    LexicalRecord,
    LexicalSearchHit,
    LexicalSearchQuery,
)


class ElasticsearchLexicalStore:
    """新物理索引完整写入后才切换Alias，失败不会暴露半量数据。"""

    def __init__(
        self,
        *,
        url: str,
        index_prefix: str,
        read_alias: str,
        request_timeout_seconds: float,
        batch_size: int,
        username: str | None = None,
        password: str | None = None,
        client: AsyncElasticsearch | None = None,
    ) -> None:
        self._index_prefix = index_prefix.casefold()
        self._read_alias = read_alias.casefold()
        self._batch_size = batch_size
        basic_auth = (username, password) if username and password else None
        self._client = client or AsyncElasticsearch(
            url,
            basic_auth=basic_auth,
            request_timeout=request_timeout_seconds,
            retry_on_timeout=True,
            max_retries=2,
        )

    async def ping(self) -> None:
        if not await self._client.ping():
            raise RuntimeError("Elasticsearch ping failed")

    async def rebuild(
        self,
        *,
        generation: str,
        records: Sequence[LexicalRecord],
    ) -> LexicalRebuildResult:
        physical_index = f"{self._index_prefix}-{generation[:20].casefold()}"
        if await self._client.indices.exists(index=physical_index):
            if await self._client.indices.exists_alias(
                index=physical_index,
                name=self._read_alias,
            ):
                count = await self._client.count(index=physical_index)
                return LexicalRebuildResult(
                    physical_index=physical_index,
                    generation=generation,
                    document_count=int(count["count"]),
                    deduplicated=True,
                )
            await self._client.indices.delete(index=physical_index)

        await self._client.indices.create(
            index=physical_index,
            settings=_INDEX_SETTINGS,
            mappings=_INDEX_MAPPINGS,
        )
        try:
            if records:
                success, _ = await async_bulk(
                    self._client,
                    (_bulk_action(physical_index, item) for item in records),
                    chunk_size=self._batch_size,
                    raise_on_error=True,
                    raise_on_exception=True,
                )
                if success != len(records):
                    raise RuntimeError("Elasticsearch partial bulk write")
            await self._client.indices.refresh(index=physical_index)
            await self._client.indices.update_aliases(
                actions=[
                    {
                        "remove": {
                            "index": f"{self._index_prefix}-*",
                            "alias": self._read_alias,
                            "must_exist": False,
                        }
                    },
                    {"add": {"index": physical_index, "alias": self._read_alias}},
                ]
            )
        except Exception:
            await self._client.indices.delete(index=physical_index, ignore_unavailable=True)
            raise
        return LexicalRebuildResult(
            physical_index=physical_index,
            generation=generation,
            document_count=len(records),
        )

    async def search(
        self,
        query: LexicalSearchQuery,
    ) -> tuple[LexicalSearchHit, ...]:
        should: list[dict[str, Any]] = [
            {
                "multi_match": {
                    "query": query.text,
                    "fields": ["document_title^2.5", "content"],
                    "type": "best_fields",
                }
            },
            {"match_phrase": {"document_title": {"query": query.text, "boost": 4}}},
            {"match_phrase": {"content": {"query": query.text, "boost": 2}}},
        ]
        if query.domain_terms:
            should.append(
                {"terms": {"domain_terms": [*query.domain_terms], "boost": 6}}
            )
        body = {
            "bool": {
                "filter": [
                    {"term": {"document_active": True}},
                    {"term": {"version_current": True}},
                    {"term": {"index_active": True}},
                    {"term": {"owner_user_id": query.owner_user_id}},
                    {"term": {"business_domain": query.business_domain}},
                    {"terms": {"access_scope": [*query.allowed_scopes]}},
                ],
                "should": should,
                "minimum_should_match": 1,
            }
        }
        try:
            response = await self._client.search(
                index=self._read_alias,
                query=body,
                size=query.top_k,
                source_includes=[
                    "chunk_id",
                    "document_id",
                    "version_id",
                    "index_version_id",
                ],
            )
        except NotFoundError:
            return ()
        hits = response["hits"]["hits"]
        return tuple(
            LexicalSearchHit(
                chunk_id=item["_source"]["chunk_id"],
                document_id=item["_source"]["document_id"],
                version_id=item["_source"]["version_id"],
                index_version_id=item["_source"]["index_version_id"],
                score=float(item["_score"]),
            )
            for item in hits
            if item.get("_score") is not None and float(item["_score"]) > 0
        )

    async def aclose(self) -> None:
        await self._client.close()


def _bulk_action(index: str, record: LexicalRecord) -> dict[str, object]:
    return {
        "_op_type": "index",
        "_index": index,
        "_id": f"{record.index_version_id}:{record.chunk_id}",
        "_source": record.model_dump(mode="json"),
    }


_INDEX_SETTINGS: dict[str, object] = {
    "number_of_shards": 1,
    "number_of_replicas": 0,
    "analysis": {
        "analyzer": {
            "bili_cjk": {
                "type": "custom",
                "tokenizer": "standard",
                "filter": ["lowercase", "cjk_width", "cjk_bigram"],
            }
        },
        "normalizer": {
            "bili_keyword": {"type": "custom", "filter": ["lowercase"]}
        },
    },
}

_INDEX_MAPPINGS: dict[str, object] = {
    "dynamic": "strict",
    "properties": {
        "chunk_id": {"type": "keyword"},
        "parent_chunk_id": {"type": "keyword"},
        "document_id": {"type": "keyword"},
        "version_id": {"type": "keyword"},
        "index_version_id": {"type": "keyword"},
        "owner_user_id": {"type": "keyword"},
        "document_title": {"type": "text", "analyzer": "bili_cjk"},
        "content": {"type": "text", "analyzer": "bili_cjk"},
        "business_domain": {"type": "keyword"},
        "access_scope": {"type": "keyword"},
        "document_active": {"type": "boolean"},
        "version_current": {"type": "boolean"},
        "index_active": {"type": "boolean"},
        "domain_terms": {"type": "keyword", "normalizer": "bili_keyword"},
    },
}
