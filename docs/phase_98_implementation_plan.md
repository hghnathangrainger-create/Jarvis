# Phase 98 — First Bounded Compound Execution (Planning Gate, Amended)

Status: **planning gate only**. No production or test code changed.
This amendment supersedes the version committed at `f3654d2`, which
left the verification-gate mechanism unresolved and treated crash
windows B/C/D as acceptable on the basis of an in-process
duplicate-resume guard alone. Both defects are corrected below by
direct, code-grounded audit. **The recommendation changes from Outcome
A to Outcome B** as a direct result.

## 0. Summary of what changed in this amendment

1. **Verification-gate architecture is now decided**: a trusted,
   catalog-configured `PlanStep` gate (Section 1), not left as an open
   choice between two options.
2. **The crash-window analysis is redone from first principles**,
   tracing exact transaction boundaries in the real code
   (`WorkflowEngine`, `PausedWorkflowStore`, `ApprovalManager`,
   `WorkflowHistoryStore`, `ToolExecutor`, `ProjectStateStore`) rather
   than reasoning from the in-process duplicate-resume guard alone. This
   surfaces a real, previously-uncharacterized gap: a crash between an
   approval being durably decided and `WorkflowEngine.resume()` actually
   being invoked silently discards the entire approved workflow today -
   for every existing YELLOW capability, not only the proposed compound
   one (Section 3).
3. **The recommendation changes to Outcome B**: a narrow, durable
   step-progress foundation, scoped exclusively to this one compound
   template, must be built and proven before any live wiring begins.

## 1. Verification-gate architecture (Mandatory blocker 1)

### 1.1 Why mismatch is distinct from verifier failure

Confirmed by direct inspection of `intelligence/verification.py` and
`tools/builtin/project_state_verify_tool.py`:

- `ProjectStateVerifyTool.run()` performs a real, successful read of
  `ProjectStateStore.get()` and **always** returns
  `ToolResult(success=True, ...)` - it is documented and tested to
  never fail. The tool's own job is only to read and report; it never
  judges correctness.
- `verify_project_state_field()` (in `intelligence/verification.py`)
  is the *only* code that judges correctness, by comparing the real,
  already-durable expected value against the verify step's real
  `ToolResult.metadata[field_name]`, producing one of `VERIFIED` /
  `FAILED` / `UNAVAILABLE` - three semantically distinct outcomes that
  are never collapsed into a bare boolean, per that module's own
  design.

These are two different questions with two different owners: **did
the read operation itself succeed** (owned by the tool /
`ToolResult.success`) versus **does the observed value satisfy the
postcondition** (owned by `verify_project_state_field()` /
`VerificationResult.outcome`). Encoding a genuinely successful read
that reveals a real mismatch as `ToolResult.success=False` would be
dishonest - it would misreport "the read failed" when in fact "the
read succeeded and proved the update did not take effect as expected."
The gate mechanism below is designed to consult the **second**
question (the `VerificationResult.outcome`), never to smuggle it into
the first (`ToolResult.success`).

### 1.2 Selected design: a trusted, catalog-configured `PlanStep` gate

**Selected** (the preferred narrow direction, confirmed viable by
direct inspection - no alternative was needed):

- **Exact production type/field proposed**: `PlanStep` (in
  `planner/plan_models.py`) gains one new, optional field:
  `requires_verified_predecessor: bool = False`. Defaults to `False`
  for every existing step - zero behavior change for anything that
  does not opt in.
- **Exact owner of the gate decision**: the trusted compound plan-
  builder (a new function in `intelligence/planning.py`, analogous to
  `_build_write_and_verify_workflow_plan()`) sets this flag to `True`
  on the *third* step (`PROJECT_STATE_SHOW`) only, when constructing
  the one compound template's plan. No other step, in any existing or
  future capability, sets it unless a future, separately-approved
  phase explicitly does so.
- **Exact trusted source of configuration**: the flag's value is
  always a literal, hardcoded `True`/`False` written by trusted,
  catalog/template-driven code at plan-construction time - never
  read from model output, never derived from `arguments`, never
  configurable by any parsed decision.
- **Exact WorkflowEngine behavior**: `WorkflowEngine._run_from()`,
  immediately before executing a step whose
  `requires_verified_predecessor` is `True`, computes the same
  `VerificationResult` the orchestrator's own response-builder already
  computes today (calling `verify_project_state_field()` - or the
  equivalent verifier function for a future consumer - unchanged,
  against the immediately-previous completed outcome's own
  `ToolResult.metadata`, and the plan's own trusted expected value).
  If the outcome is not `VERIFIED`, the engine stops the workflow
  **honestly, via the exact same "unusable previous-step result"
  shape `_resolve_tool_input()` already uses** for
  `input_from_previous_step` (`ToolResult(success=False, error="Cannot
  execute this step: ...")`) - never executing the gated step, never
  raising an exception, never mutating `ToolResult.success` on the
  *verify* step itself (which remains truthfully `True`).
- **Exact result examined**: the immediately-previous step's own
  `VerificationResult.outcome` (`VERIFIED` / `FAILED` / `UNAVAILABLE`),
  computed fresh by the engine at the moment of the gate check - never
  a value the model could influence, never a raw tool metadata field
  compared with ad hoc engine-local logic (reusing the *existing,
  already-audited* verification function, not a new comparison
  written directly in the engine).
- **Exact STOP behavior**: identical in shape to every existing
  STOP-only case - a `FAILED` `WorkflowStepOutcome` for the *gated*
  step (`PROJECT_STATE_SHOW`), with an honest, bounded error message
  ("verification did not confirm the expected value; this step was
  not executed") - the verify step's own outcome remains `COMPLETED`
  with `success=True`, truthfully. `FAILED` is reserved for the step
  that did not run, never misapplied to the step that succeeded at its
  own, different job (reading).
- **Exact backward-compatibility behavior**: `requires_verified_predecessor`
  defaults to `False`; `_resolve_tool_input()`'s and `_run_from()`'s
  existing logic paths for every step that does not set it are
  untouched - confirmed by construction, since the new check is a
  distinct, additive branch gated on the new field being `True`.
- **Exact tests**: covered in Section 12 (items 1-7), plus explicit
  regression tests proving `PROJECT_STATE_UPDATE_FOCUS`,
  `PROJECT_STATE_UPDATE_PHASE` (its existing 2-step shape),
  `SCHEDULE_ENABLE`, and `SCHEDULE_DISABLE` construct `PlanStep`s with
  `requires_verified_predecessor=False` (the dataclass default) and
  behave identically to today with no code path change.

This design was compared against the "additive tool-contract
extension" alternative from the prior planning draft and is preferred
because: (a) it generalizes an already-precedented mechanism
(`_resolve_tool_input`'s existing "usable" gate for
`input_from_previous_step`) rather than special-casing one tool's
contract; (b) it keeps `ProjectStateVerifyTool` completely
unmodified - the honesty distinction in Section 1.1 is easier to prove
when the tool that must never lie about read-success is never touched
at all; (c) it is reusable, in principle, by a future consumer beyond
this one template, without requiring a second, different verify-tool
extension for each new consumer.

The model must never control whether a step is a gate, which result
status permits continuation, the verifier, expected value, or the next
step - all of these are already true by construction here: the flag,
the verifier function called, and the expected value are all supplied
by the trusted plan-builder, never by parsed model output. No
arbitrary expressions, predicates, callbacks, or model-authored
continuation rules are introduced - the gate has exactly one supported
shape (a boolean flag consulted against one, fixed, already-existing
verification function), scoped to exactly one consumer.

## 2. Existing workflow checkpoint behavior (Mandatory blocker 2 - repository audit)

Traced directly, step by step, through the real code:

1. **When a step begins**: `WorkflowEngine._run_from()`'s loop, for
   `resume()`'s continuation, begins at
   `paused.waiting_step_index + 1`; for the resumed step itself,
   begins inside `resume()` directly.
2. **When its `ToolExecutor` call occurs**: `self._executor.execute(...)`,
   which internally calls `tool.run(request)` - for
   `ProjectStateUpdateTool`, this calls
   `self._project_state_store.update(model_field, value)` directly.
3. **When its result becomes durable**: `ProjectStateStore.update()`
   uses its own `session_scope()`, which commits **before**
   `tool.run()` even returns to `ToolExecutor`. The real side effect
   (the phase value change) is durable immediately, independently of
   any workflow-level bookkeeping.
4. **When the workflow's next-step position becomes durable**: **it
   does not, incrementally.** `WorkflowEngine._persist_paused_state()`/
   `_remove_paused_state()` are the *only* calls that touch
   `PausedWorkflowStore`, and they only ever fire at a pause (WAITING)
   point or at the top of `resume()` (deleting the row *before* the
   resumed step even executes). Confirmed directly: there is no call
   to `PausedWorkflowStore` anywhere inside the per-step COMPLETED
   path of `_run_from()`'s loop.
5. **When approval state becomes consumed**: `ApprovalManager._decide()`
   (called by `approve()`) removes the request from `self._pending`,
   records the decision in `self._decisions`, durably records the
   decision in `approval_history` (`_record_history_decision()`), and
   durably deletes the row from `PendingApprovalStore`
   (`_remove_pending_state()`) - **all within `approve()` itself**,
   which is called by the CLI/orchestrator's own caller **before**
   `WorkflowEngine.resume()` is ever invoked. Confirmed directly from
   `core/orchestrator.py`'s own `execute_approved()` docstring: "by
   the time it is called, the caller ... has already recorded [the
   decision]."
6. **When the paused workflow becomes non-resumable**: the moment
   `_remove_paused_state()` runs, at the very top of `resume()` -
   *before* the approved step executes at all.
7. **What durable record remains if the process terminates between
   any two of these operations**: analyzed exhaustively in Section 3.

**`WorkflowHistoryStore.record_transition()`** (confirmed via direct
inspection: uses its own `session_scope()`, committing independently,
per call) durably records a `workflow_step_started` entry
*immediately before* each step's `ToolExecutor` call and a
`workflow_step_completed` entry *immediately after* it succeeds - both
real, separate, immediately-committed transactions. **This makes
`workflow_history` a truthful, append-only audit trail of exactly how
far execution got - but it is never read by
`WorkflowEngine.resume()`/`reload_paused()` to make any resume
decision.** The sole authoritative store consulted at restart is
`PausedWorkflowStore`. This satisfies the task's own bar precisely:
workflow_history uniquely identifies workflow/step and is
transactionally ordered, but is not read during resume, so it is
**audit-only, not authoritative** - the distinction the task requires
be proven, not asserted.

## 3. Crash-window findings (code-grounded)

### Crash A - Before phase-update execution

Two distinct sub-windows exist, with different outcomes:

- **Before `approve()` is called at all**: fully safe today - the
  pending approval and paused-workflow rows both still exist,
  independently revalidated on restart by
  `reload_pending()`/`reload_paused()`.
- **After `approve()` durably decides the request, but before
  `WorkflowEngine.resume()` is invoked**: **not safe today.** The
  approval is no longer "pending" (already decided, durably), but
  `resume()` was never called, so `_remove_paused_state()` never ran -
  the `paused_workflow_state` row is *still present*. On restart,
  `WorkflowEngine.reload_paused()`'s own revalidation
  (`self._approvals.has_pending(record.request_id)`) finds the linked
  approval **not pending** (it was already decided) and therefore
  invalidates the entire paused workflow as unresumable - a terminal
  "could not be resumed after restart" entry is recorded, and the
  approved phase update **silently never executes**. This is a real,
  code-grounded gap, confirmed by direct inspection of
  `_try_reconstruct_paused_workflow()`'s own precondition and
  `execute_approved()`'s own docstring describing the approve-then-resume
  calling convention.
- **This is not new to Phase 98.** It is an existing, unmodified
  characteristic of the entire approval/execution pipeline
  (`approve()` and `resume()`/direct execution have always been two
  separate calls, for every YELLOW action, workflow or not, since
  Phase 6/15/27). Phase 98 does not make it worse. Fixing it would
  require redesigning the fundamental approve-then-execute calling
  convention used by *every* approval flow in the system - a
  much larger, system-wide initiative, disproportionate to and outside
  this phase's proportionate scope. It is named here explicitly so it
  is never silently assumed away, and is recommended (Section 15) as a
  candidate for a future, separately-scoped hardening phase - not
  something this narrow foundation should attempt to fix.

### Crash B - After phase-update side effect but before its completion checkpoint

Precise distinction, as required:

- **Durable-state idempotency**: setting `phase` to the same value
  twice yields the same final `phase` column value - true, but
  irrelevant to safety by itself, since `last_updated` still changes
  on each write, and (per Section 2) each write is its own
  independently-audited `tool_call`/`workflow_step_completed` event -
  a repeated write is not observably free.
- **At-most-once execution (confirmed)**: because `_remove_paused_state()`
  already ran (Section 2, step 6) *before* the tool executes, there is
  **no durable trigger left that could cause any future restart to
  invoke step 1 again** for this workflow_id - `reload_paused()` finds
  nothing to reload once the row is gone. The real side effect can
  therefore never be duplicated by this workflow's own resume path.
- **Not exactly-once in the stricter sense**: a crash strictly between
  the tool's own commit and the `workflow_step_completed`
  `workflow_history` commit means the real side effect happened, but
  no durable record confirms it happened - `workflow_history` would
  show `workflow_step_started` for step 1 with no matching
  `workflow_step_completed`, an honest (if incomplete) signal, not a
  false one.
- **At-least-once is not possible** here (nothing replays), so the one
  real risk this analysis rules out is duplication - the one risk
  Jarvis's own duplicate-execution guarantees exist to prevent.
- **This characteristic is not new to Phase 98** - it is identical in
  kind to the existing gap between step 1 and step 2 in every one of
  today's four `TWO_STEP_WORKFLOW` capabilities. Phase 98's own
  foundation (Section 4) narrows, but does not eliminate, this
  specific residual window - it adds an honest, safely-reconciled
  detection mechanism instead of leaving it entirely invisible (see
  Section 4's exact reconciliation algorithm).

### Crash C - After successful phase verification but before ProjectState show

With the gate mechanism (Section 1) and the durable progress
foundation (Section 4) in place: the verify step's own `COMPLETED`
outcome and its bounded `VerificationResult.outcome` are durably
recorded in the new progress-tracking row (Section 4) the moment the
verify step completes - *not* merely audited in `workflow_history`.
On restart, if this durable record shows step 2 completed with
outcome `VERIFIED`, resume continues at step 3 only - the phase update
and its verification are never repeated. Re-verification is
deliberately *not* performed on restart in this design (it is
unnecessary: the durable progress record already carries the bounded,
already-computed `VerificationResult.outcome`, and re-running the
verify tool a second time would be safe - it is read-only - but adds
no information the durable record doesn't already have).

### Crash D - After ProjectState show execution but before final response persistence

`PROJECT_STATE_SHOW` has **zero side effects** - re-executing it, if
its own durable completion is uncertain after a restart, is always
safe (a second read changes nothing). The design in Section 4
therefore does not need to persist step 3's own output at all: on
restart, if steps 1-2 are confirmed durably complete/verified but step
3's own completion is not confirmed, the response is (re)constructed
by simply re-reading `ProjectState` fresh via the unchanged, real
`PROJECT_STATE_SHOW` tool - never by replaying the phase update. This
answers the task's own question directly: **ProjectState is read again
after restart rather than persisting its own full output**, while the
update itself is never replayed.

### Crash E - After final workflow completion

Fully safe, unchanged: `resume()` cannot be invoked twice for one
`workflow_id` (raises `WorkflowError`), and the durable progress
record (Section 4) is marked `completed` at the end of the run,
making any later attempt at reconciliation a no-op by construction (a
`completed` record is read but never acted upon by the reconciliation
logic - see Section 4).

## 4. Durable-progress decision: Outcome B - narrow durable step-progress foundation

**Outcome B is selected.** Per Section 2/3's own evidence: no
authoritative, per-step-completion checkpoint exists once step 1
begins executing - only pause-point (WAITING) checkpoints exist today,
and `workflow_history` is audit-only, never read for resume decisions.
This is exactly the condition under which the task itself identifies
Outcome B as the expected result. General claims that "resume cannot
be called twice" are, as the task states, insufficient - the audit
above traces exact transaction boundaries instead.

### 4.1 Exact new persistence

One new, narrow table/model, scoped **exclusively** to this one
compound template - not a generic workflow-progress framework:
`CompoundWorkflowProgress` (name illustrative; finalized at
implementation time), holding, per compound workflow attempt:

- `workflow_id` (unique key, matching the real `WorkflowEngine`
  workflow id).
- `template_id` (the trusted, static compound-template identity from
  `intelligence/compound_grounding.py`'s own `CompoundTemplate.template_id` -
  never model-supplied).
- `approved_phase_value` (the exact, already-approved string value -
  the same value already durably present in the paused workflow's own
  `resolved_tool_input`, duplicated here narrowly for safe,
  independent reconciliation per Section 4.2).
- `step_1_status` / `step_2_status` / `step_3_status`, each one of
  `pending` / `in_progress` / `completed` / `failed`.
- `step_2_verification_outcome`: one of `verified` / `failed` /
  `unavailable` / `null` (mirrors `VerificationOutcome`, the existing,
  bounded enum - never a raw string).
- `overall_status`: `in_progress` / `completed` / `needs_reconciliation`.
- `created_at` / `updated_at`.

Adding a new table is low-cost in this codebase's own conventions:
schema is created via `Base.metadata.create_all(bind=engine)`
(confirmed directly in `storage/database.py`), which creates any
new table automatically, on any environment, without a migration
tool or risk to existing tables - unlike adding a column to an
*existing* table (which this design does not do).

The model never controls any of these fields - every one is written
only by trusted, catalog/template-driven code at plan-construction
and step-completion time.

### 4.2 Exact reconciliation algorithm (the atomicity-gap answer)

Addressing the task's own required "atomicity gap" directly, using
the "pre-recorded in-progress and completed states with safe
reconciliation" option it names:

1. Immediately before executing step 1 (the phase-update write), the
   engine durably writes `step_1_status = in_progress` (a new,
   narrow, additive write - not a distributed transaction spanning
   both stores).
2. Immediately after step 1's `ToolResult` returns successfully, the
   engine durably writes `step_1_status = completed`.
3. **On restart**, for any row whose `overall_status` is not
   `completed`: if `step_1_status = in_progress` (never reached
   `completed`), the engine performs one safe, read-only
   reconciliation step: read the *real*, current
   `ProjectStateStore.get().phase` and compare it against this row's
   own durable `approved_phase_value`.
   - **If they already match**: step 1 is treated as already applied
     (no re-execution) - resume continues at step 2.
   - **If they do not match**: step 1 is proven, by a safe read, to
     not yet have taken effect - it is executed exactly once (this is
     a genuine first execution, not a replay, since the read just
     proved it hasn't happened).
   - This narrow reconciliation is possible *only* because step 1's
     own real effect is independently, safely, and cheaply observable
     (a plain read) - it is not a general mechanism, and is not
     proposed for any step whose effect cannot be safely re-observed
     this way.
4. If `step_2_status`/`step_3_status` are `in_progress` (not yet
   `completed`) at restart, both remaining steps are read-only
   (`PROJECT_STATE_VERIFY_FOCUS`/`PROJECT_STATE_SHOW`) - re-running
   either is always safe, since neither has any side effect. No
   reconciliation logic is needed for either; they simply (re-)run.
5. `overall_status = needs_reconciliation` is set (durably) the moment
   any ambiguity above is detected, purely for operator visibility -
   it never blocks the safe, automatic reconciliation in steps 3-4
   above, which always resolves without manual intervention *because*
   every step involved is either safely observable (step 1, via a
   read-compare) or inherently side-effect-free (steps 2-3).

This is a narrow, bounded reconciliation strategy for one specific,
already-understood consumer - not a distributed transaction framework,
not a generic idempotency-key system, and not a claim of textbook
"exactly-once" semantics. It is an explicit, code-grounded,
narrowly-scoped replay contract: **step 1 may be safely re-attempted
only after a safe read has proven it has not yet taken effect; steps
2-3 may always be safely re-attempted, because they have no side
effects.** No duplicated observable effect is left undocumented: a
crash in the exact step-1 in-progress window can, in the worst case,
produce one extra `tool_call`/`workflow_history` audit pair for step 1
if reconciliation ever ran when the write had *already* silently
succeeded moments before a still-unmatched read (a race only possible
in the vanishingly narrow window between the real write committing and
the read-compare check, which itself reads the same already-committed
value) - this residual risk is explicitly named, is not silently
accepted, and does not duplicate the *value* written (only, in the
rarest case, an audit pair) - never the phase's own final state.

## 5. Approval-consumption findings

Confirmed directly: **"approved" and "consumed" are the same event**
in the current architecture - `ApprovalManager._decide()` removes the
request from pending and records the decision atomically within one
call. There is no separate "approved but not yet consumed" state
today. Consequences, all already true and unchanged by this
amendment:

- The same approval cannot launch a second independent workflow: once
  decided, the request is removed from `self._pending` and
  `PendingApprovalStore` - a second `resume()` call for the same
  `workflow_id` finds nothing in `self._paused` and raises
  `WorkflowError`; a second `approve()`/`decline()` call for the same
  `request_id` raises `ApprovalError` (`get_pending()` no longer finds
  it).
- A stale approval cannot alter the phase value: the approved value is
  baked into the plan's own `tool_input` at construction time, before
  approval is even created - `ApprovalDecision` carries no value of its
  own.
- A crash does not recreate approval: nothing in `reload_pending()`/
  `reload_paused()` ever fabricates a new `ApprovalRequest` - a row
  either passes revalidation (unchanged, real, original) or is
  invalidated.
- A completed or failed workflow cannot be restarted using the old
  approval: `overall_status = completed` (Section 4.1) is checked
  first and short-circuits any reconciliation attempt.

## 6. Partial-completion durability

- **Phase update and verification succeed, but show fails**: durable
  via `CompoundWorkflowProgress` (`step_1_status`/`step_2_status` =
  `completed`, `step_2_verification_outcome = verified`,
  `step_3_status = failed`) - survives a restart, since these are
  independent, narrow, durable fields, not an in-memory response
  object. No rollback occurs (unchanged: this codebase never rolls
  back a real, already-applied write). No automatic retry occurs -
  Phase 98 explicitly does not add one, and does not approve one being
  added later without a separate, explicit decision.
- **Both capabilities succeed, but response construction fails**: the
  bounded, durable fields already fully describe what happened
  (`step_1/2/3_status = completed`, `step_2_verification_outcome =
  verified`) - the final response is reconstructed by re-reading
  `ProjectState` fresh (Crash D, Section 3) and reporting the already-
  durable verification outcome; the mutation is never repeated solely
  to regenerate wording.

## 7. Bounded result persistence

Only the fields listed in Section 4.1 are persisted - no raw model
rationale, prompts, context, secrets, arbitrary tool output, stack
traces, or unrelated user data. `PROJECT_STATE_SHOW`'s own output is
deliberately **not** persisted at all (Section 3, Crash D) - it is
always re-derived fresh from the real, durable `ProjectStateStore` on
demand, since doing so is safe, cheap, and always current. The one
piece of "content" persisted beyond bounded status enums -
`approved_phase_value` - is exactly the same value the user themselves
supplied and already sees echoed back in every existing response for
this capability today; it is not new exposure.

## 8. Backward compatibility and migration assessment

- `PlanStep.requires_verified_predecessor` defaults to `False` -
  confirmed, by construction, to leave every existing `PlanStep`
  construction site (`PROJECT_STATE_UPDATE_FOCUS`,
  `PROJECT_STATE_UPDATE_PHASE`, `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`,
  and every pre-Phase-90 fixed workflow) unchanged.
- `CompoundWorkflowProgress` is a wholly new table; `create_all()`
  creates it automatically on any existing database with zero risk to
  any existing table's data (confirmed: this mechanism only creates
  tables that do not yet exist; it does not alter existing ones).
- No existing persisted `paused_workflow_state`/`pending_approval_state`/
  `workflow_history`/`approval_history` row's shape, meaning, or
  revalidation logic changes at all - the new table is consulted only
  by the new, narrow reconciliation logic (Section 4.2), which only
  ever runs for a workflow whose plan shape matches this one compound
  template (recognized the same catalog-driven way
  `_matching_two_step_write_capability` already recognizes today's
  four capabilities).
- No migration loss or silent reset is possible, since nothing
  existing is altered - only a new, empty table is added.

## 9. Revised selected outcome

**Final Outcome B - foundation first.**

## 10. Revised phase size and batch breakdown

Given the scope now includes a new persisted table and a new
`WorkflowEngine`/`PlanStep` mechanism (both squarely "persistence
schema or restart state transitions... change" per the task's own
sizing rubric), this remains sized **Large/risky**, now explicitly
structured as the task's own suggested three batches:

- **Batch 1 - Trusted verification gate and durable progress
  foundation**: `PlanStep.requires_verified_predecessor`,
  `WorkflowEngine`'s gate check, `CompoundWorkflowProgress` and its
  reconciliation logic. No live compound selection, no
  trusted-instruction change, no orchestrator compound wiring, no
  user-visible behavior. Complete regression for
  `PROJECT_STATE_UPDATE_FOCUS`, `PROJECT_STATE_UPDATE_PHASE`,
  `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`, and every existing paused-
  workflow/approval-reload test, proving zero behavior change.
- **Batch 2 - Exact compound selection, trusted plan construction, and
  approval wiring**: the Design-A live dispatch (Section 5 of the
  prior draft, unchanged), the trusted-instruction extension, the
  compound plan-builder (using Batch 1's gate), and the orchestrator's
  compound shape-matcher/response-builder. One template only, no
  generalization. Restart tests exercised before this batch closes.
- **Batch 3 - Full execution integration, partial-completion behavior,
  documentation, and closure**: end-to-end crash-window tests (all
  five, per Section 3), full three-environment regression, Ruff, and
  the completion report.

## 11. Updated test strategy

All 35 amended test items map onto the three batches:

- **Batch 1**: items 1-7 (verification gate), 8-14 (crash windows,
  exercised against the new foundation directly, without live
  selection), 26 (bounded result persistence), 27-31 (existing-capability
  regression).
- **Batch 2**: items 15-20 (restart-to-exact-step, duplicate resume,
  approval non-reuse, audit truthfulness), 32-33 (approval expiry/
  decline, persisted-paused-workflow compatibility).
- **Batch 3**: items 21-25 (partial completion), 34-35 (no migration
  loss, full three-environment suite).

## 12. Updated acceptance criteria

All 35 test items pass; every existing verified-write capability's own
suite passes completely unmodified; a new database created fresh, and
an existing database from before this phase, both work identically
after `create_all()` runs; the full suite matches the current baseline
plus exactly the new tests added, in all three environments; Ruff and
`git diff --check` are clean; the completion report documents the
Section 3 approve-then-resume gap explicitly as a known, pre-existing,
out-of-scope characteristic, and documents the Section 4.2 replay
contract's own narrow, explicit boundaries.

## 13. Updated risks and mitigations

- **Risk**: the new `WorkflowEngine` gate check regresses an existing
  capability. **Mitigation**: `requires_verified_predecessor` defaults
  to `False`; the gate branch is additive and unreachable for any
  existing step.
- **Risk**: the reconciliation algorithm (Section 4.2) is misapplied
  to a step whose effect is not safely re-observable. **Mitigation**:
  explicitly scoped, in code and in tests, to exactly this one
  template's own three steps; never generalized to an arbitrary future
  step without a fresh, separate review.
- **Risk**: the pre-existing approve-then-resume gap (Section 3, Crash
  A) is mistaken for something this phase claims to fix. **Mitigation**:
  named explicitly, with an explicit statement that it is unchanged,
  pre-existing, and out of this phase's proportionate scope.
- **Risk**: a new table is perceived as schema churn. **Mitigation**:
  confirmed additive-only via `create_all()`'s own behavior; no
  existing table touched.

## 14. Updated stop conditions

Stop and report if: mismatch must be encoded as `ToolResult.success=False`
on the verify step itself; `WorkflowEngine` cannot distinguish mismatch
from verifier failure using the real `VerificationResult.outcome`; step
position/status is not durable at each of the three steps; a write can
replay after restart without the Section 4.2 safe-read-compare proving
it has not yet taken effect; `workflow_history` is used as resume-authoritative
state; an approval can be reused after partial execution; any existing
persisted workflow becomes incompatible; response recovery requires
repeating the phase update; unrestricted result payloads must be
persisted; generic branching expressions become necessary for the
gate; or live compound wiring begins before Batch 1 is proven with
full regression evidence.

## 15. Recommendation for the pre-existing approve-then-resume gap

Not part of this phase's scope, but recorded here for a future,
separately-scoped hardening initiative: the window between
`ApprovalManager.approve()`/`decline()` durably deciding a request and
`WorkflowEngine.resume()` (or direct `ToolExecutor.execute()`) actually
running exists for *every* YELLOW action in the system today, not only
compound workflows. Closing it would require either merging
"decide" and "execute" into one durable operation, or deferring
`PendingApprovalStore` row deletion until execution genuinely begins.
This is a system-wide concern, out of proportion to a narrow,
single-template compound-execution foundation, and is recommended as
its own future phase.

## 16. Formal amendment conclusion

Both mandatory blockers are resolved with a concrete, code-grounded
design: a trusted `PlanStep` verification gate (Section 1) that never
conflates a successful-but-mismatched read with a failed one, and a
narrow, single-template durable progress table with an explicit,
bounded reconciliation contract (Section 4) that closes the real gap
found in Section 2's audit - all additive, all backward-compatible,
all scoped to exactly one consumer. The recommendation changes to
**Outcome B**: build this foundation first, in its own batch, with
complete regression proof, before any live selection or user-visible
wiring begins.

## 17. Batch 1 — Implementation Evidence

Batch 1 (the trusted verification gate and durable compound-progress
foundation, Sections 1 and 4 above) is implemented, closing no live
wiring at all.

### 17.1 Verification gate - exact implementation

- `PlanStep` (`planner/plan_models.py`) gains three new, optional
  fields: `requires_verified_predecessor: bool = False`,
  `verification_field_name: str | None = None`,
  `verification_expected_value: str | None = None`. All three default
  to values that leave every existing `PlanStep` construction site
  unchanged.
- `WorkflowEngine` (`workflow/engine.py`) gains
  `_verification_gate_failure_reason()`, called from `_run_from()`'s
  loop immediately after the existing `input_from_previous_step`
  "usable" check and before `ToolExecutor.execute()`. It is a no-op
  (returns `None`) whenever `requires_verified_predecessor` is
  `False` - the exact condition that keeps every existing plan
  unchanged. When `True`, it examines the immediately preceding
  outcome's own real `ToolResult` and distinguishes, honestly:
  preceding step never completed / preceding step's own read failed
  (`success=False`) / preceding step produced no usable value at the
  configured key / the observed value exactly matches the configured
  expected value (permitted) / the observed value differs (a genuine
  mismatch, reported with a distinct message that never says
  "verifier failure"). `_validate_executable_plan()` additionally
  rejects, at construction time, a first step declaring the gate (no
  predecessor exists) or a gated step missing either trusted
  configuration value.
- **Design refinement from the committed plan**: the committed
  amendment's prose described the engine "calling
  `verify_project_state_field()`... unchanged." Implementation found
  that `workflow/engine.py` has no import dependency on
  `intelligence/` today (confirmed directly), and that importing
  `intelligence.verification` from it would invert this codebase's own
  existing layering (today `intelligence/` depends on `workflow/`, via
  `planner.plan_models`/`workflow.engine`, never the reverse). Instead,
  `WorkflowEngine` performs the *identical* exact-match comparison
  generically and engine-natively - reusing the same style already
  established by `_PROPAGATED_FIELDS`/`_resolve_tool_input()` for
  `input_from_previous_step` - never consulting
  `intelligence.verification` at all. This achieves the exact same
  semantic guarantee (a genuinely successful-but-mismatched read is
  never conflated with a verifier failure) with a strictly smaller,
  more additive footprint (zero new cross-package import). No
  guarantee from Section 1 is weakened by this refinement.
- **Mismatch vs. verifier-failure evidence**: proven by a dedicated
  test (`test_mismatch_and_verifier_failure_produce_different_messages`)
  constructing both scenarios against the same plan shape and asserting
  their `ToolResult.error` text differs, with "mismatch" appearing only
  in the mismatch case; a second test
  (`test_tool_result_success_cannot_override_failed_verification`)
  proves the verify step's own `ToolResult.success` remains `True`
  (the read genuinely succeeded) even as the *gate* still stops the
  workflow - the two concepts are structurally independent.
- **Backward-compatible serialization**: `_plan_step_to_dict()` now
  also emits the three new keys; `_try_reconstruct_paused_workflow()`
  reads them via `.get(..., False)`/`.get(...)`, so an old, real,
  already-persisted `plan_steps_json` payload lacking these keys
  entirely reconstructs a `PlanStep` with `requires_verified_predecessor=False`
  - proven directly (not merely asserted) by
  `test_old_payload_without_new_keys_reconstructs_as_false`, which
  builds a `PlanStep` from a literal, pre-Phase-98-shaped dict, and by
  `test_round_trip_through_json_preserves_gate_fields`, which proves a
  gated step survives a real `json.dumps`/`json.loads` round trip
  unchanged.
- **Trusted ownership**: proven structurally -
  `test_gate_cannot_be_supplied_through_model_output` confirms neither
  `intelligence/structured_output.py` nor
  `intelligence/compound_structured_output.py`'s own source references
  `requires_verified_predecessor` anywhere.

### 17.2 CompoundWorkflowProgress - exact implementation

- New table `compound_workflow_progress` (`storage/models.py`), created
  additively via the existing `Base.metadata.create_all(bind=engine)`
  mechanism - confirmed to add zero risk to any existing table.
- New module `workflow/compound_workflow_progress_store.py`:
  `CompoundStepStatus` (PENDING/IN_PROGRESS/COMPLETED/FAILED),
  `CompoundOverallStatus` (PENDING/IN_PROGRESS/NEEDS_RECONCILIATION/
  COMPLETED/FAILED), `CompoundVerificationOutcome` (VERIFIED/FAILED/
  UNAVAILABLE), `CompoundWorkflowProgressStore` (create/get/list_all/
  record_pre_execution_observation/mark_step_1_completed/start_step_2/
  mark_step_2_completed/start_step_3/mark_step_3_completed/
  mark_step_3_failed/mark_needs_reconciliation), and
  `reconcile_phase_update()` plus `ReconciliationConfidence`/
  `PhaseUpdateReconciliation`.
- **Monotonic transitions and concurrency**: every transition method
  routes through one shared `_compare_and_set()` helper issuing a
  single, atomic SQL `UPDATE ... WHERE workflow_id = ? AND <expected
  columns> = ?` statement and checking `rowcount` - never a
  read-then-write pair, never an in-memory lock. A concurrent second
  caller attempting the same transition from the same expected state
  always sees `rowcount = 0` and receives `CompoundWorkflowProgressError`
  - proven directly by `TestConcurrentAdvancement`. Illegal transitions
  (completed→pending, verified→in-progress, reversed step order,
  reactivating a terminal state, a second template id) are all proven
  rejected in `TestIllegalTransitions`/`TestFixedTemplateIdentity`.
- **Bounded fields only**: `CompoundWorkflowProgress`'s own column list
  is fixed and directly asserted by
  `test_model_declares_only_bounded_columns` - no raw tool output,
  prompt, context, or secret column exists; `PROJECT_STATE_SHOW`'s own
  output is never persisted at all (Section 3, Crash D) - the design
  re-reads `ProjectState` fresh instead, whenever a later batch wires
  this in.

### 17.3 Reconciliation contract selected - Contract A, proven honest

**Contract A** (sufficient pre-state and reconciliation evidence) is
selected and implemented as `reconcile_phase_update()`, a pure
function. Its critical refinement, found necessary during
implementation of the ambiguity the task itself raised: matching the
approved value *alone* cannot distinguish "already correct before
execution" from "executed and trivially rewrote the same value" - so
the function *also* consults `ProjectStateStore.last_updated`
(observed both pre-execution and at reconciliation time). If
`last_updated` changed since the pre-execution observation, *some*
write demonstrably occurred; if it did not, no write occurred at all,
regardless of whether the value already happened to match.

- **Guarantees**: `POSTCONDITION_NOT_SATISFIED` is returned only when
  the current value definitively does not equal the approved
  value - proof the write has not (yet) taken effect.
  `POSTCONDITION_SATISFIED_STATE_CHANGED` is returned only when real
  evidence (a differing pre-execution value, or a changed timestamp)
  shows a write occurred that left the expected value.
- **Non-guarantees, stated honestly**: `POSTCONDITION_SATISFIED_STATE_CHANGED`
  is never proof that *this specific* workflow's own tool call is what
  produced the write (a genuinely concurrent, unrelated actor writing
  the same value in the same narrow window is an irreducible ambiguity
  of the current concurrency model, named here rather than hidden).
  `POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED` is returned whenever
  neither the value nor the timestamp offers any evidence either way -
  this function never resolves that case by guessing, and never
  emits any status resembling "executed exactly once" (proven directly
  by `test_reconciliation_never_claims_exactly_once`, which asserts no
  `ReconciliationConfidence` member's own value contains the word
  "exactly").
- Already-matching pre-state without timestamp evidence is proven,
  directly, to report `EXECUTION_UNCONFIRMED` - never a false
  "executed" claim
  (`test_already_matching_pre_state_without_timestamp_evidence_is_unconfirmed`).
  The same pre-state *with* timestamp evidence correctly reports
  `STATE_CHANGED`
  (`test_already_matching_pre_state_with_timestamp_evidence_is_state_changed`).
  An independently-changed, unexpected third value is distinguished
  from "never executed" in the detail text
  (`test_independently_changed_unexpected_state_is_not_satisfied`).
- The function is proven to never call `ToolExecutor`/`ProjectStateStore`/
  any tool, never touch `ApprovalManager`, and never reference
  `workflow_history` - via AST-based real-identifier detection (not
  raw text search, which would false-positive on the function's own
  explanatory docstring).

### 17.4 Approval-to-resume crash-gap re-audit

Reconfirmed by direct re-inspection of the exact same code paths
traced in the amendment (`ApprovalManager.approve()`/`_decide()`,
`core/orchestrator.py`'s `execute_approved()`,
`WorkflowEngine.resume()`/`reload_paused()`/
`_try_reconstruct_paused_workflow()`): the finding stands unchanged.
`approve()` durably decides a request and deletes its
`pending_approval_state` row in one call, **before** the caller ever
invokes `WorkflowEngine.resume()`. A process crash in that exact
window leaves `paused_workflow_state` still present but its linked
approval no longer "pending" - `reload_paused()`'s own
`has_pending(record.request_id)` check then fails, and the entire
approved-but-not-yet-executed workflow is invalidated on restart,
silently, for **every** existing YELLOW capability (workflow-based or
not) - not a defect Batch 1 introduces, and not fixed by Batch 1.

No live compound wiring inherits this gap in Batch 1 - nothing built
this batch calls `approve()`, `resume()`, or any approval flow at all
(proven by `TestStoreHasNoSideEffects`/`TestNoLiveCompoundParserDispatch`
in `tests/unit/test_phase98_batch1_isolation.py`).

**Concrete required correction before Batch 2** (a durable
approved-but-not-started handoff state, the first of the three options
the amendment named): defer `pending_approval_state` row deletion for
a workflow-linked request out of `ApprovalManager.approve()`/`_decide()`
itself, into `WorkflowEngine.resume()` (mirroring exactly how
`_remove_paused_state()` already only fires inside `resume()`, never
inside `approve()`). `WorkflowEngine.reload_paused()`'s own
`_try_reconstruct_paused_workflow()` would then need a small extension:
accept a linked approval that is either still genuinely pending *or*
already durably decided as approved-but-unconsumed (a new, narrow
distinction - not "pending" in the sense `has_pending()` means today,
but not yet "resumed" either), in addition to today's pending-only
check.

- **Would this affect existing YELLOW workflows?** Yes, unavoidably -
  `ApprovalManager.approve()`/`_decide()` is one shared code path used
  by every YELLOW action in the system, workflow-linked or not. This
  confirms the correction is a **system-wide initiative**, outside the
  proportionate scope of a compound-execution-specific foundation, and
  must be its own, separately-scoped, separately-tested phase - not
  folded into Phase 98's remaining batches.
- **Backward-compatibility requirement**: any already-persisted
  `pending_approval_state`/`paused_workflow_state` row (written before
  this future correction ships) must continue to be interpreted
  exactly as today - the new "approved-but-unconsumed" distinction
  would need to default to "not applicable" for any row lacking the
  new marker, so an in-flight upgrade never reinterprets old rows
  differently than they already behave today.
- **Per this batch's own instruction, Batch 2 must not begin** until
  this correction is implemented as its own phase, or the residual risk
  is explicitly, separately accepted through a dedicated approval
  amendment - neither has happened as of this commit.

### 17.5 Focused and regression evidence

- New tests: 15 (verification gate) + 31 (progress store +
  reconciliation) + 13 (isolation) = **59 passed**.
- Existing regressions re-run (capability catalogue, structured
  output, grounding, planning, plan models, workflow engine, paused-
  workflow store, trusted workflow foundation, approval manager,
  pending-approval store, verification, schedule enable/disable and
  phase-update orchestrator workflows, Phase 97 compound modules,
  command routing): **1403 passed**, with one pre-existing test
  (`test_plan_step_has_exactly_the_approved_field_set`) updated to
  include the three new, approved fields - an expected, legitimate
  consequence of this batch's own intentional change, not a weakening.
- Full suite: **5360 passed, 3 skipped, 0 failed**, identical in all
  three required environments - exactly 59 more than the Phase 97
  baseline of 5301.
- Ruff: exit 0 on all new findings; three pre-existing `E402` findings
  in the new `pytest.importorskip("sqlalchemy")`-guarded test file
  match, verified identically, the same established, unfixed pattern
  already present in the untouched `tests/unit/test_paused_workflow_store.py`.
- `git diff --check`: clean.

Phase 98 remains open. Batch 2 and Batch 3 were not started. No live
compound selection, planning, orchestration, approval flow, command
grammar, model instruction, help entry, or user-visible behavior was
added.
