# Phase 98 Live Compound Re-entry Planning Gate

## First Live Bounded Compound Workflow After Handoff Interlock Closure

Planning-only. No production code or tests are changed by this
document. Phase 98 remains open; nothing here is an implementation.

## 0. Amendment summary (supersedes the design in commit `aa92241`)

The original version of this document (committed at `aa92241`)
proposed persisting `CompoundWorkflowProgress` transitions as "one
CAS-guarded batch immediately after `resume()` returns." That design
is **corrected** here: a synchronous function can still be
interrupted (process kill, OOM, power loss) after any individual
durable write it performs, including mid-`resume()`, so deferring
every progress transition to a single post-hoc batch left every
inter-step crash window unrecorded. This amendment:

- selects **Option A** (a narrow, trusted, optional per-step
  lifecycle observer on `WorkflowEngine`, attached only to `resume()`
  calls for the one recognized compound plan) so each checkpoint is
  written durably at the exact moment it becomes true, not
  reconstructed afterward (Sections 10–12);
- reorders startup recovery so a **compound-aware CLAIMED
  reconciliation pass** runs before the existing generic CLAIMED
  fallback, using `CompoundWorkflowProgress` as trusted step-level
  evidence the generic pass cannot see (Sections 13–14);
- defines a narrow `resume_claimed_compound_workflow()` recovery path
  that can safely continue from a durable read-only step (verify or
  show) but **never** re-invokes the write step (Section 14);
- strengthens progress-row creation: a **synchronous** creation
  failure now actively invalidates the just-created approval/pause
  pair before returning (never lazily backfilled), while a **hard
  crash** in the same narrow window is repaired-or-isolated at startup,
  before any approval becomes visible (Section 15);
- adds a trusted, server-side approval-time re-validation gate that
  does not depend on the earlier creation attempt having succeeded
  (Section 16);
- defines a complete, 14-point trusted compound recognizer fingerprint,
  replacing the earlier "3 steps + tool names" shape check (Section 17);
- reassesses `CompoundWorkflowProgressStore`'s API: exactly **one**
  new primitive is required (`mark_step_1_failed`), down from the
  earlier three-primitive estimate for the store itself, but the
  engine now needs four small, additive changes instead of one
  (Section 18);
- retains **Outcome B**, with a corrected, more precisely specified
  Batch 2 scope (Section 20).

Sections 1–9, 13 (cross-store authority, restated), 16–18 (renumbered
below), and 21–26 of the `aa92241` version are otherwise unchanged and
reproduced here for a single coherent document.

## 1. Current baseline

- Branch `phase-4-ai-reasoning-and-write-actions`, HEAD `aa92241`.
- Full suite: 5507 passed, 3 skipped, 0 failed, identical under the
  normal environment, `AI_REASONING_ENABLED=false`, and
  `PYTHON_DOTENV_DISABLED=1`.

## 2. Accepted Phase 97 foundation

Unchanged from `aa92241` — `intelligence/compound_structured_output.py`
and `intelligence/compound_grounding.py` (closed at `e9365b3`) remain
isolated and reused unmodified.

## 3. Accepted Phase 98 Batch 1 foundation

Unchanged from `aa92241` — `PlanStep.requires_verified_predecessor`
and its companion fields (`planner/plan_models.py`,
`workflow/engine.py`'s `_verification_gate_failure_reason()`), and
`CompoundWorkflowProgressStore`/`reconcile_phase_update()`
(`workflow/compound_workflow_progress_store.py`), both reused with the
one additive method identified in Section 18.

## 4. Closed handoff interlock

Unchanged from `aa92241`. This amendment adds one new ordering
requirement inside it (Section 14) but changes no existing interlock
guarantee for non-compound workflows.

## 5. Exact target request

Unchanged: `PROJECT_STATE_UPDATE_PHASE` → internal trusted phase
verification → `PROJECT_STATE_SHOW`, one YELLOW approval, verifier and
final read trusted/GREEN.

## 6–9. Live-selection, grounding, trusted plan, approval semantics

Unchanged from `aa92241` (discriminator peek, unchanged Phase 97
grounding, the three-step plan, one-approval-for-free from the
engine's own per-step tier check, the approval-text extension subject
to a live YELLOW-preflight check). Not reproduced verbatim here; see
Sections 6–9 of the prior version for exact wording — this amendment
does not alter any of them.

## 10. Why synchronous `resume()` does not remove crash windows

`WorkflowEngine.resume()` and the `_run_from()` loop it delegates to
execute steps 1→2→3 within one Python call, but that call still
performs multiple, separate, independently-interruptible durable
writes in sequence: the pre-execution read, the write tool's own
database commit, the verify tool's read, the show tool's read, and
(in the corrected design) a `CompoundWorkflowProgress` CAS write after
each. A process kill, OOM, or power loss can land *between* any two of
these — "one synchronous function" describes Python's call stack, not
an atomic transaction spanning `ProjectStateStore` and
`CompoundWorkflowProgress` (two independent stores). Deferring every
progress transition to a single post-`resume()` batch meant every one
of those interruption points left **no durable trace at all** in
`CompoundWorkflowProgress` — the row would still show the state it had
before `resume()` was ever called, indistinguishable from "never
attempted." This is corrected below.

## 11. Selected checkpoint architecture — Option A: trusted step observer

**Selected over Option B** (injecting `CompoundWorkflowProgressStore`
directly into `WorkflowEngine`) because Option A keeps the engine
itself capability-ignorant — it only calls two small, generic,
already-existing-in-spirit hooks (mirroring how
`_verification_gate_failure_reason()` already returns an
optional-stop-reason shape) — while all ProjectState/compound domain
knowledge stays in a concrete observer object built and attached only
by trusted orchestrator code, for the one recognized plan. **Option C**
(durable step-by-step engine pausing) is rejected: it would require a
new approval-like or job-queue-like pause between GREEN steps, which
the task explicitly forbids ("Do not create new approvals between
GREEN steps"), and Phase 15's engine has no such primitive today.
**Option D** is rejected — Option A is a small, additive, fully
backward-compatible change (see Section 18), not a disproportionate
one.

**New Protocol** (`workflow/engine.py`):

```
class _CompoundStepObserver(Protocol):
    def before_step(self, workflow_id: str, step_index: int) -> str | None: ...
    def after_step(self, workflow_id: str, step_index: int, tool_result: ToolResult) -> str | None: ...
```

- `before_step` is called at the top of each step iteration, before
  `_resolve_tool_input`/the verification gate/`self._executor.execute()`.
  A non-`None` return is treated exactly like
  `_verification_gate_failure_reason()`'s existing non-`None` return:
  the step is never invoked; `_stop()` runs immediately with a
  synthetic `ToolResult(success=False, error=<the returned reason>)`.
- `after_step` is called from the **one, already-shared** place every
  step outcome already flows through: inside `_stop()` (covering
  decline, ordinary tool failure, blocked, and verification-gate
  failure — all four already funnel through this single existing
  method) and inside the loop's own "step succeeded, continue" branch,
  and inside the WAITING-pause branch (where the observer must itself
  recognize `tool_result.requires_confirmation is True` and do
  nothing, since nothing has executed yet). A non-`None` return from
  the success branch is treated as a checkpoint failure: WorkflowEngine
  converts it into a `_stop()` call with a synthetic failed
  `ToolResult` explaining that the tool itself may have succeeded but
  its durable checkpoint could not be recorded — **never** silently
  advancing to the next step without a confirmed checkpoint.
- **Attachment is deliberately narrow:** `run()` and `resume()` each
  gain a new, optional, keyword-only `step_observer: _CompoundStepObserver
  | None = None` parameter (and `_run_from()` gains the same,
  threaded through internally when `resume()` calls it for the
  remaining steps). Every existing call site passes nothing and is
  unaffected. **The observer is attached only to `resume()` calls, never
  to the initial `run()` call** — this template's step 1 is
  unconditionally YELLOW, so `run()` only ever produces the first
  pause without executing anything; attaching the observer there would
  risk capturing a pre-execution baseline before the real execution
  attempt (which may happen long after `run()`, if approval is
  delayed), which is not the correct baseline.
- The concrete `_CompoundProgressObserver` implementation (new,
  `core/orchestrator.py` or a small new module) owns the domain logic
  per Section 12 and holds references to `CompoundWorkflowProgressStore`
  and `ToolExecutor` (for its own extra `project_state_verify` read
  before Step 1 — never a raw store read, keeping every read audited).

## 12. Exact checkpoint code points

1. **Before Step 1 tool invocation** — `before_step(workflow_id, 0)`,
   called from `resume()`'s own inline handling of the waiting step
   (before its `self._executor.execute(...)` call). The observer
   performs one extra, audited `project_state_verify` read via
   `ToolExecutor`, then calls
   `record_pre_execution_observation(workflow_id, phase_value=...,
   last_updated=...)` — this single existing store call already
   atomically sets `step_1_status → IN_PROGRESS`, satisfying "mark
   Step 1 active" in the same write. A raised/failed call returns a
   bounded reason string, stopping before the write tool is ever
   invoked.
2. **Immediately after Step 1 returns success** —
   `after_step(workflow_id, 0, tool_result)` with `tool_result.success
   is True`, called from the loop's success-continuation branch
   (before it proceeds to step index 1) → `mark_step_1_completed()`.
3. **Immediately after Step 1 returns ordinary failure (or decline)** —
   `after_step(workflow_id, 0, tool_result)` with `tool_result.success
   is False`, called from inside `_stop()` (the one shared method
   decline/failure/blocked/gate-failure all already flow through) →
   the new `mark_step_1_failed()` (Section 18). `_stop()`'s own
   existing STOP-only policy already prevents advancing to Step 2 —
   the observer only needs to persist the terminal state, not enforce
   the stop.
4. **Before Step 2** — `before_step(workflow_id, 1)` → `start_step_2()`.
5. **Immediately after verification** — `after_step(workflow_id, 1,
   tool_result)` (the verify tool's own result), called from the same
   success-continuation branch as (2), **before** the loop advances to
   index 2 (and therefore before WorkflowEngine's own, separate,
   unchanged `_verification_gate_failure_reason()` check for Step 3
   ever runs). The observer computes `VerificationOutcome` by comparing
   `tool_result.metadata["phase"]` against Step 3's own trusted
   `verification_expected_value` (read directly off the Plan the
   observer was constructed with) → `mark_step_2_completed(outcome=...)`,
   whose existing implementation already atomically sets
   `overall_status → FAILED` for a non-VERIFIED outcome. This means the
   engine's own independent gate check (unchanged) and the persisted
   progress row always agree by construction — no separate write is
   needed when the gate subsequently stops Step 3.
6. **Before Step 3** — `before_step(workflow_id, 2)`, reached only if
   the engine's own gate already passed (i.e. verification_outcome was
   VERIFIED, already durably persisted in step 5 above) →
   `start_step_3()`.
7. **Immediately after Step 3 succeeds or fails** —
   `after_step(workflow_id, 2, tool_result)` → `mark_step_3_completed()`
   or `mark_step_3_failed()`, both of which already atomically set
   `overall_status` too (confirmed unchanged from Batch 1).
8. **Before returning the final WorkflowResult** — satisfied by
   construction: whichever of steps 2–7 above is the last one that ran
   is, by Python's own sequential execution, always called before the
   loop/`resume()` returns its `WorkflowResult` — no additional,
   separate "flush" write is required.

## 13. Checkpoint failure semantics

For every checkpoint call (`before_step`/`after_step`), on a CAS
conflict, a missing row, a wrong template, a wrong request/workflow
identity, or a database error:

- **fail closed** — the call returns a bounded, honest reason string
  (never raises past the observer boundary into engine internals in a
  way that could be misread as a tool failure);
- the engine **never advances to the next step** without a confirmed
  checkpoint — a `before_step` failure stops before the tool call; an
  `after_step` failure after a successful tool call stops via the same
  `_stop()` path, with an error distinguishing "the tool may have
  succeeded, but its checkpoint could not be recorded" from an
  ordinary tool failure;
- **no completed write is repeated automatically** — a checkpoint
  failure never causes a retry of the same step within the same call;
- the approval handoff is **left at `CLAIMED`** (the claim already
  happened before `resume()` was invoked, per the existing, unchanged
  interlock) — startup reconciliation (Section 14) is the only path
  that ever resolves it further, never an in-process retry;
- a database-level error (as opposed to an ordinary CAS rejection) is
  surfaced honestly to the caller of `resume()` — propagated, not
  swallowed, mirroring the existing `_claim_and_resume_workflow()`
  contract that a genuine infrastructure failure after claim marks
  `CLAIM_INTERRUPTED` before re-raising.

## 14. Compound-aware CLAIMED recovery before generic fallback

**Mandatory ordering** inside `main.reconcile_claimed_handoffs()`:
history repair (unchanged) → **new:**
`_reconcile_claimed_compound_workflows()` → existing
`_reconcile_claimed_rows()` (generic fallback, unchanged in its own
logic, but now only ever sees whatever the compound-aware pass did not
already resolve, since resolved rows have already transitioned out of
`CLAIMED`).

**`_reconcile_claimed_compound_workflows(pending_store, paused_store,
progress_store, workflow_history)`** — new, `main.py`. For each row
from `pending_store.list_by_handoff_status(CLAIMED)`:

1. Read `paused_store.get(workflow_id)` directly (bypassing
   `WorkflowEngine._paused`, since CLAIMED rows are deliberately never
   reconstructed into it — see `_RETAIN_WITHOUT_RESUME`). If missing/
   corrupt, or its `plan_steps` do not match the 14-point fingerprint
   (Section 17) applied to the raw persisted dicts: leave the row for
   the generic pass, unchanged.
2. If it matches: fetch `progress_store.get(workflow_id)`. If missing,
   or `template_id`/`request_id`/`workflow_id`/`approved_phase_value`
   do not all agree with the paused plan and the approval row: leave
   for the generic pass (an unrecognizable-or-invalid compound-like
   plan is explicitly required to fall through, never guessed at).
3. Otherwise, call the new **`resume_claimed_compound_workflow(...)`**
   (below) to classify/continue it. Rows it resolves to `CONSUMED` or
   `CLAIM_INTERRUPTED` are, by definition, no longer `CLAIMED` — the
   subsequent generic pass's own unchanged query naturally never sees
   them again. No exclusion list is needed.

**`resume_claimed_compound_workflow(record, progress, ...)`** — new,
narrow, `core/orchestrator.py`. Accepts only a row that already passed
the fingerprint + identity checks above. Reconstructs the Plan via a
new, additive `WorkflowEngine.reconstruct_claimed_compound_plan(record)`
method (exposing the *same* tool-registration + tier-reclassification
revalidation `_try_reconstruct_paused_workflow()` already performs
internally, as a second, public entry point usable for an inherited
`CLAIMED` row it does not otherwise touch). If revalidation fails:
`mark_claim_interrupted()` (existing, unchanged) — fail closed, never a
silent skip. Otherwise, dispatches on the progress row's own state
exactly per the crash-state matrix in Section 15 — it **never**
re-invokes Step 1's write tool under any circumstance; it only ever
(re)runs Steps 2/3 (both read-only) when the matrix says that is safe,
and otherwise marks `CLAIM_INTERRUPTED`. This is the one, narrow,
template-specific recovery path the task requires — not a general
"resume any claimed workflow" mechanism (it refuses anything that does
not pass the fingerprint check).

## 15. Exact crash-state matrix

- **No progress row:** do not execute; do not infer state. Before
  claim, this is handled by Section 16's creation/repair contract.
  After claim, a missing/unrecognizable row → `CLAIM_INTERRUPTED`
  (Section 14, step 2 above).
- **Progress exists; `step_1_status = PENDING`:** the pre-execution
  observation/active-marking checkpoint (Section 12, item 1) was never
  committed. Because that checkpoint is the *first* thing `resume()`'s
  observer does, before the write tool is ever invoked, this state is
  safe by construction: the write tool provably never ran. Step 1 may
  safely (re)begin — this is not "repeating a completed write," since
  nothing completed.
- **`step_1_status = IN_PROGRESS`:** the write may or may not have
  occurred. Run `reconcile_phase_update()` (Batch 1, unchanged) using
  the row's own durable `pre_execution_phase_value`/
  `pre_execution_last_updated` against a **fresh** `project_state_verify`
  read:
  - `POSTCONDITION_NOT_SATISFIED` → the write demonstrably did not take
    effect — a definite, negative, terminal fact. `mark_step_1_failed()`
    → handoff `CONSUMED` (a known terminal result; never implies
    success).
  - `POSTCONDITION_SATISFIED_STATE_CHANGED` (real evidence of a write:
    a differing pre-state now matching, or a changed timestamp) →
    `mark_step_1_completed()` (backfilling the missing checkpoint from
    strong evidence) → continue to Step 2 evaluation below.
  - `POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED` (already matched,
    no further evidence) → genuinely ambiguous; per the task's own
    instruction this must lead to terminal reconciliation/manual
    review, never continuation → `mark_needs_reconciliation()` (for
    operator visibility, never blocking) → handoff `CLAIM_INTERRUPTED`.
  - Never claims exactly-once execution in any branch.
- **`step_1_status = COMPLETED`:** the write is not repeated;
  proceed to Step 2.
- **`step_2_status = IN_PROGRESS`, or `step_1_status = COMPLETED` and
  `step_2_status = PENDING`:** verification is read-only and safe to
  (re)run. Call `start_step_2()` if still PENDING, re-run the verifier
  tool fresh, compute the outcome, `mark_step_2_completed(outcome=...)`.
  VERIFIED → continue to Step 3; FAILED/UNAVAILABLE → handoff
  `CONSUMED` (overall already FAILED, per the store's own atomic
  side-effect — a known, non-success terminal result).
- **`step_2_status = COMPLETED`, outcome VERIFIED,
  `step_3_status in (PENDING, IN_PROGRESS)`:** the final read is
  read-only and safe to (re)run. `start_step_3()` if PENDING, re-run
  `project_state_show` fresh (its output is never persisted),
  `mark_step_3_completed()` → handoff `CONSUMED` — this time a genuine
  success.
- **`step_3_status = COMPLETED` (`overall_status = COMPLETED`):**
  nothing to (re)run; `mark_consumed()` if the handoff has not already
  reached it. Response reconstruction, if ever needed, uses the
  progress row's own bounded state plus a fresh, always-safe
  `project_state_show` read — never a repeated mutation.
- VERIFIED is never fabricated from a bare ProjectState-value
  comparison outside the verifier tool's own real call, in any branch.

## 16. Progress creation and approval-gating contract

**Synchronous creation failure** (a catchable Python exception right
after `run()` returns `WAITING`): the compound-specific orchestrator
wrapper catches it and, in the same call, before returning anything to
the caller:

1. Calls the existing, public `ApprovalManager.invalidate_pending(
   request_id, reason="compound workflow progress could not be
   established")` — terminally isolating the approval using an
   already-existing bounded API (no new API needed for this).
2. Calls the existing, public `PausedWorkflowStore.delete(workflow_id)`
   to remove the paused state.
3. Returns an honest failure `JarvisResponse` — **never** an approval
   prompt. The user never sees an actionable approval whose progress
   foundation is missing.

**Hard crash** in the narrow window between the pause durably
committing and progress-row creation completing (unrecoverable
in-process, so no catch-block can run): detected at startup, as a new
responsibility folded into `main.reconcile_claimed_handoffs()` (running
before the interactive loop, after history repair, alongside the
CLAIMED passes — before any approval could actually be surfaced to the
user in practice): for each **PENDING** row that is workflow-linked
and whose paused plan matches the 14-point fingerprint (Section 17)
but has no matching `CompoundWorkflowProgress` row:

- **Repair:** if the workflow/request identities and the approved
  phase value can be reconstructed unambiguously from the paused
  plan's own already-durable step-1 `tool_input`, idempotently create
  the missing row now, before the approval is treated as showable.
- **Terminal isolation:** if anything is ambiguous or the paused plan
  itself is corrupt, apply the same two existing bounded APIs as the
  synchronous case above (`invalidate_pending` + `delete`) — approval
  is never permitted while progress is missing.

This is a **strengthening** over the `aa92241` version's "lazy
backfill at next touch," which is retracted for the ordinary,
catchable-exception case; lazy repair is now reserved only for the
narrower true-crash window this section describes.

## 17. Approval-time enforcement and the trusted recognizer

**Approval-time check** (new, small, orchestrator-level; does not
depend on the earlier creation attempt): before the orchestrator's own
call to `ApprovalManager.approve(request_id)` for a workflow-linked
request whose paused plan matches the fingerprint, re-fetch
`CompoundWorkflowProgressStore.get(workflow_id)` and require, freshly,
at this exact moment: `template_id == ALLOWED_TEMPLATE_ID`,
`request_id` matches, `workflow_id` matches, and
`approved_phase_value` equals the paused plan's own step-1
`tool_input["value"]`. Any mismatch refuses to call `approve()` at
all, reporting an honest failure. Batch 2 must identify the exact
existing call site(s) that invoke `ApprovalManager.approve()` today
(not verified line-by-line in this planning session) and insert this
gate there, or in a new wrapper all such call sites use for a
workflow-linked, fingerprint-matching request.

**Trusted compound recognizer — 14-point fingerprint**
(`_matching_compound_workflow_template()`, `core/orchestrator.py`,
replacing the earlier 3-steps-plus-tool-names shape check):

1. Exactly three steps.
2. Step 1 `tool_name == "project_state_update"`.
3. Step 1 `tool_input["field"] == "phase"`.
4. Step 1 `tool_input["value"]` is a non-empty, bounded string.
5. Step 2 `tool_name == "project_state_verify"`.
6. Step 2 is the same verifier Step 3 will check against (identity
   consistency, not a separate value).
7. Step 3's `verification_expected_value == Step 1's tool_input["value"]`.
8. Step 3 `tool_name == "project_state_show"`.
9. Step 3 `tool_input == {}` (no model-controlled input).
10. Step 3 `requires_verified_predecessor is True`.
11. Step 3 `verification_field_name == "phase"`.
12. Each step's stored `tier` matches its capability's
    `CAPABILITY_CATALOG` `max_execution_tier` exactly (YELLOW, GREEN,
    GREEN) — reusing the same exact-match reclassification discipline
    `_try_reconstruct_paused_workflow()` already applies to the
    waiting step, generalized here to all three persisted steps.
13. The linked `CompoundWorkflowProgress.template_id == ALLOWED_TEMPLATE_ID`.
14. The linked progress row's `workflow_id`/`request_id` match the
    approval/paused-workflow records exactly.

Any single mismatch → treat as unrecognized: execute nothing further
through the compound path, never fall back to a generic "compound
interpreter" (none exists), and become an honest
invalid/`CLAIM_INTERRUPTED`/refused state as appropriate to the
context (construction time vs. restart time).

## 18. Cross-store authority and reassessed progress-store primitives

**Cross-store authority** (unchanged from `aa92241` §13, restated with
one addition): `PendingApprovalStore` — approval/claim lifecycle.
`PausedWorkflowStore` — the exact approved plan and inputs.
`CompoundWorkflowProgress` — step-level compound recovery only, never
gating whether a workflow may be approved or resumed on its own (the
engine's verification gate and the fingerprint check are independently
sufficient for that). `WorkflowHistoryStore` — positive terminal
evidence only, never a substitute for step-level progress.
`ProjectState` — the observable durable postcondition only, never
proof of execution by itself. `VerificationResult` — Step 3
eligibility only. **New:** for the exact compound workflow, execution
may proceed only when the paused plan and the progress row agree on
template/request/workflow identity and approved phase value (Section
17, points 13–14); a mismatch fails closed at every touch point
(construction, approval, claim, and restart reconciliation alike).

**Existing `CompoundWorkflowProgressStore` methods** (all reused
unchanged): `create`, `get`, `list_all`,
`record_pre_execution_observation`, `mark_step_1_completed`,
`start_step_2`, `mark_step_2_completed`, `start_step_3`,
`mark_step_3_completed`, `mark_step_3_failed`,
`mark_needs_reconciliation`.

**Reassessed: exactly one new store method is required:**
`mark_step_1_failed(workflow_id)` — CAS `step_1_status: IN_PROGRESS →
FAILED`, `overall_status → FAILED`, mirroring `mark_step_3_failed()`'s
existing shape exactly. Reused for both an ordinary write-tool failure
and a user decline (both mean "the write never happened and never
will for this request"). No `mark_overall_failed()` is added — every
terminal path already sets `overall_status` atomically as a side
effect of one of the existing/one-new per-step methods; a generic,
arbitrary status-setter is deliberately not created.

**Reassessed engine-level additions (four, all small and additive,
all backward-compatible defaults):**

1. `_CompoundStepObserver` Protocol + `step_observer` parameter on
   `resume()`/`_run_from()` (Section 11).
2. `peek_paused_plan(workflow_id) -> Plan | None` — read-only accessor
   exposing `self._paused[workflow_id].plan`, needed so
   `_claim_and_resume_workflow()` can recognize the fingerprint (for a
   **live**, not-yet-claimed-by-a-dead-process workflow) before
   deciding whether to pass a `step_observer` into `resume()`.
3. `reconstruct_claimed_compound_plan(record) -> tuple[Plan | None,
   str | None]` — exposes the existing internal
   revalidation logic as a second, public entry point for an
   **inherited CLAIMED** row (Section 14), which `reload_paused()`
   deliberately never loads into `_paused`.
4. One additive metadata key on `ProjectStateVerifyTool.run()`'s
   result: `metadata["last_updated_at"] = record.last_updated if
   record else None` (the raw `datetime`, alongside the existing
   formatted string) — needed because the pre-execution observation
   (Section 12, item 1) requires a real `datetime`, and the tool
   today only returns a formatted string.

## 19. Response delivery and terminal ordering

1. Persist the final step checkpoint (Section 12, items 2/3/5/7 —
   already durable the instant the relevant step finished, per
   construction).
2. Overall compound terminal state is already persisted atomically as
   part of (1) — no separate write.
3. `resume()` returns the terminal `WorkflowResult`.
4. `_claim_and_resume_workflow()`'s existing, unchanged
   `mark_consumed()` call runs (handoff `CLAIMED → CONSUMED`).
5. The user response is delivered.

If delivery fails after step 4: no mutation is rerun, the approval is
never reopened, and the compound workflow is never repeated — identical
to the already-closed interlock's own Window F/G guarantees. If the
workflow is later found recovered after Step 3 completed but before
this ordering finished (Section 15, `step_3_status = COMPLETED`
branch): progress is used as step-level evidence, terminal bookkeeping
completes without repeating the write, and a fresh, always-safe
`project_state_show` read is used only if a response must be
reconstructed.

## 20. Revised architecture outcome and batch scope

**Outcome B retained.** The additions above (one store method, four
small engine changes, one tool metadata key, and several
orchestrator-level functions — recognizer, two startup passes, the
narrow claimed-recovery entry point, the concrete observer, the
approval-time gate) are each individually small, additive, and
independently testable; none requires a disproportionate redesign of
`Plan`/`PlanStep`/`WorkflowEngine`'s fundamental execution model.
Batch 2's scope has grown from the `aa92241` estimate (which
understated the engine-level work) but remains reasonably bounded
within one batch — **Outcome C is not selected.**

**Revised Batch 2 scope** (all dormant — no live user trigger):

1. `peek_compound_decision()` — written, unit-tested, not wired.
2. Trusted compound plan builder + recognizer
   (`_matching_compound_workflow_template()`, 14-point fingerprint).
3. `mark_step_1_failed()` on `CompoundWorkflowProgressStore`.
4. `_CompoundStepObserver` Protocol, `step_observer` parameter on
   `resume()`/`_run_from()`, `peek_paused_plan()`,
   `reconstruct_claimed_compound_plan()` on `WorkflowEngine`.
5. `metadata["last_updated_at"]` on `ProjectStateVerifyTool`.
6. Progress creation/gating contract (Section 16), approval-time
   enforcement (Section 17), compound-aware CLAIMED reconciliation
   pass and `resume_claimed_compound_workflow()` (Section 14), all
   built and exercised by direct construction in tests — not reachable
   from any live AI/CommandRouter path.
7. Compound response translator.
8. Full dormant restart/crash-window tests covering every state in
   Section 15.

**Revised Batch 3 scope** (unchanged from `aa92241`): live
discriminator routing wire-up, live grounding, the approval-text
extension (preflight-verified), full end-to-end + restart activation
tests, help/user-guide exposure, closure documentation.

## 21. Required tests

In addition to the `aa92241` test mapping (still applicable), Batch 2
must add tests for the 46 items in the task's own list, organized as:
per-step checkpoint timing (1–10), compound startup reconciliation
(11–20), progress creation and approval gating (21–27), crash recovery
(28–40), and regressions (41–46) — each named precisely in the task
prompt and not reproduced verbatim here to avoid duplicating that
enumeration; every one is achievable with the design in Sections
11–19 above.

## 22. Acceptance criteria

Implementation-ready only if the amended plan specifies (all
satisfied above): durable checkpoints inside the step lifecycle, not a
post-resume-only design; compound recovery before generic CLAIMED
fallback; a safe inherited-CLAIMED continuation path that never
re-invokes the write; exact trusted plan/progress recognition (14
points); progress existence enforced before approval, both for a
catchable failure and a hard crash; approval-time progress validation
independent of the creation attempt; fail-closed checkpoint errors;
exact crash-state restart behaviour for every progress state; and an
honest, retained Batch 2/3 split.

## 23. Risks and mitigations

- **Risk:** the observer's `after_step` veto path (checkpoint failure
  after a successful tool call) is easy to get subtly wrong inside
  `_stop()`, e.g. mis-attributing the error as an ordinary tool
  failure. **Mitigation:** a dedicated, distinctly-worded synthetic
  `ToolResult.error` and a structural test asserting the two failure
  shapes remain distinguishable in `WorkflowHistoryStore`'s own
  recorded detail.
- **Risk:** `reconstruct_claimed_compound_plan()` duplicates
  `_try_reconstruct_paused_workflow()`'s logic and drifts over time.
  **Mitigation:** implement it as a thin wrapper delegating to the
  same private helper, not a second copy.
- **Risk:** the 14-point fingerprint becomes a maintenance burden if a
  second compound template is ever added. **Mitigation:** explicitly
  out of scope (unchanged from `aa92241` §17); a second template
  requires its own fresh planning gate and its own fingerprint.
- **Risk:** the new startup passes (Sections 14, 16) add real latency
  to every restart. **Mitigation:** both are bounded by the number of
  CLAIMED/PENDING rows, identical in cost class to the existing,
  already-accepted generic passes.

## 24. Stop conditions

Unchanged in spirit from `aa92241`, restated with the corrections:
stop if progress is still written only after `resume()` returns; if
synchronous execution is used to dismiss any inter-step crash window;
if generic CLAIMED reconciliation runs before compound recovery; if an
inherited CLAIMED compound workflow requires a second
`APPROVED_UNCONSUMED → CLAIMED` claim; if progress can be missing when
an approval is accepted; if plan and progress identities can disagree
without failing closed; if a checkpoint failure allows the next step
to run; if Step 1 can repeat after durable completion; if current
ProjectState equality is treated as universal execution proof; if
verification is fabricated from the final field value outside the
verifier tool's own call; if an arbitrary three-step plan can enter
compound recovery; or if the work no longer fits safely into Batch 2
without a further foundation batch (assessed above: it still does).

## 25. Manual Anthropic limitation

Unchanged from `aa92241` — live Anthropic acceptance remains postponed
due to insufficient API credits; no production code bypasses it;
Batch 2/3 tests use direct construction and a fake provider throughout.

## 26. Acceptance criteria for this planning amendment itself

- Every correction above is grounded in a specific, named code
  location already read this session or the prior one (`workflow/engine.py`'s
  `_run_from()`/`resume()`/`_stop()`/`_try_reconstruct_paused_workflow()`,
  `main.py`'s `reconcile_claimed_handoffs()`/`_reconcile_claimed_rows()`,
  `approval/approval_manager.py`'s `invalidate_pending()`,
  `workflow/paused_workflow_store.py`'s `delete()`/`get()`).
- No production or test file changed by this amendment.
- Phase 98 implementation not started; no live compound behaviour
  exists after this commit.
