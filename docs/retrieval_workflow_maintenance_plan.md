# Retrieval Workflow Maintenance Plan — Shared Post-Selection AI Summary Helper and Message-Constant Centralisation

Status: **Planning and adversarial review only. No production code, tests,
README changes, or commits accompany this document.**

**This is explicitly not a phase.** It adds no new user-facing capability,
no new command, no new selector, and no new retrieval semantics. Every
`docs/phase_N_*` document in this repository corresponds 1:1 to a genuine
new capability (confirmed by direct inspection: `phase_1` through `phase_14`
completion reports and implementation plans, no exceptions, no precedent for
a non-capability "phase"). Naming this "Phase 15" would misrepresent it to
any future reader as a capability addition. This document is deliberately
named outside that convention (§12).

Authoritative repository state this plan builds on, verified directly, not
assumed: HEAD `dc341a6e157550182202e3e909319699a92487b3` ("Complete Phase 14
user-controlled bounded recent-memory count"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean. `poetry run
pytest -q` — **1546 passed, 0 failed** — re-run fresh for this planning
turn, not taken from Phase 14's own completion report. No pre-existing
failure exists.

---

## 1. Purpose

Phase 14's own closure predicted that the post-selection AI-summary
workflow duplication and the AI-reasoning message-constant duplication
across the Phase 10–14 memory-summary handlers might have reached the
point where a narrow, compatibility-preserving internal refactor is
justified. This document performs the actual repository-grounded
investigation that prediction called for — a fresh line-by-line
duplication map, a rejection-tested candidate analysis, an adversarial
review, and a final, explicit go/no-go decision — rather than assuming the
prediction was correct.

---

## 2. Scope

Investigate, and decide whether to schedule (not perform) a narrow,
separately-scoped maintenance refactor covering only:

- the byte-for-byte-identical tail shared by `_handle_memory_set_summary_request`, `_handle_memory_query_summary_request`, `_handle_memory_category_summary_request`, `_handle_memory_recent_summary_request`, and `_handle_memory_recent_count_summary_request` (Phases 10–14's own handlers), and
- the five byte-identical copies of the "AI reasoning not enabled"/"AI reasoning unavailable" message pair across those same five handlers.

## 2.1 Non-Goals

No selector change, no result-model change, no command/routing change, no
audit-event-shape change, no trust/security change, no new dependency, and
no capability addition of any kind. Manager-unavailable messages,
zero-selection messages, lookup-failure messages, summary labels, and
selection-disclosure wording are explicitly **not** in scope for
centralisation — confirmed below (§5) to be genuinely selector-specific,
not coincidentally duplicated.

---

## 3. Repository Truth (fresh re-inspection)

- **Branch:** `phase-4-ai-reasoning-and-write-actions`. **HEAD:**
  `dc341a6e157550182202e3e909319699a92487b3` (`dc341a6`). **Status:** clean.
- **Full suite:** 1546 passed, 0 failed, re-run before this planning turn.
- **Handlers re-read in full, fresh, this turn** (exact current line ranges
  in `core/orchestrator.py`): `_handle_memory_query_summary_request`
  (908–1096), `_handle_memory_category_summary_request` (1098–1317),
  `_handle_memory_recent_summary_request` (1319–1506),
  `_handle_memory_recent_count_summary_request` (1508–1718),
  `_handle_memory_set_summary_request` (1720–1885).
- **Shared helper methods, confirmed by diff to be completely untouched
  since before Phase 14** (`git diff 04f8b613... HEAD -- core/orchestrator.py`
  shows zero added/removed `def` lines for any of them): `_build_memory_set_disclosure`
  (1933), `_audit_memory_set_acquisition` (2033), `_evaluate_unexpected_actions`
  (2556), `_emit_memory_acquisition_event` (2422).
- **`ai/reasoning_engine.py`, `ai/router.py`, `ai/context_models.py`,
  `ai/prompt_builder.py`, `security/security_manager.py`**: confirmed
  zero-diff since before Phase 14 (`git diff 04f8b613... HEAD` on these
  files produces no output).
- **All memory-summary label/message constants**, enumerated fresh by
  direct grep (`core/orchestrator.py` lines 107–304): 7 summary labels (one
  per phase, including file/Phase 8 and singular/Phase 9), 7
  not-enabled/unavailable message pairs, 6 manager-unavailable messages, 2
  empty-input messages (Query, Category only), 1 shared zero-records
  constant, 1 shared lookup-failure-fallback constant — full detail in §5.
- **No test anywhere references any of these constants by name** —
  confirmed by repository-wide grep (`grep -rn
  "_AI_REASONING_NOT_ENABLED_MESSAGE\|_AI_REASONING_UNAVAILABLE_MESSAGE"
  tests/` returns nothing) — every test asserts only the user-visible
  response text.
- **No workflow/integration test uses mocking or monkeypatching** on any
  orchestrator internal (`grep -rln "monkeypatch\|mock\.patch\|MagicMock"
  tests/unit/test_memory_*summary_workflow.py
  tests/integration/test_memory_*summary_end_to_end.py` returns nothing) —
  every test exercises `orchestrator.handle_request(...)` as a black box
  and inspects the response/audit events, never handler internals.

---

## 4. Exact Duplication Map

Line-by-line comparison of all five handler bodies, fresh, this turn — not
a rough estimate.

| Block | Set (P10) | Query (P11) | Category (P12) | Recent (P13) | RecentCount (P14) | Classification |
|---|---|---|---|---|---|---|
| `plan = self._planner.create_plan(...)` | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 1 line, byte-identical, all 5 |
| Pre-selector validation | parse+dedupe ids (18 lines, 2 blocks) | empty-query check (6 lines) | empty-category check (6 lines) | none | none (deferred to selector) | **A** — genuinely different shape per selector; must remain explicit |
| Reasoning-availability check | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 5 lines, identical shape, only the message constant token differs |
| MemoryManager-availability check | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 5 lines, identical shape, only the message constant token differs |
| Selector invocation | n/a (uses parsed ids directly) | `select_memory_ids_by_query(...)` | `select_memory_ids_by_category(...)` | `select_recent_memory_ids(...)` | `select_recent_memory_ids_by_count(...)` | **A** — genuinely different call per selector; must remain explicit |
| Selector audit call | n/a | `_audit_memory_query_selection` | `_audit_memory_category_selection` | `_audit_memory_recent_selection` | `_audit_memory_recent_count_selection` | **A** — 4 distinct methods with genuinely different logged fields; must remain explicit |
| Selector-state early returns | cardinality-limit message (distinct) | 2 states (zero_matches, failed), own inline messages | 3 states (invalid_category, zero_matches, failed), own inline messages | 2 states (zero_matches, failed), **shared** constants | 3 states (invalid_count, zero_matches, failed) — zero/failed **reuse Recent's own shared constants**, invalid_count has its own inline message | **A** — genuinely different cardinality and wording per selector; must remain explicit |
| `ingestion = ingest_memories_for_ai(...)` | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 1 line, byte-identical except the ids-expression argument |
| `self._audit_memory_set_acquisition(...)` | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 1 line, byte-identical, all 5 |
| `if not ingestion.success: return ...` | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 5 lines, byte-identical including the fallback string, all 5 |
| `AIReasoningRequest(...)` construction | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 5 lines, byte-identical, all 5 |
| `reason()` call + unavailable-check | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 6 lines, identical shape, only the message constant token differs |
| Suggested-step formatting | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 4 lines, byte-identical, all 5 |
| Selector-specific count/disclosure sentence | none (0 lines) | 1 line, echoes query | 3 lines, echoes canonical category | 3 lines, no criterion | 1 line, no criterion (identical wording to Recent's own) | **A** — genuinely different wording/cardinality per selector; must remain explicit |
| `_build_memory_set_disclosure(ingestion)` append | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 3 lines, byte-identical, all 5 |
| `JarvisResponse(success=True, ...)` construction | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 5 lines, identical shape, only the label constant token differs |
| Comment + `_evaluate_unexpected_actions(...)` | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 3 lines (2 comment + 1 call), byte-identical, all 5 |
| `return response` | ✓ | ✓ | ✓ | ✓ | ✓ | **B** — 1 line, byte-identical, all 5 |

**No block classifies as C (identical today but likely to diverge) or D
(already semantically drifted).** Every "A" block is genuinely,
architecturally distinct (a real cardinality/wording/selector-call
difference), not incidental similarity; every "B" block is verified
byte-identical except for a single substituted identifier (a constant name
or an ids-expression).

**Exact count, the post-selector "B" tail** (from `ingestion =
ingest_memories_for_ai(...)` through `return response`, excluding the one
selector-specific sentence): **43 lines** in the Query/Category/
Recent/RecentCount handlers (Set's own span is 3 lines shorter, since it
has no selection-count sentence at all) — of which **40 lines are 100%
byte-identical across all five handlers**, and **3 lines** each contain
exactly one substituted token (the ids-expression argument, the
`UNAVAILABLE_MESSAGE` constant name, the `SUMMARY_LABEL` constant name).
Including the two availability-check blocks (10 further byte-identical
lines, modulo one substituted constant token each), the total near-identical
skeleton is **~50 lines per handler, ~250 lines across all five**, the
overwhelming majority of it exact, repeated text.

---

## 5. Message Constant Duplication — Exact Findings

**Exact five byte-identical copies**, confirmed by direct grep this turn:

```
_MEMORY_SET_AI_REASONING_NOT_ENABLED_MESSAGE
_MEMORY_QUERY_AI_REASONING_NOT_ENABLED_MESSAGE
_MEMORY_CATEGORY_AI_REASONING_NOT_ENABLED_MESSAGE
_MEMORY_RECENT_AI_REASONING_NOT_ENABLED_MESSAGE
_MEMORY_RECENT_COUNT_AI_REASONING_NOT_ENABLED_MESSAGE
```
— all five: `"AI reasoning is not enabled, so I can't summarise these memories' contents."`

```
_MEMORY_SET_AI_REASONING_UNAVAILABLE_MESSAGE
_MEMORY_QUERY_AI_REASONING_UNAVAILABLE_MESSAGE
_MEMORY_CATEGORY_AI_REASONING_UNAVAILABLE_MESSAGE
_MEMORY_RECENT_AI_REASONING_UNAVAILABLE_MESSAGE
_MEMORY_RECENT_COUNT_AI_REASONING_UNAVAILABLE_MESSAGE
```
— all five: `"AI reasoning could not produce a summary for these memories right now."`

(Phase 8's file-summary and Phase 9's singular-memory-summary pairs are
**not** part of this duplication — each carries genuinely distinct
singular/file-specific noun phrasing, e.g. "this file's contents"/"this
memory's contents," and are correctly excluded from centralisation.)

**Are these five semantically identical, or merely text-identical?**
Genuinely semantically identical, not coincidental: in all five cases the
message fires at the exact same logical moment — before or immediately
alongside selection, when the advisory reasoning engine itself is off or
unavailable — and describes exactly the same fact each time ("no summary
of the selected memory set can be produced right now"). None of the five
call sites has any selector-specific nuance this message could or should
carry; the *criterion* (query text, category, count) is never mentioned in
this particular message at any of the five sites.

**Does any copy have a different semantic owner?** No — all five are
owned by the same conceptual event (reasoning engine state), differing
only in which command triggered the check.

**Do the names carry useful selector meaning?** Only nominally (the prefix
identifies which phase declared it); the *value* carries zero
selector-specific information, confirmed above.

**Do tests assert selector-specific constant names, or only user-visible
text?** Confirmed: **only user-visible text**, everywhere, with no
exception. This directly de-risks centralisation — no test would need to
change its assertions if the underlying constant were renamed or shared,
only if the actual message *text* changed, which this plan does not
propose.

**Already-correct sharing precedent, found this turn:** Phase 14 already
directly reuses two of Phase 13's own constants
(`_MEMORY_RECENT_ZERO_RECORDS_MESSAGE`,
`_MEMORY_RECENT_LOOKUP_FAILURE_FALLBACK_MESSAGE`) rather than declaring its
own copies — a positive, already-implemented example of exactly the kind
of justified sharing this plan considers, extended one step further to the
one place it was not yet applied (the not-enabled/unavailable pair).

**Manager-unavailable, zero-selection, lookup-failure, and label
constants are correctly excluded from centralisation** — verified fresh:
manager-unavailable messages genuinely differ by operation verb
("summarise these memories" / "search your memories" / "look up memories
by category" / "look up recent memories" / "look up recent memories by
count"); zero-matches/failed wording is selector-owned where it differs
(Query, Category) and already correctly shared where it is identical
(Recent, RecentCount); labels are deliberately distinct, user-facing
phase identifiers.

**Evaluated:**
- **A — leave duplicated.** Safe, current state; the growing, unenforced
  duplication (now five copies) is real but low-severity.
- **B — one shared private `_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE`
  and one shared `_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE`
  constant, referenced by all five call sites — chosen.** Confirmed safe by
  the test-architecture finding above (no test depends on the constant
  name, only the text, which is unchanged).
- **C — helper owns the shared messages internally.** **Rejected** — this
  would couple two independently-varying decisions (the workflow *shape*,
  §6, and the message *wording*) into one artifact. A handler must still
  be free to pass its own value if a genuine, currently-unforeseen
  divergence is ever needed without touching the shared workflow helper;
  keeping the message as a helper *parameter*, sourced from a shared
  *constant* at each call site, preserves that independence.
- **D — another narrow design.** Not needed; B is sufficient and minimal.

---

## 6. Helper Boundary Candidates

| Candidate | Benefit | Semantic risk | Params/callbacks | Return type | Selector-specific wording stays outside? | Audit timing visible? | Unexpected-action scope visible? | Readability | Blast radius | Test impact | Reduces real drift or just line count? |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **A — no refactor** | None | None | n/a | n/a | n/a | Yes (fully explicit) | Yes | Baseline, already good | None | None | n/a |
| **B — extract only `AIReasoningRequest` + `reason()` + unavailable handling** | Small; saves ~12 lines/handler | Low | `ingestion, user_request, session_id, plan, unavailable_message` (5) | `AIReasoningResult \| None`, forcing caller to re-check and re-build the failure response itself | Yes | Yes | Yes | Marginal — barely reduces duplication, adds one extra call for little payoff | Very low | Very low | **Mostly line count** — the bigger, fully-identical tail (disclosure, response, unexpected-action) stays duplicated 5×. **Rejected as insufficient.** |
| **C — extract post-ingestion AI summary workflow** (ingestion-success already confirmed by caller → `AIReasoningRequest` → `reason()` → suggested-steps → selection-count sentence (passed in, precomputed) → Phase 10 disclosure → response construction → unexpected-action evaluation) | Captures the full ~40-line byte-identical tail; collapses 5 independent `_evaluate_unexpected_actions` call sites into 1 | Low — the helper never sees a selector result, only an already-successful `ingestion` and a precomputed string | `ingestion, user_request, session_id, plan, ai_unavailable_message, label, selection_sentence` (7) | `JarvisResponse` | Yes — selection_sentence is precomputed by the caller, who alone knows the selector-specific wording | **Yes** — `ingest_memories_for_ai()`/`_audit_memory_set_acquisition()`/`if not ingestion.success` stay in each handler, unchanged | Yes — helper calls `_evaluate_unexpected_actions()` itself (§8), preserving the exact existing adjacency | Genuine simplification without hiding a decision boundary | Low-medium — touches 5 call sites, but each substitution is mechanical | Low — black-box tests are unaffected (confirmed, §3) | **Reduces real drift risk** — the tail can no longer silently diverge across 5 call sites, and unexpected-action evaluation can no longer be accidentally skipped or duplicated in a future 6th handler |
| **D — extract full post-selection workflow** (selected ids → `ingest_memories_for_ai()` → acquisition audit → AI reasoning → disclosure → response → unexpected-action) | Marginally larger than C (absorbs 3 more identical lines) | **Higher** — hides the audit-then-check sequence, a genuine decision boundary (§9), inside the helper; a trust reviewer auditing "is acquisition always audited before success is checked" must now look inside the helper rather than the handler | `selected_ids, user_request, session_id, plan, ai_unavailable_message, label, selection_sentence` (7, but now also implicitly needs `self._memory_manager`) | `JarvisResponse` | Yes | **No** — this is exactly the risk this candidate introduces | Yes | Marginally worse than C for exactly this reason | Low-medium | Low | Only marginally more drift-risk-reduction than C, at a real readability/reviewability cost. **Rejected** in favour of C. |
| **E — generic selector-driven pipeline/strategy abstraction** | None found | **High** — would require the helper to understand `QuerySelectionResult`/`CategorySelectionResult`/`RecentSelectionResult`/`RecentCountSelectionResult` polymorphically; no code evidence supports this (state counts genuinely differ: 2/3/2/3(with distinct sub-cases)) | Would require callbacks or a shared result protocol | Unclear | No — a generic pipeline would need to genericise the very wording that must stay selector-specific | Unclear | Unclear | Would obscure exactly the selector-specific differences that are load-bearing, not incidental | High | High | Reduces line count at the cost of hiding real, necessary differences. **Rejected outright**, consistent with every prior phase's own explicit instruction not to build this. |

**Recommended: Candidate C.** B is insufficient (too narrow to matter). D
and E are rejected — D for hiding a load-bearing audit-ordering boundary
for a marginal gain over C, E for requiring exactly the polymorphic
result-type understanding this plan's own instructions forbid absent
direct evidence, which does not exist.

---

## 7. Designed Helper Contract (design only — not implemented)

```python
def _build_memory_summary_response(
    self,
    *,
    ingestion: MemorySetIngestionResult,
    user_request: str,
    session_id: int | None,
    plan: Plan,
    ai_unavailable_message: str,
    label: str,
    selection_sentence: str,
) -> JarvisResponse:
    """Precondition: ingestion.success is True. Callers check this and
    return their own honest failure response before ever calling this
    helper - exactly as every existing handler already does inline."""
```

**Ownership boundaries, decided explicitly:**

| Concern | Owner |
|---|---|
| `selected_ids` | **Handler** — never passed to or seen by the helper (structurally prevents any risk of the helper copying/sorting/deduplicating them) |
| `user_request` | Handler supplies; helper forwards verbatim into `AIReasoningRequest.user_input` |
| `session_id` | Handler supplies; helper forwards verbatim |
| `ingestion` | Handler produces (via the unchanged `ingest_memories_for_ai()` call, already audited and success-checked by the handler); helper only reads `ingestion.context`/passes `ingestion` to `_build_memory_set_disclosure()` |
| `MemoryManager` availability | **Handler** — checked before the selector is ever called, entirely outside the helper's concern |
| `AI reasoning` availability | **Handler** — checked before the selector is ever called (`self._reasoning is None`), entirely outside the helper's concern |
| not-enabled message | **Handler** — returned directly by the handler on its own early-return branch; never seen by the helper at all (the helper only ever runs once reasoning is confirmed active) |
| unavailable message | **Caller-supplied parameter** (`ai_unavailable_message`), sourced from the new shared constant (§5) at each of the 5 call sites |
| selector-specific selection disclosure | **Handler precomputes the full sentence string** (`selection_sentence`) using its own selector's `match_count`/criterion; helper only appends it verbatim — never a callback |
| summary label | **Caller-supplied parameter** (`label`), sourced from each handler's own existing, distinct constant |
| acquisition auditing | **Handler** — `_audit_memory_set_acquisition()` called before the helper, immediately after `ingest_memories_for_ai()`, unchanged (§9) |
| Phase 10 disclosure | **Helper** — calls the existing, unmodified `_build_memory_set_disclosure(ingestion)` and appends it, exactly where every handler already does today |
| suggested steps | **Helper** — identical, byte-for-byte-copied logic |
| `JarvisResponse` construction | **Helper** — builds the final success response |
| unexpected-action evaluation | **Helper** — calls `self._evaluate_unexpected_actions(response, result, session_id)` itself (§8), preserving the exact existing immediate adjacency to response construction |

**The helper does not own selector invocation** (confirmed — it never
calls any `select_*` function) **and does not understand any of the four
selection-result types** (confirmed — its signature contains no
`QuerySelectionResult`/`CategorySelectionResult`/`RecentSelectionResult`/
`RecentCountSelectionResult` parameter; it only ever receives an
already-successful `ingestion` and a precomputed string).

**Exact preserved timing**, confirmed unchanged from every existing
handler: selector → selector audit → selector-state branching → ingestion
→ acquisition audit → ingestion-success branch (all in the **handler**,
unchanged) → *helper begins* → `AIReasoningRequest` → `reason()` →
reasoning-unavailable branch → suggested steps → selection sentence
append → Phase 10 disclosure append → response construction →
unexpected-action evaluation → return.

---

## 8. Unexpected-Action Ownership Decision

**The helper calls `_evaluate_unexpected_actions()` itself**, rather than
returning `(response, result)` for the handler to call it. Justification,
not a line-count choice: in all five existing handlers, without exception,
this call immediately follows response construction, using exactly the two
objects (`response`, `result`) the same code block just produced — there is
no existing or plausible variant where a caller would want to construct the
response and *not* immediately evaluate unexpected actions, or evaluate them
against a *different* response. Returning both objects out of the helper
just to have the caller immediately re-pass them into the same fixed call
would add an indirection with no informational or safety benefit, and would
reintroduce exactly the "5 independent call sites that could accidentally
diverge or be forgotten" risk this refactor exists to remove.

---

## 9. Audit-Visibility Decision

**`ingest_memories_for_ai()` → `_audit_memory_set_acquisition()` → `if not
ingestion.success` remains visibly explicit in each handler, not moved into
the helper** (ruling out Candidate D, §6). This sequence is a genuine
decision boundary — the moment a partial or total ingestion failure is
caught and audited — and keeping it visible per-handler preserves a trust
reviewer's ability to confirm, by reading one handler alone, that
acquisition is always audited before success is checked, without needing to
also inspect a shared helper's internals.

**`AIReasoningRequest` construction, by contrast, is safe to move into the
helper.** Unlike the audit-then-check sequence, this construction is pure,
invariant data assembly (`user_input=user_request, context_block=ingestion.context,
session_id=session_id` — always exactly these three fields, from exactly
these three sources, in all five handlers today) with no per-selector
decision content at all; centralising it hides no per-selector trust
decision, only a mechanical repetition.

This distinction — decision boundaries stay visible per-handler; inert,
invariant data assembly may be centralised — is the guiding principle
applied throughout this plan, not a blanket "fewer lines is better" rule.

---

## 10. Failure-Boundary Review

Verified for the proposed Candidate C helper:

- **No new broad `except Exception` is required.** The helper introduces
  no new I/O, logging, or provider call of its own; every failure-prone
  operation it touches (`self._reasoning.reason(...)`, `self._logger.emit(...)`
  inside `_audit_unexpected_action`) already has its own existing, narrow
  guard, unchanged.
- **Audit emit isolation remains narrow** — `_audit_unexpected_action`'s
  own `try/except Exception: pass`, scoped only around its `emit()` call,
  is untouched by this proposal.
- **Ingestion failure remains authoritative** — the `if not
  ingestion.success` branch stays in the handler (§9), entirely outside
  the helper; the helper's own precondition ("only ever called with a
  successful `ingestion`") makes this structurally impossible to bypass
  from inside the helper.
- **Provider/validation failure still maps to reasoning unavailable** —
  `AIReasoningEngine.reason()`'s own contract (`None` on any provider or
  validation failure) is completely unchanged; the helper's `if result is
  None: return JarvisResponse(..., ai_unavailable_message, ...)` branch is
  a verbatim copy of the existing code, not a redesign.
- **Logger failure cannot alter workflow success/failure** — re-confirmed
  by re-reading `AIRouter._emit_audit_event` and `AIReasoningEngine.reason()`
  fresh this turn (both unchanged since before Phase 14, confirmed by
  diff, §3): the historical observability bug class (a raising logger
  inside `route()` propagating through `reason()`'s broad `except Exception:
  return None` and silently turning a real success into "unavailable") was
  closed at the `AIRouter._emit_audit_event` layer, which this proposal
  does not touch at all. The maintenance refactor introduces no new
  logger-emitting call site whatsoever — it only relocates existing calls
  to already-safe methods (`_build_memory_set_disclosure`,
  `_evaluate_unexpected_actions`) into a new method body.
- **No selector failure is swallowed by the helper** — the helper never
  receives a selector result of any kind (§7), so there is nothing for it
  to swallow.
- **No result state is flattened into a generic boolean** — the helper's
  only externally-supplied "state" is the already-fully-resolved
  `ingestion` object and a plain string; no selector `success`/`zero_matches`/
  `invalid_*`/`failed` state ever reaches it.

**This maintenance refactor does not reopen the historical `AIRouter`
observability bug class** — it touches none of the code that class lived
in, and introduces no new logging.

---

## 11. Trust/Injection Review

Confirmed the proposed helper leaves the trust path exactly unchanged:
selected ids → `ingest_memories_for_ai()` (handler, unchanged) → one
`AIContextBlock` → `ContentTrust.UNTRUSTED` → `AIReasoningRequest.context_block`
(helper, verbatim-copied construction) → `PromptBuilder` → real
`scan_for_injection()`/report path → `AIRouter` (all unchanged, called
exactly as today). **The helper does not construct `AIContextBlock`
manually** — it only ever reads the already-constructed
`ingestion.context` produced by the unmodified `ingest_memories_for_ai()`.
**The helper does not alter source/provenance** — `ingestion.context.source`
is never touched or reconstructed. **The helper does not merge live
selector criteria into the memory context** — `selection_sentence` is
appended only to `summary` (the AI's own output plus Jarvis-owned
disclosure text), never to `ingestion.context`/`AIReasoningRequest.context_block`.
**The helper does not inspect or transform memory content** — it never
reads `ingestion.context.text` or any per-record content at all.

---

## 12. AI Authority and Unexpected-Action Confirmation

Confirmed the proposed helper cannot: select ids (never receives a
selector result or raw ids); change selected order (never receives ids at
all, only the already-combined `ingestion`); request more memory (calls no
selector, no `MemoryManager` method, nothing `ai/memory_ingestion.py`-adjacent
beyond reading the already-produced `ingestion` object); execute AI
suggestions (never references `self._executor`); call `ToolExecutor`
(same); create approvals (same — `_evaluate_unexpected_actions`'s own
unchanged contract remains verdict/audit only). `_evaluate_unexpected_actions()`
remains the sole post-reasoning advisory-action evaluation seam, called
from exactly one place (inside the new helper) instead of five,
**reducing**, not introducing, the risk of an evaluation being
accidentally skipped or duplicated by a future sixth handler.

---

## 13. Test-Architecture Impact

- **Zero tests patch or spy on any handler-local call** (§3) — every
  existing workflow/integration test drives `orchestrator.handle_request(...)`
  and inspects the response/audit events, never handler internals.
  Extracting Candidate C would therefore require **no rewrites** to any
  existing test; observable behaviour (response text, audit fields,
  provider call counts, context trust) is unchanged byte-for-byte by
  design.
- **A shared helper deserves its own focused unit tests** nonetheless
  (not a replacement for the existing black-box coverage, an addition):
  at minimum, one test per outcome the helper itself can produce
  (reasoning-unavailable, successful response with/without a Phase 10
  disclosure, unexpected-action evaluation firing) exercised directly
  against the helper method, plus a proof that it never touches
  `self._executor`/`self._memory_manager` selection methods.
- **Existing tests already protect every one of the required invariants**
  the task asks to confirm: no provider call on selector failure (present
  in all 5 workflow/integration suites today); selected id order
  (present); Phase 10 ingestion reuse (present); acquisition audit timing
  (present, `_acquisition_events`/`_audit_layers_are_distinct_and_not_duplicated`-
  style tests in every integration file); `AIReasoningRequest` fields
  (present, via `_context_slice`/`recorder.received_context` proofs);
  `UNTRUSTED` context (present, every integration file); suggested steps
  (present); selector-specific disclosure ordering (present); summary
  labels (present, `response.message.startswith(...)` in every workflow
  test); unexpected-action verdicts (present, RED/YELLOW proofs in every
  suite); logger-failure isolation (present, selective-failing-logger
  tests in every suite).
- **No existing cross-selector invariant would need to be added purely
  because of this refactor** — the refactor's entire purpose is to
  guarantee, structurally, an invariant the tests already assert
  behaviourally; if the refactor is ever implemented, re-running the full
  existing suite unchanged is itself the correct and sufficient
  regression proof.

---

## 14. Duplicated-Message-Constant Recommendation

**B — one shared `_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE` and
one shared `_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE`**, referenced
by all five call sites (Set/Query/Category/Recent/RecentCount), replacing
the five independently-declared, byte-identical pairs. Text unchanged.
Manager-unavailable, zero-selection, lookup-failure, and label constants
remain untouched and separate (§5).

---

## 15. Proposed Maintenance Batches

The task's own suggested two-batch shape was evaluated against a single
combined batch and **retained, not accepted blindly**: the message-constant
swap (§14) is an almost purely mechanical value substitution with
essentially zero control-flow risk (confirmed safe by the test-architecture
finding, §3/§13), while the helper extraction (§7) is a genuine
control-flow change requiring careful, ordered, one-handler-at-a-time
migration to preserve exact timing (§7's "exact preserved timing"). Keeping
them as two separately-reviewable, separately-revertible batches is safer
than one combined batch, at negligible extra process cost, since both
batches touch the same five handlers and can be verified with the same
full-suite run either way.

### Maintenance Batch 1 — Shared Post-Selection AI Summary Helper

- Add one private orchestrator helper (`_build_memory_summary_response`,
  exact signature in §7).
- Migrate Phase 10–14 handlers one at a time to call it, each replacing its
  own ~40-line tail with one call, in an order that allows re-running the
  full suite after each single migration (Set, then Query, then Category,
  then Recent, then RecentCount, or any order — no handler depends on
  another).
- No selector/result-model changes. No command/routing changes. No audit
  event-shape changes. No trust/security changes.
- Focused helper tests added (§13).
- All existing workflow/integration suites must remain green, unchanged,
  after every single-handler migration, not only at the end.

### Maintenance Batch 2 — Shared Memory-Summary AI Availability Messages and Closure

- Centralise only the two byte-identical message strings (§14).
- Verify exact response text is unchanged (a `diff`-style byte comparison
  against the pre-change constants' values, not merely "tests still pass").
- Add a cross-handler consistency test only if it provides real value
  beyond what already-passing black-box tests provide (a single test
  asserting all five call sites reference the same two shared constants,
  by identity, is cheap and directly prevents the exact drift this batch
  removes — recommended).
- Full semantic-drift review, mirroring the Phase 10–14 checkpoint's own
  method, re-applied to confirm the refactor didn't introduce new drift.
- README unchanged (no user-facing text changes).
- A completion report for this batch is **not** recommended, for the same
  naming-convention reason given in §1/§12 — this repository has no
  established convention for a non-capability maintenance completion
  report, and inventing one risks the same "phase"-shaped misreading this
  document already avoids. A closure summary in the commit message itself
  is sufficient and repository-consistent (mirroring how Phase 6's own
  historical `phase_6_progress_report.md` was itself a narrower, less
  formal document than a full completion report, when the actual work was
  narrower).
- Closure commit.

**Implementation note (added at Batch 2 closure, not a retroactive
rewrite of the above recommendation):** the explicit Batch 2 authorisation
this plan's own §21 required separately requested a dedicated,
unnumbered `docs/retrieval_workflow_maintenance_completion_report.md`,
overriding this section's advisory recommendation against one. This plan
is advisory, not self-authorising (§21); the explicit go-ahead that
followed it is authoritative over this non-binding recommendation. The
report was created; it is explicitly not named `docs/phase_15_*`, for the
same reason given throughout this document.

---

## 16. Exact File Scope (for if/when implementation is authorised)

- `core/orchestrator.py` only, across both batches.
- No new files except the focused helper tests, likely appended to an
  existing orchestrator-adjacent test file rather than a new one (exact
  location to be decided at implementation time, not fixed here).
- No changes to `ai/memory_selection.py`, `ai/memory_ingestion.py`,
  `core/command_router.py`, `security/security_manager.py`,
  `ai/reasoning_engine.py`, `ai/router.py`, `ai/context_models.py`,
  `ai/prompt_builder.py`, `README.md`, or any `docs/phase_N_*` file.

---

## 17. Verification Commands (for if/when implementation is authorised)

```
poetry run pytest tests/unit/test_memory_summary_workflow.py -v
poetry run pytest tests/unit/test_memory_set_summary_workflow.py -v
poetry run pytest tests/unit/test_memory_query_summary_workflow.py -v
poetry run pytest tests/unit/test_memory_category_summary_workflow.py -v
poetry run pytest tests/unit/test_memory_recent_summary_workflow.py -v
poetry run pytest tests/unit/test_memory_recent_count_summary_workflow.py -v
poetry run pytest tests/integration -v
poetry run pytest -v
git diff --check
```

Regression floor: **1546 passed, 0 failed** — may only grow (helper tests
are additive).

---

## 18. Rollback / Stop Conditions (for if/when implementation is authorised)

Stop and report, without proceeding, if at any point during a future
implementation: any existing test's assertion on response text, audit
field shape, or provider call count needs to *change* (not merely be
re-pointed at a helper) to keep passing; the helper's precondition
("only ever called with a successful `ingestion`") cannot be honestly
satisfied for any one of the five handlers; or the byte-for-byte identical
tail turns out, on closer implementation-time reading, to differ in some
way this planning turn's line-by-line comparison missed. Any of these
would indicate the duplication map in §4 was wrong, not merely that the
refactor needs adjusting.

---

## 19. Adversarial Findings

Every question below was checked directly against the Candidate C design;
**none weakened the case for proceeding** — each was closed by the design
itself, not discovered as a new problem requiring a design change.

- **Can selector-specific zero/failure states accidentally move into the
  helper?** No — the helper never receives a selector result (§7).
- **Can the helper flatten selection semantics?** No, same reason.
- **Can acquisition audit timing change?** No — that sequence stays in
  the handler, unchanged (§9).
- **Can ingestion failure wording change?** No — the `if not
  ingestion.success` branch, with its own message, stays in the handler.
- **Can response labels drift?** No — `label` remains a per-call
  parameter sourced from each handler's own existing, distinct constant.
- **Can suggested-step order change?** No — verbatim-copied code.
- **Can Phase 10 disclosure ordering change?** No — same call, same
  position, verbatim.
- **Can `AIReasoningRequest` fields change?** No — verbatim-copied
  construction.
- **Can `UNTRUSTED` context handling change?** No — the helper never
  touches trust; it only forwards `ingestion.context` unchanged (§11).
- **Can logger failure become authoritative?** No — no new logging call
  site is introduced (§10).
- **Can unexpected actions skip evaluation?** No — the helper calls
  `_evaluate_unexpected_actions()` unconditionally, exactly where every
  existing handler already does (§8).
- **Can unexpected actions be evaluated twice?** No — exactly one call
  site remains, down from five, **reducing** this risk rather than
  introducing it.
- **Can a helper accidentally call `ToolExecutor`?** No — nothing in the
  proposed body references `self._executor` (§12).
- **Can a helper create approval behavior?** No — `_evaluate_unexpected_actions`'s
  own unchanged contract remains verdict/audit only.
- **Can selected ids be copied, sorted, or deduplicated?** No — under
  Candidate C, ids never pass through the helper at all; this was one of
  the concrete reasons Candidate D was rejected in favour of C.
- **Does a 6–7 parameter helper actually improve maintainability?**
  Modestly, genuinely: it removes ~40 lines of exact duplication per call
  site (5 call sites) and collapses 5 independent unexpected-action call
  sites into 1, at the cost of one parameter list a reader must learn once.
- **Would two smaller helpers be cleaner, or create abstraction soup?**
  Splitting further was considered and rejected — the pieces (reasoning →
  disclosure → response → unexpected-action) are always used together, in
  the same order, by every caller; one helper at this exact boundary is
  the right granularity.
- **Are the five duplicated messages actually semantically identical, or
  merely text-identical?** Genuinely semantically identical (§5) — not
  coincidental.
- **Would centralizing messages erase useful selector ownership?** No —
  confirmed the *other* messages (manager-unavailable, zero/failure,
  labels) remain separate and selector-owned, since only these two
  specific messages carry zero selector-specific information (§5).
- **Does test churn outweigh the drift risk being removed?** No — test
  churn is confirmed near-zero for both batches (§3/§13); the drift risk
  (five unenforced copies, a ~250-line duplicated skeleton) is real and
  growing with each future selector.

---

## 20. Risks/Debt Carried Forward (regardless of whether this maintenance is later implemented)

- The `SecurityManager`/`ToolExecutor`-bypass architectural debt (Phase
  10–14 checkpoint's own finding, materially reduced but not eliminated by
  Phase 14's AST invariant test) is entirely unrelated to and unaffected
  by this maintenance proposal.
- The SQLite naive-timestamp-on-read-back debt (Phase 13) is unrelated and
  unaffected.
- If Maintenance Batch 1 is implemented, a future sixth selector's handler
  would need to be written *against* the new helper contract from the
  start, rather than by copying an existing handler verbatim — a
  deliberate, intended behaviour change for future authors, not a
  regression.

---

## 21. Final Recommendation

**Implementation is justified.** The duplication is real, precisely
measured (§4), the message-constant risk is real and growing (§5), the
smallest honest helper (Candidate C, §6/§7) has a concrete, narrow,
7-parameter contract that preserves every load-bearing boundary (§8–§12),
the existing test suite already provides sufficient regression protection
with near-zero expected churn (§13), and the adversarial review found no
issue serious enough to withdraw the recommendation (§19). This is
**not** urgent — nothing is broken today — but it is now cheap, safe, and
well-understood enough that deferring it further mainly accumulates more
duplicate call sites for a future implementer to migrate at once.

**Recommended naming: unnumbered "Retrieval Workflow Maintenance"** (Option
C), not Phase 15, not "Phase 14 maintenance," not "Phase 14.1" — confirmed
by direct inspection that every existing `docs/phase_N_*` document
corresponds to a genuine capability addition, with zero precedent for a
non-capability phase, and this work adds no capability at all.

**This plan does not itself authorise implementation.** Per the governing
instructions for this turn, no production code, tests, or README changes
accompany this document, and none should be started without a separate,
explicit go-ahead.
