# Phase 20 Implementation Plan — Durable Jarvis Inbox with a Web-Search-Summary Producer

Status: **Planning only. No production code, tests, or README changes
accompany this document.**

Authoritative repository state this plan builds on, verified directly:
HEAD `4f05dd6` ("Close Phase 19: dashboard end-to-end verification,
concurrency, and documentation (Batch 3)"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean except one
untracked file, `dashboard_test.txt` — Nathan's own artifact from manually
testing a real YELLOW `create file ... and show it` workflow through the
CLI. It is not touched by this plan and must not be staged or deleted by
any future implementation batch unless separately instructed. `poetry run
pytest -q` — **2181 passed, 0 failed**, re-run fresh for this planning
turn. No pre-existing failure exists.

---

## 1. Purpose

Give Jarvis one durable, append-only inbox/output store and a fourth
dashboard tab, so the one AI-generated output family with no durable
trace anywhere today — the `summarise web search for <query>` response —
survives past CLI scrollback and a restart. This is a disclosed, narrow,
additive change to exactly one existing command; every other command is
untouched.

## 2. Scope

**In scope:** one new durable table (`inbox_entries`) and store
(`InboxStore`); one producer — a disclosed addition to the existing
`_handle_web_search_summary_request` that appends an entry only after a
real AI summary has been produced; one new `DashboardReadModel` read
path; one new "Inbox" dashboard tab; a modest, real-metric-only Overview
addition; a light layout pass on the tabs this phase already touches.

**Explicitly out of scope**, repeated here for closure-time reference: any
scheduler, timer loop, background runner, recurring job, missed-run or
duplicate-run policy, timezone scheduling logic, `APScheduler`, `Celery`,
`Redis`, or task queue; any notification delivery (desktop, email, push,
phone, or CLI-on-next-launch); any dashboard command box or
run/approve/deny/delete/retry/schedule/web-search/open-URL control; any
HTTP server, `FastAPI`, `Flask`, `Uvicorn`, IPC bridge, socket, or named
pipe; any Core-service refactor; automatic persistence of the other 7
AI-summary command families, raw web search results, workflow outputs, or
arbitrary CLI output; and an `InboxTool` (no evidence in this plan
justifies one — the store is written by exactly one existing orchestrator
handler and read by exactly one dashboard view, neither of which needs a
registered tool).

## 3. Repository and Precedent Findings

Directly inspected this turn:

- **`core/orchestrator.py::_handle_web_search_summary_request`** (lines
  1225–1357): the exact, single success path ends with `response =
  JarvisResponse(success=True, message=f"{_WEB_SEARCH_SUMMARY_LABEL}
  {summary}", plan=plan)`, followed by
  `self._evaluate_unexpected_actions(response, result, session_id)`, then
  `return response`. Every failure (empty query, AI disabled, search
  unavailable, ingestion failure, AI unavailable) returns early, well
  before this point — meaning the natural, minimal insertion point for an
  inbox write is immediately after `_evaluate_unexpected_actions` and
  before `return response`, so **only the exact final success path**
  writes an entry, with no restructuring of the handler's existing
  control flow.
- **`ai/web_search_ingestion.py::WebSearchIngestionResult`**:
  `included_count`/`omitted_for_size` are already computed and available
  at the handler's call site as plain integers — safe, content-free
  metadata usable for a small "(N results)" display, with no new
  computation needed.
- **`ai/reasoning_models.py::AIReasoningResult`**: carries `provider_name`
  but no separate model field; not needed for this phase's minimal model
  (see §7).
- **`storage/models.py` precedent, re-confirmed column-by-column**:
  `ApprovalHistoryEntry`/`WorkflowHistoryEntry` (the two most recent
  durable-history tables) both use a **plain, non-`ForeignKey` `Integer`
  `session_id`** column — unlike the original Phase 1
  `EpisodicMemory`/`AuditLogEntry`, which use
  `ForeignKey("sessions.id", ondelete="SET NULL")`. The new `InboxEntry`
  table follows the **newer, non-FK convention**, consistent with the two
  most recent precedents, not the oldest ones.
  `_utc_now()` (`datetime.now(timezone.utc)`, `DateTime(timezone=True)`)
  remains the single, unchanged timestamp convention across every table —
  reused verbatim, not reinvented.
- **`ApprovalHistoryStore`/`WorkflowHistoryStore` API shape**: both
  expose a write method (`record_request`/`record_transition`), one or
  more `list_recent(limit)` methods clamped to `_MAX_LIMIT = 50`, and a
  `get`/`latest_status_for` detail lookup. `InboxStore` follows this exact
  shape (§8).
- **`dashboard/read_model.py`/`ui/dashboard_app.py`** (Phase 19): the
  existing `DashboardReadModel` composition pattern, the 120-character
  preview-truncation convention (`_truncate_preview`), the literal-`"UTC"`
  timestamp-suffix convention (`format_timestamp`), the per-panel
  `try/except`-isolated refresh pattern, and the four-tab `ttk.Notebook`
  structure are all reused unchanged — the Inbox tab is a fifth instance
  of an already-proven pattern, not a new one.
- **`main.py`**: constructs `ApprovalHistoryStore`/`WorkflowHistoryStore`
  from the same `session_factory` already built for `MemoryManager`; the
  new `InboxStore` is constructed the same way, alongside them, and
  passed to both `JarvisOrchestrator` (for the producer) and — via
  `dashboard.py`'s own independent `build_read_model()` — to
  `DashboardReadModel` (for the consumer). Neither `main.py` nor
  `dashboard.py` gains any new import beyond the new store/model classes
  themselves.
- **Observability precedent, re-confirmed**: `_audit_web_search_summary_acquisition`
  and `AIRouter._emit_audit_event` both wrap the logger call in a narrow
  `try/except Exception: pass`-equivalent guard and never embed raw
  query/content in the audit detail. The new inbox-write audit events
  follow the identical pattern (§10) — but the inbox *entry itself* is
  explicitly **not** telemetry (§6), a distinction this plan holds
  throughout.

## 4. Producer Authority Rule

The inbox write happens **only** at the single point in
`_handle_web_search_summary_request` where a real, validated AI summary
has already been produced and the exact same success `JarvisResponse` the
CLI will return has already been constructed. Concretely:

- Raw search results alone (before `AIReasoningEngine.reason()` is
  called) **never** create an entry.
- A failed or unavailable AI call (`result is None`) **never** creates an
  entry — the handler already returns before reaching the write point.
- An "invalid" AI response cannot reach this point at all —
  `ResponseValidator` (inside `AIRouter`, unchanged by this phase) already
  rejects a malformed response before `AIReasoningEngine.reason()` can
  return one; only a validated `AIReasoningResult` reaches
  `_handle_web_search_summary_request` at all.
- Injection-detected external content, by itself, never creates or blocks
  an entry — the injection scan is unchanged, detection/report-only
  (§11), and has no bearing on whether the *AI's own final, validated
  summary* gets persisted.
- The presence of AI-suggested actions does **not** block the write, and
  does **not** change what's stored: the stored `body` is the exact same
  string (suggested-steps wording included, if any) the CLI already
  returns. `_evaluate_unexpected_actions`'s existing audit-only policy
  runs completely independently of, and unaffected by, the inbox write.

This is a **WYSIWYG rule**: the inbox entry is a durable copy of exactly
what Nathan was shown, nothing more, nothing synthesized separately.

## 5. Failure Semantics (Explicit Table)

| Scenario | CLI response | Inbox entry |
|---|---|---|
| Successful summary + successful inbox write | Unchanged, exactly as today | One new entry created |
| Successful summary + **failed** inbox write | **Unchanged, exactly as today** — the write failure never surfaces in the response | No entry (write failure is caught, never raised) |
| Web search fails (provider error) | Unchanged (existing honest failure message) | No entry |
| Zero search results | Unchanged (existing honest failure message) | No entry |
| AI reasoning disabled | Unchanged (existing honest failure message) | No entry |
| AI unavailable / call fails | Unchanged (existing honest failure message) | No entry |
| Empty query | Unchanged (existing honest failure message) | No entry |
| Dashboard cannot query the inbox table | N/A (CLI process unaffected) | Inbox tab renders its own isolated error state, exactly like the other three tabs already do |
| Inbox is empty | N/A | Dashboard renders an honest empty-state message |
| Inbox table/database unavailable at producer time | Unchanged CLI response | Write attempt caught and swallowed, exactly like a failed write above |
| Concurrent dashboard refresh during an inbox write | Unaffected — the existing WAL + `busy_timeout=2000ms` configuration (Phase 19, Batch 1) already covers this; no new concurrency work is needed |

**Decisive rule, stated once and held throughout:** a failure to persist
an inbox entry must never be visible in, or change, the CLI's own
response to Nathan. This mirrors the project's existing
observability-isolation precedent (`_emit_memory_acquisition_event` and
every sibling `_audit_*` method already never let a logging failure
affect an authoritative outcome) — but reasoned explicitly here, not
merely copied, because the inbox is user-visible durable *output*, not
mere telemetry: the distinction that matters is that **losing an inbox
write silently degrades a nice-to-have (a saved copy) without ever
degrading the actual, already-delivered answer** — an acceptable,
disclosed tradeoff, not an invisible one.

## 6. Inbox Entry Model and Privacy/Query Decision

```python
@dataclass(frozen=True, slots=True)
class InboxRecord:
    id: int
    session_id: int | None
    source_type: str          # "web_search_summary" (only value today)
    source_query: str         # the literal query, stored verbatim - see below
    body: str                 # the exact final CLI message, disclosure label included
    included_count: int | None
    created_at: datetime
```

**Fields evaluated and explicitly excluded:**

- **Separate title/subject column**: excluded. A display title
  (`"Web search: {query}"`) is cheaply derivable at read/render time from
  `source_type` + `source_query`; storing a redundant, pre-formatted copy
  would be over-modeling for a single producer.
- **Disclosure label stored separately**: excluded — see below.
- **Provider/model metadata**: excluded for v1. `AIReasoningResult.provider_name`
  exists but adds no value Nathan would act on for a single-provider
  system; can be added later with real evidence of demand, not
  speculatively now.
- **`status`**: excluded. Because only successful summaries are ever
  persisted (§4, §5), every row would carry the same single value —
  information-free.
- **`error text`**: excluded — no failure is ever stored (§5's default
  bias).
- **`read`/`unread` flag**: excluded, exactly as flagged in the
  authorizing instructions — the dashboard is read-only by structural
  guarantee, and a read/unread flag is a mutation the dashboard has no
  authority to perform.
- **`pinned`/`starred` flag**: excluded — no evidence of need, no producer
  or consumer for it today.

**Query privacy decision — store the literal query verbatim, not
normalized, redacted, or truncated.** Reasoned explicitly, not by
Phase 18 precedent alone: Phase 18's audit-log policy (never embedding
raw query/result text in `AuditLogEntry`/the acquisition audit event) is
about a **different** artifact — a generic, cross-system telemetry log
whose purpose is operational visibility, not user-facing recall. The
inbox is the opposite: a purpose-built, user-facing record that **only
Nathan** ever queries, on his own local machine, showing Nathan his own
past request. Without the literal query, a list of inbox entries would be
close to useless to browse (indistinguishable "here's a summary" rows
with no way to tell which search each one answers). This is also
consistent with, not a deviation from, existing precedent:
`ApprovalHistoryEntry.action`/`.reason` and `WorkflowHistoryEntry.detail`
already store literal, short, human-authored text describing what a
request was *about* — a single search-query string is the same category
of data, not raw multi-KB ingested content or an untrusted context block.

**Disclosure-label storage decision — store the label together with
`body`, verbatim, exactly as returned to the CLI.** `body` is populated
from the identical string the handler already builds for
`JarvisResponse.message` (`f"{_WEB_SEARCH_SUMMARY_LABEL} {summary}"`,
suggested-steps appendage included if present) — not reconstructed, not
re-derived, not re-applied at render time. This is the simplest of the
three options and the only one that is **historically accurate by
construction**: if `_WEB_SEARCH_SUMMARY_LABEL`'s wording is ever changed
in a future phase, existing inbox entries continue to show the exact
label they were actually disclosed with at creation time, rather than
having a dashboard re-apply today's wording retroactively onto
yesterday's entry.

## 7. ContentTrust and Authority Semantics

Explicit and unchanged from every prior phase's own standing rule,
restated for this artifact specifically: an `InboxRecord.body` is a
stored, user-visible **display string**. It is never a `ToolRequest`,
never a `Plan`, never approval authority, and is never fed into
`CommandRouter`, `ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, or
`AIReasoningEngine` — by the dashboard, by a future command, or by
anything else added in this phase. The dashboard's rendering of inbox
text is exactly as inert as its rendering of memory/approval/workflow
text already is (Phase 19) — proven the same way: structural,
AST-verified absence of any execution-component import anywhere the
inbox is read or rendered.

Persisting an AI summary does not grant it new authority merely by
existing longer: if a malicious search-result snippet influenced the
*wording* of the AI's summary (already possible, already inert, per
Phase 18), storing that same wording durably does not change its
authority in any way — it is still just data, now saved instead of
scrolled past.

## 8. Storage Architecture — `InboxStore`

New table `inbox_entries` (via the existing `Base.metadata.create_all`
pattern in `storage/database.py::initialize_database` — no new migration
framework, exactly as every existing table is created):

```python
class InboxEntry(Base):
    __tablename__ = "inbox_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_query: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    included_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
```

New `inbox/inbox_store.py` (new top-level package, mirroring `approval/`
and `workflow/`'s own top-level-package convention rather than nesting
under an existing one):

```python
class InboxStore:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None: ...

    def append(
        self,
        *,
        source_type: str,
        source_query: str,
        body: str,
        included_count: int | None = None,
        session_id: int | None = None,
    ) -> InboxRecord: ...

    def list_recent(self, limit: int = 20) -> list[InboxRecord]: ...

    def count(self) -> int: ...

    def get(self, entry_id: int) -> InboxRecord | None: ...
```

`list_recent` clamps to `[1, _MAX_LIMIT]` with `_MAX_LIMIT = 50`,
ordered `created_at.desc(), id.desc()` — identical convention to every
sibling store. `append` is the only write method; there is no
`update`/`delete`/`mark_read` method anywhere on this class, enforcing
append-only semantics at the API surface, not merely by convention.

## 9. Append-Only vs. Mutable Semantics

**Decision: strictly append-only.** No edit, no delete, no read/unread
mutation. This is not merely "probably out of scope" as a default — it is
**structurally enforced**: `InboxStore` exposes no method capable of
mutating an existing row, so the dashboard (which only ever holds a
`DashboardReadModel`, never an `InboxStore` reference with write access
context) has no path to mutation even if a future developer mistakenly
wired a callback to try.

## 10. Audit/Observability Decision

Two new, narrow audit events, neither duplicating existing ones (the
acquisition event already records the *search* step's included/omitted
counts; these two record the separate *persistence* step's outcome):

- `inbox_entry_created` (`EventOutcome.SUCCESS`, detail
  `f"source_type={source_type}"` — never the query or body).
- `inbox_entry_creation_failed` (`EventOutcome.FAILURE`, detail
  `f"source_type={source_type} error={exc}"` — the exception message
  only, never the query or body).

Both wrapped in the same narrow `try/except Exception: pass`-equivalent
guard as every existing `_audit_*`/`_emit_*_event` method, so a failing
logger can never affect whether the inbox write itself succeeds or the
CLI response is returned.

## 11. Injection Honesty (Unchanged, Restated)

Phase 20 changes nothing about Phase 7/18's injection posture: scanning
remains detection/report-only, suspicious external content remains inert
data, the AI result remains advisory only, and dashboard display of
`body` remains exactly as inert as every other dashboard tab's text.
Phase 20 must not be described, in its own README section or completion
report, as making injection "safer" — persistence is orthogonal to
detection/enforcement, and this plan does not conflate them.

## 12. Dashboard Read-Model and UI Extension

`dashboard/read_model.py` gains one new frozen row type and one new
method, following the exact existing pattern (§3):

```python
@dataclass(frozen=True, slots=True)
class InboxRow:
    id: int
    source_query: str
    preview: str          # _truncate_preview(body), same 120-char convention
    full_body: str
    included_count: int | None
    created_at: datetime

# DashboardReadModel gains:
def get_recent_inbox_entries(self, limit: int = 20) -> list[InboxRow]: ...
```

`DashboardOverview` gains `total_inbox_count: int` and
`recent_inbox_entries: tuple[InboxRow, ...]` (5 most recent, mirroring
the existing `recent_approvals`/`recent_workflows` shape exactly) — both
real, queried values; no estimated or fabricated metric.

`ui/dashboard_app.py` gains a fifth tab, **"Inbox"**, following the exact
existing per-tab structure: a `ttk.Treeview` (columns: Created At, Query,
Preview), a detail pane showing `full_body` and `included_count` on row
selection, an honest empty state ("No inbox entries yet."), and an
isolated `try/except`-wrapped refresh identical in shape to the other
four panels'. The Overview tab gains one more real-data line
(`f"Total inbox entries: {overview.total_inbox_count}"`) alongside the
existing three.

**Modest layout pass, scoped exactly as approved:** since this phase
already touches every tab's construction code to add the fifth tab and
Overview line, a light pass on padding/grouping/section-labeling across
the *existing* four tabs plus the new one is in scope — a toolkit change,
new dependency, or any animated/fabricated visual element is not.

## 13. Idempotency and Duplicate Behavior

**Default bias, unchanged: append a new entry on every successful run.**
No deduplication of identical queries, no "update the existing entry for
this query" behavior. No repository evidence (no existing store
deduplicates by content anywhere) supports adding one, and doing so would
require deciding a normalization/matching rule with no real use case
driving it yet.

## 14. Security/Adversarial Review Requirements (For Batch 3 Testing)

The stored `source_query`/`body` must be proven, with real adversarial
content, to remain inert dashboard display: fake commands, fake
system/developer/user messages, fake tool-call JSON/XML, fake approval or
workflow instructions, plain and malicious-looking URLs, delete/execute/
format-drive language, prompt-injection phrasing, text claiming to be
Nathan, unusually long text, and unusual Unicode/control characters must
all render as literal `Treeview` text with zero `CommandRouter`,
`ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, or
`AIReasoningEngine` invocation, zero URL opening, zero subprocess launch,
and zero write mutation triggered by selection or refresh — the same
proof shape Phase 19 already established, extended to the new tab and
the new store.

## 15. Batch Plan

### Batch 1 — Storage Model and `InboxStore`

- **Purpose**: the durable table, the store, and the record dataclass,
  fully tested in isolation from any producer or UI.
- **Production files**: `storage/models.py` (extended — `InboxEntry`),
  `inbox/__init__.py` (new), `inbox/inbox_store.py` (new).
- **Test files**: `tests/unit/test_inbox_store.py` (new).
- **Invariants protected**: append-only (no mutating method exists);
  ordering matches every sibling store's `created_at.desc(), id.desc()`
  convention; `_utc_now()` reused unchanged; empty-store queries return
  valid empty results, not errors; long body/query text is stored and
  retrieved without truncation at the store layer (truncation is a
  dashboard-layer display concern only, per §12).
- **Explicit non-goals**: no producer wiring, no dashboard changes, no
  audit events yet (those live with the producer in Batch 2).
- **Verification**: `poetry run pytest tests/unit/test_inbox_store.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files above.

### Batch 2 — Producer Wiring and Dashboard Consumer

- **Purpose**: wire the one approved producer (§4) into
  `_handle_web_search_summary_request`, add the two audit events (§10),
  extend `DashboardReadModel` and `ui/dashboard_app.py` with the Inbox
  tab and Overview line, and apply the modest layout pass (§12).
- **Production files**: `core/orchestrator.py` (extended — the disclosed
  producer call site + two audit methods), `main.py` (extended — construct
  and pass through `InboxStore`), `dashboard.py` (extended — construct
  and pass through `InboxStore`), `dashboard/read_model.py` (extended),
  `ui/dashboard_app.py` (extended).
- **Test files**: `tests/unit/test_web_search_summary_workflow.py`
  (extended — producer behavior with a fake `InboxStore`/real store),
  `tests/unit/test_dashboard_read_model.py` (extended),
  `tests/unit/test_dashboard_app.py` (extended).
- **Invariants protected**: the CLI response text is provably unchanged
  by a dedicated regression test (byte-for-byte comparison against the
  pre-Phase-20 response shape); an entry is created if and only if the
  handler's existing success path is reached; a failed
  search/AI/empty-query path creates zero entries; a raising `InboxStore`
  does not change the CLI response (§5) and does not raise out of the
  handler.
- **Explicit non-goals**: no end-to-end real-SQLite proof yet (Batch 3),
  no concurrency proof yet.
- **Verification**: the three extended test files individually, then full
  `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files above.

### Batch 3 — End-to-End Verification, Adversarial Tests, Documentation, Closure

- **Purpose**: real temporary SQLite, a fake `WebSearchProvider` + fake AI
  provider through the real `AIRouter`/`AIReasoningEngine` path (mirroring
  Phase 18's own end-to-end pattern exactly), a real `InboxStore`, a real
  `DashboardReadModel`, and a real (withdrawn) Tk dashboard — proving the
  full pipeline, refresh-sees-new-entries behavior, and every adversarial
  case in §14.
- **Test files**: `tests/integration/test_inbox_end_to_end.py` (new).
- **Documentation**: `README.md` (Phase 20 section, Inbox tab, disclosed
  producer-behavior note, non-goals), `docs/phase_20_implementation_plan.md`
  (tracked at closure), `docs/phase_20_completion_report.md` (new).
- **Verification commands**: `poetry run pytest tests/integration/test_inbox_end_to_end.py -v`, then full `poetry run pytest -q`, `git diff --check`, `git status`.
- **Commit boundary**: one closure commit, staging only the files this
  batch touches. `dashboard_test.txt` remains untouched and unstaged
  throughout every batch.

## 16. Master Specification Reconciliation

Phase 20 is honestly a **durable output/inbox slice**: dashboard-visible,
saved AI web-search summaries, and a named, evidence-based prerequisite
for any future scheduled information task (which would otherwise have
nowhere durable to land). It is **not** a notification system (no
transient-attention mechanism exists or is implied), not a scheduler, not
a phone client, not the full Master Specification dashboard, not an AI
memory system or knowledge base, not a Research Agent, not autonomous
browsing, not a command center, not a Core service, and not a messaging
app.

## 17. Adversarial Planning Review

- **Right first producer?** Yes — of the 8 AI-summary families, web-search
  summaries are the only ones whose *source* content (live search
  results) is itself not durable anywhere else either, making them the
  single highest-value, least-redundant candidate.
- **Changing an existing command too silently?** No — §4/§5 make the
  change explicit and testable (a dedicated regression test proves the
  CLI response is byte-for-byte unchanged), and this plan states the
  change plainly rather than burying it.
- **Storing sensitive queries without a deliberate decision?** No — §6
  reasons the query-privacy decision explicitly, distinguishing this
  user-facing store from Phase 18's telemetry-avoidance policy rather than
  copying that policy by rote.
- **Pretending inbox entries are trusted knowledge?** No — §7 states
  plainly they are display strings only, never trusted context, never
  reused as AI input.
- **Can inbox text become executable?** No — no code path anywhere in
  this plan feeds `body`/`source_query` into `CommandRouter`,
  `ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, or
  `AIReasoningEngine`.
- **Can dashboard selection trigger actions?** No — selection only
  populates a local detail pane, identical to the existing Memories/
  Workflow tabs' own selection behavior.
- **Adding read/unread mutation accidentally?** No — §9 makes append-only
  a structural guarantee (no mutating method exists on `InboxStore`).
- **Building notification infrastructure under another name?** No — no
  transient-attention mechanism of any kind exists in this plan; §16
  states the distinction explicitly.
- **Building scheduler prerequisites too early?** No new scheduler
  prerequisite is built here beyond the inbox itself, which was already
  identified, independently, as necessary regardless of when scheduling
  is eventually pursued.
- **Over-modeling future producers?** No — §6 explicitly rejects title,
  status, error-text, provider/model, and read/unread fields for lack of
  present need; `source_type` is the one minimal, already-necessary
  discriminator column, not a producer-abstraction framework.
- **Creating an empty abstraction?** No — one real producer and one real
  consumer both ship in this same phase (§ the authorizing instructions'
  own named requirement).
- **Really reduces Nathan's workload?** Yes, directly — §13 of the prior
  architectural review named the concrete mechanism (AI summaries
  currently vanish); this phase fixes exactly that for the one family
  most affected.
- **Is one producer enough to justify the phase?** Yes — the phase's own
  value is the durable mechanism plus dashboard integration, which a
  single well-chosen producer is sufficient to prove and use immediately.
- **Preserving Phase 18 snippet-only honesty?** Yes — `body` is stored
  verbatim including the fixed disclosure label; nothing about persistence
  changes what the label says or when it's shown.
- **Does inbox write failure break existing command semantics
  incorrectly?** No — §5's table makes this the one property tested most
  directly: a failed write never changes, blocks, or delays the CLI
  response.
- **Are audit events duplicative or useful?** Useful, not duplicative —
  they record a different step (persistence) than the existing
  acquisition event (search) or `AIRouter`'s event (the reasoning call).
- **Did we leave `dashboard_test.txt` alone unless instructed?** Yes —
  confirmed present and untouched in §baseline; no batch in this plan
  stages, modifies, or deletes it.

No finding in this pass requires a design change.

## 18. Final Summary

- **Final inbox table/model**: `inbox_entries` /
  `InboxEntry` (`id`, `session_id`, `source_type`, `source_query`, `body`,
  `included_count`, `created_at`) — 6 real columns plus `id`, no FK on
  `session_id` (matching the `ApprovalHistoryEntry`/`WorkflowHistoryEntry`
  precedent).
- **Final `InboxStore` API**: `append(...)`, `list_recent(limit=20)`,
  `count()`, `get(entry_id)` — no update/delete/mark-read method exists.
- **Final producer behavior**: `_handle_web_search_summary_request`
  writes exactly one entry, only after its existing success
  `JarvisResponse` is built, using that exact response text as `body`;
  every existing failure path is unaffected and creates no entry.
- **Final query/privacy decision**: store `source_query` literally,
  verbatim, unredacted — a deliberate, reasoned choice for this
  user-facing (not telemetry) store.
- **Final disclosure-storage decision**: the fixed label is stored
  inline, as part of `body`, verbatim from the CLI response — never
  re-derived or re-applied later.
- **Final failure semantics**: a failed inbox write never changes,
  delays, or blocks the CLI's own response; it is caught, optionally
  audited, and otherwise invisible to Nathan in that moment.
- **Final append/dedup decision**: append-only, no deduplication, a new
  entry every successful run.
- **Final dashboard Inbox view**: a fifth tab (Created At, Query,
  Preview columns; a detail pane with full body + result count on
  selection; an honest empty state; an isolated error state).
- **Final overview/layout changes**: one new real-data Overview line
  (`total_inbox_count`) plus a 5-entry recent-inbox preview, and a modest,
  non-toolkit-changing layout/spacing pass across all five tabs.
- **Final read-only authority guarantee**: `InboxStore` is never imported
  by, or reachable from, any dashboard file with write intent — the
  dashboard only ever holds a `DashboardReadModel`; no new
  execution-component import exists anywhere added by this phase,
  structurally verified.
- **Final audit/observability decision**: two new, narrow events
  (`inbox_entry_created`, `inbox_entry_creation_failed`), metadata-only,
  never duplicating the existing acquisition or `AIRouter` events.
- **Final batch sequence**: (1) storage/store; (2) producer + dashboard
  consumer; (3) end-to-end/adversarial verification, documentation,
  closure.
- **Explicit Phase 20 non-goals**: every item listed in §2 and repeated
  in the authorizing instructions — no scheduler, no notifications, no
  dashboard command/write controls, no server/Core-service work, no
  broader auto-persistence, no `InboxTool`.
- **Likely future pressure points**: a GREEN-only scheduled web-search-
  summary task now has a real, proven destination (this inbox) and
  becomes the natural next candidate in this chain; a notification layer
  becomes meaningful only once something recurring actually produces
  inbox entries unattended; the other 7 AI-summary families remain
  candidates for a future, separately-reviewed broadening of producers,
  not assumed here; and `dashboard_test.txt` remains an unaddressed,
  harmless artifact in the working tree for Nathan to clear at his own
  discretion.
