"""MySQL活动知识到Elasticsearch版本索引的全量同步编排。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256

from pydantic import BaseModel, ConfigDict, Field

from bili_support.core.database import Database
from bili_support.knowledge.dictionary import (
    PublishedDictionaryEntry,
    match_published_terms,
    parse_dictionary_manifest,
)
from bili_support.knowledge.lexical_store import LexicalRecord, LexicalStore
from bili_support.repositories import KnowledgeDictionaryRepository, KnowledgeRepository

_LEXICAL_SCHEMA_VERSION = "es-child-v2-current-state"


class LexicalSyncResult(BaseModel):
    """最近一次同步结果；失败时旧Alias继续服务。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str
    trigger: str
    generation: str | None = None
    physical_index: str | None = None
    document_count: int = Field(default=0, ge=0)
    deduplicated: bool = False
    error_code: str | None = None
    finished_at: datetime


class LexicalIndexSyncService:
    """串行构建完整活动快照，只有完整成功后才由Store切换Alias。"""

    def __init__(self, *, database: Database, store: LexicalStore) -> None:
        self._database = database
        self._store = store
        self._lock = asyncio.Lock()
        self._last_result: LexicalSyncResult | None = None

    @property
    def last_result(self) -> LexicalSyncResult | None:
        return self._last_result

    async def synchronize(self, trigger: str) -> LexicalSyncResult:
        async with self._lock:
            try:
                records, generation = await self._snapshot()
                rebuilt = await self._store.rebuild(
                    generation=generation,
                    records=records,
                )
                result = LexicalSyncResult(
                    status="succeeded",
                    trigger=trigger,
                    generation=generation,
                    physical_index=rebuilt.physical_index,
                    document_count=rebuilt.document_count,
                    deduplicated=rebuilt.deduplicated,
                    finished_at=datetime.now(UTC),
                )
            except Exception as exc:
                result = LexicalSyncResult(
                    status="failed",
                    trigger=trigger,
                    error_code=_sync_error_code(exc),
                    finished_at=datetime.now(UTC),
                )
            self._last_result = result
            return result

    async def _snapshot(self) -> tuple[tuple[LexicalRecord, ...], str]:
        async with self._database.session() as session:
            rows = await KnowledgeRepository(session).active_children_for_lexical_sync()
            active_dictionary = await KnowledgeDictionaryRepository(session).active_version()
            entries = (
                parse_dictionary_manifest(active_dictionary.manifest_json)
                if active_dictionary is not None
                else ()
            )
            dictionary_hash = (
                active_dictionary.content_sha256
                if active_dictionary is not None
                else "no-dictionary"
            )
        by_domain: dict[str, list[PublishedDictionaryEntry]] = defaultdict(list)
        for entry in entries:
            by_domain[entry.business_domain.value].append(entry)
        records = tuple(
            LexicalRecord(
                chunk_id=row.chunk.id,
                parent_chunk_id=str(row.chunk.parent_chunk_id),
                document_id=row.document.id,
                version_id=row.document_version.id,
                index_version_id=row.index_version.id,
                owner_user_id=row.document.created_by_user_id,
                document_title=row.document.title,
                content=row.chunk.content,
                business_domain=row.document.business_domain,
                access_scope=tuple(row.document.access_scope),
                document_active=row.document.status == "active",
                version_current=row.document_version.is_current,
                index_active=row.index_version.status == "active",
                domain_terms=match_published_terms(
                    f"{row.document.title}\n{row.chunk.content}",
                    tuple(by_domain[row.document.business_domain]),
                ),
            )
            for row in rows
        )
        active_index_ids = sorted({item.index_version_id for item in records})
        # Mapping或Analyzer变化必须产生新generation，不能误复用旧物理索引。
        generation_payload = "|".join(
            (_LEXICAL_SCHEMA_VERSION, *active_index_ids, dictionary_hash)
        )
        generation = sha256(generation_payload.encode("utf-8")).hexdigest()
        return records, generation


def _sync_error_code(exc: Exception) -> str:
    name = type(exc).__name__.upper()
    return f"LEXICAL_SYNC_{name}"[:64]
