# Phase 98 Live Compound Re-entry Planning Gate

## First Live Bounded Compound Workflow After Handoff Interlock Closure

Planning-only. No production code or tests are changed by this
document. Phase 98 remains open; nothing here is an implementation.

## 1. Current baseline

- Branch `phase-4-ai-reasoning-and-write-actions`, HEAD `5f0b43c`.
- Full suite: 5507 passed, 3 skipped, 0 failed, identical under the
  normal environment, `AI_REASONING_ENABLED=false`, and
  `PYTHON_DOTENV_DISABLED=1`.
- `git diff --check` clean at HEAD.

## 2. Accepted Phase 97 foundation

`intelligence/compound_structured_output.py` and
`intelligence/compound_grounding.py` (closed at `e9365b3`) implement,
in complete isolation, exactly one compound template:
`PROJECT_STATE_UPDATE_PHASE` → `PROJECT_STATE_SHOW`, connector
`" and then "`, structured shape `{"decision": "execute_sequence",
"steps": [...]}` with exactly two steps. Neither module is imported by
any live runtime module today (verified by `test_compound_isolation.py`,
which still passes at HEAD). Both are reused **unchanged** by this
plan; no correction to either is required.

## 3. Accepted Phase 98 Batch 1 foundation

Accepted at `7feea73`/`fc879c1`:

- `PlanStep.requires_verified_predecessor` /
  `verification_field_name` / `verification_expected_value`
  (`planner/plan_models.py`), enforced generically by
  `WorkflowEngine._verification_gate_failure_reason()`
  (`workflow/engine.py`). Confirmed by inspection: this gate is a
  no-op for every existing plan (default `False`), position-agnostic
  (it only ever looks at "the immediately preceding outcome"), and
  already distinguishes VERIFIED / FAILED-mismatch / UNAVAILABLE.
- `CompoundWorkflowProgressStore` / `reconcile_phase_update()`
  (`workflow/compound_workflow_progress_store.py`) — a durable,
  CAS-protected progress table and a pure reconciliation function for
  exactly the one template above. Not imported by any live module
  today.

## 4. Closed handoff interlock

Formally closed at `5f0b43c` (foundations `b38559c`, `0122bae`). It
provides: an OS-held execution lock; durable
`PENDING → APPROVED_UNCONSUMED → CLAIMED → CONSUMED` /
`CLAIMED → CLAIM_INTERRUPTED` transitions, all CAS; automatic startup
continuation of `APPROVED_UNCONSUMED` workflows
(`main.continue_approved_unconsumed_workflows()` →
`JarvisOrchestrator.resume_approved_unconsumed_workflow()` → the
shared `_claim_and_resume_workflow()`); and real restart proofs for
all four current YELLOW workflows. This plan reuses every one of these
mechanisms unchanged and confirms (Section 11) that they already
generalize to a three-step plan with no interlock-side change.

## 5. Exact target request

`PROJECT_STATE_UPDATE_PHASE` → internal trusted phase verification →
`PROJECT_STATE_SHOW`, exposed to the model as the existing Phase 97
two-capability structured decision, with the verifier inserted by
trusted code as a third, model-invisible step. One YELLOW approval
covers only the write; the verifier and the final read are trusted
GREEN internal steps requiring no further approval.

## 6. Live-selection design (discriminator peek)

**New function** (Batch 2): `peek_compound_decision(raw_text: str) ->
bool` in `intelligence/compound_structured_output.py`, reusing the
*exact same* imports that module already has
(`_live_strip_single_outer_fence`, `_live_reject_duplicate_keys`) so
the peek can never see a different JSON shape than either parser that
acts on its answer. Contract:

- Strip the one permitted outer fence, parse as a duplicate-key-safe
  JSON object.
- Return `True` only if the parse succeeds, the result is a JSON
  object, and its `"decision"` key is present and exactly equal to the
  string `"execute_sequence"`.
- Return `False` for every other case: malformed JSON, a non-object,
  a missing key, any other decision value — never raises.

**Call site** (Batch 2): a new `select_tool_or_sequence()` wrapper in
`intelligence/planning.py`, inserted immediately after
`router.route()` returns `response.text` and before either parser is
invoked:

```
if peek_compound_decision(response.text):
    # commit to the compound path — no fallback, ever
    return _select_compound_tool_sequence(response.text, ...)
return select_tool(...)   # existing function, byte-for-byte unchanged
```

- `peek_compound_decision` returning `True` **commits** the call to
  `intelligence.compound_structured_output.parse_compound_tool_selection()`
  and `intelligence.compound_grounding.ground_compound_decision()`. If
  either raises/refuses, the outcome is a new
  `PlanningOutcomeKind.INVALID_OUTPUT`-equivalent (or a new
  `UNGROUNDED_COMPOUND_SELECTION` kind) — **never** a retry through
  `parse_tool_selection()`. This is the literal, structural
  "no-fallback" guarantee the task requires: once the discriminator
  peek is `True`, the existing single-decision parser is never called
  for that response at all.
- `peek_compound_decision` returning `False` routes unconditionally to
  the existing `select_tool()` body, completely unchanged — including
  for every malformed/unsupported/execute response that exists today.
  Every existing single-decision test therefore continues to exercise
  the exact same code path it always has; `peek_compound_decision`
  only ever adds one cheap, side-effect-free JSON inspection before
  it.

No new step count, capability pair, connector, or ordering is
accepted — `parse_compound_tool_selection()`'s existing exactly-two,
exactly-`execute_sequence`, no-duplicate-capability rules are reused
unmodified, and `ground_compound_decision()`'s existing one-entry
allowlist, connector, and positional-pair equality are reused
unmodified (Section 7).

## 7. Grounding contract

Reused **unchanged**: `intelligence.compound_grounding.ground_compound_decision()`.
Confirmed by re-reading its source this session: exact connector
`" and then "`; first clause must uniquely ground
`PROJECT_STATE_UPDATE_PHASE` (action token `update`, domain token
`phase`) with its value exactly attributable via the `" to "` marker;
second clause must uniquely ground `PROJECT_STATE_SHOW` with no
attributable argument; negation detected request-wide before any
other check; the one-entry `_ALLOWED_COMPOUND_TEMPLATES` tuple (an
ordered tuple of an ordered tuple) makes a reversed pair, a third
capability, a repeated capability, or an alternate connector
structurally unrepresentable, not merely rejected by a runtime check.
Zero code change to this module.

## 8. Trusted plan

**New function** (Batch 2), mirroring
`_build_write_and_verify_workflow_plan()`:
`_build_phase_update_verify_show_workflow_plan()` in
`intelligence/planning.py`. Exact three `PlanStep`s:

1. **Write** — `tool_name="project_state_update"`,
   `tool_input={"field": "phase", "value": <grounded phase value>}`,
   preflighted YELLOW (identical preflight call already used for the
   two-step case).
2. **Verify** (trusted, model-invisible) — `tool_name="project_state_verify"`
   (the same `PROJECT_STATE_VERIFY_FOCUS` catalog entry already paired
   with `PROJECT_STATE_UPDATE_PHASE`), preflighted GREEN. Reused
   without change.
3. **Show** — `tool_name="project_state_show"`, preflighted GREEN,
   `requires_verified_predecessor=True`,
   `verification_field_name="phase"`,
   `verification_expected_value=<the same grounded phase value as
   step 1>` — a trusted, plan-construction-time literal, never
   re-read from model output a second time.

No `PlanStep`/`Plan` change is required: both already support an
arbitrary step count (`WorkflowEngine._validate_executable_plan()`
only requires sequential 1..N numbering), and the paused-workflow JSON
schema already round-trips `requires_verified_predecessor` /
`verification_field_name` / `verification_expected_value` for every
step (confirmed in `WorkflowEngine._plan_step_to_dict()` /
`_try_reconstruct_paused_workflow()`) at `SCHEMA_VERSION = 1` — no
version bump needed.

## 9. Approval semantics

`WorkflowEngine.run()`'s existing per-step tier check
(`tool_result.requires_confirmation`) only ever pauses on a YELLOW
step; steps 2 and 3 are GREEN and structurally cannot trigger
`ApprovalManager.create_request()`. **One approval is therefore
already guaranteed by the existing, unmodified engine — no new
approval-count logic is needed.**

The one open requirement the task adds beyond today's four workflows:
the approval text must name the conditional final show, without
implying it is guaranteed. This is satisfied by giving the compound
template's own step-1 `PlanStep.action` string (constructed only by
the new plan-builder above, never model-supplied) an extended,
trusted, honest description, e.g. *"update the manually-maintained
project state's phase to '<value>', then show the resulting project
state only if verification confirms the update"*. Batch 2 must confirm
this extended text still preflight-classifies as exactly YELLOW
through the live `SecurityManager` (the same exact-tier-match check
`_preflight_capability()` already performs); if it does not, the
extended disclosure is carried in the `ApprovalRequest.reason` field
instead (which is display-only and never used for classification),
leaving `action` unchanged.

Decline/expiry perform zero steps for free (`resume()`'s existing
`_stop()` path never calls `step.tool_name` for a declined decision).
Approved arguments (the grounded phase value baked into
`tool_input`/`verification_expected_value`) are immutable through
restart via the existing paused-workflow persistence, unchanged.

Schema check requested by the task: **no schema change is required**
for `pending_approval_state` or `paused_workflow_state` — both already
support this shape today (Section 8).

## 10. Progress-row creation contract

**Real constraint found by inspection:** `WorkflowEngine.run()`
self-generates `workflow_id` (`uuid.uuid4()`) and
`ApprovalManager.create_request()` self-generates `request_id`,
*inside* the same already-proven, unmodified pause path. Neither
identity exists before `run()` returns. The task's own "preferred safe
ordering" (progress row before pause) is therefore not achievable
without a materially larger change (threading pre-generated ids through
`WorkflowEngine.run()` and `ApprovalManager.create_request()`), which
is disproportionate to this one template and not adopted.

**Selected contract — create-after-pause, self-healing-before-resume:**

1. Parse/ground/build the trusted plan (Sections 6–8; pure, no
   durable writes).
2. Call `workflow_engine.run(plan, session_id=...)`. This durably
   creates `pending_approval_state` (PENDING) and
   `paused_workflow_state`, exactly as today, unchanged.
3. If `result.overall_status is WAITING`: immediately call
   `CompoundWorkflowProgressStore.create(workflow_id=result.workflow_id,
   template_id=ALLOWED_TEMPLATE_ID,
   request_id=result.pending_approval_request.request_id,
   approved_phase_value=<grounded value>)`.
4. **Idempotent backfill, not a hard precondition:** at every future
   touch point that is about to resume a compound-shaped workflow
   (live approval *and* startup continuation, both funnelling through
   `_claim_and_resume_workflow()`), first call a new recognizer
   (Section 11) and `CompoundWorkflowProgressStore.get(workflow_id)`.
   If `None`, create the row on the spot from the already-durable,
   already-reconstructed paused `Plan`'s own step-1
   `tool_input["value"]` — no re-parsing, re-grounding, or model call.

This is deliberately **not** a claim that step 2/3's identities are
durable before the approval is exposed to the user in any I/O sense —
they are durable microseconds after `run()` returns and before the CLI
ever prints the prompt, which is the practical guarantee available
without a distributed transaction across two independent SQLite
sessions (which this plan does not claim, per instruction).

**Authoritative record / repair / failure ordering / cleanup /
restart detection (explicitly, since atomicity is not claimed):**
`pending_approval_state` + `paused_workflow_state` remain authoritative
for "does this workflow exist and may it be resumed" — `CompoundWorkflowProgress`
is authoritative only for internal step-checkpoint/reconciliation
state, **never** for whether a workflow may be approved or resumed
(WorkflowEngine's own verification gate, Section 8, is independently
sufficient for that). A crash between step 2 and step 3 above leaves a
valid, ordinarily-resumable YELLOW workflow with a missing progress
row, self-healed on first touch (step 4). A declined/expired request's
progress row (if created at all) is terminated via the same
`mark_step_1_failed()` transition used for an ordinary write failure
(Section 12) — reused, not a fourth status. No new cleanup command is
added; a stale, never-reconciled row is retained indefinitely, exactly
mirroring the interlock's own accepted terminal-retention stance.

## 11. Step-transition mapping

**Recognition** (new, Batch 2): `_matching_compound_workflow_template()`
in `core/orchestrator.py`, mirroring `_matching_two_step_write_capability()`
structurally: `len(steps) == 3`, `steps[0].tool_name == "project_state_update"`
with `tool_input["field"] == "phase"`, `steps[1].tool_name ==
"project_state_verify"`, `steps[2].tool_name == "project_state_show"`
with `requires_verified_predecessor is True` and
`verification_field_name == "phase"`. This is independent of
`CompoundWorkflowProgress` row presence (Section 10) — recognition and
response translation never depend on the progress row existing.

**New engine accessor** (Batch 2, additive, read-only):
`WorkflowEngine.peek_paused_plan(workflow_id) -> Plan | None`, exposing
`self._paused[workflow_id].plan` if present — mirrors `has_paused()`'s
existing narrow read-only pattern. Needed because
`_claim_and_resume_workflow()` does not otherwise have access to the
workflow's own internal Plan before calling `resume()`.

**Pre-execution observation** (new, capability-agnostic hook inside
`_claim_and_resume_workflow()`, gated by the recognizer): captured via
one additional, real, **audited** `self._executor.execute("project_state_verify",
{}, session_id=...)` call — not a raw store read — immediately before
`resume()`. This requires one small additive change to
`tools/builtin/project_state_verify_tool.py`: add
`metadata["last_updated_at"] = record.last_updated if record else None`
(the raw `datetime`, alongside the existing formatted string) —
non-breaking, since metadata is a free-form dict nothing today depends
on the absence of. Recorded via
`CompoundWorkflowProgressStore.record_pre_execution_observation()`
only when `step_1_status is PENDING` (idempotent: also covers a prior
crash before observation was recorded).

**Because `WorkflowEngine.resume()` executes steps 1→2→3 in one
uninterrupted synchronous call** (no callback hook between internal
steps, and Batch 1's own module docstring deliberately keeps
`CompoundWorkflowProgressStore` unimported by any live runtime module
until this batch), the per-step completion transitions below are
**observability/audit checkpoints applied as one ordered batch
immediately after `resume()` returns**, not live inter-step
checkpoints — see Section 12 for why this does not weaken crash
safety.

- **Step 1 succeeds:** `step_outcomes[0].status is COMPLETED` →
  `mark_step_1_completed(workflow_id)`.
- **Step 1 ordinary failure (or a decline):** →
  **new, additive store method** `mark_step_1_failed(workflow_id)`
  (CAS `IN_PROGRESS → FAILED`, `overall_status → FAILED`; mirrors the
  existing `mark_step_3_failed()` shape exactly). Reused for decline,
  since both mean "the write never happened and never will for this
  request." Do not continue to `start_step_2`/`start_step_3`.
- **Step 2 begins/finishes:** `start_step_2()` then
  `mark_step_2_completed(workflow_id, verification_outcome=...)` — the
  real `VerificationOutcome` from `verify_project_state_field()`,
  mapped 1:1 onto `CompoundVerificationOutcome` (already the same
  three-member vocabulary). A non-VERIFIED outcome already, atomically,
  sets `overall_status → FAILED` inside this one existing store method
  — step 3 can never legally be started afterward.
- **Step 3 begins/finishes:** `start_step_3()` only legal once
  `step_2_verification_outcome == VERIFIED` (already enforced by the
  store's own CAS precondition); `mark_step_3_completed()` on success,
  `mark_step_3_failed()` on failure. Show output itself is never
  persisted — only the fixed status transition.
- **Each transition is individually CAS-guarded**; if a prior crashed
  attempt already applied part of the batch, a later, redundant call
  raises `CompoundWorkflowProgressError`, which the wrapper catches
  and ignores (never fatal, never blocks the real response — see
  Section 12).

## 12. Crash windows

Twelve windows as specified. Several of the literal restart scenarios
the task describes (8, 9, 10) do not correspond to independently
reachable crash points in the current architecture, because
`resume()` executes steps 1→2→3 without an external checkpoint
between them; this is stated plainly below rather than inventing a
checkpoint that does not exist.

1. **Before progress row creation** (i.e. before `run()` is even
   called): no durable write of any kind has happened — no approval,
   no paused workflow, no progress row, no execution. Trivially true.
2. **Approval/pause created, progress-row creation fails:** see
   Section 10's selected contract — self-healed at first future touch
   point; never blocks resume; no duplicate row (creation is always a
   get-then-create at a single-execution-lock-holding process, per the
   existing interlock's own OS-lock exclusivity guarantee).
3. **Approval/pause created, process exits before user approves:**
   identical to every existing YELLOW workflow today — normal PENDING
   behaviour, no execution, decline/expiry unaffected. A leftover
   all-PENDING progress row (if created) is inert.
4. **Approval granted before claim:** the existing, already-proven
   `APPROVED_UNCONSUMED` restart continuation — `continue_approved_unconsumed_workflows()`
   → `resume_approved_unconsumed_workflow()` → `_claim_and_resume_workflow()`
   — retains the exact plan/inputs, requires no new approval, claims
   once. Unchanged by this plan; only the new compound hook rides
   inside the same call.
5. **Claim succeeds before pre-execution observation:** the claim CAS
   (`APPROVED_UNCONSUMED → CLAIMED`) happens first (existing, unchanged
   code); a crash before observation leaves the row CLAIMED with no
   confirmed terminal workflow-history evidence — the existing,
   capability-agnostic `_reconcile_claimed_rows()` already resolves
   this generically to `CLAIM_INTERRUPTED` on next startup. No new
   logic required; the progress row (if present) is left at
   `step_1_status=PENDING`, consistent, not contradictory.
6. **Pre-execution observation recorded before Step 1:** same CLAIMED
   → CLAIM_INTERRUPTED resolution as Window 5. Restart never
   automatically retries the write (explicitly excluded). A future,
   separately-approved manual-review path could call
   `reconcile_phase_update()` with the now-durable
   `pre_execution_phase_value`/`pre_execution_last_updated` against a
   fresh read, to inform a human decision — never automatic.
7. **Step 1 tool succeeds but completion checkpoint is absent — the
   key reconciliation case:** this is exactly Batch 1's Contract A.
   `reconcile_phase_update()` is reused **completely unchanged**: its
   three-member `ReconciliationConfidence` already distinguishes
   pre-state-differed-now-matches
   (`POSTCONDITION_SATISFIED_STATE_CHANGED`), pre-state-already-matched
   with a changed `last_updated`
   (`POSTCONDITION_SATISFIED_STATE_CHANGED`), and
   pre-state-already-matched with no further evidence
   (`POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED`, never claimed as
   executed) — never fabricating VERIFIED from the ProjectState value
   alone. The row resolves to `CLAIM_INTERRUPTED` via the same
   generic interlock mechanism as Windows 5/6; `reconcile_phase_update()`
   is available as a diagnostic for a human/future tool, never invoked
   to auto-decide anything.
8. **Step 1 completed before Step 2:** does not arise as an
   independent restart point in the live path (steps 1→2 run in one
   `resume()` call with no pause between them); the only crash that
   can land here resolves identically to Window 7 (CLAIM_INTERRUPTED,
   no automatic replay).
9. **Verification finishes but progress checkpoint is absent:** same
   reasoning as Window 8 — no independent pause point exists between
   step 2 and the post-hoc batch write. Resolves to CLAIM_INTERRUPTED.
   Per-step `workflow_step_completed`-shaped history entries do exist
   in real time (`_record_history()` runs inside the step loop), but
   the existing interlock deliberately treats only
   `workflow_completed`/`workflow_stopped` as positive terminal proof
   — this plan does not weaken that. VERIFIED is never fabricated from
   the ProjectState value alone.
10. **VERIFIED persisted before Step 3:** does not arise as an
    independent restart point today for the same reason as 8/9 — steps
    2→3 run in the same `resume()` call. Resolves to
    CLAIM_INTERRUPTED, not an automatic verification-only resume of
    step 3 alone (no such narrower resume path exists or is added).
11. **Step 3 returns output before completion checkpoint:** if
    `resume()` has already returned COMPLETED, `mark_consumed()` has
    already run (in `_claim_and_resume_workflow()`, before the
    compound post-hoc batch) — a crash after that point means the
    approval is already `CONSUMED` and will never be revisited by
    `continue_approved_unconsumed_workflows()`. The progress row may be
    left at `step_3_status=IN_PROGRESS` permanently (a disclosed,
    accepted artifact, exactly mirroring the interlock's own indefinite
    terminal-retention stance). Since step 3 is read-only, an operator
    can always safely re-run an ordinary "show project state" — never
    a re-execution of the compound workflow.
12. **Compound terminal result before response delivery:** identical
    to the already-closed interlock's own Window F/G guarantees, reused
    unchanged: `mark_consumed()` already happened, the approval can
    never be reused, and any reconstructed response would use only
    bounded durable state (`WorkflowHistoryStore`'s terminal record)
    plus an always-safe fresh `project_state_show` — never a
    mutation.

## 13. Reconciliation authority

- `PendingApprovalStore`: sole authority for approval/claim lifecycle
  (PENDING/APPROVED_UNCONSUMED/CLAIMED/CONSUMED/CLAIM_INTERRUPTED/DECLINED/EXPIRED).
- `PausedWorkflowStore`: sole authority for the exact trusted plan and
  approved inputs.
- `CompoundWorkflowProgress`: authority for compound step-checkpoint
  state only — never for whether the workflow may be approved or
  resumed (Section 10).
- `WorkflowHistoryStore`: audit-oriented, positive-only terminal
  evidence (`workflow_completed`/`workflow_stopped`); step-level
  entries exist but are never treated as proof of overall completion,
  and can never reconstruct step-level restart progress on their own.
- `ProjectState` durable store: the current observable postcondition
  only — matching the approved value is never, by itself, proof the
  update tool executed (Section 12, Window 7).
- `ToolExecutor` result: live execution result only, for the one call
  that produced it.
- `VerificationResult`: the verification-gate decision only, for the
  one step that produced it.

## 14. Interlock restart integration

1. Acquire execution lock. 2. Initialize/migrate stores (no schema
change needed — Section 9). 3. Build stores/orchestrator (`build_orchestrator()`,
unchanged). 4. Repair approval/history consistency (unchanged). 5.
Reconcile inherited CLAIMED handoffs (unchanged, capability-agnostic —
Section 12, Windows 5–9). 6. Continue APPROVED_UNCONSUMED workflows
(`continue_approved_unconsumed_workflows()`, unchanged entry point).
7. Inside it, `resume_approved_unconsumed_workflow()` locates the
paused compound plan via the existing `workflow_id` metadata
mechanism — unchanged. 8. `_claim_and_resume_workflow()`'s new
recognizer (Section 11) identifies the compound shape from the
peeked `Plan` and self-heals/locates the `CompoundWorkflowProgress`
row by the trusted `workflow_id` (Section 10) — never by parsing
anything model-supplied. 9. Claims once (existing CAS, unchanged). 10.
Executes only through the existing `resume()` — never a new
interpreter; steps 1–3 run to their natural stopping point. 11.
Updates progress monotonically via the CAS-guarded batch (Section 11).
12. Produces the final bounded response via the new compound
translator (Section 15).

**Confirmed:** `resume_approved_unconsumed_workflow()` is already
completely capability-agnostic and needs **zero change** — the only
new logic lives inside `_claim_and_resume_workflow()`, selected purely
from trusted, persisted plan shape (Section 11), never model output.
No general workflow interpreter is added.

## 15. Response semantics

New `_compound_update_phase_and_show_result_to_response()` in
`core/orchestrator.py`, dispatched from `_translate_verified_workflow_result()`
via the Section 11 recognizer (added as one more entry alongside the
existing `response_builders` table — a data addition, not a growing
`if`/`elif` chain, matching the codebase's own established convention):

- **Full success:** step 1 COMPLETED, step 2 outcome VERIFIED, step 3
  COMPLETED → names the update, states verification succeeded, and
  returns the real, current `project_state_show` output (never an AI
  paraphrase).
- **Update failure:** step 1 not COMPLETED → reports failure; no
  verification or show ever claimed to have run.
- **Verification mismatch (FAILED):** reports the update's durable
  postcondition was not confirmed; step 3 never runs (engine gate,
  Section 8).
- **Verification unavailable (UNAVAILABLE):** reports verification
  could not complete; step 3 never runs.
- **Final show failure:** step 1 COMPLETED, step 2 VERIFIED, step 3
  not COMPLETED → reports the update was verified but the final read
  failed; never claims the whole sequence succeeded.
- **Interrupted/reconciliation-required:** (reached only via the
  `CLAIM_INTERRUPTED` path, never inside a single `resume()` call)
  reports honestly that the outcome could not be safely proven and
  that automatic replay was prohibited — no raw tool output, prompts,
  reasoning, or stack traces, exactly matching the existing
  `CLAIM_INTERRUPTED` visibility contract.

## 16. Existing-behaviour preservation

- Every single-capability AI decision: unaffected structurally,
  because `peek_compound_decision()` returning `False` routes to the
  byte-for-byte unchanged `select_tool()` body (Section 6) — proven by
  construction, not merely by running the existing suite.
- `PROJECT_STATE_UPDATE_FOCUS`/`PROJECT_STATE_UPDATE_PHASE`/`SCHEDULE_ENABLE`/`SCHEDULE_DISABLE`:
  `_matches_two_step_workflow_shape()` already requires `len(steps) ==
  2`; a 3-step compound plan structurally cannot match any
  `TWO_STEP_WORKFLOW` capability's shape, so no existing recognizer or
  response translator is disturbed.
- Advisory `ask jarvis:`, deterministic commands, approval decline/expiry,
  handoff restart continuation, `ToolExecutor`, `SecurityManager`,
  verification, `project_state_show`, Phase 97's isolated modules
  (still unimported by any live module until Batch 2 explicitly wires
  `peek_compound_decision`), and Phase 98 Batch 1's foundations: all
  reused unchanged, per each section above.

## 17. Security boundaries

No arbitrary multi-tool plans, no second compound template, no
model-selected verification/tier, no multiple approvals, no automatic
reapproval, no retries/replanning/rollback/compensation, no browser or
computer control, no arbitrary/automatic memory writes, no scheduler
integration, no background workers, no general workflow scripting. The
one compound sequence remains fixed, trusted, and catalog/template-driven.

## 18. Architecture options assessed

- **Outcome A** (Batch 2 complete live engine, hidden from docs;
  Batch 3 exposure/closure): rejected — the amount of new integration
  surface found by this audit (a new store method, a new tool metadata
  key, a new engine accessor, a new orchestrator recognizer/hook/
  translator, restart integration, reconciliation) is large enough
  that shipping it all live in one batch, even hidden from
  documentation, risks a half-proven path being reachable before
  restart/crash-window testing is complete.
- **Outcome B — selected.** Batch 2 builds the complete internal
  compound execution/restart/reconciliation lifecycle with **no live
  AI discriminator routing** (i.e. `peek_compound_decision()` and its
  call site are *not* wired into `select_tool()` yet) — no user can
  trigger it. Batch 3 activates live routing, adds the approval-text
  extension, full end-to-end + restart tests, help/docs, and closure.
  Matches the task's own guidance: "prefer this when partial
  user-facing activation would be unsafe."
- **Outcome C** (additional foundation required): not selected. This
  audit found the existing foundation (Plan/PlanStep, WorkflowEngine's
  N-step + verification-gate support, the paused-workflow schema,
  `CompoundWorkflowProgressStore`) already structurally sufficient.
  Only three small, additive primitives are needed (Section 19) — none
  rises to "a fresh, separately-approved foundation phase."
- **Outcome D** (defer): not selected — no disproportionate redesign
  was found to be required.

## 19. Selected outcome and Batch 2 scope

**Outcome B.** Batch 2 adds, all dormant (no live routing):

1. `peek_compound_decision()` (`intelligence/compound_structured_output.py`)
   — written and unit-tested, but **not called** from `planning.py` yet.
2. `_build_phase_update_verify_show_workflow_plan()` and
   `_select_compound_tool_sequence()` (`intelligence/planning.py`) —
   built and tested directly, not reachable from `select_tool()`'s own
   entry point yet.
3. `mark_step_1_failed()` — new, additive method on
   `CompoundWorkflowProgressStore` (`workflow/compound_workflow_progress_store.py`).
4. `peek_paused_plan()` — new, additive, read-only accessor on
   `WorkflowEngine` (`workflow/engine.py`).
5. `metadata["last_updated_at"]` — new, additive key on
   `ProjectStateVerifyTool.run()`'s returned metadata
   (`tools/builtin/project_state_verify_tool.py`).
6. `_matching_compound_workflow_template()`, the pre-execution
   observation hook and post-hoc progress batch inside
   `_claim_and_resume_workflow()`, and
   `_compound_update_phase_and_show_result_to_response()`
   (`core/orchestrator.py`) — built and tested by directly constructing
   a compound `Plan`/`WorkflowResult` in tests, without going through
   any live AI/CommandRouter path.
7. Full restart/crash-window tests for the dormant path (Section 12),
   reusing the existing real-database test conventions.

## 20. Batch 3 scope

1. Wire `peek_compound_decision()` into `select_tool()`'s entry point
   (or a new `select_tool_or_sequence()` replacing it as the one real
   call site in `core/orchestrator.py`'s `_handle_ask_jarvis_to_request()`).
2. Add the approval-text extension (Section 9), verified against the
   live `SecurityManager`.
3. Full end-to-end tests: live discriminator routing, live grounding,
   live approval → claim → resume → verify → show, on a real, durable
   database.
4. Help/user-guide exposure.
5. `docs/phase_98_approval_handoff_plan.md`-style closure documentation
   for Batch 2+3 together (not a Phase 98 completion report — Phase 98
   remains open pending Nathan's own review of whether further
   compound templates are wanted).

## 21. Required tests (mapped to the task's 75-item list)

Grouped by batch; every numbered item from the task's list is covered
by name, not reproduced item-by-item here to avoid duplicating the
task's own enumeration. **Batch 2** covers items 1–3 (decision
selection contract, unit-level, direct calls — not yet reachable
live), 9–22 (grounding/plan-shape unit tests), 27–66 (persistence,
execution, verification, progress/crash-recovery, and interlock
integration — all real-database, restart-based, mirroring
`test_yellow_workflow_restart_continuation.py`'s own established
pattern), and 74–75 (full-suite + Ruff, run at the end of Batch 2 to
prove zero regression while still dormant). **Batch 3** covers items
4–8 (live-routing-specific: fallback/malformed-input behaviour once
actually wired), 23–26 (approval-text and one-approval end-to-end,
live), 68–73 (full regression sweep including the four existing YELLOW
workflows and the closed interlock suite), and a repeat of 74–75 at
Batch 3's own close.

## 22. Acceptance criteria

- Zero change to any existing single-capability AI test's outcome.
- The three additive primitives (Section 19, items 3–5) ship with
  their own direct unit tests before any orchestrator wiring depends
  on them.
- Every crash window in Section 12 has a real, durable-database test
  proving its stated resolution (mostly: resolves to the existing,
  unchanged `CLAIM_INTERRUPTED` mechanism).
- `reconcile_phase_update()` is exercised with real pre/post
  observations from the new hook, not just Batch 1's own synthetic
  values.
- Ruff clean across the full Git-derived diff scope at the close of
  each batch.

## 23. Risks and mitigations

- **Risk:** the approval-text extension (Section 9) reclassifies away
  from YELLOW. **Mitigation:** preflight-verify before adopting it;
  fall back to the existing wording with the fuller disclosure only in
  `reason`.
- **Risk:** `peek_compound_decision()` and `parse_tool_selection()`
  drift in what counts as valid JSON/fence-stripping over time.
  **Mitigation:** both are built from the same imported helpers by
  construction (Section 6); a structural test should assert this
  import relationship, mirroring the existing isolation tests.
- **Risk:** a future second compound template is added carelessly,
  reusing `_matching_compound_workflow_template()`'s five-field check
  ambiguously. **Mitigation:** explicitly out of scope (Section 17);
  any second template requires its own fresh planning gate.

## 24. Stop conditions

Unchanged from the task's own list; restated as directly applicable
given this audit's findings: stop if any existing single-capability
test's behaviour changes; if a second claimant can ever execute; if a
completed/consumed compound workflow can replay; if any of the three
environments fails; if Ruff exits nonzero; if `git diff --check` is
not clean; if the approval-text extension cannot preflight as YELLOW
and no safe fallback is accepted; if a crash window resolves to
anything other than the existing `CLAIM_INTERRUPTED`/PENDING/CONSUMED
vocabulary.

## 25. Manual Anthropic limitation

Live Anthropic acceptance remains postponed due to insufficient API
credits — an external, non-technical limitation. No production code
bypasses it. Batch 2's tests exercise the compound plan/execution/
restart lifecycle entirely through direct construction and a fake
provider, exactly like every other AI-adjacent test in this
repository; Batch 3's live-routing tests likewise use a fake
`AIProvider`, never a real Anthropic call.

## 26. Acceptance criteria for this planning gate itself

- Repository-grounded: every function/file named above was read this
  session, not assumed.
- No production or test file changed.
- Phase 98 implementation not started; no live compound behaviour
  exists after this commit.
