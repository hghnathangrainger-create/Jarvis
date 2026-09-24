"""
test_context_assembly.py

Unit tests for intelligence/context.py (Phase 90, Batch 1 - Context
Intelligence), covering the Section 24.A contracts (ContextSource,
ContextItem, AssembledContext), the exact deterministic
query-derivation and memory-selection algorithms, the fixed character
budgets, and ProjectState honesty rendering.

These use small, duck-typed fakes for MemoryManager/ProjectStateStore -
never a real database - so every scenario (retrieval failure, budget
exhaustion, dedup, recency fallback) can be constructed directly and
deterministically. The orchestrator's real, end-to-end vertical slice
(real MemoryManager/ProjectStateStore/AIReasoningEngine) is covered
separately in tests/unit/test_orchestrator_context_query.py.

Run with:
    pytest tests/unit/test_context_assembly.py
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from datetime import datetime, timezone

import pytest

from config.constants import ContentTrust
from intelligence.context import (
    AssembledContext,
    ContextAssembler,
    ContextItem,
    ContextSource,
    build_ai_context_block,
    derive_query_terms,
)


@dataclasses.dataclass
class _FakeMemoryRecord:
    id: int
    content: str


@dataclasses.dataclass
class _FakeProjectStateRecord:
    branch: str | None = None
    phase: str | None = None
    commit: str | None = None
    suite_result: str | None = None
    focus: str | None = None
    last_updated: datetime | None = None


class _FakeMemoryManager:
    """A duck-typed MemoryManager double: no database, no AI."""

    def __init__(
        self,
        *,
        search_results: dict[str, list[_FakeMemoryRecord]] | None = None,
        recent_results: list[_FakeMemoryRecord] | None = None,
        search_raises: bool = False,
        recent_raises: bool = False,
    ) -> None:
        self._search_results = search_results or {}
        self._recent_results = recent_results or []
        self._search_raises = search_raises
        self._recent_raises = recent_raises
        self.search_calls: list[tuple[str, int]] = []
        self.recent_calls: list[int] = []

    def search(self, query: str, limit: int = 20, category: str | None = None):
        self.search_calls.append((query, limit))
        if self._search_raises:
            raise RuntimeError("simulated search failure")
        return self._search_results.get(query, [])

    def list_recent(self, limit: int = 20, category: str | None = None):
        self.recent_calls.append(limit)
        if self._recent_raises:
            raise RuntimeError("simulated list_recent failure")
        return self._recent_results[:limit]


class _FakeProjectStateStore:
    def __init__(
        self,
        record: _FakeProjectStateRecord | None = None,
        *,
        raises: bool = False,
    ) -> None:
        self._record = record
        self._raises = raises

    def get(self):
        if self._raises:
            raise RuntimeError("simulated project state failure")
        return self._record


def _assembler(
    *,
    search_results=None,
    recent_results=None,
    search_raises: bool = False,
    recent_raises: bool = False,
    project_state: _FakeProjectStateRecord | None = None,
    project_state_raises: bool = False,
) -> tuple[ContextAssembler, _FakeMemoryManager, _FakeProjectStateStore]:
    memory = _FakeMemoryManager(
        search_results=search_results,
        recent_results=recent_results,
        search_raises=search_raises,
        recent_raises=recent_raises,
    )
    project_state_store = _FakeProjectStateStore(
        project_state, raises=project_state_raises
    )
    return (
        ContextAssembler(
            memory_manager=memory, project_state_store=project_state_store
        ),
        memory,
        project_state_store,
    )


# --- A. Context contract tests -------------------------------------------------


def test_context_source_has_exactly_four_bounded_members() -> None:
    """Phase 100, Batch 2 (docs/phase_100_intelligence_core_gap_audit.md)
    adds VERIFIED_ACTIONS as a third member, and the Markdown Brain
    Integration adds BRAIN as a fourth - each for its own real,
    already-built consumer (VerifiedActionContextBuilder / the optional
    BrainService collaborator wired by main.py) - never speculatively,
    matching the bar ContextSource's own docstring sets."""
    assert {member.value for member in ContextSource} == {
        "memory", "project_state", "verified_actions", "brain",
    }


def test_context_item_is_frozen_and_slotted() -> None:
    item = ContextItem(
        context_id="memory:1",
        source=ContextSource.MEMORY,
        source_record_id="1",
        text="hello",
        trust=ContentTrust.UNTRUSTED,
        relevance_reason="test",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.text = "changed"  # type: ignore[misc]
    assert not hasattr(item, "__dict__")


def test_context_item_has_exactly_the_amended_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(ContextItem)}
    assert field_names == {
        "context_id",
        "source",
        "source_record_id",
        "text",
        "trust",
        "relevance_reason",
    }


def test_assembled_context_is_frozen_and_slotted_with_exact_fields() -> None:
    assembled = AssembledContext(
        request_text="hi",
        items=(),
        total_chars=0,
        truncated=False,
        notes=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        assembled.truncated = True  # type: ignore[misc]
    assert not hasattr(assembled, "__dict__")
    field_names = {f.name for f in dataclasses.fields(AssembledContext)}
    assert field_names == {"request_text", "items", "total_chars", "truncated", "notes"}


def test_memory_context_id_is_deterministic_across_two_assemblies() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(42, "some content")]
    )
    first = assembler.assemble("no matching terms whatsoever")
    second = assembler.assemble("no matching terms whatsoever")
    first_memory_id = next(
        i.context_id for i in first.items if i.source is ContextSource.MEMORY
    )
    second_memory_id = next(
        i.context_id for i in second.items if i.source is ContextSource.MEMORY
    )
    assert first_memory_id == second_memory_id == "memory:42"


def test_project_state_context_id_is_always_the_fixed_singleton_id() -> None:
    assembler, _, _ = _assembler(
        project_state=_FakeProjectStateRecord(branch="main")
    )
    assembled = assembler.assemble("hello")
    project_item = next(i for i in assembled.items if i.source is ContextSource.PROJECT_STATE)
    assert project_item.context_id == "project_state:current"
    assert project_item.source_record_id is None


def test_context_id_is_never_derived_from_raw_content() -> None:
    """Proof by construction: a memory whose content contains a
    distinctive, unique marker must never leak that marker into any
    context_id anywhere in the assembly."""
    marker = "UNIQUE_SECRET_MARKER_XYZ"
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(7, f"content with {marker} inside")]
    )
    assembled = assembler.assemble("irrelevant")
    for item in assembled.items:
        assert marker not in item.context_id


def test_every_retrieved_item_is_untrusted() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(1, "a"), _FakeMemoryRecord(2, "b")],
        project_state=_FakeProjectStateRecord(branch="main"),
    )
    assembled = assembler.assemble("anything")
    assert len(assembled.items) >= 1
    assert all(item.trust is ContentTrust.UNTRUSTED for item in assembled.items)


def test_live_request_is_not_represented_as_a_context_item() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(1, "unrelated content")]
    )
    request_text = "what is my distinctive live request text"
    assembled = assembler.assemble(request_text)
    assert assembled.request_text == request_text
    assert all(item.text != request_text for item in assembled.items)
    assert all(item.context_id != "request" for item in assembled.items)


# --- B. Query derivation tests --------------------------------------------------


def test_stopwords_are_removed_exactly() -> None:
    terms = derive_query_terms("what is the current focus of your project")
    # "what"/"is"/"the"/"current"/"of"/"your" are stopwords; "focus" and
    # "project" survive (both >= 4 chars).
    assert terms == ("focus", "project")


def test_punctuation_splits_tokens() -> None:
    terms = derive_query_terms("budget, timeline; scope!!")
    assert terms == ("budget", "timeline", "scope")


def test_lowercase_normalisation() -> None:
    terms = derive_query_terms("BUDGET Timeline")
    assert terms == ("budget", "timeline")


def test_minimum_four_character_rule() -> None:
    terms = derive_query_terms("cat dog fox budget")
    # "cat"/"dog"/"fox" are all 3 characters - excluded; "budget" survives.
    assert terms == ("budget",)


def test_first_five_terms_cap_preserves_original_order() -> None:
    terms = derive_query_terms("alpha bravo charlie delta echo foxtrot golf")
    assert terms == ("alpha", "bravo", "charlie", "delta", "echo")


def test_zero_surviving_terms_yields_empty_tuple() -> None:
    terms = derive_query_terms("what is it to you and me")
    assert terms == ()


def test_command_prefix_words_excluded_even_mid_sentence() -> None:
    terms = derive_query_terms("what does jarvis know about the budget")
    assert "jarvis" not in terms
    assert "ask" not in terms
    assert terms == ("know", "budget")


# --- C. Memory-selection tests --------------------------------------------------


def test_lexical_matches_come_before_recency_fallback() -> None:
    assembler, memory, _ = _assembler(
        search_results={"budget": [_FakeMemoryRecord(1, "budget note")]},
        recent_results=[_FakeMemoryRecord(9, "recent note")],
    )
    assembled = assembler.assemble("what is the budget plan")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert memory_items[0].source_record_id == "1"
    assert memory_items[1].source_record_id == "9"


def test_query_terms_are_searched_in_original_order() -> None:
    assembler, memory, _ = _assembler(
        search_results={
            "budget": [_FakeMemoryRecord(1, "budget content")],
            "timeline": [_FakeMemoryRecord(2, "timeline content")],
        }
    )
    assembler.assemble("what is the budget and timeline")
    assert memory.search_calls == [("budget", 5), ("timeline", 5)]


def test_deduplicates_by_memory_id_first_occurrence_wins() -> None:
    assembler, _, _ = _assembler(
        search_results={
            "budget": [_FakeMemoryRecord(1, "first")],
            "timeline": [_FakeMemoryRecord(1, "duplicate - should be skipped")],
        }
    )
    assembled = assembler.assemble("the budget and timeline")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert len(memory_items) == 1
    assert memory_items[0].text == "first"


def test_five_memory_item_cap_is_enforced() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(i, f"content {i}") for i in range(1, 10)]
    )
    assembled = assembler.assemble("no useful search terms here at all")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert len(memory_items) == 5


def test_recency_fallback_fills_remaining_slots() -> None:
    assembler, memory, _ = _assembler(
        search_results={"budget": [_FakeMemoryRecord(1, "budget content")]},
        recent_results=[_FakeMemoryRecord(2, "a"), _FakeMemoryRecord(3, "b")],
    )
    assembled = assembler.assemble("the budget")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    ids = [i.source_record_id for i in memory_items]
    assert ids == ["1", "2", "3"]
    # remaining = 5 - 1 = 4
    assert memory.recent_calls == [4]


def test_recency_fallback_skips_ids_already_selected_lexically() -> None:
    assembler, _, _ = _assembler(
        search_results={"budget": [_FakeMemoryRecord(1, "budget content")]},
        recent_results=[_FakeMemoryRecord(1, "duplicate"), _FakeMemoryRecord(2, "new")],
    )
    assembled = assembler.assemble("the budget")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    ids = [i.source_record_id for i in memory_items]
    assert ids == ["1", "2"]


def test_empty_memory_state_produces_honest_note_and_no_items() -> None:
    assembler, _, _ = _assembler()
    assembled = assembler.assemble("anything at all")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert memory_items == []
    assert "no matching or recent memories found" in assembled.notes


def test_search_failure_is_isolated_and_recency_fallback_still_runs() -> None:
    assembler, memory, _ = _assembler(
        search_raises=True,
        recent_results=[_FakeMemoryRecord(1, "fallback content")],
    )
    assembled = assembler.assemble("the budget plan")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert len(memory_items) == 1
    assert memory_items[0].source_record_id == "1"
    assert "memory retrieval failed" in assembled.notes


def test_recent_failure_is_isolated_from_lexical_success() -> None:
    assembler, _, _ = _assembler(
        search_results={"budget": [_FakeMemoryRecord(1, "budget content")]},
        recent_raises=True,
    )
    assembled = assembler.assemble("the budget")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert len(memory_items) == 1
    assert "memory retrieval failed" in assembled.notes


def test_memory_selection_never_calls_any_ai_dependency() -> None:
    """Structural proof: ContextAssembler's constructor accepts only
    MemoryManager/ProjectStateStore/VerifiedActionContextBuilder (the
    last added by Phase 100, Batch 2)/BrainService (Markdown Brain
    Integration, read-only filesystem access only) - it has no
    AI-related collaborator to call in the first place."""
    signature = inspect.signature(ContextAssembler.__init__)
    assert set(signature.parameters) == {
        "self", "memory_manager", "project_state_store",
        "verified_action_context_builder", "brain_service",
    }


# --- D. Budget tests -------------------------------------------------------------


def test_maximum_six_total_items() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(i, "x") for i in range(1, 10)],
        project_state=_FakeProjectStateRecord(branch="main"),
    )
    assembled = assembler.assemble("no useful terms present")
    assert len(assembled.items) == 6


def test_maximum_five_memory_items_regardless_of_project_state() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(i, "x") for i in range(1, 10)],
        project_state=None,
    )
    assembled = assembler.assemble("no useful terms present")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert len(memory_items) == 5


def test_per_item_truncation_at_500_characters_with_disclosed_notice() -> None:
    long_content = "a" * 600
    assembler, _, _ = _assembler(recent_results=[_FakeMemoryRecord(1, long_content)])
    assembled = assembler.assemble("no useful terms present")
    memory_item = next(i for i in assembled.items if i.source is ContextSource.MEMORY)
    assert memory_item.text.startswith("a" * 500)
    assert "truncated" in memory_item.text
    assert len(memory_item.text) > 500
    assert assembled.truncated is True


def test_project_state_reservation_is_fixed_regardless_of_actual_length() -> None:
    """A short ProjectState text does not free up extra room for memory
    items - the two budgets are independent, never one shared pool."""
    short_project_state = _FakeProjectStateRecord(branch="m")
    long_memory_records = [_FakeMemoryRecord(i, "a" * 500) for i in range(1, 6)]
    assembler, _, _ = _assembler(
        recent_results=long_memory_records, project_state=short_project_state
    )
    assembled = assembler.assemble("no useful terms present")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    # All 5 memory items (500 chars each = 2500 exactly) still fit, proving
    # the unused portion of ProjectState's own small reservation was never
    # reallocated to memory - memory got exactly its own fixed 2500 budget.
    assert len(memory_items) == 5
    assert sum(len(i.text) for i in memory_items) == 2500


def test_total_chars_equals_sum_of_included_item_text_lengths() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(1, "short content")],
        project_state=_FakeProjectStateRecord(branch="main"),
    )
    assembled = assembler.assemble("no useful terms present")
    assert assembled.total_chars == sum(len(i.text) for i in assembled.items)
    assert assembled.request_text not in str(assembled.total_chars)


def test_truncated_flag_false_when_nothing_was_truncated_or_omitted() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(1, "short")],
        project_state=_FakeProjectStateRecord(branch="main", last_updated=datetime.now(timezone.utc)),
    )
    assembled = assembler.assemble("no useful terms present")
    assert assembled.truncated is False


def test_whole_item_omission_when_budget_would_be_exceeded() -> None:
    # Each 600-char record truncates to 500 + a disclosed notice (> 500
    # chars total), so 5 such records exceed the fixed 2,500 memory
    # budget - the last one that would not fit is wholly omitted.
    records = [_FakeMemoryRecord(i, "x" * 600) for i in range(1, 6)]
    assembler, _, _ = _assembler(recent_results=records, project_state=None)
    assembled = assembler.assemble("no useful terms present")
    memory_items = [i for i in assembled.items if i.source is ContextSource.MEMORY]
    assert len(memory_items) < 5
    assert assembled.truncated is True
    assert any("omitted" in note for note in assembled.notes)


def test_notes_never_contain_raw_omitted_content() -> None:
    marker = "SECRET_OMITTED_CONTENT_MARKER"
    records = [_FakeMemoryRecord(i, f"{marker}{'x' * 600}") for i in range(1, 6)]
    assembler, _, _ = _assembler(recent_results=records, project_state=None)
    assembled = assembler.assemble("no useful terms present")
    for note in assembled.notes:
        assert marker not in note


# --- E. ProjectState tests -------------------------------------------------------


def test_fully_populated_project_state_record() -> None:
    record = _FakeProjectStateRecord(
        branch="main",
        phase="Phase 90",
        commit="abc123",
        suite_result="4318 passed, 3 skipped, 0 failed",
        focus="context intelligence",
        last_updated=datetime(2026, 7, 17, 8, 0, 0, tzinfo=timezone.utc),
    )
    assembler, _, _ = _assembler(project_state=record)
    assembled = assembler.assemble("anything")
    item = next(i for i in assembled.items if i.source is ContextSource.PROJECT_STATE)
    assert "main" in item.text
    assert "Phase 90" in item.text
    assert "abc123" in item.text
    assert "4318 passed" in item.text
    assert "context intelligence" in item.text
    assert "2026-07-17 08:00:00 UTC" in item.text
    assert "[FILL IN]" not in item.text


def test_partially_populated_project_state_record_mixes_real_values_and_fill_in() -> None:
    record = _FakeProjectStateRecord(branch="main")
    assembler, _, _ = _assembler(project_state=record)
    assembled = assembler.assemble("anything")
    item = next(i for i in assembled.items if i.source is ContextSource.PROJECT_STATE)
    assert "Current branch: main" in item.text
    assert item.text.count("[FILL IN]") == 4
    assert "not recorded yet" in item.text


def test_absent_project_state_record_is_all_fill_in() -> None:
    assembler, _, _ = _assembler(project_state=None)
    assembled = assembler.assemble("anything")
    item = next(i for i in assembled.items if i.source is ContextSource.PROJECT_STATE)
    assert item.text.count("[FILL IN]") == 5
    assert "not recorded yet" in item.text
    assert "project state has not been recorded yet" in assembled.notes


def test_project_state_retrieval_failure_is_isolated_and_honest() -> None:
    assembler, _, _ = _assembler(project_state_raises=True)
    assembled = assembler.assemble("anything")
    project_items = [i for i in assembled.items if i.source is ContextSource.PROJECT_STATE]
    assert project_items == []
    assert "project state retrieval failed" in assembled.notes


def test_project_state_discloses_manual_not_auto_detected_and_may_be_stale() -> None:
    assembler, _, _ = _assembler(project_state=_FakeProjectStateRecord(branch="main"))
    assembled = assembler.assemble("anything")
    item = next(i for i in assembled.items if i.source is ContextSource.PROJECT_STATE)
    assert "manually recorded" in item.text
    assert "never auto-detected from git, a subprocess, or the filesystem" in item.text
    assert "may be stale" in item.text


def test_project_state_does_not_scrape_show_tool_output() -> None:
    """Structural proof: intelligence/context.py never imports
    ProjectStateShowTool, and never parses its rendered text - it reads
    only the structured ProjectStateRecord via ProjectStateStore.get()."""
    import intelligence.context as module

    tree = ast.parse(inspect.getsource(module))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
            if node.module:
                imported_names.add(node.module)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    assert "ProjectStateShowTool" not in imported_names
    assert "tools.builtin.project_state_show_tool" not in imported_names
    assert "ai.prompt_studio" not in imported_names
    assert "_field_or_fill_in" not in imported_names


# --- build_ai_context_block combination ------------------------------------------


def test_build_ai_context_block_combines_all_items_into_one_untrusted_block() -> None:
    assembler, _, _ = _assembler(
        recent_results=[_FakeMemoryRecord(1, "memory content here")],
        project_state=_FakeProjectStateRecord(branch="main"),
    )
    assembled = assembler.assemble("anything")
    block = build_ai_context_block(assembled)
    assert block is not None
    assert block.trust is ContentTrust.UNTRUSTED
    assert "memory content here" in block.text
    assert "main" in block.text
    assert "memory:1" in block.text
    assert "project_state:current" in block.text


def test_build_ai_context_block_returns_none_for_empty_assembly() -> None:
    assembled = AssembledContext(
        request_text="hi", items=(), total_chars=0, truncated=False, notes=()
    )
    assert build_ai_context_block(assembled) is None
