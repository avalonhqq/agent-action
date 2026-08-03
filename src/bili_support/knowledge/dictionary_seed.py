"""把受版本控制的领域词表幂等导入候选区。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from bili_support.core.config import get_settings
from bili_support.core.database import Database
from bili_support.core.security import UserContext
from bili_support.schemas.dictionary import DictionaryTermCreate
from bili_support.services.dictionary import KnowledgeDictionaryService

_TERM_LIST_ADAPTER = TypeAdapter(list[DictionaryTermCreate])
_DEFAULT_FIXTURE = Path("data/fixtures/dictionary_terms_v1.json")


def load_dictionary_terms(path: Path) -> list[DictionaryTermCreate]:
    """读取并严格校验JSON词表；未知字段和非法枚举会立即失败。"""

    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    terms = _TERM_LIST_ADAPTER.validate_python(raw)
    identities = {
        (item.business_domain.value, item.term.strip().casefold()) for item in terms
    }
    if len(identities) != len(terms):
        raise ValueError("词表中存在同一业务域下的重复领域词")
    return terms


async def seed_dictionary_terms(
    *,
    path: Path,
    actor: UserContext,
) -> dict[str, int]:
    """通过领域词Service写入，保留去重、用户审计和candidate状态。"""

    settings = get_settings()
    database = Database(settings.database_url, echo=settings.database_echo)
    service = KnowledgeDictionaryService(database)
    try:
        existing = await service.list_terms(business_domain=None, status=None)
        identities = {
            (item.business_domain.value, item.normalized_term) for item in existing
        }
        inserted = 0
        skipped = 0
        for payload in load_dictionary_terms(path):
            identity = (
                payload.business_domain.value,
                payload.term.strip().casefold(),
            )
            if identity in identities:
                skipped += 1
                continue
            await service.create_candidate(actor=actor, payload=payload)
            identities.add(identity)
            inserted += 1
        return {"inserted": inserted, "skipped": skipped, "total": len(identities)}
    finally:
        await database.dispose()


def main() -> None:
    """命令行入口；默认导入首批哔哩哔哩客服领域词。"""

    parser = argparse.ArgumentParser(description="导入领域词候选")
    parser.add_argument("--file", type=Path, default=_DEFAULT_FIXTURE)
    parser.add_argument("--actor-id", default="dictionary-seed")
    parser.add_argument("--actor-name", default="领域词初始化任务")
    args = parser.parse_args()
    report = asyncio.run(
        seed_dictionary_terms(
            path=args.file,
            actor=UserContext(
                external_id=args.actor_id,
                display_name=args.actor_name,
            ),
        )
    )
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
