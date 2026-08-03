"""第7周7D：受控产品实体提取、证据覆盖与多样性选择。"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from bili_support.intent.types import EntityType, IntentEntity
from bili_support.knowledge.dictionary import PublishedDictionaryEntry
from bili_support.schemas.knowledge import RetrievalParentView

_CONTROLLED_ALIASES: dict[str, tuple[str, ...]] = {
    "大会员": ("大会员", "会员"),
    "连续包月": ("连续包月", "自动续费"),
    "年度套餐": ("年度套餐", "年度", "年费"),
    "季度套餐": ("季度套餐", "季度"),
    "单月套餐": ("单月套餐", "单月"),
    "电视端": ("电视端", "电视", "TV端"),
}


class RequiredEntity(BaseModel):
    """仅保存适合进入公开覆盖Trace的产品/套餐实体。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    aliases: tuple[str, ...] = Field(min_length=1, max_length=10)


class EvidenceCoverage(BaseModel):
    """一次检索对问题所需产品实体的覆盖摘要。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    required: tuple[str, ...] = ()
    covered: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    ratio: float = Field(ge=0, le=1)
    supplemental_query_used: bool = False


def extract_required_entities(
    *,
    question: str,
    intent_entities: tuple[IntentEntity, ...],
    published_entries: tuple[PublishedDictionaryEntry, ...] = (),
) -> tuple[RequiredEntity, ...]:
    """合并Intent产品实体、内置词和active发布快照，不读取候选词。"""

    names: list[str] = []
    alias_registry = _alias_registry(published_entries)
    for entity in intent_entities:
        if entity.type is not EntityType.PRODUCT:
            continue
        name = entity.normalized_value or entity.raw_value
        if name not in names:
            names.append(name)
    for name in _scan_aliases(question, alias_registry):
        if name not in names:
            names.append(name)
    return tuple(
        RequiredEntity(
            name=name,
            aliases=alias_registry.get(name, (name,)),
        )
        for name in names
    )


def _alias_registry(
    published_entries: tuple[PublishedDictionaryEntry, ...],
) -> Mapping[str, tuple[str, ...]]:
    """active版本覆盖同名内置项，并确保规范词本身始终可匹配。"""

    registry = dict(_CONTROLLED_ALIASES)
    for entry in published_entries:
        registry[entry.term] = tuple(dict.fromkeys((entry.term, *entry.aliases)))
    return registry


def _scan_aliases(
    question: str,
    registry: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    """最长非重叠匹配，避免“超级大会员”同时误命中“大会员”。"""

    text = question.casefold()
    matches: list[tuple[int, int, str, str]] = []
    for canonical, aliases in registry.items():
        for alias in aliases:
            surface = alias.casefold()
            start = text.find(surface)
            while surface and start >= 0:
                matches.append((start, start + len(surface), canonical, surface))
                start = text.find(surface, start + 1)
    selected: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for start, end, canonical, _surface in sorted(
        matches,
        key=lambda item: (-len(item[3]), item[0], item[2]),
    ):
        if any(start < used_end and end > used_start for used_start, used_end in occupied):
            continue
        selected.append((start, end, canonical))
        occupied.append((start, end))
    return tuple(
        canonical
        for _, _, canonical in sorted(selected, key=lambda item: item[0])
    )


def evaluate_coverage(
    *,
    entities: tuple[RequiredEntity, ...],
    parents: tuple[RetrievalParentView, ...],
    supplemental_query_used: bool = False,
) -> EvidenceCoverage:
    """标题或正文包含任一受控别名即视为该实体有证据覆盖。"""

    covered = []
    corpus = tuple(
        f"{item.document_title}\n{item.parent.content}".casefold()
        for item in parents
    )
    for entity in entities:
        if any(
            alias.casefold() in text
            for alias in entity.aliases
            for text in corpus
        ):
            covered.append(entity.name)
    required = tuple(item.name for item in entities)
    missing = tuple(name for name in required if name not in covered)
    return EvidenceCoverage(
        required=required,
        covered=tuple(covered),
        missing=missing,
        ratio=(len(covered) / len(required) if required else 1.0),
        supplemental_query_used=supplemental_query_used,
    )


def coverage_aware_parent_order(
    *,
    entities: tuple[RequiredEntity, ...],
    parents: tuple[RetrievalParentView, ...],
    top_k: int,
) -> tuple[RetrievalParentView, ...]:
    """先为每个实体保留首个覆盖Parent，再按原检索顺序补齐。"""

    selected: list[RetrievalParentView] = []
    selected_ids: set[str] = set()
    for entity in entities:
        for parent in parents:
            text = f"{parent.document_title}\n{parent.parent.content}".casefold()
            if any(alias.casefold() in text for alias in entity.aliases):
                if parent.parent.id not in selected_ids:
                    selected.append(parent)
                    selected_ids.add(parent.parent.id)
                break
    for parent in parents:
        if parent.parent.id not in selected_ids:
            selected.append(parent)
            selected_ids.add(parent.parent.id)
    return tuple(selected[:top_k])
