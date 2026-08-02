"""领域词候选去重、人工审核和不可变版本发布用例。"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

from bili_support.core.database import Database
from bili_support.core.exceptions import ConflictError, ResourceNotFoundError
from bili_support.core.security import UserContext
from bili_support.knowledge.dictionary import (
    DictionaryTermStatus,
    DictionaryTermType,
    DictionaryVersionStatus,
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


class KnowledgeDictionaryService:
    """所有写入经过用户审计；发布版本是可下载但不可修改的完整快照。"""

    def __init__(self, database: Database) -> None:
        self._database = database

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
            content_hash = sha256(artifact.encode("utf-8")).hexdigest()
            active = await repository.active_version()
            if active is not None and active.content_sha256 == content_hash:
                await session.commit()
                return DictionaryVersionView.model_validate(active)
            await repository.supersede_active()
            version = KnowledgeDictionaryVersion(
                version_number=await repository.next_version_number(),
                status=DictionaryVersionStatus.ACTIVE.value,
                content_sha256=content_hash,
                artifact_content=artifact,
                term_count=len(artifact.splitlines()),
                published_by_user_id=user.id,
                release_note=release_note.strip(),
            )
            repository.add_version(version)
            await session.flush()
            await session.commit()
            return DictionaryVersionView.model_validate(version)

    async def list_versions(self) -> list[DictionaryVersionView]:
        async with self._database.session() as session:
            versions = await KnowledgeDictionaryRepository(session).list_versions()
            return [DictionaryVersionView.model_validate(item) for item in versions]

    async def active_artifact(self) -> DictionaryArtifactView:
        async with self._database.session() as session:
            version = await KnowledgeDictionaryRepository(session).active_version()
            if version is None:
                raise ResourceNotFoundError("尚未发布领域词典")
            return DictionaryArtifactView.model_validate(version)

    async def artifact(self, version_id: str) -> DictionaryArtifactView:
        async with self._database.session() as session:
            version = await KnowledgeDictionaryRepository(session).version(version_id)
            if version is None:
                raise ResourceNotFoundError("领域词典版本不存在")
            return DictionaryArtifactView.model_validate(version)
