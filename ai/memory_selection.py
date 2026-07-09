"""
memory_selection.py

Deterministic, non-id-based memory selection for the Jarvis AI Operating
System. Query-based selection was added in Phase 11, Batch 1
(Deterministic Query-Based Memory Selection Foundation); category-based
selection was added in Phase 12, Batch 1 (Deterministic Category-Based
Memory Selection Foundation); recency-based selection was added in Phase
13, Batch 1 (Deterministic Recent-Memory Selection Foundation) - all three
as sibling capabilities in this same module, mirroring how
ai/memory_ingestion.py already houses both its single- and multi-record
ingestion responsibilities together.

Responsibilities:
    - Query selection: accept an explicit, caller-supplied query string
      and invoke the existing, unmodified MemoryManager.search() with the
      fixed Phase 11 selection ceiling (docs/phase_11_implementation_plan.md,
      Section 5.1: limit=10, matching core/orchestrator.py's own
      _MAX_MEMORY_SET_SIZE and ai/memory_ingestion.py's own
      _DEFAULT_MAX_RECORDS).
    - Category selection: accept an explicit, caller-supplied category
      string, defensively validate it against the existing
      is_known_category() helper before ever calling
      MemoryManager.list_by_category() or normalize_category(), and
      invoke list_by_category() with the fixed Phase 12 selection ceiling
      (docs/phase_12_implementation_plan.md, Section 7.2: limit=10).
    - Recency selection: accept no caller-supplied criterion at all beyond
      the fixed selection ceiling, and invoke the existing, unmodified
      MemoryManager.list_recent() - across all categories, never scoped to
      one - with the fixed Phase 13 selection ceiling
      (docs/phase_13_implementation_plan.md, Section 5.1/7: limit=10).
      "Recent" means exactly what list_recent() already means: the newest
      up-to-10 stored records in the store's own order - never an
      invented time-window (last 24 hours, today, this week, or
      otherwise), since no such capability exists anywhere in the store
      this module calls (Phase 13 plan, Section 2).
    - Preserve MemoryManager.search()'s/list_by_category()'s/
      list_recent()'s own result order exactly for all three selectors -
      no re-sorting, no deduplication, no candidate-pool reduction (Phase
      11 plan, Section 5.2; Phase 12 plan, Section 7.1; Phase 13 plan,
      Section 6).
    - Extract only the ordered memory ids from the results, never their
      content.
    - Represent every outcome as data, mirroring ai/memory_ingestion.py's
      MemoryIngestionResult/MemorySetIngestionResult convention. Query
      selection has three distinct, never-collapsed states (success, zero
      matches, search failure - Phase 11 plan, Sections 8, 12.2.1).
      Category selection has four distinct, never-collapsed states
      (success, zero matches, invalid category, lookup failure - Phase 12
      plan, Sections 5.3, 6, 8), because an unknown category is a
      genuinely different, more severe kind of input problem than an
      empty search query: reusing MemoryManager.list_by_category()
      directly with an unvalidated category would let
      normalize_category() silently substitute "general" rather than
      failing, honestly or otherwise (Phase 12 plan, Section 2.1). Recency
      selection has three distinct, never-collapsed states (success, zero
      matches, lookup failure - Phase 13 plan, Section 5.2), the same
      shape as query selection, because recency takes no caller-supplied
      criterion that could itself be invalid - there is no fourth
      "invalid input" state to represent.

Does NOT (query selection, Phase 11):
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
    - Rely on MemoryManager.search()'s own default limit (20). The fixed
      Phase 11 selection ceiling (10) is always passed explicitly.

Does NOT (category selection, Phase 12):
    - Ever call MemoryManager.list_by_category() or normalize_category()
      with a category that has not already passed is_known_category() -
      the defensive validation is this module's own, not merely relied
      upon from a caller (Phase 12 plan, Section 5.3, Candidate B). An
      unknown category never reaches the lookup call, so
      normalize_category()'s own silent "general" fallback never has an
      opportunity to fire from this path.
    - Invent aliases, fuzzy matching, or any AI-based category inference.
      KNOWN_CATEGORIES/normalize_category()/is_known_category() remain
      the sole source of truth, imported and reused directly.
    - Call MemoryTool as a category-lookup proxy, or perform any direct
      SQL/filtering logic locally - MemoryManager.list_by_category() is
      called directly, unchanged, exactly once per selection attempt.
    - Rely on MemoryManager.list_by_category()'s own default limit (20).
      The fixed Phase 12 selection ceiling (10) is always passed
      explicitly.

Does NOT (recency selection, Phase 13):
    - Infer, filter by, or otherwise represent any time window (last 24
      hours, today, yesterday, this week, a user-defined period, or any
      other calendar/relative-date meaning). No such capability exists in
      MemoryManager.list_recent()/EpisodicMemoryStore.list_recent(), and
      none is introduced here - "recent" means only "the newest up-to-10
      stored records in the store's own order" (Phase 13 plan, Section 2).
    - Scope the lookup to a single category. list_recent() is always
      called with no category argument (its own default, None), so
      records from every known category remain eligible purely on
      newest-first order - recency selection is not category selection
      and does not reuse select_memory_ids_by_category() (Phase 13 plan,
      Section 8).
    - Reverse, chronologically re-order, or otherwise reinterpret
      list_recent()'s own newest-first result for readability or any
      other reason. The store's own order is preserved exactly, because
      Phase 10's combined-context budget is streaming/order-sensitive and
      reversing would invert which records are kept when the budget is
      exceeded (Phase 13 plan, Section 6).
    - Accept a caller-supplied count or time period. The selection
      ceiling is a fixed, code-level constant; no user-tunable parameter
      is exposed (Phase 13 plan, Section 3, Candidate A).
    - Rely on MemoryManager.list_recent()'s own default limit (20). The
      fixed Phase 13 selection ceiling (10) is always passed explicitly.

Does NOT (all three selectors):
    - Retrieve memory content, construct an AIContextBlock, assign
      ContentTrust, or call PromptBuilder, AIRouter, AIReasoningEngine, or
      any AI provider. This module answers exactly one question per
      selector: which ordered ids did the existing deterministic
      mechanism return for this validated input? Turning those ids into
      AI-facing context remains exclusively
      ai/memory_ingestion.py's ingest_memories_for_ai(), called
      afterward, unchanged, by a future orchestrator caller (Phase 11
      plan, Sections 11, 12; Phase 12 plan, Section 11; Phase 13 plan,
      Section 11).
    - Duplicate any part of MemorySetIngestionResult,
      ingest_memories_for_ai(), _truncate(), combined-context
      framing/budgeting, whole-record omission, or partial-success
      accounting - all of that remains Phase 10's, untouched and reused
      unchanged by a future caller.
    - Emit any audit/observability event. The memory_query_selection,
      memory_category_selection, and memory_recent_selection audit events
      are all orchestrator/workflow concerns, assigned to their respective
      Batch 2 (Phase 11 plan, Section 12.2; Phase 12 plan, Section 12;
      Phase 13 plan, Section 13), not this primitive.
    - Retry, rank, or otherwise second-guess a lookup-layer exception - a
      raised exception is caught once, at this module's own boundary, for
      the one call it wraps, and represented as a single, honest failure
      state.

This module's only new production component in Phase 13 Batch 1 is the
recency-selection primitive; the existing Phase 11 query-selection
primitive (select_memory_ids_by_query/QuerySelectionResult) and Phase 12
category-selection primitive (select_memory_ids_by_category/
CategorySelectionResult) are untouched in behaviour, per the explicit
instruction not to generalise or rename existing APIs merely for symmetry.
"""

from __future__ import annotations

from dataclasses import dataclass

from memory.memory_manager import MemoryManager
from memory.memory_models import is_known_category, normalize_category

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


# ---------------------------------------------------------------------------
# Category-based selection (Phase 12, Batch 1)
# ---------------------------------------------------------------------------

#: The fixed Phase 12 selection ceiling (docs/phase_12_implementation_plan.md,
#: Section 7.2). Deliberately identical in value to _SELECTION_LIMIT above
#: and to Phase 10's own max_records default, for the same reason Phase 11
#: already established: the category-lookup limit and the Phase 10
#: selection ceiling are equal by explicit design, not by coincidence, and
#: remain two independently configurable numbers, never conflated as one
#: concept in code.
_CATEGORY_SELECTION_LIMIT = 10

#: Honest, generic failure message for a genuine category-lookup exception.
#: Deliberately does not embed the raised exception's own text, mirroring
#: _SEARCH_FAILURE_MESSAGE's own convention above.
_CATEGORY_LOOKUP_FAILURE_MESSAGE = (
    "Could not look up stored memories by category right now."
)


@dataclass(frozen=True, slots=True)
class CategorySelectionResult:
    """The result of a deterministic, category-based memory-id selection.

    Exactly one of four states applies, distinguished by the `success`,
    `zero_matches`, `invalid_category`, and `failed` properties below -
    never collapsed into one another, even though a future caller (Batch 2)
    may map `zero_matches`, `invalid_category`, and `failed` to the same
    EventOutcome.FAILURE audit value (docs/phase_12_implementation_plan.md,
    Section 12).

    Unlike QuerySelectionResult (Phase 11), whose `query_length` field
    exists because a search query is arbitrary, potentially-sensitive free
    text, this result carries the actual `category` value directly - a
    category is always one of a small, fixed, non-sensitive set of known
    strings (never arbitrary user free text), so storing and later logging
    it directly is safe (Phase 12 plan, Section 6).

    Attributes:
        selected_ids: The ids of the records MemoryManager.list_by_
            category() returned, in exactly the order it returned them -
            never re-sorted, deduplicated, or reordered here. Empty for
            every state except a non-empty success.
        category: The canonical, validated category actually queried
            (e.g. "project"), never the raw, as-supplied user spelling.
            Present (non-None) for `success`, `zero_matches`, and `failed`
            - every state where a real, known category was actually
            established before a lookup was attempted or failed. `None`
            only when `invalid_category` is True, since there is no
            canonical category to report for input that was never valid
            to begin with.
        error: A human-readable failure reason, set only when the
            underlying list_by_category() call itself raised. None
            otherwise, including for `invalid_category` and zero matches.
        invalid_category: True only when the supplied category failed
            is_known_category() validation - no lookup was ever
            attempted.
    """

    selected_ids: tuple[int, ...] = ()
    category: str | None = None
    error: str | None = None
    invalid_category: bool = False

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent outcome.

        Raises:
            ValueError: If `invalid_category` is True alongside a
                non-None `error`, a non-empty `selected_ids`, or a non-None
                `category` - an invalid-category result never claims a
                canonical category, selected ids, or a lookup error,
                since no lookup was ever attempted. Also raised if
                `invalid_category` is False but `category` is None (every
                other state requires a canonical category to have been
                established), or if `error` is set alongside a non-empty
                `selected_ids`.
        """
        if self.invalid_category:
            if (
                self.error is not None
                or self.selected_ids
                or self.category is not None
            ):
                raise ValueError(
                    "CategorySelectionResult with invalid_category=True "
                    "cannot also carry an error, selected_ids, or a "
                    "category - no lookup was ever attempted for an "
                    "invalid category."
                )
            return

        if self.category is None:
            raise ValueError(
                "CategorySelectionResult must carry a canonical category "
                "whenever invalid_category is False - success, "
                "zero_matches, and failed all require a category that "
                "already passed validation before a lookup was attempted "
                "or failed."
            )
        if self.error is not None and self.selected_ids:
            raise ValueError(
                "CategorySelectionResult cannot carry both selected_ids "
                "and an error - a represented lookup failure never claims "
                "that any ids were actually selected."
            )

    @property
    def success(self) -> bool:
        """Return whether the lookup completed and matched at least one record.

        Returns:
            True only when `invalid_category` is False, `error` is None,
            and `selected_ids` is non-empty.
        """
        return (
            not self.invalid_category
            and self.error is None
            and bool(self.selected_ids)
        )

    @property
    def zero_matches(self) -> bool:
        """Return whether a valid category lookup completed but matched nothing.

        Distinct from both `invalid_category` and `failed`: the supplied
        category was genuinely known and the lookup itself succeeded - it
        is a valid, deterministic fact that no stored memory currently has
        this category.

        Returns:
            True only when `invalid_category` is False, `error` is None,
            and `selected_ids` is empty.
        """
        return (
            not self.invalid_category
            and self.error is None
            and not self.selected_ids
        )

    @property
    def failed(self) -> bool:
        """Return whether the underlying list_by_category() call itself raised.

        Returns:
            True only when `error` is set.
        """
        return self.error is not None

    @property
    def match_count(self) -> int:
        """Return the number of selected ids.

        Returns:
            len(selected_ids).
        """
        return len(self.selected_ids)


def select_memory_ids_by_category(
    memory_manager: MemoryManager,
    category: str,
    *,
    limit: int = _CATEGORY_SELECTION_LIMIT,
) -> CategorySelectionResult:
    """Select an ordered set of memory ids matching a category, deterministically.

    Defensively validates `category` against the existing, unmodified
    `is_known_category()` before anything else is attempted. An unknown
    category never reaches `normalize_category()` or
    `MemoryManager.list_by_category()` - this is the selector's own
    correctness guarantee (docs/phase_12_implementation_plan.md, Section
    5.3, Candidate B), not merely a convention a caller must remember to
    uphold: without it, `normalize_category()` would silently substitute
    `"general"` for any unrecognised category, which could select the
    wrong records entirely rather than merely failing or returning empty.

    For a category that passes validation, the canonical form (from
    `normalize_category()`) is used for both the actual
    `memory_manager.list_by_category()` call and this result's own
    `category` field - never the raw, as-supplied spelling. Calls
    `list_by_category(canonical, limit=limit)` exactly once - the sole
    call site - and extracts only the ids of the returned records, in
    exactly the order it returned them. Applies no ranking, no re-sorting,
    no deduplication, and no candidate-pool reduction: whatever order and
    whichever up-to-`limit` records `MemoryManager.list_by_category()`/
    `EpisodicMemoryStore.list_recent()` returns is exactly what this
    function reports (created_at DESC, id DESC, per the current store
    implementation - see docs/phase_12_implementation_plan.md, Section
    7.1).

    An empty or whitespace-only `category` fails `is_known_category()`
    exactly like any other unrecognised value (mirroring
    `is_known_category("")` returning False) and therefore also resolves
    to `invalid_category`, never to a silent `"general"` lookup - there is
    no separate empty-input special case here (Phase 12 plan, Section 8).

    Args:
        memory_manager: The MemoryManager used to perform the lookup.
        category: The caller-supplied category text, checked against
            `is_known_category()` before any other use - not stripped or
            altered here (that helper already strips/lower-cases
            internally for its own comparison).
        limit: The maximum number of records `memory_manager.
            list_by_category()` may return. Defaults to the fixed Phase 12
            selection ceiling (10). Production callers should not
            override this; it exists as a parameter only so tests can
            exercise the limit explicitly without relying on the
            module-level default.

    Returns:
        A CategorySelectionResult. If `category` fails validation,
        `invalid_category` is True, `category` is None, and no lookup is
        attempted (`.invalid_category` is True). On a successful lookup
        that matched at least one record, `selected_ids` carries the
        ordered ids and `category` carries the canonical form (`.success`
        is True). On a successful lookup that matched nothing,
        `selected_ids` is empty and `category` still carries the
        canonical form (`.zero_matches` is True). If
        `list_by_category()` itself raises, `selected_ids` is empty,
        `category` still carries the canonical form, and `error` carries
        an honest, generic failure message (`.failed` is True) - the
        raised exception's own text is never embedded in the returned
        error.
    """
    if not is_known_category(category):
        return CategorySelectionResult(invalid_category=True)

    canonical = normalize_category(category)

    try:
        records = memory_manager.list_by_category(canonical, limit=limit)
    except Exception:
        return CategorySelectionResult(
            category=canonical, error=_CATEGORY_LOOKUP_FAILURE_MESSAGE
        )

    selected_ids = tuple(record.id for record in records)
    return CategorySelectionResult(selected_ids=selected_ids, category=canonical)


# ---------------------------------------------------------------------------
# Recency-based selection (Phase 13, Batch 1)
# ---------------------------------------------------------------------------

#: The fixed Phase 13 selection ceiling (docs/phase_13_implementation_plan.md,
#: Section 7). Deliberately identical in value to _SELECTION_LIMIT and
#: _CATEGORY_SELECTION_LIMIT above, and to Phase 10's own max_records
#: default, for the same reason already established twice: the
#: recency-lookup limit and the Phase 10 selection ceiling are equal by
#: explicit design, not by coincidence, and remain two independently
#: configurable numbers, never conflated as one concept in code.
_RECENT_SELECTION_LIMIT = 10

#: Honest, generic failure message for a genuine list_recent() exception.
#: Deliberately does not embed the raised exception's own text, mirroring
#: _SEARCH_FAILURE_MESSAGE's/_CATEGORY_LOOKUP_FAILURE_MESSAGE's own
#: convention above.
_RECENT_LOOKUP_FAILURE_MESSAGE = (
    "Could not look up recent stored memories right now."
)


@dataclass(frozen=True, slots=True)
class RecentSelectionResult:
    """The result of a deterministic, recency-based memory-id selection.

    Exactly one of three states applies, distinguished by the `success`,
    `zero_matches`, and `failed` properties below - never collapsed into a
    single generic outcome, the same three-state shape as
    QuerySelectionResult (docs/phase_13_implementation_plan.md, Section
    5.2). Unlike QuerySelectionResult (which carries `query_length`) and
    CategorySelectionResult (which carries `category`), this result carries
    no criterion-describing field at all: recency selection takes no
    caller-supplied input beyond the fixed selection ceiling, so there is
    nothing else here to represent, log, or validate.

    Attributes:
        selected_ids: The ids of the records MemoryManager.list_recent()
            returned, in exactly the order it returned them - never
            re-sorted, deduplicated, or reordered here (created_at DESC,
            id DESC, per the current store implementation). Empty when the
            lookup completed but the store held no memories, or when it
            failed.
        error: A human-readable failure reason, set only when the
            underlying list_recent() call itself raised. None when the
            lookup call completed, whether or not it returned any
            records.
    """

    selected_ids: tuple[int, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent outcome.

        Raises:
            ValueError: If `error` is set alongside a non-empty
                `selected_ids` - a represented lookup failure never claims
                that any ids were actually selected.
        """
        if self.error is not None and self.selected_ids:
            raise ValueError(
                "RecentSelectionResult cannot carry both selected_ids and "
                "an error - a represented lookup failure never claims "
                "that any ids were actually selected."
            )

    @property
    def success(self) -> bool:
        """Return whether the lookup completed and returned at least one record.

        Returns:
            True only when `error` is None and `selected_ids` is
            non-empty.
        """
        return self.error is None and bool(self.selected_ids)

    @property
    def zero_matches(self) -> bool:
        """Return whether the lookup completed but the store held no memories.

        Distinct from `failed`: the lookup operation itself succeeded - it
        is a valid, deterministic fact that no memories are currently
        stored, not an infrastructure problem.

        Returns:
            True only when `error` is None and `selected_ids` is empty.
        """
        return self.error is None and not self.selected_ids

    @property
    def failed(self) -> bool:
        """Return whether the underlying list_recent() call itself raised.

        Returns:
            True only when `error` is set.
        """
        return self.error is not None

    @property
    def match_count(self) -> int:
        """Return the number of selected ids.

        Returns:
            len(selected_ids).
        """
        return len(self.selected_ids)


def select_recent_memory_ids(
    memory_manager: MemoryManager,
    *,
    limit: int = _RECENT_SELECTION_LIMIT,
) -> RecentSelectionResult:
    """Select the ordered ids of the newest stored memories, deterministically.

    Calls memory_manager.list_recent(limit=limit) exactly once - the sole
    call site - across all categories (list_recent()'s own `category`
    parameter is never supplied, so its default of None applies, and every
    known category remains eligible) - and extracts only the ids of the
    returned records, in exactly the order list_recent() returned them.
    Applies no ranking, no re-sorting, no deduplication, and no
    candidate-pool reduction: whatever order and whichever up-to-`limit`
    records MemoryManager.list_recent()/EpisodicMemoryStore.list_recent()
    returns is exactly what this function reports (created_at DESC, id
    DESC, per the current store implementation - see
    docs/phase_13_implementation_plan.md, Section 6). This function never
    reverses the selected set into chronological order: the store's own
    newest-first order is preserved exactly, because Phase 10's
    combined-context budget processes ids in supplied order and reversing
    would invert which of the selected records are kept if that budget is
    ever exceeded (Phase 13 plan, Section 6).

    "Recent" means exactly what the repository's own list_recent() already
    means: the newest up-to-`limit` stored memory records, in the store's
    own order. This function does not filter by, or infer, any time window
    (last 24 hours, today, this week, or otherwise) - no such capability
    exists anywhere in the store this function calls, and none is
    introduced here (docs/phase_13_implementation_plan.md, Section 2).

    Args:
        memory_manager: The MemoryManager used to perform the lookup.
        limit: The maximum number of records memory_manager.list_recent()
            may return. Defaults to the fixed Phase 13 selection ceiling
            (10). Production callers should not override this; it exists
            as a parameter only so tests can exercise the limit explicitly
            without relying on the module-level default.

    Returns:
        A RecentSelectionResult. On a successful lookup that returned at
        least one record, `selected_ids` carries the ordered ids and
        `error` is None (`.success` is True). On a successful lookup that
        returned nothing (an empty store), `selected_ids` is empty and
        `error` is None (`.zero_matches` is True). If
        memory_manager.list_recent() itself raises, `selected_ids` is
        empty and `error` carries an honest, generic failure message
        (`.failed` is True) - the raised exception's own text is never
        embedded in the returned error.
    """
    try:
        records = memory_manager.list_recent(limit=limit)
    except Exception:
        return RecentSelectionResult(error=_RECENT_LOOKUP_FAILURE_MESSAGE)

    selected_ids = tuple(record.id for record in records)
    return RecentSelectionResult(selected_ids=selected_ids)
