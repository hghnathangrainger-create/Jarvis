# Phase 98 Safety Interlock Planning Gate — Durable Approved-to-Resume Handoff (Amended)

Status: **planning gate only**. No production or test code changed.
This amendment resolves six mandatory gaps identified in the prior
draft (committed at `5e90546`): the unstated process-concurrency
assumption behind "no lease token"; the missing actionable lifecycle
for `CLAIM_INTERRUPTED`; an incomplete post-claim transition matrix
(most critically, the "crashed after real success, before the handoff
was marked consumed" window); undefined approval-history/handoff
consistency; and a `CONSUMED` state that conflated "ownership acquired"
with "terminal outcome known." All resolutions below are grounded in
direct, live inspection of the real calling code, not assumption.

## 1. Current baseline

Unchanged from the prior draft: HEAD `fc879c1` at the time of that
draft, now amended after `5e90546`. Phase 98 Batch 1 accepted and
closed. Batch 2/3 remain blocked.

## 2. Supported process model (Mandatory gap 1)

Directly inspected `main.py`, `ui/cli.py`, `dashboard.py`,
`ui/dashboard_app.py`, `dashboard/read_model.py`, `scheduler.py`, and
`storage/database.py`'s own WAL/busy-timeout configuration, and
searched the whole repository for every production call site of
`.approve(`, `.decline(`, `execute_approved(`, and `WorkflowEngine.resume(`.

**Findings:**

- Exactly **one** production code path ever calls
  `approve()`/`decline()`/`execute_approved()`:
  `ui/cli.py`'s `_handle_approval()` (lines 406-454), inside
  `JarvisCLI.run()`'s single-threaded, synchronous, blocking
  `while True: input()` loop. Within one running process, at most one
  of these calls is ever in flight at a time - there is no
  threading/asyncio anywhere in `approval/`, `workflow/`, `core/`,
  `ui/`, or `main.py` (confirmed by direct search).
- `main.py`'s `build_orchestrator()` calls
  `approvals.reload_pending()` then `workflow_engine.reload_paused()`
  exactly once, synchronously, strictly before `cli.run()` begins - no
  live claimant can exist in this process before that pass completes,
  by construction (the interactive loop that could ever call
  `approve()`/`claim_for_resume()` has not started yet).
- Two **other** real processes legitimately open the same SQLite file:
  `dashboard.py` (confirmed, by direct inspection of its own docstring
  and every write-method call site, to be **100% read-only** - it
  never calls `ApprovalManager.approve()/decline()`,
  `WorkflowEngine.resume()`, or any store's write method) and
  `scheduler.py` (writes only to `ScheduleStore`/`InboxStore` - never
  touches `pending_approval_state`, `paused_workflow_state`, or any
  approval/workflow code path at all).
- **No single-instance enforcement exists** (no PID file, no OS lock,
  no documented "one instance only" policy) - nothing today
  technically prevents a second `main.py` CLI process from being
  started against the same database file.

**Conclusion**: the real, documented, intended production model is
**exactly one Jarvis CLI process is the sole actor in the
approve-to-resume path** at any time; the two other processes that
share the database never touch this path. The absence of enforcement
is a real gap this correction closes explicitly (Section 7).

**Selected: Design A - single-process, startup-exclusive recovery.**
Design B (claim tokens/leases) is rejected as disproportionate: there
is no genuine, intended concurrent-claimant scenario to defend against,
and Design A's own requirements are fully satisfiable given this
evidence.

### Design A requirements, satisfied

- CLAIMED recovery runs only inside the existing, one-time
  `reload_pending()` startup pass (Section 8) - never during live
  operation.
- Recovery completes before `cli.run()` begins (unchanged ordering,
  confirmed in `main.py`).
- No live claimant can exist during that pass, by construction (the
  loop that would create one has not started).
- An ordinary reload/list operation (`PendingApprovalStore.get()`/
  `.list_all()`) never itself mutates `handoff_status` - only the
  dedicated startup-recovery pass inside `reload_pending()` does.
- Concurrent calls *within* the one running process remain protected
  by the database-level CAS (Section 9) regardless - defense in depth,
  not required by the process model alone, but free and already
  designed in.
- **New, explicit documentation requirement**: this correction's own
  module docstrings must state plainly that running two Jarvis CLI
  processes concurrently against the same database is **unsupported**
  for the approval/workflow path (the dashboard and scheduler remain
  fully supported, since neither touches it).

### Exact stale-CLAIMED rule

- **Who judges staleness**: `ApprovalManager.reload_pending()`'s own
  startup-recovery pass, and only that pass.
- **When**: once, synchronously, during `build_orchestrator()`, before
  `cli.run()` begins.
- **What evidence**: the row's own `handoff_status == CLAIMED`,
  observed at the moment this pass runs. Under the single-process
  model, this is sufficient and complete evidence by itself: the
  *current* process could not yet have created a `CLAIMED` row (its own
  interactive loop has not started), so any `CLAIMED` row found here
  can only be inherited from a *prior* run of this same process that
  did not reach a terminal state before exiting.
- **How a live claimant is protected from false interruption**: there
  is no live claimant to protect against at this exact moment, by
  definition of when this pass runs - it executes strictly before any
  claim in this process could exist.

## 3. Current approval-to-resume sequence

Unchanged from the prior draft (Section 3 there); re-confirmed here.

## 4. Current durable records after approval / transaction boundaries

Unchanged from the prior draft (Sections 4-5 there): one shared SQLite
database, but no shared transaction boundary across stores today; each
store's own methods always open and commit their own `session_scope()`.

## 5. Approval-history authority and consistency (Mandatory gap 4)

Directly re-inspected `ApprovalManager._decide()`'s exact call order:
`self._audit()` (generic event log) → `self._record_history_decision()`
(durable `approval_history` write) → `self._remove_pending_state()`
(today: delete). `_record_history_request()` already writes a
"pending" `approval_history` row at *request creation* time, before any
decision - `record_decision()` therefore always *updates* an existing,
`request_id`-keyed row, never inserts a fresh one for the decision
itself; this is confirmed to already be naturally idempotent by
identity (re-applying the same update is a no-op change, not a
duplicate row).

**Answers to the seven required questions:**

1. Today, `approval_history` is written *before* the pending row is
   deleted (both inside the same `_decide()` call, no crash window
   possible between them today since nothing yields control between
   the two calls - this ordering is unaffected by this correction).
2. **Under the new design**: the authoritative handoff transition
   (`PENDING → APPROVED_UNCONSUMED`) is applied **first**; the
   `approval_history` update is applied **second**. Reasoning below.
3. If the first commit (handoff transition) succeeds and the second
   (history update) fails: the row is durably, correctly
   `APPROVED_UNCONSUMED` (safe, resumable, authoritative); `approval_history`
   still shows "pending" until repaired (Section "repair," below) - an
   *incomplete* audit view, never an *actively wrong* one, and never a
   safety issue, since nothing reads `approval_history` to decide
   claim eligibility.
4. Yes, `approval_history` can transiently show "pending" while the
   handoff is `APPROVED_UNCONSUMED` (case 3) - always self-correcting
   via the repair pass, never silently permanent.
5. No - the reverse ordering (history-first) was considered and
   rejected specifically because it could leave `approval_history`
   durably claiming "approved" while the authoritative handoff was
   still `PENDING` and could later be legitimately declined/expired -
   an actual, permanent contradiction in the historical record, which
   the chosen ordering cannot produce.
6. No - `approve()`'s own precondition (`handoff_status == PENDING`)
   means a genuine retry of the *whole* `approve()` call after its
   first success always fails immediately (CAS precondition no longer
   holds); only the narrow, internal "did the history update also
   apply" question needs idempotent repair, never a duplicate decision.
7. The **handoff state** (`pending_approval_state.handoff_status`)
   alone is authoritative for claim eligibility - `approval_history` is
   never consulted by `claim_for_resume()`.
8. **Repair**: the same startup `reload_pending()` pass that performs
   recovery (Section 8) also checks, for every row whose handoff status
   is `APPROVED_UNCONSUMED`/`CLAIMED`/`CONSUMED`, whether
   `approval_history` already reflects "approved" for that
   `request_id`; if not, it idempotently backfills it using the
   authoritative handoff state as the source of truth (an `UPDATE`
   keyed by `request_id`, never an `INSERT` of a second row). A
   genuinely contradictory pair (structurally should not occur given
   the chosen ordering, but defended against) is *reported* (a distinct
   audit entry) and resolved in the handoff state's own favor for claim
   eligibility - never silently ignored, never allowed to block
   legitimate recovery.

**Selected: Design B - authoritative transition plus idempotent history
recording.** Design A (one shared transaction) was assessed and
rejected: it would require introducing cross-store session-sharing
machinery the repository does not have today (Section 4), to protect
an audit-only table that never governs safety - disproportionate to the
actual requirement.

## 6. Exact final handoff state model (Mandatory gap 5)

A deliberately **minimal** set - each justified by a distinct recovery
need traced above, not added for theoretical completeness:

- `PENDING` - unchanged from today.
- `APPROVED_UNCONSUMED` - decided approved; execution handoff not yet
  claimed. *(The fix.)*
- `CLAIMED` - exactly one caller holds the right to attempt execution;
  covers the entire span from "about to call `resume()`/`ToolExecutor.execute()`"
  through "outcome not yet durably finalized." No separate
  `EXECUTION_STARTED` state is introduced: `workflow_step_started`
  history writes are wrapped in a swallowing `try/except`
  (`WorkflowEngine._record_history()`'s own, already-existing,
  documented behavior), so their *absence* is never reliable proof
  execution did not begin - a finer-grained state here would buy no
  additional, trustworthy recovery precision, only false confidence.
- `CONSUMED` - ownership fully, terminally transferred: the approval
  can never be claimed or reused again, **regardless of whether the
  underlying action ultimately succeeded or failed**. The
  success/failure *fact itself* is deliberately **not** duplicated onto
  this column - it is already owned, authoritatively, by
  `WorkflowHistoryStore`/`WorkflowResult` (for a workflow) or by the
  caller's own immediate, synchronous knowledge (for a direct tool
  call); duplicating it here would be redundant persisted data with no
  recovery use this design requires (Gap 5's own "use only states
  justified by actual recovery needs").
- `CLAIM_INTERRUPTED` - a `CLAIMED` row found, at restart, with no
  positive, authoritative evidence of a terminal outcome (Section 9).
  Terminal for automation; not terminal in the database sense (see
  Section 9's own bounded lifecycle).
- `DECLINED` / `EXPIRED` - unchanged, terminal, row deleted immediately
  exactly as today (a declined or expired request was never approved,
  so none of this new machinery ever applies to it).

`CLAIMED` and `CONSUMED` are never conflated: `CLAIMED` means ownership
acquired, outcome pending; `CONSUMED` means a terminal outcome (of any
kind) is now durably reflected elsewhere and this approval is retired.

## 7. Exact consumption semantics

- **Decision** (user approved): `PENDING → APPROVED_UNCONSUMED`, inside
  `ApprovalManager.approve()` (renamed internally from today's
  `_decide()` deletion behavior).
- **Claim** (one caller owns the right to attempt resume):
  `APPROVED_UNCONSUMED → CLAIMED`, via the new
  `ApprovalManager.claim_for_resume(request_id)`, called as the first
  action inside `core/orchestrator.py`'s `execute_approved()` - the one
  existing choke-point already common to both workflow-linked and
  plain single-tool YELLOW approvals.
- **Consumed** (non-reusable execution lifecycle entered, terminal
  outcome not implied): `CLAIMED → CONSUMED`, applied synchronously by
  `execute_approved()` immediately after `resume()`/`ToolExecutor.execute()`
  returns - **before** the final `JarvisResponse` is constructed or
  delivered (Section 9's own transition-matrix cases 3-4, 8).
- **Completed** (terminal outcome known): never a separate handoff
  column - always read from `WorkflowHistoryStore.latest_status_for(workflow_id)`
  (a workflow) or the caller's own immediate `ToolResult` (a direct
  tool call), both already-existing, unchanged sources of truth.

## 8. Claim ownership / exact claim transaction

Unchanged from the prior draft's own design (Section 9 there):

```sql
UPDATE pending_approval_state
SET handoff_status = 'claimed'
WHERE request_id = ? AND handoff_status = 'approved_unconsumed'
```

`rowcount == 1` → exclusive success; `rowcount == 0` → rejected,
`ApprovalError` raised, nothing further attempted. No owner/claim
token is introduced (Section 2's single-process finding makes one
unnecessary); no read-then-write race; `request_id`/`workflow_id`/
`tool_input_json` remain immutable through every transition (no claim
operation ever writes to them).

## 9. Post-claim transition matrix (Mandatory gap 3)

| Scenario | Handoff transition | Paused workflow | Audit |
|---|---|---|---|
| Claim succeeds, paused workflow missing | `CLAIMED → CLAIM_INTERRUPTED` (synchronous, not a crash-recovery case - discovered immediately) | none to clean up | honest entry: "linked paused workflow missing" |
| Claim succeeds, `WorkflowEngine` rejects before any tool executes (invalid plan, incompatible payload) | `CLAIMED → CLAIM_INTERRUPTED` | retained, invalidation reason recorded | honest entry: "plan rejected before execution" |
| Tool execution begins, ordinary failure (known, synchronous) | `CLAIMED → CONSUMED` | already deleted by existing `resume()` logic (unchanged) | unchanged existing behavior |
| Execution + verification finish with a known failure (mismatch/unavailable) | `CLAIMED → CONSUMED` | already deleted (unchanged) | unchanged existing behavior (e.g. today's FOCUS/PHASE response builders) |
| Workflow completes successfully | `CLAIMED → CONSUMED`, applied by `execute_approved()` immediately after `resume()` returns, before building the final response | already deleted (unchanged, at `resume()` entry) | unchanged existing `workflow_completed` entry |
| **Crash after workflow success, before handoff marked consumed** | See Section "Terminal reconciliation" below - the mandatory case | already deleted (unchanged) | `workflow_completed` entry already durably present |
| Crash after execution failure, before handoff terminal update | Same reconciliation rule (checks for `workflow_stopped` too) | already deleted (unchanged) | `workflow_stopped` entry already durably present |
| Handoff marked consumed, response delivery fails | No further transition - already terminal `CONSUMED` | unaffected | unaffected |

### Terminal reconciliation (the mandatory crash case)

Confirmed directly: `WorkflowHistoryStore.latest_status_for(workflow_id)`
**already exists**, unchanged, as a plain, read-only query returning
the most recent transition for a `workflow_id`. This is a **one-directional**,
reliable signal: if it returns `workflow_completed` or `workflow_stopped`,
that transition genuinely, durably happened (a `WorkflowHistoryStore`
write is never fabricated) - but its *absence* is **not** reliable proof
nothing happened (`_record_history()`'s own swallowed-exception design
means a real completion's history write could itself have failed).

**The reconciliation rule uses only the reliable direction**: on
restart, for any row found `CLAIMED`, if `latest_status_for(workflow_id)`
returns a terminal status (`workflow_completed` or `workflow_stopped`),
reconcile directly to `CONSUMED` - genuine, positive evidence, no
ambiguity, no need for `CLAIM_INTERRUPTED`. If it returns anything else
(including `None`), fall back to `CLAIM_INTERRUPTED` - absence of
evidence is never treated as evidence of absence.

**This mechanism is asymmetric between workflow-linked and plain
single-tool approvals**, stated honestly: a plain (non-workflow) YELLOW
approval has no `workflow_id`/`workflow_history` trail at all, so it has
no equivalent positive-evidence source available today - such a claim,
if interrupted, always falls back to `CLAIM_INTERRUPTED` regardless of
whether the tool actually completed. This is always *safe* (never risks
replaying a write) though less *precise* than the workflow-linked case;
closing this asymmetry is explicitly out of scope for this correction.

## 10. Interrupted-state lifecycle (Mandatory gap 2)

**Selected: Option A - terminal manual-review state**, as the required
default for every existing capability (no exact reconciliation strategy
exists for arbitrary tools, per Section 9's asymmetry finding above).
Option C (safe pre-execution reset via workflow-history absence) is
**rejected**: absence of a `workflow_history` row is not authoritative,
for the same reason given above - `_record_history()`'s own swallowed
exceptions mean a real, started execution could produce no history
trace at all. Inferring "never started" from that absence would be
exactly the unsafe inference the task explicitly forbids.

**Exact contract**: `CLAIM_INTERRUPTED` means - approval was granted;
one claimant acquired execution rights; final execution outcome cannot
be proven from authoritative handoff state; automatic replay is
prohibited; the old approval can never be reused (`claim_for_resume()`'s
own CAS precondition structurally excludes it, permanently).

- **Cannot be claimed again**: `claim_for_resume()`'s precondition
  (`handoff_status == APPROVED_UNCONSUMED`) excludes it.
- **Cannot return to `APPROVED_UNCONSUMED`**: no code path performs
  this transition for the generic case (Option C rejected above).
- **Cannot be declined or expired**: both require `PENDING`.
- **The linked paused workflow is retained, not deleted**: a small,
  additive refinement to `WorkflowEngine._try_reconstruct_paused_workflow()`'s
  own existing two-way check (pending vs. not-pending) into a
  three-way check: still `PENDING` → reconstruct as resumable
  (unchanged); linked approval is `DECLINED`/`EXPIRED` → invalidate and
  delete exactly as today (unchanged); linked approval is
  `APPROVED_UNCONSUMED`/`CLAIMED`/`CONSUMED`/`CLAIM_INTERRUPTED` → leave
  the `paused_workflow_state` row untouched, do not add it to
  `self._paused`, do not delete it. This is the only way the exact
  approved tool arguments remain durably, physically inspectable (via
  `PausedWorkflowStore.get()`/`.list_all()`, already-existing) after an
  interruption - `workflow_history` deliberately never stores
  `tool_input` at all, so relying on it alone would silently discard
  the approved arguments.
- **A new request requires a new approval**: unchanged - re-issuing the
  same natural-language request creates an entirely new, independent
  approval/paused-workflow pair; the quarantined pair is never reused.
- **Cleanup is explicit, not automatic**: this correction never
  auto-deletes a `CLAIM_INTERRUPTED` row or its retained paused
  workflow. Indefinite retention, pending a future, separately-approved,
  explicit operator-facing cleanup/inspection design, is the correct,
  honest answer for this phase - never silent purging.

### Visibility

- **Approval history**: the startup-recovery pass that produces
  `CLAIM_INTERRUPTED` also writes one honest, distinct
  `approval_history` entry (reusing the existing `record_timeout()`-shaped
  write, exactly like today's reload-invalidation path already does),
  visible via the existing `show approval history` command - no new
  user-facing surface needed.
- **Workflow history**: unaffected/unchanged for a workflow whose
  linked approval becomes `CLAIM_INTERRUPTED` - its own prior entries
  (whatever real steps did complete) remain exactly as recorded.
- **Paused-workflow inspection**: the retained row is queryable via
  existing store methods, not yet exposed as its own user command
  (consistent with adding no new user-facing surface during planning).
- No new user-facing command is proposed in this planning gate.

## 11. Startup recovery behavior (exact)

`ApprovalManager.reload_pending()` gains one additional pass, after its
existing pending-row revalidation, iterating every row whose
`handoff_status` is `CLAIMED`:

1. If `WorkflowHistoryStore.latest_status_for(workflow_id)` (when the
   row is workflow-linked) shows a terminal status → `CLAIMED → CONSUMED`.
2. Otherwise → `CLAIMED → CLAIM_INTERRUPTED`, plus the paused-workflow
   retention behavior (Section 10) and the `approval_history` entry
   (Section 10's "Visibility").

A second pass also repairs any `approval_history` row not yet reflecting
an already-authoritative `APPROVED_UNCONSUMED`/`CLAIMED`/`CONSUMED`
handoff state (Section 5's idempotent repair).

Neither pass ever auto-claims, auto-resumes, or auto-executes anything -
both only ever adjust durable bookkeeping to honestly reflect what is
already, separately known to be true.

## 12. Expiry and decline semantics

Unchanged in substance from the prior draft (Section 12 there),
re-confirmed correct given the refined state model: pending may be
declined or expire; approved-unconsumed/claimed/consumed/interrupted
can never be declined or expire (all are already outside
`self._pending` the moment a decision is made, exactly as today -
`_sweep_expired()` is untouched).

## 13. Backward compatibility

Unchanged in substance from the prior draft (Section 14 there): one new
column, `pending_approval_state.handoff_status`, migrated via the same,
already-proven guarded `ALTER TABLE ... DEFAULT` pattern
(`_ensure_memory_category_column()`), defaulting existing rows to
`'pending'` - exactly and only what they already, implicitly meant
under today's code.

## 14. Migration assessment

Unchanged: **required**, one column, one guarded, idempotent
`ALTER TABLE` statement, zero risk to any other table or existing row's
meaning.

## 15. Existing YELLOW workflow guarantees (Mandatory gap 6)

For `PROJECT_STATE_UPDATE_FOCUS`, `PROJECT_STATE_UPDATE_PHASE`,
`SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`:

**Guaranteed**: an approved-before-claim workflow survives a restart
and is discoverable (never silently discarded); no second approval is
ever required to complete an already-approved action; approved
arguments remain immutable through every transition; exactly one
claimant wins a race, ever; a duplicate claim is always rejected; an
approval can never be redirected to a different workflow or request.

**Not automatically guaranteed**: exactly-once tool execution for a
crash occurring strictly *after* a claim is acquired but *before* a
terminal outcome is durably confirmable (Section 9's asymmetry: only
the workflow-linked case, and only when its own `workflow_history`
happens to have durably recorded a terminal transition, can be
automatically reconciled - a plain single-tool approval, or a workflow
whose terminal history write itself silently failed, falls back to the
honest, non-automatic `CLAIM_INTERRUPTED` review state); no automatic
replay of an interrupted write, ever; no claim that a tool "ran exactly
once" is ever made without direct, positive evidence.

**Precise wording for this correction**: it delivers **"durable
approved-to-claim handoff safety"** - not "complete crash-safe
execution." The distinction is deliberate and load-bearing.

## 16. Future Phase 98 compound integration

Unchanged in conclusion from the prior draft: the future compound
Batch 2 design calls `claim_for_resume()` like any other capability,
then locates its own `CompoundWorkflowProgress` row and resumes from
the durable next step. Additionally, and newly clarified by this
amendment: the future compound consumer *can*, in its own separately-
approved batch, use `reconcile_phase_update()` (already built, already
tested, Batch 1) to narrow a `CLAIM_INTERRUPTED` compound workflow down
to a confirmed continuation point - this is Option B from Mandatory
gap 2's own menu, legitimately available *only* to this one consumer
because it alone has an exact, trusted reconciliation strategy; every
other existing capability correctly remains on the universal, safe
`CLAIM_INTERRUPTED` review path.

## 17. Selected outcome

**Final Outcome B - split foundations**, given the amount of
independently-testable, sequentially-dependent machinery now specified
(schema/state model, claim API/startup recovery/interrupted-state
lifecycle, and orchestrator wiring/full regression) - each batch
should be provable in isolation before the next depends on it.

## 18. Revised phase size and batches

**Large/risky - three batches** (unchanged classification, refined
structure):

- **Batch 1**: `pending_approval_state.handoff_status` column +
  migration; `PendingApprovalHandoffStatus` enum; `PendingApprovalStore`
  CAS methods (transition + claim); `approval_history` idempotent-repair
  helper. No `ApprovalManager`/orchestrator behavior change yet -
  purely additive schema and store-level primitives, fully unit-tested
  in isolation.
- **Batch 2**: `ApprovalManager.approve()`/`claim_for_resume()`/
  `reload_pending()` (startup recovery + terminal reconciliation via
  `latest_status_for()` + interrupted-state handling);
  `WorkflowEngine._try_reconstruct_paused_workflow()`'s three-way
  retention refinement. Complete regression for every existing YELLOW
  capability (decline, expiry, restart, duplicate-resume, duplicate
  claim).
- **Batch 3**: `core/orchestrator.py`'s `execute_approved()` wiring
  (calls `claim_for_resume()` first; marks `CONSUMED` after
  execution); full end-to-end crash-window tests; explicit,
  documented single-process-model statement; full three-environment
  regression; closure.

## 19. Updated required tests

All 42 items the task requires map onto the three batches: schema/CAS/
migration tests (Batch 1, items covering compatibility and claim
ownership mechanics); `ApprovalManager` transition, history-consistency,
startup-recovery, interrupted-claim, and per-capability regression
tests (Batch 2); orchestrator wiring, full post-claim transition-matrix,
and full-suite/Ruff verification (Batch 3).

## 20. Updated acceptance criteria

All required tests pass; every existing YELLOW capability's own test
suite passes (with the narrow, expected update noted for any test
asserting immediate row deletion on approval); a fresh database and an
existing pre-correction database behave identically after migration;
the documented single-process assumption is stated explicitly in the
shipped module docstrings; Ruff and `git diff --check` clean.

## 21. Updated risks and mitigations

- **Risk**: `latest_status_for()` is later found to have an edge case
  making its terminal-status read unreliable. **Mitigation**: this
  amendment relies only on its *positive* signal (presence of a
  terminal row), never its absence - the one-directional design is
  robust to any additional, yet-undiscovered way a write could fail to
  happen, since absence already defaults to the safe path.
- **Risk**: `CLAIM_INTERRUPTED`/retained paused-workflow rows
  accumulate indefinitely with no cleanup. **Mitigation**: explicitly
  named as out of scope (Section 10), a candidate for a future,
  separately-approved operator-facing follow-up.
- **Risk**: a second Jarvis CLI process is started against the same
  database despite being unsupported. **Mitigation**: explicitly
  documented as unsupported (Section 2); the CAS-based claim mechanism
  still provides defense in depth even in that unsupported scenario
  (it would simply make the startup-recovery pass's own "stale means
  found-at-startup" assumption unsound - a documented limitation, not
  a silent one).

## 22. Updated stop conditions

Unchanged in spirit from the prior draft, refined: stop if the
migration cannot be made additive/backward-compatible; the claim CAS
cannot guarantee exclusivity; `CLAIMED` rows cannot be durably
distinguished from `APPROVED_UNCONSUMED`; any existing YELLOW
capability's execution/verification behavior would need to change;
`workflow_history` would need to become authoritative (rather than a
one-directional corroborating signal); a cross-store atomic transaction
becomes unavoidable; `CLAIM_INTERRUPTED` has no terminal/review path;
approval history and handoff state may contradict without detection or
repair; duplicate history decisions can be inserted; claim success and
terminal outcome are collapsed into one misleading status; or a
successful workflow could be replayed after a terminal-update crash.

## 23. Manual Anthropic limitation

Unchanged: live Anthropic manual acceptance remains postponed
(insufficient API credits, an external limitation). No production
change may bypass it. This correction must be, and will be, proven
entirely with deterministic, repository-level tests.

## 24. Formal amendment conclusion

Every mandatory gap is resolved with a concrete, code-grounded design:
a single-process recovery model justified by direct inspection of the
real (and only) call site; a minimal, non-conflated state model; an
honest, one-directional terminal-reconciliation rule using an
already-existing store method; and an explicit, permanent,
non-automatic review path for the one case (arbitrary interrupted
writes) that cannot be safely automated. Recommended as a three-batch,
large/risky future phase - not implemented in this planning gate.
