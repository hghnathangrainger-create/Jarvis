# Phase 98 Safety Interlock Planning Gate — Durable Approved-to-Resume Handoff (Final Amendment)

Status: **planning gate only**. No production or test code changed.
This final amendment resolves the three remaining implementation
blockers identified against the prior draft (`b824e6f`): the
undefined-but-load-bearing process-exclusivity assumption; the
insufficiently audited reliability of `WorkflowHistoryStore.latest_status_for()`
as a reconciliation signal; and the missing durable, visible record of
a `CLAIM_INTERRUPTED` outcome. All three are resolved below using
direct, live code inspection - not assumption.

## 1. Enforced process model (Blocker 1)

### 1.1 Real, evidence-based process inventory

Directly traced every production call site of
`.approve(`/`.decline(`/`execute_approved(`/`WorkflowEngine.resume(`,
and inspected `main.py`, `ui/cli.py`, `dashboard.py`,
`ui/dashboard_app.py`, `dashboard/read_model.py`, and `scheduler.py`:

- **Exactly one code path** (`ui/cli.py`'s `_handle_approval()`, inside
  `JarvisCLI.run()`'s single-threaded, blocking `while True: input()`
  loop) ever calls the approve-to-resume sequence in production. No
  threading/asyncio exists anywhere near this path.
- **`dashboard.py`/`ui/dashboard_app.py`/`dashboard/read_model.py`** are
  confirmed, by direct inspection of every write-method call site
  (`.save(`, `.update(`, `.delete(`, `.create(`, `record_*`, `.approve(`,
  `.resume(`), to be **100% read-only** - they never touch
  `ApprovalManager`/`WorkflowEngine` at all.
- **`scheduler.py`** is a separate process that writes only to
  `ScheduleStore`/`InboxStore` - it never calls
  `ApprovalManager.approve()`/`claim_for_resume()` or
  `WorkflowEngine.resume()`. Its own execution of a due, scheduled
  action is a **different, already-established trust boundary**:
  Jarvis's own existing schedule design requires approval once, at
  schedule-*creation* time (a YELLOW action, per
  `security/security_manager.py`'s own "schedule web search" rule);
  the scheduled run itself is a pre-authorized, repeated, automatic
  action that never re-enters the per-action YELLOW approval flow.
  `scheduler.py` is therefore correctly, structurally exempt from this
  correction's own guard - it is not a second claimant of anything this
  interlock protects.
- **No single-instance enforcement exists today** - confirmed by
  searching for any PID file, OS lock, or documented policy; none
  exists.

**Selected: Option A - enforced single-instance database guard.** The
real, intended, documented deployment is exactly one Jarvis CLI process
per database; Option B (claim tokens/liveness for genuinely concurrent
execution-capable processes) is rejected as solving a problem the real
architecture does not have.

### 1.2 Exact guard design

A new, narrow, singleton-row table, `ProcessInstanceLock` (mirroring
`ProjectState`'s own established singleton-row convention), scoped
entirely within the same SQLite database file every other store
already uses (so it is automatically scoped per `DATABASE_PATH` - two
different configured database files never contend, with zero extra
scoping logic required):

- `owner_pid: int` - the OS process id of the current holder.
- `owner_token: str` - a fresh UUID generated at acquisition, guarding
  against the (extremely rare) case of PID reuse by an unrelated
  process across a reboot.
- `acquired_at: datetime`.
- A `UNIQUE` constraint on a fixed singleton key ensures at most one
  row can ever exist, giving true atomic "only one owner" semantics at
  the database level - not an in-memory flag.

**Exact acquisition** (`acquire_process_guard()`, in a new, narrow
module): attempt an `INSERT`; on success, the caller holds the guard,
represented by an opaque token object (no other code can construct or
forge one, so a caller cannot call the recovery pass without a
genuine, successful acquisition - a structural, not merely
conventional, guarantee). If a row already exists, perform the
**stale-owner liveness check**: determine whether a process with the
recorded `owner_pid` is currently running on this machine (a small,
platform-specific liveness check - POSIX via `os.kill(pid, 0)`,
Windows via `ctypes`-based `OpenProcess` - a narrow, bounded utility
function, not a distributed system). If the recorded owner is
confirmed dead, delete the stale row and retry the `INSERT` once
(recovering from an abnormal prior termination). If the recorded owner
is confirmed alive (or liveness cannot be determined), acquisition
**fails**, and `main.py` refuses to start, reporting that Jarvis
appears to already be running against this database.

**Release**: `main.py`'s own top-level `try/finally` around `cli.run()`
deletes the row (keyed by `owner_token`) on any clean exit path,
including normal completion and a handled `KeyboardInterrupt`.

**Startup ordering** (`main.py`'s `build_orchestrator()`): the guard is
acquired as the **first** action, strictly before `reload_pending()`,
`reload_paused()`, or the new CLAIMED-reconciliation pass (Section 3)
- all of which now require the caller to present the guard token,
making it structurally impossible to run recovery without first
acquiring it.

**Read-only components are unaffected**: `dashboard.py` never calls
`acquire_process_guard()` at all (confirmed structurally separate,
Section 1.1) - it continues to read the same database file with zero
change, protected only by the pre-existing WAL/busy-timeout
configuration, exactly as today.

**Test harnesses**: every existing test constructs `ApprovalManager`/
`WorkflowEngine` directly, bypassing `main.py`'s own
`build_orchestrator()` entirely - the guard is acquired only by
`main.py`'s own explicit call, never implicitly required by any
manager's constructor, so the entire existing test suite is
unaffected. Dedicated new tests exercise the guard module itself in
isolation (Section 12).

### 1.3 Mandatory rule, honored

"Any CLAIMED row found at startup is definitionally from a crashed
process" now holds **only because** runtime exclusivity is technically
enforced (via the guard) immediately before the reconciliation pass
that relies on this assumption - the assumption is no longer
documentation-only.

## 2. Workflow-history terminal-evidence audit (Blocker 2)

Directly inspected `workflow/workflow_history_store.py` in full and
every writer in `workflow/engine.py`.

1. **Exact workflow identity**: `workflow_id`, a fresh `uuid.uuid4()`
   string generated once per `run()` call
   (`WorkflowEngine._new_workflow_id()`).
2. **Uniqueness**: a fresh UUID4 per workflow attempt; old workflow ids
   are never reused for a different workflow.
3. **Exact terminal status values**: `workflow_completed` (success) and
   `workflow_stopped` (the single STOP-only outcome for any failure,
   decline, or block - there is no separate "workflow_failed" event
   name; confirmed against `KNOWN_WORKFLOW_STATUSES`'s own fixed
   seven-entry vocabulary).
4. **Writers**: `_run_from()`'s own success path calls
   `_record_history(_EVENT_WORKFLOW_COMPLETED, ...)` as its final
   action, after every step has genuinely, sequentially executed;
   `_stop()` calls `_record_history(_EVENT_WORKFLOW_STOPPED, ...)` as
   its final action, after the failing step's own real `ToolResult` is
   already known.
5. **Written only after a real terminal result exists**: yes -
   confirmed by the code's own sequencing; neither call is reachable
   before the real, synchronous outcome is already determined.
6. **Cannot be written before tool execution/verification finishes**:
   confirmed - `self._executor.execute(...)` (the real, blocking tool
   call) always precedes any terminal history write for that step/workflow.
7. **Duplicate or contradictory terminal rows**: not possible under
   normal operation - `resume()` cannot be invoked twice for the same
   `workflow_id` (raises `WorkflowError`), and `_run_from()`/`_stop()`
   each write their own terminal event at most once per workflow
   lifecycle, which never repeats.
8. **Ordering**: `latest_status_for()` orders by
   `created_at.desc(), id.desc()`.
9. **Timestamp ordering alone is not used**: the `id` column (an
   autoincrementing primary key) is an explicit tiebreaker, giving a
   true, unambiguous insertion-order signal even when two events share
   an identical stored timestamp.
10. **A later non-terminal row cannot obscure a terminal one**: for a
    given `workflow_id`, nothing is ever written after its own terminal
    event - the workflow is over. Structurally impossible.
11. **Failed history insertion does not change execution**: confirmed
    (`_record_history()`'s own try/except swallows any write failure,
    per its own docstring) - this is exactly why *absence* of a
    terminal row is not reliable evidence, but has no bearing on the
    reliability of *presence*.
12. **Old rows never share a workflow identity with a new workflow**:
    confirmed (UUID4, never reused).

### Reconciliation contract (final)

**Accepted**: an exact `workflow_completed` record for the *same*
`workflow_id` reconciles `CLAIMED → CONSUMED`; an exact
`workflow_stopped` record for the *same* `workflow_id` also reconciles
`CLAIMED → CONSUMED` (a known, definite terminal outcome - not
uncertain, regardless of whether that outcome was success or failure).
**Not accepted, and not relied upon anywhere in this design**: absence
proving non-execution; a generic (non-workflow-scoped) audit event;
tool-level audit records alone; inference from paused-workflow deletion
alone; or a matching postcondition value alone (Batch 1's own
`reconcile_phase_update()` remains a *separate*, narrower, only-later
integrated mechanism for its one specific future consumer, per Section
9's own compound-integration note - never a substitute for this
general rule).

`latest_status_for()` is confirmed reliable for this exact purpose by
points 1-12 above; **no corrected query is required** - it is used
unmodified.

## 3. CLAIM_INTERRUPTED durable visibility (Blocker 3)

Directly inspected `approval/approval_history_store.py` in full:
`ApprovalHistoryEntry` is one row per `request_id` (a request is
recorded once, as "pending", and later updated **in place** - never a
second row for the same request), with a fixed, small
`KNOWN_APPROVAL_STATUSES = ("pending", "approved", "declined", "expired")`
vocabulary used by the dashboard's own status breakdown.

**Selected: Option A - approval-history interruption event.** A new
method, `record_interruption(*, request_id, interrupted_at, reason=None)`,
mirrors `record_timeout()`'s exact shape: looks up the existing row by
`request_id`, and updates it to a new, fixed status value,
`"interrupted"` (added to `KNOWN_APPROVAL_STATUSES` so the dashboard's
own breakdown honestly includes it), with `decided_by="claim_interrupted"`
and a **fixed, trusted, canned `reason` string** (never derived from
model output, tool output, or any unbounded text) stating plainly that
execution was claimed, its outcome could not be confirmed after a
restart, and the approval cannot be reused.

**Idempotency**: because the table has exactly one row per
`request_id`, calling `record_interruption()` more than once (e.g.
across repeated startup-recovery attempts after another crash *during*
recovery itself) can never create a duplicate row. For genuine,
value-level idempotency (not merely row-count idempotency), the method
is a no-op if the row's `status` is already `"interrupted"` - it never
overwrites the original `interrupted_at` timestamp on a later,
redundant call.

**Properties satisfied**: durable (a real database row); bounded (one
fixed status string plus one fixed, canned reason - no free-form or
unbounded content); identifies the exact approval via `request_id`
(and, for a workflow-linked approval, the same `request_id` is already
present on the retained `paused_workflow_state` row, Section 5,
cross-referencing the exact workflow); states uncertainty and prohibits
replay via its own fixed reason text; idempotent; survives restart (a
real row, not in-memory); remains inspectable via the existing
`show approval history` / `ApprovalHistoryTool` read path, with the
exact same visibility as any other status - **this specific claim is
flagged, honestly, as needing direct confirmation in Batch 2** against
the tool's own real display code (not verified line-by-line in this
planning gate); if that code turns out to special-case or reject
unknown status strings, a small, narrow, additive display fix is
explicitly in scope for that same batch, not a surprise discovered
later. Never authorizes execution - `record_interruption()` never
touches `pending_approval_state`, `ApprovalManager`, or any execution
code path.

## 4. Approval-history repair ordering (final)

Exact, deterministic startup sequence (matching the task's own
required order, confirmed coherent given the dependencies above):

1. Acquire the exclusive execution-process guard (Section 1) - refuses
   to proceed if a live owner already holds it.
2. Repair approval/handoff consistency: for every row whose
   `handoff_status` is `APPROVED_UNCONSUMED`/`CLAIMED`/`CONSUMED`
   (i.e., every row that was genuinely approved, regardless of its
   current sub-state), idempotently backfill an `approval_history`
   "approved" entry if one is not already present (Section 5 of the
   prior draft, unchanged) - this step depends only on the *immutable*
   fact "was this approved," never on the CLAIMED-reconciliation
   outcome that has not run yet.
3. Reconcile inherited `CLAIMED` rows (Section 2's reconciliation
   contract): each becomes `CONSUMED` (exact terminal evidence found)
   or `CLAIM_INTERRUPTED` (no exact evidence found).
4. Append any missing, idempotent interruption audit events (Section 3)
   for whatever newly landed in `CLAIM_INTERRUPTED` during step 3 -
   sequenced after step 3 specifically because it depends on that
   step's own outcome.
5. Rebuild the in-memory pending view (`reload_pending()`'s own
   existing, unchanged logic) and a new, separate, read-only
   approved-unconsumed view (never auto-claimed).
6. Only then does `main.py` proceed to `cli.run()`, accepting user
   input.

**Crash-during-repair recoverability**: every step above is idempotent
individually (guard re-acquisition after this same process's own
restart; history repair via update-in-place; CLAIMED reconciliation via
the same deterministic evidence check; interruption-event recording via
update-in-place) - a crash at any point during this sequence is safely
recovered simply by re-running the entire sequence, from step 1, on the
next launch. No step depends on a partially-completed prior run leaving
any transient, unrecoverable state.

## 5. Final transition matrix

| Transition | Status |
|---|---|
| `PENDING → DECLINED` | Allowed (unchanged) |
| `PENDING → EXPIRED` | Allowed (unchanged) |
| `PENDING → APPROVED_UNCONSUMED` | Allowed (the fix) |
| `APPROVED_UNCONSUMED → CLAIMED` | Allowed (CAS, exactly one claimant) |
| `CLAIMED → CONSUMED` | Allowed, when exact terminal workflow evidence exists (Section 2), or when a non-workflow tool call's own synchronous outcome is already known |
| `CLAIMED → CLAIM_INTERRUPTED` | Allowed, only when inherited across an *enforced* exclusive-startup boundary (Section 1) with no exact terminal evidence (Section 2), **or** synchronously, when the claimed handoff discovers its own paused workflow missing/invalid before any tool executes (reuses this same bucket - no new state) |
| `CLAIM_INTERRUPTED → *` | **Rejected** - always terminal |
| `CONSUMED → *` | **Rejected** - always terminal |
| `APPROVED_UNCONSUMED → PENDING` | **Rejected** |
| `CLAIMED → APPROVED_UNCONSUMED` | **Rejected** |
| `CLAIM_INTERRUPTED → CLAIMED` | **Rejected** |
| `CONSUMED → CLAIMED` | **Rejected** |
| `DECLINED`/`EXPIRED → APPROVED_*` | **Rejected** |
| Any transition altering `approved_phase_value`-equivalent tool input | **Rejected** - no transition in this table ever writes to `tool_input_json` |

Missing/invalid paused workflow after a claim transitions directly to
`CLAIM_INTERRUPTED` - the smallest state model already covers this
case; no separate `TERMINAL_INVALID` state is introduced.

## 6. Process guard and read-only components (summary)

- **Interactive CLI**: acquires the guard at startup, holds it for its
  entire lifetime, releases on clean shutdown.
- **Test harnesses**: unaffected - never call the guard's acquisition
  function unless a test targets the guard module directly.
- **Read-only dashboard**: unaffected, structurally exempt (never calls
  the guard or any approval/workflow write method).
- **Scheduler**: unaffected, structurally exempt - it writes only to
  `ScheduleStore`/`InboxStore`, never to `pending_approval_state`/
  `paused_workflow_state`; its own execution of a due schedule remains
  the separate, pre-existing, approved-once-at-creation trust boundary
  documented in Section 1.1, unrelated to this interlock.
- **Multiple database files**: each has its own, independent guard row,
  since the guard lives inside the same file every other store already
  uses - no cross-file contention possible.
- **Read-only commands** (e.g. "show approval history"): unaffected -
  they never call the guard, exactly like the dashboard.

## 7. Existing YELLOW workflow impact, backward compatibility, migration

Unchanged in substance from the prior draft (its own Sections 13-15):
one new column (`pending_approval_state.handoff_status`) plus one new
table (`process_instance_lock`) plus one new status string
(`"interrupted"` in `ApprovalHistoryEntry.status`) - all additive,
migrated via the same guarded `ALTER TABLE`/`create_all()` pattern
already proven for `episodic_memories.category`; existing rows default
safely; `PROJECT_STATE_UPDATE_FOCUS`/`PHASE`/`SCHEDULE_ENABLE`/`DISABLE`
guarantees and non-guarantees restated precisely as **"durable
approved-to-claim handoff safety,"** never "complete crash-safe
execution."

## 8. Future Phase 98 compound integration

Unchanged in conclusion: the future compound consumer calls
`claim_for_resume()` like any other capability, then locates its
`CompoundWorkflowProgress` row; it may additionally, in its own
separately-approved batch, narrow a `CLAIM_INTERRUPTED` compound
workflow using `reconcile_phase_update()`'s own exact evidence - a
capability-specific refinement layered *on top of* this general
interlock, never a substitute for it.

## 9. Selected outcome

**Outcome A - three-batch interlock is implementation-ready.**

## 10. Final batch structure

- **Batch 1 - Schema, migration, and exclusive-process primitive**:
  `pending_approval_state.handoff_status` column + migration;
  `process_instance_lock` table + `acquire_process_guard()`/
  `release_process_guard()` + stale-owner liveness check;
  `PendingApprovalHandoffStatus` enum; `PendingApprovalStore` CAS
  transition/claim methods. No `ApprovalManager`/orchestrator behavior
  change yet - purely additive primitives, fully unit-tested in
  isolation.
- **Batch 2 - ApprovalManager lifecycle, history consistency, and
  startup recovery**: `approve()`'s new transition;
  `claim_for_resume()`; the full deterministic startup sequence
  (Section 4); `record_interruption()` +
  `KNOWN_APPROVAL_STATUSES` update; `WorkflowEngine._try_reconstruct_paused_workflow()`'s
  three-way retention refinement; confirmation (and, if needed, a
  small fix) that `ApprovalHistoryTool`'s existing display path shows
  `"interrupted"` truthfully. Complete regression for every existing
  YELLOW capability.
- **Batch 3 - Orchestrator integration and full closure**:
  `execute_approved()` calls `claim_for_resume()` first and marks
  `CONSUMED` after execution; explicit, documented single-process
  statement shipped in module docstrings; full end-to-end crash-window
  tests; full three-environment regression; closure.

## 11. Updated required tests

All 49 items the task requires map onto the three batches: exclusive-
process-ownership and terminal-history-evidence tests (Batch 1, plus
Batch 1's own share of compatibility tests); interrupted-visibility,
startup-ordering/idempotency, and per-capability regression tests
(Batch 2); orchestrator wiring, full existing-YELLOW-workflow
end-to-end tests, and full-suite/Ruff verification (Batch 3).

## 12. Updated acceptance criteria

All required tests pass; the guard prevents a genuine second
execution-capable process while never blocking the dashboard/scheduler;
`latest_status_for()`-based reconciliation is exercised against real,
distinct workflow ids proving no cross-workflow leakage; `record_interruption()`
is proven idempotent (row count and value); every existing YELLOW
capability's own suite passes; fresh and migrated databases behave
identically; Ruff and `git diff --check` clean.

## 13. Updated risks and mitigations

- **Risk**: cross-platform PID-liveness checking has a subtle bug.
  **Mitigation**: a narrow, isolated utility function, its own
  dedicated tests per platform behavior, never load-bearing beyond
  stale-guard recovery.
- **Risk**: `ApprovalHistoryTool`'s existing display path silently
  hides an unrecognized status. **Mitigation**: explicitly named as a
  Batch 2 confirmation-or-fix item, not assumed away.
- **Risk**: PID reuse coincides with a stale guard row. **Mitigation**:
  the `owner_token` UUID is checked alongside the PID as an additional,
  cheap safeguard, documented as reducing (not eliminating) this
  already-rare risk.

## 14. Updated stop conditions

Stop before implementation if: the single-process rule remains
documentation-only (i.e., the guard is not actually enforced before
recovery runs); a second process could run the reconciliation pass
while another genuine claimant is live; stale-owner detection cannot be
determined safely; `latest_status_for()` cannot provide exact,
workflow-scoped positive terminal evidence; a terminal row could be
written before real completion; `CLAIM_INTERRUPTED` remains invisible
through a real, confirmed bounded read path; interrupted-event
insertion can duplicate or produce inconsistent values across repeated
calls; startup ordering is not deterministic or not idempotently
recoverable from a crash; approval history could ever authorize
execution; old approved arguments could change; a terminal handoff
could become claimable; or the correction is described as exactly-once
tool execution rather than durable approved-to-claim handoff safety.

## 15. Formal final amendment conclusion

All three blockers are resolved with concrete, code-grounded designs:
an enforced, database-backed, singleton-row process guard (justified by
a complete inventory of every real process that touches the shared
database); an exhaustive, twelve-point audit proving
`latest_status_for()` is safe as a one-directional, positive-only
reconciliation signal, with no corrected query needed; and a durable,
idempotent, bounded interruption record reusing the existing
`ApprovalHistoryStore`'s own established update-in-place pattern. The
handoff correction is recommended as a three-batch, large/risky future
phase - not implemented in this planning gate.
