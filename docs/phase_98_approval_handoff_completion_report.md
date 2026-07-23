# Approval-to-Resume Handoff Interlock — Formal Completion Report

Status: **the interlock is formally closed** as of this report. Phase 98
itself (live compound selection/execution) remains a separate, open,
still-blocked initiative - this report closes only the durable
approval-to-resume handoff safety mechanism, not Phase 98's own
remaining batches.

## 1. Original crash gap

Discovered during Phase 98's own planning (`docs/phase_98_implementation_plan.md`,
Section 3): `ApprovalManager.approve()`/`_decide()` durably decided a
request and deleted its `pending_approval_state` row in one call,
**before** the caller (the CLI, via `execute_approved()`) ever invoked
`WorkflowEngine.resume()`. A process crash in that exact window left
`paused_workflow_state` present but its linked approval no longer
"pending," causing `reload_paused()`'s own revalidation to invalidate
the entire approved-but-not-yet-executed workflow on restart -
silently, for **every** existing YELLOW capability, workflow-linked or
not, since Phase 6/15/27. This was a system-wide gap, not specific to
any one capability or to the (still-unimplemented) compound workflow
that originally prompted its discovery.

## 2. Batch 1 and Batch 2 commits

- `b38559c` — Add approval handoff lock and CAS foundations (Interlock
  Batch 1): `runtime/process_lock.py`'s `ExecutionProcessLock`, the
  additive `pending_approval_state.handoff_status` column and guarded
  migration, `PendingApprovalHandoffStatus`, and
  `PendingApprovalStore`'s six CAS transition primitives. No live
  wiring.
- `0122bae` — Integrate durable approval handoff lifecycle (Interlock
  Batch 2): live OS-lock wiring in `main.py`
  (`start_execution_session()`/`reconcile_claimed_handoffs()`), the
  durable approve/decline/expire lifecycle (no longer deleting the
  pending row on decision), claim-before-resume wired into
  `JarvisOrchestrator.execute_approved()`, terminal
  `CLAIMED -> CONSUMED` transitions, exclusive startup reconciliation of
  inherited `CLAIMED` rows using positive-only workflow-history
  evidence, and `CLAIM_INTERRUPTED` audit visibility.

## 3. Batch 3 corrections

Batch 3's own mandatory audit found that Batch 2's `APPROVED_UNCONSUMED`
retention, while durable, had **no reachable production path** to ever
continue such a workflow after a restart - `claim_for_resume()` was
callable only from `execute_approved()`, itself reachable only with a
live, in-process `JarvisResponse` that cannot survive a restart. Two
corrections were made:

1. **Narrow automatic startup continuation added** (`main.continue_approved_unconsumed_workflows()`),
   claiming and resuming every durable `APPROVED_UNCONSUMED` row through
   the exact same trusted `claim_for_resume()`/`WorkflowEngine.resume()`
   path live execution already uses - no new approval, no AI/model call,
   no parser/grounding call, exact persisted inputs only.
2. **Two genuine pre-existing defects in the already-accepted Batch 2
   code were found and fixed** while implementing continuation (Section
   10 below) - both were invisible to Batch 2's own test suite because
   they only manifest when a *second*, freshly-restarted
   `ApprovalManager`/`WorkflowEngine` instance pair reconstructs an
   already-`APPROVED_UNCONSUMED` row, a scenario Batch 2 correctly
   deferred (no live wiring existed yet to exercise it).

## 4. OS lock design

Unchanged since Batch 1: `runtime/process_lock.py`'s
`ExecutionProcessLock` wraps a sidecar file
(`<canonical_database_path>.jarvis.lock`) with a genuine, kernel-held,
non-blocking exclusive lock - `fcntl.flock()` on POSIX,
`msvcrt.locking()` on Windows - proven against real subprocesses
(`tests/integration/test_process_lock_subprocess.py`). Acquired only in
`main.start_execution_session()`, held across the complete interactive
CLI lifetime via `try`/`finally`, and released automatically by the
operating system on any process termination, including a crash.
`build_orchestrator()` itself remains completely lock-free and
unmodified throughout all three batches, preserving its 100+ existing
test callers (including two that call it twice in one process to
simulate a restart).

## 5. Scheduler limitation

Documented, unchanged, and never silently expanded across all three
batches: `scheduler.py` is a genuinely separate, execution-capable
process that never acquires the execution lock. **Concurrent scheduler
and execution-capable-CLI use of the same database remains explicitly
unsupported.** The interlock guarantees only approval/workflow handoff
ownership - never whole-database single-writer safety. Scheduler safety
remains a separate, deferred, future trust-boundary problem. No
scheduler production code was changed in any interlock batch (Batch 3
proof: `test_scheduler_never_imports_approval_manager_or_orchestrator`).

## 6. Handoff schema and transitions

One additive column, `pending_approval_state.handoff_status`
(`String(24)`, default `"pending"`), and `PendingApprovalHandoffStatus`:
`PENDING`, `APPROVED_UNCONSUMED`, `CLAIMED`, `CONSUMED`,
`CLAIM_INTERRUPTED`, `DECLINED`, `EXPIRED`. Allowed CAS transitions,
enforced structurally (no generic `transition(from, to)` API exists):

```
PENDING             -> APPROVED_UNCONSUMED   (approve)
PENDING             -> DECLINED              (decline)
PENDING             -> EXPIRED               (timeout / reload invalidation)
APPROVED_UNCONSUMED  -> CLAIMED                (claim_for_resume)
CLAIMED             -> CONSUMED              (mark_consumed)
CLAIMED             -> CLAIM_INTERRUPTED     (mark_claim_interrupted)
```

Every other combination is unreachable through the public store API -
never merely rejected at runtime.

## 7. Approval/history authority

The durable `handoff_status` column is the sole authority for execution
eligibility. `ApprovalHistoryStore` remains audit-only, updated
idempotently, and can never authorize execution by itself:
`claim_for_resume()`/`mark_consumed()` consult only
`PendingApprovalStore`, never `ApprovalHistoryStore`. History repair
(`main._repair_approval_history_consistency()`) only ever fills a
missing/still-"pending" gap - it never overwrites an already-decided
record contradictorily.

## 8. Claim-before-resume

`ApprovalManager.claim_for_resume()` performs one atomic, rowcount-
checked CAS (`APPROVED_UNCONSUMED -> CLAIMED`). Wired into
`JarvisOrchestrator._claim_and_resume_workflow()` - the single, shared,
capability-agnostic gate used identically by both the live approval
path (`execute_approved()`) and startup continuation
(`resume_approved_unconsumed_workflow()`). Exactly one claim can ever
succeed for a given request; every other concurrent or later attempt
observes `False` and executes nothing.

## 9. `APPROVED_UNCONSUMED` restart continuation

**Outcome B implemented.** `main.continue_approved_unconsumed_workflows()`,
called from `start_execution_session()` after lock acquisition, database
initialization, and full recovery/reconciliation, processes every
`APPROVED_UNCONSUMED` row (via `ApprovalManager.list_approved_unconsumed()`,
deterministic oldest-created-first order) and continues each through
`resume_approved_unconsumed_workflow()`. No new approval is ever
created; no AI/model call is ever made; the exact persisted, already-
approved `tool_input` is the only input ever used; a per-row failure
never corrupts or blocks any other row.

## 10. `CLAIMED` reconciliation

Unchanged in mechanism from Batch 2, reconfirmed this batch:
`main._reconcile_claimed_rows()` consults
`WorkflowHistoryStore.latest_status_for(workflow_id)` - the row's own
exact linked `workflow_id`, from its own durable metadata - for
positive-only terminal evidence (`workflow_completed`/`workflow_stopped`).
Exact terminal evidence -> `CONSUMED`; absent, non-terminal, or another
workflow's own unrelated terminal evidence -> `CLAIM_INTERRUPTED`.
Idempotent (a reconciled row is no longer `CLAIMED`, so a repeat pass
never revisits it). Never resumes, executes, or replays anything.

**Two defects found and fixed in this previously-accepted mechanism's
own supporting code** (both in `workflow/engine.py`, not in the
reconciliation function itself):

1. `_try_reconstruct_paused_workflow()` treated `APPROVED_UNCONSUMED`
   identically to `CLAIMED` (both "retain without resuming") - but
   `APPROVED_UNCONSUMED` must be fully reconstructed into
   `WorkflowEngine._paused` (exactly like an ordinary still-pending
   reload) for continuation to have anything to claim/resume at all.
   Corrected: only `CLAIMED` is now retained-without-reconstruction;
   `APPROVED_UNCONSUMED` falls through to full reconstruction.
2. `_reap_stale_paused()` (Phase 15, Batch 4's original expiry-cleanup
   mechanism) checked only for `APPROVED_UNCONSUMED` when deciding
   whether a workflow with no in-memory decision was genuinely stale -
   but the row transitions to `CLAIMED` the instant `claim_for_resume()`
   succeeds, and a *second* `has_paused()` call immediately afterward
   (in both the live path and continuation) would then see `CLAIMED`,
   conclude the workflow was stale, and durably delete its
   `paused_workflow_state` row a moment before `resume()` itself ran.
   The live path never observed this because the *same* live
   `ApprovalManager` instance already holds the decision in memory
   (`get_decision()` succeeds, short-circuiting the check); a freshly
   restarted instance's `_decisions` is empty. Corrected: `CLAIMED` is
   now also excluded from the staleness check.

Both defects were found by writing real, on-disk-database restart
tests (`tests/integration/test_yellow_workflow_restart_continuation.py`)
that initially failed with exactly these symptoms, then fixed and
re-verified; dedicated regression tests now guard against recurrence.

## 11. `CLAIM_INTERRUPTED` visibility

`ApprovalHistoryStore.record_interruption()` (Batch 2, reconfirmed
unchanged) sets a history row's `status` to `"interrupted"`, embedding
the discovery timestamp and any bounded reason in `decision_reason` -
preserving the original `decided_by`/`decided_at` (who approved it, and
when, remains visible). Idempotent by construction (one row per
`request_id`). `ApprovalHistoryTool`'s existing per-entry formatting
(`record.status.upper()`) already displays "INTERRUPTED" truthfully for
any such row, with no code change required
(`tests/unit/test_approval_history_interruption_display.py`). Visible
meaning: approval was granted; execution was claimed; the terminal
outcome could not be proven; automatic replay is prohibited; the old
approval is no longer usable - never unrestricted tool output, prompts,
model reasoning, stack traces, or secrets.

## 12. `CONSUMED` semantics

`CONSUMED` means only that a claimed execution's ownership was used and
a real, well-defined `WorkflowResult` was reached (`COMPLETED`,
`FAILED`, or a new `WAITING` pause on a later step) - **never**
"succeeded." The workflow result/history remains the sole source of
whether the underlying action itself succeeded, failed, produced a
verification mismatch, or found verification unavailable. Proven across
all four such outcomes
(`tests/integration/test_orchestrator_claim_before_resume.py`). Retained
**indefinitely** - never deleted by any code in this interlock; no
cleanup command exists or was added, a deliberate, honestly-documented
choice (deleting it would make an already-consumed approval's own
durable evidence unverifiable, or free its `request_id` for confusion).

## 13. Production store wiring

`main.build_orchestrator()` is the only production construction of
`JarvisOrchestrator`/`ApprovalManager`, and it always supplies the real,
durable `PendingApprovalStore` - proven both structurally (every
`ApprovalManager(...)` call in `main.py` supplies `pending_store=`) and
behaviourally (a production-wired `claim_for_resume()` on an unknown id
returns `False`, never the no-store fallback's unconditional `True`).
The pre-existing `JarvisOrchestrator.__init__`'s own
`approval_manager or ApprovalManager()` test-convenience default is
retained (not removed - unnecessary), proven unreachable from
`build_orchestrator()`'s own real wiring. Neither `dashboard.py` nor
`scheduler.py` imports `ApprovalManager`/`JarvisOrchestrator`/
`WorkflowEngine` at all.

## 14. Crash windows A–G

| Window | Description | Evidence |
|---|---|---|
| A | Before approval - remains PENDING, no execution, decline/expiry work | `test_window_a_pending_request_remains_pending_no_execution` + full existing decline/expiry regression suites |
| B | After `APPROVED_UNCONSUMED` commit, before ordinary resume - the original system-wide bug | All four workflows in `test_yellow_workflow_restart_continuation.py`, end to end, on real on-disk databases |
| C | During claim CAS - one claimant succeeds, second fails; crash before/after commit | `test_window_c_one_claimant_succeeds_second_fails`, `test_window_c_crash_before_cas_commit_leaves_approved_unconsumed`, `test_window_c_crash_after_cas_commit_leaves_claimed` |
| D | After claim, before `WorkflowEngine` begins - no replay; terminal evidence reconciles, else interrupted | `test_missing_paused_workflow_after_claim_produces_claim_interrupted` (Batch 2); `test_missing_terminal_history_produces_claim_interrupted` (Batch 2) |
| E | After workflow terminal result, before `mark_consumed` - terminal history reconciles to `CONSUMED` | `test_claimed_with_workflow_completed_becomes_consumed`, `test_claimed_with_workflow_stopped_becomes_consumed` (Batch 2) |
| F | After `CONSUMED`, before response delivery - no replay, approval non-reusable | `test_response_delivery_failure_after_consumed_does_not_replay` (Batch 2) |
| G | After final completion - duplicate resume/startup/claim all zero-execute | `test_window_g_duplicate_restart_performs_zero_new_execution`, `test_window_g_duplicate_claim_after_consumed_fails` |

## 15. All four YELLOW workflow restart proofs

All four proven end to end, on real, temporary, on-disk SQLite
databases (never `:memory:`, never in-memory object reuse), in
`tests/integration/test_yellow_workflow_restart_continuation.py`:
process one creates a real pending approval + paused workflow and
approves it; every in-memory object is discarded; process two (a wholly
separate stack bound only to the same file) reloads durable state and
calls the real `main.continue_approved_unconsumed_workflows()` directly.

- **`PROJECT_STATE_UPDATE_FOCUS`**: `test_focus_update_restart_continuation`
  - exact approved focus value written, `CONSUMED`, no reapproval.
- **`PROJECT_STATE_UPDATE_PHASE`**: `test_phase_update_restart_continuation`
  - exact approved phase value written and internally verified,
    `CONSUMED`, no reapproval.
- **`SCHEDULE_ENABLE`**: `test_schedule_enable_restart_continuation` -
  schedule durably enabled, verified, `CONSUMED`, no reapproval.
- **`SCHEDULE_DISABLE`**: `test_schedule_disable_restart_continuation` -
  schedule durably disabled, verified, `CONSUMED`, no reapproval.

Each asserts: exactly one claim succeeded (`claim_for_resume()` returns
`False` afterward), the expected real write occurred, the expected
verification/tool ran, the terminal handoff is `CONSUMED`, and no second
approval exists.

## 16. Backward compatibility

Existing migrated rows default to `PENDING`; existing pending approvals,
paused workflows, and approval-history records all remain readable and
correctly displayed; every existing YELLOW capability's own tools,
argument validation, `SecurityManager` tier, approval wording, exact
tool input, `ToolExecutor` execution, durable verification, and
success/failure responses are all unchanged - only the handoff lifecycle
differs. Four Batch 2-era tests whose own old expectations were
precisely the bug this interlock fixes were corrected (never weakened)
to assert the new, correct behaviour; this batch corrected one further
Batch 2 test (`test_reload_retains_when_linked_approval_is_approved_unconsumed`
-> `test_reload_reconstructs_when_linked_approval_is_approved_unconsumed`)
for the same reason (Section 10).

## 17. Migration evidence

No new schema change in Batch 3 (the additive `handoff_status` column
and its guarded migration were introduced in Batch 1 and remain
unchanged). Fresh and migrated databases continue to behave identically
- reconfirmed by the full, unmodified Batch 1 migration test suite
passing in this batch's own full-suite run.

## 18. Test results

- Batch 1: 72 tests. Batch 2: 66 net new tests. Batch 3: 23 net new
  tests (10 production wiring + 5 real four-workflow restart + 8 crash-
  window proofs, plus 1 corrected pre-existing test).
- Full suite at closure: **5507 passed, 3 skipped, 0 failed**, identical
  in the normal environment, `AI_REASONING_ENABLED=false`, and
  `PYTHON_DOTENV_DISABLED=1`.

## 19. Ruff verification

Full-interlock scope (`git diff --name-only 6c9e404..HEAD -- '*.py'`,
covering Batch 1 + Batch 2 + Batch 3 together): clean, exit 0. Exact
file count and list, and the exact command/output, are recorded in the
Batch 3 closure commit's own final report (this document's companion
Batch 3 prompt response).

## 20. Manual Anthropic limitation

Live Anthropic API acceptance testing remains **postponed**, due to
insufficient API credits - an external, non-technical limitation. No
code in this interlock bypasses, simulates, or works around that
limitation: every test exercising an "ask jarvis to:" capability uses a
real `AIRouter` wired to a fake, deterministic, in-memory `AIProvider`
(never a live network call), and the OS lock, CAS primitives, and
startup recovery are proven with pure deterministic Python and real
subprocesses/on-disk databases - never AI output of any kind. Handoff
safety is proven entirely independently of live Anthropic access.

## 21. Exact guarantees

- Durable retention: an approved request's row is never deleted on
  decision; it survives a crash between approval and resume.
- Single claim ownership: at most one caller can ever successfully
  claim a given request's execution.
- Startup continuation: every `APPROVED_UNCONSUMED` row is automatically
  claimed and resumed after a restart, using only durable, already-
  approved state - never a new approval, never new model output.
- Honest terminal classification: `CONSUMED` (a real terminal result was
  reached) is always distinguished from `CLAIM_INTERRUPTED` (claimed,
  outcome unconfirmed) - `workflow_history` absence is never treated as
  negative proof.
- No automatic replay: a `CLAIM_INTERRUPTED` or `CONSUMED` row is never
  automatically re-executed by anything in this interlock.
- Production enforcement: the real, durable CAS is always used in
  production; the no-store compatibility fallback is provably
  unreachable from it.

## 22. Exact non-guarantees

- **Not** a universal exactly-once execution guarantee: a crash strictly
  between a real tool write committing and its own `workflow_history`
  record committing leaves an honest, narrow, previously-documented
  audit gap (Phase 98's own Section 4.2) - never a duplicated *value*,
  only, in the rarest case, a missing audit pairing.
- **Not** whole-database single-writer safety: the scheduler remains
  entirely outside this lock; concurrent scheduler and CLI use of the
  same database is unsupported, not safe.
- **Not** a cleanup/retention system: `CONSUMED`/`CLAIM_INTERRUPTED` rows
  accumulate indefinitely; no archival or deletion mechanism exists.
- **Not** live Anthropic-proven: proven entirely via deterministic and
  fake-provider tests, pending future live acceptance testing when API
  credits are available.

## 23. Formal interlock closure

The Approval-to-Resume Handoff Interlock (Batches 1, 2, and 3) is
**formally closed** as of this report. Every mandatory audit, crash
window, and required test passed; both defects discovered during Batch
3's own implementation were corrected and regression-tested; production
wiring was proven, not merely asserted.

## 24. Phase 98 compound status

Phase 98 (live compound selection, planning, approval, and execution of
the `PROJECT_STATE_UPDATE_PHASE -> PROJECT_STATE_SHOW` compound
template) **remains open and blocked**. This report closes only the
system-wide handoff safety mechanism that Phase 98's own planning
surfaced as a prerequisite - it does not itself begin, plan, or
authorize Phase 98 live compound Batch 2. No live compound parsing,
selection, planning, approval, or execution exists anywhere in the
repository as of this report.
