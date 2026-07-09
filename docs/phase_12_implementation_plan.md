# Phase 12 Implementation Plan — Deterministic Category-Based Memory Selection

Status: **Planning only. No production code, tests, README changes, completion
report, staging, or commits accompany this document.**

**Clarification addendum (this revision):** three narrow planning points —
the invalid-category correctness boundary and its ownership (§5.2, new
§5.3, §6, §8), the exact category normalisation/canonicalisation sequence
(§4), and the `memory_category_selection` audit fields/privacy contract
(§12) — were clarified and tightened before Batch 1 begins. The most
consequential change: category validation is no longer solely the
orchestrator's job (the original §4/§5.2 text) — the selector itself now
defensively validates via the existing `is_known_category()` and returns a
distinct `invalid_category` result, per the approved Candidate B. No other
section's substance changed.

Phase number confirmed available by direct repository inspection: `docs/`
contains completion/implementation documentation through Phase 11 only
(`phase_11_completion_report.md`, `phase_11_implementation_plan.md`); no
`phase_12_*` file exists prior to this one.

Authoritative closure state this plan builds on, verified directly against
the repository rather than assumed: HEAD `a2d47d27e255e4beeb2c00f870edf05b9e189905`
("Complete Phase 11 deterministic query-based memory selection"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean.
`poetry run pytest -q` — **1124 passed, 0 failed** — is the regression floor.

---

## 1. Purpose

Phase 11 proved a deterministic, explicit **query** could safely select a
bounded set of memory ids for AI reasoning, reusing Phase 10's combination
architecture unchanged. Phase 12 answers the analogous question for an
explicit **category**: **how does Jarvis turn an explicit user-named memory
category into a deterministic, bounded, explainable ordered set of stored
memory records for AI reasoning, while preserving the real repository
category semantics and without introducing semantic retrieval or AI-selected
context?**

The scope is deliberately narrow: reuse `MemoryManager.list_by_category()`
exactly as it already behaves, reuse Phase 10's ingestion/combination
architecture unchanged, and reuse Phase 11's selection-layer precedent where
it genuinely fits — without inventing category inference, fuzzy matching, or
any AI involvement in selection.

---

## 2. Repository Findings

### 2.1 Actual category model (`memory/memory_models.py`, `storage/models.py`)

- **Structure:** category is a plain **string** column
  (`EpisodicMemory.category: Mapped[str] = mapped_column(String(32),
  nullable=False, default="general", server_default="general", index=True)`)
  — not an enum, not a separate table, not a nullable/optional field. It is
  always present on every row.
- **Known values:** exactly five, defined as string constants in
  `memory/memory_models.py`: `"general"` (`GENERAL`, also `DEFAULT_CATEGORY`),
  `"personal"` (`PERSONAL`), `"project"` (`PROJECT`), `"preference"`
  (`PREFERENCE`), `"note"` (`NOTE`) — collected in
  `KNOWN_CATEGORIES: tuple[str, ...]`. These are the **only** categories
  proven by the repository; none are invented for this plan.
- **Normalisation:** `normalize_category(category: str | None) -> str`
  strips whitespace and lower-cases, then returns the result only if it is
  a member of `KNOWN_CATEGORIES`; otherwise (including `None` or a blank
  string) it returns `DEFAULT_CATEGORY` (`"general"`). **Normalisation never
  raises and never rejects — it silently falls back.**
- **Case sensitivity:** none after normalisation — `"Project"`, `"PROJECT "`,
  and `"project"` all normalise to `"project"`.
- **Aliases:** **none exist anywhere in the repository.** There is no
  synonym table, no fuzzy matching, no alternate spellings recognised for
  any category.
- **Validation:** `is_known_category(category: str | None) -> bool`
  independently reports whether a value (after the same strip+lower) is a
  known category, without normalising or falling back — it is a pure
  predicate, never raising.
- **Default category behaviour:** any memory saved without an explicit
  category, or with a blank/unknown one, is stored as `"general"`.
- **Genuine finding, materially important:** because `normalize_category()`
  **silently maps any unknown string to `"general"`** rather than rejecting
  it, `MemoryManager.list_by_category("spaceships")` does not fail, return
  an empty list because "spaceships" doesn't exist, or raise — it silently
  queries for `"general"` memories instead, which may well be non-empty.
  **A naive read of "zero results" for an invalid category would actually
  be a mis-execution against the wrong category, not an honest "unknown
  category" report or even a guaranteed-empty result.** This is a more
  severe failure mode than any behaviour Phase 11 had to account for, and
  is addressed explicitly in §4 and §9 below.
- **Mutability:** category can change after creation via the existing,
  separate, YELLOW-tier `move memory <id> to <category>` /
  `memory_update` tool — irrelevant to this read-only capability, noted
  only for completeness.
- **Required:** yes, structurally (`nullable=False`); there is no
  "no category" state to represent.
- **Persistence:** a plain, indexed SQL column, queried via ordinary
  SQLAlchemy `.filter()`, exactly like `content`.

### 2.2 `MemoryManager.list_by_category()` / `EpisodicMemoryStore.list_recent()` — exact semantics

`MemoryManager.list_by_category(category: str, limit: int = 20)` is a thin
wrapper: `return self._store.list_recent(limit=limit, category=category)` —
it is not a separate query path from `list_recent`/`list()`, merely that
method called with a category filter.

- **Input type:** `str` (any string; `normalize_category` handles `None`
  defensively at the store layer, but the public signature is `str`).
- **Filtering semantics:** an **exact-match** SQL filter,
  `EpisodicMemory.category == normalize_category(category)` — not a
  substring/`LIKE` match (unlike Phase 11's content search). The category
  is normalised **before** filtering, at the store layer, on every call.
- **Case sensitivity:** none — normalisation lower-cases before the
  exact-match filter is built.
- **Ordering:** `ORDER BY created_at DESC, id DESC` — the **same**
  deterministic, tie-broken ordering `EpisodicMemoryStore.search()` already
  uses for Phase 11. No new ordering analysis is required; determinism is
  already established.
- **Default limit:** 20, with **no upper clamp** at the `MemoryManager`/
  `EpisodicMemoryStore` layer — identical situation to Phase 11's
  `search()`. `MemoryTool`'s own 1–50 clamp (`_DEFAULT_LIMIT`/`_MAX_LIMIT`)
  applies only to its own call path, not to a direct `MemoryManager` call.
- **Duplicates:** structurally impossible — a single, non-joining filter
  over one table.
- **Deleted/inactive records:** cannot appear — no soft-delete column
  exists anywhere on `EpisodicMemory` (unchanged since Phase 11's own
  finding).
- **Error behaviour:** neither `list_recent` nor `list_by_category` catches
  anything; a database-layer exception propagates to the caller unmodified.
- **Return shape:** full, detached `MemoryRecord` objects (`id`, `content`,
  `source`, `session_id`, `created_at`, `category`) — not bare ids.
- **SQL parameterisation:** confirmed safe — `EpisodicMemory.category ==
  normalize_category(category)` is an ordinary SQLAlchemy equality filter,
  bound as a parameter, never string-interpolated. Because normalisation
  always collapses input to one of exactly six fixed strings before the
  filter is even built, there is no meaningful "adversarial category
  string reaches SQL" surface at all — normalisation itself is the
  sanitisation step, structurally, not merely incidentally.
- **Not "relevant" or "ranked":** confirmed by code — this is a plain
  exact-match filter with recency ordering, nothing else.

---

## 3. Proposed Command Surface

### 3.1 Candidates evaluated

**Candidate 1 — `summarise memories in <category>` / `summarize memories in
<category>`.** Mirrors the existing, already-shipped `show memories in
<category>` phrasing (`core/command_router.py`'s `_build_memory_input`,
via `_extract_after(stripped, " in ")`), and mirrors the existing
leading-prefix extraction pattern every summary-family matcher already
uses (`match_file_summary`, `match_memory_summary`,
`match_memory_query_summary`, `match_memory_set_summary`).
**Collision found by inspection:** this prefix (`"summarise memories in"`)
is a strict superset-string of Phase 10's plural prefix (`"summarise
memories"`) — the **exact same class of collision** Phase 11 already
discovered and fixed for its own `"about"` grammar. Verified directly:
`"summarise memories in project".startswith("summarise memories")` is
`True`.

**Candidate 2 — `summarise <category> memories`.** Does **not** collide
with either existing plural or singular prefix (verified: it does not
start with `"summarise memory"` or `"summarise memories"` at all, since
the category token sits between `"summarise"` and `"memories"`).
Rejected: it requires a **trailing-fixed-suffix extraction** (find
`" memories"` at the end, take everything between `"summarise "` and
it) — a categorically different, less-precedented parsing shape than
every existing matcher in this codebase, all of which extract a **leading**
prefix and treat the remainder as the argument. Adopting a new extraction
shape for one command, solely to dodge a now-familiar and already-solved
collision class, is not a compelling trade-off against consistency with
five existing matchers.

**Chosen: Candidate 1**, accepting the same collision-and-fix pattern
Phase 11 already established and proved reliable, for consistency with
the existing `"show memories in <category>"` phrasing and every existing
matcher's leading-prefix extraction shape.

### 3.2 Resolution: longest-prefix/more-specific-first dispatch (a standing requirement now)

A new `_MEMORY_CATEGORY_SUMMARY_PREFIXES = ("summarise memories in",
"summarize memories in")` and `CommandRouter.match_memory_category_summary()`
method, mirroring `match_memory_query_summary()` exactly (extract raw
trailing text only). `JarvisOrchestrator.handle_request()` must check this
new matcher **before** `match_memory_set_summary` — the Phase 11 lesson
("longest/most-specific prefix checked first") is now a **standing review
requirement** for every new summary-family command, not a one-off fix.

**Verified non-collision with every other command:**
- vs. `match_memory_summary` (singular, `"summarise memory"`): diverges at
  the word's 6th character (`y` vs `i`), same as already established.
- vs. `match_memory_query_summary` (Phase 11, `"summarise memories about"`):
  diverges at the second word (`"in"` vs `"about"`) — neither is a prefix
  of the other in either direction; check order between these two new
  matchers does not affect correctness.
- vs. `show memory <id>` / `forget memory <id>` / generic `_MEMORY_KEYWORDS`
  text: routed via `CommandRouter.match()`, never reached until all
  summary-family matchers return `None`.
- vs. the existing `"show memories in <category>"` (`_build_memory_input`):
  different leading verb (`"show"` vs `"summarise"`), and unreachable from
  that method anyway since the new matcher is checked before
  `_handle_request_core`/`match()` is ever reached.

**Exact required dispatch order:**
```
1. match_file_summary                -> Phase 8
2. match_memory_summary               -> Phase 9 (singular)
3. match_memory_query_summary         -> Phase 11 (query)
4. match_memory_category_summary      -> Phase 12 (category, NEW)
5. match_memory_set_summary           -> Phase 10 (explicit-id plural)
6. _handle_request_core / CommandRouter.match() -> ordinary rule-based dispatch
```
Position 4 is placed immediately before position 5 because that is the
only strict ordering requirement (superset-string collision); its position
relative to 2/3 is arbitrary and chosen only for readability (grouping the
newer, non-id-based summary commands together).

---

## 4. Parsing and Normalisation Contract

**Ownership clarified (Candidate B, §5.3):** validation of *whether a
category is known* is owned by the **selector**, not solely the
orchestrator. The orchestrator's own pre-flight check is narrowed to "was
any category text supplied at all" — a pure command-grammar concern,
mirroring Phase 11's own empty-query check exactly.

**Exact sequence for valid input:**
```
raw extracted category (CommandRouter.match_memory_category_summary, strip only)
  -> orchestrator: reject if empty after strip (pure syntax check; no
     is_known_category() call needed here - mirrors Phase 11's empty-query
     rejection; no lookup, no audit event, no AI consulted)
  -> select_memory_ids_by_category(memory_manager, category_text):
       -> is_known_category(category_text)  [the real, authoritative check]
       -> if False: return CategorySelectionResult(invalid_category=True);
          list_by_category() is never called
       -> if True: normalize_category(category_text) -> canonical form
          (e.g. "PROJECT " -> "project")
          -> memory_manager.list_by_category(canonical, limit=10)
  -> orchestrator audits the returned CategorySelectionResult exactly once
     (success / zero_matches / invalid_category / failed - see §12)
```

- **Command extraction** (raw trailing text, stripped only — no semantic
  interpretation): owned by `CommandRouter.match_memory_category_summary()`,
  mirroring every existing matcher's own contract.
- **Orchestrator's own check — emptiness only:** an empty (post-strip)
  category is rejected before the selector is ever called — no lookup, no
  audit event, no AI consulted — exactly mirroring Phase 11's own
  empty-query handling. The orchestrator no longer needs to import or call
  `is_known_category()`/`normalize_category()` itself; that responsibility
  moved entirely to the selector (§5.2/§5.3).
- **Selector's own validation (mandatory, authoritative):**
  `select_memory_ids_by_category()` calls the **existing**, reused,
  unmodified `memory.memory_models.is_known_category(category)` itself,
  before ever calling `MemoryManager.list_by_category()`. This directly
  closes the §2.1 finding: `list_by_category()` called directly cannot
  distinguish an unknown category from `"general"` (`normalize_category()`
  silently falls back), so the selector must never call it with anything
  that has not already passed `is_known_category()`.
- **Canonicalisation:** for a category that passes validation, the
  selector calls the **existing**, reused, unmodified
  `normalize_category(category)` to obtain the canonical form (confirmed
  by direct inspection: `"PROJECT"` → `"project"`) and uses that canonical
  value for **both** the actual `list_by_category()` call and the result's
  own `category` field (§6) — never the arbitrary raw user spelling.
- **No second category vocabulary is created.** `KNOWN_CATEGORIES`,
  `normalize_category()`, and `is_known_category()` remain the sole source
  of truth, imported and reused directly by the selector.
- **Case variants:** confirmed by direct inspection —
  `is_known_category("PROJECT")` strips+lowers to `"project"`, a member of
  `KNOWN_CATEGORIES`, so it returns `True`; `normalize_category("PROJECT")`
  likewise returns the canonical `"project"`. Every case variant of a
  known category (`"Project"`, `"PROJECT"`, `"  project  "`) is therefore
  valid and canonicalises to the same lowercase form.
- **Punctuation:** not specially handled; a category with stray
  punctuation (e.g. `"project."`) simply fails `is_known_category()` and
  is honestly rejected as unknown by the selector — no punctuation-
  stripping heuristic is added.
- **Unknown category names:** rejected honestly by the selector itself
  (`invalid_category=True`), **never** silently substituted with
  `"general"`.
- **Aliases:** none exist; none are added.
- **Empty category input** (`"summarise memories in"` with nothing after
  it, or only whitespace): handled entirely at the orchestrator layer as
  a pure syntax rejection (above) — it never reaches the selector, and is
  therefore never audited as `invalid_category`, mirroring Phase 11's own
  "empty query, no audit event" precedent exactly.
- **No AI is ever asked to infer or classify a category.**

---

## 5. Selection Architecture

### 5.1 Where the new selector lives

**Candidates evaluated**, per the explicit instruction to review Phase 11's
architecture before deciding:

**Candidate A — a second function/result type inside the existing
`ai/memory_selection.py`.** Direct precedent: Phase 10 itself extended
`ai/memory_ingestion.py` with a second, sibling function
(`ingest_memories_for_ai`, alongside the existing `ingest_memory_for_ai`)
rather than creating a second ingestion module, precisely because the new
capability was a generalisation/sibling of the existing one (single-id
ingestion → multi-id ingestion, both "ingestion"). Query-based selection
→ category-based selection is the analogous sibling relationship (both
"deterministically turn a piece of explicit user-supplied criteria into an
ordered set of memory ids via one existing `MemoryManager` read method"),
making this the **precedent-consistent** choice.

**Candidate B — a separate module, `ai/memory_category_selection.py`,**
mirroring `ai/memory_selection.py`'s shape exactly. Lowest possible risk
to Phase 11's already-closed file (zero touch, not even to its docstring),
but would duplicate most of that file's boilerplate (imports, the
`MemoryManager` type dependency, the same three-state result-dataclass
shape) for a difference that is really just "which one `MemoryManager`
read method is called."

**Candidate C — a generic, pluggable selection-strategy framework**
covering explicit-id/query/category (and future recency) uniformly.
Rejected outright, exactly as Phase 11 already reasoned: with only three
concrete strategies existing after this phase, a shared abstraction is
premature generalisation this project's own conventions consistently
reject (see §20).

**Chosen: Candidate A.** `ai/memory_selection.py` gains a second function,
`select_memory_ids_by_category()`, and a second, distinctly-named result
type, `CategorySelectionResult` (see §6 for why it is not a reuse of
`QuerySelectionResult`). The module's own docstring header is updated
(documentation only, no behaviour change) to describe it as the home for
deterministic, non-id-based selection helpers in general — query-based
today, category-based added here — mirroring how `ai/memory_ingestion.py`'s
own docstring already describes both its single- and multi-record
responsibilities together in one place. **`select_memory_ids_by_query()`
and `QuerySelectionResult` are not renamed, not refactored, and not
touched in behaviour** — this is a pure addition, not a generalisation of
existing Phase 11 APIs, per the explicit instruction not to increase
regression blast radius for aesthetic consistency.

### 5.2 What `select_memory_ids_by_category()` does and does not do

Does:
- Accept `(memory_manager, category, *, limit)`.
- **Validate the category itself, defensively, via the existing,
  unmodified `is_known_category()`** — the selector's own correctness
  does not depend solely on the orchestrator having validated first (see
  §5.3). An unknown category never reaches
  `MemoryManager.list_by_category()`.
- For a category that passes validation, canonicalise it via the
  existing, unmodified `normalize_category()` before calling
  `memory_manager.list_by_category(canonical, limit=limit)` — the sole
  lookup call site.
- Return the ids of the results **in the exact order `list_by_category()`
  returned them** — no re-sorting.
- Represent an invalid category, zero records, a non-empty result, and a
  lookup-layer exception as **four** distinct, named outcomes, never
  collapsed into one another.

Does not:
- Retrieve memory content, construct an `AIContextBlock`, or touch
  trust/provenance — that remains exclusively `ingest_memories_for_ai()`'s
  job, called afterward, unmodified.
- Apply the cardinality/disclosure message itself — that remains the
  orchestrator's job, reusing the same pattern Phase 10/11 already
  establish.
- Emit any audit/observability event — assigned to Batch 2 (orchestrator),
  mirroring Phase 11 exactly.
- Introduce category inference, fuzzy matching, or any AI involvement.

### 5.3 Invalid-Category Correctness Boundary (clarification)

**Invariant:** a category-selection operation must never call
`MemoryManager.list_by_category()` with an unknown category value in a
way that permits `normalize_category()` to silently substitute
`"general"`.

**Candidates evaluated:**

**Candidate A — orchestrator-only validation.** The original version of
this plan's position: only `JarvisOrchestrator` calls
`is_known_category()` before ever invoking the selector. **Rejected on
reflection.** This makes the selector's own correctness depend entirely
on caller discipline — any future caller (a different command, a test, a
later refactor) that invokes `select_memory_ids_by_category()` directly,
without first validating, would silently query `"general"` for a typo'd
category, with no defence at the exact point the mistake would occur.

**Candidate B — selector-level defensive validation; the orchestrator
validates early only for a fast, no-side-effect syntax rejection.** The
selector itself calls `is_known_category()` and returns a distinct
`invalid_category` result; the orchestrator's own pre-flight check is
narrowed to a pure emptiness check (§4). **Chosen.** This matches the
actual severity of the risk found in §2.1: the silent fallback does not
merely process noisy input — it can **select the wrong records**, a
correctness property that must not depend solely on every future caller
remembering to validate first. Both layers reuse the exact same, existing
`is_known_category()`/`normalize_category()` helpers — no second
vocabulary is invented — and the two checks serve genuinely different
purposes: the orchestrator's is a fast, side-effect-free syntax rejection;
the selector's is the actual, authoritative correctness guarantee for
anyone who calls it, including future callers this plan cannot foresee.

**Candidate C — change `normalize_category()`/`MemoryManager.
list_by_category()` globally to reject unknown categories.** **Rejected.**
This would change established, working repository behaviour that other
workflows deliberately and correctly rely on — e.g. `remember this as
<category>: ...` intentionally never fails for an unrecognised category,
falling back to `"general"` by design (a Phase 5 decision serving the
*save* workflow's own, different goals). Changing that behaviour globally
to serve Phase 12's narrower *read* correctness need would be
disproportionate, unnecessary compatibility blast radius reaching far
outside this phase's scope, when the same correctness guarantee is fully
achievable at the one new call site alone.

**Confirmed: Candidate B matches the actual code and this plan's own
architecture.** No disagreement with the preferred contract; no stronger
repository-grounded alternative was found. The result model (§6) and
failure semantics (§8) are updated accordingly to carry a distinct,
never-collapsed `invalid_category` state.

---

## 6. Result Model: New Type, Not a Reuse

**Reviewed `QuerySelectionResult` directly** (`selected_ids`, `error`,
`query_length`). **Decision: do not reuse it; introduce
`CategorySelectionResult`.**

- **Semantic clarity:** `query_length` exists specifically because a
  search query is arbitrary, potentially-sensitive free text whose
  *length* (not content) is the safe thing to log (§14). A category is
  the opposite: a bounded, six-valued, non-sensitive enum-like string.
  Reusing `query_length` to hold a category's length would be actively
  misleading (implying the same privacy rationale applies, when it does
  not) — exactly the "misleading field name" the task instructs against.
- **Backward compatibility:** `QuerySelectionResult` is an approved,
  closed Phase 11 API with its own tests; touching it (e.g. adding an
  optional `category` field, or renaming `query_length` to something
  generic) would widen Batch 1's regression surface for no functional
  gain, and is explicitly rejected as unjustified generalisation for
  aesthetic consistency.
- **Invariants (clarified — four distinct states, not three):**
  `CategorySelectionResult` carries:
  - `selected_ids: tuple[int, ...] = ()` — ordered ids, empty for every
    non-success state.
  - `category: str | None = None` — the **canonical, validated** category
    actually queried (e.g. `"project"`), never the raw user spelling.
    Present (non-`None`) for `success`, `zero_matches`, and `failed` —
    every state where a real, known category was actually established —
    and **only** `None` when `invalid_category` is `True`, since there is
    no canonical category to report for input that was never valid to
    begin with.
  - `error: str | None = None` — set only for a genuine
    `list_by_category()` exception.
  - `invalid_category: bool = False` — set only when `is_known_category()`
    rejected the supplied category; no lookup was ever attempted.

  `__post_init__` enforces mutual exclusivity across all four states:
  `invalid_category=True` requires `error is None`, `selected_ids == ()`,
  and `category is None`; `error is not None` requires
  `selected_ids == ()`; and any non-`invalid_category` state requires
  `category is not None` (a canonical category was always established
  before a lookup was attempted or failed). Four properties expose the
  states cleanly: `.success` (category set, error `None`, ids non-empty),
  `.zero_matches` (category set, error `None`, ids empty),
  `.invalid_category` (the stored field itself), and `.failed` (error
  set). `match_count` is a convenience property, `len(selected_ids)`.
  **Invalid category is never collapsed into zero matches, and never
  collapsed into lookup failure** — each of the four states is
  independently representable and independently testable.
- **Audit needs:** because categories are safe to log directly (unlike
  queries), `CategorySelectionResult.category` doubles as exactly the
  non-sensitive field the new audit event needs (§12) for `success`/
  `zero_matches`/`failed` — and its deliberate `None` value for
  `invalid_category` is exactly what prevents the audit event from ever
  fabricating a `category=general` or echoing raw invalid input (§12).

---

## 7. Ordering and Limit Contract

### 7.1 Ordering

`EpisodicMemoryStore.list_recent()`'s category-filtered path already uses
the **same** `created_at DESC, id DESC` deterministic ordering Phase 11
already relies on and has already been proven deterministic — **no new
architectural issue exists here; no narrow ordering fix is required.**
The selector preserves this order exactly, with no re-sorting anywhere,
exactly as Phase 11 already established for query results. Because
Phase 10's combined-context budget is order-sensitive, this means: within
a category, **newer memories are more likely to be fully included; older
memories in that category are more likely to be omitted for size** if the
category is large — the same honest, disclosed recency-bias consequence
Phase 11 already discloses, now applying to category selection too.

### 7.2 Limits — candidates evaluated

**Candidate A — exact fixed `limit=10`, mirroring Phase 11.** One call,
one deterministic result set, no separate reduction step, trivially
avoids ever exceeding `ingest_memories_for_ai()`'s own `max_records=10`
backstop since the numbers are equal by construction. Simplest to
explain and test.

**Candidate B — a category-specific bounded user limit** (e.g. an
optional trailing count in the command grammar). Rejected for the same
reason Phase 11 rejected its own equivalent: it expands command grammar
and parsing surface for a capability whose purpose is proving the
minimal deterministic path, with no demonstrated need yet.

**Candidate C — a larger category pool with deterministic reduction.**
Rejected for the same reason Phase 11 rejected it: because the store's
own ordering is already deterministic, "fetch 50, keep the newest 10"
produces an *identical* selected set to `list_by_category(limit=10)`
directly — the larger pool adds a second concept and a second thing to
test for a disclosure nuance not in scope.

**Chosen: Candidate A**, re-evaluated fresh (not copy-pasted) and
confirmed correct again for the same structural reasons: `select_memory_
ids_by_category()` calls `memory_manager.list_by_category(category,
limit=10)` explicitly — never the store's own default of 20, never a
larger pool.

### 7.3 Distinct limits, kept distinct

Mirroring Phase 11's own §5.3: the category-lookup `limit` (10, this
phase), `ingest_memories_for_ai()`'s `max_records` backstop (existing, 10,
never exceeded by construction), per-record `max_chars_per_record`
truncation (existing, Phase 9, 4000, unchanged), and the combined
`max_total_chars` ceiling (existing, Phase 10, 20,000, unchanged) remain
four separate, never-conflated concepts.

---

## 8. Failure Semantics

Distinguished explicitly, mirroring Phase 11's own four-category
structure, with one new, mandatory addition (invalid category) that
Phase 11's own model did not need:

1. **Empty category syntax** (`"summarise memories in"` with nothing, or
   only whitespace, after it): rejected by the **orchestrator**, before
   the selector is ever called — no lookup, no audit event, no AI
   consulted. This is the only state that never reaches the selector at
   all, mirroring Phase 11's own empty-query handling exactly.
2. **Unknown/invalid category name** (non-empty text that fails
   `is_known_category()`): detected by the **selector itself**
   (`CategorySelectionResult.invalid_category=True`, §5.3/§6) and rejected
   honestly, naming the known categories. **This state is audited**
   (`outcome=invalid_category`, §12), unlike state 1 — the selector was
   genuinely invoked and performed genuine, meaningful work (a validation
   check) before rejecting. `list_by_category()` itself is never called
   for this state, so `normalize_category()`'s silent `"general"` fallback
   never has an opportunity to fire — the case §2.1 identified as risky is
   structurally closed here, not merely avoided by convention.
3. **Valid category, zero records:** `list_by_category()` returns `[]`.
   Distinct, honest message (e.g. *"No stored memories are in the
   'project' category."*) — no ingestion attempted, no AI consulted.
4. **Category-lookup infrastructure failure:** `list_by_category()`
   raises. Caught once at the `select_memory_ids_by_category()` boundary
   and represented as a distinct, honest failure (e.g. *"Could not look
   up stored memories by category right now."*) — never as "zero
   records." No AI consulted.
5. **Selected records becoming unusable after lookup** (disappearance,
   retrieval error, size omission): represented entirely through Phase
   10's **existing, unmodified** accounting (`not_found`,
   `retrieval_errors`, `omitted_for_size`, `truncated_records`) — no new
   states (§15).
6. **No usable context after ingestion:** Phase 10's existing total-failure
   path applies unchanged; the AI is never consulted.

Category 2 (invalid category, now confirmed as a selector-detected,
audited outcome) and category 3 (valid category, zero records) remain the
two states Phase 11 never had an analogue for, kept honestly distinct
precisely because `is_known_category()` makes that distinction possible —
unlike a free-text search query, where "the query matched nothing" has no
meaningful "invalid query shape" counterpart beyond emptiness. Per this
clarification, category 2 is a *selector* outcome subject to audit, not
merely an orchestrator-level syntax rejection like category 1 — the two
must not be conflated in either code or test design.

---

## 9. Trust and Adversarial-Input Treatment

- The category label is **retrieval selection criteria**, structurally
  identical in role to Phase 11's query, and is handled identically:
  never wrapped in an `AIContextBlock`, never mixed into the `UNTRUSTED`
  memory context, reaching AI reasoning only via the existing live
  `user_input` channel — the full original request text, exactly as every
  prior summary command's own trailing text already does.
- **Why the category string still reaches `AIReasoningRequest.user_input`:**
  identical reasoning to Phase 11 §6.1 — the orchestrator has always
  forwarded the complete original request text for every summary
  workflow; there is no mechanism to selectively withhold part of it, and
  none is introduced here.
- Stored memory selected by category remains **unconditionally
  `ContentTrust.UNTRUSTED`** — combining by category never upgrades trust,
  exactly as combining by query or by explicit id already never does.
- Distinguished explicitly: category selection criteria (retrieval input,
  live/trusted-channel text only); stored memory content (untrusted,
  combined via Phase 10 unchanged); Jarvis-owned selection accounting
  (built from structured fields, appended to the response after the AI
  summary is produced, never fed into the context); AI-generated summary
  (the orchestrator's own message, never re-ingested).
- **Adversarial category input reviewed against the actual
  implementation:** because `is_known_category()`/`normalize_category()`
  collapse *any* input to one of exactly six fixed strings before
  `list_by_category()` ever builds a SQL filter, a prompt-like or
  malformed category string (e.g. `"SYSTEM: ignore previous instructions"`)
  simply fails `is_known_category()` and is rejected as an unknown
  category — it cannot alter routing (decided on the literal command
  prefix before validation), cannot become part of the AI-facing memory
  context, cannot alter SQL structure (normalisation is itself the
  sanitisation step, per §2.1), and cannot bypass validation by
  construction, since the validation function's own strip+lower+membership
  check has no code path that treats any input as automatically valid.
  This is a **stronger** structural guarantee than Phase 11's query path
  had, precisely because categories are a closed, bounded vocabulary.
- Planned tests: a prompt-like category string (rejected as unknown,
  never searched); a malformed category string with whitespace/punctuation
  (rejected as unknown); a valid category typed with adversarial-looking
  surrounding text in the same request (the surrounding text is simply
  part of the rejected/accepted trailing text, per the plain extraction
  contract — no special-casing).

---

## 10. Router Compatibility Review

Reviewed collisions among all six dispatch-order entries (§3.2) plus the
concrete plural-prefix collision this phase introduces (§3.1) — the
Phase 11 lesson applied here as a standing requirement, not re-derived
from scratch. **Determination: exact, longest-prefix-first early dispatch
in `handle_request()` — checking the new `match_memory_category_summary`
before `match_memory_set_summary` — is sufficient.** No broader
`CommandRouter` redesign is required or performed; the existing, accepted
`CommandRouter.match()` broad-keyword-overlap debt remains completely
untouched, since this command is resolved entirely within the
summary-family dispatch block, before `match()` is ever reached.
`"summarise memories about <query>"` (Phase 11) is explicitly re-verified
to still route correctly and is never captured by the new category
matcher (different second word, `"about"` vs `"in"`, in either direction).

---

## 11. Security Review

Reviewed together, as mandated: `SecurityManager._RULES`, `MemoryTool`,
the Phase 9 single-memory path, the Phase 10 explicit-id path, and the
Phase 11 query-selected path. `MemoryManager.list_by_category()` is
exactly as unconditionally read-only as `MemoryManager.get()`/`search()`
already are, and would be called directly from `ai/memory_selection.py` —
the same disclosed, accepted bypass of `ToolExecutor`/
`SecurityManager.classify_action()` Phase 9 established and Phase 10/11
already reused, now extended to a **fourth** direct call site.

**Determination: no new `ActionType`, no new `SecurityManager` rule, and
no compatibility-preserving refactor is required.** The inherited
`SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion
semantic-drift debt (documented since Phase 9, carried through Phase
10/11) is **reviewed again as mandated and reconfirmed acceptable,
non-blocking debt**, now with a fourth example (`list_by_category`)
alongside `get`/`search`. No concrete new risk this phase introduces
requires resolving it now; resolving it remains a larger, separately-scoped
security-architecture question. Category selection cannot cause a write,
update, or delete regardless of category content — searching and reading
by category remain in scope; mutating and deleting memory remain entirely
out of scope, still gated by the unchanged `memory_update`/`memory_forget`
YELLOW tools.

---

## 12. Audit Design and Privacy Decision

**A new, narrow, non-authoritative event is needed**, mirroring Phase 11's
own reasoning: per-id `memory_acquisition` events describe retrieval
outcomes *during ingestion*, not the fact that a category lookup was
performed or its outcome.

- **Event name:** `memory_category_selection`.
- **Fields (clarified — four possible outcomes):**
  `outcome=<success|zero_records|invalid_category|failure> [category=<str>]
  match_count=<int> selected_ids=<comma-joined ints, or empty>`.
  `category=` is present **only** when `CategorySelectionResult.category`
  is not `None` — i.e. for `success`, `zero_records`, and `failure`,
  where a real, canonical, validated category was actually established
  before the lookup was attempted (or failed). **For `invalid_category`,
  the `category=` field is omitted entirely** — never `category=<raw
  invalid text>`, and never `category=general`. This omission-when-absent
  shape mirrors the existing repository convention already used for the
  optional `reason=` field in `_emit_memory_acquisition_event`'s own
  detail string (present only when applicable, never a placeholder
  value) — no new formatting convention is invented for this.
- **Privacy decision, explicitly re-evaluated rather than copied from
  Phase 11:** unlike a free-text search query, **the category value is
  safe to log directly** when one was actually established.
  `normalize_category()` guarantees it is always one of exactly six
  short, fixed, non-sensitive, organisational-label strings (§2.1) —
  never arbitrary user free text. Logging `category=project` is
  materially more useful for review than logging only a length would be,
  and carries none of the privacy risk Phase 11's `query_length`-only
  design exists to avoid. This is a deliberate, justified divergence from
  Phase 11's audit-privacy stance, not an inconsistency — the two inputs
  have genuinely different sensitivity/cardinality profiles. **Raw,
  unvalidated category input is never logged under any circumstance** —
  for `invalid_category`, there is no canonical value to log by
  construction (`CategorySelectionResult.category is None`), so the
  omission is structural, enforced by the result model's own invariant
  (§6), not merely a judgement call made at logging time. The audit must
  never make an invalid category look like a successful canonical
  `"general"` selection, and this design guarantees that: `category=`
  simply cannot be populated with anything for that outcome.
- **Outcome semantics:** `EventOutcome.SUCCESS` when at least one id was
  selected; `EventOutcome.FAILURE` for `zero_records`, `invalid_category`,
  **and** a genuine lookup exception, distinguished via the `outcome=`
  field inside `detail` — mirroring the existing convention (a
  `not_found` id is already audited as `FAILURE` with a `reason=` field
  in this exact system) rather than inventing new `EventOutcome` members.
  No stronger repository-grounded alternative exists; this mapping is
  confirmed, not merely assumed.
- **No duplicate auditing:** this event fires once per request, describing
  only the category-lookup step; Phase 10's existing per-id
  `memory_acquisition` events, `AIRouter`'s `ai_call` event, and
  `PromptBuilder`'s injection-detection event are all reused completely
  unchanged and are not duplicated.
- **Logger-failure isolation:** the same narrow `try/except Exception:
  pass`, scoped only around the `emit()` call itself, identical in shape
  to `_audit_memory_query_selection`'s own precedent. Must be proven not
  to alter any of the four outcomes: `invalid_category` rejection,
  `zero_records` semantics, a successful selection, or lookup-failure
  semantics — observability remains non-authoritative for all four.

---

## 13. Selection-to-Ingestion Race

Identical structure to Phase 11 §11: a selected id can disappear or error
between `list_by_category()` and Phase 10's own later `MemoryManager.get()`
re-retrieval. **Phase 10's existing `not_found`/`retrieval_errors`/
`omitted_for_size`/`truncated_records` accounting fully represents every
category-selection race scenario — no new state is required.** No
transactions, locks, or snapshots are introduced, for the same reasons
Phase 11 already gave (single-user, local, SQLite-backed architecture; no
new or more severe race is introduced by reaching the same ids via a
different selection mechanism).

---

## 14. Proposed Batch Boundaries

Mirroring Phase 8–11's established three-batch shape:

- **Batch 1 — Category selection foundation.** `ai/memory_selection.py`
  extended with `select_memory_ids_by_category()` and
  `CategorySelectionResult`, including the selector's own defensive
  `is_known_category()`/`normalize_category()` validation and
  canonicalisation (§4/§5.3); module docstring updated to describe both
  selection concerns. No command/orchestrator wiring yet.
- **Batch 2 — Category command and orchestrator wiring.**
  `core/command_router.py`: new prefixes and
  `match_memory_category_summary()`. `core/orchestrator.py`: dispatch
  order insertion (before `match_memory_set_summary`), a narrow
  emptiness-only pre-flight check (the selector owns the actual
  known-category validation, per §4/§5.3), a new terminal handler reusing
  `ingest_memories_for_ai()` unchanged, and the new
  `memory_category_selection` audit event covering all four
  `CategorySelectionResult` outcomes.
- **Batch 3 — End-to-end verification and documentation.** Consolidated
  integration test, README update, `docs/phase_12_completion_report.md`.
  **Not performed in this planning turn.**

---

## 15. Exact Files Expected to Change

- **Modified:** `ai/memory_selection.py` (Batch 1 — additive; existing
  `select_memory_ids_by_query`/`QuerySelectionResult` untouched in
  behaviour).
- **Modified:** `core/command_router.py` (Batch 2 — new prefixes, new
  match method; zero change to any existing method's behaviour).
- **Modified:** `core/orchestrator.py` (Batch 2 — new dispatch branch
  before `match_memory_set_summary`, new handler, new audit event; zero
  change to any existing handler's behaviour).
- **New (Batch 1, not this turn):** `tests/unit/test_memory_selection.py`
  extended with category-selector tests (same file, since it already
  covers `ai/memory_selection.py`).
- **New (Batch 2, not this turn):** extensions to
  `tests/unit/test_command_router.py`; a new
  `tests/unit/test_memory_category_summary_workflow.py`.
- **New (Batch 3, not this turn):** a new
  `tests/integration/test_memory_category_summary_end_to_end.py`.
- **New/modified (Batch 3, not this turn):**
  `docs/phase_12_completion_report.md`, `README.md`.
- **This turn only:** `docs/phase_12_implementation_plan.md` (this
  document).

No change is proposed to `ai/prompt_builder.py`, `ai/router.py`,
`ai/reasoning_engine.py`, `ai/reasoning_models.py`, `ai/context_models.py`,
`ai/memory_ingestion.py`, `memory/memory_manager.py`,
`memory/episodic_memory.py`, `memory/memory_models.py`,
`tools/builtin/memory_tool.py`, `security/security_manager.py`, or
`storage/models.py`.

---

## 16. Test Strategy and Regression Floor

**Regression floor: 1124 passed, 0 failed — may only grow.** Planned
coverage (not written this turn) spans, at minimum: exact category-command
matching and spelling variants; routing precedence against Phase 11's
query command, Phase 10's plural command, Phase 9's singular command, and
the generic `_MEMORY_KEYWORDS` path; exact category-text extraction;
normalisation/validation via the reused `is_known_category()`/
`normalize_category()`, at the **selector layer specifically** (not
merely asserted at the orchestrator level); **every one of the five known
category values** (`general`/`personal`/`project`/`preference`/`note`)
individually; **canonical lowercase input** for each; **accepted case
variants** (`"PROJECT"`, `"Project"`) canonicalising to the same lowercase
form; **leading/trailing whitespace**, proven stripped at the correct
ownership layer (`CommandRouter`'s own `.strip()` on extraction, not a
second strip in the selector); an **unknown category** that is proven
`invalid_category=True`, not silently treated as `"general"` — including
the specific regression case of a category that, absent this phase's
validation, *would* have fallen back to `"general"` under
`normalize_category()` alone; an **empty category** (orchestrator-level
rejection, no selector call, no audit event — distinct from the
selector-level `invalid_category` outcome); **punctuation/prompt-like
category input** (rejected as unknown by the same `is_known_category()`
path, never specially interpreted); a **valid category with zero
records**; a **category-lookup exception**; exact `list_by_category()`
semantics (exact-match, case-insensitive, ordered `created_at DESC, id
DESC`); order preservation into the Phase 10 handoff with no
resort/dedup/ranking; the fixed `limit=10` ceiling; the search-to-ingestion
race (not_found/retrieval_errors) with no new states; partial success; no
usable context; no provider call for the invalid-category/empty/
zero-record/lookup-failure/no-usable-context states; continued
`ContentTrust.UNTRUSTED` preservation; provenance from the actually-
included set; the category string's exclusion from the memory context and
its (expected) presence in the live `user_input`; disclosure kept outside
the AI-facing context; the new `memory_category_selection` audit event's
**exact four-outcome fields** — including that the category value itself
is intentionally logged for `success`/`zero_records`/`failure` (unlike
Phase 11's query), and that `category=` is proven **absent** (never a raw
invalid string, never `category=general`) for `invalid_category`; a
logger raising selectively for that event not altering any of the four
outcomes; stored-result injection scanning still firing through the
unmodified `PromptBuilder` path; delimiter-imitation compatibility;
security/approval unchanged; RED/YELLOW unexpected-action compatibility;
provider failure; validation failure; and full Phase 8/9/10/11 regression.

Verification commands (for the future implementation turn):
```
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_category_summary_workflow.py -v
poetry run pytest tests/integration/test_memory_category_summary_end_to_end.py -v
poetry run pytest -v
```

---

## 17. Risks and Non-Blocking Debt

- **Carried forward, unchanged:** the `SecurityManager._RULES`/`MemoryTool`
  semantic-drift debt (now with a fourth example, `list_by_category`); the
  broad `CommandRouter.match()` keyword overlap; memory retrieval
  remaining unscoped by session; the recency bias inherent in reusing the
  store's own ordering under a size-limited budget; the search-to-ingestion
  TOCTOU-style race (same accepted class as Phase 10/11's).
- **New, disclosed by this plan:** the silent
  unknown-category-normalises-to-`"general"` behaviour (§2.1) — not a
  defect in the store (it is a deliberate, documented Phase 5 design
  choice for the *save*/*organise* workflows, where a permissive fallback
  is appropriate), but a genuine risk **specifically for a read/selection
  workflow** if this phase's own validation step were ever skipped or
  removed in a future refactor. This is why §4/§8 make the
  `is_known_category()` pre-flight check mandatory and explicit, not an
  optional nicety.

---

## 18. Scope Exclusions

Deliberately **not** implemented: semantic search; embeddings; vector
databases; hybrid lexical/vector retrieval; relevance ranking; LLM-based
category classification; AI-selected memory ids; autonomous memory
discovery; recency-based selection (a distinct, separately-scoped future
capability); any multi-strategy selector framework; category inference;
fuzzy category matching; multi-category boolean expressions or
intersections; combined query+category hybrid retrieval; background
indexing; chunking frameworks; long-context summarisation trees;
multi-user/session-isolation redesign; memory mutation; memory deletion.

---

## 19. Future Selection Architecture

After this phase, deterministic selection exists in three concrete forms —
explicit ids (Phase 10), query search (Phase 11), and category (Phase 12)
— all sharing the exact seam Phase 10 established: **a strategy produces
an ordered tuple of memory ids; `ingest_memories_for_ai()` combines them.**
A fourth, future form (recency-based selection) would fit the same seam
trivially. **No generic strategy-pattern abstraction, plugin interface, or
registry is introduced now** — with three concrete strategies, a shared
abstraction remains premature generalisation by this project's own
standing convention; that decision is deferred until a genuinely
compelling fourth or fifth strategy is being built and the *cost* of
continuing without an abstraction (not merely its aesthetic absence)
becomes concrete and demonstrable.

---

## 20. Final Recommendation

Proceed to Batch 1 (extending `ai/memory_selection.py`) only after this
plan is explicitly reviewed and approved, following the same
batch-by-batch approval discipline Phase 8–11 already established. No
production code, tests, or documentation beyond this plan file have been
written in this turn.

---

## Delivery Summary (updated by this clarification revision)

**This revision's three clarifications, in brief:**
- **Invalid-category correctness boundary (§5.2, §5.3, §6, §8):**
  Candidate B confirmed and adopted — `select_memory_ids_by_category()`
  itself defensively validates via the existing `is_known_category()` and
  returns a distinct `invalid_category` result; the orchestrator's own
  pre-check narrows to a pure emptiness check. `CategorySelectionResult`
  now carries four distinct, never-collapsed states (`success`,
  `zero_matches`, `invalid_category`, `failed`), each independently
  representable. Candidate A (orchestrator-only) rejected as making
  selector correctness depend on caller discipline; Candidate C (global
  behaviour change) rejected as disproportionate, out-of-scope blast
  radius.
- **Category normalisation/canonicalisation contract (§4):** the exact
  sequence — raw extraction (strip only) → orchestrator emptiness check →
  selector's `is_known_category()` → `normalize_category()` canonical
  form → `list_by_category()` — is now written out explicitly.
  `CategorySelectionResult.category` always carries the canonical,
  validated value (e.g. `"project"`), never the raw user spelling.
  Confirmed: `"PROJECT"` canonicalises to `"project"` under the existing,
  unmodified helper.
- **`memory_category_selection` audit fields/privacy (§12):** four
  outcomes (`success|zero_records|invalid_category|failure`); `category=`
  present only when `CategorySelectionResult.category is not None`
  (omitted entirely, not a placeholder, for `invalid_category`) — never
  the raw invalid string, never `category=general`. `EventOutcome.FAILURE`
  covers `zero_records`, `invalid_category`, and lookup failure alike,
  distinguished only via `outcome=`. Logger-failure isolation proven not
  to alter any of the four outcomes.

---

## Delivery Summary

1. **Repository findings:** §2 — category is a plain, required string
   column, five known values, silent-fallback normalisation with no
   rejection path (a genuine, material finding driving §4/§8's mandatory
   validation step), `list_by_category()` an exact-match filter reusing
   the store's already-deterministic ordering.
2. **Exact category model:** §2.1.
3. **Exact `list_by_category()` semantics:** §2.2.
4. **Proposed command surface:** `summarise memories in <category>` /
   `summarize memories in <category>`, §3, with a concrete, verified
   routing collision against Phase 10's plural matcher (the same class
   Phase 11 already discovered) and its resolution via longest-prefix-
   first dispatch, now a standing requirement (§3.2, §10).
5. **Parsing/normalisation contract:** §4 — exact sequence documented:
   orchestrator emptiness check → selector's `is_known_category()` →
   `normalize_category()` canonical form → `list_by_category()`; reused,
   never duplicated, category vocabulary; case variants (e.g. `"PROJECT"`)
   confirmed to canonicalise to `"project"`.
6. **Selection architecture and result-model decision:** §5 (extend
   `ai/memory_selection.py`, Candidate A, mirroring Phase 10's own
   ingestion-module-extension precedent), §5.3 (invalid-category
   correctness boundary — Candidate B adopted: the selector itself
   defensively validates, not the orchestrator alone), and §6 (a new
   `CategorySelectionResult` carrying four distinct, never-collapsed
   states — `success`/`zero_matches`/`invalid_category`/`failed` — not a
   reuse of `QuerySelectionResult`, justified by categories' different,
   safe-to-log sensitivity profile).
7. **Ordering and limit contract:** §7 — store ordering already
   deterministic, no new fix needed; Candidate A (`limit=10`, mirroring
   Phase 11) chosen after fresh re-evaluation.
8. **Failure semantics:** §8 — six distinct states, including the two
   (invalid category — now confirmed selector-detected and audited,
   distinct from the orchestrator's own empty-syntax rejection —
   and valid-category-zero-records) Phase 11 had no analogue for.
9. **Trust and adversarial-input treatment:** §9 — category never enters
   the untrusted memory context; validation's closed vocabulary, now
   enforced defensively inside the selector itself, gives a stronger
   structural guarantee against adversarial category strings than Phase
   11's free-text query ever had.
10. **Router compatibility review:** §10 — Phase 11's query command and
    Phase 10's plural command both re-verified unaffected.
11. **Security review:** §11 — no new `ActionType`/rule/refactor;
    semantic-drift debt reconfirmed acceptable with a fourth example.
12. **Audit design/privacy decision:** §12 — new `memory_category_selection`
    event with four outcomes (`success|zero_records|invalid_category|
    failure`); category value logged directly only when one was actually
    established (never for `invalid_category`, where `category=` is
    structurally omitted, never a raw string, never `category=general`) —
    a deliberate, justified divergence from Phase 11's query-privacy
    stance, not an inconsistency.
13. **Selection-to-ingestion race treatment:** §13 — fully represented by
    Phase 10's existing accounting, no new states.
14. **Proposed batch boundaries:** §14.
15. **Exact files expected to change:** §15.
16. **Test strategy and 1124-test floor:** §16.
17. **Risks/debt:** §17.
18. **Scope exclusions:** §18.
19. **Final recommendation:** §20 — proceed to Batch 1 only after explicit
    approval of this plan.
20. **Exact plan file created:** `docs/phase_12_implementation_plan.md`
    (this document).
21. **Git status:** working tree unchanged by this turn except for this
    new, untracked planning file; nothing staged or committed.
