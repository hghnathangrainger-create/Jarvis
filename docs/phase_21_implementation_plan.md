# Phase 21 Implementation Plan — GREEN-Only Scheduled Web-Search Summaries to Inbox

Status: **Planning only. No production code, tests, or README changes
accompany this document.**

Authoritative repository state this plan builds on, verified directly:
HEAD `6e15c8f` ("Close Phase 20: inbox end-to-end verification,
adversarial proof, and documentation (Batch 3)"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean except one
untracked file, `dashboard_test.txt` — Nathan's own artifact, confirmed
present and untouched, not addressed by this plan. `poetry run pytest -q`
— **2252 passed, 0 failed**, re-run fresh for this planning turn.

---

## 1. Purpose

Let Nathan define a small number of daily, fixed-time web-search-summary
schedules that run unattended and save their results into the existing
durable Inbox — the first proactive, unattended Jarvis behavior — while
remaining exactly as narrow as Phase 20's own producer: one action type,
no general scheduler, no new authority anywhere in the system.

## 2. Scope

**In scope:** one durable, *mutable* `schedules` table and `ScheduleStore`
(the first non-append-only durable store in the project, since a
schedule's `enabled`/`last_run_at` fields change in place); four small
tools (`ScheduleCreateTool`, `ScheduleListTool`, `ScheduleEnableTool`,
`ScheduleDisableTool`) registered exactly like every existing tool,
routed through the unmodified `CommandRouter`/`ToolExecutor`/
`SecurityManager`/`ApprovalManager` pipeline; one independent runner
process (`scheduler.py`); one narrow, new execution helper (deliberately
**not** a reuse of `_handle_web_search_summary_request` - see §7); an
atomic claim mechanism; a read-only dashboard Schedules tab.

**Explicitly out of scope**, repeated here for closure-time reference:
general-purpose scheduling, arbitrary command scheduling, stored command
strings executed later, workflow-triggering schedules, YELLOW/RED
scheduled *actions* (schedule *creation* itself is YELLOW - see §9 - but
the thing it schedules remains GREEN-only), approval scheduling, a
background-agent framework, `Celery`, `Redis`, `APScheduler` (no evidence
found requiring it - see §6), a task queue, any notification channel,
dashboard write actions of any kind, a Core-service refactor, an HTTP
server, an IPC/socket bridge, multiple schedule action types, a
natural-language parser, a cron-expression system, webpage fetching,
Research Agent work, and voice/phone work.

## 3. Repository and Precedent Findings

Directly inspected this turn:

- **`core/orchestrator.py::_handle_web_search_summary_request`**
  (unchanged, re-read in full): its single success path builds
  `AIReasoningRequest(user_input=user_request, context_block=ingestion.context, ...)`
  where `user_request` is Nathan's **entire typed command text** (for
  example `"summarise web search for jarvis ai"`).
- **`ai/reasoning_engine.py`**: `_build_prompt(request)` wraps this into
  `f"User request: {request.user_input}"`, which becomes `AIRouter`'s
  `user_message`.
- **`ai/prompt_builder.py::build()`** (re-read in full): `user_message` is
  placed directly into the final prompt's user-content section and is
  **never passed through `scan_for_injection`** - only the `context`
  block receives that treatment when its trust is not
  `JARVIS_TRUSTED`. This is correct and safe today because `user_message`
  is assumed, by design, to be Nathan's own live, current-turn text.
- **`ai/web_search_ingestion.py`** (re-read in full): the literal query
  never appears in the ingested `AIContextBlock.text` at all - it is used
  only as a `WebSearchProvider.search()` parameter and as
  `AIContextBlock.source` metadata (`f"web-search:{query!r}"`), which
  `PromptBuilder.build()` never reads or sends to the AI provider. The
  query reaches the AI's prompt content **only** via the interactive
  path's `user_message`.
- **Critical finding (the trust-origin question the authorizing
  instructions asked this plan to address explicitly): a scheduled run
  has no live Nathan present.** If a runner reused
  `_handle_web_search_summary_request` by constructing a synthetic
  command string (e.g. `f"summarise web search for {stored_query}"`),
  the stored, replayed query would flow into the one prompt slot that
  receives **zero** injection scanning - specifically because that
  slot's entire design assumption ("this is what a live human is typing
  right now") would be silently violated. This is a real, previously
  unexamined gap, not a hypothetical one. **Resolution: §7.**
- **`inbox/inbox_store.py`**: `append()`'s `source_type` parameter already
  accepts any string; no schema change is needed to add a second,
  honestly-distinct value for scheduler-produced entries (§11).
- **`storage/models.py`** (re-read in full): `ApprovalHistoryEntry`/
  `WorkflowHistoryEntry`/`InboxEntry` are all **append-only or
  write-then-decide-once** (an approval is created pending, then decided
  exactly once). A mutable `enabled` flag and a repeatedly-updated
  `last_run_at` make `ScheduleEntry` a genuinely new table *shape* in
  this project - disclosed explicitly, not treated as "just another
  history table."
- **`core/command_router.py`**: no existing prefix uses the words
  "schedule", "enable", or "disable" anywhere (`_FILE_LIST_PREFIXES`
  contains only "list files"/"show files"/"list directory" variants) -
  confirmed by direct grep, not assumed. No collision exists with the
  proposed grammar (§8).
- **`security/security_manager.py`**: no existing keyword rule matches
  "schedule", "enable schedule", or "disable schedule" - all three would
  fall through to the existing `_DEFAULT_TIER = YELLOW` fallback
  unchanged, and `"list"` is already a GREEN rule. **Zero new
  `SecurityManager` logic is strictly required**; three small, explicit,
  specifically-worded rules are nonetheless recommended for the same
  reason every existing YELLOW rule has its own tailored reason text
  rather than the generic fallback message (§9) - a disclosed UX/honesty
  refinement, not a requirement.
- **`tools/builtin/workflow_history_tool.py`** (re-read as the template
  for `ScheduleListTool`): a thin wrapper exposing a fixed `action_for()`
  string and delegating reads to its store - the exact shape
  `ScheduleListTool` will follow.
- **`main.py`/`dashboard.py`**: both already follow the "construct one
  store over the shared `session_factory`, pass it to the consumer(s)"
  composition-root pattern three times over (approvals, workflow
  history, inbox). `scheduler.py` will be a **fourth** independent
  composition root, mirroring `dashboard.py`'s own precedent exactly.
- **`pyproject.toml`**: no scheduler/task-queue dependency
  (`APScheduler`, `Celery`, `Redis`) exists - confirmed directly. None is
  needed: the "due" check is a simple, bounded poll loop.
- **README Phase 20 section / completion report**: confirm the current,
  exact producer/consumer boundary this plan extends, not redefines.

## 4. Schedule Model

```python
class ScheduleEntry(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    time_of_day: Mapped[str] = mapped_column(String(5), nullable=False)  # "HH:MM", validated
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False, index=True
    )
```

**Fields evaluated and explicitly excluded:**

- `updated_at` - excluded; `enabled`'s own value plus the `tool_call`
  audit event already generated by `ScheduleEnableTool`/
  `ScheduleDisableTool` (§9) capture the meaningful history without a
  redundant column.
- `last_error`/`failure_count` - excluded; failures are recorded as audit
  events (§12), not schedule-row state, keeping this table's *shape*
  minimal even though, unlike prior tables, it is mutable.
- `timezone` - excluded; host local time is used uniformly (§10).
- `action_type` - excluded; the runner hard-codes exactly one action in
  code, not configuration (§7, §14 - the explicit guard against becoming
  a task queue).
- `next_run_at` - excluded; computed fresh by the runner on each poll
  from `enabled`/`last_run_at`/`time_of_day`, never stored, so it can
  never drift out of sync with reality.
- `max_results`/search-limit override - excluded; the existing
  `ingest_web_search_for_ai` defaults are reused unchanged, with no new
  per-schedule configurability.

**A genuinely new precedent, disclosed:** this is the first durable
table in the project that is neither append-only nor write-once-then-
decided-once. `ScheduleStore`'s API (§5) is kept as narrow as possible in
compensation - exactly four mutating operations (create, enable,
disable, claim), each independently reviewable, none of them generic.

## 5. `ScheduleStore` API

```python
class ScheduleStore:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None: ...

    def create(self, *, query: str, time_of_day: str, name: str | None = None) -> ScheduleRecord: ...
    def list_all(self, limit: int = 50) -> list[ScheduleRecord]: ...
    def get(self, schedule_id: int) -> ScheduleRecord | None: ...
    def enable(self, schedule_id: int) -> ScheduleRecord | None: ...
    def disable(self, schedule_id: int) -> ScheduleRecord | None: ...
    def count(self) -> int: ...
    def claim_due(self, schedule_id: int) -> bool: ...
```

`create()` validates `query` is non-empty and `time_of_day` matches a
strict `^([01]\d|2[0-3]):[0-5]\d$` pattern (24-hour `HH:MM`, seconds
never accepted) - both validated in Python, raising a clear
`ValueError` the calling tool translates into an honest tool-result
failure, exactly like `FileCreateTool`'s own existing path-validation
convention. `list_all()` orders by `id.asc()` (a small, stable
configuration list, not a "most recent history" view - a deliberate,
disclosed difference from every other store's `created_at.desc()`
convention). There is **no** `update`/`delete`/`set_query`/`rename`
method - the only way to stop a schedule from running is `disable()`,
never removal, keeping the write surface exactly as narrow as the
four operations this phase actually needs.

`claim_due()` is the atomic guard (§13) - it is the **only** method that
both reads and conditionally writes `last_run_at` in one step, and it is
never called from the dashboard or from any interactive command; only
`scheduler.py` calls it.

## 6. Schedule Creation Mechanism

Evaluated: (1) hardcoded sample - rejected, not usable; (2) config file -
rejected, no validation feedback, less discoverable, and inconsistent
with every other stateful piece of Jarvis data living in SQLite; (3)
**CLI commands - approved**; (4) dashboard write actions - rejected,
reopens the exact command-interaction authority question the Phase
19→20 review already deferred; (5) seed script - rejected as a product
mechanism (acceptable only as a test fixture, never user-facing); (6)
natural-language parser - rejected, adds ambiguity/injection surface for
no real benefit over a fixed `HH:MM` field Nathan types once.

**Architectural decision: schedule CRUD is implemented as four ordinary
tools, not a bypass-dispatch orchestrator handler.** Unlike the AI-summary
commands (which bypass `ToolExecutor` because their entire point is an
AI reasoning call), schedule creation/enable/disable are structurally
identical to `MemoryTool`'s own "remember"/"forget" shape: a plain,
durable write against one row. Routing them through the existing,
completely unmodified `CommandRouter.match()` → `ToolRegistry` →
`ToolExecutor.execute()` → `SecurityManager.classify_action()` → (YELLOW)
`ApprovalManager` pipeline means:

- Zero new orchestrator code.
- YELLOW confirmation for schedule creation/enable/disable comes **for
  free** from existing, unmodified machinery - Nathan is asked to
  confirm before committing Jarvis to a new recurring, unattended action,
  exactly the deliberate friction point named in the prior architectural
  review.
- The existing `tool_call` audit event already covers "a schedule was
  created/enabled/disabled" with zero new audit code (§12).

## 7. Runner Architecture and the Trust-Origin Resolution

**Decision: extract a narrow, new helper - do not reuse
`_handle_web_search_summary_request` by constructing a synthetic command
string.** Reusing it would place the stored, replayed query into
`user_message`, the one prompt slot with zero injection scanning,
precisely because that slot's trust assumption ("a live human is typing
this right now") no longer holds for an unattended run. This plan
resolves that gap with a stricter posture than the interactive path -
not a weaker one:

- The new helper's `user_input` is a **fixed, Jarvis-authored
  instruction** (for example, `"Summarise the following web search
  results."`) - it never contains the stored query, so nothing
  stored/replayed ever reaches the unscanned trust slot at all.
- The query is used only as a `WebSearchProvider.search()` parameter
  (unchanged from Phase 18/20) and is additionally placed **inside** the
  `UNTRUSTED` context block's own text (as a labelled line preceding the
  search-result snippets), so that if it is ever shown to the AI at all,
  it goes through the **same injection scan every other untrusted
  context already receives** - a strictly safer treatment than the
  interactive path's own `user_message`, justified specifically because
  no live human confirms a scheduled run each time it fires.
- This is implemented as a small, additive composition in the *new*
  runner-support module - `ai/web_search_ingestion.py` itself is **not
  modified**, preserving Phase 18's own reviewed, unchanged behavior for
  the interactive command. The new module calls the existing
  `ingest_web_search_for_ai(provider, query)` unchanged, then builds one
  new `AIContextBlock.from_untrusted(f"Search query: {query}\n\n{ingestion.context.text}", source=...)`
  before constructing the `AIReasoningRequest`.
- The fixed `_WEB_SEARCH_SUMMARY_LABEL` constant is imported directly
  from `core.orchestrator` (not duplicated) so the scheduled path's
  disclosure wording can never silently drift from the interactive
  path's own.

**Runner process (`scheduler.py`):** a fourth independent composition
root, mirroring `dashboard.py` exactly - constructs its own
`create_database_engine`/`session_factory`, its own
`DuckDuckGoSearchProvider`, its own `AIRouter`/`AIReasoningEngine` (real
`ClaudeProvider`, subject to `AI_REASONING_ENABLED` exactly like
`main.py`), its own `ScheduleStore`/`InboxStore`. It never imports
`CommandRouter`, `ToolExecutor`, `ApprovalManager`, or `WorkflowEngine` -
there is no live command to route, no approval to gate (the schedule was
already approved at creation time), and no workflow involved. It polls
on a modest interval (proposed: 60 seconds - frequent enough that a
`time_of_day` is honored within a minute, infrequent enough to be a
trivial resource cost), and for each enabled schedule: calls
`claim_due(schedule_id)`; if claimed, runs the narrow helper above; on
success, appends to the inbox with `source_type="scheduled_web_search_summary"`
(§11); on failure at any stage, audits and creates no inbox entry (§12).
It exposes a single-pass, non-looping entry point for tests (§18) so a
test can invoke exactly one poll cycle without an infinite loop.

## 8. CLI Command Grammar

```text
schedule web search summary for <query> at <HH:MM>
list schedules
enable schedule <id>
disable schedule <id>
```

Collision-checked directly against every existing `*_PREFIXES` constant
in `core/command_router.py` (§3) - none uses "schedule", "enable", or
"disable"; "list schedules" cannot be confused with "list files"/"list
directory" (different second word, exactly the established
disambiguation convention this project already uses for every other
prefix family). No arbitrary text is ever accepted after the fixed
grammar positions; `<query>` and `<HH:MM>` are the only two extracted
fields, mirroring `FileCreateTool`'s own "create file `<path>` with
`<content>`" extraction shape exactly.

## 9. Security Classification

Verified directly: with **zero** new `SecurityManager` rules, "schedule
web search summary for..." / "enable schedule..." / "disable schedule..."
all fall through to the existing `_DEFAULT_TIER = YELLOW`, and "list
schedules" already matches the existing GREEN `"list"` rule. **This
already produces exactly the desired classification.** Three small,
explicit, specifically-worded rules are nonetheless recommended -
consistent with every existing YELLOW rule having its own tailored
reason, rather than the generic fallback text - as a disclosed, optional
UX refinement:

```python
_Rule("schedule web search", SecurityTier.YELLOW, "Creating a scheduled action commits Jarvis to run it unattended and should be confirmed."),
_Rule("enable schedule", SecurityTier.YELLOW, "Re-enabling a scheduled action resumes unattended runs and should be confirmed."),
_Rule("disable schedule", SecurityTier.YELLOW, "Disabling a scheduled action changes state and should be confirmed."),
```

No rule change is made to the scheduled *action itself* (the runner never
classifies anything - it has no live command to classify at all).

## 10. Time Semantics

**Decision: host local time throughout**, computed fresh at every check
via `datetime.now().astimezone()` - never a stored per-schedule
timezone. `time_of_day` is a strict 24-hour `HH:MM` (seconds ignored/not
accepted); an invalid value is rejected at `create()` time with a clear
error, never silently clamped. DST and clock changes are handled
correctly *for free* by relying on the OS's own local-time conversion
rather than any manual offset arithmetic. `last_run_at` continues to be
stored in UTC, matching every other table's unbroken `_utc_now()`
convention - the "due" comparison converts it to local time at
comparison time, not at storage time, preserving both properties at
once (§13).

## 11. Privacy/Query Decision

**Decision: store the literal, unredacted query - consistent with, not
a departure from, Phase 20's own reasoning.** A schedule is exactly as
user-facing and local as an Inbox entry; the same argument applies
(without the literal query, a list of schedules would be nearly
unreadable). `source_type="scheduled_web_search_summary"` (a distinct
value from the interactive path's `"web_search_summary"`) is used for
inbox entries this phase's runner produces - a small, honest,
zero-schema-cost disclosure that lets Nathan (and the dashboard) tell an
overnight, unattended result apart from one he asked for directly.

## 12. Audit/Observability Decisions

CRUD operations need **no new audit code** - `ToolExecutor`'s existing
`tool_call` event already fires for every `ScheduleCreateTool`/
`ScheduleEnableTool`/`ScheduleDisableTool` invocation, exactly like every
other tool. The runner (which never touches `ToolExecutor`) gets three
new, narrow, metadata-only events, mirroring Phase 20's own
`inbox_entry_created`/`_failed` pair precisely:

- `scheduled_summary_claimed` (detail: `f"schedule_id={id}"`)
- `scheduled_summary_succeeded` (detail: `f"schedule_id={id} included={n}"`)
- `scheduled_summary_failed` (detail: `f"schedule_id={id} error={exc}"`)

**Never the literal query or body**, matching the explicit instruction
and Phase 20's own established convention. A not-due schedule is not
audited at every poll (would be pure noise); only real state
transitions are recorded.

## 13. Duplicate/Race Guard

`claim_due(schedule_id)` issues one atomic, single-statement SQL
`UPDATE`:

```sql
UPDATE schedules
SET last_run_at = :now_utc
WHERE id = :id
  AND enabled = 1
  AND time_of_day <= :now_local_hhmm
  AND (last_run_at IS NULL OR date(last_run_at, 'localtime') < date(:now_utc, 'localtime'))
```

checking `rowcount == 1` before the caller proceeds to actually run the
search/AI/inbox-write sequence. This closes the two-runner race at the
SQL layer itself (SQLite's own transactional atomicity, already
WAL-configured since Phase 19) - there is no Python-side
read-then-write gap for a second process to land in between. **This
specific SQL construction (the `'localtime'` modifier applied to a
UTC-stored value) must be empirically verified against this repository's
actual SQLAlchemy/SQLite versions during Batch 2 implementation** -
consistent with this project's standing discipline of verifying claims
about SQLite behavior directly (as Phase 19 did for `journal_mode`)
rather than trusting documentation alone. **A simpler fallback design -
a plain Python read-then-write, relying operationally on Nathan running
only one `scheduler.py` process - is the explicitly considered, less
robust alternative** if the atomic SQL approach proves awkward in
practice; which of the two ships is a key decision left open for Batch 2
(§21).

A claimed run that then fails (search error, AI error, inbox-write
error) does **not** retry the same day and does **not** re-attempt on
the next poll cycle - `last_run_at` was already updated at claim time,
so the schedule is correctly not due again until tomorrow. This is a
deliberate, disclosed choice: a narrow phase should not also invent a
retry policy.

## 14. Failure Semantics (Explicit Table)

| Scenario | Inbox entry | Schedule state |
|---|---|---|
| Successful claim + successful run | One entry created | `last_run_at` updated |
| Successful claim + search failure / zero results / AI disabled / AI unavailable / AI failure | None | `last_run_at` updated (no retry today) |
| Successful claim + inbox write failure | None (write itself failed) | `last_run_at` updated (no retry today) |
| Claim fails (already claimed, not due, or disabled) | None | Unchanged |
| Runner crashes after claim, before running | None | `last_run_at` updated - schedule correctly waits until tomorrow, not stuck retrying |
| Schedule disabled mid-poll-cycle (between listing and claiming) | None | `claim_due`'s own `enabled = 1` WHERE clause naturally excludes it |
| Invalid/corrupt schedule row | Skipped, audited, never crashes the poll loop for other schedules | Unchanged |
| Very long / empty query | Rejected at `create()` time, never reaches the runner | N/A |
| Malformed `time_of_day` | Rejected at `create()` time | N/A |
| Missing AI provider configuration | Same honest failure as the interactive path - no entry | `last_run_at` updated |
| Dashboard read failure for schedules | Isolated to the Schedules tab alone, exactly like every other panel | N/A |

## 15. Dashboard Schedules Tab

**Decision: include it - low-risk, consistent with every existing
pattern, clearly useful.** A new `DashboardReadModel.get_schedules()`
method calls the same `ScheduleStore.list_all()`/`count()` methods
already needed for the `list schedules` tool - no new store API surface
is added specifically for the dashboard. Columns: ID, Name, Query preview
(same 120-character truncation convention), Time of Day, Enabled,
Last Run At, Created At. No "next due" countdown is computed or
displayed in v1 (would require duplicating the runner's own "due" logic
in the UI layer for cosmetic benefit only - deferred, not essential).

**Explicitly excluded, per the authorizing instructions:** add/edit/
delete/enable/disable/run-now/retry controls, a notification toggle, or
any command input - the tab is exactly as read-only as the other five.
`ui/dashboard_app.py` gains no new import of `CommandRouter`,
`ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, `AIReasoningEngine`,
`WebSearchProvider`, or `ScheduleStore`'s own mutating methods
(`create`/`enable`/`disable`/`claim_due`) - only `get_schedules()`/
`count()` are ever called from the dashboard side, structurally provable
the same way Phase 19/20 already proved the equivalent guarantee for
every other tab.

## 16. Master Specification Reconciliation

Phase 21 is honestly a **narrow, GREEN-only scheduled information-task
slice**: the first proactive, unattended Jarvis behavior, built entirely
on infrastructure already proven safe (the Inbox, the dashboard's
independent-process pattern, the existing tool/approval pipeline). It is
**not** a general scheduler, not a background-agent framework, not a
notification system, not a phone client, not a task queue, not a
Core service, not a workflow scheduler, not a Research Agent, not
autonomous browsing, not arbitrary command automation, not dashboard
interactivity, and not voice-assistant behavior.

## 17. Adversarial Planning Review

- **Introducing unattended execution too early?** No - it is the
  narrowest possible unattended action (one hard-coded, GREEN, read-only-
  in-effect action), gated by an explicit YELLOW confirmation at
  creation time.
- **Does Phase 20 provide enough durable destination support?** Yes -
  proven end-to-end; this plan adds nothing to the Inbox's own schema.
- **Are CLI schedule commands safer than dashboard creation?** Yes -
  reuses the entire existing tool/approval pipeline unmodified; dashboard
  creation would have required either a second write-authority runtime
  or reopening the deferred Core-service question.
- **Does the runner execute arbitrary command strings?** No - it never
  constructs or parses a command string at all; it calls Python
  functions directly (§7).
- **Does a stored scheduled query gain too much authority?** No - it is
  used only as a search parameter and as scanned `UNTRUSTED` context
  text; it is never given `user_message`/live-input trust (§7 - the
  central finding of this review).
- **Is stored query text incorrectly treated as live user input?**
  Explicitly avoided - this is the specific gap §7 closes.
- **Can two runners create duplicate entries?** Closed by the atomic SQL
  claim (§13), with an honestly-flagged fallback if that proves
  impractical.
- **Can failed runs retry endlessly?** No - `last_run_at` is set at
  claim time, before the run's own success/failure is known, so a
  failure never re-fires the same day.
- **Can missed runs backfill too much stale work?** No - "due" is a
  same-day catch-up check only; a machine off for a week produces
  exactly one run on the day it comes back, never a backlog.
- **Does host local time create hidden problems?** DST/clock changes are
  handled by the OS's own local-time conversion, not manual arithmetic -
  the one remaining risk (the `'localtime'` SQL modifier's exact
  behavior) is explicitly flagged for empirical verification, not
  assumed.
- **Are audit events metadata-only?** Yes - query/body text is never
  logged, only schedule id, counts, and error messages (§12).
- **Does the dashboard remain read-only?** Yes - only two read methods
  are ever called from the dashboard side, structurally provable.
- **Building a task queue under another name?** No - exactly one
  hard-coded action, no `action_type` column, no dispatch table (§4).
- **Sneaking in notifications?** No - nothing pushes, emails, or alerts;
  the Inbox and its dashboard tab remain the only visibility mechanism,
  exactly as before.
- **Creating pressure for read/unread inbox mutation?** No new pressure
  beyond what already existed after Phase 20 - this plan adds no
  notification concept that would create such pressure.
- **Is the scope still one action type?** Yes, confirmed throughout.
- **Does this genuinely reduce Nathan's workload?** Yes - directly: a
  result appears without him touching the keyboard, the concrete
  "Jarvis feels alive" moment named in the prior architectural review.

No finding in this pass requires a design change.

## 18. Batch Plan

### Batch 1 — Schedule Storage, Tools, and CLI Grammar

- **Purpose**: the durable table/store and the four CRUD tools, fully
  routed through the existing, unmodified pipeline.
- **Production files**: `storage/models.py` (extended - `ScheduleEntry`),
  `scheduling/__init__.py` (new), `scheduling/schedule_store.py` (new),
  `tools/builtin/schedule_create_tool.py`, `schedule_list_tool.py`,
  `schedule_enable_tool.py`, `schedule_disable_tool.py` (new),
  `core/command_router.py` (extended - four new prefixes/matchers),
  `security/security_manager.py` (extended - three new rules, §9),
  `main.py` (extended - construct `ScheduleStore`, register four tools).
- **Test files**: `tests/unit/test_schedule_store.py`,
  `tests/unit/test_schedule_tools.py` (new), `tests/unit/test_command_router.py` (extended).
- **Invariants protected**: no update/delete method exists beyond
  enable/disable; `time_of_day`/`query` validated at creation; YELLOW
  classification for create/enable/disable, GREEN for list, confirmed
  via the real `SecurityManager`; no collision with any existing prefix.
- **Explicit non-goals**: no runner, no dashboard, no claim logic tested
  end-to-end yet (unit-level `claim_due` correctness only).
- **Verification**: focused tests, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files above.

### Batch 2 — Runner, Due/Claim Logic, Execution Path

- **Purpose**: `scheduler.py`, the narrow trust-safe execution helper
  (§7), and the atomic claim mechanism, verified against real SQLite
  concurrency.
- **Production files**: `scheduler.py` (new, repo root),
  `scheduling/scheduled_summary_runner.py` (new - the narrow helper).
- **Test files**: `tests/unit/test_schedule_due_logic.py`,
  `tests/unit/test_scheduled_summary_runner.py` (new).
- **Invariants protected**: due/not-due/disabled schedules behave
  exactly per §14's table; the atomic claim (or its verified fallback)
  prevents duplicate runs under simulated concurrent access; the
  trust-origin resolution (§7) is proven directly - the stored query
  never reaches an unscanned prompt slot; zero `ApprovalManager`/
  `WorkflowEngine` involvement anywhere in the runner.
- **Explicit non-goals**: no dashboard, no README.
- **Verification**: focused tests, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files above.

### Batch 3 — Dashboard Schedules Tab, End-to-End, Adversarial, Closure

- **Purpose**: the read-only dashboard consumer, real-SQLite end-to-end
  proof, the adversarial sweep from §17/the authorizing instructions,
  documentation, closure.
- **Production files**: `dashboard/read_model.py`, `dashboard.py`,
  `ui/dashboard_app.py` (all extended - Schedules tab and read path only).
- **Test files**: `tests/unit/test_dashboard_read_model.py`,
  `tests/unit/test_dashboard_app.py` (extended),
  `tests/integration/test_scheduled_summary_end_to_end.py` (new).
- **Documentation**: `README.md` (Phase 21 section), `docs/phase_21_implementation_plan.md`
  (tracked at closure), `docs/phase_21_completion_report.md` (new).
- **Verification commands**: the new end-to-end file, then full
  `poetry run pytest -q`, `git diff --check`, `git status`.
- **Commit boundary**: one closure commit. `dashboard_test.txt` remains
  untouched and unstaged throughout.

## 19. Testing Plan (Consolidated)

**Batch 1**: table creation via `initialize_database`; `create`/`list_all`/
`get`/`enable`/`disable`/`count` behavior; query/time-of-day validation
(rejects empty query, rejects malformed time); disabled schedules
excluded from "due" candidates; public API contains no update/delete/
arbitrary-field method (structural test, mirroring `InboxStore`'s own);
no `action_type` or command-string column exists; persistence across a
real file-backed reopen; CLI grammar parses all four commands and
collides with none of the existing prefixes (regression-tested); YELLOW/
GREEN classification confirmed via the real `SecurityManager`; a
`tool_call` audit event fires for create/enable/disable, confirming no
new audit code is needed for CRUD.

**Batch 2**: due-calculation correctness across enabled/disabled/already-
run-today/not-yet-time cases; same-day catch-up proven; no multi-day
backfill proven (a schedule "missed" for 3 days runs exactly once, not
three times); at-most-once-per-local-date proven; atomic claim success
and claim-fails-when-already-claimed proven (a second `claim_due` call
for the same schedule on the same day returns `False`); a direct proof
that the stored query never appears in an unscanned prompt slot (asserting
against the fake AI provider's own received request content); scheduled
summary success creates exactly one inbox entry with
`source_type="scheduled_web_search_summary"`; every failure path (§14)
creates zero entries; zero `ApprovalManager`/`WorkflowEngine` construction
anywhere in the runner (structural import-absence test); the runner
exposes a single-pass entry point usable in tests without an infinite loop.

**Batch 3**: dashboard read-model lists real schedules; Schedules tab
renders real data, honest empty state, isolated error state; dashboard
never calls `ScheduleStore.create`/`enable`/`disable`/`claim_due`
(structural + spy-based proof, mirroring Phase 20's `InboxStore.append()`
spy exactly); dashboard refresh sees a schedule change made by another
session; a full real-SQLite, fake-search-provider, fake-AI-provider
end-to-end proving a due schedule produces exactly one inbox entry and a
disabled/not-due one produces none; the adversarial sweep (§20 of the
authorizing instructions) proving stored schedule query content -
prompt injection, fake commands, fake tool-call JSON, malicious URLs,
control characters, extreme length - remains inert exactly as Phase 20
already proved for interactive inbox entries; a simulated two-runner
race proving only one claim succeeds.

## 20. Final Summary

- **Final schedule table/model**: `schedules` / `ScheduleEntry` (`id`,
  `name`, `query`, `time_of_day`, `enabled`, `last_run_at`, `created_at`)
  - the first mutable (non-append-only) durable table in the project,
    explicitly disclosed as such.
- **Final `ScheduleStore` API**: `create`, `list_all`, `get`, `enable`,
  `disable`, `count`, `claim_due` - seven methods, no update/delete/
  arbitrary-field method.
- **Final CLI grammar**: `schedule web search summary for <query> at
  <HH:MM>` / `list schedules` / `enable schedule <id>` / `disable
  schedule <id>` - implemented as four ordinary tools through the
  unmodified `CommandRouter`/`ToolExecutor`/`SecurityManager`/
  `ApprovalManager` pipeline.
- **Final runner architecture**: `scheduler.py`, a fourth independent
  composition root (mirroring `dashboard.py`), polling every 60 seconds,
  never importing `CommandRouter`/`ToolExecutor`/`ApprovalManager`/
  `WorkflowEngine`.
- **Final due semantics**: enabled, `time_of_day` reached in host local
  time, and `last_run_at`'s local calendar date is not today - same-day
  catch-up, no multi-day backfill, at most once per local date.
- **Final duplicate/race guard**: one atomic SQL `UPDATE ... WHERE ...`
  claim, rowcount-checked, with an explicitly considered simpler
  read-then-write fallback if the SQL construction proves impractical
  (final choice deferred to Batch 2, per direct empirical verification).
- **Final failure semantics**: only a genuinely successful run creates an
  inbox entry; every failure is audited, never faked as success; a
  claimed-then-failed run does not retry the same day.
- **Final trust-origin decision**: the stored query never occupies the
  unscanned `user_message` slot; it drives the search call and appears
  only inside the already-injection-scanned `UNTRUSTED` context text,
  via a new, narrow helper module - `_handle_web_search_summary_request`
  and `ai/web_search_ingestion.py` are both left completely unmodified.
- **Final privacy/query decision**: store the literal query, consistent
  with Phase 20's own reasoning; scheduler-produced inbox entries use the
  distinct `source_type="scheduled_web_search_summary"`.
- **Final dashboard Schedules decision**: included, read-only, reusing
  `ScheduleStore.list_all()`/`count()` with no new store API added
  specifically for it.
- **Final audit/observability decision**: zero new code for CRUD (the
  existing `tool_call` event already covers it); three new, narrow,
  metadata-only runner events (`scheduled_summary_claimed`/`_succeeded`/
  `_failed`).
- **Final batch sequence**: (1) storage/tools/CLI grammar; (2) runner/
  due/claim/execution path; (3) dashboard tab/end-to-end/adversarial/
  closure.
- **Explicit Phase 21 non-goals**: every item listed in §2, restated in
  full at closure.
- **Likely future pressure points**: a notification layer now has a real
  first candidate to point to (an unattended, scheduled result); the
  `'localtime'` SQL claim mechanism's real-world verification result
  (§13) should be recorded in the completion report either way; a second
  schedule action type, if ever proposed, is a deliberate, separately-
  reviewed decision - not something this phase's schema quietly enables.
