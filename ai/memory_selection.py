"""
memory_selection.py

Deterministic query-based memory selection for the Jarvis AI Operating
System (Phase 11, Batch 1: Deterministic Query-Based Memory Selection
Foundation).

Responsibilities:
    - Accept an explicit, caller-supplied query string and invoke the
      existing, unmodified MemoryManager.search() with the fixed Phase 11
      selection ceiling (docs/phase_11_implementation_plan.md, Section
      5.1: limit=10, matching core/orchestrator.py's own
      _MAX_MEMORY_SET_SIZE and ai/memory_ingestion.py's own
      _DEFAULT_MAX_RECORDS).
    - Preserve MemoryManager.search()'s own result order exactly - no
      re-sorting, no deduplication, no candidate-pool reduction (Phase 11
      plan, Section 5.2).
    - Extract only the ordered memory ids from the search results, never
      their content.
    - Represent every outcome as data, mirroring ai/memory_ingestion.py's
      MemoryIngestionResult/MemorySetIngestionResult convention: a
      successful, non-empty selection; a successful search that matched
      nothing (zero matches); and a search-layer failure are three
      distinct, never-collapsed states (Phase 11 plan, Sections 8, 12.2.1).

Does NOT:
    - Reject, strip, normalise, or otherwise pre-validate the query
      string. MemoryManager.search() already returns an empty result for
      an empty or whitespace-only query
      (memory/episodic_memory.py: `term = query.strip();
      if not term: return []`); this module relies on that existing
      behaviour rather than duplicating or second-guessing it with a
      parallel parser policy (Phase 11 plan, Section 6/8, clarification
      point 6). A user-facing "please provide a non-empty query"
      rejection, if wanted, is a command/orchestrator-layer (Batch 2)
      concern, not this module's.
    - Escape, normalise, or otherwise alter `%`/`_` wildcard meaning.
      MemoryManager.search()'s existing, parameterised ILIKE semantics are
      used completely unchanged - this module calls no other query
      mechanism and applies no local escaping, so it cannot become a
      second, diverging search dialect (Phase 11 plan, Section 2.1
      clarification, Section 4.2).
    - Call MemoryTool. MemoryManager.search() is called directly, exactly
      as ai/memory_ingestion.py already calls MemoryManager.get()
      directly - the same disclosed, accepted bypass of MemoryTool's own
      formatting/clamping layer (Phase 11 plan, Section 7.1).
    - Retrieve memory content, construct an AIContextBlock, assign
      ContentTrust, or call PromptBuilder, AIRouter, AIReasoningEngine, or
      any AI provider. This module answers exactly one question: which
      ordered ids did the existing deterministic search return? Turning
      those ids into AI-facing context remains exclusively
      ai/memory_ingestion.py's ingest_memories_for_ai(), called
      afterward, unchanged, by a future Batch 2 caller (Phase 11 plan,
      Sections 11, 12).
    - Duplicate any part of MemorySetIngestionResult,
      ingest_memories_for_ai(), _truncate(), combined-context
      framing/budgeting, whole-record omission, or partial-success
      accounting - all of that remains Phase 10's, untouched and reused
      unchanged by a future caller.
    - Emit any audit/observability event. The memory_query_selection audit
      event is an orchestrator/workflow concern, assigned to Batch 2
      (Phase 11 plan, Section 12.2), not this primitive.
    - Retry, rank, or otherwise second-guess a search-layer exception - a
      raised exception is caught once, at this module's own boundary, and
      represented as a single, honest failure state.
    - Rely on MemoryManager.search()'s own default limit (20). The fixed
      Phase 11 selection ceiling (10) is always passed explicitly.

This module is the only new production component Phase 11 Batch 1 adds.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.memory_manager import MemoryManager

#: The fixed Phase 11 selection ceiling (docs/phase_11_implementation_plan.md,
#: Section 5.1). Deliberately identical to core/orchestrator.py's own
#: _MAX_MEMORY_SET_SIZE and ai/memory_ingestion.py's own
#: _DEFAULT_MAX_RECORDS, so the search-result limit and the Phase 10
#: selection ceiling are equal by explicit design, not by coincidence - see
#: the plan's Section 5.1/5.3 for why these remain two independently
#: configurable numbers that are intentionally set equal in this first
#: implementation, never conflated as one concept in code.
_SELECTION_LIMIT = 10

#: Honest, generic failure message for a genuine search-layer exception.
#: Deliberately does not embed the raised exception's own text, matching
#: this codebase's convention of honest-but-generic failure messages (e.g.
#: core/orchestrator.py's _MEMORY_MANAGER_NOT_AVAILABLE_MESSAGE) rather
#: than surfacing raw internals. Matches
#: docs/phase_11_implementation_plan.md, Section 8, category 3, verbatim.
_SEARCH_FAILURE_MESSAGE = "Could not search stored memories right now."


@dataclass(frozen=True, slots=True)
class QuerySelectionResult:
    """The result of a deterministic, query-based memory-id selection.

    Exactly one of three states applies, distinguished by the `success`,
    `zero_matches`, and `failed` properties below - never collapsed into a
    single generic outcome, even though a future caller (Batch 2) may map
    `zero_matches` and `failed` to the same EventOutcome.FAILURE audit
    value (docs/phase_11_implementation_plan.md, Section 12.2.2).

    Attributes:
        selected_ids: The ids of the records MemoryManager.search()
            returned, in exactly the order search returned them - never
            re-sorted, deduplicated, or reordered here. Empty when the
            search completed but matched nothing, or when it failed.
        error: A human-readable failure reason, set only when the
            underlying search call itself raised. None when the search
            call completed, whether or not it matched anything.
        query_length: len() of the query string as supplied to
            select_memory_ids_by_query(), captured for a future caller's
            audit use (docs/phase_11_implementation_plan.md, Section
            12.2.2) without this result, or this module, ever retaining
            the query text itself.
    """

    selected_ids: tuple[int, ...] = ()
    error: str | None = None
    query_length: int = 0

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent outcome.

        Raises:
            ValueError: If `error` is set alongside a non-empty
                `selected_ids` - a represented search failure never claims
                that any ids were actually selected.
        """
        if self.error is not None and self.selected_ids:
            raise ValueError(
                "QuerySelectionResult cannot carry both selected_ids and "
                "an error - a represented search failure never claims "
                "that any ids were actually selected."
            )

    @property
    def success(self) -> bool:
        """Return whether the search completed and matched at least one record.

        Returns:
            True only when `error` is None and `selected_ids` is
            non-empty.
        """
        return self.error is None and bool(self.selected_ids)

    @property
    def zero_matches(self) -> bool:
        """Return whether the search completed but matched nothing.

        Distinct from `failed`: the search operation itself succeeded - it
        is a valid, deterministic fact that nothing in storage currently
        matches the query, not an infrastructure problem.

        Returns:
            True only when `error` is None and `selected_ids` is empty.
        """
        return self.error is None and not self.selected_ids

    @property
    def failed(self) -> bool:
        """Return whether the underlying search call itself raised.

        Returns:
            True only when `error` is set.
        """
        return self.error is not None


def select_memory_ids_by_query(
    memory_manager: MemoryManager,
    query: str,
    *,
    limit: int = _SELECTION_LIMIT,
) -> QuerySelectionResult:
    """Select an ordered set of memory ids matching a query, deterministically.

    Calls memory_manager.search(query, limit=limit) exactly once - the
    sole call site - and extracts only the ids of the returned records, in
    exactly the order search returned them. Applies no ranking, no
    re-sorting, no deduplication, and no candidate-pool reduction: whatever
    order and whichever up-to-`limit` records
    MemoryManager.search()/EpisodicMemoryStore.search() returns is exactly
    what this function reports (created_at DESC, id DESC, per the current
    store implementation - see docs/phase_11_implementation_plan.md,
    Section 5.2).

    This function performs no query validation of its own: an empty or
    whitespace-only query is passed straight through to
    memory_manager.search(), which already returns an empty result for
    such a query (memory/episodic_memory.py's own
    `term = query.strip(); if not term: return []`) - so an empty query
    here produces QuerySelectionResult.zero_matches, not a distinct
    "invalid query" state, which remains a command/orchestrator-layer
    (Batch 2) concern (Phase 11 plan, Section 6/8, clarification point 6).

    `%` and `_` retain their existing SQL LIKE wildcard meaning throughout
    - this function does not escape them, locally or otherwise (Phase 11
    plan, Section 2.1 clarification).

    Args:
        memory_manager: The MemoryManager used to perform the search.
        query: The caller-supplied query text, forwarded to
            memory_manager.search() unchanged - not stripped, escaped, or
            otherwise altered here.
        limit: The maximum number of records memory_manager.search() may
            return. Defaults to the fixed Phase 11 selection ceiling (10).
            Production callers should not override this; it exists as a
            parameter only so tests can exercise the limit explicitly
            without relying on the module-level default.

    Returns:
        A QuerySelectionResult. On a successful search that matched at
        least one record, `selected_ids` carries the ordered ids and
        `error` is None (`.success` is True). On a successful search that
        matched nothing, `selected_ids` is empty and `error` is None
        (`.zero_matches` is True). If memory_manager.search() itself
        raises, `selected_ids` is empty and `error` carries an honest,
        generic failure message (`.failed` is True) - the raised
        exception's own text is never embedded in the returned error.
    """
    try:
        records = memory_manager.search(query, limit=limit)
    except Exception:
        return QuerySelectionResult(
            error=_SEARCH_FAILURE_MESSAGE, query_length=len(query)
        )

    selected_ids = tuple(record.id for record in records)
    return QuerySelectionResult(selected_ids=selected_ids, query_length=len(query))
