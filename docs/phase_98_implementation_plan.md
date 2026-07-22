# Phase 98 — First Bounded Compound Execution (Planning Gate)

Status: **planning gate only**. No production or test code changed.

## 1. Current baseline

- Branch: `phase-4-ai-reasoning-and-write-actions`, HEAD `e9365b3`.
- Verified baseline: 5301 passed, 3 skipped, 0 failed, identical in all
  three required environments.
- Phase 97 — Isolated Compound Request Grounding Foundation is closed
  (`e9365b3`); its two modules
  (`intelligence/compound_structured_output.py`,
  `intelligence/compound_grounding.py`) are fully tested but wired
  into no live path.

## 2. Phase 97 foundation inherited

`parse_compound_tool_selection()` accepts exactly
`{"decision": "execute_sequence", "steps": [{capability_id, arguments}, {capability_id, arguments}]}`,
strictly validated (exact key sets, real/non-internal capabilities, no
duplicates, reused argument-spec validation). `ground_compound_decision()`
accepts a `ParsedCompoundToolSelection` and the live request text,
checks the declared ordered pair against the one-entry
`_ALLOWED_COMPOUND_TEMPLATES` tuple `(PROJECT_STATE_UPDATE_PHASE,
PROJECT_STATE_SHOW)`, splits the request on the fixed `" and then "`
connector into two ordered clauses, and independently grounds each
clause at its own fixed position against the complete signature
catalogue - correctly rejecting reversed order both structurally and
textually. Neither module is imported by any live runtime file
(structurally proven by `tests/unit/test_compound_isolation.py`).

## 3. Files and tests inspected

Read directly in this planning gate:
`intelligence/compound_structured_output.py`,
`intelligence/compound_grounding.py`, `intelligence/structured_output.py`,
`intelligence/capability_catalog.py`, `intelligence/grounding.py`,
`intelligence/planning.py`, `intelligence/verification.py`,
`core/orchestrator.py`, `planner/plan_models.py`,
`workflow/workflow_models.py`, `workflow/engine.py`,
`workflow/paused_workflow_store.py`, `workflow/workflow_history_store.py`
(record_transition's own commit behavior), `approval/approval_manager.py`,
`security/security_manager.py`, `tools/executor.py`,
`tools/builtin/project_state_update_tool.py`,
`tools/builtin/project_state_verify_tool.py`,
`project_state/project_state_store.py`. Cross-referenced against the
already-audited (this session's own prior phases) test suites for
`test_orchestrator_update_phase_workflow.py`,
`test_orchestrator_schedule_enable_workflow.py`,
`test_workflow_engine.py`, `test_approval_manager.py`,
`test_trusted_workflow_foundation.py`,
`test_compound_structured_output.py`, `test_compound_grounding.py`,
`test_compound_isolation.py`.

## 4. Exact live-selection options assessed

### Design A - Trusted decision dispatcher (assessed: viable, selected)

`select_tool()` would peek only far enough to read the raw `"decision"`
string (via a cheap, defensive, best-effort JSON decode that - on ANY
failure of any kind - falls through unconditionally to today's
`parse_tool_selection()`), and dispatch to
`parse_compound_tool_selection()` only when that peeked value is
*exactly* `"execute_sequence"`. Since `"execute_sequence"` is a value
`parse_tool_selection()` already rejects today (via its unmodified
"unknown decision value" branch), this changes behavior for **zero**
previously-valid single-capability output - it only redirects handling
for output that was already invalid for a different, specific reason.
Malformed output of any other shape (bad JSON, missing "decision" key,
any other string) always falls through to the existing parser, which
already handles every such case - so output can never "fall between"
the two parsers by construction; there are exactly two destinations and
one deterministic default.

### Design B - Separate compound selection path (assessed: rejected)

Pre-classifying the raw *request text* (before any AI call) to decide
which of two trusted instructions to send would make the identical
literal request text receive different model treatment depending on a
separate, fragile heuristic - and if that heuristic's pattern-match is
even slightly off, a genuinely compound-shaped request silently
reverts to single-capability treatment (likely refused as unsupported
or ungrounded) with no ambiguity signal to the user. This also
duplicates the trusted-instruction surface without technical necessity.
Rejected: not because it strictly requires a second AI call (it need
not), but because of exactly the "ambiguous fallback" / "different
model treatment of otherwise identical requests" risk the task itself
warns against, for no offsetting benefit over Design A.

### Design C - Deterministic construction (assessed: rejected)

Constructing the compound decision directly from request text pattern-
matching, bypassing the model (and Phase 97's own parser) entirely,
would make `parse_compound_tool_selection()` an orphaned function with
no real production caller - undermining the very reason Phase 97 built
it. It also blurs the Intelligence Core's own boundary with
`CommandRouter`'s separate, deterministic grammar system: an AI-facing
capability that is secretly never AI-mediated is a different kind of
thing than what "ask jarvis to:" has ever been. Rejected as
inconsistent with the existing Intelligence Core contract.

**Selected: Design A.**

## 5. Selected selection design

`select_tool()` gains a small, new, purely dispatch-level branch:
decode the raw provider response defensively (reusing the same
fence-stripping the existing parser already does, isolated so any
failure defers to the existing parser unchanged); if, and only if, the
decoded `"decision"` field equals exactly `"execute_sequence"`, call
`parse_compound_tool_selection()` and, on success, `ground_compound_decision()`
- never falling back to `parse_tool_selection()` on a compound parse/
ground failure (that failure is reported as its own bounded outcome,
exactly mirroring today's `INVALID_OUTPUT`/`UNGROUNDED_SELECTION`
outcomes, never silently retried as a single-capability attempt).
Every other decision value (including any malformed shape) is handed
to `parse_tool_selection()`, completely unchanged. `_TRUSTED_PLANNING_INSTRUCTION`
gains one clearly-delimited, additional section describing the one
compound form and its one allowed template, appended after the
existing eleven capability descriptions - none of which are edited.
This is the first change to the live decision-selection contract since
Phase 90, and must be treated with the same rigor as that original
work: exactly one AI call, no retries, no fallback, no automatic
substitution.

## 6. Exact compound schema and template

Unchanged from Phase 97: `{"decision": "execute_sequence", "steps": [{"capability_id": "project_state_update_phase", "arguments": {"value": "<exact value>"}}, {"capability_id": "project_state_show", "arguments": {}}]}`,
grounded against the one allowed request form
`"update phase to <value> and then show project state"` with the
fixed connector `" and then "`. No schema or template change is
proposed by this phase - Phase 98 only proposes *wiring* what Phase 97
already built.

## 7. Plan representation assessment

**Option A (flattened trusted 3-step Plan) is correct and sufficient**
- confirmed by direct inspection that `WorkflowEngine`/`Plan`/`PlanStep`/
`WorkflowResult` already support an arbitrary step count with no
change (Phase 97's own planning gate already established this; re-
confirmed here). The trusted plan-builder (a new function alongside
`_build_write_and_verify_workflow_plan()`) would build exactly three
`PlanStep`s: (1) the model-approved phase-update write, using
`PROJECT_STATE_UPDATE_PHASE`'s own existing catalog entry unchanged;
(2) its own existing, catalog-declared internal verifier
(`paired_verify_capability_id` = `PROJECT_STATE_VERIFY_FOCUS`, exactly
as today - the model never declares, selects, or influences this
step); (3) the model-declared second compound step,
`PROJECT_STATE_SHOW`, using its own existing catalog entry unchanged.
Option B (nested plans) is unnecessary - there is no real, current
consumer needing a *generic* nested-workflow architecture, and
inventing one for this single template would be exactly the kind of
speculative generalization this codebase's own catalog philosophy
warns against. Option C (orchestration outside workflow persistence)
is rejected outright per the task's own instruction, and unnecessary
given Option A already works.

The model never controls internal step expansion, tool names, the
verifier, verification input, approval scope, persistence, or response
aggregation - every one of those remains trusted, catalog/template-
derived data, exactly mirroring the existing four `TWO_STEP_WORKFLOW`
capabilities' own established boundary.

## 8. Approval semantics

Confirmed, with **zero new approval code required**: `ToolExecutor.execute()`
already, unconditionally, classifies every step fresh at execution
time and only ever pauses (creates an approval) for a YELLOW step;
`WorkflowEngine`'s STOP-only loop already runs every GREEN step
immediately, back-to-back, with no separate approval. Applied to the
3-step compound plan, this already produces exactly the required
behavior: one approval (step 1, YELLOW), no approval for steps 2/3
(both GREEN), no execution of any step before that one approval is
granted, decline/expiry preventing all three steps identically to
today's decline/expiry handling. `PausedWorkflowStore`/`ApprovalManager`'s
existing, unchanged persistence already durably preserves everything
"Approval data requirements" lists (the compound template identity
implicitly, via the persisted plan's own tool-name triple; the exact
ordered pair, via `plan_steps`; the exact approved phase value and
trusted tool input, via step 1's own persisted `tool_input`; the
existence of the later show step, since it is literally `plan_steps[2]`;
current progress, via `waiting_step_index`/`completed_outcomes`;
stale/expired/declined state, via the existing, unchanged
`ApprovalManager`/`reload_pending()` machinery) - with no schema change.

## 9. Durable persistence assessment (Mandatory question 4)

Confirmed directly: `PausedWorkflowStore.save()`/`_plan_step_to_dict()`/
`_completed_outcome_to_dict()` already serialize a plan's *entire*
step list and completed-outcome list generically, with no assumption
about step count - a 3-step compound plan persists exactly as safely
as today's 2-step plans, with **no schema or model change**.

However, direct inspection of `WorkflowEngine._run_from()`/`resume()`
reveals an important, honestly-reportable characteristic: **the engine
only durably checkpoints at a pause (WAITING) point** - once step 1's
approval is granted, `resume()` deletes the durable paused-workflow row
*before* executing anything, then runs every remaining GREEN step
synchronously, in one Python call, with no incremental durable
checkpoint between them. This is not new to Phase 98 - it is the exact,
already-shipped, already-accepted characteristic every one of today's
four `TWO_STEP_WORKFLOW` capabilities already has between their own
write and verify steps. Extending from two steps to three extends the
same characteristic by one step, not a new kind of risk.

Crucially, `WorkflowHistoryStore.record_transition()` uses its own
`session_scope()` and commits independently, per call - confirmed by
direct inspection. `_run_from()`'s loop calls this once per step,
synchronously, as each step completes, *before* moving to the next.
This means: even though nothing auto-resumes a crash mid-synchronous-run,
`workflow_history` durably and truthfully records exactly how far
execution actually got, step by step, satisfying "audit events remain
truthful" with zero new code.

### Crash-window analysis

- **Crash A (before update execution)**: Fully safe today - the
  paused-workflow row and its linked pending approval both exist,
  independently revalidated on restart by `reload_paused()`/
  `reload_pending()`; a fresh approve+resume() executes the write
  exactly once.
- **Crash B (after update write, before phase verification)**: The
  durable paused-workflow row was already deleted at the top of
  `resume()`, before step 1 ran - there is nothing to "resume," so
  nothing is replayed and nothing is duplicated. The real write already
  happened, durably, for real. This is the *same* characteristic every
  existing write-then-verify capability already has today; it is not
  new. `workflow_history` durably shows step 1 completed.
- **Crash C (after successful phase verification, before ProjectState
  show)**: New *consequence* (though not a new *mechanism*): today,
  "after verify" already means "workflow complete" (there is no third
  step), so this exact window did not previously exist. With a third
  step, a crash here means the show step - an independent, real,
  user-facing GREEN read with **zero side effects** - never runs.
  Nothing is corrupted or duplicated: the phase write and its
  verification are both already durably real; only a non-destructive,
  freely-repeatable read (the user can simply ask "show jarvis project
  state" again) is lost. `workflow_history` durably shows steps 1-2
  completed, step 3 absent - an honest, complete record of exactly
  what happened, with no fabrication.
- **Crash D (after show execution, before final response)**: The show
  step's own real ToolResult is already durably recorded in
  `workflow_history`; only the *response construction* (already-real
  data formatted into one message) would need to be reconstructed -
  never re-executed. No step needs to repeat.
- **Crash E (after final completion)**: Fully safe - `resume()`
  structurally cannot be called twice for the same workflow_id (raises
  `WorkflowError`), and there is nothing left to resume regardless.

**Conclusion**: durable persistence and duplicate-resume safety are
already fully proven for everything that matters for correctness (the
write itself, and truthful audit history). The only residual exposure
(Crash C/D) affects exclusively a non-destructive, freely-repeatable
read with no data-integrity consequence - and per this task's own
"no retry, no replanning" exclusion, *not* auto-resuming it is the
*correct*, required behavior, not a gap. **No new durable persistence
foundation is required.**

## 10. Execution and verification order - the one genuine architectural gap found

Direct inspection reveals a real, narrow gap: `WorkflowEngine`'s
STOP-only policy only ever halts on a step's own `ToolResult.success`/
`blocked`/`requires_confirmation` - it has no mechanism to make step 3
conditional on a *semantic* conclusion drawn from step 2's real
metadata. Because `ProjectStateVerifyTool.run()` is documented and
tested to **never fail** (`success=True` unconditionally), the engine
today would run step 3 (show) regardless of whether verification
actually matched - directly conflicting with the task's own explicit
requirement ("only after successful verification, execute
PROJECT_STATE_SHOW... Phase verification mismatch: no show").

Two viable, narrow designs to close this gap, both backward-compatible:

- **Design 1 - Additive tool-contract extension.** Give
  `ProjectStateVerifyTool` a new, optional input (e.g. `expected_value`,
  paired with `field`) that, only when supplied, makes it perform the
  exact-match comparison internally and return `success=False` on
  mismatch; when absent (every existing caller today), behavior is
  byte-for-byte unchanged. This alone, with zero engine change, lets
  the existing STOP-only policy correctly prevent step 3 on mismatch.
- **Design 2 - Generic engine-level gate (preferred).** Extend
  `PlanStep` with one new, optional, trusted field (e.g.
  `required_previous_metadata: dict[str, object] | None = None`,
  defaulting to `None` for every existing step - zero behavior change)
  and generalize `WorkflowEngine._resolve_tool_input()`'s own existing
  "usable" check (already used for `input_from_previous_step`) to also
  honor it: if set, compare the immediately-previous outcome's real
  `ToolResult.metadata` against the trusted, plan-construction-time
  values, and report `usable=False` - stopping the workflow honestly,
  via the exact same existing message shape ("the immediately previous
  step did not produce the required result data"), never executing
  step 3. This generalizes an already-precedented mechanism
  (`_PROPAGATED_FIELDS`) rather than special-casing one tool, and is
  reusable by any future consumer.

Both are additive and backward-compatible; **Design 2 is preferred**
for architectural consistency with this codebase's own established
generalization pattern (Phase 94 Batch 1, Phase 96's fixed-argument
disambiguation), but either is viable. The implementation phase's own
first batch must choose and justify one with full regression evidence.

`PROJECT_STATE_UPDATE_PHASE` retains its entire existing contract
unchanged (fixed `field="phase"`, one approved exact value, YELLOW
preflight, `ToolExecutor` write, exact durable verification, no retry,
no correction). `PROJECT_STATE_SHOW` executes only after the gate
above confirms success, through its own existing, real GREEN tool, via
`ToolExecutor`, reading the genuinely current, post-update durable
`ProjectStateStore` row - never a cached pre-update value, since it is
a real tool call, not a stored snapshot.

Every step - including the GREEN show step - still receives its own
real `SecurityManager.classify_action()` call, both at trusted
plan-construction time (via the existing `_preflight_capability()`
pattern, extended to all three steps) *and*, unconditionally, at real
execution time via `ToolExecutor` (already true, structurally, for
every step regardless of any change here). The compound template being
allowlisted never substitutes for, weakens, or bypasses either check.

## 11. Partial-completion model

A narrow, bounded outcome model - reusing the exact existing pattern
each current response-builder already implements (inspecting
`WorkflowResult.overall_status`/`step_outcomes`), extended from two to
three possible step positions - covers exactly the five required
states (nothing executed / update failed / update succeeded+verified
but show failed / both succeeded / resume pending) with no new generic
framework. This is a data-shape extension of an already-proven pattern,
not a new architecture.

## 12. Failure behavior

- **Compound parse/ground failure**: reported as its own bounded
  outcome before any preflight, approval, persistence, or execution -
  mirrors today's `INVALID_OUTPUT`/`UNGROUNDED_SELECTION` exactly.
- **Approval decline/expiry**: no update, verification, or show -
  already true structurally (STOP-only policy).
- **Update execution failure**: no verification, no show - already
  true structurally.
- **Verification mismatch**: no show, no retry, update reported as
  unverified - requires the new gate (Section 10).
- **Missing ProjectState during verification**: `ProjectStateVerifyTool`
  already handles a never-written record honestly (empty string
  fields, `_NOT_RECORDED` placeholder) rather than failing or
  recreating anything - no show, since this is definitionally not an
  exact match to a real approved value.
- **Verifier failure**: no show, no retry (same gate).
- **Show failure after verified update**: genuine, honestly-reported
  partial completion - the response must state the update succeeded
  and was verified, and separately that the show step failed, without
  rolling back the (already-real, already-verified) mutation.
- **Response-construction failure after both steps succeed**: both
  steps' real `ToolResult`s are already durably available in the
  synchronous call's own return value (and in `workflow_history`) -
  never rerun the mutation solely to reconstruct wording.

## 13. Grounded response design

A single, narrow, new, trusted compound response-builder (mirroring
`_project_state_update_phase_workflow_result_to_response()`'s own
exact shape, extended to a third outcome), never model-controlled,
combining the real verified phase-update outcome and the real
`PROJECT_STATE_SHOW` output - never fabricating prior phase, branch,
commit, suite result, focus, timestamps, or live repository status
(ProjectState remains manually maintained and may be stale, exactly as
today). The response states plainly that the phase update was approved
and durably verified, and that the displayed project state is the real
stored result read *after* that verification.

## 14. Existing behavior preservation

Every existing capability (`PROJECT_STATE_UPDATE_PHASE`,
`PROJECT_STATE_UPDATE_FOCUS`, `PROJECT_STATE_SHOW`, `SCHEDULE_ENABLE`,
`SCHEDULE_DISABLE`, all other user-facing capabilities), the existing
single-capability structured output and grounding, advisory "ask
jarvis:", deterministic commands, approval/workflow behavior,
`ToolExecutor`, verification, help, and the user guide must regress
identically. A single-capability request must never be reinterpreted
as compound; a malformed compound request must never fall back to
executing one clause - both guaranteed structurally by Design A's own
dispatch discipline (Section 5).

## 15. Selected outcome

**Outcome A - implement the first bounded compound execution**, with
Batch 1 explicitly scoped around resolving the one genuine
architectural gap found (Section 10) before any live wiring proceeds.

## 16. Exact scope (for the future implementation phase)

- `intelligence/planning.py`: the new dispatch branch (Section 5), the
  new trusted-instruction section, and a new compound plan-builder
  function.
- Either `tools/builtin/project_state_verify_tool.py` (Design 1) or
  `planner/plan_models.py` + `workflow/engine.py` (Design 2, preferred) -
  one small, additive, backward-compatible change, chosen and justified
  in Batch 1.
- `core/orchestrator.py`: one new compound-shape matcher and one new,
  narrow response-builder.
- Full regression and new focused tests per Section 20.
- Documentation: `docs/phase_98_completion_report.md`; `docs/user_guide.md`/
  `tools/builtin/help_tool.py` updated to describe the one new command
  form.

## 17. Exact non-goals

No second compound template; no reversed order; no focus-update-plus-show,
schedule-enable/disable-plus-list, two-write, two-read, or arbitrary
GREEN/YELLOW combination; no arbitrary capability arrays; no internal-
verifier declaration by the model; no new `SecurityManager` rule; no
weaker tiers; no pre-approval execution; no shared/reused approval
across unrelated mutations; no model-selected ordering/verifier/steps;
no retries; no replanning; no rollback/compensation; no parallel
execution; no automatic memory writes; no conversation persistence; no
browser/computer control; no source-code self-modification.

## 18. Phase size and batches

Per the task's own sizing rule ("if durable workflow models or live
structured-decision dispatch must change, treat as at least medium")
and given this phase is also the **first change to the live decision-
selection contract since Phase 90** and the first modification to an
existing, shared internal verifier tool's contract (or, under Design
2, to `workflow/engine.py` itself - the single most safety-critical
file in the repository) - this is sized **Large/risky: three batches**,
not merely medium, despite no persistence *schema* change being
required:

- **Batch 1**: resolve the verification-gate mechanism (Section 10,
  Design 1 or 2), fully regression-tested in isolation against every
  existing consumer, with zero behavior change for any of them.
- **Batch 2**: the compound plan-builder, the live dispatch branch, the
  trusted-instruction extension, and the orchestrator shape-matcher/
  response-builder - fully tested against fake/deterministic decisions,
  without yet exercising a live AI call.
- **Batch 3**: full end-to-end integration, crash-window/audit-trail
  tests, full three-environment regression, documentation, and
  closure.

## 19. Test strategy

Covers all 43 items the task requires, organized by batch: Batch 1
tests prove the verification-gate mechanism's own backward
compatibility (items 9-11, 24-32, 37); Batch 2 tests prove dispatch
isolation and schema/template/connector/attribution/extra-signature
behavior (items 1-8, 12-23, 40); Batch 3 tests prove durable
persistence/restart/duplicate-resume (items 16-21), partial completion
and audit ordering (items 33, 36), and full-suite/Ruff verification
(items 42-43).

## 20. Acceptance criteria

All 43 required test categories pass; the full suite matches the
current baseline plus exactly the new tests added, in all three
environments; every existing verified-write capability's own test
suite passes unmodified; Ruff and `git diff --check` are clean; the
completion report documents the verification-gate design choice and
its backward-compatibility evidence explicitly.

## 21. Risks and mitigations

- **Risk**: touching `workflow/engine.py` (Design 2) regresses an
  existing capability. **Mitigation**: new field defaults to `None`
  for every existing `PlanStep`; exhaustive regression proof required
  before Batch 2 begins.
- **Risk**: the live dispatch branch mis-routes malformed output.
  **Mitigation**: default-to-existing-parser design (Section 5) makes
  misrouting structurally impossible for anything but the exact
  `"execute_sequence"` literal.
- **Risk**: crash-window exposure (Section 9) is misunderstood as a
  regression. **Mitigation**: explicit, honest documentation that this
  is an existing, accepted characteristic, not new, and that its only
  new consequence affects a non-destructive, freely-repeatable read.

## 22. Stop conditions (for the future implementation phase)

Stop and report if: the verification-gate mechanism cannot be made
additive/backward-compatible; the live dispatch cannot guarantee
zero-fallback-between-parsers; a second template or arbitrary pairing
becomes necessary; any approval, persistence, or execution safety
property in Sections 8-9 cannot be preserved; or user-visible behavior
for any existing capability would change.

## 23. Manual Anthropic limitation

Live Anthropic manual acceptance remains postponed because the
configured API account lacks sufficient credits - an external account
limitation, not a Jarvis production-code failure. No production change
is proposed to bypass it. Planning and the future implementation
remain verifiable using deterministic and fake-provider tests, exactly
as every prior phase in this session has been.

## 24. Formal planning-gate conclusion

Every mandatory question has a concrete, evidence-based answer using
already-existing architecture, except one narrow, well-understood,
additive gap (Section 10), which has two viable, backward-compatible
resolutions. No stop condition is triggered. **Outcome A is
recommended**, sized Large/risky (three batches), with the
verification-gate mechanism resolved first, in its own batch, before
any live wiring proceeds.
