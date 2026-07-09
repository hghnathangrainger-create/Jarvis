# Jarvis — Phase 11 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 11 — Deterministic Query-Based Memory Selection for Advisory AI (Batches 1–3, complete)
**Date:** 2026-07-09

---

## Executive Summary

Phase 11 of the Jarvis AI Operating System is **complete** for the scope defined in `docs/phase_11_implementation_plan.md`: it is the fourth proof point of the Phase 7 trust and injection-defence pipeline, and the first to select stored memories **automatically** from an explicit user query rather than from user-typed ids. It answers the question Phase 10 left open — how Jarvis turns an explicit user query about stored memory into a deterministic, bounded, explainable set of memory records for AI reasoning — without pretending that keyword/database search is semantic intelligence, and without ever giving the AI authority to choose its own context.

Phase 11 is deliberately narrow. **Selection is a plain, deterministic, case-insensitive content-pattern (SQL `ILIKE`) substring search over one field, reusing the repository's existing `MemoryManager.search()` exactly as it already behaves.** It does not implement semantic search, embeddings, vector retrieval, cosine similarity, hybrid lexical/vector retrieval, LLM-based relevance ranking, AI-selected memory ids, autonomous memory discovery, recency-based or category-based automatic selection, query rewriting, or synonym expansion. Exactly one, already-complete deterministic capability is added: turn an explicit query into an ordered, bounded set of matching memory ids, and reuse Phase 10's own combination architecture unchanged to reason about them together.

Three batches delivered this:

- **Batch 1 — Deterministic Query-Based Memory Selection Foundation.** New `ai/memory_selection.py`: `select_memory_ids_by_query()` and `QuerySelectionResult`, calling `MemoryManager.search(query, limit=10)` exactly once, preserving the store's own result order exactly, with zero involvement from Phase 10 ingestion, `AIContextBlock`, or any AI component.
- **Batch 2 — Query Command and Orchestrator Wiring.** An explicit `summarise memories about <query>` / `summarize memories about <query>` command, a concrete routing-collision fix (see below), a new terminal orchestrator workflow reusing Phase 10's `ingest_memories_for_ai()` unchanged, and a new, narrow, non-authoritative `memory_query_selection` audit event.
- **Batch 3 — End-to-End Verification, Security Closure, Documentation, and Commit.** This report, a README update, and a consolidated integration test proving the complete real stack — command routing, deterministic search, ordering, the 10-record ceiling, wildcard semantics, SQL-parameterisation, query trust, stored-result injection detection, the search-to-ingestion race, zero-match/search-failure distinctions, audit privacy, and Phase 8/9/10 compatibility — against genuine, multiple saved memory records.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and every test — including every new Phase 11 test — uses a fake provider. No live Claude API call is made anywhere in this codebase's test suite.

---

## Phase 11 Objective

Phase 10 proved a small, explicit, user-named set of memories could be safely combined and reasoned about together. Phase 11's objective is narrow and specific: prove that a **query**, not a list of ids, can deterministically select a bounded, ordered, explainable set of memory ids — reusing Phase 10's combination architecture completely unchanged — without inventing, or being mistaken for, semantic search, relevance ranking, or any form of AI-directed retrieval.

---

## Implemented Capability

### Command syntax

| Command | What it does |
|---|---|
| `summarise memories about <query>` / `summarize memories about <query>` | Deterministically searches stored memory content for the given query (GREEN, same authority as `search memories for <query>`), selects up to 10 matching ids, and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

**Explicit query, deterministic selection only.** The command recognises nothing but the literal, required `about` grammar plus whatever text follows it. There is no natural-language routing, no synonym expansion, no query rewriting, and no AI involvement in deciding which memories are selected — the selection is a plain, reproducible database search the user could describe exactly by reading this report.

### Routing-collision discovery and resolution

**A concrete, verified collision was found during planning, before any code was written**, not a hypothetical concern: `"summarise memories about <query>"` begins with the literal string `"summarise memories"` — the exact prefix Phase 10's own plural explicit-id matcher (`match_memory_set_summary`) already checks for. Verified directly:

```
"summarise memories about home renovation".casefold().startswith("summarise memories")  -> True
```

Left unresolved, the Phase 10 matcher would have swallowed a query-based request, extracted `"about home renovation"` as if it were an id list, and rejected it with a confusing, wrong error. This is resolved by the **longest-prefix/more-specific-first dispatch rule**: `JarvisOrchestrator.handle_request()` checks the new `match_memory_query_summary` (prefix `"summarise memories about"`) **before** `match_memory_set_summary` (prefix `"summarise memories"`). The exact dispatch order is:

```
1. match_file_summary            -> Phase 8 file summary
2. match_memory_summary          -> Phase 9 singular memory summary
3. match_memory_query_summary    -> Phase 11 query-based memory summary (NEW)
4. match_memory_set_summary      -> Phase 10 explicit-id plural memory summary
5. _handle_request_core / CommandRouter.match() -> ordinary rule-based dispatch
```

Proven end to end for all three required traces: `"summarise memories about Jarvis security"` reaches the Phase 11 workflow; `"summarise memories 27, 12, 18"` still reaches the unchanged Phase 10 workflow (the query matcher's stricter `"about"` requirement does not match it, so dispatch falls through correctly); `"summarise memory 27"` still reaches the unchanged Phase 9 workflow (its prefix never collides with either plural form — `"memory"` and `"memories"` diverge at the word's 6th character). No broader `CommandRouter` redesign was performed; the existing, accepted `CommandRouter.match()` keyword-overlap debt is untouched.

### Selection/order/limit contract

- **Fixed selection ceiling: 10.** `select_memory_ids_by_query()` calls `MemoryManager.search(query, limit=10)` explicitly — **never** the store's own default of 20, and never a larger candidate pool fetched and later reduced. Proven via a spy `MemoryManager` recording the exact `(query, limit)` arguments received, both at the primitive level (Batch 1) and through the full real command path (Batch 3).
- **Order is preserved exactly, never re-sorted.** The selector reports ids in precisely the order `MemoryManager.search()`/`EpisodicMemoryStore.search()` returns them; no numeric sort, no stable-dedup pass, no reordering for context-budget packing is performed anywhere on the Phase 11 path. Because the store's own order is `created_at DESC, id DESC` (newest first, deterministically tie-broken by id), this means: **newer matching memories are more likely to be fully included; older matches among the results are more likely to be wholly omitted for size** if the matched set is large — an honest, disclosed recency bias, not a relevance judgement.
- **More than 10 matches are capped, never ranked.** Proven with 12 saved matches: exactly the two oldest/lowest ids never enter Phase 10 ingestion or the AI-facing prompt at all, and no wording anywhere claims relevance, ranking, or candidate comparison (`test_more_than_ten_matches_are_capped_at_ten_end_to_end`).

### Query trust

The query reaches `AIReasoningRequest.user_input` exactly as every existing summary command's own trailing text already does — as ordinary, live, current-turn user input — **never** as `AIContextBlock` content, and **never** mixed into the delimited `UNTRUSTED` memory context. Proven with a deliberately chosen wildcard query (`"_at"`, matching `"cat"` via `LIKE` semantics without ever being a literal substring of that content) that isolates the memory-context slice from the rest of the prompt: the query is provably absent from the context slice while present in the full prompt only via the live `user_input` channel (`test_raw_query_excluded_from_memory_context_reaches_only_live_user_input`). A prompt-like query containing `SYSTEM:`, `JARVIS_TRUSTED`, and `"ignore previous instructions"` remains ordinary retrieval criteria: it neither upgrades matched content's trust nor alters its provenance, proven against both a genuine match (content stays `UNTRUSTED`, correct `source`) and a no-match case (an ordinary, honest zero-match response).

---

## Exact `MemoryManager.search()` Semantics Relied On (Unchanged)

Established by direct code inspection, not assumed from method names, and confirmed unchanged throughout Phase 11:

- **Fields searched:** `EpisodicMemory.content` only — never `category`, `source`, `id`, or `created_at`.
- **Matching semantics:** a single, case-insensitive SQL `ILIKE` substring match (`EpisodicMemory.content.ilike(f"%{term}%")`) — not tokenised, not ranked, not similarity-based, not natural-language-aware.
- **Ordering:** `ORDER BY created_at DESC, id DESC` — a genuinely deterministic order, confirmed to require no architectural fix to claim determinism.
- **Limits:** the store itself defaults to `limit=20` with no upper clamp at that layer; Phase 11 always passes `limit=10` explicitly, deliberately equal to (but a distinct, independently-configurable parameter from) `ingest_memories_for_ai()`'s own `max_records=10` defensive backstop.
- **Wildcard semantics:** `%` and `_` are **not escaped** and retain their live SQL `LIKE` wildcard meaning — `%` matches any run of characters, `_` matches any single character. Proven end to end: a bare `%` query matched every saved record; `"_at"` matched `"cat"`/`"hat"` but not bare `"at"` (too short to satisfy the wildcard). **This is documented accurately as inherited `LIKE` wildcard pattern behaviour, not SQL injection, and not a guarantee of literal-substring matching for queries containing `%` or `_`.** No escaping was added anywhere on the Phase 11 path, including locally inside `ai/memory_selection.py` — doing so would have created a second, diverging search dialect from `MemoryTool`'s own unescaped `search memories for <query>` command.
- **Parameterisation / injection resistance:** confirmed safe. `EpisodicMemory.content.ilike(pattern)` binds the pattern as a parameter through SQLAlchemy; it is never string-interpolated into raw SQL. Proven end to end with a `"'; DROP TABLE episodic_memories; --"` query (no exception, zero matches, the table intact, a prior record still findable by a follow-up search afterward) and a classic `"' OR '1'='1"` payload (zero matches — proving the query never becomes SQL structure, since a real string-concatenation vulnerability would have returned every row).
- **No duplicates possible.** A single, non-joining filter over one table; each matching row is returned exactly once.
- **No soft-delete exists.** A deleted memory is physically absent from the table and cannot be returned by any later search.

---

## Query Validation and Extraction

`CommandRouter.match_memory_query_summary()` extracts the raw trailing text after the required `"about"` grammar, stripped of leading/trailing whitespace only — mirroring every other summary matcher's own extraction contract exactly; internal whitespace, punctuation, and wildcard characters are preserved unchanged. `JarvisOrchestrator._handle_memory_query_summary_request()` rejects only a truly empty (post-strip) query **before any search is attempted** — no memory read, no audit event, no AI consulted — mirroring Phase 9/10's own pre-acquisition validation precedent. A punctuation-only or wildcard-only query is **deliberately not treated as invalid**: it is passed to the selector like any other query, since rejecting it would require an unjustified heuristic about what counts as "meaningful" query content. `select_memory_ids_by_query()` itself performs no query validation at all — it relies on `MemoryManager.search()`'s own existing behaviour (`return []` for an empty/whitespace query), a documented and tested precondition, not a duplicated parser policy.

---

## Selection-to-Ingestion Handoff and Phase 10 Reuse

`select_memory_ids_by_query()`'s ordered `selected_ids` are handed **unchanged, in the same order**, into Phase 10's own, completely unmodified `ingest_memories_for_ai()` — the same primitive the explicit-id workflow already uses. No second search, no re-sort, no stable-dedup pass (search results cannot contain duplicates in the first place), no second combination function, and no duplicated truncation/budgeting/provenance logic exists anywhere in Phase 11. Proven directly at the real command-to-ingestion handoff (`test_selector_to_ingestion_order_is_preserved_exactly`, and the full success proof `test_query_selection_end_to_end_success`, which confirms the combined block's `source` label reflects only the actually-included ids in real, store-returned order).

### Search-to-ingestion race (TOCTOU-style boundary)

A selected id can, in principle, disappear or fail between the search call and Phase 10's own later `MemoryManager.get()` re-retrieval. This is a genuine, disclosed race, **structurally identical in kind and severity** to the one Phase 9/10 already accept for the explicit-id path (nothing ever prevented a user-typed id from being forgotten between typing it and Jarvis retrieving it, either). **No new accounting state, transaction, lock, or snapshot was introduced.** It is represented entirely through Phase 10's existing states: a disappearance maps to `not_found` (proven with a wrapper whose `get()` reports a specific, genuinely-searched id as gone); a genuine retrieval error maps to `retrieval_errors` (proven with a wrapper whose `get()` raises for a specific id). One unusable selected id never discards the others (proven with three real matches, one made to disappear, the other two still reaching the AI). If every selected id becomes unusable, the existing Phase 10 total-failure path applies and the provider is never called (proven directly).

---

## Zero-Match and Search-Failure Semantics

Kept distinct, both in code and in user-visible wording, and both proven never to reach ingestion or the AI provider:

- **Zero matches** (`MemoryManager.search()` completes but matches nothing): `"No stored memories matched '<query>'."` — an honest statement that the search itself succeeded and found nothing.
- **Search failure** (`MemoryManager.search()` itself raises): `"Could not search stored memories right now."` — a distinct, honest infrastructure-failure message, never conflated with "zero matches."

Both are proven through the real command/orchestrator path with exact audit-field assertions (see below), and `test_zero_match_and_search_failure_produce_distinct_wording` proves the two user-visible messages are never the same string.

---

## `memory_query_selection` Audit Event — Fields and Privacy

A new, narrow, non-authoritative audit event, distinct from Phase 10's per-id `memory_acquisition` events: it describes the search step itself — that a search was attempted, its outcome, and how many/which ids it selected — exactly once per query-based request.

**Exact fields, proven by test, for every query shape (ordinary, prompt-like, and SQL-looking alike):**

```
outcome=<success|zero_matches|failure> query_length=<int> match_count=<int> selected_ids=<comma-joined ints, or empty>
```

**The raw query text is never embedded** — only its length — directly reusing two existing repository conventions rather than inventing a new one: `PromptBuilder`'s own `audit_suspicious_injection` reporter's `text_length=` field, and `_emit_memory_acquisition_event`'s convention of logging only non-content integers/short reason codes. `zero_matches` and a genuine search exception both map to the existing `EventOutcome.FAILURE` value, distinguished only via the `outcome=` field inside `detail` — mirroring the **existing** precedent that a `not_found` id is already audited as `FAILURE` (with a `reason=` field) in this exact system, rather than inventing a new `EventOutcome` member. `EventOutcome.SUCCESS` is used only when at least one id was selected.

**Hashing was deliberately not used** as a privacy mechanism: this codebase has no keyed-hash/HMAC infrastructure anywhere, and an unsalted hash of a short, often-predictable search query would not provide real privacy — it would be brute-forceable and would also create a stable, correlatable identifier across requests, arguably worse than logging nothing.

Proven directly, parametrised across an ordinary query, a prompt-like query (`SYSTEM:`/`JARVIS_TRUSTED`/"ignore previous instructions"), and a SQL-looking query (`'; DROP TABLE episodic_memories; --`): none of the three ever appear inside the event's own `detail` string (`test_selection_event_never_leaks_query_text_for_any_query_shape`).

---

## Audit Layering (No Duplication)

Proven directly (`test_audit_layers_are_distinct_and_not_duplicated`) that a single query-based request produces:

- **exactly one** Phase 11 `memory_query_selection` event (search-selection state),
- **exactly one** Phase 10 `memory_acquisition` event **per included id** (unchanged, reused, never duplicated or re-emitted by the Phase 11 selection helper — `ai/memory_selection.py` emits nothing itself),
- **exactly one** `AIRouter` `ai_call` event,
- **zero** `tool_call` events (acquisition never goes through `ToolExecutor`),

and, where suspicious content is present, the existing `PromptBuilder`/`audit_suspicious_injection` `injection_detection` event, unchanged.

---

## Observability Isolation

**Exactly one new logger-emitting call site exists in Phase 11**: `JarvisOrchestrator._audit_memory_query_selection()`. It is wrapped in a narrow `try/except Exception: pass` scoped **only** around the `self._logger.emit(...)` call itself — never around `select_memory_ids_by_query()`, `ingest_memories_for_ai()`, `AIReasoningEngine.reason()`, disclosure construction, or unexpected-action evaluation. **Exactly one new exception boundary exists in `ai/memory_selection.py`**: a `try/except Exception` around `memory_manager.search(...)` itself, converting a genuine search-layer exception into the represented `.failed` state — not an observability guard, and it swallows nothing beyond that single call.

A logger that fails **only** for the `memory_query_selection` event is proven not to alter a successful selection, a zero-match outcome, or a search-failure outcome (`test_selectively_failing_selection_logger_does_not_alter_success` / `..._zero_matches` / `..._search_failure`). `AIRouter`'s own `ai_call` audit isolation (the Phase 9 closure fix) is proven unaffected and independently correct on this new workflow (`test_failing_ai_call_audit_does_not_break_a_valid_query_workflow`). No `except Exception` anywhere in Phase 11 wraps more than its one, narrowly-scoped, non-authoritative or single-call boundary — no defect was found requiring a fix.

---

## Injection Scanning Ownership

No new scanner exists anywhere in Phase 11. A real, matched memory containing a known instruction-like pattern (`"ignore all previous instructions"`) is combined through the real query-selection path exactly as any explicit-id-selected record already is, and `PromptBuilder`'s existing, unmodified `scan_for_injection()` detects and audits it through the same `audit_suspicious_injection` reporter Phase 7 already established (`test_stored_result_injection_is_detected_and_audited_end_to_end`). The memory text never becomes an executable command, and no approval is implicitly granted (`blocked=False`, `requires_confirmation=False`, `approval_request=None`, zero `tool_call` events).

**The Phase 10 delimiter-imitation limitation is preserved and re-verified honestly, not re-litigated.** A real, saved memory whose content imitates the Phase 10 record delimiter and embeds role/trust-like labels (`SYSTEM`, `JARVIS_TRUSTED`, a fake `source=` label) still results in a combined block that is `ContentTrust.UNTRUSTED`, with `source` derived only from the real, single retrieved record's own id (`test_delimiter_and_role_imitation_stays_untrusted_with_correct_provenance`). As Phase 10 already disclosed, this is a model-level, free-text narrative-provenance ambiguity only — never a claim of cryptographic or parser-level isolation, and Jarvis's own internal trust/provenance state is unaffected by construction.

---

## Security / Approval Semantics

**No new `ActionType` or `SecurityManager._RULES` entry was added. No existing action classification was reclassified. No `SecurityTier` changed. No approval behaviour changed.** `MemoryManager.search()` is exactly as unconditionally read-only as `MemoryManager.get()` already is, and is called directly from `ai/memory_selection.py` — the same disclosed, accepted bypass of `ToolExecutor`/`SecurityManager.classify_action()` Phase 9 established and Phase 10 already reused, now extended to a third direct call site. This was reviewed, as mandated, together with the inherited `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion semantic-drift debt (documented since Phase 9): it is **reconfirmed acceptable, non-blocking debt**, now with a third example (`search`) alongside `get` — resolving it would mean a larger, separately-scoped security-architecture question outside Phase 11's narrow purpose. Searching and reading stored memory remain in scope; mutating and deleting memory remain entirely out of scope, still gated by the unchanged `memory_update`/`memory_forget` YELLOW tools.

---

## Unexpected AI Action Verification

`test_unexpected_red_suggestion_is_blocked_end_to_end` and `test_unexpected_yellow_suggestion_is_escalated_end_to_end` prove, through the real stack, that an AI-suggested action outside the request's own expected scope is evaluated and audited exactly as every prior phase already established — via the same, completely unmodified `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods. The verdict remains a policy/audit observation only: no suggestion becomes a `ToolRequest`, executes, grants approval, or changes a `SecurityTier`, regardless of whether the AI's context came from explicit ids or a query-based search.

---

## Provider / Validation Failure Semantics

Preserved unchanged and re-proven on this workflow: a provider failure and an empty/invalid AI response both return `success=False` with no `"[AI query-based memory summary"` label ever present — no fabricated summary in either case. No broad exception handler anywhere in Phase 11 converts an authoritative failure into an apparent success.

---

## Unchanged Phase 8/9/10 Workflows

Confirmed by direct inspection and by every pre-existing test passing unchanged, plus fresh, direct proofs on the very same orchestrator instance used for the query workflow:

- **Phase 8 file summary is unchanged** — untouched by this diff.
- **Phase 9 single-memory summary is unchanged** in syntax, routing, AI path, trust, audit, security/approval, and output semantics — `test_phase_9_singular_command_is_unaffected_on_the_same_orchestrator`.
- **Phase 10 explicit-id multi-memory summary is unchanged** in syntax, routing, stable dedup, cardinality validation, user-order contract, ingestion, budgeting, omission, provenance, trust, disclosure, audit, and AI path — `test_phase_10_explicit_id_command_is_unaffected_on_the_same_orchestrator`, `test_routing_collision_fix_does_not_capture_plural_explicit_id_command`.
- **`PromptBuilder` and `AIReasoningRequest` remain singular-context APIs** — neither file was modified anywhere in Phase 11.
- **`MemoryManager`, `MemoryTool`, and `EpisodicMemoryStore` remain unchanged** — confirmed by a zero-diff check.
- **No semantic/vector retrieval was introduced** — confirmed by direct diff inspection; no new dependency was added anywhere (`pyproject.toml`/`poetry.lock` untouched).

---

## Tests and Verification

**New in Phase 11:**
- **Batch 1:** `ai/memory_selection.py` (new production module); `tests/unit/test_memory_selection.py` (24 tests, new).
- **Batch 2:** `core/command_router.py` extended; `core/orchestrator.py` extended; `tests/unit/test_command_router.py` extended (12 new tests); `tests/unit/test_memory_query_summary_workflow.py` (45 tests, new).
- **Batch 3:** `tests/integration/test_memory_query_summary_end_to_end.py` (36 tests, new).

**Full Phase 11 test inventory, run directly in the development environment** (`poetry run pytest -q`, Python 3.14.6, pytest 9.1.1):

```
1124 passed
0 failed
0 skipped
0 errored
```

This is every test from Phases 1–10 (1088, which already included Phase 11 Batches 1–2's own new tests approved in prior turns) plus Batch 3's 36 new consolidated integration tests. No live Claude API call is made anywhere in the suite.

### Test commands

```powershell
# The full test suite
poetry run pytest -v

# Phase 11 selection foundation, command routing, and workflow
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_query_summary_workflow.py -v

# Consolidated end-to-end verification (Batch 3)
poetry run pytest tests/integration/test_memory_query_summary_end_to_end.py -v

# All integration tests
poetry run pytest tests/integration -v
```

---

## Exact Files Changed

- `ai/memory_selection.py` (new, Batch 1)
- `core/command_router.py` (extended, Batch 2)
- `core/orchestrator.py` (extended, Batch 2)
- `tests/unit/test_memory_selection.py` (new, Batch 1)
- `tests/unit/test_command_router.py` (extended, Batch 2)
- `tests/unit/test_memory_query_summary_workflow.py` (new, Batch 2)
- `tests/integration/test_memory_query_summary_end_to_end.py` (new, Batch 3)
- `docs/phase_11_implementation_plan.md` (planning, including the wildcard/audit-privacy/routing clarification revision)
- `docs/phase_11_completion_report.md` (this report, Batch 3)
- `README.md` (Batch 3)
- **Not touched:** `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `AIReasoningEngine`, `SecurityManager`, `ai/memory_ingestion.py`, `main.py`.

---

## Known Limitations and Non-Blocking Debt

- **Unescaped `%`/`_` wildcard behaviour in `EpisodicMemoryStore.search()`'s `ILIKE` pattern** — a real, existing, disclosed characteristic, deliberately not patched in this phase; a narrow future fix (escape literal `%`/`_` inside `EpisodicMemoryStore.search()` itself, affecting every caller uniformly) is identified but not scheduled, and would be a separately reviewed compatibility change, not a Phase-11-local one.
- **The search-to-ingestion TOCTOU-style race** — accepted as structurally identical in kind and severity to the already-accepted explicit-id race; represented entirely via Phase 10's existing accounting, no locking introduced.
- **Recency bias under the combined-size budget** — an honest, disclosed consequence of preserving the store's own `created_at DESC` order rather than inventing a new one; not a relevance judgement.
- **Inherited, unchanged from Phase 9/10, non-blocking:** the `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion semantic-drift debt (now with a third example, `search`); the broad `CommandRouter.match()` memory-keyword overlap; memory retrieval remaining unscoped by session (accurate and non-blocking for the current single-user, local architecture).
- **The fixed 10-record selection ceiling is a disclosed starting judgement call**, revisable with evidence, not a permanent architectural limit — deliberately kept equal to Phase 10's own `max_records` default rather than introducing a second, differently-tuned number.

---

## Status Statement

**Phase 11 complete for its defined scope: deterministic, query-based automatic memory selection into the advisory AI reasoning path, reusing Phase 10's combination architecture completely unchanged, through the completely unmodified Phase 7 trust and injection-defence pipeline, with full Phase 4 unexpected-action policy coverage, and zero changes to `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `MemoryManager`, `MemoryTool`, or `EpisodicMemoryStore`.**

Phase 11 is not, and must not be described as, semantic search, intelligent retrieval, relevance ranking, AI-selected memory, or autonomous memory discovery — it is a plain, deterministic, case-insensitive content-pattern substring search, deterministically ordered and bounded. Closure-level inspection of every observability call site and exception boundary introduced by this phase found no defect requiring a fix.

---

## Recommended Next Capability

Deterministic query-based selection (Phase 11) is now the second of what could eventually be several memory-selection strategies alongside explicit ids (Phase 10) and, further out, recency-based, category-based, and (separately reviewed and security-assessed) semantic retrieval — all sharing the same seam Phase 10 established and Phase 11 reused unchanged: a strategy produces an ordered tuple of memory ids, and `ingest_memories_for_ai()` combines them. No generic strategy-pattern abstraction was introduced for this, deliberately, since only two concrete strategies exist after this phase. The natural next continuation is **recency-based or category-based automatic memory selection**, each requiring its own narrow, separately-scoped design review before being started; semantic/vector retrieval and any Entity/Semantic Memory work remain further out still, each requiring its own dependency and security review. Neither is started here.
