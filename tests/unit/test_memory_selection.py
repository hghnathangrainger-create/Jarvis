"""
test_memory_selection.py

Unit tests for ai/memory_selection.py's deterministic query-based
selection primitive, select_memory_ids_by_query() / QuerySelectionResult
(Phase 11, Batch 1).

These prove:
    - MemoryManager.search() is called exactly once, with the fixed Phase
      11 selection ceiling (limit=10) explicitly - never the store's own
      default of 20, and never a larger candidate pool later reduced.
    - The exact order MemoryManager.search()/EpisodicMemoryStore.search()
      returns is preserved - no numeric sort, no re-sort, no reordering
      for any reason.
    - Real, unmodified search semantics are preserved and exercised
      through the genuine MemoryManager/EpisodicMemoryStore/SQLite stack,
      not a mock: content-only matching, case-insensitivity, ordinary
      literal text, `%`/`_` LIKE wildcard behaviour, and quote/SQL-like
      query input remaining safely parameterised data rather than SQL
      structure (proving store integrity survives, not merely that no
      exception was raised).
    - Zero matches and a genuine search-layer exception are represented as
      two distinct QuerySelectionResult states, never collapsed into one.
    - QuerySelectionResult's own construction invariant (never both
      selected_ids and error) is enforced.
    - This module never imports or references Phase 10 ingestion
      (ingest_memories_for_ai/MemorySetIngestionResult/AIContextBlock) or
      any AI-reasoning component (AIReasoningEngine/AIRouter/
      PromptBuilder) - selection and ingestion/reasoning remain separate,
      by construction.

Run with:
    pytest tests/unit/test_memory_selection.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

import ai.memory_selection as memory_selection_module
from ai.memory_selection import (
    CategorySelectionResult,
    QuerySelectionResult,
    RecentCountSelectionResult,
    RecentSelectionResult,
    select_memory_ids_by_category,
    select_memory_ids_by_query,
    select_recent_memory_ids,
    select_recent_memory_ids_by_count,
)
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from memory.memory_models import KNOWN_CATEGORIES


class _SpyMemoryManager:
    """Wraps a real MemoryManager, recording the exact args every search()
    call received, without changing real search behaviour."""

    def __init__(self, real: MemoryManager) -> None:
        self._real = real
        self.search_calls: list[tuple[str, int]] = []

    def search(self, query: str, limit: int = 20, **kwargs: object):
        self.search_calls.append((query, limit))
        return self._real.search(query, limit=limit, **kwargs)


class _RaisingMemoryManager:
    """Simulates a genuine search-layer exception."""

    def search(self, query: str, limit: int = 20, **kwargs: object):
        raise RuntimeError("simulated database failure")


@pytest.fixture()
def memory_manager() -> MemoryManager:
    """Build a MemoryManager backed by a fresh in-memory database."""
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _save(memory_manager: MemoryManager, content: str, **kwargs: object) -> int:
    record = memory_manager.save(content=content, **kwargs)
    assert record is not None
    return record.id


# --- Successful selection, exact ids, order preservation --------------------


def test_successful_selection_returns_matching_ids(
    memory_manager: MemoryManager,
) -> None:
    id_a = _save(memory_manager, "Notes about the Jarvis security review")
    _save(memory_manager, "Unrelated grocery list")
    id_c = _save(memory_manager, "Follow-up on the Jarvis security review")

    result = select_memory_ids_by_query(memory_manager, "security review")

    assert result.success
    assert not result.zero_matches
    assert not result.failed
    assert result.error is None
    assert set(result.selected_ids) == {id_a, id_c}


def test_search_result_order_is_preserved_not_sorted(
    memory_manager: MemoryManager,
) -> None:
    # Saved in ascending id order; the store's own contract orders
    # results created_at DESC, id DESC - i.e. reverse of insertion order.
    id_a = _save(memory_manager, "alpha budget note")
    id_b = _save(memory_manager, "beta budget note")
    id_c = _save(memory_manager, "gamma budget note")

    result = select_memory_ids_by_query(memory_manager, "budget")

    assert result.selected_ids == (id_c, id_b, id_a)


def test_no_numeric_reordering_of_selected_ids(
    memory_manager: MemoryManager,
) -> None:
    # If the primitive ever sorted numerically, this would come back
    # ascending; the real store's created_at/id DESC order is descending.
    ids = [_save(memory_manager, f"reorder-check entry {i}") for i in range(5)]

    result = select_memory_ids_by_query(memory_manager, "reorder-check")

    assert result.selected_ids == tuple(reversed(ids))
    assert result.selected_ids != tuple(sorted(result.selected_ids))


# --- Explicit limit=10 behaviour, never the store's default of 20 -----------


def test_explicit_limit_of_ten_is_passed_to_search(
    memory_manager: MemoryManager,
) -> None:
    spy = _SpyMemoryManager(memory_manager)
    for i in range(3):
        _save(memory_manager, f"limit-check entry {i}")

    select_memory_ids_by_query(spy, "limit-check")

    assert spy.search_calls == [("limit-check", 10)]


def test_more_than_ten_matches_are_capped_at_ten_newest(
    memory_manager: MemoryManager,
) -> None:
    ids = [_save(memory_manager, f"ceiling-check entry {i}") for i in range(11)]

    result = select_memory_ids_by_query(memory_manager, "ceiling-check")

    assert len(result.selected_ids) == 10
    # created_at DESC, id DESC: the ten highest ids, newest first - the
    # single oldest/lowest id (ids[0]) is excluded, never a differently
    # chosen subset and never resorted.
    assert result.selected_ids == tuple(reversed(ids))[:10]
    assert ids[0] not in result.selected_ids


def test_does_not_retrieve_a_larger_candidate_pool_then_slice(
    memory_manager: MemoryManager,
) -> None:
    spy = _SpyMemoryManager(memory_manager)
    for i in range(15):
        _save(memory_manager, f"pool-check entry {i}")

    select_memory_ids_by_query(spy, "pool-check")

    # Exactly one search() call, with limit=10 - never limit=20 (the
    # store's own default) and never a larger pool later reduced.
    assert spy.search_calls == [("pool-check", 10)]


# --- Content-only matching, case-insensitivity, ordinary literal text -------


def test_matches_content_only_not_category_or_source(
    memory_manager: MemoryManager,
) -> None:
    matching_id = _save(memory_manager, "the quarterly project plan")
    off_topic_id = _save(
        memory_manager, "something unrelated entirely", category="project"
    )

    result = select_memory_ids_by_query(memory_manager, "project")

    assert matching_id in result.selected_ids
    assert off_topic_id not in result.selected_ids


def test_case_insensitive_matching(memory_manager: MemoryManager) -> None:
    memory_id = _save(memory_manager, "Hello World, this is a Test")

    result = select_memory_ids_by_query(memory_manager, "HELLO world")

    assert result.selected_ids == (memory_id,)


def test_ordinary_literal_text_matches_only_its_substring(
    memory_manager: MemoryManager,
) -> None:
    matching_id = _save(memory_manager, "the cat sat on the mat")
    _save(memory_manager, "completely different content")

    result = select_memory_ids_by_query(memory_manager, "cat sat")

    assert result.selected_ids == (matching_id,)


# --- Wildcard behaviour: %/_ retain LIKE meaning, unescaped -----------------


def test_percent_wildcard_matches_broadly_not_literally(
    memory_manager: MemoryManager,
) -> None:
    id_a = _save(memory_manager, "first entry")
    id_b = _save(memory_manager, "second entry")
    id_c = _save(memory_manager, "third entry")

    # "%" alone becomes the ILIKE pattern "%%%", which matches any
    # non-empty content - proving % is NOT escaped and keeps its SQL LIKE
    # wildcard meaning rather than being treated as a literal character.
    result = select_memory_ids_by_query(memory_manager, "%")

    assert result.success
    assert {id_a, id_b, id_c} <= set(result.selected_ids)


def test_underscore_wildcard_matches_any_single_character(
    memory_manager: MemoryManager,
) -> None:
    cat_id = _save(memory_manager, "cat")
    hat_id = _save(memory_manager, "hat")
    # Too short to contain a (single-char + "at") substring at all.
    _save(memory_manager, "at")

    # "_at" becomes the ILIKE pattern "%_at%": any sequence, then any
    # single character, then the literal "at" - matching "cat"/"hat" (a
    # preceding character + "at") but not bare "at" (no preceding
    # character to satisfy "_"). Proves `_` is not escaped.
    result = select_memory_ids_by_query(memory_manager, "_at")

    assert set(result.selected_ids) == {cat_id, hat_id}


# --- Quote / SQL-metacharacter input: parameterised, non-injective ----------


def test_quote_containing_query_matches_as_literal_data(
    memory_manager: MemoryManager,
) -> None:
    memory_id = _save(memory_manager, "Nathan's meeting notes for Friday")

    result = select_memory_ids_by_query(memory_manager, "Nathan's meeting")

    assert result.selected_ids == (memory_id,)


def test_sql_like_query_does_not_alter_query_structure_or_store_integrity(
    memory_manager: MemoryManager,
) -> None:
    survivor_id = _save(memory_manager, "a memory that must survive")

    malicious_query = "'; DROP TABLE episodic_memories; --"
    result = select_memory_ids_by_query(memory_manager, malicious_query)

    # No exception, and (correctly) nothing matches this literal string.
    assert result.zero_matches
    assert result.error is None

    # Store integrity proof: the table was not dropped and the previously
    # saved record is still retrievable through an ordinary search - a
    # real, observed-behaviour proof, not just an absence of exceptions.
    assert memory_manager.count() >= 1
    follow_up = select_memory_ids_by_query(memory_manager, "must survive")
    assert follow_up.selected_ids == (survivor_id,)


def test_sql_metacharacter_query_is_parameterized_not_concatenated(
    memory_manager: MemoryManager,
) -> None:
    # A classic always-true injection payload. If the query were ever
    # string-concatenated into raw SQL instead of bound as a parameter,
    # this would return every row regardless of content. Parameterised
    # ILIKE treats it as a literal (non-matching) substring instead.
    _save(memory_manager, "ordinary content one")
    _save(memory_manager, "ordinary content two")

    result = select_memory_ids_by_query(memory_manager, "' OR '1'='1")

    assert result.zero_matches


# --- Zero matches vs. search failure: two distinct, non-collapsed states ---


def test_zero_matches_is_distinct_from_failure(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "something entirely unrelated")

    result = select_memory_ids_by_query(memory_manager, "no such term exists")

    assert result.zero_matches
    assert not result.failed
    assert not result.success
    assert result.selected_ids == ()
    assert result.error is None


def test_search_exception_is_represented_as_failed_not_zero_matches() -> None:
    result = select_memory_ids_by_query(_RaisingMemoryManager(), "anything")

    assert result.failed
    assert not result.zero_matches
    assert not result.success
    assert result.selected_ids == ()
    assert result.error == "Could not search stored memories right now."


def test_empty_query_relies_on_search_own_handling_yields_zero_matches(
    memory_manager: MemoryManager,
) -> None:
    # Documents and proves the Batch 1 precondition: this primitive does
    # not itself reject an empty/whitespace query - it relies on
    # MemoryManager.search()'s own existing behaviour (return [] for an
    # empty/whitespace query), which this test exercises through the real
    # store rather than merely asserting the design intent in prose.
    result = select_memory_ids_by_query(memory_manager, "   ")

    assert result.zero_matches
    assert not result.failed
    assert result.selected_ids == ()


# --- QuerySelectionResult invariants -----------------------------------------


def test_result_rejects_error_and_selected_ids_together() -> None:
    with pytest.raises(ValueError):
        QuerySelectionResult(selected_ids=(1, 2), error="boom")


def test_result_default_construction_is_zero_matches() -> None:
    result = QuerySelectionResult()

    assert result.zero_matches
    assert not result.success
    assert not result.failed


def test_query_length_reflects_supplied_query_without_retaining_it(
    memory_manager: MemoryManager,
) -> None:
    query = "a fairly specific search phrase"

    result = select_memory_ids_by_query(memory_manager, query)

    assert result.query_length == len(query)
    # The result object carries no attribute holding the raw query text.
    assert not hasattr(result, "query")


# --- No duplicate ids from a genuine multi-match search ---------------------


def test_no_duplicate_ids_across_multiple_real_matches(
    memory_manager: MemoryManager,
) -> None:
    # The store performs a single, non-joining filter over one table
    # (memory/episodic_memory.py), so a matching row can never be
    # returned more than once - proven here directly rather than
    # simulating an artificial duplicate scenario the real store cannot
    # produce.
    ids = [_save(memory_manager, f"dup-check shared term {i}") for i in range(6)]

    result = select_memory_ids_by_query(memory_manager, "dup-check shared term")

    assert len(result.selected_ids) == len(set(result.selected_ids))
    assert set(result.selected_ids) == set(ids)


# --- No Phase 10 ingestion or AI/provider involvement ------------------------


def test_module_does_not_reference_phase_10_ingestion() -> None:
    assert not hasattr(memory_selection_module, "ingest_memories_for_ai")
    assert not hasattr(memory_selection_module, "ingest_memory_for_ai")
    assert not hasattr(memory_selection_module, "MemorySetIngestionResult")
    assert not hasattr(memory_selection_module, "AIContextBlock")


def test_module_does_not_reference_ai_reasoning_components() -> None:
    assert not hasattr(memory_selection_module, "AIReasoningEngine")
    assert not hasattr(memory_selection_module, "AIRouter")
    assert not hasattr(memory_selection_module, "PromptBuilder")


def test_does_not_call_ingestion_or_ai_during_selection(
    memory_manager: MemoryManager,
) -> None:
    # A behavioural proof alongside the structural one above: selection
    # completes and returns without any ingestion/AI collaborator ever
    # being supplied or needed.
    _save(memory_manager, "a memory for the no-ingestion proof")

    result = select_memory_ids_by_query(memory_manager, "no-ingestion proof")

    assert result.success
    assert isinstance(result, QuerySelectionResult)


# =============================================================================
# Category-based selection (Phase 12, Batch 1)
# =============================================================================


class _CategorySpyMemoryManager:
    """Wraps a real MemoryManager, recording every (category, limit)
    list_by_category() call received, without changing real behaviour."""

    def __init__(self, real: MemoryManager) -> None:
        self._real = real
        self.list_by_category_calls: list[tuple[str, int]] = []

    def list_by_category(self, category: str, limit: int = 20):
        self.list_by_category_calls.append((category, limit))
        return self._real.list_by_category(category, limit=limit)


class _RaisingCategoryMemoryManager:
    """Simulates a genuine category-lookup exception."""

    def list_by_category(self, category: str, limit: int = 20):
        raise RuntimeError("simulated database failure")


# --- Successful selection, canonicalization, order preservation -------------


def test_successful_category_selection_returns_matching_ids(
    memory_manager: MemoryManager,
) -> None:
    id_a = _save(memory_manager, "Project note one", category="project")
    id_b = _save(memory_manager, "Project note two", category="project")
    _save(memory_manager, "Personal note", category="personal")

    result = select_memory_ids_by_category(memory_manager, "project")

    assert result.success
    assert not result.zero_matches
    assert not result.invalid_category
    assert not result.failed
    assert result.error is None
    assert result.category == "project"
    assert set(result.selected_ids) == {id_a, id_b}


@pytest.mark.parametrize("category", list(KNOWN_CATEGORIES))
def test_every_supported_category_is_selectable(
    memory_manager: MemoryManager, category: str
) -> None:
    memory_id = _save(memory_manager, f"a {category} memory", category=category)

    result = select_memory_ids_by_category(memory_manager, category)

    assert result.success
    assert result.category == category
    assert result.selected_ids == (memory_id,)


def test_category_result_order_is_preserved_not_sorted(
    memory_manager: MemoryManager,
) -> None:
    id_a = _save(memory_manager, "alpha project note", category="project")
    id_b = _save(memory_manager, "beta project note", category="project")
    id_c = _save(memory_manager, "gamma project note", category="project")

    result = select_memory_ids_by_category(memory_manager, "project")

    assert result.selected_ids == (id_c, id_b, id_a)


def test_category_no_numeric_reordering_of_selected_ids(
    memory_manager: MemoryManager,
) -> None:
    ids = [
        _save(memory_manager, f"reorder-check {i}", category="note")
        for i in range(5)
    ]

    result = select_memory_ids_by_category(memory_manager, "note")

    assert result.selected_ids == tuple(reversed(ids))
    assert result.selected_ids != tuple(sorted(result.selected_ids))


def test_category_isolation_project_records_excluded_from_personal(
    memory_manager: MemoryManager,
) -> None:
    project_id = _save(memory_manager, "project only content", category="project")
    personal_id = _save(memory_manager, "personal only content", category="personal")

    project_result = select_memory_ids_by_category(memory_manager, "project")
    personal_result = select_memory_ids_by_category(memory_manager, "personal")

    assert project_result.selected_ids == (project_id,)
    assert personal_id not in project_result.selected_ids
    assert personal_result.selected_ids == (personal_id,)
    assert project_id not in personal_result.selected_ids


def test_returned_ids_correspond_exactly_to_saved_records(
    memory_manager: MemoryManager,
) -> None:
    saved_ids = {
        _save(memory_manager, f"preference entry {i}", category="preference")
        for i in range(4)
    }

    result = select_memory_ids_by_category(memory_manager, "preference")

    assert set(result.selected_ids) == saved_ids


# --- Canonicalization: case variants, whitespace -----------------------------


def test_uppercase_category_canonicalizes_to_lowercase(
    memory_manager: MemoryManager,
) -> None:
    memory_id = _save(memory_manager, "uppercase test", category="project")

    result = select_memory_ids_by_category(memory_manager, "PROJECT")

    assert result.success
    assert result.category == "project"
    assert result.selected_ids == (memory_id,)


@pytest.mark.parametrize(
    "variant", ["Project", "PROJECT", "  project  ", "Project ", " PROJECT"]
)
def test_accepted_case_and_whitespace_variants_canonicalize_identically(
    memory_manager: MemoryManager, variant: str
) -> None:
    memory_id = _save(memory_manager, "variant test", category="project")

    result = select_memory_ids_by_category(memory_manager, variant)

    assert result.success
    assert result.category == "project"
    assert result.selected_ids == (memory_id,)


def test_category_field_holds_canonical_value_not_raw_spelling(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "canonical check", category="note")

    result = select_memory_ids_by_category(memory_manager, "  NOTE  ")

    assert result.category == "note"
    assert result.category != "  NOTE  "


# --- Fixed limit=10, exact call count, no candidate-pool reduction ---------


def test_explicit_limit_of_ten_is_passed_to_list_by_category(
    memory_manager: MemoryManager,
) -> None:
    spy = _CategorySpyMemoryManager(memory_manager)
    for i in range(3):
        _save(memory_manager, f"limit-check {i}", category="project")

    select_memory_ids_by_category(spy, "project")

    assert spy.list_by_category_calls == [("project", 10)]


def test_more_than_ten_category_matches_are_capped_at_ten_newest(
    memory_manager: MemoryManager,
) -> None:
    ids = [
        _save(memory_manager, f"ceiling-check {i}", category="project")
        for i in range(11)
    ]

    result = select_memory_ids_by_category(memory_manager, "project")

    assert len(result.selected_ids) == 10
    assert result.selected_ids == tuple(reversed(ids))[:10]
    assert ids[0] not in result.selected_ids


def test_does_not_retrieve_a_larger_category_pool_then_slice(
    memory_manager: MemoryManager,
) -> None:
    spy = _CategorySpyMemoryManager(memory_manager)
    for i in range(15):
        _save(memory_manager, f"pool-check {i}", category="project")

    select_memory_ids_by_category(spy, "project")

    # Exactly one list_by_category() call, with limit=10 - never limit=20
    # (the store's own default) and never a larger pool later reduced.
    assert spy.list_by_category_calls == [("project", 10)]


# --- Invalid-category correctness invariant ---------------------------------


def test_unknown_category_is_rejected_without_any_lookup(
    memory_manager: MemoryManager,
) -> None:
    spy = _CategorySpyMemoryManager(memory_manager)
    _save(memory_manager, "a general memory", category="general")

    result = select_memory_ids_by_category(spy, "spaceships")

    assert result.invalid_category
    assert not result.success
    assert not result.zero_matches
    assert not result.failed
    assert result.category is None
    assert result.selected_ids == ()
    assert result.error is None
    # The critical proof: no lookup was ever attempted, so
    # normalize_category()'s silent "general" fallback never had an
    # opportunity to fire, and "general" content was never selected.
    assert spy.list_by_category_calls == []


def test_unknown_category_does_not_select_general_records(
    memory_manager: MemoryManager,
) -> None:
    general_id = _save(memory_manager, "general content", category="general")

    result = select_memory_ids_by_category(memory_manager, "spaceships")

    assert result.invalid_category
    assert general_id not in result.selected_ids
    assert result.selected_ids == ()


@pytest.mark.parametrize(
    "invalid_input",
    ["", "   ", "project.", "spaceships", "SYSTEM", "JARVIS_TRUSTED", "!!!"],
)
def test_invalid_or_prompt_like_category_input_is_rejected(
    memory_manager: MemoryManager, invalid_input: str
) -> None:
    result = select_memory_ids_by_category(memory_manager, invalid_input)

    assert result.invalid_category
    assert result.category is None
    assert result.selected_ids == ()
    assert result.error is None


def test_empty_string_direct_call_resolves_to_invalid_category(
    memory_manager: MemoryManager,
) -> None:
    result = select_memory_ids_by_category(memory_manager, "")

    assert result.invalid_category
    assert not result.zero_matches
    assert not result.failed


def test_whitespace_only_direct_call_resolves_to_invalid_category(
    memory_manager: MemoryManager,
) -> None:
    result = select_memory_ids_by_category(memory_manager, "   ")

    assert result.invalid_category
    assert not result.zero_matches
    assert not result.failed


# --- Zero records vs. invalid category vs. lookup failure -------------------


def test_valid_category_with_zero_records(memory_manager: MemoryManager) -> None:
    result = select_memory_ids_by_category(memory_manager, "preference")

    assert result.zero_matches
    assert not result.success
    assert not result.invalid_category
    assert not result.failed
    assert result.category == "preference"
    assert result.selected_ids == ()
    assert result.error is None


def test_category_lookup_exception_is_represented_as_failed() -> None:
    result = select_memory_ids_by_category(
        _RaisingCategoryMemoryManager(), "project"
    )

    assert result.failed
    assert not result.success
    assert not result.zero_matches
    assert not result.invalid_category
    assert result.category == "project"
    assert result.selected_ids == ()
    assert result.error == "Could not look up stored memories by category right now."


def test_zero_matches_and_invalid_category_and_failed_are_all_distinct(
    memory_manager: MemoryManager,
) -> None:
    zero_result = select_memory_ids_by_category(memory_manager, "note")
    invalid_result = select_memory_ids_by_category(memory_manager, "spaceships")
    failed_result = select_memory_ids_by_category(
        _RaisingCategoryMemoryManager(), "note"
    )

    assert zero_result.zero_matches and not zero_result.invalid_category and not zero_result.failed
    assert invalid_result.invalid_category and not invalid_result.zero_matches and not invalid_result.failed
    assert failed_result.failed and not failed_result.zero_matches and not failed_result.invalid_category


# --- CategorySelectionResult invariants -------------------------------------


def test_invalid_category_result_rejects_coexisting_error() -> None:
    with pytest.raises(ValueError):
        CategorySelectionResult(invalid_category=True, error="boom")


def test_invalid_category_result_rejects_coexisting_selected_ids() -> None:
    with pytest.raises(ValueError):
        CategorySelectionResult(invalid_category=True, selected_ids=(1, 2))


def test_invalid_category_result_rejects_coexisting_category() -> None:
    with pytest.raises(ValueError):
        CategorySelectionResult(invalid_category=True, category="project")


def test_non_invalid_result_requires_a_category() -> None:
    with pytest.raises(ValueError):
        CategorySelectionResult(selected_ids=(1,))


def test_result_rejects_error_and_selected_ids_together() -> None:
    with pytest.raises(ValueError):
        CategorySelectionResult(category="project", selected_ids=(1, 2), error="boom")


def test_all_defaults_construction_is_incoherent_and_rejected() -> None:
    # Plain CategorySelectionResult() defaults to invalid_category=False
    # and category=None - an incoherent combination (every non-invalid
    # state requires a canonical category), so it must raise rather than
    # silently construct a meaningless "successful" empty result. The only
    # way to construct a valid, all-empty-fields result is explicitly
    # passing invalid_category=True (proven by
    # test_unknown_category_is_rejected_without_any_lookup above, which
    # exercises that exact construction via the real selector function).
    with pytest.raises(ValueError):
        CategorySelectionResult()


# --- No Phase 10 ingestion or AI/provider involvement (category path) ------


def test_does_not_call_ingestion_or_ai_during_category_selection(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "a memory for the no-ingestion proof", category="note")

    result = select_memory_ids_by_category(memory_manager, "note")

    assert result.success
    assert isinstance(result, CategorySelectionResult)


def test_no_duplicate_ids_across_multiple_real_category_matches(
    memory_manager: MemoryManager,
) -> None:
    # The store performs a single, non-joining filter over one table, so a
    # matching row can never be returned more than once - proven here
    # directly rather than simulating an artificial duplicate scenario the
    # real store cannot produce.
    ids = [
        _save(memory_manager, f"dup-check {i}", category="project")
        for i in range(6)
    ]

    result = select_memory_ids_by_category(memory_manager, "project")

    assert len(result.selected_ids) == len(set(result.selected_ids))
    assert set(result.selected_ids) == set(ids)


# =============================================================================
# Recency-based selection (Phase 13, Batch 1)
# =============================================================================


class _RecentSpyMemoryManager:
    """Wraps a real MemoryManager, recording every list_recent() call
    received, without changing real behaviour."""

    def __init__(self, real: MemoryManager) -> None:
        self._real = real
        self.list_recent_calls: list[int] = []

    def list_recent(self, limit: int = 20, **kwargs: object):
        self.list_recent_calls.append(limit)
        return self._real.list_recent(limit=limit, **kwargs)


class _RaisingRecentMemoryManager:
    """Simulates a genuine list_recent()-layer exception."""

    def list_recent(self, limit: int = 20, **kwargs: object):
        raise RuntimeError("simulated database failure")


# --- Successful selection, exact ids, order preservation -------------------


def test_successful_recent_selection_returns_newest_ids(
    memory_manager: MemoryManager,
) -> None:
    id_a = _save(memory_manager, "first memory")
    id_b = _save(memory_manager, "second memory")
    id_c = _save(memory_manager, "third memory")

    result = select_recent_memory_ids(memory_manager)

    assert result.success
    assert not result.zero_matches
    assert not result.failed
    assert result.error is None
    assert result.selected_ids == (id_c, id_b, id_a)


def test_recent_result_order_is_preserved_newest_first_not_reversed(
    memory_manager: MemoryManager,
) -> None:
    # Saved in ascending id order; the store's own contract orders results
    # created_at DESC, id DESC - i.e. newest first, the reverse of
    # insertion order. The selector must not reverse this back into
    # chronological (oldest-first) order for any reason.
    ids = [_save(memory_manager, f"chronology entry {i}") for i in range(5)]

    result = select_recent_memory_ids(memory_manager)

    assert result.selected_ids == tuple(reversed(ids))


def test_recent_no_numeric_reordering_of_selected_ids(
    memory_manager: MemoryManager,
) -> None:
    ids = [_save(memory_manager, f"reorder-check entry {i}") for i in range(5)]

    result = select_recent_memory_ids(memory_manager)

    assert result.selected_ids == tuple(reversed(ids))
    assert result.selected_ids != tuple(sorted(result.selected_ids))


# --- Explicit limit=10 behaviour, never the store's default of 20 ----------


def test_explicit_limit_of_ten_is_passed_to_list_recent(
    memory_manager: MemoryManager,
) -> None:
    spy = _RecentSpyMemoryManager(memory_manager)
    for i in range(3):
        _save(memory_manager, f"limit-check entry {i}")

    select_recent_memory_ids(spy)

    assert spy.list_recent_calls == [10]


def test_more_than_ten_recent_records_are_capped_at_ten_newest(
    memory_manager: MemoryManager,
) -> None:
    ids = [_save(memory_manager, f"ceiling-check entry {i}") for i in range(11)]

    result = select_recent_memory_ids(memory_manager)

    assert len(result.selected_ids) == 10
    # created_at DESC, id DESC: the ten highest ids, newest first - the
    # single oldest/lowest id (ids[0]) is excluded, never a differently
    # chosen subset and never resorted.
    assert result.selected_ids == tuple(reversed(ids))[:10]
    assert ids[0] not in result.selected_ids


def test_does_not_retrieve_a_larger_recent_pool_then_slice(
    memory_manager: MemoryManager,
) -> None:
    spy = _RecentSpyMemoryManager(memory_manager)
    for i in range(15):
        _save(memory_manager, f"pool-check entry {i}")

    select_recent_memory_ids(spy)

    # Exactly one list_recent() call, with limit=10 - never limit=20 (the
    # store's own default) and never a larger pool later reduced.
    assert spy.list_recent_calls == [10]


# --- Across-all-categories behaviour: recency is not category selection ----


def test_recent_selection_spans_multiple_categories_by_recency_order(
    memory_manager: MemoryManager,
) -> None:
    older_project_id = _save(
        memory_manager, "older project memory", category="project"
    )
    newer_note_id = _save(memory_manager, "newer note memory", category="note")

    result = select_recent_memory_ids(memory_manager)

    # The newer note is eligible before the older project record solely
    # because recency is newest-first across all categories - never
    # grouped, quota'd, or prioritised by category.
    assert result.selected_ids == (newer_note_id, older_project_id)


def test_recent_selection_does_not_group_or_prioritize_by_category(
    memory_manager: MemoryManager,
) -> None:
    ids = []
    for i, category in enumerate(KNOWN_CATEGORIES):
        ids.append(_save(memory_manager, f"entry {i}", category=category))

    result = select_recent_memory_ids(memory_manager)

    # Saved in KNOWN_CATEGORIES order; newest-first means the reverse of
    # insertion order, regardless of which category each entry carries.
    assert result.selected_ids == tuple(reversed(ids))


def test_recent_selection_does_not_reuse_category_selector(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "a project memory", category="project")

    result = select_recent_memory_ids(memory_manager)

    # The result type itself proves this is the recency primitive, not a
    # category lookup in disguise - CategorySelectionResult carries a
    # `category` field this result never has.
    assert isinstance(result, RecentSelectionResult)
    assert not hasattr(result, "category")


def test_content_differences_do_not_influence_recent_selection(
    memory_manager: MemoryManager,
) -> None:
    # Deliberately dissimilar content, categories, and sources - only
    # save order (and therefore created_at/id) should determine selection.
    id_a = _save(memory_manager, "zzz alpha", category="personal", source="tool")
    id_b = _save(memory_manager, "aaa beta", category="project", source="conversation")
    id_c = _save(memory_manager, "mmm gamma", category="note", source="tool")

    result = select_recent_memory_ids(memory_manager)

    assert result.selected_ids == (id_c, id_b, id_a)


def test_returned_recent_ids_exactly_match_list_recent_records(
    memory_manager: MemoryManager,
) -> None:
    ids = [_save(memory_manager, f"exact-match entry {i}") for i in range(4)]

    result = select_recent_memory_ids(memory_manager)
    direct = memory_manager.list_recent(limit=10)

    assert result.selected_ids == tuple(record.id for record in direct)
    assert set(result.selected_ids) == set(ids)


# --- Zero records vs. lookup failure: two distinct, non-collapsed states ---


def test_zero_records_is_zero_matches_not_failure(
    memory_manager: MemoryManager,
) -> None:
    result = select_recent_memory_ids(memory_manager)

    assert result.zero_matches
    assert not result.failed
    assert not result.success
    assert result.selected_ids == ()
    assert result.error is None


def test_list_recent_exception_is_represented_as_failed() -> None:
    result = select_recent_memory_ids(_RaisingRecentMemoryManager())

    assert result.failed
    assert not result.zero_matches
    assert not result.success
    assert result.selected_ids == ()
    assert result.error == "Could not look up recent stored memories right now."
    # The raised exception's own text is never embedded in the result.
    assert "simulated database failure" not in (result.error or "")


# --- RecentSelectionResult invariants ---------------------------------------


def test_recent_result_rejects_error_and_selected_ids_together() -> None:
    with pytest.raises(ValueError):
        RecentSelectionResult(selected_ids=(1, 2), error="boom")


def test_recent_result_default_construction_is_zero_matches() -> None:
    result = RecentSelectionResult()

    assert result.zero_matches
    assert not result.success
    assert not result.failed


def test_recent_result_match_count_reflects_selected_ids_cardinality(
    memory_manager: MemoryManager,
) -> None:
    for i in range(4):
        _save(memory_manager, f"match-count entry {i}")

    result = select_recent_memory_ids(memory_manager)

    assert result.match_count == len(result.selected_ids) == 4


# --- Timestamp and tie-breaking proof ----------------------------------------


def test_created_at_is_utc_valued_though_sqlite_returns_it_naive(
    memory_manager: MemoryManager,
) -> None:
    before = datetime.now(timezone.utc)
    memory_id = _save(memory_manager, "timestamp check")
    after = datetime.now(timezone.utc)

    record = memory_manager.get(memory_id)

    assert record is not None
    # storage/models.py's _utc_now() stamps an aware UTC datetime at write
    # time (its own docstring: "timezone-aware UTC datetime"), but this
    # repository's SQLite backend does not preserve tzinfo on round-trip -
    # EpisodicMemoryStore returns a *naive* datetime whose numeric value is
    # still UTC. This test proves the actually-observed round-trip
    # behaviour rather than assuming the model docstring's
    # "timezone-aware" claim survives storage. Recency ordering itself is
    # unaffected either way, since SQL ORDER BY compares the same column
    # representation on both sides of every comparison.
    assert record.created_at.tzinfo is None
    stamped_at_utc = record.created_at.replace(tzinfo=timezone.utc)
    assert before - timedelta(seconds=5) <= stamped_at_utc <= after + timedelta(seconds=5)


def test_equal_created_at_records_are_ordered_by_id_desc() -> None:
    from sqlalchemy import create_engine

    from storage.database import (
        create_session_factory,
        initialize_database,
        session_scope,
    )
    from storage.models import EpisodicMemory

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    manager = MemoryManager(EpisodicMemoryStore(factory))

    id_a = _save(manager, "tie-break entry A")
    id_b = _save(manager, "tie-break entry B")

    # Force both records to share the exact same created_at, using the
    # same repository ORM model/session seam production code already
    # writes through - not a new clock abstraction, just a direct proof
    # of the store's own id DESC tie-break contract for genuinely equal
    # timestamps.
    shared_timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with session_scope(factory) as db:
        for memory_id in (id_a, id_b):
            entry = db.get(EpisodicMemory, memory_id)
            entry.created_at = shared_timestamp

    result = select_recent_memory_ids(manager)

    # Both records now share an identical created_at; id DESC breaks the
    # tie deterministically - the higher id (inserted later) sorts first.
    assert result.selected_ids.index(id_b) < result.selected_ids.index(id_a)


# --- No duplicate ids from a genuine multi-record lookup --------------------


def test_no_duplicate_ids_across_multiple_real_recent_records(
    memory_manager: MemoryManager,
) -> None:
    # The store performs a single, non-joining query over one table
    # (memory/episodic_memory.py), so a row can never be returned more
    # than once - proven here directly rather than simulating an
    # artificial duplicate scenario the real store cannot produce.
    ids = [_save(memory_manager, f"dup-check entry {i}") for i in range(6)]

    result = select_recent_memory_ids(memory_manager)

    assert len(result.selected_ids) == len(set(result.selected_ids))
    assert set(result.selected_ids) == set(ids)


# --- No Phase 10 ingestion or AI/provider involvement (recent path) --------


def test_does_not_call_ingestion_or_ai_during_recent_selection(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "a memory for the no-ingestion proof")

    result = select_recent_memory_ids(memory_manager)

    assert result.success
    assert isinstance(result, RecentSelectionResult)


# =============================================================================
# Count-based recency selection (Phase 14, Batch 1)
# =============================================================================


# --- RecentCountSelectionResult invariants -----------------------------------


def test_count_result_success_construction_is_valid(
    memory_manager: MemoryManager,
) -> None:
    result = RecentCountSelectionResult(selected_ids=(1, 2), requested_count=5)

    assert result.success
    assert not result.zero_matches
    assert not result.invalid_count
    assert not result.failed
    assert result.match_count == 2


def test_count_result_zero_matches_construction_is_valid() -> None:
    result = RecentCountSelectionResult(requested_count=5)

    assert result.zero_matches
    assert not result.success
    assert not result.invalid_count
    assert not result.failed
    assert result.selected_ids == ()


def test_count_result_invalid_count_construction_is_valid() -> None:
    result = RecentCountSelectionResult(invalid_count=True)

    assert result.invalid_count
    assert not result.success
    assert not result.zero_matches
    assert not result.failed
    assert result.requested_count is None
    assert result.selected_ids == ()
    assert result.error is None


def test_count_result_failed_construction_is_valid() -> None:
    result = RecentCountSelectionResult(requested_count=5, error="boom")

    assert result.failed
    assert not result.success
    assert not result.zero_matches
    assert not result.invalid_count
    assert result.selected_ids == ()


def test_count_result_invalid_count_rejects_coexisting_error() -> None:
    with pytest.raises(ValueError):
        RecentCountSelectionResult(invalid_count=True, error="boom")


def test_count_result_invalid_count_rejects_coexisting_selected_ids() -> None:
    with pytest.raises(ValueError):
        RecentCountSelectionResult(invalid_count=True, selected_ids=(1, 2))


def test_count_result_invalid_count_rejects_coexisting_requested_count() -> None:
    with pytest.raises(ValueError):
        RecentCountSelectionResult(invalid_count=True, requested_count=5)


def test_count_result_non_invalid_requires_a_requested_count() -> None:
    with pytest.raises(ValueError):
        RecentCountSelectionResult(selected_ids=(1,))


def test_count_result_rejects_error_and_selected_ids_together() -> None:
    with pytest.raises(ValueError):
        RecentCountSelectionResult(
            requested_count=5, selected_ids=(1, 2), error="boom"
        )


def test_count_result_all_defaults_construction_is_incoherent_and_rejected() -> None:
    # Plain RecentCountSelectionResult() defaults to invalid_count=False and
    # requested_count=None - an incoherent combination (every non-invalid
    # state requires a validated requested_count), so it must raise rather
    # than silently construct a meaningless "successful" empty result.
    with pytest.raises(ValueError):
        RecentCountSelectionResult()


def test_count_result_match_count_reflects_selected_ids_cardinality() -> None:
    result = RecentCountSelectionResult(
        selected_ids=(1, 2, 3, 4), requested_count=4
    )

    assert result.match_count == 4


# --- Count validation: accepted values ---------------------------------------


def test_count_of_one_is_accepted(memory_manager: MemoryManager) -> None:
    _save(memory_manager, "count-check entry")

    result = select_recent_memory_ids_by_count(memory_manager, "1")

    assert result.success
    assert result.requested_count == 1


def test_count_of_ten_is_accepted(memory_manager: MemoryManager) -> None:
    for i in range(10):
        _save(memory_manager, f"count-check entry {i}")

    result = select_recent_memory_ids_by_count(memory_manager, "10")

    assert result.success
    assert result.requested_count == 10
    assert len(result.selected_ids) == 10


def test_leading_zero_is_accepted(memory_manager: MemoryManager) -> None:
    _save(memory_manager, "leading-zero-check entry")

    result = select_recent_memory_ids_by_count(memory_manager, "05")

    assert result.success
    assert result.requested_count == 5


def test_surrounding_whitespace_is_accepted_after_strip(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "whitespace-check entry")

    result = select_recent_memory_ids_by_count(memory_manager, "  5  ")

    assert result.success
    assert result.requested_count == 5


# --- Count validation: rejected values, never silently clamped -------------


def test_count_of_zero_is_rejected(memory_manager: MemoryManager) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "0")

    assert result.invalid_count
    assert result.requested_count is None
    assert result.selected_ids == ()


def test_count_above_ten_is_rejected_never_clamped(
    memory_manager: MemoryManager,
) -> None:
    for i in range(15):
        _save(memory_manager, f"over-limit-check entry {i}")
    spy = _RecentSpyMemoryManager(memory_manager)

    result = select_recent_memory_ids_by_count(spy, "11")

    assert result.invalid_count
    assert result.requested_count is None
    # The critical proof: no lookup was ever attempted at all, so the
    # count was never silently reinterpreted as 10.
    assert spy.list_recent_calls == []


def test_plus_prefixed_count_is_rejected(memory_manager: MemoryManager) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "+5")

    assert result.invalid_count


def test_negative_count_is_rejected(memory_manager: MemoryManager) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "-5")

    assert result.invalid_count


def test_decimal_count_is_rejected(memory_manager: MemoryManager) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "5.0")

    assert result.invalid_count


def test_embedded_whitespace_count_is_rejected(
    memory_manager: MemoryManager,
) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "5 5")

    assert result.invalid_count


def test_empty_count_text_is_rejected(memory_manager: MemoryManager) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "")

    assert result.invalid_count


def test_whitespace_only_count_text_is_rejected(
    memory_manager: MemoryManager,
) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "   ")

    assert result.invalid_count


def test_non_numeric_count_text_is_rejected(memory_manager: MemoryManager) -> None:
    result = select_recent_memory_ids_by_count(memory_manager, "five")

    assert result.invalid_count


def test_unicode_digit_count_behaviour_matches_existing_repository_semantics(
    memory_manager: MemoryManager,
) -> None:
    """Locks the existing, inherited str.isdigit()/int() behaviour rather
    than guessing at it: a fullwidth Unicode digit is accepted by
    str.isdigit() (and by int()) exactly as it already would be for a
    memory id parsed by core/orchestrator.py's own _parse_memory_id() -
    this is carried-forward repository behaviour, not a new rule invented
    for this function."""
    fullwidth_five = "５"  # U+FF15 FULLWIDTH DIGIT FIVE
    assert fullwidth_five.isdigit()
    assert int(fullwidth_five) == 5
    _save(memory_manager, "unicode-digit-check entry")

    result = select_recent_memory_ids_by_count(memory_manager, fullwidth_five)

    assert result.success
    assert result.requested_count == 5


def test_invalid_count_produces_no_exception_and_no_lookup(
    memory_manager: MemoryManager,
) -> None:
    spy = _RecentSpyMemoryManager(memory_manager)

    result = select_recent_memory_ids_by_count(spy, "not-a-count")

    assert result.invalid_count
    assert spy.list_recent_calls == []


# --- Delegation to select_recent_memory_ids(): exactly once, limit=count ---


def test_valid_count_delegates_exactly_once_with_matching_limit(
    memory_manager: MemoryManager,
) -> None:
    for i in range(6):
        _save(memory_manager, f"delegation-check entry {i}")
    spy = _RecentSpyMemoryManager(memory_manager)

    select_recent_memory_ids_by_count(spy, "3")

    assert spy.list_recent_calls == [3]


def test_no_local_list_recent_reimplementation_exists() -> None:
    """Confirms select_recent_memory_ids_by_count() never calls
    .list_recent() itself - the only path to that method is through the
    existing, unmodified select_recent_memory_ids(). Parses the actual
    function body via ast (excluding the docstring, which legitimately
    discusses list_recent() in prose) rather than a raw substring search."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(inspect.getsource(select_recent_memory_ids_by_count))
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)
    # Skip the docstring (the first statement, a bare string expression).
    body_without_docstring = func_def.body[1:]

    called_attrs = {
        node.func.attr
        for stmt in body_without_docstring
        for node in ast.walk(stmt)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "list_recent" not in called_attrs

    called_names = {
        node.func.id
        for stmt in body_without_docstring
        for node in ast.walk(stmt)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "select_recent_memory_ids" in called_names


def test_success_ids_and_order_preserved_unchanged(
    memory_manager: MemoryManager,
) -> None:
    ids = [_save(memory_manager, f"order-check entry {i}") for i in range(5)]

    result = select_recent_memory_ids_by_count(memory_manager, "5")

    # Newest-first (created_at DESC, id DESC), identical to
    # select_recent_memory_ids()'s own order - never re-sorted here.
    assert result.selected_ids == tuple(reversed(ids))


def test_zero_matches_maps_correctly_through_delegation() -> None:
    # Use a real, empty in-memory store rather than a bespoke double, so
    # the delegated zero-matches path is exercised genuinely.
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    manager = MemoryManager(EpisodicMemoryStore(factory))

    result = select_recent_memory_ids_by_count(manager, "5")

    assert result.zero_matches
    assert not result.failed
    assert not result.invalid_count
    assert result.requested_count == 5
    assert result.selected_ids == ()


def test_delegated_failure_maps_correctly_without_leaking_raw_exception() -> None:
    result = select_recent_memory_ids_by_count(
        _RaisingRecentMemoryManager(), "5"
    )

    assert result.failed
    assert not result.success
    assert not result.zero_matches
    assert not result.invalid_count
    assert result.requested_count == 5
    assert result.selected_ids == ()
    assert result.error == "Could not look up recent stored memories right now."
    assert "simulated database failure" not in (result.error or "")


# --- Storage/ordering compatibility ------------------------------------------


def test_more_than_requested_records_are_capped_at_the_requested_count(
    memory_manager: MemoryManager,
) -> None:
    ids = [_save(memory_manager, f"cap-check entry {i}") for i in range(11)]

    result = select_recent_memory_ids_by_count(memory_manager, "4")

    assert len(result.selected_ids) == 4
    # The four newest (highest ids), newest first - never the store's
    # full 11, never a differently-chosen subset.
    assert result.selected_ids == tuple(reversed(ids))[:4]


def test_count_selection_spans_multiple_categories_by_recency_order(
    memory_manager: MemoryManager,
) -> None:
    older_id = _save(memory_manager, "older project entry", category="project")
    newer_id = _save(memory_manager, "newer note entry", category="note")

    result = select_recent_memory_ids_by_count(memory_manager, "2")

    assert result.selected_ids == (newer_id, older_id)


def test_does_not_call_ingestion_or_ai_during_count_selection(
    memory_manager: MemoryManager,
) -> None:
    _save(memory_manager, "a memory for the no-ingestion proof")

    result = select_recent_memory_ids_by_count(memory_manager, "1")

    assert result.success
    assert isinstance(result, RecentCountSelectionResult)


def test_module_does_not_reference_phase_10_ingestion_count_path() -> None:
    assert not hasattr(memory_selection_module, "ingest_memories_for_ai")
    assert not hasattr(memory_selection_module, "ingest_memory_for_ai")
    assert not hasattr(memory_selection_module, "MemorySetIngestionResult")
    assert not hasattr(memory_selection_module, "AIContextBlock")


# --- Phase 13 selector/result untouched by the Phase 14 addition -----------


def test_phase_13_recent_selector_unaffected_by_phase_14_addition(
    memory_manager: MemoryManager,
) -> None:
    memory_id = _save(memory_manager, "phase 13 regression check content")

    result = select_recent_memory_ids(memory_manager)

    assert isinstance(result, RecentSelectionResult)
    assert result.selected_ids == (memory_id,)


# --- Phase 11/12 selectors remain fully unmodified by Phase 13 -------------


def test_phase_11_query_selector_unaffected_by_phase_13_addition(
    memory_manager: MemoryManager,
) -> None:
    memory_id = _save(memory_manager, "phase 11 regression check content")

    result = select_memory_ids_by_query(memory_manager, "phase 11 regression check")

    assert isinstance(result, QuerySelectionResult)
    assert result.selected_ids == (memory_id,)


def test_phase_12_category_selector_unaffected_by_phase_13_addition(
    memory_manager: MemoryManager,
) -> None:
    memory_id = _save(memory_manager, "phase 12 regression check", category="note")

    result = select_memory_ids_by_category(memory_manager, "note")

    assert isinstance(result, CategorySelectionResult)
    assert result.selected_ids == (memory_id,)
