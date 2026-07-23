# Phase 98 Safety Interlock Planning Gate — Durable Approved-to-Resume Handoff

Status: **planning gate only**. No production or test code changed.

## 1. Current baseline

- Branch: `phase-4-ai-reasoning-and-write-actions`, HEAD `fc879c1`.
- Phase 98 Batch 1 formally accepted and closed (`7feea73`, `fc879c1`).
- Full suite: 5360 passed, 3 skipped, 0 failed, identical in all three
  required environments.
- Phase 98 remains open; Batch 2/3 have not started.

## 2. Exact discovered crash gap

Confirmed by direct, live tracing of the real calling code (not
assumption): `ui/cli.py` (the sole caller of this sequence in the
running application) does exactly this, at lines 434-453:

```python
decision = self._orchestrator.approvals.approve(
    request.request_id, decided_by=answer.decided_by
)
...
if decision.is_approved:
    executed = self._orchestrator.execute_approved(response, decision)
```

`ApprovalManager.approve()` (via `_decide()`) durably records the
decision and **deletes** the `pending_approval_state` row in one call,
synchronously, before `execute_approved()`/`WorkflowEngine.resume()`
is ever invoked - confirmed directly in `approval/approval_manager.py`.
A process crash between these two lines leaves: the decision durably
recorded as APPROVED in `approval_history` (permanent, audit-only); no
`pending_approval_state` row at all (deleted); and the linked
`paused_workflow_state` row (if any) still present, but now orphaned -
`WorkflowEngine.reload_paused()`'s own revalidation
(`self._approvals.has_pending(record.request_id)`) finds the approval
**not pending** (it was already decided) and invalidates the entire
workflow as unresumable, silently discarding an already-approved user
action.

## 3. Current approval-to-resume sequence (exact, code-grounded)

1. A YELLOW step causes `WorkflowEngine`/`ToolExecutor` to return
   `requires_confirmation=True`; `ApprovalManager.create_request()`
   durably writes a `pending_approval_state` row (`PendingApprovalStore.save()`)
   and, for a workflow, `WorkflowEngine._persist_paused_state()`
   durably writes a `paused_workflow_state` row
   (`PausedWorkflowStore.save()`) - two **independent**, separately
   committed transactions, each via its own `session_scope()`.
2. `ui/cli.py` prompts the user and calls
   `ApprovalManager.approve(request_id, ...)`.
3. `approve()` → `_decide()`: looks up the in-memory pending request,
   builds the `ApprovalDecision`, removes it from `self._pending`,
   stores it in `self._decisions`, writes one `approval_decision`
   audit event, calls `_record_history_decision()` (durable,
   permanent `approval_history` row - "approved"), and calls
   `_remove_pending_state()` → `PendingApprovalStore.delete(request_id)`
   (durable delete of `pending_approval_state`) - **all within this
   one `approve()` call, all committed before it returns.**
4. `ui/cli.py` prints the decision, then calls
   `self._orchestrator.execute_approved(response, decision)`.
5. `execute_approved()` derives `workflow_id` from `response` and
   calls `WorkflowEngine.resume(workflow_id, decision, ...)`, which
   pops `self._paused[workflow_id]` (in-memory) and calls
   `_remove_paused_state()` → `PausedWorkflowStore.delete(workflow_id)`
   (durable delete) **before** the approved step's `ToolExecutor.execute()`
   call happens.

Step 3 and step 5 are two **separate**, independently committed
database transactions, invoked by two **separate** function calls from
the same calling code, with ordinary Python code (a `print`, an `if`)
in between - never inside one atomic unit today.

## 4. Current durable records after approval

Immediately after step 3 above (before step 5 ever runs):
`approval_history` has a permanent "approved" row (read-only, audit);
`pending_approval_state` has **no row** for this request (deleted);
`paused_workflow_state` still has its full row (plan, resolved input,
approved arguments) - untouched, since only `resume()` itself ever
deletes it. This is precisely why the paused workflow "exists" but is
unreachable: its own row is fine, but the linked approval it depends on
for revalidation is gone.

## 5. Current transaction boundaries

Confirmed directly: `storage/database.py` provides exactly one
`session_scope()` helper, and every store (`PendingApprovalStore`,
`PausedWorkflowStore`, `ApprovalHistoryStore`, `WorkflowHistoryStore`,
`CompoundWorkflowProgressStore`, etc.) is bound to the **same single**
SQLAlchemy engine/session factory (one SQLite file, confirmed via
`create_database_engine()`/`create_session_factory()` - there is
exactly one `DATABASE_PATH`). However, **each store's own methods
always open and commit their own independent `session_scope()`** -
none accepts an externally-supplied session, and nothing in the
current codebase coordinates two stores' writes into one shared
transaction. They share one *database*, but not today's *transaction
boundary* - confirming Option B's own literal requirement ("one
database; one transaction boundary; and repository-supported session
handling") is only partially met: the database is shared, but the
session-sharing mechanism does not exist yet and would itself be new,
cross-cutting production surface.

## 6. Architecture options assessed

### Option A - Keep the approval row after approval (selected)

Add one new, narrow status dimension to `PendingApprovalState` itself -
never touching `PausedWorkflowState` at all, since (per Section 4) that
row was never the problem. `approve()` transitions the row
PENDING → APPROVED_UNCONSUMED instead of deleting it; a new, narrow
`claim_for_resume()` operation performs a single-table, single-statement
compare-and-set APPROVED_UNCONSUMED → CLAIMED, called once, at the one
existing choke-point (`execute_approved()`, or immediately before it)
that already handles both workflow-linked and plain single-tool YELLOW
approvals identically. This is the smallest, most surgical option:
one table, one store, one manager, zero change to
`PausedWorkflowState`/`PausedWorkflowStore`/`WorkflowEngine`'s pause/
resume mechanics themselves.

### Option B - Atomic approval-to-paused-workflow handoff (assessed, not selected)

Would require introducing session-sharing across two independently-
designed stores (Section 5's own finding: no repository-supported
mechanism for this exists today) purely to protect a row
(`paused_workflow_state`) that Section 4 already shows is **not** the
one being lost. This is more invasive than the actual gap requires -
proposing it would mean inventing new cross-store session-passing
machinery to solve a problem Option A solves within one table. Rejected
as disproportionate to the real, narrowly-diagnosed defect.

### Option C - Durable approved-work queue or handoff record (assessed, not selected)

A new, separate table linking approval id/workflow id/claim status
would duplicate data `PendingApprovalState` already owns (it already
carries `request_id`, and - via `paused_workflow_state.request_id` -
the link to any workflow is already established). Rejected: Option A
achieves everything this option would, without a new table.

### Option D - Other repository-grounded solution

None found simpler than Option A after direct inspection.

**Selected: Option A.**

## 7. Selected state model

A new, narrow enum, `PendingApprovalHandoffStatus` (deliberately
**separate** from the existing `ApprovalStatus`, which remains the
user's own decision outcome - approved/declined - forever unchanged;
this new enum describes the durable **row's own handoff lifecycle**,
never conflated with the decision itself):

- `PENDING` - awaiting a decision (today's only implicit state).
- `APPROVED_UNCONSUMED` - decided approved; execution handoff not yet
  claimed.
- `CLAIMED` - exactly one caller has acquired the right to execute;
  execution has not yet been confirmed to have started.
- `CONSUMED` - the claim was successfully handed off into
  `WorkflowEngine.resume()`/direct `ToolExecutor.execute()`; the row is
  deleted at this point (mirrors today's existing deletion timing,
  just moved later).
- `DECLINED` / `EXPIRED` - terminal, row deleted immediately (unchanged
  from today).
- `CLAIM_INTERRUPTED` - a claimed row found, on restart, with no
  durable evidence execution ever began or completed - flagged for
  operator visibility, **never** automatically re-claimed or resumed.

No state is added for theoretical completeness - each one is required
by a distinct, real transition this section's own crash-window analysis
demands.

## 8. Selected handoff design

- `PendingApprovalState` gains one new column,
  `handoff_status: str`, defaulting (for migration) to `"pending"`.
- `ApprovalManager._decide(approved=True, ...)` no longer deletes the
  `pending_approval_state` row; it durably transitions
  `handoff_status` to `APPROVED_UNCONSUMED` via a single-statement
  compare-and-set (`PENDING → APPROVED_UNCONSUMED`). A decline still
  deletes the row immediately (unchanged - a declined request is
  already fully terminal).
- A new `ApprovalManager.claim_for_resume(request_id) -> ApprovalDecision`
  method performs the single-statement CAS
  `APPROVED_UNCONSUMED → CLAIMED`; on success, returns the same,
  already-recorded, immutable `ApprovalDecision` from `self._decisions`
  (or reconstructed on reload - Section 11); on failure (rowcount 0),
  raises `ApprovalError` - the caller must not proceed to execute
  anything.
- `core/orchestrator.py`'s `execute_approved()` calls
  `claim_for_resume()` as its very first action, before deriving
  `workflow_id` or calling `resume()`/`ToolExecutor.execute()` - this
  one insertion point already uniformly covers both workflow-linked
  and plain single-tool YELLOW approvals, since `execute_approved()`
  is already the sole existing choke-point for both (confirmed
  directly in its own code).
- Once `resume()`/direct execution genuinely begins, the row
  transitions `CLAIMED → CONSUMED` and is deleted - mirroring today's
  existing deletion timing, simply moved to occur after the claim
  instead of after the decision.

## 9. Exact claim semantics

```sql
UPDATE pending_approval_state
SET handoff_status = 'claimed'
WHERE request_id = ? AND handoff_status = 'approved_unconsumed'
```

- `rowcount == 1`: this caller, and only this caller, holds the claim.
- `rowcount == 0`: another claimant already succeeded, or the row is
  in an invalid state for claiming (still pending, already claimed,
  already consumed, or gone) - reported as `ApprovalError`, never
  silently retried.
- No read-then-write pair anywhere in the claim path - one atomic SQL
  statement, exactly mirroring Phase 98 Batch 1's own
  `CompoundWorkflowProgressStore._compare_and_set()` pattern.
- No owner/claim token is introduced for this narrow scope: the CAS
  rowcount itself is sufficient, sole proof of exclusive ownership: at
  most one process can ever observe `rowcount == 1` for a given
  transition, by SQLite's own transactional guarantees (confirmed:
  `session_scope()` commits or rolls back atomically per call). No
  process identity, hostname, or other information is persisted.
- Workflow id, request id, and approved arguments (`tool_input_json`,
  unchanged) remain completely immutable throughout every transition -
  no column touched by any claim operation ever mutates them.

## 10. Crash-window analysis

### Window A - Before approval

Unchanged: the row is `PENDING`; decline/expiry work exactly as today
(both delete the row immediately, and never race the new mechanism,
since it is never reached before a decision exists).

### Window B - After durable approval, before claim (the primary gap)

The row now durably shows `APPROVED_UNCONSUMED` instead of being
deleted. Restart discovery (Section "claimed-but-not-started
recovery" below) finds it via `PendingApprovalStore.list_all()`
(already existing), recognizes `handoff_status == APPROVED_UNCONSUMED`,
and makes it available for a caller to explicitly claim - no new
approval is ever created; the exact, original `tool_input_json`/
`action`/`reason` are read verbatim, unchanged.

### Window C - During atomic claim

Two concurrent claimants: the CAS statement (Section 9) guarantees
exactly one succeeds; the other sees `rowcount == 0` and raises
`ApprovalError`, attempting nothing further. A database error during
the `UPDATE` rolls back via `session_scope()`'s own existing
exception handling - the row remains `APPROVED_UNCONSUMED`, safely
re-claimable. A process exit before commit: the transaction never
completed, so the row is unchanged (`APPROVED_UNCONSUMED`), safely
re-claimable. A process exit immediately after commit: the row is
durably `CLAIMED` - see Window D.

### Window D - After claim, before WorkflowEngine/ToolExecutor starts

**Mandatory design decision.** A `CLAIMED` row found at restart, with
no corresponding evidence execution began, cannot in general be proven
safe to either re-claim or discard - for an **arbitrary** YELLOW tool
(not merely the future phase-update case), there is no universal,
safe way to determine whether the real side effect already occurred.
The correction therefore defines one honest, universal rule for every
existing YELLOW capability: on restart, a `CLAIMED` row with no
completion evidence is transitioned to `CLAIM_INTERRUPTED` - a durable,
visible, terminal-for-automation state. It is never automatically
re-claimed, re-executed, or silently discarded; recording it durably
(rather than deleting it, and rather than silently leaving it
`CLAIMED` forever) is itself the entire correction for the general
case - it makes an otherwise-invisible ambiguity durably visible for
manual review, without ever guessing.

For the one narrow, already-built exception - the future compound
`PROJECT_STATE_UPDATE_PHASE` consumer - Phase 98 Batch 1's own
`reconcile_phase_update()` (already implemented, already tested, not
live-wired) can, in a **separately-approved future batch**, safely
narrow `CLAIM_INTERRUPTED` down to a confirmed continuation point using
its own real, evidence-based reconciliation contract (Contract A). This
plan does not implement that wiring now - it only confirms the
foundation already built in Batch 1 is the correct, compatible
consumer of this new, more general handoff-recovery vocabulary.

### Window E - After WorkflowEngine begins

Ownership transfers from the approval handoff (`CLAIMED`) to
`WorkflowEngine`'s own existing pause/resume semantics exactly as
today, the moment `resume()` genuinely starts - the row moves to
`CONSUMED` and is deleted at that point (not before), closing the
window entirely; the approval can never be reused once this happens,
since the row backing any future claim attempt no longer exists. For
the future compound consumer, ownership further transfers into
`CompoundWorkflowProgress`'s own already-existing, already-tested
step-by-step tracking (Batch 1) - unaffected by this plan.

### Window F - After workflow completion

Unchanged and already safe: `resume()` cannot be invoked twice for one
`workflow_id` (raises `WorkflowError`); with this correction, the
approval row is already deleted (`CONSUMED`) by the time completion is
reached, so there is nothing left to reclaim by any path.

## 11. Claimed-state recovery (restart-discovery)

`ApprovalManager.reload_pending()` is extended (not replaced) with a
second pass, after its existing pending-row revalidation: for every
persisted row whose `handoff_status` is `APPROVED_UNCONSUMED`, revalidate
identically to a pending row (tool still registered, action still
classifies YELLOW) and, if valid, make it available via a new,
narrow accessor (e.g. `list_approved_unconsumed()`) - never
auto-claimed, never auto-resumed; a caller (main.py's own startup
sequence, or a future explicit CLI command) must still explicitly
decide to claim and resume it, exactly mirroring how a reloaded
*pending* request already requires an explicit human decision today.
For every row whose `handoff_status` is `CLAIMED`, the same reload
pass transitions it to `CLAIM_INTERRUPTED` (Section 10, Window D) and
records an honest terminal entry in `approval_history` - never
resumed, never silently dropped.

## 12. Expiry and decline semantics

- **Pending**: may be declined; may expire (`_sweep_expired()`,
  unchanged - it only ever iterates `self._pending`, which a decided
  request has already left, by construction, regardless of this
  correction); may not execute.
- **Approved-unconsumed**: cannot later be declined or expire as
  though never approved - `_sweep_expired()` never touches it (it is
  not in `self._pending`); `decline()`/`approve()` called again for the
  same `request_id` raise `ApprovalError` (the row is no longer
  `PENDING`, so `get_pending()`'s own lookup - extended to check
  `handoff_status == PENDING` - correctly fails). Remains resumable via
  `claim_for_resume()` only; approved arguments (`tool_input_json`)
  are never touched by any transition.
- **Claimed**: cannot be reclaimed by another process (Section 9's CAS
  guarantee); cannot be reused for another workflow (the row is
  identity-bound to one `request_id`/one `tool_input_json`, immutable).
- **Terminal (consumed/declined/expired/claim-interrupted)**: the
  approval is no longer actionable through any code path - `claim_for_resume()`'s
  own CAS precondition (`handoff_status == APPROVED_UNCONSUMED`)
  structurally excludes every terminal state.

## 13. Approval-consumption semantics

"Decided" (approve()/decline() called) and "consumed" (execution
genuinely began) become two **distinct**, separately-observable
events for the first time - closing exactly the ambiguity Section 2
identifies. "Decided" now durably persists past the moment of decision
(for an approval); "consumed" is deferred until `WorkflowEngine.resume()`/
direct execution truly starts. `approval_history` remains completely
unchanged in shape and meaning - it already only ever records the
*decision* (approved/declined/expired), never execution progress; this
plan adds no new column there.

## 14. Backward compatibility

1. **Existing pending-approval rows**: any row present at migration
   time is, by definition, still genuinely pending under today's code
   (no other state was ever possible) - the migration's default
   (`handoff_status = 'pending'`) is exactly correct for every one of
   them, with zero reinterpretation.
2. **Existing paused-workflow rows**: entirely untouched - Option A
   makes no change to `PausedWorkflowState`/`PausedWorkflowStore`.
3. **Existing approval-history rows**: untouched - no schema or
   meaning change.
4. **Existing serialized approval status values**: `ApprovalStatus`
   (PENDING/APPROVED/DECLINED/EXPIRED) is untouched; the new
   `PendingApprovalHandoffStatus` is a wholly separate, new enum/column,
   never replacing or reinterpreting the existing one.
5. **Old code assuming the row disappears after `approve()`**: only
   `ApprovalManager`'s own internal `_decide()`/`_remove_pending_state()`
   call sites assume this today - both are being changed together, in
   the same commit, as part of this correction; no other module reads
   `pending_approval_state` directly (confirmed: only
   `PendingApprovalStore`/`ApprovalManager` reference it).
6. **Existing tests expecting deletion**: any test asserting
   `pending_approval_state` is empty immediately after `approve()`
   would need updating to expect `APPROVED_UNCONSUMED` until
   `claim_for_resume()` runs - an expected, legitimate consequence of
   the corrected contract, not a weakening; enumerated in Section 22.
7. **Restart behavior for pre-correction rows**: covered by item 1 -
   identical to today's behavior for anything genuinely mid-flight
   during an upgrade.
8. **`create_all()` behavior**: adds new tables automatically, but
   (confirmed directly, `storage/database.py`) **does not alter an
   existing table** - a genuine migration step is required for the new
   column, exactly like the existing, already-precedented
   `_ensure_memory_category_column()` pattern.
9. **Migration required**: **yes** - one new column,
   `pending_approval_state.handoff_status`, added via a guarded,
   idempotent `ALTER TABLE ... ADD COLUMN handoff_status VARCHAR(24)
   NOT NULL DEFAULT 'pending'`, mirroring the existing
   `episodic_memories.category` migration exactly.
10. **Default state preserves old rows safely**: yes - confirmed in
    item 1/9 together; no data loss, no reinterpretation.

## 15. Impact on all existing YELLOW workflows

For `PROJECT_STATE_UPDATE_FOCUS`, `PROJECT_STATE_UPDATE_PHASE`,
`SCHEDULE_ENABLE`, `SCHEDULE_DISABLE` - none of their own execution,
verification, or response-building logic changes at all. Confirmed,
per capability:

- The paused workflow (plan, resolved tool input) remains available
  after approval exactly as today - untouched (Section 6, Option A).
- Approved arguments remain immutable - `tool_input_json` is never
  written to by any new transition.
- Restart before execution begins can recover via the new
  `list_approved_unconsumed()`/`claim_for_resume()` path - previously
  impossible; this is a strict safety improvement, not a behavior
  change to the capability itself.
- Exactly one claimant can resume (Section 9's CAS); duplicate claim
  is refused (`rowcount == 0`).
- Decline and expiry are unchanged (Section 12).
- A completed workflow cannot restart - unchanged
  (`WorkflowError` on a second `resume()`; the approval row is already
  `CONSUMED`/deleted by then).

## 16. Future Phase 98 compound integration

Once this correction ships, the future Batch 2 design can: call
`claim_for_resume()` for the compound template's own approval exactly
like any other YELLOW action (no compound-specific claim logic
needed); use the now-successfully-claimed, immutable
`ApprovalDecision`/paused-workflow data to locate its own
`CompoundWorkflowProgress` row (already keyed by `workflow_id`,
Batch 1); resume execution from the durable next step exactly as
Batch 1's own store already supports; and never recreate approval,
since the claim mechanism guarantees the same approval can never launch
a second execution. This is precisely how the handoff correction
unblocks Batch 2 - Batch 2 no longer needs to solve the approve-then-
resume gap itself; it only needs to call the now-existing
`claim_for_resume()` before proceeding, exactly like every other
capability.

## 17. Selected outcome

**Outcome A - narrow correction is ready** (to plan; not implemented in
this gate).

- **Exact implementation title**: "Durable Approved-to-Resume Handoff
  Interlock."
- **Exact files expected to change**: `storage/models.py`
  (`PendingApprovalState.handoff_status` column),
  `storage/database.py` (new guarded migration step, mirroring
  `_ensure_memory_category_column()`), `approval/pending_approval_store.py`
  (read/write the new column; new compare-and-set methods),
  `approval/approval_manager.py` (`_decide()` no longer deletes on
  approval; new `claim_for_resume()`; `reload_pending()` extended),
  `core/orchestrator.py` (`execute_approved()` calls
  `claim_for_resume()` first).
- **Exact state model**: Section 7.
- **Exact claim API**: Section 9.
- **Exact transaction boundaries**: one single-statement CAS per
  transition, each its own `session_scope()` - no cross-store
  transaction introduced (Option A's own defining property).
- **Exact restart-discovery path**: Section 11.
- **Exact claimed-state recovery**: Section 10, Window D.
- **Exact compatibility design**: Section 14.
- **Phase size**: Large/risky (Section 21).
- **Batch structure**: Section 21.
- **Tests**: Section 22.
- **Acceptance criteria**: Section 23.
- **Stop conditions**: Section 25.

## 18. Exact scope

Exactly the five files in Section 17's "files expected to change" list.
No change to `PausedWorkflowState`/`PausedWorkflowStore`/
`WorkflowEngine`'s pause/resume mechanics, `SecurityManager`,
`ToolExecutor`, `WorkflowHistoryStore`, or any capability-specific
tool/verification code.

## 19. Exact non-goals

No SecurityManager rule change; no weaker tiers; no execution before
approval; no automatic re-approval; no approval reuse; no
model-controlled claim states; no background workers; no generic job
queue; no arbitrary workflow scheduling; no retries; no replanning; no
rollback; no compensation; no autonomous behavior; no new
capabilities; no live compound wiring; no distributed lease system.

## 20. Phase size and batches

Per the task's own rule ("if approval schema, workflow schema or
restart behavior changes, it is at least medium... if migration or
transactional redesign is required, classify it as large/risky") and
given this touches a real column migration on `pending_approval_state`
and changes the timing of an existing, universally-used deletion in
`ApprovalManager._decide()` (affecting every YELLOW action in the
system): **Large/risky - three batches.**

- **Batch 1**: schema migration + `PendingApprovalHandoffStatus` +
  `PendingApprovalStore` CAS methods, fully tested in isolation with
  zero behavior change to `ApprovalManager` yet (additive column and
  store methods only).
- **Batch 2**: `ApprovalManager._decide()`/`claim_for_resume()`/
  `reload_pending()` changes, with complete regression proof for every
  existing YELLOW capability (decline, expiry, restart, duplicate-resume).
- **Batch 3**: `core/orchestrator.py`'s `execute_approved()` wiring,
  full end-to-end crash-window tests, full three-environment
  regression, and closure.

## 21. Required tests

All 29 items the task requires map onto the batches above: schema/CAS
tests (Batch 1); decision-timing, claim, expiry/decline, restart,
duplicate-claim, and per-capability regression tests (Batch 2);
end-to-end crash-window, audit-truthfulness, and full-suite/Ruff
verification (Batch 3).

## 22. Acceptance criteria

All required tests pass; every existing YELLOW capability's own test
suite passes, with only the narrow, expected update noted in Section
14, item 6 (any test asserting immediate row deletion on approval);
full suite matches baseline plus new tests, in all three environments;
a fresh database and an existing pre-correction database both behave
identically after migration; Ruff and `git diff --check` clean.

## 23. Risks and mitigations

- **Risk**: changing `_decide()`'s deletion timing regresses existing
  approval tests. **Mitigation**: Batch 2's own explicit regression
  scope, run before Batch 3 begins.
- **Risk**: the migration is skipped on an existing database.
  **Mitigation**: mirrors the already-proven, already-shipped
  `_ensure_memory_category_column()` pattern exactly.
- **Risk**: `CLAIM_INTERRUPTED` rows accumulate with no cleanup path.
  **Mitigation**: explicitly out of scope for automatic handling by
  design (Section 10) - a future, separately-approved operator-facing
  view is a candidate follow-up, not part of this correction.

## 24. Stop conditions

Stop and report if: the migration cannot be made additive/backward-
compatible; the claim CAS cannot guarantee exclusivity; `CLAIMED` rows
cannot be durably distinguished from `APPROVED_UNCONSUMED`; any
existing YELLOW capability's execution/verification behavior would
need to change; workflow history would need to become authoritative;
or a cross-store atomic transaction (Option B) becomes unavoidable.

## 25. Manual Anthropic limitation

Live Anthropic manual acceptance remains postponed because the
configured API account lacks sufficient credits - an external account
limitation, not a Jarvis production-code failure. No production change
may bypass it. The approval-handoff correction must be, and will be,
proven entirely with deterministic, repository-level tests (real
SQLite, fake providers) - exactly as every prior phase in this session
has been.

## 26. Formal planning-gate conclusion

The real, code-grounded gap is narrower than it first appears: the
`paused_workflow_state` row was never the problem; the
`pending_approval_state` row's own destructive deletion on approval is
the entire defect. Option A closes it with a single-table, single-store
change, reusing the exact compare-and-set pattern Phase 98 Batch 1
already established, with an honest, universal (not compound-only)
answer for the one truly hard case (a claimed-but-unconfirmed
arbitrary side effect). Recommended for future implementation as a
three-batch, large/risky phase, not implemented in this planning gate.
