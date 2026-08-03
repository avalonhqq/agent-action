from pathlib import Path

from bili_support.intent.types import BusinessDomain
from bili_support.knowledge.dictionary import DictionaryTermStatus
from bili_support.knowledge.dictionary_seed import load_dictionary_terms


def test_dictionary_seed_fixture_covers_all_business_domains() -> None:
    terms = load_dictionary_terms(Path("data/fixtures/dictionary_terms_v1.json"))

    assert len(terms) == 48
    assert {item.business_domain for item in terms} == set(BusinessDomain)
    assert all(item.term.strip() for item in terms)
    assert all(item.frequency >= 6000 for item in terms)


def test_dictionary_seed_payloads_are_candidates_by_service_contract() -> None:
    # Fixture故意不包含状态：create_candidate统一赋值candidate，不能批量绕过审核。
    terms = load_dictionary_terms(Path("data/fixtures/dictionary_terms_v1.json"))

    assert DictionaryTermStatus.CANDIDATE.value == "candidate"
    assert all("status" not in item.model_dump() for item in terms)
