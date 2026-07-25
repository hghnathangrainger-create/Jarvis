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

## 27. Batch 2 implementation evidence

**The internal compound lifecycle described in Sections 1-26 above now
exists.** It remains dormant and unreachable from any live request:
`peek_compound_decision()` and the trusted plan builder are written and
independently tested, but no call site attaches either to
`select_tool()`; `core/compound_workflow.py` and
`workflow/compound_progress_observer.py` are not imported by
`core/orchestrator.py` or `main.py`; no help output, user guide, or
prompt instruction mentions any of it (proven structurally in
`tests/unit/test_phase98_batch2_dormant_isolation.py`). **Batch 3 is
still required** for atomic live activation. **No user-visible
compound behaviour exists.**

### Foundations implemented exactly as designed

- **A** - `peek_compound_decision()` added to
  `intelligence/compound_structured_output.py`, reusing the existing
  fence/duplicate-key helpers unchanged.
- **B** - `_build_phase_update_verify_show_workflow_plan()` added to
  `intelligence/planning.py` as a private, unwired helper alongside the
  existing two-step builder.
- **C** - `matches_compound_plan_shape()` /
  `compound_progress_identity_matches()` /
  `is_recognized_compound_workflow()` in the new `core/compound_workflow.py`
  - the full 14-point fingerprint, exactly as specified.
- **D** - `CompoundWorkflowProgressStore.mark_step_1_failed()` - the
  one new store primitive; all 11 pre-existing methods reused
  unchanged.
- **E** - `_CompoundStepObserver` Protocol added to `workflow/engine.py`;
  `resume()`/`_run_from()`/`_stop()` gained an optional, keyword-only
  `step_observer` parameter (defaulting to `None`, never accepted by
  `run()`); `peek_paused_plan()` and `reconstruct_claimed_compound_plan()`
  added as new, read-only public accessors; the pre-existing
  `_try_reconstruct_paused_workflow()` was refactored (its
  approval-status-independent reconstruction extracted into
  `_reconstruct_plan_and_outcomes()`) so the new
  `reconstruct_claimed_compound_plan()` reuses it rather than
  duplicating it. The concrete observer
  (`workflow/compound_progress_observer.py:CompoundStepObserver`)
  implements the Protocol structurally (no inheritance), performing the
  pre-execution observation via one extra, audited
  `project_state_verify` call and computing `VerificationOutcome`
  from Step 3's own trusted, already-durable expected value.
- **F** - `establish_compound_progress_or_isolate()` (synchronous
  creation-failure path: terminally isolates via the existing
  `ApprovalManager.invalidate_pending()` + `PausedWorkflowStore.delete()`,
  never lazily left) and
  `repair_or_isolate_pending_compound_progress()` (the dormant,
  hard-crash repair pass over PENDING rows) in `core/compound_workflow.py`.
- **G** - `validate_compound_approval_before_transition()` in
  `core/compound_workflow.py` - re-fetches progress fresh at validation
  time, never trusting an earlier creation attempt; reports
  `is_compound_workflow=False, valid=True` for every non-compound
  approval, leaving it provably unaffected.
- **H** - `reconcile_claimed_compound_workflows()` and the narrow
  `resume_claimed_compound_workflow()` in `core/compound_workflow.py`,
  implementing the full crash-state matrix; structurally proven to
  never call `claim_for_resume()` (the Protocol it depends on does not
  even expose that method).
- **I** - `translate_compound_workflow_result()` in
  `core/compound_workflow.py`, producing exactly the six
  `CompoundResultKind` outcomes.

### One production-code correction made during implementation

`establish_compound_progress_or_isolate()`/
`repair_or_isolate_pending_compound_progress()` originally caught only
`CompoundWorkflowProgressError` around `CompoundWorkflowProgressStore.create()`.
Since a duplicate `workflow_id` raises a raw `IntegrityError` (the
column is unique), not that typed exception, this was widened to catch
`Exception` generally - discovered and fixed while writing
`test_compound_progress_creation_gating.py`'s own duplicate-workflow-id
test, before any commit.

### Test suite added (11 new files, 4 existing files extended)

- `tests/unit/test_phase98_batch2_dormant_isolation.py` (22 tests)
- `tests/unit/test_peek_compound_decision.py` (16)
- `tests/unit/test_compound_plan_builder.py` (11)
- `tests/unit/test_compound_workflow_recognizer.py` (23)
- `tests/unit/test_compound_workflow_progress_store.py` (+7, `mark_step_1_failed`)
- `tests/unit/test_workflow_engine_compound_checkpoints.py` (18)
- `tests/unit/test_compound_progress_creation_gating.py` (10)
- `tests/unit/test_compound_approval_time_validation.py` (8)
- `tests/integration/test_compound_claimed_recovery.py` (14)
- `tests/unit/test_compound_result_translator.py` (10)
- `tests/integration/test_compound_lifecycle_dormant_end_to_end.py` (3)
- `tests/unit/test_phase98_batch1_isolation.py` (+1, `select_tool` never
  calls the new builder; the Batch 1 "no verification-gate reference in
  planning.py" test narrowed to "only in the one dormant builder")
- `tests/unit/test_project_state_verify_tool.py` (updated for the
  additive `last_updated_at` metadata key)
- `tests/unit/test_workflow_engine.py` (its two structural invariant
  tests updated to reflect the intentional refactor:
  `_reconstruct_plan_and_outcomes` added to the reload-revalidation
  allowlist, and the except-block census widened from 2 swallowing
  `Pass` blocks to 2 swallowing + 2 fail-closed `Return` blocks)

Each of the four above was updated to reflect Batch 2's own
intentional, planned additions - never weakened.

### Verification

- Full suite: **5650 passed, 3 skipped, 0 failed**, identical under the
  normal environment, `AI_REASONING_ENABLED=false`, and
  `PYTHON_DOTENV_DISABLED=1`.
- Git-derived Ruff scope (21 files: 9 modified, 12 new): **all checks
  passed, exit 0**.
- `git diff --check`: clean.

## 28. Batch 2 acceptance correction — checkpoint-failure handoff and terminal semantics

**Issue discovered.** Batch 2's own design converted every observer/
checkpoint infrastructure failure into a synthetic `ToolResult` and
called `WorkflowEngine._stop()` — the same method used for a genuinely
*known* terminal outcome (an ordinary tool failure, a decline, a
verification-gate mismatch). `_stop()` unconditionally writes a
`workflow_stopped` history entry and returns an ordinary `WorkflowResult`.
Since `workflow_stopped` is one of exactly two event names the existing,
unmodified generic interlock (`main._reconcile_claimed_rows()`) accepts
as positive terminal evidence, and since `_claim_and_resume_workflow()`
already treats *any* `WorkflowResult` `resume()` returns (rather than
raises) as "a real, well-defined result" and unconditionally calls
`mark_consumed()` — a checkpoint infrastructure failure (a CAS conflict,
a missing progress row, a transient database error, an unexpected
observer exception) would have been indistinguishable from a definitive,
known outcome the moment Batch 3 wired a `step_observer` into the live
resume path. This would have caused the handoff to be marked `CONSUMED`
(or, on restart, the generic interlock to independently reach the same
conclusion) for an outcome nobody had actually confirmed — silently
defeating the entire purpose of compound-specific reconciliation.
`resume()` also unconditionally removed the durable `paused_workflow_state`
row before any checkpoint was even attempted, which — combined with the
above — would have left compound-specific startup recovery with nothing
to reconstruct the plan from.

**Correction implemented.** The preferred design (a dedicated,
nonterminal checkpoint exception) was selected. `workflow/engine.py`
adds `CompoundCheckpointError(Exception)`, and every checkpoint touch
point inside `resume()`/`_run_from()` now raises it directly instead of
converting the failure into a synthetic `ToolResult` and calling
`_stop()`. `_stop()` itself was reverted to its pre-Batch-2 form (no
`step_observer` parameter at all) — it is now reachable only for a
genuinely known outcome, exactly as before Batch 2 existed.
`resume()` wraps its own body (everything after the paused-state
removal) in a single `try/except CompoundCheckpointError`, which
restores both the durable (`_persist_paused_state()`) and in-memory
(`self._paused[workflow_id]`) paused state before re-raising — so a
checkpoint failure leaves no trace of ever having been attempted from
the durable record's own point of view, regardless of which step
triggered it (compound recovery only ever needs the plan's own static
content, never `waiting_step_index` to reflect the exact point of
failure).

**Why checkpoint infrastructure failure remains nonterminal.** A
checkpoint failure means the *durable evidence* of what happened could
not be trusted — not that the requested sequence completed, not that it
definitively failed before mutation, and not that no reconciliation is
required. Raising instead of returning a `WorkflowResult` means no
`workflow_stopped`/`workflow_completed` history entry is ever written
for this failure alone, and no caller can mistake it for a well-defined
result the way it already treats an ordinary return.

**Why the handoff stays `CLAIMED`.** `CompoundCheckpointError` is a
distinct exception type from the generic `Exception` the existing,
unmodified `_claim_and_resume_workflow()` already catches around
`resume()` (which calls `mark_claim_interrupted()` before re-raising).
A future, separately-approved Batch 3 wiring must catch
`CompoundCheckpointError` specifically, *before* that generic handler,
and must do nothing to the handoff at all — leaving it exactly
`CLAIMED`, never immediately `CLAIM_INTERRUPTED` and never `CONSUMED`.
This planning obligation is documented here for Batch 3; Batch 2 itself
makes no orchestrator change (per the dormant boundary), so no live
code path can reach this decision point yet.

**How startup reconciliation resolves it.** Because the paused workflow
and its progress row are both left intact, a checkpoint-failed compound
workflow remains fully eligible for
`core.compound_workflow.resume_claimed_compound_workflow()`'s existing
crash-state matrix: Step 1's own real durable state is classified via
the unchanged `reconcile_phase_update()`; Step 2/3 (both read-only) may
be safely rerun. `tests/integration/test_compound_checkpoint_failure_handoff_semantics.py::TestStep1SuccessCheckpointFailureHandoffSemantics::test_remains_reconcilable_by_compound_recovery_afterward`
proves this directly: a Step-1-success/checkpoint-failure is followed by
a real `resume_claimed_compound_workflow()` call that reaches `CONSUMED`
with a fully `COMPLETED` progress row, using only durable state and zero
second claim.

**Files changed:** `workflow/engine.py` (the correction itself),
`tests/unit/test_workflow_engine_compound_checkpoints.py` (7 tests
updated to assert `CompoundCheckpointError` instead of the old
synthetic-`_stop()` behaviour; new `TestGenericStopUnaffectedByCheckpointCorrection`
class), `tests/integration/test_compound_lifecycle_dormant_end_to_end.py`
(1 test updated), and the new
`tests/integration/test_compound_checkpoint_failure_handoff_semantics.py`
(6 tests proving the handoff/progress-level semantics directly with a
real `PendingApprovalStore`).

**Verification:** full suite **5659 passed, 3 skipped, 0 failed**,
identical under all three environments; Ruff clean across the 4-file
correction scope; `git diff --check` clean. No production or test file
outside this narrow scope changed. Phase 98 remains open; Batch 3 was
not started; no live compound behaviour exists.

## 29. Batch 3 implementation evidence — atomic live activation

**Phase 98 is now closed.** The first live bounded compound request -
`ask jarvis to: update my project phase to <value> and then show my
project state` - is reachable end-to-end through the real, wired-
together path, atomically, in one working set: live discriminator
routing, exact compound parsing/grounding, the trusted three-step
Plan, progress creation before an actionable approval, one honest
approval, live claim/resume with observer attachment,
`CompoundCheckpointError` handling, compound-first startup recovery
ordering, six-outcome response translation, and help/user-guide
exposure.

### Live wiring added exactly as designed

- **`intelligence/planning.py`** - `select_tool()` now calls
  `peek_compound_decision(response.text)` immediately after
  `router.route()` succeeds; a `True` result commits fully to the new
  `_select_compound_tool_sequence()` helper (parse → ground → build),
  never falling back to `parse_tool_selection()`. Three new
  `PlanningOutcomeKind` members
  (`EXECUTABLE_COMPOUND_WORKFLOW`/`INVALID_COMPOUND_OUTPUT`/
  `UNGROUNDED_COMPOUND_SELECTION`). `_TRUSTED_PLANNING_INSTRUCTION`
  extended with exactly one compound-decision paragraph, naming the one
  fixed template and explicitly prohibiting any other pair, reversed
  order, extra steps, or repetition. Step 1's `action` text (display-
  only, never authoritative for security classification - confirmed via
  `ToolExecutor.execute()`/`_preflight_capability()` both re-deriving
  classification fresh from `tool.action_for()`) is honestly extended to
  describe the full conditional three-step sequence for approval
  display.
- **`core/orchestrator.py`** - new `paused_workflow_store`/
  `compound_progress_store` optional constructor collaborators (default
  `None`, every existing call site unaffected);
  `validate_pending_approval_for_transition()` (the live Foundation G
  wiring point, called from `ui/cli.py` immediately before `approve()`);
  `_start_compound_update_phase_and_show_workflow()` (runs the plan,
  then establishes progress before ever returning an actionable
  approval); `_compound_step_observer_for()` (recognizes the trusted
  plan purely from durable state - never decision/model output); a
  rewritten `_claim_and_resume_workflow()` that attaches the observer
  only for a recognized, approved compound resume, catches
  `CompoundCheckpointError` in its own block *before* the pre-existing
  generic `except Exception`, and dispatches to
  `translate_compound_workflow_result()` for `is_compound` results.
- **`main.py`** - `build_orchestrator()` constructs and passes through
  the new `CompoundWorkflowProgressStore`; `reconcile_claimed_handoffs()`
  rewritten with compound-first ordering: history repair →
  `repair_or_isolate_pending_compound_progress()` →
  `reconcile_claimed_compound_workflows()` (a small, dedicated,
  throwaway compound-only `ToolRegistry`/`ToolExecutor`/
  `SecurityManager`/`WorkflowEngine` stack, never the full production
  registry) → the existing, unchanged generic `_reconcile_claimed_rows()`,
  which now only ever sees rows the compound pass did not already
  resolve. New `_DurableCompoundApprovalInvalidator` adapter implements
  the approval-invalidator contract directly against
  `PendingApprovalStore.mark_expired()` + `ApprovalHistoryStore.record_timeout()`
  - deliberately never a fresh `ApprovalManager` (which would require an
  incorrect `reload_pending()` call against the narrow compound-only
  registry, wrongly invalidating every unrelated real pending approval).
- **`ui/cli.py`** - `_handle_approval()` calls
  `validate_pending_approval_for_transition()` immediately before
  recording an approval decision (never for a decline - decline never
  transitions to `APPROVED_UNCONSUMED`, so this gate does not apply).
- **`tools/builtin/help_tool.py`/`docs/user_guide.md`** - exactly one
  narrow, honest compound example added to each, describing only the
  fixed phase-update-then-show exception in natural language (`and
  then`) - never the internal `execute_sequence` decision literal or
  the internal word "compound," and never implying a general multi-step
  mechanism exists.

### Design correction discovered and fixed during live activation: dedicated non-execution terminalization

**Issue discovered.** Live-testing the decline path exposed a genuine
defect unreachable in Batch 2's own dormant tests (which only ever
attached a fake, trace-recording observer with no real CAS logic).
`WorkflowEngine.resume()`'s decline branch calls
`_observer_after_step(step_observer, workflow_id, 0, tool_result)`
directly, **never** `_observer_before_step()` first (an existing,
deliberately-tested Batch 2 engine contract -
`TestDeclineNeverInvokesBeforeStep`). The real
`CompoundStepObserver.after_step()` for a failed step 0 calls
`CompoundWorkflowProgressStore.mark_step_1_failed()`, whose CAS
precondition requires `step_1_status == IN_PROGRESS` - a state only
`before_step()` (via `record_pre_execution_observation()`) ever sets.
Since `before_step()` is never called for a decline, this transition
always raised `CompoundWorkflowProgressError`, surfacing to the user as
the checkpoint-interrupted message instead of an honest decline
outcome - for *every* decline of the compound approval, not merely an
edge case.

**Two rejected fixes.** Widening `mark_step_1_failed()`'s own CAS
precondition to also accept `PENDING` would have reversed an existing,
explicitly tested Batch 1 contract
(`test_illegal_from_pending_state`) and overloaded a real-execution-
failure primitive to also mean "never attempted." Making `resume()`
call `before_step()` before `after_step()` on decline would have
changed a generic, already-tested `WorkflowEngine` contract that every
future observer (not only this one) depends on, and would have made
the pre-execution `project_state_verify` read fire even for a decline
that will never write anything.

**Correction implemented: a dedicated non-execution terminalization
path**, never routed through `mark_step_1_failed()` at all:

- `CompoundOverallStatus` gains one new, narrow bounded member,
  `NOT_EXECUTED` - honestly distinct from `FAILED` (which always means
  a real attempt genuinely did not succeed).
- `CompoundWorkflowProgressStore.mark_not_executed_before_start()` -
  new, CAS-backed, idempotent (a second call on an already-
  `NOT_EXECUTED` row is a safe no-op, returned unchanged). Legal only
  when every step is still `PENDING`, overall status is still
  `PENDING`, and no pre-execution observation was ever recorded - i.e.
  the row is in exactly the pristine state `create()` left it in. Never
  classifies Step 1 as `FAILED`.
- `core/orchestrator.py`'s `_claim_and_resume_workflow()`: when a
  recognized compound workflow's decision is not approved, the trusted
  `step_observer` is never attached at all (`step_observer = None`) -
  the existing, generic `WorkflowEngine` decline contract runs
  completely unaffected (ToolExecutor, the verifier, and the show step
  all receive zero calls, exactly as for any other declined workflow) -
  and the new `_terminalize_declined_compound_progress()` helper calls
  `mark_not_executed_before_start()` directly, best-effort, absorbing
  `CompoundWorkflowProgressError` silently (never blocking or altering
  the decline's own outcome).
- `core/compound_workflow.py`'s new
  `terminalize_declined_or_expired_compound_progress()` - the startup
  consistency repair backstop, wired into `main.reconcile_claimed_handoffs()`
  alongside the existing PENDING/CLAIMED passes (order-independent - it
  only ever touches rows already durably `DECLINED`/`EXPIRED`, a
  disjoint set). This is the *sole* mechanism that ever terminalizes an
  **expired** compound workflow's progress row at all: expiry never
  goes through `resume()` - `WorkflowEngine._reap_stale_paused()`
  silently discards the paused workflow lazily, with no callback into
  this module whatsoever - so unlike decline (which is also
  terminalized live, synchronously, with this repair pass only as its
  own crash-window backstop), an expired row's progress is *always*
  resolved here, never live. `ReconciliationSummary` gains
  `compound_progress_terminalized: int = 0`.
- The authoritative handoff state (`DECLINED`/`EXPIRED` on
  `pending_approval_state`) is never touched by any of the above - it
  was already correct before this correction; only the compound
  progress row's own honesty was ever the defect.

**New tests** (`tests/unit/test_phase98_batch3_live_compound_activation.py::TestDeclineAndExpiryTerminalization`):
decline terminalizes progress as `NOT_EXECUTED` with zero observer step
events and zero execution of all three real tools; the generic
`WorkflowEngine` decline contract (paused row removed, `workflow_stopped`
terminal history) is unaffected; the terminalization is idempotent;
expiry leaves the progress row exactly `PENDING`/pristine live (no
hook exists); the repair pass correctly terminalizes it.

### Test suite added

- `tests/unit/test_phase98_batch3_live_compound_activation.py` - 34
  tests: decision activation (6), approval and progress creation (3),
  normal execution end-to-end (4), six-outcome translation (4),
  `CompoundCheckpointError` handling (2), decline/expiry
  terminalization (5), restart and crash recovery (3), regression (3),
  plus the corrected verification-unavailable double.
- Every pre-existing dormant-isolation assertion this batch's
  activation intentionally flips (`test_compound_isolation.py`,
  `test_phase98_batch1_isolation.py`,
  `test_phase98_batch2_dormant_isolation.py`) was rewritten as a
  narrower, structural *confinement* proof (AST-based: the compound
  reference is confined to exactly the intended methods/functions),
  never simply deleted or weakened to "anything goes." One further,
  pre-existing test outside the Phase 98 test files themselves,
  `test_production_approval_wiring.py::test_main_source_always_passes_pending_store_to_approval_manager`,
  was narrowed to name one explicit, structurally-identified exception:
  the compound-recovery-only `WorkflowEngine`'s bare `ApprovalManager()`,
  used solely to satisfy a required constructor argument for an engine
  instance that is only ever used for its own read-only
  `reconstruct_claimed_compound_plan()` accessor (confirmed via that
  method's own docstring: "never mutates approval or paused-workflow
  state itself").

### Verification

- Full suite: **5687 passed, 3 skipped, 0 failed**, identical under the
  normal environment, `AI_REASONING_ENABLED=false`, and
  `PYTHON_DOTENV_DISABLED=1`.
- Batch 3 Ruff scope (`git diff --name-only a5cfa58 -- '*.py'`, plus
  the new untracked test file): **all checks passed, exit 0**.
- Complete Phase 98 Ruff scope (`git diff --name-only 3583820 -- '*.py'`,
  spanning Batch 1, the handoff interlock, dormant lifecycle, checkpoint
  correction, and this live activation together): **all checks passed,
  exit 0**.
- `git diff --check` clean for both ranges.

### Guarantees

Exactly one compound decision, for exactly one fixed template, is ever
live; no fallback to a single-capability interpretation on any
compound-parse/grounding failure; no second claim CAS; no
`CONSUMED`/`CLAIM_INTERRUPTED` on a checkpoint failure; compound-first
startup recovery strictly before the generic CLAIMED fallback; a
decline or expiry never executes any of the three real tools and is
never misreported as a checkpoint/infrastructure failure; help/user
guide expose only the one fixed natural-language example, never the
internal decision literal or general multi-tool capability.

### Non-guarantees (explicitly out of scope)

No second compound template exists or is planned; no arbitrary
multi-tool execution of any kind; no live mechanism terminalizes an
expired compound workflow's progress except the startup repair pass
(a long-running process that never restarts will show a stale-but-
harmless `PENDING` progress row for an expired approval until its next
restart); Anthropic live acceptance remains postponed (insufficient API
credits) - this batch's own tests use direct construction and a fake
provider throughout, exactly as every prior Phase 98 batch's own tests
do.

Phase 98 is now closed. See `docs/phase_98_completion_report.md` for
the full closure report.
