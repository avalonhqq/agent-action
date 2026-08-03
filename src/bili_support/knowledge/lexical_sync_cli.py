"""手动触发MySQL活动Child到Elasticsearch的幂等全量同步。"""

from __future__ import annotations

import asyncio

from bili_support.core.config import get_settings
from bili_support.core.database import Database
from bili_support.knowledge.elasticsearch_store import ElasticsearchLexicalStore
from bili_support.services.lexical_sync import LexicalIndexSyncService


async def _run() -> int:
    settings = get_settings()
    if not settings.elasticsearch_enabled:
        raise RuntimeError("Elasticsearch is not enabled")
    database = Database(settings.database_url, echo=settings.database_echo)
    store = ElasticsearchLexicalStore(
        url=settings.elasticsearch_url,
        index_prefix=settings.elasticsearch_index_prefix,
        read_alias=settings.elasticsearch_read_alias,
        request_timeout_seconds=settings.elasticsearch_request_timeout_seconds,
        batch_size=settings.elasticsearch_batch_size,
        username=settings.elasticsearch_username,
        password=(
            settings.elasticsearch_password.get_secret_value()
            if settings.elasticsearch_password is not None
            else None
        ),
    )
    try:
        result = await LexicalIndexSyncService(
            database=database,
            store=store,
        ).synchronize("manual_cli")
        print(result.model_dump_json())
        return 0 if result.status == "succeeded" else 1
    finally:
        await store.aclose()
        await database.dispose()


def main() -> None:
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
