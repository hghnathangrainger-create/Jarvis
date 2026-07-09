# Phase 14 Implementation Plan — User-Controlled Bounded Recent-Memory Count

Status: **Planning only. No production code, tests, README changes, completion
report, staging, or commits accompany this document**, except where the
established plan-file workflow itself requires this document to exist.

Phase number confirmed available by direct repository inspection: `docs/`
contains completion/implementation documentation through Phase 13 only
(`phase_13_completion_report.md`, `phase_13_implementation_plan.md`); no
`phase_14_*` file exists prior to this one.

Authoritative closure state this plan builds on, verified directly against
the repository rather than assumed: HEAD `04f8b613aeaaec209cc36e1b06a63ab8116c1bb1`
("Complete Phase 13 deterministic recency-based memory selection"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean. `poetry run
pytest -q` — **1384 passed, 0 failed** — is the regression floor, re-run
fresh for this planning turn, not taken from a prior report.

This plan also builds on the just-completed **Retrieval-Family Architecture
Checkpoint** (Phases 10–13), whose conclusions are treated as authoritative
inputs, re-verified rather than merely cited, throughout this document.

---

## 1. Purpose

Phase 13 proved a fixed, parameter-free "give me the newest stored memories"
request could deterministically select a bounded set of memory ids. Phase
14 answers the question Phase 13's own completion report explicitly left
open: **how does Jarvis turn an explicit, user-supplied, strictly-bounded
count into a deterministic, honest, newest-first selection of that many
stored memories, without duplicating Phase 13's fixed-command semantics,
without silently clamping an out-of-range count, and without disclosing a
number of summarized memories the AI-ingestion boundary could not actually
have included?**

---

## 2. Exact Scope

- One new, sibling command grammar (`"summarise latest <count> memories"` /
  `"summarize latest <count> memories"`, §4) with its own dedicated
  `CommandRouter` matcher, orchestrator handler, selector, result type, and
  audit event.
- A strictly bounded, strictly validated count (`1`–`10`, §4.3), rejected
  outright — never silently clamped — when malformed or out of range.
- Full reuse of Phase 10's `ingest_memories_for_ai()`, Phase 13's own
  `select_recent_memory_ids()` (as an internal implementation detail, §5),
  and the entire existing trust/audit/unexpected-action architecture,
  unchanged.
- One narrow, additive closure item carried over from the architecture
  checkpoint: a focused, structural test proving the AI memory-ingestion/
  selection modules call only known read-only `MemoryManager` methods
  (§9).
- One narrow, additive regression item carried over from the checkpoint:
  budget-pressure ordering proofs for Phase 11/12, mirroring Phase 13's own
  existing proof (§10).

## 2.1 Non-Goals

Explicitly out of scope, per the architecture checkpoint and this plan's own
review:

- Changing Phase 13's existing exact `"summarise recent memories"` command,
  its fixed newest-10 semantics, `RecentSelectionResult`, or
  `select_recent_memory_ids()`'s public contract.
- Generalising `QuerySelectionResult`/`CategorySelectionResult`/
  `RecentSelectionResult` into a shared/generic type.
- Extracting a common post-selection workflow helper (§11 — deferred, not
  rejected).
- Centralising the duplicated `_AI_REASONING_NOT_ENABLED_MESSAGE`/
  `_AI_REASONING_UNAVAILABLE_MESSAGE` constants (§12 — deferred, not
  rejected).
- Redesigning `SecurityManager`, adding a new `ActionType`, or routing any
  existing or new AI memory read through `ToolExecutor`.
- Time-window retrieval, calendar/relative-date interpretation, semantic or
  vector retrieval, hybrid retrieval, or AI-selected/AI-ranked context.
- Any broader `CommandRouter.match()` redesign.

---

## 3. Repository Findings (fresh re-inspection, not taken from prior reports)

- **`MemoryManager.list_recent(limit: int = 20, *, category: str | None = None) -> list[MemoryRecord]`** — unchanged since Phase 9, delegates to `EpisodicMemoryStore.list_recent(limit=limit, category=category)`. No clamp on `limit` at either layer.
- **`EpisodicMemoryStore.list_recent()`** orders `.order_by(EpisodicMemory.created_at.desc(), EpisodicMemory.id.desc())` — unchanged.
- **`select_recent_memory_ids(memory_manager, *, limit: int = _RECENT_SELECTION_LIMIT) -> RecentSelectionResult`** (`ai/memory_selection.py:680`) — confirmed **already accepts a caller-supplied `limit` keyword argument today**; only production callers are instructed not to override it. Calls `list_recent(limit=limit)` exactly once, wraps the call in `except Exception: return RecentSelectionResult(error=_RECENT_LOOKUP_FAILURE_MESSAGE)`.
- **`RecentSelectionResult`** (`ai/memory_selection.py:594`) — exactly `selected_ids: tuple[int,...]`, `error: str|None`; three states (`success`/`zero_matches`/`failed`); no field for an invalid-input state; explicitly documented as carrying "no criterion-describing field at all" because Phase 13's command takes none.
- **`_RECENT_SELECTION_LIMIT = 10`** (`ai/memory_selection.py:582`) — the existing fixed ceiling, identical in value to Phase 10's `_MAX_MEMORY_SET_SIZE` (`core/orchestrator.py`) and `ingest_memories_for_ai`'s own `_DEFAULT_MAX_RECORDS` (`ai/memory_ingestion.py`).
- **`ingest_memories_for_ai(memory_manager, memory_ids, *, max_records=10, ...)`** (`ai/memory_ingestion.py`) — raises `ValueError` if `len(memory_ids) > max_records`; this is a **defensive backstop**, not a validation layer — its own docstring states the command-parsing layer is expected to already enforce the ceiling.
- **`core/command_router.py`** dedicated matcher grammar, confirmed by direct read:
  - `_MEMORY_SUMMARY_PREFIXES = ("summarise memory", "summarize memory")` — prefix, returns raw trailing text.
  - `_MEMORY_QUERY_SUMMARY_PREFIXES = ("summarise memories about", ...)` — prefix, returns raw trailing text.
  - `_MEMORY_CATEGORY_SUMMARY_PREFIXES = ("summarise memories in", ...)` — prefix, returns raw trailing text.
  - `_MEMORY_SET_SUMMARY_PREFIXES = ("summarise memories", "summarize memories")` — prefix, returns raw trailing text.
  - `_MEMORY_RECENT_SUMMARY_EXACT = ("summarise recent memories", "summarize recent memories")` — **exact match only**, `match_memory_recent_summary(text) -> bool`, no trailing text extracted (there is none).
- **Exact current dispatch order** in `JarvisOrchestrator.handle_request()`: `match_file_summary` → `match_memory_summary` → `match_memory_query_summary` → `match_memory_category_summary` → `match_memory_recent_summary` → `match_memory_set_summary` → `_handle_request_core`/`CommandRouter.match()`. Only the query/category matchers' position relative to the plural matcher is load-bearing (confirmed, unchanged).
- **`MemoryTool`** (`tools/builtin/memory_tool.py`) — its `"list"` operation calls `self._memory.list_recent(limit=limit, category=category)` directly, where `limit` is clamped by `_clamp_limit()` to `[1, 50]` (`_DEFAULT_LIMIT=10`, `_MAX_LIMIT=50`). **This is a different surface from the AI-summary family**: it never makes an exact "Found N" honesty claim, is tool-gated (`action_for()` returns `"list memories"`, classified GREEN by `SecurityManager._RULES`, executed through `ToolExecutor`), and its own audit trail is the generic `tool_call` event — not `memory_recent_selection`. Its 50-record ceiling is **not** a precedent for this phase's own ceiling (§4.3).
- **Current `memory_recent_selection` audit shape** (`core/orchestrator.py`, `_audit_memory_recent_selection`): `outcome=<success|zero_records|failure> match_count=<int> selected_ids=<...>` — no criterion field, no `requested_count`, by deliberate Phase 13 design (the fixed ceiling has no per-request variance to log).
- **Phase 10 context-size and record-count ceilings** (`ai/memory_ingestion.py`): `_DEFAULT_MAX_RECORDS = 10`, `_DEFAULT_MAX_CHARS = 4000` (per record), `_DEFAULT_MAX_TOTAL_CHARS = 20_000` (combined) — all unchanged, all reused unmodified by every existing selector and by this phase.

---

## 4. Phase Boundary, Command Grammar, and Routing

### 4.1 Phase boundary

This is formally **Phase 14**, a sibling retrieval capability alongside
Phases 10–13, not a modification of Phase 13. Phase 13's exact command,
its fixed newest-10 semantics, and every one of its production files are
touched **only additively** by this plan — confirmed by the files-changed
list in §15.4, and re-verified at closure (§16.9 of the batch plan).

### 4.2 Candidate grammars evaluated

| Candidate | Form | Collision check | Verdict |
|---|---|---|---|
| **A. `"summarise latest <count> memories"`** | `summarise` + `latest` + count + `memories` | Does not start with `"summarise memories"` (`_MEMORY_SET_SUMMARY_PREFIXES`) or `"summarise memory"` (`_MEMORY_SUMMARY_PREFIXES`) in either direction — `"latest"` immediately follows `"summarise "`, diverging at the very next character from both. Not equal to, and does not collide with, `_MEMORY_RECENT_SUMMARY_EXACT` (different keyword, `"latest"` vs `"recent"`, and that matcher is exact-match-only in any case). Reads naturally in English. **Chosen.** |
| B. `"summarise recent <count> memories"` | `summarise` + `recent` + count + `memories` | Also collision-free by the same string-comparison logic (verified). **Rejected** — reuses the word "recent" for a grammatically and architecturally distinct command from Phase 13's own parameter-free `"recent"` command, inviting confusion between two adjacent but differently-shaped commands that share a keyword. |
| C. `"summarise <count> recent memories"` | `summarise` + count + `recent` + `memories` | Also collision-free (the fixed prefix would be just `"summarise "`, distinguished only by the *trailing* literal `"recent memories"`). **Rejected** — structurally inconsistent with every existing matcher's "fixed prefix, then everything to the end is trailing free text" shape; here the count sits *before* two required literal words, which no existing matcher does, and the very short fixed prefix (`"summarise "`) increases the surface for accidental future collisions with other, unrelated future commands starting the same way. |

**Chosen grammar:** `"summarise latest <count> memories"` / `"summarize
latest <count> memories"` (both UK/US spellings, mirroring every existing
command pair).

### 4.3 Exact matcher design (a genuinely new extraction shape)

Every existing matcher recognises a fixed **prefix** and treats everything
after it as unconstrained trailing text. This grammar is the **first** in
the repository to require a fixed **prefix and a fixed, mandatory suffix**
(`"... memories"` at the very end), because natural English count phrasing
places the number before the noun, not at the end of the string. This is
disclosed explicitly, not silently reused via the existing `_file_prefix`
prefix-only helper, which cannot express a required suffix.

**Design:** a single compiled, anchored, case-insensitive regex:

```python
_MEMORY_RECENT_COUNT_SUMMARY_PATTERN = re.compile(
    r"(?:summarise|summarize)\s+latest\s+(.+)\s+memories", re.IGNORECASE
)
```

`match_memory_recent_count_summary(text: str) -> str | None` applies
`_MEMORY_RECENT_COUNT_SUMMARY_PATTERN.fullmatch(text)` to the already-
stripped request text (the same "text: The stripped request text"
contract every existing matcher already documents) and returns
`match.group(1)` **unstripped, unvalidated, in its original casing** — or
`None` if the text does not have this exact shape at all. This mirrors
every existing matcher's ownership split exactly: the router recognises
*grammatical shape* only; semantic/numeric validity is a downstream
concern (§5).

**Verified directly, not assumed, by manual trace:**
- `"summarise latest 5 memories"` → matches, `group(1) == "5"`.
- `"summarise latest memories"` (no count at all) → **does not match** —
  `(.+)` requires at least one character, and there is no room between
  `"latest "` and `"memories"` for both a non-empty capture and the
  required `\s+` separator; the router falls through exactly as any other
  malformed-prefix command already does today. (This means, unlike
  Category's `"summarise memories in"`, there is no analogous "matched but
  empty" case here — see §4.4.)
- `"summarise latest 5 memories about work"` (extra trailing content) →
  **does not match** — `fullmatch` requires the literal `"memories"` to be
  the final token; anything after it fails the match entirely, never
  silently ignored.
- `"summarise latest five memories"` → matches (`(.+)` is not digit-only),
  `group(1) == "five"` — an invalid-shape-but-grammatically-complete
  command, correctly deferred to count validation (§5), not rejected by
  the router.
- `"summarise latest  5  memories"` (extra internal whitespace) → matches,
  `group(1)` may include leading/trailing whitespace around the digits
  (e.g. `"5 "` or `" 5"`), which the downstream `.strip()` (§5) normalises
  before the digit check — handled for free, no special-casing needed.
- `"summarise recent memories"` (Phase 13's own exact command) → does not
  match this pattern at all (no `"latest"` token present).
- `"summarise memories 5"` / `"summarise memories 5, 12"` (Phase 10's own
  plural command) → does not match (no `"latest"` token, and Phase 10's
  own grammar has no required `"memories"` *suffix* — it is itself the
  prefix).

### 4.4 No orchestrator-level empty-input pre-check needed

Unlike Category (`"summarise memories in"` matches with empty trailing
text, requiring a distinct orchestrator-level empty-category message),
this grammar's **mandatory trailing literal `"memories"`** means there is
no realistic "the user typed the keyword with nothing after it" case that
still matches the router at all (§4.3's trace above) — the only way to
reach the handler with a degenerate `raw_count_text` is a whitespace-only
capture (an extreme edge case), which the selector's own single
`invalid_count` state already covers correctly (§5). **No separate
orchestrator-level empty-input branch is added**, a deliberate,
repository-grounded simplification from Category's own precedent, not an
oversight.

### 4.5 Dispatch placement

Confirmed collision-free against all five existing matchers in both
directions (§4.2/§4.3). **Dispatch-order placement is therefore not
load-bearing**, exactly like Phase 13's own recency matcher. It is placed
immediately after `match_memory_recent_summary` in `handle_request()`
purely for narrative grouping (clustering the "recency family":
category → recent → recent-count → plural), and this non-dependence on
position is itself proven by test (§15.3), not merely asserted.

---

## 5. Count Validation Contract, Selection Primitive, and Result Model

### 5.1 Bounds

- **Minimum: 1.** `count=0` is rejected as invalid input, not treated as a
  valid request that happens to select nothing — a "latest 0 memories"
  request is a malformed parameter, not a legitimate query with an honest
  zero-result answer, and no lookup is attempted for it.
- **Maximum: 10.** Deliberately reuses Phase 13's own existing
  `_RECENT_SELECTION_LIMIT` constant **by direct reference**, not a new
  literal `10` — this ties Phase 14's ceiling to Phase 10/13's own ceiling
  by construction, so they cannot silently drift apart. This is **not**
  MemoryTool's 50-record ceiling: that ceiling belongs to a different,
  tool-gated, non-honesty-claiming surface (§3); this family's ceiling is
  bounded by what `ingest_memories_for_ai()`'s `max_records=10` can
  structurally include, and disclosure honesty (§7) depends on the
  requested count never exceeding what can actually be summarised.
- **Leading zeros:** accepted (`"05"` → `5`), via the same
  `.isdigit()`/`int()` pattern `_parse_memory_id` already uses for ids —
  inherited, existing repository behaviour, not a new decision.
- **`+5`, `-5`, decimals (`5.0`), embedded whitespace (`"5 5"`):** all
  rejected — `str.isdigit()` returns `False` for every one of these,
  identically to how a malformed memory id is already rejected today.
  Unicode digit characters that `str.isdigit()` accepts (e.g. fullwidth
  digits) are accepted identically to how `_parse_memory_id` already,
  silently, accepts them for ids — an existing, inherited repository
  characteristic, explicitly disclosed here rather than treated as a new
  edge case invented for this phase.
- **Whitespace around the count:** stripped before validation (`.strip()`,
  matching `_parse_memory_id`'s own convention), so `" 5 "` is accepted.
- **`count=0` and over-limit counts (`11+`):** both rejected outright —
  **strict rejection, never silent clamping.** MemoryTool's own clamping
  behaviour is not the established convention for *this* family: no
  existing selector in `ai/memory_selection.py` (query, category, or
  recency) has ever silently substituted a different value for invalid
  input — each rejects outright (`zero_matches` is a valid *outcome* of a
  well-formed request, never a re-interpretation of a malformed one; an
  unknown category is never silently treated as `"general"`). Strict
  rejection is therefore the repository-consistent choice, confirmed, not
  merely the task's stated default preference.
- **Invalid counts are matcher matches, selector-level invalid states —
  not router non-matches.** The router's job is shape recognition only
  (§4.3); a grammatically well-formed command with a semantically invalid
  count (`"summarise latest 55 memories"`, `"summarise latest five
  memories"`, `"summarise latest 0 memories"`) all reach the handler and
  are rejected there with an honest, specific message — exactly mirroring
  how an unknown category reaches `select_memory_ids_by_category()` and is
  rejected there, not silently misrouted.

### 5.2 Selection primitive design

Evaluated against the four candidates:

- **A — extend `select_recent_memory_ids()` with a caller-supplied
  limit — rejected.** The function already *has* a `limit` parameter, but
  its `RecentSelectionResult` has no room for, and its existing tests
  explicitly assert, a three-state shape with no invalid-input concept.
  Bolting an `invalid_count` field onto it would violate the explicit
  instruction not to modify `RecentSelectionResult` for a new concern, and
  would force Phase 13's own fixed-command tests to reason about a state
  that command can never produce.
- **B/C — add a new, sibling, narrowly-named function — chosen.**
  Mirrors the exact, established, three-times-repeated pattern of this
  module (query → category → recency, each a sibling addition with its
  own result type).
- **D — reuse `select_recent_memory_ids()` through a private seam,
  without changing its public contract — chosen, combined with B.**

**Chosen design**, combining B and D: a new function
`select_recent_memory_ids_by_count(memory_manager, raw_count_text: str) ->
RecentCountSelectionResult` in `ai/memory_selection.py`, mirroring
Category's own Candidate-B precedent exactly: **it accepts the raw,
unvalidated string** (not a pre-parsed int), and is itself the defensive
correctness boundary — a future direct caller cannot bypass validation by
constructing this function's arguments carelessly, exactly as
`select_memory_ids_by_category()` cannot be bypassed for an unknown
category.

```python
_RECENT_COUNT_MINIMUM = 1
_RECENT_COUNT_MAXIMUM = _RECENT_SELECTION_LIMIT  # reused by reference, not a new literal

def select_recent_memory_ids_by_count(
    memory_manager: MemoryManager, raw_count_text: str,
) -> RecentCountSelectionResult:
    text = raw_count_text.strip()
    if not text.isdigit():
        return RecentCountSelectionResult(invalid_count=True)
    count = int(text)
    if not (_RECENT_COUNT_MINIMUM <= count <= _RECENT_COUNT_MAXIMUM):
        return RecentCountSelectionResult(invalid_count=True)

    inner = select_recent_memory_ids(memory_manager, limit=count)
    if inner.failed:
        return RecentCountSelectionResult(requested_count=count, error=inner.error)
    return RecentCountSelectionResult(
        requested_count=count, selected_ids=inner.selected_ids
    )
```

**This is the key architectural point: the actual `list_recent()` call,
its own `except Exception` boundary, and its own order-preservation
guarantee are never reimplemented — they are reused by calling Phase 13's
existing, unmodified `select_recent_memory_ids(memory_manager,
limit=count)` internally.** The only new logic in this entire function is
count validation and result-shape translation. `inner.error` (already the
exact, existing `_RECENT_LOOKUP_FAILURE_MESSAGE` string) is propagated
unchanged, so no new failure-message constant is needed for the lookup-
failure case at all.

### 5.3 New result type: `RecentCountSelectionResult`

A new type is **confirmed necessary, not assumed** — verified in §5.1
above that a genuine `invalid_count` state exists and must be rejected
*before* any lookup is attempted, the same architectural kind of problem
`CategorySelectionResult.invalid_category` solves, for the same reason
(a future direct caller must not be able to trigger an uncaught
`ValueError` from `ingest_memories_for_ai()`'s own `max_records` backstop,
or a dishonest `zero_matches` for a degenerate `count=0`, by skipping
validation).

```python
@dataclass(frozen=True, slots=True)
class RecentCountSelectionResult:
    selected_ids: tuple[int, ...] = ()
    requested_count: int | None = None
    error: str | None = None
    invalid_count: bool = False

    def __post_init__(self) -> None:
        if self.invalid_count:
            if self.error is not None or self.selected_ids or self.requested_count is not None:
                raise ValueError(...)
            return
        if self.requested_count is None:
            raise ValueError(...)
        if self.error is not None and self.selected_ids:
            raise ValueError(...)

    @property
    def success(self) -> bool:
        return not self.invalid_count and self.error is None and bool(self.selected_ids)

    @property
    def zero_matches(self) -> bool:
        return not self.invalid_count and self.error is None and not self.selected_ids

    @property
    def failed(self) -> bool:
        return self.error is not None

    @property
    def match_count(self) -> int:
        return len(self.selected_ids)
```

Four states — `success` / `zero_matches` / `invalid_count` / `failed` —
directly parallel to `CategorySelectionResult`'s shape (`category` →
`requested_count`), never collapsed. `requested_count` is `None` only for
`invalid_count` (mirroring `category`'s own None-only-when-invalid rule);
present for every other state, since a genuinely valid count was
established before the lookup was attempted or failed. **No raw invalid
count text is ever stored on the result** — the orchestrator, which
already has `raw_count_text` in scope from the matcher, builds the
user-facing echo message itself, exactly mirroring how the category
handler echoes raw category text without the result needing to carry it.

**Does not generalise `QuerySelectionResult`/`CategorySelectionResult`/
`RecentSelectionResult`** — all three remain completely untouched.

---

## 6. Honest Newest-N Semantics

Identical contract to Phase 13, extended only by a caller-supplied,
validated count: `created_at DESC, id DESC`, across all categories, one
`list_recent(limit=count)` call (via the internal delegation to
`select_recent_memory_ids`), no content/category/source/trust inspection,
no larger candidate pool fetched, no re-sorting, no reversal to
chronological order, no new deduplication policy. Every one of Phase 13's
own "Does NOT" guarantees is inherited unchanged because the actual lookup
is the same function call.

---

## 7. Phase 10 Ingestion Compatibility and Disclosure Honesty

Because `_RECENT_COUNT_MAXIMUM` is defined as a direct reference to
`_RECENT_SELECTION_LIMIT` (`= 10`), and `ingest_memories_for_ai()`'s own
`max_records` defaults to `10`, **the over-limit case can never reach
ingestion at all** — `invalid_count` rejects it before any lookup. This
makes the disclosure honesty requirement true by construction: the
handler will only ever call `ingest_memories_for_ai()` with `1`–`10` ids,
so `ingest_memories_for_ai`'s own defensive `max_records` backstop can
never actually trigger via this path (it remains a backstop for a
contract this phase's own validation already enforces, exactly as it
already is for every other selector).

**Disclosure must report actual `match_count`, never blindly echo
`requested_count`.** If a user requests the latest 8 but only 3 memories
are stored, the honest outcome is `success` with `match_count=3` — the
disclosure sentence must read `"Found 3 recent memories."`, not imply 8
were found. Proposed wording: `f"{summary} Found {match_count} of the "
f"{requested_count} most recent {memory_noun} requested."` when
`match_count < requested_count`, or simply `f"{summary} Found
{match_count} recent {memory_noun}."` (identical to Phase 13's own
wording) when `match_count == requested_count`. **Exact final wording is a
Batch 2 implementation decision**, not fixed rigidly here, but the
invariant — never claim more were found than `match_count` actually
reports — is fixed now and will be tested explicitly (§15.3).

**Reused unchanged, no duplication:** `ingest_memories_for_ai()`,
`MemorySetIngestionResult`, `_audit_memory_set_acquisition()`,
`_build_memory_set_disclosure()` — identical call sites to every existing
selector, appended after this handler's own selection-count sentence,
exactly mirroring Query/Category/Recent's own ordering.

---

## 8. Audit Event Design

**A new, distinct event: `memory_recent_count_selection`** — **not** a
modification of Phase 13's existing `memory_recent_selection` event
(Candidate A, rejected): reusing that event would force it to handle two
semantically different call shapes (a fixed command with no per-request
variance, and a user-controlled one with genuine variance), which is
exactly the kind of complexity the architecture checkpoint's semantic-
drift audit warned against, and would silently alter an already-shipped,
already-tested event's meaning for the *existing* command too.

**Fields:** `outcome=<success|zero_records|invalid_count|failure>
[requested_count=<int>] match_count=<int> selected_ids=<...>`.
`requested_count=` is present for every outcome except `invalid_count`
(mirroring `category=`'s own omission-when-invalid rule) — **never** the
raw, unvalidated input text, and never a fabricated value. `requested_count`
is safe to log directly: it is always a small bounded integer (1–10) once
validated, carrying no more sensitivity than `category=`'s own bounded
vocabulary. **No raw memory content is ever logged**, matching every
existing event in this family.

`EventOutcome.SUCCESS` only when at least one id was selected;
`zero_records`, `invalid_count`, and a genuine lookup exception all map to
`EventOutcome.FAILURE`, distinguished via `outcome=` inside `detail` —
identical convention to Category's own four-state mapping.

**Selection audit (`memory_recent_count_selection`) and acquisition audit
(`memory_acquisition`) remain fully distinct**, exactly as for every prior
selector — the new selection event fires once per request, describing the
count-lookup step; Phase 10's existing per-id acquisition events fire
afterward, unmodified, during ingestion.

**Logger-failure isolation:** the new `_audit_memory_recent_count_selection`
method uses the identical narrow `try/except Exception: pass` scoped only
around its own `emit()` call, matching all six existing audit methods.

---

## 9. Read-Only AI-Retrieval Invariant (formalising the checkpoint's one concrete debt)

**Chosen: Option A — a focused, structural, introspection-based test, plus
a concise documented rule** — matching the stated preference, and
rejecting a facade (Option C, unjustified blast radius for a debt with no
active defect) or documentation-only (Option D, does not convert five
consecutive prose reconfirmations into anything checkable).

**Design:** a new, narrow test (e.g.
`tests/unit/test_ai_memory_read_only_invariant.py`) using Python's
built-in `ast` module (no new dependency) to parse the actual source of
`ai/memory_ingestion.py`, `ai/memory_selection.py`, and this phase's own
additions, walking every `ast.Call` node whose function is an
`ast.Attribute` accessed on a name bound to a `MemoryManager`-typed
parameter (identified structurally, e.g. by parameter annotation in the
enclosing function signature, not by guessing variable names), and
asserting every such `.attr` name is a member of a small, explicit
allowlist: `{"get", "search", "list_by_category", "list_recent"}`.

**What this test can prove:** every syntactically-direct method call on a
`MemoryManager`-annotated parameter, anywhere in these two files, is one
of the four known read-only methods — a genuine, repository-wide,
regression-proof structural guarantee that a future edit introducing a
call to (for example) `memory_manager.forget(...)` or
`memory_manager.update_content(...)` inside either file would be caught
immediately, mechanically, without relying on a human reviewer noticing.

**What this test cannot prove:** dynamic dispatch (`getattr(memory_manager,
some_variable_name)(...)`), a call routed through a differently-named
local alias the AST walk does not recognise as the same parameter, or a
call inside a third file this test does not scan. None of these patterns
exist anywhere in the current codebase (confirmed by direct read of both
files), so the test is not working around a known gap — it is establishing
a checkable floor for a pattern that has, so far, only ever been
maintained by careful, repeated, manual review across five phases.

**Concise documented rule** (added as a module-docstring note in both
`ai/memory_ingestion.py` and `ai/memory_selection.py`, Batch 3): "This
module's direct `MemoryManager` calls are restricted to
`get`/`search`/`list_by_category`/`list_recent` — enforced by
`tests/unit/test_ai_memory_read_only_invariant.py`. No mutation or
deletion method may be called directly from this module; those remain
exclusively reachable through the YELLOW, `ToolExecutor`-gated
`memory_update`/`memory_forget` tools."

This directly closes the checkpoint's one concrete finding (§9 of the
checkpoint) at the lowest available blast radius: **zero changes to
`SecurityManager`, zero changes to how any existing read reaches
`MemoryManager`, zero new runtime code path** — purely a new test plus two
short doc-comments.

---

## 10. Phase 11/12 Budget-Pressure Regression Debt

**Decision: Option A** — add the equivalent proofs as part of this phase's
own Batch 3 compatibility verification, since they require **no production
changes**, only new test functions appended to the existing
`tests/integration/test_memory_query_summary_end_to_end.py` and
`tests/integration/test_memory_category_summary_end_to_end.py` files,
mirroring Phase 13's own `test_newest_first_order_survives_context_budget_
pressure_end_to_end` exactly (large real records, genuine budget overflow,
prove the oldest-of-selected is omitted first). This proves the shared,
order-sensitive `ingest_memories_for_ai()` invariant identically across
query/category/recency/recency-count, closing the one coverage gap the
checkpoint identified, in the same phase that is already touching this
exact seam.

---

## 11. Workflow-Helper / Refactor Decision

Re-inspected the actual Phase 10/11/12/13 handler bodies with this phase's
own design in hand, as instructed:

- **Would Phase 14 copy the same ~25–30-line post-selection skeleton
  again?** Yes — availability checks, `ingest_memories_for_ai()` call,
  acquisition audit, ingestion-success check, `AIReasoningRequest`
  construction, `reason()` call, suggested-steps construction, disclosure
  append, response/label construction, unexpected-action call are all
  structurally identical to the four existing handlers.
- **Does the new count-specific invalid-input/disclosure/audit behaviour
  make a helper harder rather than easier?** Yes, materially — the
  `invalid_count` early-return and the conditional "found fewer than
  requested" disclosure sentence (§7) are genuinely new branches with
  their own wording, which a shared helper would need to accept via
  further parameters or callbacks.
- **Can a narrow private post-selection helper be extracted without
  callback-heavy or six-parameter indirection?** Marginally — the
  identical *tail* (from `ingest_memories_for_ai()` through
  `_evaluate_unexpected_actions()`) could plausibly be extracted with
  roughly 6–7 parameters (`selected_ids`, `user_request`, `session_id`,
  `plan`, an AI-unavailable message, a label, a precomputed
  selection-count sentence), now that a **fifth** call site exists —
  this is the threshold the architecture checkpoint predicted would be
  reached "around a 5th or 6th selector," and it has now, in practice,
  been reached.
- **Would extraction improve invariant enforcement or merely reduce line
  count?** Both, modestly — it would guarantee the identical tail cannot
  silently diverge across five call sites, at the cost of one additional
  indirection layer between "read the handler" and "understand what it
  does."
- **Does the orchestrator's own documented value of explicit linear
  coordination argue against extraction?** Yes, still — `core/
  orchestrator.py`'s own module docstring states the Core "coordinates
  existing subsystems; it owns no planning, security, or execution logic
  of its own," a property currently true *per line, per handler*, that an
  extraction would trade for per-parameter indirection.

**Decision: do not extract in Phase 14.** The threshold is real and now
met in practice, but per the explicit instruction not to refactor merely
because a numeric threshold is reached, this phase proceeds with its own
explicit handler, identical in shape to the other four. **This finding is
carried forward as explicit, disclosed debt** (§17), recommending a
future, separately-scoped, narrow, compatibility-preserving internal
refactor — mirroring exactly how `_emit_memory_acquisition_event` was
itself extracted, once, later, as "the approved compatibility-preserving
internal refactor" between Phase 9 and Phase 10 — not bundled into this
capability-adding phase.

---

## 12. Duplicated Message Constants

Phase 14 will declare its own `_MEMORY_RECENT_COUNT_AI_REASONING_NOT_
ENABLED_MESSAGE` and `_MEMORY_RECENT_COUNT_AI_REASONING_UNAVAILABLE_
MESSAGE`, byte-identical in text to the four that already exist for Set/
Query/Category/Recent — **a fifth copy.**

**Classification: C — evidence for the larger workflow helper**, not
merely "still harmless" (A) — five independent, unenforced copies of the
same two strings is a real, if low-severity, maintenance surface. **Not
fixed in this planning turn or in Phase 14's implementation**: per §11,
both this and the helper-extraction question are bundled into the same
future, narrow, dedicated refactor recommendation, to avoid touching four
already-shipped constants' call sites during a capability-adding phase.
Two exceptions, both **positive, justified reuse, not new duplication**:
the zero-matches message (`"No memories are stored yet."`) and the
lookup-failure message (`_RECENT_LOOKUP_FAILURE_MESSAGE`, propagated via
`inner.error`) are both **directly reused from Phase 13's own existing
constants**, not re-declared — a deliberate instance of sharing exactly
where the underlying fact is identical, distinct from the AI-reasoning
messages' blind duplication.

---

## 13. Trust, Injection, and AI-Authority Model

Unchanged, re-verified: `select_recent_memory_ids_by_count()`'s
`selected_ids` flow, unmodified and once, into `ingest_memories_for_ai()`
→ one `AIContextBlock` → `ContentTrust.UNTRUSTED` (never `JARVIS_TRUSTED`,
structurally impossible) → `AIReasoningRequest.context_block`. The
user-requested count reaches `AIReasoningRequest.user_input` only as part
of the full, live `user_request` text (exactly like every existing
criterion) — never inserted into the memory context as metadata, to be
proven directly (§15.3) mirroring Phase 13's own
`test_recent_command_excluded_from_memory_context_end_to_end`. Stored
memory content remains `UNTRUSTED` regardless of how many records were
requested. The AI never chooses, ranks, expands, or replaces `selected_ids`
— selection is complete before `AIReasoningRequest` is ever constructed.
Unexpected AI actions remain verdict/audit only: GREEN→FLAG,
YELLOW→ESCALATE, RED→BLOCK, via the same, unmodified
`_evaluate_unexpected_actions`/`_audit_unexpected_action` — never executed.

---

## 14. Failure Boundaries

- `select_recent_memory_ids_by_count()` introduces **no new** `except
  Exception` block of its own — it delegates to `select_recent_memory_ids()`,
  whose own single, existing, narrow boundary around `list_recent()`
  already converts any infrastructure failure into an honest
  `RecentSelectionResult.failed`, which this function simply repackages
  (`inner.error` copied verbatim, never the raw exception text).
- The new `_audit_memory_recent_count_selection` method adds exactly one
  new `except Exception: pass`, scoped only around its own `emit()` call —
  the seventh such narrow boundary in this family, identical in shape to
  the other six.
- No broad exception handling is added anywhere around selection,
  ingestion, or AI reasoning logic itself.
- Provider/validation failure semantics are entirely inherited: `reason()`
  returning `None` produces the honest "reasoning unavailable" message,
  never a fabricated `"[AI recent-count memory summary"`-labelled success.

---

## 15. Proposed Batches

The task's own suggested four-batch shape was compared against the
repository's actual, consistent three-batch convention (Phases 11, 12, and
13 each closed with exactly one "end-to-end verification, security
closure, documentation, and commit" batch). **Adjustment made: collapsed
back to three batches**, folding the suggested Batch 3 and Batch 4 content
into one Batch 3, exactly matching established convention — the read-only
invariant test and the Phase 11/12 regression additions are additional
*items* within that same, already-proven batch shape, not evidence a new
batch boundary is structurally required.

### Batch 1 — Count-Based Recent Selection Foundation

- `ai/memory_selection.py`: `select_recent_memory_ids_by_count()`,
  `RecentCountSelectionResult`, `_RECENT_COUNT_MINIMUM`,
  `_RECENT_COUNT_MAXIMUM` (referencing `_RECENT_SELECTION_LIMIT`).
- `tests/unit/test_memory_selection.py`: extended with count-selector
  unit tests (real storage where practical, mirroring Category's own
  Batch 1 coverage).
- No command/orchestrator/AI wiring.

### Batch 2 — Command and AI Summary Workflow

- `core/command_router.py`: `_MEMORY_RECENT_COUNT_SUMMARY_PATTERN`,
  `match_memory_recent_count_summary()`.
- `core/orchestrator.py`: dispatch branch, `_handle_memory_recent_count_
  summary_request()`, `_audit_memory_recent_count_selection()`, new
  message constants (§12) and label.
- `tests/unit/test_command_router.py`: extended with matcher grammar/
  non-collision tests.
- New `tests/unit/test_memory_recent_count_summary_workflow.py`, mirroring
  Category's/Recent's own Batch 2 workflow test file.
- No README.

### Batch 3 — End-to-End Verification, Security-Invariant Closure, Documentation, and Commit

- New `tests/integration/test_memory_recent_count_summary_end_to_end.py`
  (real-stack success, exact-grammar strictness, count bounds, ordering/
  budget-pressure proof for this selector, trust/injection/provenance
  imitation, selection-to-ingestion race, zero/invalid/failure exact audit
  fields, logger-failure isolation, RED/YELLOW unexpected-action, provider/
  validation failure, all-prior-selector compatibility on one orchestrator
  instance).
- New `tests/unit/test_ai_memory_read_only_invariant.py` (§9).
- Additive-only regression tests in the existing
  `test_memory_query_summary_end_to_end.py` and
  `test_memory_category_summary_end_to_end.py` (§10).
- `README.md` update.
- `docs/phase_14_completion_report.md`.
- Full verification (§16), `git diff --check`, closure commit.

---

## 16. Verification Plan (for the future implementation turn)

```
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_recent_count_summary_workflow.py -v
poetry run pytest tests/unit/test_ai_memory_read_only_invariant.py -v
poetry run pytest tests/integration/test_memory_recent_count_summary_end_to_end.py -v
poetry run pytest tests/integration/test_memory_query_summary_end_to_end.py -v
poetry run pytest tests/integration/test_memory_category_summary_end_to_end.py -v
poetry run pytest -v
git diff --check
```

Regression floor: **1384 passed, 0 failed** — may only grow.

---

## 17. Risks and Debt Explicitly Carried Forward

- **Inherited, unchanged:** the broad `CommandRouter.match()` keyword
  overlap; memory retrieval unscoped by session; the recency-count-to-
  ingestion TOCTOU-style race (same accepted class as Phase 10–13's,
  represented entirely through Phase 10's existing `not_found`/
  `retrieval_errors` states, no new state added).
- **Newly disclosed, deferred by explicit decision (§11/§12):** the
  post-selection workflow-helper threshold has now been reached in
  practice (5 call sites); the AI-reasoning message constants now have a
  fifth identical copy. Both deferred to a future, narrow,
  compatibility-preserving refactor phase, not attempted here.
- **Newly disclosed, accepted as a known limitation:** the read-only
  AI-retrieval invariant test (§9) proves only syntactically-direct calls;
  it cannot detect a hypothetical future dynamic-dispatch bypass. No such
  pattern exists today.
- **Unchanged from Phase 13:** the SQLite naive-timestamp-on-read-back
  debt remains non-blocking for this phase (no time-window semantics are
  introduced) and still blocking for any future calendar-aware capability.

---

## 18. Exact Stop Points

This document stops after planning and the adversarial review (§19,
below). No production code, no test code, no README change, no completion
report, and no commit accompany it, except this plan file's own addition,
per the task's explicit instructions.

---

## 19. Adversarial Plan Review

Each question below was checked directly against the design above; none
required a design change — each risk was already closed by construction,
not discovered after the fact.

1. **Can an over-limit count produce dishonest disclosure?** No — bounded
   to ≤10 before any lookup (§5.1/§7); disclosure always reports actual
   `match_count`, never blindly echoes `requested_count` (§7).
2. **Can count validation be bypassed by alternate numeric syntax?** No
   new gap — inherits `_parse_memory_id`'s own existing `.isdigit()`/
   `int()` characteristics (including its pre-existing Unicode-digit
   acceptance), explicitly disclosed as carried-forward, not new (§5.1).
3. **Can Phase 13's exact fixed command change accidentally?** No — zero
   lines of `_MEMORY_RECENT_SUMMARY_EXACT`/`match_memory_recent_summary`/
   `select_recent_memory_ids`/`RecentSelectionResult` are touched; Phase 14
   only *calls* `select_recent_memory_ids` as an unmodified internal
   dependency (§5.2). Verified at implementation-closure time via diff.
4. **Can routing send the new grammar into `match_memory_set_summary` or
   generic handling?** No — confirmed collision-free by direct string/
   regex trace against all five existing matchers (§4.2/§4.3); to be
   proven by test in Batch 2/3.
5. **Can selected ids be reordered before Phase 10 ingestion?** No — the
   new function performs zero sorting/reordering of its own; it only
   validates a count and delegates the actual lookup, unchanged, to
   `select_recent_memory_ids()` (§5.2/§6).
6. **Can the user count enter the UNTRUSTED memory context?** No — reaches
   `user_input` only, never `context_block` (§13), to be proven directly.
7. **Can AI influence selection?** No — selection completes, and is
   audited, before `AIReasoningRequest` is ever constructed (§13).
8. **Can a logger failure change success/failure?** No — the new audit
   method uses the same narrow, `emit()`-only guard as all six existing
   ones (§8/§14).
9. **Can a RED or YELLOW AI suggestion execute?** No — unchanged
   verdict-only policy, reused (§13).
10. **Can the new AI retrieval path directly call a `MemoryManager`
    mutation method?** No — it calls only `select_recent_memory_ids()`
    (itself calling only `list_recent()`); additionally covered,
    mechanically, by the new read-only invariant test (§9).
11. **Does the proposed invariant test actually prove the direct-call
    rule, or merely assert file names?** It parses real source via `ast`
    and checks actual call targets against an allowlist — genuinely
    structural, with its provable/unprovable boundary explicitly stated
    (§9), not a filename or string-search assertion.
12. **Does Phase 14 create enough workflow duplication to justify a
    helper?** Yes, the threshold is reached (§11) — but extraction is
    deliberately deferred, not performed, per explicit instruction.
13. **Does a helper weaken readability or hide selector-specific
    semantics?** Assessed as a real risk if attempted now (§11), which is
    exactly why extraction is deferred rather than attempted inside this
    capability phase.
14. **Does a fifth copy of the AI reasoning messages create enough drift
    risk to centralise them?** Classified C (§12) — real, but bundled into
    the same deferred future refactor as §11, not fixed now.
15. **Does any plan step accidentally introduce time-window semantics?**
    No — the grammar has zero date/time vocabulary; "latest N" is purely
    an ordinal count over the existing deterministic order (§6).
16. **Does any plan step introduce semantic/vector/AI-selected
    retrieval?** No — the design exclusively extends the existing
    deterministic `list_recent()` mechanism; no embeddings, ranking, or AI
    involvement in selection anywhere in this plan.

**No plan corrections were required as a result of this review.**
