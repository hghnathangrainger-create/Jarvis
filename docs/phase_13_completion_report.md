# Jarvis — Phase 13 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 13 — Deterministic Recency-Based Automatic Memory Selection for Advisory AI (Batches 1–3, complete)
**Date:** 2026-07-09

---

## Executive Summary

Phase 13 of the Jarvis AI Operating System is **complete** for the scope defined in `docs/phase_13_implementation_plan.md`: it is the sixth proof point of the Phase 7 trust and injection-defence pipeline, and the third to select stored memories automatically — this time from **recency** rather than an explicit query or category. It answers the question left open at the close of Phase 12: how Jarvis turns an explicit user request for recent stored memories into a deterministic, bounded, explainable ordered selection for AI reasoning, using the repository's actual recency semantics rather than inventing unsupported time-window meaning or giving the AI authority to choose context.

Phase 13 is deliberately narrow. **"Recent" means exactly what the repository's existing, unmodified `MemoryManager.list_recent()` already means: the newest up-to-10 stored memory records across all categories, in the store's own `created_at DESC, id DESC` order — not a calendar window, not a relative-date interpretation, not a relevance ranking.** It does not implement last-24-hours/today/this-week retrieval, timezone-aware filtering, user-controlled counts, semantic/vector retrieval, or any form of AI-driven memory selection. Exactly one, already-complete deterministic capability is added: turn a fixed, parameter-free "give me the newest stored memories" request into an ordered, bounded set of matching memory ids, and reuse Phase 10's own combination architecture unchanged to reason about them together.

Three batches delivered this:

- **Batch 1 — Deterministic Recent-Memory Selection Foundation.** `ai/memory_selection.py` extended with `select_recent_memory_ids()` and `RecentSelectionResult`, calling the existing, unmodified `MemoryManager.list_recent(limit=10)` exactly once, across all categories, preserving the store's own newest-first order exactly. A genuine finding surfaced during this batch — corrected in the plan before Batch 2 began — that persisted `created_at` values are observed **naive**, not timezone-aware, once round-tripped through this repository's SQLite backend (see below).
- **Batch 2 — Recent-Memory Command and Orchestrator Wiring.** An explicit, **exact-match** `summarise recent memories` / `summarize recent memories` command (the first summary-family command with no trailing free-text argument at all), a new terminal orchestrator workflow reusing Phase 10's `ingest_memories_for_ai()` unchanged, and a new, narrow, non-authoritative `memory_recent_selection` audit event.
- **Batch 3 — End-to-End Verification, Security Closure, Documentation, and Commit.** This report, a README update, and a consolidated integration test proving the complete real stack — command routing (including a genuine budget-pressure case proving the newest-first ordering decision is load-bearing), across-category selection, recency trust, stored-result injection detection, the selection-to-ingestion race, zero-record/lookup-failure distinctions, audit privacy, and Phase 8/9/10/11/12 compatibility — against genuine, multiple saved memory records.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and every test — including every new Phase 13 test — uses a fake provider. No live Claude API call is made anywhere in this codebase's test suite.

---

## Phase 13 Objective

Phase 12 proved an explicit category could safely select a bounded, ordered set of memory ids. Phase 13's objective is narrow and specific: prove that **recency** — reusing the memory system's existing, unmodified `list_recent()` ordering — can deterministically select a bounded, ordered, explainable set of memory ids, reusing Phase 10's combination architecture completely unchanged, **without ever inventing a time-window meaning the repository does not actually implement** — the temptation Phase 11/12's own free-text query and fixed category vocabulary never presented, since neither of those capabilities could be mistaken for calendar-aware retrieval.

---

## Honest Definition of "Recent"

Established by direct code inspection of `memory/memory_manager.py` and `memory/episodic_memory.py`, confirmed unchanged throughout Phase 13:

- **`MemoryManager.list_recent(limit=20, *, category=None)`** delegates directly to **`EpisodicMemoryStore.list_recent(limit=limit, category=category)`** — the same underlying store method `MemoryManager.list_by_category()` (Phase 12) also calls, distinguished only by whether `category` is supplied.
- **Exact ordering: `.order_by(EpisodicMemory.created_at.desc(), EpisodicMemory.id.desc())`** — a SQL-level `ORDER BY`, not a Python-side sort. Newest-`created_at`-first is primary; `id` descending is the deterministic secondary tie-break.
- **No time-window capability exists anywhere in `EpisodicMemoryStore`.** There is no `WHERE created_at > ...`/`BETWEEN` clause, no relative-date parsing, nothing in the method name that implies otherwise once the implementation is actually read.
- **No clamp on `limit` exists** — whatever integer is supplied is forwarded straight into SQLAlchemy's `.limit(limit)`. Phase 13 always passes a fixed, code-level constant (`10`), never a user-supplied integer.

**"Recent" therefore means, honestly and exclusively: the newest up-to-10 stored memory records across all categories, in the store's own `created_at DESC, id DESC` order.** It is never described, anywhere in this phase's code, tests, or documentation, as "last 24 hours," "today," "this week," "recently accessed," "recently modified," or "most relevant" — none of these meanings exist in the repository this phase builds on.

---

## Implemented Capability

### Command syntax

| Command | What it does |
|---|---|
| `summarise recent memories` / `summarize recent memories` | Deterministically looks up the newest up-to-10 stored memories across all categories (GREEN, the same authority as the existing read-only memory commands), and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

**Exact-match command, no trailing argument at all.** Unlike every other summary-family command (`match_memory_summary`, `match_memory_query_summary`, `match_memory_category_summary`, `match_memory_set_summary`), which extract and forward trailing free text, `CommandRouter.match_memory_recent_summary(text) -> bool` recognises **only** the two complete phrases above, matched case-insensitively after stripping surrounding whitespace — never as a prefix. `"summarise recent memories about security"`, `"summarise recent memories in project"`, `"summarise recent memories 5"`, `"summarise recent memory"` (singular), and `"summarise very recent memories"` are all proven, at both the unit and integration level, to **not** match — each routes through its own existing, unaffected command (or falls through unrecognised) instead of the extra tokens being silently ignored.

### No routing collision (a materially simpler situation than Phase 11/12)

Phase 11 and 12 each had to resolve a genuine prefix collision with Phase 10's plural explicit-id matcher, because their qualifier word (`"about"`, `"in"`) comes **after** `"memories"`, making their own prefix a strict superset-string of `"summarise memories"`. Phase 13's qualifier (`"recent"`) sits **before** `"memories"` instead: `"summarise recent memories".startswith("summarise memories")` is **False** — the strings diverge immediately after `"summarise "`. Verified directly against all four existing summary-family prefixes, in both directions: no collision exists anywhere. **Consequently, unlike Phase 11/12, the dispatch-order placement of `match_memory_recent_summary` in `handle_request()` is not a correctness requirement** — it is grouped with the other summary-family checks (immediately after the category matcher) purely for narrative consistency, and this non-dependence on ordering is itself proven by test rather than merely asserted.

The exact, current dispatch order remains:

```
1. match_file_summary            -> Phase 8 file summary
2. match_memory_summary          -> Phase 9 singular memory summary
3. match_memory_query_summary    -> Phase 11 query-based memory summary
4. match_memory_category_summary -> Phase 12 category-based memory summary
5. match_memory_recent_summary   -> Phase 13 recent-memory summary (NEW, non-load-bearing position)
6. match_memory_set_summary      -> Phase 10 explicit-id plural memory summary
7. _handle_request_core / CommandRouter.match() -> ordinary rule-based dispatch
```

Proven end to end for every required trace: `"summarise recent memories"` reaches the Phase 13 workflow; `"summarise memory 27"` still reaches the unchanged Phase 9 workflow; `"summarise memories 27, 12"` still reaches the unchanged Phase 10 workflow; `"summarise memories about security"` still reaches the unchanged Phase 11 workflow; `"summarise memories in project"` still reaches the unchanged Phase 12 workflow; `"show memories in project"` and `"forget memory 27"` (pre-existing, generic commands) are untouched.

### Selection primitive and result model

`ai/memory_selection.py` adds `select_recent_memory_ids(memory_manager, *, limit=10)`, calling `memory_manager.list_recent(limit=limit)` exactly once — **no `category` argument is ever passed**, so every known category remains eligible purely on newest-first order. A new, minimal `RecentSelectionResult` (`selected_ids`, `error`, with `success`/`zero_matches`/`failed`/`match_count` properties) was added rather than reusing `QuerySelectionResult` (which would force a meaningless `query_length`) or `CategorySelectionResult` (which would force a meaningless `category` field and unusable `invalid_category` invariants) — a three-state shape, the same as `QuerySelectionResult`, because recency takes no caller-supplied criterion that could itself be invalid.

### Selection/order/limit contract

- **Fixed selection ceiling: 10.** `select_recent_memory_ids()` calls `MemoryManager.list_recent(limit=10)` explicitly — never the store's own default of 20, never a larger pool fetched and later reduced. Proven via a spy recording the exact limit argument, at both the unit level (Batch 1/2) and the full real command path (Batch 3, 12 saved records, exactly one call with `limit=10`).
- **Order is preserved exactly, never re-sorted, never reversed.** `EpisodicMemoryStore.list_recent()`'s `created_at DESC, id DESC` order is handed unchanged into `ingest_memories_for_ai()`. **This is the one architecturally consequential decision of this phase**, explored in full below.
- **More than 10 matches are capped, never ranked.** Proven with 12 saved records: exactly the two oldest/lowest ids never enter Phase 10 ingestion or the AI-facing prompt at all, and no wording anywhere claims relevance, ranking, or a time window.

### Across-all-categories behaviour

Recent selection is not category selection, and does not call `select_memory_ids_by_category()`. Proven directly: memories saved across all five known categories (`general`, `personal`, `project`, `preference`, `note`) are all present in a single recent-selection result (`test_recent_selection_spans_all_known_categories_end_to_end`), and a newer `note` memory is proven to precede an older `project` memory in the real, provider-facing context, solely because recency selection is newest-first across all categories — never grouped, quota'd, or prioritised by category (`test_newer_note_precedes_older_project_end_to_end`).

---

## Newest-First Ordering Decision (the phase's central architectural finding)

Because Phase 10's combined-context budget (`ingest_memories_for_ai`, `max_total_chars`) processes `memory_ids` in exactly the order supplied and omits-for-size whichever records overflow the running total **starting from wherever the overflow first occurs and continuing to the end of the sequence**, the order handed to ingestion is genuinely consequential, not cosmetic.

Two candidates were weighed during planning:

- **Chosen: preserve `list_recent()`'s own newest-first order exactly**, unmodified, all the way through to `ingest_memories_for_ai()`.
- **Rejected: reverse the selected set into chronological (oldest-first) order** before ingestion, for AI-reading coherence.

**The rejected candidate was ruled out for a concrete, mechanical reason, not a stylistic preference:** reversing to chronological order would mean that, on any budget overflow, the ids Phase 10's streaming omission drops are the **newest** of the selected records — the single memory the user most wanted included would be the first one silently dropped. This directly inverts the entire purpose of a "recent" selection.

**Proven directly at closure, not merely argued in the plan:** `test_newest_first_order_survives_context_budget_pressure_end_to_end` saves ten real records large enough (~2,500 characters each) that their combined content exceeds Phase 10's unmodified `max_total_chars=20,000` default, then confirms that fewer than all ten selected records survive into the combined context, that the **newest** (highest id, most recently saved) record is always among the survivors, that the **oldest** of the ten selected records is the one omitted, and that the response's own itemised disclosure names it under `"omitted to stay within the combined size limit"` — exactly the priority the newest-first ordering decision guarantees, and exactly what a chronological reversal would have inverted.

This is disclosed as a known, accepted framing tradeoff, not treated as fully solved: the AI reads newest-first content, not a chronological narrative. A future, separately-scoped enhancement to `ingest_memories_for_ai()` could decouple "omission priority order" from "display order" if this is ever found to matter in practice — not attempted here, and no Phase 10 budget or configuration was changed to accommodate this proof.

---

## Timestamp Representation — Correction and Closure

**A genuine finding, discovered during Batch 1 and corrected in the plan before Batch 2 began:** the original planning claim that `created_at` "is always UTC and timezone-aware" was **not fully true after SQLite persistence/read-back**.

- **Creation-side intent:** `storage/models.py`'s `_utc_now()` produces a timezone-aware UTC `datetime` at write time — this part of the original claim is accurate.
- **Observed read-back reality, proven directly** (`test_created_at_is_utc_valued_though_sqlite_returns_it_naive` in `tests/unit/test_memory_selection.py`): once written to and read back from this repository's SQLite backend, tzinfo is stripped — every read path (`MemoryManager.get()`, `list_recent()`, `list_by_category()`, `search()`) returns a **naive** `datetime` whose numeric value is still UTC.
- **The corrected, repository-grounded contract**, now documented in `docs/phase_13_implementation_plan.md` §2.2/§8/§18: memory timestamps are created using UTC-valued time, but SQLite read-back currently strips tzinfo, so persisted/retrieved `created_at` values are observed as naive `datetime` values carrying UTC-valued clock data under normal repository creation. This does **not** claim that every historical or migrated timestamp in the database is provably UTC — only that timestamps produced through the normal `_utc_now()`-backed creation path are.

**Why this is non-blocking for Phase 13's newest-N selection:** ordering is delegated entirely to `list_recent()`'s own SQL `ORDER BY created_at DESC, id DESC` — a database-side column comparison, never a Python-side timezone conversion or elapsed-time calculation. Phase 13 performs no time-window comparison, no "last 24 hours" semantics, no local-time/calendar interpretation, and no timezone conversion of any kind. `id DESC` deterministically resolves identical-`created_at` ties regardless of tzinfo presence — proven directly by forcing two real records to share an identical `created_at` value via the repository's own ORM session seam and confirming `id DESC` still orders them deterministically (`test_equal_created_at_records_are_ordered_by_id_desc`).

**Why this is blocking for any future time-window capability:** a genuinely calendar-aware or relative-date retrieval feature (last-N-hours, calendar-day, timezone-aware filtering, relative-date semantics, cross-timezone interpretation, or any timestamp-migration guarantee) would need to reason about timestamp values directly, at which point the naive-on-read-back reality becomes load-bearing rather than incidental. This debt is explicitly disclosed as requiring review **before** any such feature is built — not fixed here, and no tzinfo-repair, UTC-replacement, or timezone-conversion code was added anywhere in Phase 13.

---

## Recency Trust and Prompt-Boundary Proof

The literal command text (`"summarise recent memories"`) reaches `AIReasoningRequest.user_input` exactly as every existing summary command's own trailing text already does — as ordinary, live, current-turn user input — **never** as `AIContextBlock` content, and **never** mixed into the delimited `UNTRUSTED` memory context. Proven directly: the command text is absent from the isolated memory-context slice while present in the full prompt only via the live `user_input` channel (`test_recent_command_excluded_from_memory_context_end_to_end`). Selected stored memory remains unconditionally `ContentTrust.UNTRUSTED` regardless of recency; combined-block provenance (`source`) is derived only from the actually-included ids, in real newest-first order — never a recency criterion, since none exists to leak.

---

## Selection-to-Ingestion Handoff and Phase 10 Reuse

`select_recent_memory_ids()`'s ordered `selected_ids` are handed **unchanged, in the same newest-first order**, into Phase 10's own, completely unmodified `ingest_memories_for_ai()` — the exact same primitive the explicit-id, query-based, and category-based workflows already use. No second lookup, no re-sort, no duplicated combination function, no duplicated truncation/budgeting/provenance logic exists anywhere in Phase 13.

### Recency-selection-to-ingestion race (TOCTOU-style boundary)

A selected id can, in principle, disappear or fail between the recency lookup and Phase 10's own later `MemoryManager.get()` re-retrieval. This is a genuine, disclosed race, **structurally identical in kind and severity** to the one Phase 9/10/11/12 already accept for their own selection paths. **No new accounting state, transaction, lock, or snapshot was introduced.** It is represented entirely through Phase 10's existing states: a disappearance maps to `not_found` (proven with a wrapper whose `get()` reports a specific, genuinely recency-selected id as gone); a genuine retrieval error maps to `retrieval_errors` (proven with a wrapper whose `get()` raises for a specific id). One unusable selected id never discards the others; if every selected id becomes unusable, the existing Phase 10 total-failure path applies and the provider is never called — all proven directly through the real workflow.

---

## Zero-Record and Lookup-Failure Semantics

Kept distinct, both in code and in user-visible wording, and both proven never to reach ingestion or the AI provider:

- **Zero records** (an empty store): `"No memories are stored yet."` — an honest statement that the lookup itself succeeded and genuinely found nothing, distinguishing this from an infrastructure problem.
- **Lookup failure** (`MemoryManager.list_recent()` itself raises): `"Could not look up recent stored memories right now."` — a distinct, honest infrastructure-failure message, never conflated with "zero records," and never leaking the raw exception's own text.

Both proven distinct in wording (`test_zero_records_and_lookup_failure_produce_distinct_wording`) and in exact audit fields.

---

## `memory_recent_selection` Audit Event — Fields, Privacy

A new, narrow, non-authoritative audit event, distinct from Phase 10's per-id `memory_acquisition` events and from Phase 11/12's own selection events: it describes the recency-lookup step itself exactly once per recent-memory request.

**Exact fields, proven by test:**

```
outcome=<success|zero_records|failure> match_count=<int> selected_ids=<comma-joined ints, or empty>
```

**Deliberately, this event carries no criterion field at all** — unlike Phase 11's `query_length` and Phase 12's `category`, there is no caller-supplied criterion to log, since recency selection takes none. **No `requested_count=` field was added either**, even though one might seem analogous to `category=`: the selection ceiling (10) is a fixed, code-level constant with no per-request variance, so logging it on every single event would be a constant, redundant value carrying no review-time information. Proven directly (`test_recent_selection_event_carries_only_the_approved_fields`) that the event's `detail` string contains **exactly** `outcome=... match_count=... selected_ids=...` and nothing else — no memory content, no timestamps, no categories, no `query`, no `category`, no `requested_count`.

`EventOutcome.SUCCESS` is used only when at least one id was selected; `zero_records` and a genuine lookup exception both map to the existing `EventOutcome.FAILURE` value, distinguished only via the `outcome=` field inside `detail` — mirroring the existing precedent Phase 11's own `memory_query_selection` event already established.

---

## Audit Layering (No Duplication)

Proven directly (`test_audit_layers_are_distinct_and_not_duplicated`) that a single recent-memory request produces:

- **exactly one** Phase 13 `memory_recent_selection` event (recency-selection state),
- **exactly one** Phase 10 `memory_acquisition` event **per included id** (unchanged, reused, never duplicated or re-emitted by the Phase 13 selection helper — `ai/memory_selection.py` emits nothing itself),
- **exactly one** `AIRouter` `ai_call` event,
- **zero** `tool_call` events (acquisition never goes through `ToolExecutor`),

and, where suspicious content is present, the existing `PromptBuilder`/`audit_suspicious_injection` `injection_detection` event, unchanged.

---

## Observability Isolation

**Exactly one new logger-emitting call site exists in Phase 13**: `JarvisOrchestrator._audit_memory_recent_selection()`. It is wrapped in a narrow `try/except Exception: pass` scoped **only** around the `self._logger.emit(...)` call itself — never around `select_recent_memory_ids()`, `ingest_memories_for_ai()`, `AIReasoningEngine.reason()`, disclosure construction, or unexpected-action evaluation. Closure-level inspection confirmed the new `except Exception` block wraps only this one `emit()` call, alongside the pre-existing, unchanged boundaries: `_audit_memory_query_selection` and `_audit_memory_category_selection` (each wrapping only their own `emit()` call), `_emit_memory_acquisition_event`, `_audit_unexpected_action`, and, in `ai/memory_selection.py`, the three pre-existing/Batch-1 boundaries around `MemoryManager.search()`, `MemoryManager.list_by_category()`, and `MemoryManager.list_recent()` respectively, each wrapping only its own single lookup call. No broad exception swallowing exists anywhere in Phase 13.

A logger that fails **only** for the `memory_recent_selection` event is proven not to alter a successful selection, a zero-record outcome, or a lookup-failure outcome. `AIRouter`'s own `ai_call` audit isolation and Phase 10's `memory_acquisition` audit are both proven unaffected and independently correct on this new workflow.

---

## Injection Scanning Ownership

No new scanner exists anywhere in Phase 13. A real, recency-matched memory containing a known instruction-like pattern is combined through the real recency-selection path exactly as any explicit-id-, query-, or category-selected record already is, and `PromptBuilder`'s existing, unmodified `scan_for_injection()` detects and audits it through the same `audit_suspicious_injection` reporter Phase 7 already established. The memory text never becomes an executable command, and no approval is implicitly granted. **The Phase 10 delimiter-imitation limitation is preserved and re-verified honestly, not re-litigated:** a real, saved memory whose content imitates the Phase 10 record delimiter and embeds role/trust-like labels (`SYSTEM`, `JARVIS_TRUSTED`, a fake `source=` label) still results in a combined block that is `ContentTrust.UNTRUSTED`, with `source` derived only from the real, single retrieved record's own id.

---

## Security / Approval Semantics

**No new `ActionType` or `SecurityManager._RULES` entry was added. No existing action classification was reclassified. No `SecurityTier` changed. No approval behaviour changed.** `MemoryManager.list_recent()` is exactly as unconditionally read-only as `get()`/`search()`/`list_by_category()` already are, called directly from `ai/memory_selection.py` — the same disclosed, accepted bypass of `ToolExecutor`/`SecurityManager.classify_action()` Phase 9 established and Phase 10/11/12 already reused, now extended to a **fifth** direct call site. This was reviewed together with the inherited `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion semantic-drift debt: **reconfirmed acceptable, non-blocking debt**, now with a fifth example (`list_recent`) alongside `get`/`search`/`list_by_category`. Recency-based selection cannot cause a write, update, or delete regardless of which records it selects; mutating and deleting memory remain entirely out of scope, still gated by the unchanged `memory_update`/`memory_forget` YELLOW tools.

---

## Unexpected AI Action Verification

`test_unexpected_red_suggestion_is_blocked_end_to_end` and `test_unexpected_yellow_suggestion_is_escalated_end_to_end` prove, through the real stack, that an AI-suggested action outside the request's own expected scope is evaluated and audited exactly as every prior phase already established — via the same, completely unmodified `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods. The verdict remains a policy/audit observation only: no suggestion becomes a `ToolRequest`, executes, grants approval, or changes a `SecurityTier`, regardless of whether the AI's context came from explicit ids, a query, a category, or recency.

---

## Provider / Validation Failure Semantics

Preserved unchanged and re-proven on this workflow: a provider failure and an empty/invalid AI response both return `success=False` with no `"[AI recent memory summary"` label ever present — no fabricated summary in either case. No broad exception handler anywhere in Phase 13 converts an authoritative failure into an apparent success. A `memory_recent_selection` logger failure and an `AIRouter` `ai_call` logger failure are both proven not to masquerade as a provider or validation failure.

---

## Unchanged Phase 8/9/10/11/12 Workflows

Confirmed by direct inspection and by every pre-existing test passing unchanged, plus fresh, direct proofs on the very same orchestrator instance used for the recent-memory workflow:

- **Phase 8 file summary is unchanged** — untouched by this diff.
- **Phase 9 single-memory summary is unchanged** — `test_phase_9_singular_command_is_unaffected_on_the_same_orchestrator`.
- **Phase 10 explicit-id multi-memory summary is unchanged** — `test_phase_10_explicit_id_command_is_unaffected_on_the_same_orchestrator`, `test_routing_collision_does_not_capture_plural_explicit_id_command`.
- **Phase 11 query-based memory summary is unchanged** — `test_phase_11_query_command_is_unaffected_on_the_same_orchestrator`.
- **Phase 12 category-based memory summary is unchanged** — `test_phase_12_category_command_is_unaffected_on_the_same_orchestrator`.
- **`PromptBuilder` and `AIReasoningRequest` remain singular-context APIs** — neither file was modified anywhere in Phase 13.
- **`MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, and the timestamp creation helper (`_utc_now()`) remain unchanged** — confirmed by a zero-diff check.
- **No semantic/vector retrieval, ranking, user-controlled count, or time-window capability was introduced** — confirmed by direct diff inspection; no new dependency was added anywhere (`pyproject.toml`/`poetry.lock` untouched).

---

## Production Diff Structural Review

The new `_handle_memory_recent_summary_request()` handler was compared line by line against the established Phase 12 category handler at closure. Every branch classifies cleanly as one of: recent selection (`select_recent_memory_ids()` call), recent-selection audit (`_audit_memory_recent_selection()`), zero/failure handling (two early-return branches with Phase-13-specific wording), Phase 10 ingestion reuse (`ingest_memories_for_ai()`, unchanged call), Phase 10 acquisition auditing (`_audit_memory_set_acquisition()`, unchanged call), AI request construction (`AIReasoningRequest`, identical shape to every prior handler), AI reasoning result handling (`self._reasoning.reason()`, identical), unexpected-action handling (`_evaluate_unexpected_actions()`, unchanged, reused), and Jarvis-owned recent disclosure (the `"Found N recent memories."` wording plus the unchanged `_build_memory_set_disclosure()` reuse). No duplicated ingestion algorithm, trust construction, prompt construction, provider routing, response validation, or unexpected-action policy exists anywhere in this handler — every one of those concerns is a direct, unmodified call into existing, shared code.

**The handler structurally mirrors the Phase 12 category handler closely, and this is documented rather than refactored away.** A generic selection-workflow abstraction was deliberately not introduced solely to reduce line count: four concrete handlers (Phase 9 singular, Phase 10 plural, Phase 11 query, Phase 12 category, Phase 13 recency) now share this shape, each with its own distinct pre-flight checks (empty-query rejection, empty-category rejection, none at all for recency) and disclosure wording — collapsing them into one parameterised implementation was assessed and rejected as unjustified churn against four already-shipped, already-tested workflows, consistent with the explicit instruction not to generalise or refactor established selectors/handlers for aesthetic symmetry.

---

## Tests and Verification

**New in Phase 13:**
- **Batch 1:** `ai/memory_selection.py` extended; `tests/unit/test_memory_selection.py` extended (22 new tests, including the timestamp round-trip correction and the `id DESC` tie-break proof).
- **Batch 2:** `core/command_router.py` extended; `core/orchestrator.py` extended; `tests/unit/test_command_router.py` extended (12 new tests); `tests/unit/test_memory_recent_summary_workflow.py` (42 tests, new).
- **Batch 3:** `tests/integration/test_memory_recent_summary_end_to_end.py` (41 tests, new).

**Full Phase 13 test inventory, run directly in the development environment** (`poetry run pytest -q`, Python 3.14.6, pytest 9.1.1):

```
1384 passed
0 failed
0 skipped
0 errored
```

This is every test from Phases 1–12 (1343, the accepted Batch 2 floor, which already included Phase 13 Batches 1–2's own new tests approved in prior turns) plus Batch 3's 41 new consolidated integration tests. No live Claude API call is made anywhere in the suite.

### Test commands

```powershell
# The full test suite
poetry run pytest -v

# Phase 13 recency selection foundation, command routing, and workflow
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_recent_summary_workflow.py -v

# Consolidated end-to-end verification (Batch 3)
poetry run pytest tests/integration/test_memory_recent_summary_end_to_end.py -v

# All integration tests
poetry run pytest tests/integration -v
```

---

## Exact Files Changed

- `ai/memory_selection.py` (extended, Batch 1)
- `core/command_router.py` (extended, Batch 2)
- `core/orchestrator.py` (extended, Batch 2)
- `tests/unit/test_memory_selection.py` (extended, Batch 1)
- `tests/unit/test_command_router.py` (extended, Batch 2)
- `tests/unit/test_memory_recent_summary_workflow.py` (new, Batch 2)
- `tests/integration/test_memory_recent_summary_end_to_end.py` (new, Batch 3)
- `docs/phase_13_implementation_plan.md` (planning, including the timestamp-documentation correction revision)
- `docs/phase_13_completion_report.md` (this report, Batch 3)
- `README.md` (Batch 3)
- **Not touched:** `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, `memory/memory_models.py`, the timestamp creation helper (`_utc_now()`), `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `AIReasoningEngine`, `SecurityManager`, `ai/memory_ingestion.py`, `main.py`, `select_memory_ids_by_query()`/`QuerySelectionResult`, `select_memory_ids_by_category()`/`CategorySelectionResult`.

---

## Known Limitations and Non-Blocking Debt

- **Inherited, unchanged from Phase 9/10/11/12, non-blocking:** the `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion semantic-drift debt (now with a fifth example, `list_recent`); the broad `CommandRouter.match()` memory-keyword overlap; memory retrieval remaining unscoped by session; the recency-selection-to-ingestion TOCTOU-style race (same accepted class as Phase 10/11/12's).
- **New, disclosed by this phase:** the newest-first ingestion order means that under total-context-budget pressure, the *oldest* of the selected 10 records are dropped first — the correct, intended priority, but it also means the AI never receives a chronologically-ordered narrative, only a newest-first-framed one. Proven directly, not merely argued (`test_newest_first_order_survives_context_budget_pressure_end_to_end`).
- **New, disclosed by this phase:** the SQLite tzinfo-stripping timestamp-representation debt (corrected mid-Batch-1, documented above) — non-blocking for this phase's own newest-N selection, but must be reviewed before any future last-N-hours, calendar-day, timezone-aware, relative-date, or timestamp-migration capability is built.
- **The fixed 10-record selection ceiling is a disclosed starting judgement call**, revisable with evidence, not a permanent architectural limit — deliberately kept equal to Phase 10/11/12's own selection ceilings rather than introducing a second, differently-tuned number.

---

## Status Statement

**Phase 13 complete for its defined scope: deterministic, recency-based automatic memory selection into the advisory AI reasoning path, reusing Phase 10's combination architecture completely unchanged, through the completely unmodified Phase 7 trust and injection-defence pipeline, with full Phase 4 unexpected-action policy coverage, and zero changes to `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, or the Phase 11/12 selectors.**

Phase 13 is not, and must not be described as, time-windowed, calendar-aware, relevance-ranked, or AI-selected memory retrieval — it is a plain, deterministic, newest-N lookup against the repository's existing, unchanged ordering contract, bounded at a fixed ceiling, with the ordering decision proven load-bearing under genuine budget pressure rather than merely asserted. Closure-level inspection of every observability call site and exception boundary introduced by this phase found no defect requiring a fix.

---

## Recommended Next Capability

Deterministic selection now exists in four concrete forms — explicit ids (Phase 10), query search (Phase 11), category (Phase 12), and recency (Phase 13) — all sharing the same seam Phase 10 established: a strategy produces an ordered tuple of memory ids, and `ingest_memories_for_ai()` combines them. No generic strategy-pattern abstraction was introduced for this, deliberately, even now with four concrete strategies in place. Natural next continuations, each requiring its own narrow, separately-scoped design review before being started: a user-controlled recency count ("latest 5 memories"), which would be the first selector to introduce a validated numeric parameter; or a genuinely time-windowed retrieval capability, which would first require resolving the SQLite timestamp-representation debt disclosed above. Semantic/vector retrieval and any Entity/Semantic Memory work remain further out still, each requiring its own dependency and security review. None is started here.
