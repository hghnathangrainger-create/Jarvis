# Phase 11 Implementation Plan — Deterministic Query-Based Automatic Memory Selection

Status: **Planning only. No production code, tests, README changes, completion
report, staging, or commits accompany this document.**

**Clarification addendum (this revision):** three narrow planning points —
wildcard-semantics contract (§2.1, §3.4, §4.2, §9, §10, §15), the
`memory_query_selection` audit event's exact fields and privacy design
(§12.2), and the exact `handle_request` dispatch precedence (§3.2) — were
clarified and tightened before Batch 1 begins. No other section's
substance changed; only wording was strengthened where noted.

Phase number confirmed available by direct repository inspection: `docs/`
contains completion/implementation documentation through Phase 10 only
(`phase_10_completion_report.md`, `phase_10_implementation_plan.md`); no
`phase_11_*` file exists prior to this one.

Authoritative closure state this plan builds on, verified directly against
the repository rather than assumed: HEAD `43483341ebc3634589579432d66214c0c190e88f`
("Complete Phase 10 multi-memory retrieval and selection"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean apart from two
pre-existing, unrelated untracked files (`a.txt`, `report.txt`) that are not
part of any tracked phase work and are left untouched by this plan and by
every future Phase 11 commit. `poetry run pytest -q` — **1007 passed, 0
failed** — is the regression floor.

---

## 1. Purpose

Phase 9 proved a single explicitly-named stored memory can be safely
summarised by the advisory AI. Phase 10 proved a small, explicit, user-named
*set* of memories can be safely combined into one context and summarised
together. Both phases deliberately required the user to already know the
exact numeric id(s) of what they wanted summarised.

Phase 11 answers the question Phase 10 left open for the *first* time in a
way that requires a real design decision about automatic selection: **how
does Jarvis turn an explicit user query about stored memory into a
deterministic, bounded, explainable set of memory records for AI reasoning,
without pretending that keyword/database search is semantic intelligence or
giving the AI authority to choose its own context?**

The scope is deliberately narrow: reuse the repository's existing
`MemoryManager.search()` mechanism exactly as it already behaves, reuse
Phase 10's combination/ingestion architecture unchanged, and add nothing that
could be mistaken for semantic search, ranking, or AI-directed retrieval.

---

## 2. Repository Findings Relevant to Deterministic Search Selection

Established by direct inspection of `memory/episodic_memory.py`,
`memory/memory_manager.py`, `tools/builtin/memory_tool.py`, and
`storage/models.py` — not assumed from method names.

### 2.1 `MemoryManager.search()` / `EpisodicMemoryStore.search()` — exact semantics

- **Fields searched:** `EpisodicMemory.content` only. Neither `source`,
  `category`, `id`, `session_id`, nor `created_at` participate in the text
  match. `category` is usable only as a separate, exact-match *filter*
  (`EpisodicMemory.category == normalize_category(category)`), never as
  matched text.
- **Matching semantics:** a single SQL `ILIKE` substring match:
  `EpisodicMemory.content.ilike(f"%{term}%")`. This is case-insensitive
  substring containment, not tokenised, not ranked, not similarity-based, and
  not natural-language-aware in any sense.
- **Case sensitivity:** none — `ILIKE` is case-insensitive by definition;
  confirmed no additional case handling exists in `EpisodicMemoryStore` or
  `MemoryManager` beyond that.
- **Substring/token/SQL behaviour:** substring, not token-based. The whole,
  stripped query string becomes one `%…%` pattern; there is no splitting on
  words, no AND/OR combination of multiple terms, and no stemming.
- **Result ordering:** `ORDER BY EpisodicMemory.created_at DESC,
  EpisodicMemory.id DESC` — newest-first, with `id DESC` as an explicit
  tie-break for equal timestamps. This is a genuinely deterministic order:
  two identical calls against unchanged data always return records in the
  same sequence. **No architectural fix is required to claim determinism**
  — the store already guarantees it.
- **Default and maximum limits:** `MemoryManager.search()` /
  `EpisodicMemoryStore.search()` both default `limit=20` and apply **no
  upper clamp** at all — a caller supplying `limit=10_000` would receive up
  to 10,000 rows. The only clamping in the whole memory stack is in
  `tools/builtin/memory_tool.py` (`_DEFAULT_LIMIT = 10`, `_MAX_LIMIT = 50`,
  enforced by `MemoryTool._clamp_limit`), which applies **only** to requests
  routed through `MemoryTool` (the CLI-facing `search memories for <query>`
  command) — it does **not** apply to a direct `MemoryManager.search()` call,
  exactly the same layering Phase 9/10 already rely on for
  `MemoryManager.get()` bypassing `MemoryTool`.
- **Duplicates:** structurally impossible. The query is a single
  non-joining `filter()` over one table; each matching row is returned
  exactly once.
- **Deleted/inactive records:** cannot appear. `storage/models.py` defines
  no soft-delete or "active" column on `EpisodicMemory`; `EpisodicMemoryStore.delete()`
  performs a real `db.delete(entry)`. A deleted memory is physically absent
  from the table and cannot be returned by any future search.
- **Error behaviour:** neither `EpisodicMemoryStore.search()` nor
  `MemoryManager.search()` catches anything. A database-layer exception
  (connection failure, corrupted session, etc.) propagates to the caller
  unmodified — unlike `ingest_memories_for_ai()`'s own per-id
  `try/except Exception`, there is no existing per-call resilience at this
  layer today.
- **Whitespace-only queries:** explicitly handled — `term = query.strip();
  if not term: return []`. An empty or whitespace-only query returns an
  empty list, not an exception, and this is true both at the
  `EpisodicMemoryStore` and `MemoryManager` levels.
- **Wildcard characters:** `%` and `_` are **not escaped** before being
  embedded in the `ILIKE` pattern (`pattern = f"%{term}%"`). A query
  containing a literal `%` or `_` is interpreted by PostgreSQL/SQLite as a
  genuine `LIKE` wildcard (`%` matches any run of characters, `_` matches
  any single character), broadening the match beyond the literal substring
  a naive user would expect. This is a real, disclosed characteristic of
  the existing implementation, not something this plan patches (see §9,
  §6).

  **Confirmed decision (clarification): Phase 11 preserves these exact
  semantics unchanged.** `select_memory_ids_by_query()` calls
  `memory_manager.search()` directly with no wildcard-escaping step of its
  own. This matches the user's preferred first-phase contract precisely:
  `%`/`_` retain their current `LIKE` wildcard meaning; this is not a SQL
  injection risk because the query remains parameterised (§2.1 above); and
  Phase 11 does **not** create a second, divergent search dialect by
  escaping wildcard characters only inside `ai/memory_selection.py` while
  `MemoryTool`'s own `search memories for <query>` command continues to
  interpret them as wildcards unescaped — a single query string must mean
  the same thing regardless of which command surface it was typed through.
  Escaping literal `%`/`_`, if ever done, belongs in
  `EpisodicMemoryStore.search()` itself, as a separately reviewed
  compatibility change affecting every caller uniformly, not as a
  Phase-11-local workaround. See §16 for this deferred item.
- **SQL escaping/parameterisation:** confirmed safe from SQL injection.
  `EpisodicMemory.content.ilike(pattern)` is a SQLAlchemy ORM filter — the
  pattern is bound as a parameter by SQLAlchemy/the DB driver, never
  string-interpolated into raw SQL text. The wildcard-character behaviour
  above is a semantic broadening risk within the existing query contract,
  not an injection vulnerability.
- **Return shape:** full, detached `MemoryRecord` objects (`id`, `content`,
  `source`, `session_id`, `created_at`, `category`) — not bare identifiers
  requiring a further lookup. Phase 11 nonetheless re-retrieves by id
  through the existing, unmodified `ingest_memories_for_ai()` (see §5, §11)
  rather than reusing the search call's own returned content directly, for
  reasons given there.

### 2.2 What this is not

Nothing above implements, resembles, or should ever be described as:
semantic search, embeddings, a vector database, similarity ranking,
relevance scoring, or natural-language understanding. It is a plain,
case-insensitive substring match over one text column, deterministically
ordered by recency. The Master Specification's own aspirational Chapter 8
material (semantic memory via ChromaDB, relevance scoring by "semantic
similarity + recency + access frequency") describes a different, unbuilt,
explicitly-deferred future capability — confirmed by direct inspection of
`docs/JARVIS_PROJECT_MASTER_SPECIFICATION_V2_1.md` — and Phase 11 does not
implement any part of it.

---

## 3. Proposed Command Surface

**Chosen wording:** `summarise memories about <query>` /
`summarize memories about <query>` — the user's own example, verified
compatible with the existing router only after a specific, necessary
ordering fix (§7).

### 3.1 Concrete routing collision found by inspection

`core/command_router.py`'s Phase 10 plural matcher,
`match_memory_set_summary`, checks `lowered.startswith(prefix)` for
`prefix in ("summarise memories", "summarize memories")`. Verified directly:

```
"summarise memories about home renovation".casefold()
  .startswith("summarise memories")  -> True
  trailing text after that prefix    -> "about home renovation"
```

Today, unmodified, this text would be swallowed by the *existing* Phase 10
matcher, handed to `_parse_memory_ids("about home renovation")`, and
rejected with *"'about home renovation' is not a valid list of memory ids"*
— a confusing, wrong error for a request that was never meant to be an
explicit-id list. This is a genuine pre-existing collision this phase must
resolve deliberately, not a hypothetical one.

### 3.2 Resolution

Add a new, more specific prefix pair,
`_MEMORY_QUERY_SUMMARY_PREFIXES = ("summarise memories about", "summarize memories about")`,
and a new `CommandRouter.match_memory_query_summary()` method mirroring
`match_memory_summary`/`match_memory_set_summary` exactly (extract raw
trailing text only; no parsing, validation, or tool registration here).
Because `"summarise memories about"` is a strict superset-string of
`"summarise memories"`, `JarvisOrchestrator.handle_request()` must check the
new, more specific matcher **before** `match_memory_set_summary` — the same
longest-prefix-first principle `CommandRouter._file_prefix` already applies
*inside* a single prefix tuple, now applied *across* the three (soon four)
mutually-prefix-colliding command families at the outer dispatch level. If
the query matcher does not match, dispatch falls through to
`match_memory_summary` then `match_memory_set_summary` exactly as before —
zero behaviour change for any existing command.

#### 3.2.1 Exact `handle_request` dispatch precedence (clarification)

The only *strict* ordering requirement is that
`match_memory_query_summary` is checked before `match_memory_set_summary`
(§3.1: `"summarise memories about"` is a superset-string of `"summarise
memories"`). `match_memory_query_summary` does **not** collide with
`match_memory_summary` (singular) in either direction — `"summarise
memory"` and `"summarise memories"` diverge at the word's 6th character
(`y` vs `i`), confirmed in §3.3 — so their relative order does not affect
correctness. For readability, the new check is placed immediately before
the existing plural check it must precede. The full, exact sequence in
`JarvisOrchestrator.handle_request()` becomes:

```
1. match_file_summary(text)          -> file summary workflow (Phase 8)
2. match_memory_summary(text)        -> singular memory workflow (Phase 9)
3. match_memory_query_summary(text)  -> NEW query-based workflow (Phase 11)
4. match_memory_set_summary(text)    -> explicit-id plural workflow (Phase 10)
5. otherwise: _handle_request_core() -> CommandRouter.match() (ordinary
   rule-based dispatch: file_list/file_read/file_create/file_append,
   approval_history, generic "memory" tool incl. "search memories for
   <query>", memory_update, memory_forget, echo, info, etc.)
```

Each step returns `None` and falls through to the next when its own
prefix does not match; the first non-`None` match wins and is handled
terminally. Traced against the three required examples:

- `"summarise memories about Jarvis security"` — step 2: does not start
  with `"summarise memory"` + word-boundary `y` (it has `"memories"`, `i`
  at that position) → no match. Step 3: starts with `"summarise memories
  about"` → **match** → Phase 11 query workflow. (Step 4 is never
  reached.)
- `"summarise memories 27, 12, 18"` — step 2: no match (same reason as
  above). Step 3: starts with `"summarise memories"` but the next
  characters are `" 27, 12, 18"`, not `" about"` → no match. Step 4:
  starts with `"summarise memories"` → **match** → Phase 10 explicit-id
  workflow, unchanged.
- `"summarise memory 27"` — step 2: starts with `"summarise memory"` →
  **match** → Phase 9 singular workflow, unchanged. (Steps 3 and 4 are
  never reached.)

No change to the ordering or behaviour of `_handle_request_core()` or
`CommandRouter.match()` (step 5) is proposed; they are reached, exactly as
today, only when none of the four summary-family matchers apply.

### 3.3 Other collision checks performed

- `summarise memory <id>` (singular): prefix `"summarise memory"` vs new
  `"summarise memories about"` — diverge at the 8th character (`" "` vs
  `"s"`), confirmed non-colliding in either direction, same style of check
  already documented for the singular/plural pair.
- `show memory <id>`, `forget memory <id>`: routed via `CommandRouter.match()`
  (`_MEMORY_KEYWORDS`, `startswith("forget memory")`), never reached by
  `handle_request()` until *after* all three (now four) summary-family
  matchers have returned `None` — no collision, confirmed by reading
  `handle_request`'s dispatch order directly.
- Generic `search memories for <query>` (existing `MemoryTool`-routed, GREEN,
  read-only, non-AI command): begins with `"search"`, not `"summarise"` —
  no collision, and this command's behaviour (a plain formatted list, no AI
  call) is completely unaffected and unchanged by Phase 11.
- Unrelated free text containing "memory" (e.g. "I have a good memory"):
  unaffected — it matches none of the summary-family prefixes and falls
  through to the existing generic `_MEMORY_KEYWORDS` handling in `match()`,
  exactly as today.

### 3.4 Wording constraint

The response label and body text must never claim "most relevant" or
"best" memories. Chosen label: `[AI query-based memory summary - advisory
only]`, distinct from the existing three labels
(`_FILE_SUMMARY_LABEL`, `_MEMORY_SUMMARY_LABEL`, `_MEMORY_SET_SUMMARY_LABEL`),
mirroring their exact naming convention. Body wording reuses
`MemoryTool`'s own existing phrase shape ("Memories matching '<query>'")
for consistency rather than inventing new, potentially over-claiming
language.

**Clarification:** because §2.1 confirms `%`/`_` retain live `LIKE`
wildcard meaning (unescaped, unchanged), all user-visible and documentation
wording for this capability must describe it precisely as **deterministic,
case-insensitive content-pattern/substring search with inherited wildcard
semantics** — never as "guaranteed literal-substring matching." A query
containing `%` or `_` is honestly a pattern, not a guaranteed-literal
phrase, and no wording introduced by this phase may imply otherwise.

---

## 4. Architectural Decisions and Rejected Alternatives

### 4.1 Where selection logic lives

**Decision:** a new, narrow module, `ai/memory_selection.py`, mirroring
`ai/memory_ingestion.py`'s own precedent of one small, single-purpose
module per new capability. It owns exactly one function,
`select_memory_ids_by_query()`, and one result type, `QuerySelectionResult`.

**Rejected alternative 1 — extend `ai/memory_ingestion.py` itself.**
Rejected: that module's docstring and `Does NOT` contract are specifically
scoped to *acquiring and combining already-identified records*. Adding
query execution would silently widen its responsibility and its "Does NOT"
list would need contradicting rather than extending — the same kind of
scope creep Phase 9/10 repeatedly rejected for themselves.

**Rejected alternative 2 — put the search call directly in
`core/orchestrator.py`.** Rejected: Phase 9/10 precedent is clear that
`JarvisOrchestrator` parses and validates (`_parse_memory_id`,
`_parse_memory_ids`) but never itself calls `MemoryManager.get()`/`search()`
to *acquire* content — acquisition is always delegated to a narrow `ai/`
module so provenance and failure representation stay in one, disclosed
place. Calling `search()` directly from the orchestrator would break that
established ownership split without a compelling reason to.

**Rejected alternative 3 — a generic, pluggable "selection strategy"
abstraction covering explicit-id, query, and future recency/category
strategies uniformly.** Rejected for this phase (see §17): only two
concrete strategies would exist (explicit-id, query-based); building a
shared abstraction for a hypothetical third is premature generalisation the
project's own conventions explicitly warn against.

### 4.2 What `select_memory_ids_by_query()` does and does not do

Does:
- Accept `(memory_manager, query, *, limit)`.
- Call `memory_manager.search(query, limit=limit)` — the sole call site.
- Return the ids of the results **in the exact order `search()` returned
  them** — no re-sorting, no deduplication (search results cannot contain
  duplicates, §2.1).
- Represent zero matches, a non-empty result, and a search-layer exception
  as three distinct, named outcomes (§8), never collapsed into one generic
  failure.

Does not:
- Retrieve memory content itself, construct an `AIContextBlock`, or touch
  trust/provenance in any way — that remains exclusively
  `ingest_memories_for_ai()`'s job, called afterward, unmodified, by the
  orchestrator, exactly as the explicit-id path already does.
- Reuse the `MemoryRecord.content` returned by `search()` as the AI-facing
  text. Selected ids are re-retrieved via the existing
  `ingest_memories_for_ai()` → `MemoryManager.get()` path instead (§11), so
  Phase 10's entire truncation/budget/provenance contract applies unchanged
  and there is exactly one code path that ever produces AI-facing memory
  content.
- Apply the `_MAX_MEMORY_SET_SIZE` cardinality message itself — that
  remains the orchestrator's job, reusing the same check Phase 10 already
  performs, applied here to the *count of selected ids* rather than a
  user-typed list length.
- Scan, filter, or validate query text for injection patterns. The query is
  never itself stored-memory content; it is retrieval criteria and live
  user input (§6).
- Escape, normalise, or otherwise alter the meaning of `%`/`_` wildcard
  characters before calling `memory_manager.search()`. Doing so only
  inside this module would create a second, Phase-11-only search dialect
  diverging from `MemoryTool`'s own unescaped `search memories for
  <query>` behaviour — rejected explicitly (§2.1 clarification).

---

## 5. Selection / Order / Limit Contract

### 5.1 Candidates evaluated for the search-call limit vs. selection ceiling

**Candidate A — call `search()` with exactly the existing Phase 10
selection ceiling (`limit=10`).**
Strengths: one call, one deterministic result set, search results *are*
the selection with no separate reduction step; simplest to explain
("Jarvis asked for at most 10 matching memories; here is what matched");
trivially avoids ever exceeding `ingest_memories_for_ai()`'s own
`max_records=10` defensive backstop, since the two numbers are the same by
construction.
Weaknesses: no way to honestly disclose "N further memories also matched
but were not shown" without a second query.
Explainability: highest — "up to 10 matches" is a single, exact,
falsifiable claim.
Failure modes: none beyond those already handled at the ingestion layer.
Compatibility: trivially compatible — reuses the existing ceiling constant.

**Candidate B — retrieve a larger deterministic candidate pool (e.g.
`limit=50`, matching `MemoryTool._MAX_LIMIT`) and apply a repository-owned
reduction policy down to 10.**
Strengths: could support a future, honest "50 total matched, showing the
newest 10" disclosure.
Weaknesses: because `search()`'s own ordering is already deterministic
newest-first, "reduce a 50-item newest-first list to the first 10" produces
an *identical* selected set to simply calling `search(limit=10)` directly —
the larger pool adds a second concept (candidate pool size vs. selection
size), a second thing to test, and a second thing to explain, for a
disclosure nuance ("N more exist beyond what's shown") that is not part of
this phase's required scope.
Explainability: lower — two numbers (pool size, selection size) instead of
one.
Failure modes: none new, but more surface area for the same outcomes.
Compatibility: compatible, but introduces unused complexity.

**Candidate C — expose a user-controlled result limit within a bounded
maximum (e.g. an optional trailing count in the command grammar).**
Strengths: user transparency/control.
Weaknesses: expands command grammar and parsing surface for a first
capability whose stated purpose is proving the minimal deterministic path
end-to-end; introduces new validation edge cases (non-numeric counts,
counts above the bound) with no demonstrated user need yet.
Explainability: potentially confusing without real demand to justify it.
Failure modes: a new class of malformed-input handling to get right.
Compatibility: compatible, but scope-expanding.

**Chosen: Candidate A.** `select_memory_ids_by_query()` is called with
`limit=_MAX_MEMORY_SET_SIZE` (10) — the exact same constant
`core/orchestrator.py` already defines and uses for the explicit-id
cardinality ceiling — so the search-result limit and the selected-record
limit are **intentionally, explicitly set equal**, while remaining two
independently-configurable parameters in the code (one passed to
`MemoryManager.search()`, the other `ingest_memories_for_ai()`'s own
`max_records`), never conflated as the same concept in the implementation
even though their values coincide by deliberate design in this first cut.

### 5.2 Ordering contract

Phase 11 preserves `EpisodicMemoryStore.search()`'s existing
`created_at DESC, id DESC` order **exactly**, with no re-sorting anywhere
in `select_memory_ids_by_query()` or the orchestrator. Because Phase 10's
combined-context budget check consumes ids in supplied order, this means:
**newer matching memories are more likely to be fully included; older
matching memories among the results are more likely to be wholly omitted
for size** when the matched set is large. This is an honest, disclosed
consequence of reusing the store's own deterministic order rather than
inventing a new one for this phase, and it is explicitly *not* a
relevance judgement — it is a recency bias, named as such.

### 5.3 Distinct limits, kept distinct

Four separate limits exist in the resulting design and must never be
conflated in code or documentation:
1. `MemoryManager.search()`'s call-site `limit` (this phase: 10).
2. `ingest_memories_for_ai()`'s `max_records` defensive backstop (existing:
   10 — never exceeded here by construction, §5.1).
3. `ingest_memory_for_ai`/`ingest_memories_for_ai`'s per-record
   `max_chars_per_record` truncation (existing, Phase 9: 4000, unchanged).
4. `ingest_memories_for_ai`'s `max_total_chars` combined-context ceiling
   (existing, Phase 10: 20,000, unchanged).

---

## 6. Query Trust and Injection Treatment

### 6.1 Does the query text reach `AIReasoningRequest`/`PromptBuilder`?

**Yes — unavoidably, and via the same mechanism every existing summary
command already uses.** `AIReasoningRequest.user_input` has always carried
the *entire original request text* for every Phase 8/9/10 summary command
(e.g. the literal digits in `"summarise memory 42"` already reach the AI
today via `user_input=user_request`). Phase 11's query is not a new
exception to this — it is the same, pre-existing pattern applied to a
command whose trailing text happens to be a search query instead of an id
list.

**Why this is necessary:** `PromptBuilder.build()`'s `user_message`
parameter is how the AI is told what the user actually asked; every
existing summary workflow already forwards the full request text this way,
and there is no separate "hide the command's own argument from the AI"
mechanism anywhere in the codebase to selectively withhold it.

**Trust classification:** the query is part of the user's own,
current-turn, live-typed request text — the same status every other word
in `user_request` already has. It is **not** wrapped in an `AIContextBlock`
at all (`PromptBuilder.build()`'s `user_message` argument is structurally
distinct from its `context` argument), so it never becomes, and never
needs to become, `ContentTrust.JARVIS_TRUSTED` via
`AIContextBlock.from_live_user_input()` — that factory remains unused by
this orchestrator path, exactly as it already is for Phase 9/10.

**Effect on injection handling:** none, and none is introduced. Injection
scanning (`PromptBuilder`'s automatic scan) has only ever applied to
`AIContextBlock` instances with `trust=UNTRUSTED` — never to
`user_message`. This was already true before Phase 11 (a user could always
type "ignore previous instructions" as live command text) and remains
unchanged. The genuine, unchanged risk surface is the **stored memory
content** the query happens to select, not the query text itself (§8).

### 6.2 What stays untrusted

- Retrieved memory content (via `ingest_memories_for_ai()`): unchanged,
  `ContentTrust.UNTRUSTED`, exactly as Phase 9/10 already establish.
- Jarvis-owned search/selection accounting (match count, ids, loss
  disclosure): built entirely from structured data, appended to the
  AI-generated summary text **after** it is produced, never mixed into or
  fed back into the `AIContextBlock` the AI reasoned about — the same
  separation `_build_memory_set_disclosure` already enforces for Phase 10,
  reused unchanged.
- AI-generated summary: unchanged in status — the orchestrator's own
  message, never re-ingested as memory or re-classified as trusted.

---

## 7. Security / Router Debt Review

### 7.1 Security review

Reviewed together, as required: `SecurityManager._RULES`, `MemoryTool`,
`MemoryManager.search()`, the Phase 9 single-memory path, and the Phase 10
explicit-id path.

`MemoryManager.search()` is exactly as unconditionally read-only as
`MemoryManager.get()` already is. Neither goes through `ToolExecutor` or
`SecurityManager.classify_action()` when called directly from an `ai/`
ingestion/selection module — this is the same disclosed, accepted
exception Phase 9 established and Phase 10 already reused, now extended to
a third direct `MemoryManager` call site.

**Determination: no new `ActionType`, no new `SecurityManager` rule, and no
compatibility-preserving refactor is required before implementation.**
Reasoning: (1) the operation is unconditionally GREEN/read-only regardless
of query content — a query cannot cause a write, update, or delete; (2) no
dynamic security decision is being skipped that was ever being made for
`MemoryManager.get()` either; (3) a refactor routing search-based selection
through `ToolExecutor` would be a disproportionate, scope-expanding change
introduced by this phase rather than required by any new risk it
introduces.

The inherited `SecurityManager._RULES`/`MemoryTool`-versus-AI-memory-
ingestion semantic-drift debt (documented since Phase 9, carried through
Phase 10) is **reviewed as mandated and confirmed to remain acceptable,
non-blocking debt**, now with a third example (`search`) alongside `get`.
It is not resolved here; resolving it would mean deciding whether
`SecurityManager._RULES`'s "search" GREEN keyword rule and this direct,
rule-bypassing call path should ever be unified — a larger, separately-
scoped security-architecture question outside Phase 11's narrow purpose.

Explicitly distinguished, per the mandatory framing: **searching** stored
memory and **reading** selected memory (both in scope, both unconditionally
GREEN/read-only) versus **mutating** memory and **deleting** memory (both
out of scope, untouched, still gated by the existing `memory_update`/
`memory_forget` YELLOW tools).

### 7.2 CommandRouter review

Reviewed collisions among all six named cases (§3.3) plus the concrete
plural-prefix collision found in §3.1. **Determination: exact, longest-
prefix-first early dispatch in `handle_request()` — checking the new,
more specific `match_memory_query_summary` before the existing
`match_memory_set_summary` — is sufficient.** No broader natural-language
router redesign is required or performed. This preserves the already-
documented, accepted debt (`CommandRouter.match()`'s broad `_MEMORY_KEYWORDS`
overlap) completely unchanged, since the new command is resolved entirely
within the summary-family dispatch block in `handle_request()`, before
`match()` is ever reached.

---

## 8. No-Result and Failure Semantics

Distinguished explicitly, as required, into four separate categories —
none collapsed into another:

1. **Invalid query** (empty after stripping, or the command phrase used
   with no trailing text at all): rejected before `search()` is ever
   called. No memory read, no audit event, no AI consulted. A query
   consisting only of punctuation/separators (e.g. `"---"`) is
   **deliberately not treated as invalid** — after stripping it is
   non-empty text and is passed to `search()` like any other query,
   because rejecting it would require an unjustified heuristic about what
   counts as "meaningful" query content; it simply becomes a search for
   that literal substring (see §9's wildcard note for `%`/`_` specifically).
2. **Zero search matches**: `search()` returns `[]`. Distinct, honest
   message (e.g. *"No stored memories matched 'X'."*) — no memory
   ingestion attempted, no AI consulted.
3. **Search infrastructure failure**: `search()` raises. Caught once at
   the `select_memory_ids_by_query()` boundary (mirroring, at the single-
   call granularity, the same per-call resilience `ingest_memories_for_ai()`
   already applies per id) and represented as a distinct, honest failure —
   *"Could not search stored memories right now."* — never as "zero
   matches." No AI consulted.
4. **Selected memories becoming unusable after search** (a matched id is
   deleted, becomes unreadable, or is wholly omitted for the combined-size
   budget by the time `ingest_memories_for_ai()` actually retrieves it):
   represented entirely through Phase 10's **existing, unmodified**
   accounting — `not_found`, `retrieval_errors`, `omitted_for_size`,
   `truncated_records` — with **no new state introduced** (§11, §12). If
   every selected id ends up unusable, Phase 10's existing total-failure
   path (`ingestion.success is False`) applies unchanged, and the AI is
   never consulted — the same "no usable context, no provider call" rule
   Phase 10 already enforces.

Category 2 (zero matches) and category 4-total-loss (all matched ids later
unusable) are kept distinct in wording even though both end in "no AI
call": zero matches means *nothing in storage contains the query text*;
total loss after selection means *matches existed but none could actually
be included* — different facts, different honest messages.

---

## 9. Injection and Adversarial Query Review

Reviewed directly against the actual implementation, not assumed:

- **Command routing:** a query cannot alter routing — routing is decided
  on the literal request text by `CommandRouter` before `search()` is ever
  invoked; nothing in the query influences which prefix matched.
- **Result count:** cannot be altered by query content — the `limit`
  passed to `search()` is a fixed constant (§5.1), never derived from or
  influenced by the query string.
- **SQL/query injection:** not possible — confirmed parameterised `ILIKE`
  filter (§2.1).
- **Wildcard exploitation (`%`, `_`):** confirmed real and unescaped
  (§2.1). A query containing `%` or `_` broadens matching beyond the
  literal substring a user likely intended (e.g. a bare `%` matches every
  non-empty memory). This is **documented here as a disclosed, accepted
  characteristic of the existing search implementation and is not patched
  by this plan or this phase**, per the explicit instruction not to alter
  search semantics during planning. Confirmed (clarification): Phase 11
  calls the existing `search()` semantics directly and unmodified — no
  escaping is added anywhere, including locally inside
  `ai/memory_selection.py`, precisely to avoid creating a second search
  dialect (§4.2). It is carried forward as non-blocking debt (§16) with a
  narrow, specific future fix identified (escape literal `%`/`_` inside
  `EpisodicMemoryStore.search()` itself, affecting every caller uniformly)
  should it ever be judged worth doing as a separately reviewed
  compatibility change.
- **Becoming part of AI context:** the query itself never does (§6) — it
  reaches the AI only as ordinary live `user_input`, never as
  `AIContextBlock` content, and is never scanned or needs to be.
- **Affecting `PromptBuilder` scanning:** no effect — scanning applies only
  to the combined, `UNTRUSTED` memory context Phase 10 already produces,
  unchanged by how that context's constituent ids were selected.
  Retrieved memory content selected via a query is exactly as subject to
  the existing scan as retrieved memory content selected via explicit ids
  — proven by construction, since both paths converge on the same,
  unmodified `ingest_memories_for_ai()` → `PromptBuilder.build()` sequence.
- **Imitating search syntax / misleading Jarvis-owned disclosure:** the
  query cannot influence `_build_memory_set_disclosure`'s wording (unchanged,
  built entirely from structured ids/counts) or any new query-selection
  disclosure this phase adds (§10) — both are built from typed accounting
  fields, never from re-parsed query or memory text.

**Conclusion, stated plainly per the required framing:** a malicious or
prompt-like search query can, at most, influence *which already-untrusted,
already-scanned* stored records get pulled into context (by matching more
or fewer records than a naive reading of the query would suggest, via the
wildcard behaviour above) — it cannot make any selected record trusted,
cannot bypass the injection scan, cannot alter routing, and cannot create
or expand execution authority. The real, unchanged risk surface remains
exactly where Phase 8/9/10 already established it: content that was
previously stored as a memory, not the cleverness of a later query that
happens to retrieve it.

---

## 10. Search Explainability and Disclosure

User-visible accounting, reusing Phase 10's existing itemisation verbatim
plus one new, narrow pre-ingestion disclosure:

- Query used: echoed in the response header, mirroring `MemoryTool`'s own
  existing `"Memories matching '<query>'"` phrasing for consistency, never
  "most relevant," "best," or "smart search." Per §3.4's clarification,
  this wording describes a content-pattern/substring match with inherited
  wildcard semantics, never a guarantee of literal-substring matching.
- Number of deterministic matches selected: a plain count (e.g. *"3
  memories matched"*), never a relevance claim.
- `included`, `not_found`, `retrieval_errors`, `omitted_for_size`,
  `truncated_records`: **reused exactly as Phase 10 already discloses
  them** via `_build_memory_set_disclosure`, unmodified. On clean success
  (nothing lost), matched-count is stated but `included` ids are **not**
  listed by default — this mirrors Phase 10's own existing behaviour,
  which never lists `included` ids on a clean success either, only in a
  "Note:" when something was lost.
- Memory ids in the success case: **not** disclosed by default, for
  consistency with the existing Phase 10 precedent above; ids remain
  available in the itemised loss-disclosure exactly as Phase 10 already
  provides.
- No search-level candidate-reduction disclosure is introduced, since
  Candidate A (§5.1) was chosen specifically because it has nothing to
  disclose beyond "up to 10 matches."

---

## 11. Search-to-Ingestion Race Analysis (TOCTOU)

Explicitly reviewed, as required. The sequence is:

```
MemoryManager.search(query, limit=10)
  -> ordered list of MemoryRecord (search's own snapshot)
  -> select_memory_ids_by_query() extracts ids, same order
  -> ingest_memories_for_ai(memory_manager, ids)
  -> MemoryManager.get(id) per id, again, independently
```

A selected id can, in principle, disappear or change content between the
`search()` call and the later `get()` call inside `ingest_memories_for_ai()`
— e.g. deleted via `forget memory <id>` in the intervening moment, or
its content updated via `memory_update`.

**This is a genuine, disclosed TOCTOU-style retrieval race, structurally
identical to one Phase 9/10 already accept for the explicit-id path**
(nothing prevents a user-named id from being forgotten between typing the
command and Jarvis retrieving it either). Phase 11 introduces no new kind
of race — only a new way to arrive at the same, already-accepted one.

**Representation:** no new accounting state is introduced.
- If the record was deleted in the gap: `MemoryManager.get()` returns
  `None`, and `ingest_memories_for_ai()` already places that id in
  `not_found` — reused unchanged.
- If retrieval itself raises for some other reason in the gap:
  `retrieval_errors` — reused unchanged.
- If the record's content changed in the gap: whatever the *current*
  content is at `get()` time is what gets ingested and truncated/budgeted
  — the same "read what's there now" semantics `MemoryManager.get()`
  already has for the explicit-id path, unchanged.

**No transactions or locking are introduced.** Repository inspection
confirms this remains a single-user, local, SQLite-backed architecture
with no concurrent-writer scenario to defend against beyond what Phase
9/10 already knowingly accept; introducing locking here would be a
disproportionate response to a race this phase does not make any more
likely or more severe than it already was.

---

## 12. Audit Design

### 12.1 Reused, unchanged

- Per-id acquisition outcomes during `ingest_memories_for_ai()`: reuse
  `_emit_memory_acquisition_event`/`_audit_memory_set_acquisition`
  precisely as Phase 10 already implements them — no changes.
- AI call outcomes: `AIRouter._emit_audit_event`, unchanged.
- Suspicious injection reporting: `PromptBuilder`'s existing
  `report_injection` path, unchanged.
- Unexpected-action handling: `_evaluate_unexpected_actions`/
  `_audit_unexpected_action`, unchanged, reused exactly as Phase 8/9/10
  already call it.

### 12.2 New: one search-level audit event (clarified)

**Determination:** a new, narrow audit event **is** necessary. Per-id
`memory_acquisition` events describe retrieval outcomes *during
ingestion*; none of them describe the fact that a search was performed at
all, what its outcome was, or how many ids it selected — a reviewer
looking only at per-id acquisition events would have no way to tell "a
query produced these ids" from "the user typed these ids explicitly."

#### 12.2.1 Candidates evaluated for the event's content

Reviewed against the actual `EventLogger`/`Event` implementation
(`observability/logger.py`) and the two existing precedents in this
codebase for logging something arguably sensitive:
`JarvisOrchestrator._emit_memory_acquisition_event` (never embeds raw
memory content, only ids/booleans/short reason codes) and
`ai/prompt_builder.py`'s `audit_suspicious_injection` reporter, which logs
`detail=f"matched_patterns={...} text_length={len(result.text)}"` —
**length, never the scanned text itself** — for exactly the same class of
situation: an event describing something about a piece of arguably
sensitive free text without persisting that text.

**Candidate A — store the complete raw query.** Rejected. A free-text
search query is user-supplied content that could itself contain anything
the user typed — the same category of content the codebase already
refuses to write into `detail` elsewhere (memory content, scanned prompt
text). `Event.detail`/`AuditLogEntry.detail` is an unbounded, append-only,
permanent `Text` column (`storage/models.py`) with no redaction or
deletion path (§Stage-level invariant carried from Phase 6:
`approval_history` and `audit_log` are both durable and, for `audit_log`,
never updated or deleted in normal operation) — writing raw query text
there would make the audit log a second, undefended copy of whatever the
user searched for, indefinitely.

**Candidate B — do not store the raw query; audit only a non-content
property (length) plus outcome/count/selected ids.** This is the
**chosen** design, because it is not an invented scheme but a direct
application of an existing, already-shipped repository convention
(`audit_suspicious_injection`'s `text_length=` field) to a new event, plus
the existing `_emit_memory_acquisition_event` convention of auditing
non-content integers (ids) and short outcome/reason codes.

**Candidate C — store a bounded/redacted representation (e.g. a
truncated snippet) consistent with an existing repository convention, if
one exists.** Evaluated directly: repository inspection found **no**
existing convention anywhere in this codebase for storing a
truncated/bounded snippet of user-supplied text in an audit event — every
existing precedent for "something sensitive happened" logs a *property*
of the text (its length) or a *categorical* fact about it (which named
patterns matched), never a fragment of the text itself. Candidate C, as
actually practised in this repository, therefore collapses into Candidate
B — there is no separate, real "bounded snippet" convention to choose
instead.

**Hashing, explicitly rejected as a privacy mechanism:** the project has
no keyed-hash, HMAC, or salting infrastructure anywhere (confirmed: no
`hashlib`/`hmac` import exists in the codebase). An unsalted hash of a
short, often-predictable search query would not provide real privacy — a
reviewer or attacker with a small dictionary of likely queries could
recover the original by brute-forcing the hash, and a fixed, unsalted
digest of the same query also becomes a stable, correlatable identifier
across requests, which is arguably worse than logging nothing. Hashing is
therefore not invented here; length-only (Candidate B) is chosen instead.

#### 12.2.2 Chosen design, exact fields

- **Event name (`action_type`):** `"memory_query_selection"`.
- **Source:** `"jarvis_orchestrator"` (same `_SOURCE` constant already used
  for every other orchestrator-owned event).
- **Fields (detail string):** `outcome=<success|zero_matches|failure>
  query_length=<int> match_count=<int> selected_ids=<comma-joined ints, or
  empty>`. **The raw query text is never embedded** — only its length
  (`query_length`), directly matching `audit_suspicious_injection`'s
  `text_length=` precedent, plus the non-content, non-sensitive outcome,
  match count, and (on success) the selected integer ids — the same
  sensitivity class as the existing `memory_id` field already logged by
  `_emit_memory_acquisition_event`.
- **Outcome semantics:** `SUCCESS` when at least one id was selected
  (`match_count > 0`). `zero_matches` and a genuine search exception both
  use the existing `EventOutcome.FAILURE` value, distinguished only via
  the `outcome=` field inside `detail` — deliberately mirroring, not
  inventing a variant of, the **existing** convention that a "nothing
  found" case is already audited as `FAILURE` in this exact system: a
  `not_found` id in `_audit_memory_set_acquisition` is audited as
  `EventOutcome.FAILURE` with `reason="not_found"` even though nothing
  actually errored — "the operation validly found nothing" and "the
  operation genuinely failed" already share one `EventOutcome` value in
  this codebase's own audit vocabulary, distinguished by an in-`detail`
  reason/outcome code rather than a new enum member, exactly as
  `zero_matches` vs. a real search exception are distinguished here.
- **Authoritative status:** non-authoritative, observability-only —
  identical status to every other event this codebase emits. Its failure
  can never change whether the search itself succeeded, how many matches
  were found, or what the orchestrator does next.
- **Logger-failure isolation:** wrapped in the same narrow
  `try/except Exception: pass`, scoped only around the `emit()` call
  itself, reusing the existing `_emit_memory_acquisition_event`-style
  isolation pattern rather than inventing a new one — consistent with the
  standing invariant that observability failure must never alter an
  otherwise-authoritative workflow outcome.

No double-auditing is introduced: this one event describes the search
step exactly once per request; it does not repeat information the
per-id `memory_acquisition` events already carry (those still fire once
per id during ingestion, as before), and it does not duplicate the
existing `ai_call` or injection-detection events.

---

## 13. Proposed Batch Boundaries

Mirroring Phase 8/9/10's established three-batch shape:

- **Batch 1 — Query-based selection foundation.** New
  `ai/memory_selection.py`: `select_memory_ids_by_query()` and
  `QuerySelectionResult`. No command or orchestrator wiring yet. Unit
  tests only for this module in isolation.
- **Batch 2 — Command and orchestrator wiring.** `core/command_router.py`:
  new prefixes and `match_memory_query_summary()`. `core/orchestrator.py`:
  dispatch-order fix (§3.2), new `_handle_memory_query_summary_request()`,
  the new `memory_query_selection` audit event (§12.2), reuse of
  `ingest_memories_for_ai()` unchanged.
- **Batch 3 — End-to-end verification and documentation.** Consolidated
  integration test proving the full path against real, multiple saved
  memories including a genuine query-selected multi-record injection
  attempt; README update; `docs/phase_11_completion_report.md`. **Not
  performed in this planning turn** — explicitly deferred to a future,
  separately-approved turn, per this turn's constraints.

---

## 14. Exact Files Expected to Change

- **New:** `ai/memory_selection.py` (Batch 1).
- **Modified:** `core/command_router.py` (Batch 2 — new prefixes, new
  match method; zero change to any existing method's behaviour).
- **Modified:** `core/orchestrator.py` (Batch 2 — new dispatch branch
  checked before `match_memory_set_summary`, new handler method, new audit
  event; zero change to any existing handler's behaviour).
- **New (Batch 3, not this turn):** `tests/unit/test_memory_selection.py`,
  extensions to `tests/unit/test_command_router.py`, a new
  `tests/unit/test_memory_query_summary_workflow.py`, a new
  `tests/integration/test_memory_query_summary_end_to_end.py`.
- **New/modified (Batch 3, not this turn):**
  `docs/phase_11_completion_report.md`, `README.md`.
- **This turn only:** `docs/phase_11_implementation_plan.md` (this
  document).

No change is proposed to `ai/prompt_builder.py`, `ai/router.py`,
`ai/reasoning_engine.py`, `ai/reasoning_models.py`, `ai/context_models.py`,
`ai/memory_ingestion.py`, `memory/memory_manager.py`,
`memory/episodic_memory.py`, `memory/memory_models.py`,
`tools/builtin/memory_tool.py`, `security/security_manager.py`, or
`storage/models.py`. Any future finding that one of these requires change
would need its own explicit justification and rejected-alternatives
analysis, per the standing rule for touching hardened Phase 7–10 core
APIs.

---

## 15. Test Strategy and Regression Floor

**Regression floor: 1007 passed, 0 failed — may only grow.** Planned
coverage (Batch 3, not written this turn) spans, at minimum, every item the
scoping brief enumerated: exact query-command matching and spelling
variants; plural/singular/generic command compatibility (unchanged);
exact query-text extraction and whitespace handling (decided: preserved as
typed after stripping only leading/trailing whitespace, not internally
normalised, mirroring how `_parse_memory_ids`/`_parse_memory_id` already
treat their own trailing text); empty/whitespace-only/punctuation-only
query behaviour; real `MemoryManager.search()` semantics including
case-insensitivity; **and, per clarification, explicit, dedicated test
cases for: (a) `%` wildcard behaviour (a query containing a literal `%`
matches more broadly than its literal substring, proving the inherited,
unescaped semantic is preserved); (b) `_` wildcard behaviour (a query
containing a literal `_` matches any single character in that position);
(c) ordinary literal text behaviour (a query with no metacharacters
matches only its literal substring, case-insensitively); and (d) SQL
metacharacters/quote input (e.g. `'`, `;`, `--`) remaining safely
parameterised and non-injective — proving no query string can alter the
executed SQL regardless of content**; deterministic ordering and limit
enforcement; zero matches; search exception; the search-to-ingestion
id hand-off with no duplicated combination logic; the disappearance/
retrieval-error race; provenance from the actually-included set; continued
`ContentTrust.UNTRUSTED` preservation; no provider call for an invalid
query, zero matches, or no usable context; partial success after
selection; disclosure kept outside the AI-facing context; a genuine
query-selected multi-record injection attempt proving the existing,
unmodified `PromptBuilder` scan still fires; security/approval
compatibility; the new search-level audit event and its logger-failure
isolation; provider/validation failure compatibility (unchanged);
unexpected-action compatibility (unchanged); and full Phase 8/9/10
regression.

Verification commands (for the future implementation turn):
```
poetry run pytest tests/unit/test_memory_selection.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_memory_query_summary_workflow.py -v
poetry run pytest tests/integration/test_memory_query_summary_end_to_end.py -v
poetry run pytest -v
```

---

## 16. Risks and Non-Blocking Debt

- **Carried forward, unchanged:** the `SecurityManager._RULES`/`MemoryTool`-
  versus-AI-memory-ingestion semantic-drift debt (now with a third example,
  `search`, §7.1); the broad `CommandRouter.match()` memory-keyword overlap
  (§7.2); memory retrieval remaining unscoped by session (accurate and
  non-blocking for the current single-user, local architecture).
- **New, disclosed by this plan:** unescaped `%`/`_` wildcard behaviour in
  `EpisodicMemoryStore.search()`'s `ILIKE` pattern (§2.1, §9) — a real,
  existing characteristic, deliberately not patched during planning; a
  narrow future fix (escape literal wildcard characters before pattern
  construction) is identified but not scheduled.
- **New, disclosed by this plan:** the search-to-ingestion TOCTOU-style
  race (§11) — accepted as structurally identical in kind and severity to
  the already-accepted explicit-id race, not a new risk category.
- **New, disclosed by this plan:** the recency bias inherent in reusing
  the store's existing `created_at DESC` order under a size-limited
  combined budget (§5.2) — an honest consequence of the chosen design, not
  a defect.

---

## 17. Scope Exclusions

Deliberately **not** implemented by this capability, reviewed and rejected
individually rather than by blanket assumption:

Semantic search; embeddings; vector databases; cosine similarity; hybrid
lexical/vector retrieval; LLM-based relevance ranking; AI-selected memory
ids; autonomous memory discovery; background indexing; recency-based
*automatic* selection as its own command (recency is only ever a side
effect of reusing existing ordering, never an independent selection mode
here); category-based automatic selection; multi-query expansion; query
rewriting; synonym expansion; reranking; chunking frameworks; long-context
summarisation trees; multi-user/session-isolation redesign; memory
mutation; memory deletion. None of this phase's wording, disclosure, or
code implies any of the above.

---

## 18. Future Selection Architecture

Deterministic query-based selection (Phase 11) becomes, after this phase,
the **second** of what could eventually be several memory-selection
strategies alongside explicit ids (Phase 10) and, further out, recency-
based, category-based, and (separately reviewed and security-assessed)
semantic retrieval. The shared seam that already exists and that any
future strategy would reuse is exactly the one Phase 10 established and
Phase 11 reuses unchanged: **a strategy produces an ordered tuple of
memory ids; `ingest_memories_for_ai()` combines them.** No generic
strategy-pattern abstraction, plugin interface, or registry is introduced
now — with only two concrete strategies existing after this phase, building
a shared abstraction for a hypothetical third would be exactly the kind of
premature generalisation this project's conventions already reject
elsewhere. That decision is deferred until a third concrete strategy is
actually being built.

---

## 19. Final Recommendation

Proceed to Batch 1 (`ai/memory_selection.py`) only after this plan is
explicitly reviewed and approved, following the same batch-by-batch
approval discipline Phase 8, 9, and 10 already established. No production
code, tests, or documentation beyond this plan file have been written in
this turn.

---

## Delivery Summary (updated by this clarification revision)

**This revision's three clarifications, in brief:**
- **Wildcard semantics (§2.1, §3.4, §4.2, §9, §10, §15):** confirmed —
  Phase 11 preserves `MemoryManager.search()`'s existing parameterised
  `ILIKE` semantics unchanged; `%`/`_` keep their live wildcard meaning; no
  escaping is added anywhere, including locally inside
  `ai/memory_selection.py` (rejected explicitly, as that would create a
  second search dialect); user-visible wording describes the capability as
  deterministic case-insensitive content-pattern/substring search with
  inherited wildcard semantics, not guaranteed literal-substring matching;
  four explicit test categories (`%`, `_`, ordinary literal text, SQL
  metacharacter/quote non-injection) added to §15.
- **`memory_query_selection` audit privacy (§12.2):** Candidate B chosen —
  no raw query text, only `query_length`, `outcome`, `match_count`, and
  (on success) `selected_ids` — justified as a direct reuse of two
  existing repository conventions (`audit_suspicious_injection`'s
  `text_length=` field; `_emit_memory_acquisition_event`'s non-content
  id/reason fields), not an invented scheme. Candidate A (raw query)
  rejected as an unbounded, undefended, permanent copy of user text.
  Candidate C (bounded/redacted snippet) found to have no real, distinct
  repository precedent and collapses into Candidate B. Hashing explicitly
  rejected: no keyed-hash/HMAC infrastructure exists in this codebase, and
  an unsalted hash of short, predictable query text would leak information
  rather than protect it.
- **Exact dispatch precedence (§3.2.1):** the full five-step
  `handle_request` sequence is now written out explicitly — file summary,
  singular memory summary, the new query-based matcher, the explicit-id
  plural matcher, then ordinary rule-based `CommandRouter.match()` — with
  all three of the user's required examples traced step-by-step to their
  correct workflow.

---

## Delivery Summary

1. **Repository findings:** §2 — `MemoryManager.search()`/
   `EpisodicMemoryStore.search()` verified directly: substring `ILIKE`
   match on `content` only, case-insensitive, deterministic
   `created_at DESC, id DESC` ordering, default `limit=20` with no clamp
   at this layer, no duplicates possible, no soft-delete exists, empty
   query returns `[]`, unescaped `%`/`_` wildcards, parameterised (SQL-
   injection-safe), returns full `MemoryRecord` objects.
2. **Exact search semantics from code:** §2.1.
3. **Proposed command surface:** `summarise memories about <query>` /
   `summarize memories about <query>`, §3, with a concrete, verified
   routing collision against the existing Phase 10 plural matcher and its
   resolution via longest-prefix-first dispatch ordering.
4. **Architectural decisions and rejected alternatives:** §4 (new
   `ai/memory_selection.py`; rejected extending `memory_ingestion.py`,
   rejected orchestrator-direct search calls, rejected a premature generic
   strategy abstraction).
5. **Selection/order/limit contract:** §5 — Candidate A chosen
   (`search(limit=10)` exactly matching the existing selection ceiling);
   Candidates B and C evaluated and rejected; existing store ordering
   preserved unchanged, with its order-sensitive, size-budget interaction
   explicitly named.
6. **Query trust and injection treatment:** §6 — the query reaches
   `AIReasoningRequest.user_input` exactly as every existing command's
   trailing text already does, never as an `AIContextBlock`, with no
   effect on injection scanning.
7. **Security/router debt review:** §7 — no new `ActionType`/rule/refactor
   required; existing semantic-drift debt reviewed and confirmed
   acceptable; router collision resolved via exact early dispatch, no
   broader redesign performed.
8. **Audit design:** §12 — existing events reused unchanged; one new,
   narrow, non-authoritative `memory_query_selection` event defined with
   exact fields, outcome semantics, and logger-failure isolation.
9. **Search-to-ingestion race analysis:** §11 — a genuine, disclosed
   TOCTOU-style race, structurally identical to the already-accepted
   explicit-id race, represented entirely via Phase 10's existing
   `not_found`/`retrieval_errors` accounting, no locking introduced.
10. **Proposed batch boundaries:** §13 — three batches mirroring Phase
    8/9/10; only Batch 1 scoped to begin next.
11. **Exact files expected to change:** §14.
12. **Test strategy and 1007-test regression floor:** §15.
13. **Risks and non-blocking debt:** §16.
14. **Scope exclusions:** §17.
15. **Final recommendation:** §19 — proceed to Batch 1 only after explicit
    approval of this plan.
16. **Exact plan file created:** `docs/phase_11_implementation_plan.md`
    (this document).
17. **Git status:** working tree unchanged by this turn except for this
    new, untracked planning file; `a.txt` and `report.txt` remain present,
    untouched, pre-existing, and unrelated; nothing staged or committed.
