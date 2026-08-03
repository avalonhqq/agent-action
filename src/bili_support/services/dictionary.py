"""领域词候选去重、人工审核和不可变版本发布用例。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from hashlib import sha256
from os import replace
from pathlib import Path
from uuid import uuid4

from bili_support.core.database import Database
from bili_support.core.exceptions import ConflictError, ResourceNotFoundError
from bili_support.core.security import UserContext
from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.dictionary import (
    DictionaryTermStatus,
    DictionaryTermType,
    DictionaryVersionStatus,
    PublishedDictionaryEntry,
    parse_dictionary_manifest,
    render_dictionary_manifest,
    render_jieba_dictionary,
)
from bili_support.models.entities import (
    KnowledgeDictionaryTerm,
    KnowledgeDictionaryVersion,
)
from bili_support.repositories import UserRepository
from bili_support.repositories.dictionary import KnowledgeDictionaryRepository
from bili_support.schemas.dictionary import (
    DictionaryArtifactView,
    DictionaryTermCreate,
    DictionaryTermView,
    DictionaryVersionView,
    MockDictionaryCandidatesRequest,
)
from bili_support.services.lexical_sync import LexicalIndexSyncService


class KnowledgeDictionaryService:
    """所有写入经过用户审计；发布版本是可下载但不可修改的完整快照。"""

    def __init__(
        self,
        database: Database,
        *,
        runtime_dictionary_path: str | Path | None = None,
        lexical_sync_service: LexicalIndexSyncService | None = None,
    ) -> None:
        self._database = database
        self._runtime_dictionary_path = (
            Path(runtime_dictionary_path)
            if runtime_dictionary_path is not None
            else None
        )
        self._lexical_sync_service = lexical_sync_service

    async def create_candidate(
        self,
        *,
        actor: UserContext,
        payload: DictionaryTermCreate,
    ) -> DictionaryTermView:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            repository = KnowledgeDictionaryRepository(session)
            normalized = payload.term.strip().casefold()
            existing = await repository.term_by_identity(
                business_domain=payload.business_domain.value,
                normalized_term=normalized,
            )
            if existing is not None:
                await session.commit()
                return DictionaryTermView.model_validate(existing)
            aliases = [
                item for item in payload.aliases if item != normalized
            ]
            term = KnowledgeDictionaryTerm(
                term=payload.term,
                normalized_term=normalized,
                aliases=aliases,
                business_domain=payload.business_domain.value,
                term_type=payload.term_type.value,
                frequency=payload.frequency,
                source_type=payload.source_type.value,
                source_reference=payload.source_reference,
                status=DictionaryTermStatus.CANDIDATE.value,
                created_by_user_id=user.id,
            )
            repository.add_term(term)
            await session.flush()
            await session.commit()
            return DictionaryTermView.model_validate(term)

    async def create_mock_candidates(
        self,
        *,
        actor: UserContext,
        payload: MockDictionaryCandidatesRequest,
    ) -> list[DictionaryTermView]:
        """Mock来源只产生候选，不允许自动审核或发布。"""

        results = []
        for term in payload.terms:
            results.append(
                await self.create_candidate(
                    actor=actor,
                    payload=DictionaryTermCreate(
                        term=term,
                        business_domain=payload.business_domain,
                        term_type=DictionaryTermType.OTHER,
                        source_type=payload.source_type,
                        source_reference=payload.source_reference,
                    ),
                )
            )
        return results

    async def list_terms(
        self,
        *,
        business_domain: str | None,
        status: DictionaryTermStatus | None,
    ) -> list[DictionaryTermView]:
        async with self._database.session() as session:
            terms = await KnowledgeDictionaryRepository(session).list_terms(
                business_domain=business_domain,
                status=status.value if status is not None else None,
            )
            return [DictionaryTermView.model_validate(item) for item in terms]

    async def review(
        self,
        *,
        actor: UserContext,
        term_id: str,
        approved: bool,
        review_note: str,
    ) -> DictionaryTermView:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            term = await KnowledgeDictionaryRepository(session).term(term_id)
            if term is None:
                raise ResourceNotFoundError("领域词不存在")
            if term.status != DictionaryTermStatus.CANDIDATE.value:
                raise ConflictError("领域词已经完成审核，不能重复修改")
            term.status = (
                DictionaryTermStatus.APPROVED.value
                if approved
                else DictionaryTermStatus.REJECTED.value
            )
            term.review_note = review_note.strip()
            term.reviewed_by_user_id = user.id
            term.reviewed_at = datetime.now(UTC)
            await session.commit()
            return DictionaryTermView.model_validate(term)

    async def publish(
        self,
        *,
        actor: UserContext,
        release_note: str,
    ) -> DictionaryVersionView:
        async with self._database.session() as session:
            user = await UserRepository(session).get_or_create(
                actor.external_id, actor.display_name
            )
            repository = KnowledgeDictionaryRepository(session)
            terms = await repository.approved_terms()
            if not terms:
                raise ConflictError("没有已审核通过的领域词，不能发布")
            artifact = render_jieba_dictionary(
                tuple(
                    (item.normalized_term, tuple(item.aliases), item.frequency)
                    for item in terms
                )
            )
            entries = _published_entries(terms)
            manifest_json = render_dictionary_manifest(entries)
            content_hash = sha256(artifact.encode("utf-8")).hexdigest()
            active = await repository.active_version()
            if active is not None and active.content_sha256 == content_hash:
                # 0007迁移前的历史版本没有别名分组；相同制品首次重发时只补齐迁移字段。
                if active.manifest_json == "[]":
                    active.manifest_json = manifest_json
                await session.commit()
                selected = active
            else:
                await repository.supersede_active()
                selected = KnowledgeDictionaryVersion(
                    version_number=await repository.next_version_number(),
                    status=DictionaryVersionStatus.ACTIVE.value,
                    content_sha256=content_hash,
                    artifact_content=artifact,
                    manifest_json=manifest_json,
                    term_count=len(artifact.splitlines()),
                    published_by_user_id=user.id,
                    release_note=release_note.strip(),
                )
                repository.add_version(selected)
                await session.flush()
                await session.commit()
            view = DictionaryVersionView.model_validate(selected)
            deployed_artifact = selected.artifact_content
        await self._deploy_runtime_artifact(deployed_artifact)
        if self._lexical_sync_service is not None:
            await self._lexical_sync_service.synchronize("dictionary_publish")
        return view

    async def list_versions(self) -> list[DictionaryVersionView]:
        async with self._database.session() as session:
            versions = await KnowledgeDictionaryRepository(session).list_versions()
            return [DictionaryVersionView.model_validate(item) for item in versions]

    async def active_artifact(self) -> DictionaryArtifactView:
        async with self._database.session() as session:
            version = await KnowledgeDictionaryRepository(session).active_version()
            if version is None:
                raise ResourceNotFoundError("尚未发布领域词典")
            return self._artifact_view(version)

    async def artifact(self, version_id: str) -> DictionaryArtifactView:
        async with self._database.session() as session:
            version = await KnowledgeDictionaryRepository(session).version(version_id)
            if version is None:
                raise ResourceNotFoundError("领域词典版本不存在")
            return self._artifact_view(version)

    async def active_entries(
        self,
        *,
        business_domain: str | None = None,
    ) -> tuple[PublishedDictionaryEntry, ...]:
        """只返回active版本快照，approved但未发布的词不会进入运行时。"""

        async with self._database.session() as session:
            version = await KnowledgeDictionaryRepository(session).active_version()
            if version is None:
                return ()
            entries = parse_dictionary_manifest(version.manifest_json)
            if business_domain is None:
                return entries
            return tuple(
                item
                for item in entries
                if item.business_domain.value == business_domain
            )

    async def sync_active_artifact(self) -> bool:
        """应用启动时用数据库active版本修复本地运行时词典。"""

        async with self._database.session() as session:
            repository = KnowledgeDictionaryRepository(session)
            version = await repository.active_version()
            if version is None:
                return False
            if version.manifest_json == "[]":
                # 历史版本只在当前approved集合能复现完全相同制品时才安全回填。
                terms = await repository.approved_terms()
                rebuilt_artifact = render_jieba_dictionary(
                    tuple(
                        (item.normalized_term, tuple(item.aliases), item.frequency)
                        for item in terms
                    )
                )
                rebuilt_hash = sha256(rebuilt_artifact.encode("utf-8")).hexdigest()
                if rebuilt_hash == version.content_sha256:
                    version.manifest_json = render_dictionary_manifest(
                        _published_entries(terms)
                    )
                    await session.commit()
            artifact = version.artifact_content
        await self._deploy_runtime_artifact(artifact)
        return True

    def _artifact_view(
        self,
        version: KnowledgeDictionaryVersion,
    ) -> DictionaryArtifactView:
        return DictionaryArtifactView(
            id=version.id,
            version_number=version.version_number,
            status=DictionaryVersionStatus(version.status),
            content_sha256=version.content_sha256,
            term_count=version.term_count,
            published_by_user_id=version.published_by_user_id,
            release_note=version.release_note,
            published_at=version.published_at,
            artifact_content=version.artifact_content,
            entries=parse_dictionary_manifest(version.manifest_json),
        )

    async def _deploy_runtime_artifact(self, artifact: str) -> None:
        """以同目录原子替换部署Jieba制品，读请求不会看到半文件。"""

        if self._runtime_dictionary_path is None:
            return
        await asyncio.to_thread(
            _atomic_write_text,
            self._runtime_dictionary_path,
            artifact,
        )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _published_entries(
    terms: list[KnowledgeDictionaryTerm],
) -> tuple[PublishedDictionaryEntry, ...]:
    return tuple(
        PublishedDictionaryEntry(
            term=item.normalized_term,
            aliases=tuple(item.aliases),
            business_domain=BusinessDomain(item.business_domain),
            term_type=DictionaryTermType(item.term_type),
            frequency=item.frequency,
        )
        for item in terms
    )
