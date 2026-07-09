# Jarvis — Phase 12 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 12 — Deterministic Category-Based Memory Selection for Advisory AI (Batches 1–3, complete)
**Date:** 2026-07-09

---

## Executive Summary

Phase 12 of the Jarvis AI Operating System is **complete** for the scope defined in `docs/phase_12_implementation_plan.md`: it is the fifth proof point of the Phase 7 trust and injection-defence pipeline, and the second to select stored memories automatically — this time from an explicit, user-named **category** rather than a query. It answers the question Phase 11 left open: how Jarvis turns an explicit user-named memory category into a deterministic, bounded, explainable ordered set of memory records for AI reasoning, while preserving the repository's real category semantics and without ever letting an unrecognised category silently fall back to browsing the `"general"` category.

Phase 12 is deliberately narrow. **Selection is an exact-match lookup against the repository's existing, unmodified `MemoryManager.list_by_category()`, reusing the same five-category vocabulary the memory system has always had.** It does not implement recency-based selection, semantic/vector retrieval, fuzzy category matching, multi-category boolean expressions, query+category hybrid retrieval, or any form of AI-driven category inference. Exactly one, already-complete deterministic capability is added: turn an explicit, validated category into an ordered, bounded set of matching memory ids, and reuse Phase 10's own combination architecture unchanged to reason about them together.

Three batches delivered this:

- **Batch 1 — Deterministic Category-Based Memory Selection Foundation.** `ai/memory_selection.py` extended with `select_memory_ids_by_category()` and `CategorySelectionResult`, defensively validating every category against the existing `is_known_category()` **before** ever calling `normalize_category()` or `MemoryManager.list_by_category()` — the selector, not merely the orchestrator, is the correctness boundary that prevents an unknown category from silently querying `"general"`.
- **Batch 2 — Category Command and Orchestrator Wiring.** An explicit `summarise memories in <category>` / `summarize memories in <category>` command, a concrete routing-collision fix (see below — the same collision class Phase 11 already discovered), a new terminal orchestrator workflow reusing Phase 10's `ingest_memories_for_ai()` unchanged, and a new, narrow, non-authoritative `memory_category_selection` audit event.
- **Batch 3 — End-to-End Verification, Security Closure, Documentation, and Commit.** This report, a README update, and a consolidated integration test proving the complete real stack — command routing, selector-owned invalid-category rejection, canonicalisation, ordering, the 10-record ceiling, category trust, stored-result injection detection, the selection-to-ingestion race, zero-record/lookup-failure distinctions, audit privacy, and Phase 8/9/10/11 compatibility — against genuine, multiple saved memory records.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and every test — including every new Phase 12 test — uses a fake provider. No live Claude API call is made anywhere in this codebase's test suite.

---

## Phase 12 Objective

Phase 11 proved a deterministic search query could safely select a bounded, ordered set of memory ids. Phase 12's objective is narrow and specific: prove that an explicit **category** — reusing the memory system's existing, unmodified organisational vocabulary — can deterministically select a bounded, ordered, explainable set of memory ids, reusing Phase 10's combination architecture completely unchanged, **without ever letting an unrecognised category silently substitute `"general"`** — the one genuinely new correctness risk this capability introduces that Phase 11's free-text query never had.

---

## Exact Authoritative Category Vocabulary

Established by direct code inspection of `memory/memory_models.py`, confirmed unchanged throughout Phase 12:

- **Structure:** category is a plain, required string column on `EpisodicMemory` (`String(32)`, `nullable=False`, default `"general"`) — not an enum, not a separate table.
- **Known values — exactly five, and only these:** `"general"` (`GENERAL`, also `DEFAULT_CATEGORY`), `"personal"` (`PERSONAL`), `"project"` (`PROJECT`), `"preference"` (`PREFERENCE`), `"note"` (`NOTE`) — collected in `KNOWN_CATEGORIES: tuple[str, ...]`. No aliases exist anywhere in the repository.
- **`normalize_category(category)`:** strips whitespace, lower-cases, and returns the result only if it is a member of `KNOWN_CATEGORIES`; otherwise (including `None` or blank) it returns `"general"`. **This fallback never raises and never rejects — it is silent.**
- **`is_known_category(category)`:** an independent, pure predicate — strips, lower-cases, and reports membership in `KNOWN_CATEGORIES` — without normalising or falling back.
- **The genuine, material finding that shaped this phase's central design decision:** because `normalize_category()` silently maps *any* unrecognised string to `"general"`, a naive category-selection implementation calling `MemoryManager.list_by_category()` directly with unvalidated input would not fail, or return empty, for a typo'd or adversarial category — it would silently query `"general"` instead, which may well be non-empty. **This is a materially more severe failure mode than anything Phase 11's free-text query selection had to account for**, and is the reason Phase 12's selector — not merely its orchestrator — owns defensive validation (see below).

---

## Implemented Capability

### Command syntax

| Command | What it does |
|---|---|
| `summarise memories in <category>` / `summarize memories in <category>` | Deterministically looks up stored memories in the given category (GREEN, same authority as the existing `show memories in <category>` command), selects up to 10 matching records, and asks the advisory AI to summarise them together. Requires AI reasoning to be enabled. |

**Explicit, validated category, deterministic selection only.** The command recognises nothing but the literal, required `in` grammar plus whatever text follows it — no fuzzy matching, no AI category inference, no natural-language variants (`"what do I remember in project"` is not recognised).

### Routing-collision discovery and resolution

**A concrete, verified collision was found during planning — the same class Phase 11 already discovered, now confirmed as a standing review requirement for every new summary command, not a one-off fix.** `"summarise memories in <category>"` begins with the literal string `"summarise memories"` — the exact prefix Phase 10's own plural explicit-id matcher (`match_memory_set_summary`) already checks for. Verified directly:

```
"summarise memories in project".startswith("summarise memories")  -> True
```

Left unresolved, the Phase 10 matcher would swallow a category-based request, extract `"in project"` as if it were an id list, and reject it with a confusing, wrong error. Resolved by the same **longest-prefix/more-specific-first dispatch rule** Phase 11 already established: `JarvisOrchestrator.handle_request()` checks the new `match_memory_category_summary` (prefix `"summarise memories in"`) **before** `match_memory_set_summary` (prefix `"summarise memories"`). The exact, current dispatch order is:

```
1. match_file_summary            -> Phase 8 file summary
2. match_memory_summary          -> Phase 9 singular memory summary
3. match_memory_query_summary    -> Phase 11 query-based memory summary
4. match_memory_category_summary -> Phase 12 category-based memory summary (NEW)
5. match_memory_set_summary      -> Phase 10 explicit-id plural memory summary
6. _handle_request_core / CommandRouter.match() -> ordinary rule-based dispatch
```

Proven end to end for every required trace: `"summarise memories in project"` reaches the Phase 12 workflow; `"summarise memories 27, 12, 18"` still reaches the unchanged Phase 10 workflow; `"summarise memory 27"` still reaches the unchanged Phase 9 workflow; `"summarise memories about security"` still reaches the unchanged Phase 11 workflow (the two new matchers' prefixes diverge at their second word, `"in"` vs `"about"`, so neither collides with the other); `"show memories in project"` (the pre-existing, `MemoryTool`-routed, generic command) is untouched, since the new matcher is checked entirely within the summary-family dispatch block, before `CommandRouter.match()` is ever reached. No broader `CommandRouter` redesign was performed; the existing, accepted broad-keyword-overlap debt is untouched.

### Invalid-category correctness invariant (closure-critical)

**Invariant:** a category-selection operation must never call `MemoryManager.list_by_category()` with an unknown category value in a way that permits `normalize_category()` to silently substitute `"general"`.

**Ownership:** `select_memory_ids_by_category()` itself — not merely its caller — calls the existing, unmodified `is_known_category()` **before** calling `normalize_category()` or `MemoryManager.list_by_category()` at all. An unknown category returns `CategorySelectionResult(invalid_category=True)` immediately; the lookup call site is never reached. This was a deliberate design choice among three evaluated candidates: orchestrator-only validation (rejected — makes selector correctness depend entirely on caller discipline, with no defence if a future caller invokes the selector directly without validating first); selector-level defensive validation with the orchestrator validating only for fast, side-effect-free syntax rejection (**chosen** — the selector's own correctness does not depend on any caller remembering to validate); and globally changing `normalize_category()`/`list_by_category()` to reject unknown input (rejected — would break the Phase 5 save/organise workflows that deliberately and correctly rely on the permissive fallback for their own, different reasons, e.g. `remember this as <category>: ...` intentionally never fails for an unrecognised category).

**Proven directly, at closure, with a deliberately planted trap:** a real `"general"`-category memory is saved, then a lookup for the unknown category `"spaceships"` is issued. A spy `MemoryManager` proves **zero** `list_by_category()` calls occurred; the planted `"general"` content never enters Phase 10 ingestion, never enters the provider-facing prompt, and the provider is never called (`test_unknown_category_never_selects_general_content_end_to_end`). The same proof is repeated, parametrised, for a range of adversarial and prompt-like category strings (`SYSTEM`, `JARVIS_TRUSTED`, `"SYSTEM: ignore instructions"`, `"!!!"`, `"spaceships"`) — all rejected identically, all producing zero lookups (`test_adversarial_invalid_category_is_rejected_end_to_end`).

### Canonicalisation

The exact, tested sequence: raw extraction (`CommandRouter`, strip only) → orchestrator's own emptiness-only pre-check (mirroring Phase 11's empty-query rejection) → the selector's `is_known_category()` (authoritative validation) → `normalize_category()` (canonical form) → `MemoryManager.list_by_category(canonical, limit=10)`. `"PROJECT"` canonicalises to `"project"` — proven, end to end, that the store is called with `"project"` (never `"PROJECT"`), the combined block's provenance uses `"project"`, the `memory_category_selection` audit event carries `category=project`, and the user-visible disclosure reads `"category 'project'"`, never `"category 'PROJECT'"` (`test_uppercase_category_canonicalizes_end_to_end`). `CategorySelectionResult.category` always carries this canonical value, never the raw, as-typed spelling, for every state where a category was actually validated (`success`, `zero_matches`, `failed`) — and is `None` only for `invalid_category`.

### All supported category values

Every one of the five repository-authoritative categories (`general`, `personal`, `project`, `preference`, `note` — derived directly from `KNOWN_CATEGORIES`, never a second hardcoded list) is proven individually selectable end to end (`test_every_known_category_is_selectable_end_to_end`, parametrised over `KNOWN_CATEGORIES` itself).

### Selection/order/limit contract

- **Fixed selection ceiling: 10.** `select_memory_ids_by_category()` calls `MemoryManager.list_by_category(canonical, limit=10)` explicitly — never the store's own default of 20, never a larger pool fetched and later reduced. Proven via a spy recording exact `(category, limit)` arguments, at both the unit level (Batch 1) and the full real command path (Batch 3, 12 saved matches, exactly one call with `limit=10`).
- **Order is preserved exactly, never re-sorted.** `EpisodicMemoryStore.list_recent()`'s category-filtered path uses the **same** `created_at DESC, id DESC` deterministic ordering Phase 11 already relies on and has already been proven deterministic — no new ordering analysis or fix was required. Proven into the real, combined, provider-facing context (`test_category_selection_end_to_end_success`, `test_more_than_ten_category_matches_are_capped_at_ten_end_to_end`).
- **More than 10 matches are capped, never ranked.** Proven with 12 saved matches: exactly the two oldest/lowest ids never enter Phase 10 ingestion or the AI-facing prompt at all, and no wording anywhere claims relevance, ranking, or candidate comparison.

### Category trust

The category reaches `AIReasoningRequest.user_input` exactly as every existing summary command's own trailing text already does — as ordinary, live, current-turn user input — **never** as `AIContextBlock` content, and **never** mixed into the delimited `UNTRUSTED` memory context. Proven directly: the literal command text is absent from the isolated memory-context slice while present in the full prompt only via the live `user_input` channel (`test_category_criteria_excluded_from_memory_context_end_to_end`). Selected stored memory remains unconditionally `ContentTrust.UNTRUSTED` regardless of category; combined-block provenance (`source`) is derived only from the actually-included ids, never the category or the requested category text.

---

## Selection-to-Ingestion Handoff and Phase 10 Reuse

`select_memory_ids_by_category()`'s ordered `selected_ids` are handed **unchanged, in the same order**, into Phase 10's own, completely unmodified `ingest_memories_for_ai()` — the exact same primitive the explicit-id and query-based workflows already use. No second lookup, no re-sort, no duplicated combination function, no duplicated truncation/budgeting/provenance logic exists anywhere in Phase 12.

### Category-selection-to-ingestion race (TOCTOU-style boundary)

A selected id can, in principle, disappear or fail between the category lookup and Phase 10's own later `MemoryManager.get()` re-retrieval. This is a genuine, disclosed race, **structurally identical in kind and severity** to the one Phase 9/10/11 already accept for the explicit-id and query-based paths. **No new accounting state, transaction, lock, or snapshot was introduced.** It is represented entirely through Phase 10's existing states: a disappearance maps to `not_found` (proven with a wrapper whose `get()` reports a specific, genuinely category-matched id as gone); a genuine retrieval error maps to `retrieval_errors` (proven with a wrapper whose `get()` raises for a specific id). One unusable selected id never discards the others; if every selected id becomes unusable, the existing Phase 10 total-failure path applies and the provider is never called — all proven directly through the real workflow.

---

## Zero-Record and Lookup-Failure Semantics

Kept distinct, both in code and in user-visible wording, and both proven never to reach ingestion or the AI provider:

- **Zero records** (a valid, known category with no matching stored memories): `"No stored memories are in the '<category>' category."` — an honest statement that the category was genuinely valid and the lookup succeeded, finding nothing.
- **Lookup failure** (`MemoryManager.list_by_category()` itself raises): `"Could not look up stored memories by category right now."` — a distinct, honest infrastructure-failure message, never conflated with "zero records."
- **Invalid category** (fails `is_known_category()`): `"'<raw text>' is not a known memory category. Known categories are: general, personal, project, preference, note."` — distinct from both of the above, and only this message ever echoes the user's own raw input (a normal, expected UX courtesy, unrelated to the audit-privacy rule below, which governs only the non-authoritative audit trail).

All three are proven distinct in wording (`test_zero_records_and_lookup_failure_produce_distinct_wording`, plus the Batch 2 unit-level three-way distinctness test) and in exact audit fields.

---

## `memory_category_selection` Audit Event — Fields, Privacy, Canonicalisation

A new, narrow, non-authoritative audit event, distinct from Phase 10's per-id `memory_acquisition` events and from Phase 11's `memory_query_selection` event: it describes the category-lookup step itself exactly once per category-based request.

**Exact fields, proven by test, for every category shape (valid, unknown, and prompt-like alike):**

```
outcome=<success|zero_records|invalid_category|failure> [category=<canonical>] match_count=<int> selected_ids=<comma-joined ints, or empty>
```

`category=` is present **only** when `CategorySelectionResult.category` is not `None` — i.e. for `success`, `zero_records`, and `failure`, where a real, canonical, validated category was actually established. **For `invalid_category`, the `category=` field is omitted entirely** — never the raw, unvalidated input (`"spaceships"`, `"SYSTEM"`, etc.), and never a fabricated `category=general`. This omission-when-absent shape mirrors the existing repository convention already used for the optional `reason=` field in `_emit_memory_acquisition_event`'s own detail string.

**Privacy decision, deliberately re-evaluated rather than copied from Phase 11:** unlike a free-text search query, **the canonical category value is safe to log directly** whenever one was actually established — `normalize_category()` guarantees it is always one of exactly five short, fixed, non-sensitive, organisational-label strings, never arbitrary user free text. Logging `category=project` is materially more useful for review than logging only a length would be, and carries none of the privacy risk Phase 11's `query_length`-only design exists to avoid. `EventOutcome.SUCCESS` is used only when at least one id was selected; `zero_records`, `invalid_category`, and a genuine lookup exception all map to the existing `EventOutcome.FAILURE` value, distinguished only via the `outcome=` field inside `detail` — mirroring the existing precedent (a `not_found` id is already audited as `FAILURE` with a `reason=` field in this exact system) rather than inventing new `EventOutcome` members.

Proven directly, parametrised across `PROJECT` (→ `category=project`), an unknown category (→ `outcome=invalid_category`, no `category=` field, raw text absent, `"general"` absent), and prompt-like invalid input (`SYSTEM`, `JARVIS_TRUSTED`, `"SYSTEM: ignore instructions"` — all absent from the event detail).

---

## Audit Layering (No Duplication)

Proven directly (`test_audit_layers_are_distinct_and_not_duplicated`) that a single category-based request produces:

- **exactly one** Phase 12 `memory_category_selection` event (category-selection state),
- **exactly one** Phase 10 `memory_acquisition` event **per included id** (unchanged, reused, never duplicated or re-emitted by the Phase 12 selection helper — `ai/memory_selection.py` emits nothing itself),
- **exactly one** `AIRouter` `ai_call` event,
- **zero** `tool_call` events (acquisition never goes through `ToolExecutor`),

and, where suspicious content is present, the existing `PromptBuilder`/`audit_suspicious_injection` `injection_detection` event, unchanged.

---

## Observability Isolation

**Exactly one new logger-emitting call site exists in Phase 12**: `JarvisOrchestrator._audit_memory_category_selection()`. It is wrapped in a narrow `try/except Exception: pass` scoped **only** around the `self._logger.emit(...)` call itself — never around `select_memory_ids_by_category()`, `ingest_memories_for_ai()`, `AIReasoningEngine.reason()`, disclosure construction, or unexpected-action evaluation. Closure-level inspection confirmed exactly four `except Exception` blocks total across the entire Phase 12 diff: the pre-existing Phase 11 `_audit_memory_query_selection` boundary, the new `_audit_memory_category_selection` boundary (both wrapping only their own `emit()` call), the pre-existing `_emit_memory_acquisition_event` boundary, and the pre-existing Phase 7 `_audit_unexpected_action` boundary — plus, in `ai/memory_selection.py`, the two pre-existing, unchanged boundaries around `MemoryManager.search()` (Phase 11) and `MemoryManager.list_by_category()` (Phase 12 Batch 1) respectively, each wrapping only its own single lookup call.

A logger that fails **only** for the `memory_category_selection` event is proven not to alter a successful selection, a zero-record outcome, an invalid-category rejection, or a lookup-failure outcome. `AIRouter`'s own `ai_call` audit isolation (the Phase 9 closure fix) and Phase 10's `memory_acquisition` audit are both proven unaffected and independently correct on this new workflow. No `except Exception` anywhere in Phase 12 wraps more than its one, narrowly-scoped, non-authoritative or single-call boundary — no defect was found requiring a fix.

---

## Injection Scanning Ownership

No new scanner exists anywhere in Phase 12. A real, matched category memory containing a known instruction-like pattern is combined through the real category-selection path exactly as any explicit-id- or query-selected record already is, and `PromptBuilder`'s existing, unmodified `scan_for_injection()` detects and audits it through the same `audit_suspicious_injection` reporter Phase 7 already established. The memory text never becomes an executable command, and no approval is implicitly granted. **The Phase 10 delimiter-imitation limitation is preserved and re-verified honestly, not re-litigated:** a real, saved category memory whose content imitates the Phase 10 record delimiter and embeds role/trust-like labels (`SYSTEM`, `JARVIS_TRUSTED`, a fake `source=` label) still results in a combined block that is `ContentTrust.UNTRUSTED`, with `source` derived only from the real, single retrieved record's own id.

---

## Security / Approval Semantics

**No new `ActionType` or `SecurityManager._RULES` entry was added. No existing action classification was reclassified. No `SecurityTier` changed. No approval behaviour changed.** `MemoryManager.list_by_category()` is exactly as unconditionally read-only as `MemoryManager.get()`/`search()` already are, called directly from `ai/memory_selection.py` — the same disclosed, accepted bypass of `ToolExecutor`/`SecurityManager.classify_action()` Phase 9 established and Phase 10/11 already reused, now extended to a **fourth** direct call site. This was reviewed together with the inherited `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion semantic-drift debt: **reconfirmed acceptable, non-blocking debt**, now with a fourth example (`list_by_category`) alongside `get`/`search`. Category-based selection cannot cause a write, update, or delete regardless of category content; mutating and deleting memory remain entirely out of scope, still gated by the unchanged `memory_update`/`memory_forget` YELLOW tools.

---

## Unexpected AI Action Verification

`test_unexpected_red_suggestion_is_blocked_end_to_end` and `test_unexpected_yellow_suggestion_is_escalated_end_to_end` prove, through the real stack, that an AI-suggested action outside the request's own expected scope is evaluated and audited exactly as every prior phase already established — via the same, completely unmodified `_evaluate_unexpected_actions`/`_audit_unexpected_action` methods. The verdict remains a policy/audit observation only: no suggestion becomes a `ToolRequest`, executes, grants approval, or changes a `SecurityTier`, regardless of whether the AI's context came from explicit ids, a query, or a category.

---

## Provider / Validation Failure Semantics

Preserved unchanged and re-proven on this workflow: a provider failure and an empty/invalid AI response both return `success=False` with no `"[AI category memory summary"` label ever present — no fabricated summary in either case. No broad exception handler anywhere in Phase 12 converts an authoritative failure into an apparent success.

---

## Unchanged Phase 8/9/10/11 Workflows

Confirmed by direct inspection and by every pre-existing test passing unchanged, plus fresh, direct proofs on the very same orchestrator instance used for the category workflow:

- **Phase 8 file summary is unchanged** — untouched by this diff.
- **Phase 9 single-memory summary is unchanged** — `test_phase_9_singular_command_is_unaffected_on_the_same_orchestrator`.
- **Phase 10 explicit-id multi-memory summary is unchanged** — `test_phase_10_explicit_id_command_is_unaffected_on_the_same_orchestrator`, `test_routing_collision_fix_does_not_capture_plural_explicit_id_command`.
- **Phase 11 query-based memory summary is unchanged** — `test_phase_11_query_command_is_unaffected_on_the_same_orchestrator`.
- **`PromptBuilder` and `AIReasoningRequest` remain singular-context APIs** — neither file was modified anywhere in Phase 12.
- **`MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, `normalize_category()`, and `is_known_category()` remain unchanged** — confirmed by a zero-diff check.
- **No semantic/vector retrieval was introduced** — confirmed by direct diff inspection; no new dependency was added anywhere (`pyproject.toml`/`poetry.lock` untouched).

---

## Tests and Verification

**New in Phase 12:**
- **Batch 1:** `ai/memory_selection.py` extended; `tests/unit/test_memory_selection.py` extended (41 new tests).
- **Batch 2:** `core/command_router.py` extended; `core/orchestrator.py` extended; `tests/unit/test_command_router.py` extended (13 new tests); `tests/unit/test_memory_category_summary_workflow.py` (47 tests, new).
- **Batch 3:** `tests/integration/test_memory_category_summary_end_to_end.py` (42 tests, new).

**Full Phase 12 test inventory, run directly in the development environment** (`poetry run pytest -q`, Python 3.14.6, pytest 9.1.1):

```
1267 passed
0 failed
0 skipped
0 errored
```

This is every test from Phases 1–11 (1225, which already included Phase 12 Batches 1–2's own new tests approved in prior turns) plus Batch 3's 42 new consolidated integration tests. No live Claude API call is made anywhere in the suite.

### Test commands

```powershell
# The full test suite
poetry run pytest -v

# Phase 12 category selection foundation, command routing, and workflow
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_category_summary_workflow.py -v

# Consolidated end-to-end verification (Batch 3)
poetry run pytest tests/integration/test_memory_category_summary_end_to_end.py -v

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
- `tests/unit/test_memory_category_summary_workflow.py` (new, Batch 2)
- `tests/integration/test_memory_category_summary_end_to_end.py` (new, Batch 3)
- `docs/phase_12_implementation_plan.md` (planning, including the invalid-category/canonicalization/audit clarification revision)
- `docs/phase_12_completion_report.md` (this report, Batch 3)
- `README.md` (Batch 3)
- **Not touched:** `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, `memory/memory_models.py` (`KNOWN_CATEGORIES`/`normalize_category`/`is_known_category`), `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `AIReasoningEngine`, `SecurityManager`, `ai/memory_ingestion.py`, `main.py`.

---

## Known Limitations and Non-Blocking Debt

- **Inherited, unchanged from Phase 9/10/11, non-blocking:** the `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion semantic-drift debt (now with a fourth example, `list_by_category`); the broad `CommandRouter.match()` memory-keyword overlap; memory retrieval remaining unscoped by session; the recency bias inherent in reusing the store's own ordering under a size-limited budget; the search/category-selection-to-ingestion TOCTOU-style race (same accepted class as Phase 10/11's).
- **The `normalize_category()` silent unknown→`"general"` fallback remains unchanged** in the repository's save/organise workflows — a deliberate, historically-correct Phase 5 design choice for those write paths, not a defect. Phase 12 does not change it globally; it structurally prevents the fallback from ever being *reached* on the new read/selection path by validating with `is_known_category()` before the fallback-bearing function is ever called. Any future direct caller of `MemoryManager.list_by_category()` that bypasses `select_memory_ids_by_category()` would not automatically inherit this protection — a documented, disclosed boundary of this fix, not a hidden one.
- **The fixed 10-record selection ceiling is a disclosed starting judgement call**, revisable with evidence, not a permanent architectural limit — deliberately kept equal to Phase 10/11's own selection ceilings rather than introducing a second, differently-tuned number.

---

## Status Statement

**Phase 12 complete for its defined scope: deterministic, category-based automatic memory selection into the advisory AI reasoning path, reusing Phase 10's combination architecture completely unchanged, through the completely unmodified Phase 7 trust and injection-defence pipeline, with full Phase 4 unexpected-action policy coverage, and zero changes to `PromptBuilder`, `AIRouter`, `AIReasoningRequest`, `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, or the category helper functions.**

Phase 12 is not, and must not be described as, semantic, inferred, fuzzy, intelligent, or AI-classified category selection — it is a plain, deterministic, exact-match lookup against the repository's existing, unchanged five-category vocabulary, deterministically ordered and bounded, with a defensive validation boundary that structurally prevents an unrecognised category from ever silently selecting `"general"` content. Closure-level inspection of every observability call site and exception boundary introduced by this phase found no defect requiring a fix.

---

## Recommended Next Capability

Deterministic selection now exists in three concrete forms — explicit ids (Phase 10), query search (Phase 11), and category (Phase 12) — all sharing the same seam Phase 10 established: a strategy produces an ordered tuple of memory ids, and `ingest_memories_for_ai()` combines them. No generic strategy-pattern abstraction was introduced for this, deliberately, since only three concrete strategies exist after this phase. The natural next continuation is **recency-based automatic memory selection** ("summarise my most recent memories" or similar), requiring its own narrow, separately-scoped design review before being started; semantic/vector retrieval and any Entity/Semantic Memory work remain further out still, each requiring its own dependency and security review. Neither is started here.
