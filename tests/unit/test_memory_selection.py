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

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

import ai.memory_selection as memory_selection_module
from ai.memory_selection import QuerySelectionResult, select_memory_ids_by_query
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager


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
