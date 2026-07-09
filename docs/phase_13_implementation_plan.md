# Phase 13 Implementation Plan — Deterministic Recency-Based Automatic Memory Selection

Status: **Planning only. No production code, tests, README changes, completion
report, staging, or commits accompany this document.**

Phase number confirmed available by direct repository inspection: `docs/`
contains completion/implementation documentation through Phase 12 only
(`phase_12_completion_report.md`, `phase_12_implementation_plan.md`); no
`phase_13_*` file exists prior to this one.

Authoritative closure state this plan builds on, verified directly against
the repository rather than assumed: HEAD `b27623c048440c3638d9c1dcdb5ef09bae887f89`
("Complete Phase 12 deterministic category-based memory selection"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean (`git status
--porcelain` empty). `poetry run pytest -q` is accepted as authoritative at
**1267 passed, 0 failed** per the closure just approved; this plan does not
re-run the suite, since no code changed since that closure.

---

## 1. Purpose

Phase 11 proved a deterministic, explicit **query** could safely select a
bounded set of memory ids for AI reasoning. Phase 12 did the same for an
explicit **category**. Phase 13 answers the analogous question for **recency**:
**how does Jarvis turn an explicit user request for recent stored memories
into a deterministic, bounded, explainable ordered selection for AI
reasoning, using the repository's actual recency semantics rather than
inventing unsupported time-window meaning or giving the AI authority to
choose context?**

The scope is deliberately narrow: reuse `MemoryManager.list_recent()` exactly
as it already behaves, reuse Phase 10's ingestion/combination architecture
unchanged, and reuse the Phase 11/12 selection-layer precedent where it
genuinely fits — without inventing a time-window query capability, a
user-tunable count, or any AI involvement in selection.

---

## 2. Repository Findings — Exact `list_recent()` Semantics

### 2.1 Call chain

`MemoryManager.list_recent(limit: int = 20, *, category: str | None = None)`
(`memory/memory_manager.py:84`) delegates directly to
`EpisodicMemoryStore.list_recent(limit=limit, category=category)`
(`memory/episodic_memory.py:109`) — no logic of its own beyond the pass-through.
Notably, `MemoryManager.list_by_category()` (Phase 12's own foundation) calls
the **exact same store method**: `self._store.list_recent(limit=limit,
category=category)`. There is only one storage-layer implementation of
"newest records, optionally filtered by category" in the entire repository;
Phase 12's category selection and Phase 13's recency selection are two
different callers of the identical underlying query, distinguished only by
whether `category` is supplied.

### 2.2 Documented, verified behaviour

- **Input parameters:** `limit: int = 20`, `category: str | None = None`
  (keyword-only). Phase 13 will call it with `category=None` — recency is
  defined across all categories, never scoped to one (a category+recency
  hybrid is explicitly out of scope, §19).
- **Default limit:** 20 (`MemoryManager`/`EpisodicMemoryStore` agree). Not
  relevant to Phase 13's own call, which will pass an explicit limit exactly
  as Phase 11/12 already do for their own selection ceilings.
- **Maximum/clamp behaviour:** **none exists.** Neither `MemoryManager` nor
  `EpisodicMemoryStore` clamps, validates, or rejects `limit` — whatever
  integer is supplied is forwarded straight into SQLAlchemy's `.limit(limit)`,
  which becomes a SQL `LIMIT` clause. This is pre-existing, unchanged
  repository behaviour; Phase 13 will pass a fixed, code-level constant, never
  a user-supplied integer, so this absence of clamping is not a new risk this
  phase introduces (§7, §11).
- **Category interaction:** when `category` is not `None`, the store filters
  `EpisodicMemory.category == normalize_category(category)` before ordering
  and limiting. Phase 13's own call passes `category=None`, so this filter is
  never applied — recency selection queries the unfiltered table.
- **Exact ordering:** `.order_by(EpisodicMemory.created_at.desc(),
  EpisodicMemory.id.desc())` — a SQL-level `ORDER BY`, not a Python-side sort.
  Newest-`created_at`-first is primary; `id` descending is the deterministic
  secondary tie-break.
- **`created_at` handling:** `storage/models.py` defines
  `created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
  default=_utc_now, nullable=False, index=True)`, where `_utc_now()` returns
  "the current time as a timezone-aware UTC datetime." **Correction (Batch 1
  finding, verified by `test_created_at_is_utc_valued_though_sqlite_returns_it_naive`
  in `tests/unit/test_memory_selection.py`):** this describes only the
  *creation-side* value `_utc_now()` produces before it is written. Once
  written to and read back from this repository's SQLite backend, tzinfo is
  observed to be stripped — a retrieved `MemoryRecord.created_at` is a
  **naive** `datetime`, not an aware one. The repository-grounded contract
  is therefore: memory timestamps are created using UTC-valued time, but
  SQLite read-back currently strips tzinfo, so persisted/retrieved
  `created_at` values are observed as naive `datetime` values carrying
  UTC-valued clock data under normal repository creation. This plan does not
  claim, and Batch 1 did not test, that every historical or migrated
  timestamp in the database is guaranteed UTC-valued — only that timestamps
  produced through the normal `_utc_now()`-backed creation path are.
- **Tie-breaking:** `id DESC` is a genuine, load-bearing secondary sort key,
  not decorative — see §8 for why it is necessary and sufficient.
- **Newest-N vs. time-window filter:** **"recent" means the newest N stored
  records in repository order, full stop.** There is no `WHERE created_at >
  ...` clause, no time-window parameter, no relative-date parsing anywhere in
  `EpisodicMemoryStore`. Nothing in the method name implies otherwise once the
  implementation is actually read; this plan does not infer time-window
  semantics from the name "recent," per the explicit instruction.
- **Timezone-awareness:** created UTC-valued and aware at write time, but
  **observed naive on read-back** through this repository's SQLite backend
  (corrected above) — ordering is unaffected either way, since `ORDER BY`
  compares the same stored column representation on both sides of every
  comparison, regardless of whether that representation carries tzinfo.
- **Identical timestamps possible:** yes — two memories saved within the same
  wall-clock instant (a realistic occurrence for rapid successive `remember
  this:` calls, and routine in tests that construct several records without a
  synthetic delay) can share an identical `created_at`. `id DESC` fully
  resolves this: `id` is an autoincrementing primary key, so it is
  monotonically increasing with insertion order and can never itself tie.
- **Duplicate possibility:** none — each row is returned at most once per
  call; there is no join or fan-out in this query that could produce a
  repeated id.
- **Deleted/inactive record behaviour:** `MemoryManager.forget()` /
  `EpisodicMemoryStore.delete()` perform a **hard delete**
  (`db.delete(entry)`) — there is no soft-delete, tombstone, or `is_active`
  flag anywhere in the schema. A deleted memory is simply absent from every
  future `list_recent()` result; there is no "inactive but visible" state to
  handle.
- **Returned record shape:** `list[MemoryRecord]`, the same frozen dataclass
  (`id`, `content`, `source`, `session_id`, `created_at`, `category`) every
  other store method already returns — no new shape.
- **Lookup/storage error behaviour:** `list_recent()` performs no
  `try/except` of its own; a genuine database/session-layer exception (e.g. a
  connection failure inside `session_scope`) propagates as a raised
  exception to the caller, exactly like `search()` and `list_by_category()`
  already do. This is precisely the gap Phase 11/12's own selectors close at
  their own boundary — Phase 13's selector must do the same (§9).

---

## 3. Honest Definition of "Recent"

Evaluated against what the repository actually supports:

| Candidate | Repository support | Verdict |
|---|---|---|
| **A. Newest up-to-10 records, repository order** | Full — `list_recent(limit=10, category=None)` already does exactly this, today, unmodified. | **Chosen.** |
| B. Explicit time window (last 24h / 7 days) | **None.** No `WHERE created_at > ...`/`BETWEEN` capability exists anywhere in `EpisodicMemoryStore`. Adding it means a new store method or query parameter — a genuine new storage/query capability, not a selection-layer addition. | Rejected for this phase (§19). |
| C. User-specified count ("latest 5") | Trivial to wire (`limit` already accepts any int) but introduces a first user-controlled numeric parameter into this selection family, with its own malformed-input surface (negative, zero, huge, non-numeric, `LIMIT`-clamp absence per §2.2) that Phase 11/12 deliberately avoided by fixing their own ceilings. | Deferred (§19/§20), not chosen for this increment. |
| D. User-specified time period | Same gap as B, compounded by relative-date parsing (a much larger, separately-scoped capability: calendar/timezone semantics, "last week" ambiguity, etc.). | Rejected for this phase (§19). |

**Chosen: Candidate A.** "Recent" means exactly what `list_recent()` already,
deterministically means: the newest up-to-10 stored memory records across all
categories, ordered `created_at DESC, id DESC`, with no time-window
interpretation invented anywhere in this stack.

Per-candidate evaluation, for the record:
- **A** — full determinism (single SQL query, no ranking), full
  explainability ("the 10 most recently stored memories"), zero new routing
  complexity (no argument to parse), zero new validation complexity (no
  argument to validate), no new privacy/security surface (no new user-typed
  string reaches the selector at all — a strictly *narrower* input surface
  than Phase 11/12 introduced), and the cleanest future-compatibility story
  (a later count/time-window feature can be added as new, additional
  selector parameters without altering this decision).
- **B/D** — would require a new, disclosed `EpisodicMemoryStore` capability
  (out of scope per the instruction not to invent unsupported time-window
  meaning), plus an entirely new calendar/timezone-interpretation surface
  this plan is explicitly told to keep proportional (§8).
- **C** — moderate routing/validation complexity (a new invalid-count state,
  mirroring Phase 12's `invalid_category`, but for numeric input), no
  security implication beyond bounding the value, reasonable future
  compatibility — a legitimate second increment, not this one.

---

## 4. Proposed Command Surface

**Chosen phrasing:** `"summarise recent memories"` / `"summarize recent
memories"` — exactly two literal phrases, no wildcard variants, mirroring the
two-spelling (UK/US) convention every existing summary command already uses.

### 4.1 Collision review (Phase 11/12 lesson applied as a standing requirement)

The existing four summary-family prefixes are:

```
_MEMORY_SUMMARY_PREFIXES          = ("summarise memory", "summarize memory")
_MEMORY_QUERY_SUMMARY_PREFIXES    = ("summarise memories about", ...)
_MEMORY_CATEGORY_SUMMARY_PREFIXES = ("summarise memories in", ...)
_MEMORY_SET_SUMMARY_PREFIXES      = ("summarise memories", "summarize memories")
```

Phase 11 and 12 each collided with `_MEMORY_SET_SUMMARY_PREFIXES` because
their qualifier word ("about", "in") comes **after** "memories," making their
own prefix a strict superset-string of `"summarise memories"`.

Phase 13's candidate phrase places its qualifier **before** "memories":
`"summarise recent memories"`. Checking `"summarise recent
memories".startswith("summarise memories")` is **False** — the strings
diverge at the very next character after `"summarise "` (`'r'` vs `'m'`).
Verified in both directions against all four existing prefixes:

- vs. singular (`"summarise memory"`): diverges at `"summarise "` + `'r'`
  (recent) vs. `'m'` (memory) — no collision either direction.
- vs. query (`"summarise memories about"`): second word differs (`"recent"`
  vs. `"memories"`) — no collision either direction.
- vs. category (`"summarise memories in"`): same reasoning — no collision.
- vs. plural/explicit-id (`"summarise memories"`): as shown above — no
  collision either direction, unlike Phase 11/12's own qualifiers.

**Finding: `"summarise recent memories"` is a genuinely new, orthogonal
prefix that collides with none of the four existing summary-family
matchers, in either direction.** This is a materially simpler situation than
Phase 11/12 faced — dispatch-order placement relative to the other four
matchers is **not load-bearing for correctness** here (no ordering constraint
exists), though this plan still places the new check in the summary-family
dispatch block for narrative grouping (§10), documented as a non-binding
choice rather than a correctness requirement.

Also confirmed non-colliding with `CommandRouter.match()`'s broad
`_MEMORY_KEYWORDS = ("memory", "memories", "remember", "recall")`
substring-contains check — irrelevant regardless, since the summary-family
matchers are all checked in `handle_request()` before `match()` is ever
reached (§10).

### 4.2 Rejected variants

Per the explicit instruction, no vague natural-language variants
("what have I been thinking about lately," "catch me up on my memories,"
etc.) are added — none of them are deterministically routable without either
a keyword heuristic (ambiguous, unreviewable) or an AI-driven interpretation
step (exactly the authority-to-the-AI outcome this whole selection-layer
lineage exists to avoid).

---

## 5. Selector / Result-Model Decision

### 5.1 New primitive: `select_recent_memory_ids()`

Add to `ai/memory_selection.py`, mirroring `select_memory_ids_by_query()`'s
shape most closely (no input-validation state is needed — see §5.2):

```python
_RECENT_SELECTION_LIMIT = 10
_RECENT_LOOKUP_FAILURE_MESSAGE = "Could not look up recent stored memories right now."

def select_recent_memory_ids(
    memory_manager: MemoryManager,
    *,
    limit: int = _RECENT_SELECTION_LIMIT,
) -> RecentSelectionResult:
    try:
        records = memory_manager.list_recent(limit=limit)
    except Exception:
        return RecentSelectionResult(error=_RECENT_LOOKUP_FAILURE_MESSAGE)

    selected_ids = tuple(record.id for record in records)
    return RecentSelectionResult(selected_ids=selected_ids)
```

This answers exactly the narrow question the instruction specifies — "what
ordered ids did the repository's deterministic recent-memory lookup
return?" — and nothing more. It takes no free-text or category argument, so
(unlike Phase 12) there is no defensive pre-validation step to perform: there
is no invalid input for a zero-argument lookup to reject. `category=None` is
never exposed as a parameter here; a category-scoped recency call would be a
hybrid retrieval strategy, explicitly deferred (§19).

**Does NOT** (mirroring the existing module's own conventions): retrieve
content, construct an `AIContextBlock`, call `ingest_memories_for_ai()`,
emit any audit event, or rank/reorder `list_recent()`'s own result.

### 5.2 New result model: `RecentSelectionResult`

**Decision: add a new, dedicated, minimal result model — do not reuse
`QuerySelectionResult` or `CategorySelectionResult`.**

- Reusing `QuerySelectionResult` would force every recency call to populate
  a `query_length` field with a meaningless value (there is no query text),
  which is exactly the kind of semantically dishonest field-repurposing
  Phase 12 itself rejected when it introduced `CategorySelectionResult`
  rather than stretching `QuerySelectionResult` to cover categories.
- Reusing `CategorySelectionResult` would be worse: it would force a
  meaningless `category` field and force satisfying its
  `invalid_category`-related invariants for a selector that has no such
  state to represent.
- A "compatibility-preserving generalisation" (e.g. a shared base with
  optional fields) is not justified: there is no immediate code-sharing need
  strong enough to outweigh the blast radius of touching Phase 11/12's
  already-shipped, already-tested result models. The instruction is explicit
  that Phase 11/12 selectors must not be generalised "merely for symmetry."

`RecentSelectionResult` is therefore the **smallest** of the three result
models — it carries only what a parameter-free lookup can meaningfully
represent:

```python
@dataclass(frozen=True, slots=True)
class RecentSelectionResult:
    selected_ids: tuple[int, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if self.error is not None and self.selected_ids:
            raise ValueError(...)  # mirrors QuerySelectionResult exactly

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.selected_ids)

    @property
    def zero_matches(self) -> bool:
        return self.error is None and not self.selected_ids

    @property
    def failed(self) -> bool:
        return self.error is not None
```

Three states — `success` / `zero_matches` / `failed` — exactly Phase 11's
shape, never collapsed. No fourth "invalid parameter" state exists because
Candidate A (§3) introduces no user-controlled parameter to be invalid.

---

## 6. Ordering Decision

Because Phase 10's combined-context budget (`ingest_memories_for_ai`,
`max_total_chars`) processes `memory_ids` in exactly the order supplied and
omits-for-size whichever records do not fit **starting from wherever the
running total first overflows**, the order recency selection hands to
ingestion is a genuine, consequential architectural decision — not cosmetic.

### 6.1 Candidates

- **A — preserve repository newest-first order exactly.** Pass
  `selected_ids` to `ingest_memories_for_ai()` in precisely the order
  `list_recent()` returned them (newest first).
- **B — select newest N, then reverse the selected set into chronological
  (oldest→newest) order before ingestion**, so the AI reads a coherent
  timeline rather than newest-to-oldest.
- **C — change storage/query ordering** (e.g. add an
  `EpisodicMemoryStore` parameter to return oldest-first). Rejected outright:
  it would modify `memory/episodic_memory.py`, a component every prior phase
  (9–12) explicitly left unchanged, and would alter `list_recent()`'s
  behaviour for every other caller (Phase 12's own category selection calls
  the identical method), not just this new selector.

### 6.2 Analysis

- **User intent:** a user asking for "recent memories" likely wants a
  reasonably coherent narrative when summarised — B's chronological-read
  argument has real merit here, more than it would for Phase 11/12's
  criteria (an arbitrary query match or category has no inherent "reading
  direction").
- **Provenance:** either order is equally honest — `ingest_memories_for_ai`'s
  `source=f"memory-set:{included ids}"` label simply reflects whichever
  order was actually supplied; this is a labelling detail, not a security
  concern.
- **Budget interaction — the deciding factor:** `ingest_memories_for_ai`
  processes `memory_ids` in supplied order and appends to `omitted_for_size`
  whichever records overflow the running total, **starting from where the
  overflow first occurs and continuing to the end of the sequence** (a
  single forward streaming pass, never revisited). Under **Candidate A**
  (newest-first), if the budget is exceeded partway through, the ids
  omitted are the **oldest of the selected N** — the newest, most relevant
  memories are always kept. Under **Candidate B** (reversed to
  oldest-first for narrative coherence), the exact same streaming behaviour
  means the ids omitted on overflow are the **newest of the selected N** —
  the single memory the user most wanted included (the most recent one) is
  the first candidate to be dropped. This directly inverts the entire
  purpose of a "recent" selection whenever the combined content exceeds
  `max_total_chars`. This is a concrete, mechanical consequence of Phase
  10's existing streaming-omission design, not a hypothetical concern.
- **Explainability:** Candidate A's disclosure ("these are the N most
  recent memories, newest first, any overflow drops the oldest of them")
  is simpler and strictly truthful about what actually happened. Candidate
  B would need a caveat ("shown oldest-first for readability, but overflow
  still silently drops the newest one") that contradicts the surface framing.
- **Consistency with Phase 11/12:** both prior phases established "whatever
  order the store returns is exactly what is reported/ingested — no
  re-sorting" as a standing convention (`docs/phase_11_implementation_plan.md`
  §5.2; `docs/phase_12_implementation_plan.md` §7.1). Candidate A extends
  that convention; Candidate B would be the first selector to deviate from
  it, and would need to do so for a benefit (reading coherence) that is
  actively undermined by the budget-omission mechanics above.

**Chosen: Candidate A — preserve `list_recent()`'s own newest-first order
exactly, unmodified, all the way through to `ingest_memories_for_ai()`.**
Candidate B is rejected specifically because it would silently drop the most
recent memory first on any budget overflow, contradicting the very selection
criterion the user asked for. This residual limitation (the AI reads
newest-first content, not a chronological narrative) is disclosed as a known,
accepted framing choice (§17) rather than treated as solved — a future,
separately-scoped Phase 10 enhancement could expose an independent "display
order" distinct from "omission-priority order" if this is ever felt to be a
real problem, but that is out of scope here (§19/§20).

---

## 7. Limit Contract

- **Recency lookup limit:** fixed constant `_RECENT_SELECTION_LIMIT = 10`,
  passed explicitly to `memory_manager.list_recent(limit=...)` — never
  relying on `list_recent()`'s own default (20), exactly mirroring how Phase
  11/12 never rely on `search()`/`list_by_category()`'s own defaults either.
- **Selected-record ceiling:** identical value (10) — there is only one
  ceiling here, not two, because `list_recent()`'s `LIMIT` clause already
  produces exactly the newest-N rows directly; no separate "selected-record
  ceiling" distinct from the "lookup limit" is needed.
- **Interaction with Phase 10's `max_records=10`:** equal by explicit design,
  not by coincidence — identical to the existing, already-reviewed
  relationship between `_SELECTION_LIMIT`/`_CATEGORY_SELECTION_LIMIT` and
  `ai/memory_ingestion.py`'s own `_DEFAULT_MAX_RECORDS`. Two independently
  configurable constants, intentionally set equal, never conflated as one
  concept in code.
- **User-specified count:** not supported in this increment (§3, Candidate
  C deferred).
- **Larger candidate pool with reduction:** rejected (Candidate C in §7's
  own evaluation set, distinct from §3's Candidate C) — `list_recent(limit=10)`
  already returns exactly the correct newest-10 set directly from SQL;
  fetching more and reducing in Python would add complexity and a second,
  redundant ordering decision with no behavioural benefit.
- **No ranking is added** — the store's own `created_at DESC, id DESC` order
  is the entirety of the selection criterion.

---

## 8. Timestamp / Tie-Breaking Analysis

- **Type:** Python `datetime`, stored as SQL `DateTime(timezone=True)`.
- **Timezone-awareness — corrected per Batch 1 finding:** created
  UTC-valued and timezone-aware at write time (`_utc_now()` in
  `storage/models.py`), but this repository's SQLite backend is observed to
  **strip tzinfo on read-back** — `MemoryManager.get()`/`list_recent()` and
  every other read path return a **naive** `datetime` whose numeric value is
  still UTC (proven directly in Batch 1 by
  `test_created_at_is_utc_valued_though_sqlite_returns_it_naive`). The
  earlier planning claim "created_at is always UTC and timezone-aware" is
  corrected accordingly: it is accurate only for the value `_utc_now()`
  produces before persistence, not for what any caller subsequently reads
  back.
- **Why this does not invalidate Phase 13's newest-N ordering:** ordering is
  delegated entirely to `list_recent()`'s own SQL `ORDER BY
  created_at DESC, id DESC` — a database-side column comparison, never a
  Python-side timezone conversion or elapsed-time calculation. Phase 13
  performs no time-window comparison, no "last 24 hours" semantics, no
  local-time/calendar interpretation, and no timezone conversion of any
  kind; it only trusts the store's own ordering and lets `id DESC` resolve
  ties. Because tzinfo presence/absence plays no role in any of that, the
  observed naive-on-read-back behaviour is **non-blocking specifically for
  this newest-N selection capability** — this is not a claim that timezone
  representation is irrelevant in general (see §18), only that this
  particular capability does not depend on it.
- **UTC/local assumptions:** none needed at the selection layer — comparison
  and ordering happen entirely inside the database via `ORDER BY`, never via
  Python-side datetime arithmetic that could be tripped up by a naive/aware
  mismatch or a host machine's local timezone.
- **Ordering source:** the SQL `ORDER BY` clause itself, not any
  post-query Python sort — `list_recent()` never reorders what the database
  already returned in order.
- **Clock changes:** a backward system clock adjustment between two inserts
  could, in principle, cause a later-inserted row to carry an earlier
  `created_at` than an earlier-inserted row — `id DESC` does not correct for
  this (it only tie-breaks *identical* timestamps; it cannot detect or repair
  a timestamp that is merely out of step with insertion order). This is a
  pre-existing property of `_utc_now()`/`list_recent()` shared by every
  existing caller (`list_by_category()`, generic listing) — not a new risk
  Phase 13 introduces, and not something this phase's selector can or should
  attempt to correct (that would require Phase 13 to second-guess the
  store's own ordering, which the instruction explicitly forbids as
  "silently reordering").
- **Identical `created_at` values:** confirmed possible (§2.2) — `id DESC`
  provides a genuinely deterministic secondary key, since `id` is an
  autoincrementing primary key that strictly increases with insertion order
  and can never itself collide.
- **Proportionality:** because no time-window filtering exists or is being
  added (§3), this analysis is deliberately scoped to ordering/tie-breaking
  only — no calendar or timezone subsystem is designed or justified here.

---

## 9. Failure Semantics

| Scenario | Handling |
|---|---|
| No stored memories at all | `RecentSelectionResult.zero_matches` — a valid, deterministic fact (nothing to select), not an infrastructure problem. |
| `list_recent()` infra failure (raised exception) | `RecentSelectionResult.failed`, `error=_RECENT_LOOKUP_FAILURE_MESSAGE` — generic, honest, never embeds the raw exception text, mirroring `_SEARCH_FAILURE_MESSAGE`/`_CATEGORY_LOOKUP_FAILURE_MESSAGE`. |
| Selected record disappears before Phase 10 ingestion | Fully covered by `MemorySetIngestionResult.not_found` — no new state (§15). |
| Retrieval error during Phase 10 ingestion | Fully covered by `MemorySetIngestionResult.retrieval_errors` — no new state. |
| All selected records omitted for size | `ingestion.success` is `False`; handled by the existing "not `ingestion.success`" branch, returning `ingestion.error`'s itemized message — mirrors the category/query handlers exactly. |
| No usable context after ingestion | The provider is never called — the existing handlers already return before constructing `AIReasoningRequest` in this case; the same structure is reused unchanged. |
| Invalid syntax (count/time parameter) | **Not applicable** — no user-controlled parameter exists in this increment (§3/§5.1). |

No stored-record scenario and no lookup-infrastructure failure are ever
collapsed into one another — `zero_matches` and `failed` remain fully
distinct properties, exactly as Phase 11 established.

---

## 10. Trust and Adversarial-Input Treatment

- **"Recent" is selection criteria, not stored memory content.** The literal
  command text (`"summarise recent memories"`) carries no per-request
  variable data at all — unlike a query or category, there is nothing
  user-supplied to extract, validate, or reason about at the router layer.
- **Stored selected memories remain `ContentTrust.UNTRUSTED`** — unchanged,
  via the same, unmodified `ingest_memories_for_ai()` call every other
  summary workflow already uses.
- **Live `user_input`:** mirroring every existing handler exactly, the new
  `_handle_memory_recent_summary_request()` will pass
  `user_input=user_request` (the full original request text) into
  `AIReasoningRequest` — not just an extracted fragment (there is no
  fragment to extract here; the entire phrase is fixed). This is consistent
  with how the category/query handlers already pass the *full* original
  request, not merely the trailing extracted text.
- **Jarvis-owned selection accounting** (the selected ids, the match count)
  stays entirely in the audit event and the disclosure appended to the
  response message — never inserted into the `AIContextBlock`/memory
  context, exactly as query text and category names are already kept out of
  the context block and confined to `user_input`/disclosure.
- **Recency must not upgrade trust** — and cannot, structurally:
  `ingest_memories_for_ai()` only ever produces `ContentTrust.UNTRUSTED`
  blocks regardless of which selector supplied the ids.
- **Dispatch precedence** is not itself a trust boundary, but is verified
  correct in §4.1/§13 regardless.

### 10.1 New adversarial surface: none

Because the command has no free-text or numeric argument at all, this phase
introduces **no new adversarial input surface at the command-parsing or
selection layer** — a strictly narrower attack surface than Phase 11's query
text or Phase 12's category text, both of which had to defend against
malformed/adversarial user-typed strings. The only adversarial content that
can reach the AI is the stored memory content itself, exactly as for every
existing memory-summary command — handled entirely by the existing,
unmodified `PromptBuilder` injection scanner over the `UNTRUSTED` combined
context. No new scanner is added. (If a future count/time parameter is ever
added, per §3/§19, *that* increment would need to review malformed numeric/
date input at that time — explicitly out of scope now.)

---

## 11. Router Compatibility Review

Confirmed in §4.1: the new prefix pair collides with none of the four
existing summary-family matchers in either direction, and is resolved
entirely within the summary-family dispatch block in `handle_request()`,
before `CommandRouter.match()` (and its broad `_MEMORY_KEYWORDS`
substring-contains check) is ever reached. Because no collision exists,
dispatch-order placement relative to the singular/query/category/plural
checks is not load-bearing for correctness — unlike Phase 11/12, where a
specific check-before-plural-matcher ordering was mandatory. This plan still
places `match_memory_recent_summary` in a fixed, documented position (grouped
with the other summary-family checks, before `match_memory_set_summary`, for
narrative consistency) but the completion report/tests will explicitly prove
correctness does not depend on that position, distinguishing it from Phase
11/12's genuine ordering requirement.

No broader `CommandRouter` redesign is required; the existing, accepted
`CommandRouter.match()` broad-keyword-overlap debt remains untouched, since
this command never reaches `match()`.

---

## 12. Security Review

Reviewed together, as mandated: `SecurityManager._RULES`, `MemoryTool`, and
the Phase 9/10/11/12 AI-memory-summary paths. `MemoryManager.list_recent()`
is exactly as unconditionally read-only as `get()`/`search()`/
`list_by_category()` already are, and will be called directly from
`ai/memory_selection.py` — the same disclosed, accepted bypass of
`ToolExecutor`/`SecurityManager.classify_action()` Phase 9 established and
Phase 10/11/12 already reused, now extended to a **fifth** direct call site.

**Determination: no new `ActionType`, no new `SecurityManager` rule, and no
compatibility-preserving refactor is required.** The inherited
`SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-ingestion
semantic-drift debt (documented since Phase 9, carried through Phase
10/11/12) is reviewed again as mandated and **reconfirmed acceptable,
non-blocking debt**, now with a fifth example (`list_recent`) alongside
`get`/`search`/`list_by_category`. Recency selection cannot cause a write,
update, or delete regardless of which records it selects — reading the
newest stored memories remains in scope; mutating/deleting memory remains
entirely out of scope, still gated by the unchanged `memory_update`/
`memory_forget` YELLOW tools. This is the third consecutive phase to
reconfirm this exact debt as non-blocking without any new concrete risk
requiring its resolution now; resolving it remains a larger, separately-scoped
security-architecture question, unchanged from Phase 12's own conclusion.

---

## 13. Audit Design

- **Event name:** `memory_recent_selection` (mirrors
  `memory_query_selection`/`memory_category_selection` naming).
- **Fields:** `outcome=<success|zero_records|failure> match_count=<int>
  selected_ids=<comma-joined ints, or empty>`.
- **No `requested_count` field.** Because the limit is a fixed, code-level
  constant (10) with no per-request variance (§3/§7 — Candidate A introduces
  no user-tunable count), logging `requested_count=10` on every single event
  would be a constant, redundant value carrying no review-time information —
  the same reasoning Phase 12 already applied when it declined to add
  fields that would be constant across every event of a given outcome.
- **Outcome semantics:** `EventOutcome.SUCCESS` when at least one id was
  selected; `EventOutcome.FAILURE` for both `zero_records` and a genuine
  lookup exception, distinguished via the `outcome=` field inside `detail` —
  mirroring the existing two-state-collapsed-to-one-`EventOutcome` convention
  Phase 11's own `_audit_memory_query_selection` already established (no
  third `EventOutcome` member is invented).
- **No invalid-parameter outcome** — there is no such state to represent in
  this increment.
- **No content logged, ever** — only ids, a count, and the fixed outcome
  label; no memory text.
- **No double-auditing:** this event fires once per request, describing only
  the recency-lookup step; Phase 10's existing per-id `memory_acquisition`
  events, `AIRouter`'s `ai_call` event, and `PromptBuilder`'s
  injection-detection event are all reused unchanged, not duplicated.
- **Logger-failure isolation:** the same narrow `try/except Exception: pass`,
  scoped only around the `emit()` call itself, identical in shape to
  `_audit_memory_query_selection`/`_audit_memory_category_selection`. Must be
  proven not to alter any of the three outcomes (`success`, `zero_records`,
  `failed`) — observability remains non-authoritative for all three.

---

## 14. Selection-to-Ingestion Race Treatment

Identical structure to Phase 11 §11 / Phase 12 §13: a selected id can
disappear or error between `list_recent()` and Phase 10's own later
`MemoryManager.get()` re-retrieval inside `ingest_memories_for_ai()`.
**Phase 10's existing `not_found`/`retrieval_errors`/`omitted_for_size`/
`truncated_records` accounting fully represents every recency-selection
race scenario — no new state is required.** No transactions, locks, or
snapshots are introduced, for the same reasons Phase 11/12 already gave
(single-user, local, SQLite-backed architecture; reaching the same ids via a
third selection mechanism introduces no new or more severe race than the
first two already accepted).

---

## 15. Proposed Batch Boundaries

Mirroring Phase 9–12's established three-batch shape:

- **Batch 1 — Recency selection foundation.** `ai/memory_selection.py`
  extended with `select_recent_memory_ids()` and `RecentSelectionResult`;
  module docstring updated to describe all three selection concerns
  (query/category/recency) as siblings. No command/orchestrator wiring yet.
- **Batch 2 — Recency command and orchestrator wiring.**
  `core/command_router.py`: new prefixes and
  `match_memory_recent_summary()`. `core/orchestrator.py`: dispatch
  insertion in `handle_request()` (position documented as non-load-bearing,
  §11), a new terminal handler (`_handle_memory_recent_summary_request`)
  reusing `ingest_memories_for_ai()` unchanged, and the new
  `memory_recent_selection` audit event covering all three
  `RecentSelectionResult` outcomes. Unlike Phase 11/12, there is no
  empty-input pre-flight check to add (no argument exists to be empty).
- **Batch 3 — End-to-end verification and documentation.** Consolidated
  integration test, README update, `docs/phase_13_completion_report.md`.
  **Not performed in this planning turn.**

---

## 16. Exact Files Expected to Change

- **Modified:** `ai/memory_selection.py` (Batch 1 — additive; existing
  `select_memory_ids_by_query`/`QuerySelectionResult` and
  `select_memory_ids_by_category`/`CategorySelectionResult` untouched in
  behaviour).
- **Modified:** `core/command_router.py` (Batch 2 — new prefixes, one new
  match method; zero change to any existing method's behaviour).
- **Modified:** `core/orchestrator.py` (Batch 2 — new dispatch branch, new
  handler, new audit event; zero change to any existing handler's
  behaviour).
- **New (Batch 1, not this turn):** extensions to
  `tests/unit/test_memory_selection.py` (already covers `ai/memory_selection.py`).
- **New (Batch 2, not this turn):** extensions to
  `tests/unit/test_command_router.py`; a new
  `tests/unit/test_memory_recent_summary_workflow.py`.
- **New (Batch 3, not this turn):** a new
  `tests/integration/test_memory_recent_summary_end_to_end.py`.
- **New/modified (Batch 3, not this turn):**
  `docs/phase_13_completion_report.md`, `README.md`.
- **This turn only:** `docs/phase_13_implementation_plan.md` (this
  document).

No change is proposed to `ai/prompt_builder.py`, `ai/router.py`,
`ai/reasoning_engine.py`, `ai/reasoning_models.py`, `ai/context_models.py`,
`ai/memory_ingestion.py`, `memory/memory_manager.py`,
`memory/episodic_memory.py`, `memory/memory_models.py`,
`tools/builtin/memory_tool.py`, `security/security_manager.py`, or
`storage/models.py`.

---

## 17. Test Strategy and Regression Floor

**Regression floor: 1267 passed, 0 failed — may only grow.** Planned
coverage (not written this turn) spans, at minimum:

- Exact recency-command matching for both spellings; exact non-collision
  proof against all four existing summary matchers in both directions
  (§4.1), plus a proof that the generic `_MEMORY_KEYWORDS` path in
  `CommandRouter.match()` is never reached for this command.
- Dispatch-order-independence proof: the recency handler fires correctly
  regardless of its position relative to the other four matchers (distinct
  from Phase 11/12's genuine ordering requirement — this is the test that
  demonstrates the difference).
- Exact `list_recent()` semantics at the selector layer: default `category=None`
  is always passed; the fixed `limit=10` ceiling; newest-first order
  preserved exactly, unmodified, into the returned ids.
- Zero stored memories (`zero_matches`); a `list_recent()` lookup exception
  (`failed`); the mutual-exclusivity invariant on `RecentSelectionResult`.
- Identical-`created_at` tie-breaking resolved deterministically by `id DESC`
  (constructing two records with the same timestamp, if the test harness can
  force this, or documenting the store-level guarantee otherwise).
- Selected-ids-to-Phase-10-handoff order preservation — proof that ingestion
  receives ids in the exact same newest-first order the selector returned,
  never reversed (validating the §6 decision directly, not merely asserting
  it in prose).
- No ranking, no dedup, no re-sort anywhere in the new selector.
- No duplicate ingestion logic — `ingest_memories_for_ai()` is the sole
  ingestion call site, reused unchanged.
- Selection-to-ingestion disappearance/retrieval-error/partial-success/
  no-usable-context scenarios, and proof the AI provider is never called for
  the last of these.
- Continued `ContentTrust.UNTRUSTED` preservation; provenance
  (`source=f"memory-set:{included ids}"`) reflecting only the actually
  included ids.
- The fixed command phrase's absence from the memory context and its
  presence in the live `user_input`; disclosure (match count, etc.) kept
  outside the AI-facing context.
- Stored-result injection scanning still firing through the unmodified
  `PromptBuilder` path (with `injection_logger=logger` explicitly wired in
  the end-to-end test, per the exact regression Phase 12's own Batch 3
  initially missed); delimiter-imitation compatibility.
- The new `memory_recent_selection` audit event's exact three-outcome
  fields, no memory content logged, no `requested_count` field; a logger
  raising selectively for this event not altering any of the three outcomes.
- Security/approval behaviour unchanged; RED/YELLOW unexpected-action
  compatibility preserved; provider failure; validation failure.
- Full Phase 8/9/10/11/12 regression, run as part of the full suite.

Verification commands (for the future implementation turn):
```
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_recent_summary_workflow.py -v
poetry run pytest tests/integration/test_memory_recent_summary_end_to_end.py -v
poetry run pytest -v
```

---

## 18. Risks and Non-Blocking Debt

- **Carried forward, unchanged:** the `SecurityManager._RULES`/`MemoryTool`
  semantic-drift debt (now with a fifth example, `list_recent`); the broad
  `CommandRouter.match()` keyword overlap; memory retrieval remaining
  unscoped by session; the search/category/recency-to-ingestion
  TOCTOU-style race (same accepted class as Phase 10/11/12's).
- **New, disclosed by this plan:** the newest-first ingestion order (§6)
  means that under total-size budget pressure, the *oldest* of the selected
  10 records are dropped first, not the newest — the intended, correct
  priority, but it also means the AI never receives a chronologically
  ordered narrative, only a newest-first-framed one. A future,
  separately-scoped enhancement to `ingest_memories_for_ai()` could
  decouple "omission priority order" from "display order" if this is ever
  found to matter in practice; not attempted here.
- **New, disclosed by this plan:** `list_recent()`'s clock-skew edge case
  (§8) — a backward system clock adjustment could theoretically place a
  later-inserted record earlier in `created_at` order than an
  earlier-inserted one. Pre-existing in the store, not introduced by this
  phase, and not corrected by it (correcting it would require Phase 13 to
  second-guess the store's own ordering, which is out of scope).
- **New, confirmed by Batch 1's own tests (corrects an earlier planning
  claim):** SQLite tzinfo stripping is pre-existing timestamp-representation
  debt. `created_at` is created UTC-valued and timezone-aware
  (`_utc_now()`), but every read path in this repository returns it as a
  **naive** `datetime` once persisted to and retrieved from SQLite — not
  "always timezone-aware," as an earlier revision of this plan claimed
  before Batch 1 tested the actual round-trip. This is **non-blocking for
  Phase 13's newest-N selection** (§8), which never compares, converts, or
  interprets timestamp values directly. It **must be reviewed before**
  implementing any of the following, none of which are in scope for Phase
  13: last-N-hours retrieval; calendar-day retrieval; timezone-aware memory
  filtering; relative-date semantics ("yesterday," "this week");
  cross-timezone interpretation; or any timestamp-migration guarantee that
  assumes historical `created_at` values are provably, uniformly UTC. Not
  fixed in Phase 13; no timezone-normalisation code is added; `MemoryManager`,
  `EpisodicMemoryStore`, the models, and the schema all remain unchanged.
- **Explicitly deferred, not a defect:** no time-window or user-count
  capability exists yet (§3/§19) — "recent" is honestly narrower than a
  calendar-aware reader might assume, and the completion report (when
  written) must state this plainly rather than let the phrase "recent
  memories" imply more than newest-N.

---

## 19. Scope Exclusions

Explicitly reviewed and deferred:

- Semantic search, embeddings, vector databases, hybrid retrieval,
  relevance ranking, AI-selected memory ids, autonomous memory discovery.
- Category inference; query+category+recency hybrid retrieval; a generic
  multi-strategy/selector-framework abstraction (each selector remains a
  plain function + dataclass pair, §20).
- Time-window retrieval (last 24h/7 days) — no repository support exists;
  adding it is a new, separately-scoped `EpisodicMemoryStore` capability.
- Natural-language date parsing; relative-date interpretation; calendar-aware
  memory filtering; user-defined retention periods.
- Background indexing, chunking, summarization trees, multi-user/session
  redesign, memory mutation, memory deletion.
- User-specified recent-count (Candidate C, §3) — a legitimate, narrow
  future increment, not this one.

---

## 20. Future Retrieval Architecture

Explicit-id (Phase 10), query (Phase 11), category (Phase 12), and now
recency (Phase 13) coexist in `ai/memory_selection.py` as four independent,
narrow, deterministic functions, each answering the same question in its own
terms — "what ordered ids did the repository's own deterministic mechanism
return for this validated input?" — and each feeding the identical, unchanged
Phase 10 `ingest_memories_for_ai()` boundary. A future semantic/embedding
retrieval strategy could add a fifth sibling selector (e.g.
`select_memory_ids_by_similarity()`) with its own result model, without
altering `ingest_memories_for_ai()`'s contract at all, since that boundary
only ever needs an ordered id sequence, regardless of how those ids were
chosen. No unifying "strategy" interface or framework is introduced now,
consistent with the explicit instruction not to build it prematurely; the
four selectors remain siblings, not implementations of a shared abstraction.

---

## 21. Final Recommendation

Implement Phase 13 exactly as scoped above: a new `select_recent_memory_ids()`
/ `RecentSelectionResult` pair in `ai/memory_selection.py` (Batch 1), a new
`"summarise recent memories"` / `"summarize recent memories"` command wired
through `CommandRouter`/`JarvisOrchestrator` reusing Phase 10's ingestion
unchanged (Batch 2), and full end-to-end verification, README update, and a
completion report (Batch 3) — mirroring Phase 9–12's batch discipline
exactly. The two decisions with genuine architectural weight are §3 (recent
= newest-10, no invented time-window) and §6 (preserve newest-first order
through ingestion, rejecting the chronological-reversal candidate because it
would invert the budget's omission priority) — both are resolved with
repository-grounded reasoning, not convention alone.

---

## 22. Plan File and Git Status

- **Plan file created:** `docs/phase_13_implementation_plan.md` (this
  document only).
- **Git status at the end of this planning turn** (`git status --porcelain`,
  verified directly, not assumed):
  ```
  ?? docs/phase_13_implementation_plan.md
  ```
  - Modified/staged: none by this turn.
  - Untracked: only `docs/phase_13_implementation_plan.md` (new, this turn).
  - No files were staged or committed, per the explicit instruction.
