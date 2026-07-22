# Phase 97 — Compound Request Grounding Foundation (Planning Gate)

Status: **planning gate only**. No production code changed. This
document supersedes the earlier, less rigorous draft of
`docs/phase_97_implementation_plan.md` produced before this expanded
planning gate was requested; that draft's own candidate (a third,
internal context step appended to `PROJECT_STATE_UPDATE_PHASE`) is
retired in favor of the analysis below, which was requested to be
performed against a much larger, more rigorous question set and a
different candidate menu (Options A-E).

## 1. Current repository checkpoint

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- Starting HEAD: `d7d16ff` (Phase 96 closed).
- Verified baseline (re-confirmed live during this planning gate, not
  merely recalled): 756 focused tests across
  `test_capability_catalog.py`, `test_structured_output.py`,
  `test_grounding.py`, `test_intelligence_planning.py`,
  `test_approval_manager.py`, `test_workflow_engine.py`,
  `test_pending_approval_store.py`, `test_paused_workflow_store.py`,
  `test_trusted_workflow_foundation.py`, `test_verification.py`,
  `test_orchestrator_schedule_enable_workflow.py`,
  `test_orchestrator_schedule_disable_workflow.py`, and
  `test_orchestrator_update_phase_workflow.py` — all 756 passed.
- `dashboard_test.txt` remains untouched, untracked, uncommitted
  throughout this planning gate.

## 2. Phase 90-96 architectural baseline

- Phase 90 (Batches 2/3): introduced the one-capability-per-request
  structured decision (`intelligence/structured_output.py`), the
  trusted planning instruction and `select_tool()`
  (`intelligence/planning.py`), and the original
  `TWO_STEP_WORKFLOW` write-then-verify shape for
  `PROJECT_STATE_UPDATE_FOCUS`.
- Phase 91: added three zero-argument and one bounded-argument
  `SINGLE_TOOL` read capabilities.
- Phase 92 (Batch 1): added `intelligence/grounding.py` - a
  deny-only, deterministic gate requiring the live request to
  **uniquely** match exactly the model-selected capability's own
  signature across the *whole* catalog (never merely the selected
  capability's signature in isolation).
- Phase 93 (Batch 1): added two more zero-argument read capabilities
  (`APPROVAL_HISTORY`, `WORKFLOW_HISTORY`).
- Phase 94: Batch 1 generalized the `TWO_STEP_WORKFLOW`
  write/verify pairing into trusted catalog data
  (`paired_verify_capability_id`/`paired_verify_input_keys`); Batch 2
  added `SCHEDULE_ENABLE`, the first *second* `TWO_STEP_WORKFLOW`
  capability, proving the generic pairing mechanism; Batch 3 replaced
  the last per-capability `if`/`elif` recognizer in
  `core/orchestrator.py` with a fully catalog-driven matcher
  (`_matching_two_step_write_capability`/`_matches_two_step_workflow_shape`).
- Phase 95: added `SCHEDULE_DISABLE`, reusing the same verifier
  capability with a distinct `verifier_id`, proving verifier reuse is
  safe because `CapabilityId` is never persisted.
- Phase 96: added `PROJECT_STATE_UPDATE_PHASE`, reusing
  `PROJECT_STATE_VERIFY_FOCUS` genericized to serve either field, and
  extended the orchestrator's shape-matcher with a small,
  catalog-driven fixed-argument disambiguation
  (`fixed_arguments_for()`) for the first time two capabilities share
  one identical write/verify tool-name pair.

Every one of these four `TWO_STEP_WORKFLOW` capabilities pairs exactly
**one real, user-facing capability** with **one internal-only,
never-model-selectable verifier capability**. None of them combine two
independently real, user-facing, model-selectable capabilities into
one request. That is the exact gap this phase addresses.

## 3. Exact intelligence gap

Jarvis can select and safely execute exactly one model-selected,
user-facing capability per request (optionally paired with its own
fixed, internal verifier). It has no way to represent, ground, or
execute a single user request that deliberately names **two**
independent, real, user-facing capabilities as one bounded compound
goal (e.g., "update my project phase to X and show me my project
state"). Closing this gap is the next meaningful step toward "one
bounded user goal represented by a small trusted sequence of catalogue
capabilities."

## 4. Mandatory inspection findings

Every file listed in the task's "Mandatory inspection" section was
read directly in this planning gate (not recalled from memory):
`intelligence/capability_catalog.py`, `intelligence/structured_output.py`,
`intelligence/grounding.py`, `intelligence/planning.py`,
`intelligence/verification.py`, `core/orchestrator.py`,
`workflow/engine.py`, `workflow/workflow_models.py`,
`workflow/paused_workflow_store.py`, `approval/approval_manager.py`,
`security/security_manager.py`, `tools/executor.py`,
`planner/plan_models.py`, plus the Phase 94/95/96 plans and completion
reports (already deeply audited across this session's own prior
phases, re-confirmed here against the live code rather than assumed).

Key, load-bearing findings, each directly answering the "Current
architecture" questions (1-10):

1. **The structured-decision schema cannot represent multiple
   capabilities today.** `parse_tool_selection()` enforces an exact
   `{"decision", "capability_id", "arguments"}` shape with
   `capability_id` a single nullable string and `arguments` a single
   dict — confirmed by direct reading, not assumption.
2. **The planner assumes exactly one capability.** `select_tool()`
   parses one decision, resolves one `CapabilityAdapter`, and (for a
   `TWO_STEP_WORKFLOW` capability) builds exactly one write step plus
   its own trusted, internal verifier step — never two independently
   *selected* capabilities.
3. **Grounding assumes exactly one user-facing signature per request,
   and enforces it strictly.** `ground_decision()`'s
   `_grounded_capability_ids()` computes the *entire* set of
   catalog signatures the live request matches, and refuses outright
   (`MULTIPLE_SIGNATURES_MATCHED`) the instant more than one matches -
   this is precisely the rule that would reject any request naming two
   real capabilities today, by design, not by oversight.
4. **The workflow engine already persists an arbitrary number of
   sequential steps.** `WorkflowEngine._validate_executable_plan()`
   only requires steps numbered `1, 2, 3, ...` with no gaps; nothing
   caps the count at two. `_persist_paused_state`/`_plan_step_to_dict`/
   `_completed_outcome_to_dict` serialize the *whole* `plan.steps` and
   `completed_outcomes` collections generically. This was true before
   this phase and needs no change.
5. **Persisted workflows track COMPLETED/WAITING/FAILED per step, but
   have no distinct "verified" step status.** `WorkflowStepOutcome.status`
   uses the existing `StepStatus` enum; verification
   (VERIFIED/FAILED/UNAVAILABLE) is always a separate, orchestrator-level
   semantic conclusion drawn *after* a COMPLETED verify step's
   `ToolResult.metadata` - never itself a step status. This is an
   existing, deliberate design choice (confirmed in
   `intelligence/verification.py`'s own docstring), not a gap.
6. **Resume never reruns an earlier step.** `WorkflowEngine.resume()`
   pops the paused state, executes exactly the one waiting step, and on
   success calls `_run_from(..., start_index=paused.waiting_step_index + 1, ...)`
   - `_run_from` only ever advances forward from `start_index`.
7. **Duplicate-resume protection operates at the whole-workflow level,
   which is sufficient because Phase 15's model allows at most one
   waiting step at a time.** `resume()` pops
   `self._paused[workflow_id]` before executing anything; a second
   `resume()` call for the same id always raises `WorkflowError`
   ("no paused workflow"). There is no independent *per-step* duplicate
   marker, but none is needed while exactly one step can ever be
   waiting per workflow.
8. **The generic catalogue-driven matcher recognizes today's fixed
   2-step write+internal-verify shape, but has no concept of a
   plan built from two independently-selected user-facing
   capabilities** - `_matching_two_step_write_capability` iterates
   only `TWO_STEP_WORKFLOW` catalog entries, each with exactly one
   fixed `paired_verify_capability_id`. A compound plan of two
   *independently selected* real capabilities is a different shape
   this matcher was never designed to recognize, and this phase does
   not ask it to (see Section 9's exact non-goals).
9. **`ToolExecutor.execute()` is already the sole per-step execution
   path for every step `WorkflowEngine` ever runs**, regardless of step
   count - confirmed directly; no direct `tool.run()` call exists
   anywhere outside `ToolExecutor._handle_run()`.
10. **The response-building pattern already reports partial completion
    honestly** for the existing 2-step shape (WAITING vs FAILED vs
    COMPLETED, with the exact failing step identified) - this pattern
    is proven and reusable, but not extended in this phase since no
    new plan shape is built.

Findings for "Grounding and intent" (11-17) and "Trusted data flow"
(36-40) are folded into Sections 11 and 15 below, since they directly
shaped the selected design rather than being freestanding facts.

## 5. Candidate options considered

### Option A — Selected: Compound Request Grounding Foundation

Add a new, additive, non-live-wired decision shape and a new grounding
function proving that a request naming exactly two capabilities from a
small, explicit, hand-authored allowlist of ordered template pairs can
be deterministically, uniquely attributed - without building any
execution machinery and without changing the live "ask jarvis to:"
trusted instruction or `select_tool()`'s real call path.

### Option B — Considered, lower priority: Durable Sequential Workflow Foundation

Rejected as the *first* move (though still valuable later): Section 4,
finding 4 already shows `WorkflowEngine` and its persistence layer are
**already** fully general past two steps - there is close to nothing
left to build here. Writing tests that merely reconfirm already-true
engine behavior is legitimate but low-value compared to Option A, which
closes a *real*, currently-blocking gap (grounding's uniqueness rule).
Deferred until Option A's foundation exists to give it something
concrete to execute.

### Option C — Considered, correctly deferred: First Bounded Two-Step User Workflow

This is the eventual goal, but attempting it *in this phase* would
require simultaneously changing `intelligence/structured_output.py`
(new schema), `intelligence/grounding.py` (new uniqueness rule),
`intelligence/planning.py` (new plan-construction path), and
`core/orchestrator.py` (new shape recognition and response building) -
four interacting, individually risky changes to the most heavily
audited parts of the codebase, in one phase. Option C's own listed risk
("may combine too many architectural changes in one phase") is exactly
what direct inspection confirms. Deferred to a future phase, to be
built *on top of* Option A once it is proven correct in isolation.

### Option D — Considered, not selected now: Outcome/Task Context Foundation

A durable, non-memory task-outcome record. Valuable for a later Respond/
Remember-focused phase, but it does not address the actual blocking
gap (Section 3) at all - it improves what Jarvis remembers about a
result, not whether Jarvis can safely represent a compound goal in the
first place. Not selected because it doesn't advance the stated
priority (multi-step planning) at all this cycle.

### Option E — No stronger prerequisite found

Direct inspection did not surface a more fundamental blocker than the
grounding uniqueness rule (Section 4, finding 3). Every other piece
needed for eventual compound execution (durable persistence,
per-step verification, approval, exactly-once resume) already exists
and works, confirmed live in Section 4. No Option E candidate is
proposed.

## 6. Honest comparison

| | Closes the real blocking gap | New live model-facing behavior | Touches execution/approval/persistence code | Risk of simultaneous multi-module change | Reusable by future compound templates |
|---|---|---|---|---|---|
| A (selected) | Yes - the grounding uniqueness rule itself | No (not wired to the live instruction or `select_tool()`) | No | Low - additive, isolated modules | Yes - foundation any future template reuses |
| B | No - engine already supports N steps | No | Tests only, no real behavior change | Low, but low value | Marginal |
| C | Yes, but all at once | Yes | Yes, extensively | High | N/A - is the end goal, not a foundation |
| D | No | No | No | Low | Low - orthogonal concern |
| E | N/A | N/A | N/A | N/A | N/A |

Option A is the only candidate that closes a real, currently-blocking
architectural gap while keeping blast radius small, live behavior
completely unchanged, and produces a genuinely reusable foundation for
Option C later.

## 7. Selected Phase 97 objective

**Build and thoroughly test a Compound Request Grounding Foundation:**
a new, additive parsing shape for a two-capability compound decision,
and a new grounding function that deterministically proves such a
request's two declared capabilities are each independently evidenced
in the live request text, and that no unaccounted-for third capability
also matches - restricted to a small, explicit, hand-authored allowlist
of trusted, ordered capability-pair templates (never an arbitrary
pairing of any two of the eleven capabilities). **Not wired into the
live trusted planning instruction or into `select_tool()`'s real call
path this phase** - proven correct by its own dedicated test suite,
with wiring and actual execution explicitly deferred (Section 33).

## 8. Why it is the best next phase

- It is the one piece every future compound-execution design (Option
  C) needs regardless of its own eventual shape, since without it no
  compound request can ever be safely attributed to a live request at
  all (Section 4, finding 3).
- It touches zero execution, approval, or persistence code - the
  highest-risk parts of the codebase are completely undisturbed.
- It changes zero live, user-facing behavior - Nathan's real "ask
  jarvis to: ..." command behaves identically before and after this
  phase, since the new shape is never offered to the model and
  `select_tool()`'s real call path is unchanged.
- It produces concrete, reusable evidence (a real, tested worked
  example - Section 11) that the eventual Option C design is soundly
  buildable, rather than a purely paper design.
- It is small enough to implement, test, and regress in one controlled
  phase, matching the selection standard's explicit "small enough for
  one controlled implementation phase" requirement.

## 9. Exact user-visible behavior, if any

**None.** No change to `_TRUSTED_PLANNING_INSTRUCTION`, no change to
`select_tool()`'s real call path, no new command, no new response
shape a user could ever see. This is a pure, internal foundation.

## 10. Exact structured-decision changes

- New module-level function in `intelligence/structured_output.py`:
  `parse_compound_tool_selection(raw_text, catalog, allowed_templates)`.
  Never replaces or modifies `parse_tool_selection()` - a wholly
  separate, additive function with its own dedicated tests.
- New schema, validated with the same rigor as the existing one (2,000
  char cap, single outer fence, duplicate-key rejection, exact
  top-level key set): `{"decision": "execute_sequence",
  "capability_ids": ["id1", "id2"], "arguments": [{...}, {...}]}`.
  Exactly two entries in `capability_ids` and `arguments`, in the same
  order; each `capability_ids[i]` must be a real, non-`internal_only`
  catalog member, and `arguments[i]` is validated against that specific
  capability's own declared `CapabilityArgumentSpec` tuple, reusing
  `_validate_arguments()` unchanged (called once per declared step).
- New, distinct top-level decision literal `"execute_sequence"` -
  chosen to be unambiguous with the existing `"execute"`/`"unsupported"`
  values; the existing schema/parser is entirely untouched.
- `(capability_ids[0], capability_ids[1])`, as an ordered tuple, must
  be a member of a new, small, explicit, hand-authored
  `_ALLOWED_COMPOUND_TEMPLATES: frozenset[tuple[CapabilityId, CapabilityId]]`
  constant in `intelligence/capability_catalog.py` - never an arbitrary
  pairing. This phase populates it with exactly one worked example:
  `(CapabilityId.PROJECT_STATE_UPDATE_PHASE, CapabilityId.PROJECT_STATE_SHOW)`.

## 11. Exact grounding changes

New function in `intelligence/grounding.py`:
`ground_compound_decision(*, request_text, capability_ids, arguments)`.

- Reuses the existing negation gate (`_contains_negation_marker`)
  unchanged, applied once to the whole request.
- Reuses `_grounded_capability_ids(request_text)` unchanged (it is
  already fully generic over the whole catalog).
- New rule (answers Q12/Q13 directly): the matched signature set must
  equal **exactly** `frozenset(capability_ids)` - not merely `len == 1`.
  This is a strict generalization, not a relaxation: it still refuses
  the request if it matches zero signatures, a signature outside the
  declared pair, or only one of the two declared signatures.
- Each declared capability's own existing per-capability argument-span
  extraction/attribution logic (`_ARGUMENT_MARKER_BY_CAPABILITY`/
  `_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY`) is reused verbatim, applied
  independently to each of the two steps - answers Q15/Q38/Q39
  directly: no new attribution philosophy, no cross-step data use.
- **Step order is trusted from the fixed template, never independently
  re-derived from the request text** (the honest answer to Q16): this
  function does not attempt to prove *order* from natural language: it
  only proves that the declared, already-template-validated pair's
  signatures are each genuinely evidenced, with no third,
  unaccounted-for match. Order-faithfulness is guaranteed structurally
  instead, by requiring the declared pair to exactly match one static,
  hand-authored, already-ordered template (Q17's answer) - the model
  can therefore never invent a novel order or pairing, only confirm
  one of the templates this catalog already allows.
- One new `UngroundedReason` member,
  `COMPOUND_TEMPLATE_NOT_ALLOWED` for a syntactically valid pair that
  is not in `_ALLOWED_COMPOUND_TEMPLATES`; existing reasons
  (`NO_SIGNATURE_MATCHED`, `MULTIPLE_SIGNATURES_MATCHED`,
  `MISSING_ARGUMENT_SPAN`, `AMBIGUOUS_ARGUMENT_SPAN`,
  `ARGUMENT_VALUE_MISMATCH`, `NEGATED_OR_CONFLICTING_REQUEST`) are
  reused unchanged, applied per step where applicable.

## 12. Exact planning changes

**None in production.** `intelligence/planning.py`'s `select_tool()` is
not modified in this phase - it never calls
`parse_compound_tool_selection()`/`ground_compound_decision()`, and
`_TRUSTED_PLANNING_INSTRUCTION` is not extended to mention the new
shape. This is a deliberate scope boundary (Section 33): wiring live
selection is Option C's job, once this foundation is proven.

## 13. Exact workflow-model changes

**None.** `workflow/engine.py`, `planner/plan_models.py`, and
`workflow/workflow_models.py` are untouched - Section 4's findings
already confirm they need no change to support more than two steps
whenever a future phase builds a compound Plan.

## 14. Exact persistence changes

**None.** No new persisted field, table, or schema version. This phase
produces no `Plan`, no `ApprovalRequest`, and no paused workflow of any
kind, so nothing new is ever durably written.

## 15. Exact approval design

**Not exercised this phase** - no approval is ever created, since no
execution path is wired. The architectural answers (Q18-26), based on
Section 4's confirmed facts about the *already-existing*, unchanged
`ToolExecutor`/`ApprovalManager`, are recorded here for the future
execution phase's benefit:

- GREEN→GREEN: both steps run back-to-back automatically, no approval
  (already how step 2 of today's write+verify shape runs after step 1).
- GREEN→YELLOW: step 1 runs automatically; step 2 pauses for its own
  approval, exactly like today's single-YELLOW-step case, just at
  position 2 instead of 1.
- YELLOW→GREEN: step 1 pauses for approval; once approved, step 2 runs
  automatically in the same `resume()` call - this is exactly today's
  existing write+verify shape's own behavior, unchanged.
- YELLOW→YELLOW: step 1 pauses; once approved and executed, step 2
  would itself independently pause for its *own*, separate approval
  (`ToolExecutor.execute()` classifies every step fresh, every time -
  confirmed in Section 4 - so a second YELLOW step is never
  auto-approved by the first's decision). One approval per YELLOW step,
  never one approval authorizing two (Q22/Q24 - already true of the
  unmodified `ToolExecutor`/`WorkflowEngine`, needs no new code).
- Approved arguments are already immutable between approval and
  execution today (`PendingToolState`/`_PausedWorkflow.resolved_tool_input`
  are frozen dataclasses, confirmed in Section 4/2) - this holds
  regardless of step count, unchanged.
- Approval expiry on a partially completed plan already stops the
  workflow honestly with no execution of the un-approved step
  (`WorkflowEngine._reap_stale_paused`/`ApprovalManager._sweep_expired`,
  confirmed unchanged in Section 4).

## 16. Exact execution design

**Not exercised this phase.** No `Plan` is ever constructed or run.

## 17. Exact verification design

**Not exercised this phase.** `intelligence/verification.py` is
untouched.

## 18. Exact restart/resume behavior

**Not applicable this phase** - nothing is ever persisted, so there is
nothing to restart or resume.

## 19. Exact duplicate-prevention behavior

**Not applicable this phase** for the same reason as Section 18.

## 20. Exact partial-completion behavior

**Not applicable this phase.** A future execution phase inherits
Section 4's already-confirmed honest partial-completion behavior
(WAITING/FAILED/COMPLETED per step, never fabricated).

## 21. Exact failure-state behavior

`parse_compound_tool_selection()`/`ground_compound_decision()` each
raise/return their own bounded, non-sensitive failure reason exactly
like today's single-capability path - no new failure taxonomy beyond
the one new `UngroundedReason` member (Section 11). No execution
failure mode exists this phase, since nothing executes.

## 22. Exact final-response behavior

**Not applicable this phase** - no `JarvisResponse` is ever produced
from this new code path; it is exercised only by its own unit tests.

## 23. Backward compatibility

- `parse_tool_selection()`, `ground_decision()`, `select_tool()`, and
  every existing `CapabilityId`/`CAPABILITY_CATALOG` entry are
  byte-for-byte unchanged.
- The trusted planning instruction is unchanged, so every existing,
  live "ask jarvis to: ..." request behaves identically.
- All 756 baseline tests re-run during this planning gate (Section 1)
  continue to pass unmodified, confirming no regression risk from the
  facts this plan relies on.

## 24. Data migration analysis

**None required.** No persisted schema, table, or field changes.

## 25. Security analysis

- No new `SecurityManager` rule is needed this phase - no action is
  ever classified, since nothing executes.
- The new grounding rule is strictly *more* restrictive than today's
  single-capability rule in every dimension except the explicit,
  narrow, hand-authored template allowance - it can never cause a
  request to be accepted that would have been refused before, since
  the new code path is never reached from any live decision.
- The compound-template allowlist (`_ALLOWED_COMPOUND_TEMPLATES`) is
  trusted, static, hand-authored data - never model-supplied, never
  derived from parsed output, exactly matching every other trusted
  catalog table in this codebase.

## 26. Trusted-versus-model-controlled boundaries

- Model-controlled: which two capability ids to declare (from the
  fixed allowlist only), and each step's own declared argument values
  (independently validated exactly as today).
- Trusted, never model-controlled: capability existence/catalog
  membership, `internal_only` exclusion, the compound-template
  allowlist itself (and therefore step order), argument-span markers,
  and the negation-marker list. This mirrors every existing trusted/
  model-controlled boundary in `intelligence/capability_catalog.py`
  and `intelligence/grounding.py` exactly - no new boundary philosophy
  is introduced.

## 27. Required production files

- `intelligence/capability_catalog.py` - new
  `_ALLOWED_COMPOUND_TEMPLATES` constant and a small accessor.
- `intelligence/structured_output.py` - new
  `parse_compound_tool_selection()` and its supporting dataclass(es)/
  exception reuse.
- `intelligence/grounding.py` - new `ground_compound_decision()` and
  one new `UngroundedReason` member.

No other production file changes - `intelligence/planning.py`,
`core/orchestrator.py`, `workflow/engine.py`,
`workflow/paused_workflow_store.py`, `approval/approval_manager.py`,
`security/security_manager.py`, and `tools/executor.py` are all
untouched.

## 28. Required test files

- `tests/unit/test_structured_output.py` - extended with a dedicated
  section for `parse_compound_tool_selection()` (or a new, sibling
  test file, e.g. `test_structured_output_compound.py`, if the
  addition is large enough to warrant separation - decided during
  implementation based on actual size).
- `tests/unit/test_grounding.py` - extended (or a new sibling file)
  for `ground_compound_decision()`.
- `tests/unit/test_capability_catalog.py` - extended for
  `_ALLOWED_COMPOUND_TEMPLATES`.

## 29. Focused test matrix

- Schema: exact key set, duplicate-key rejection, fence stripping,
  2,000-char cap - all reused/re-verified for the new decision literal.
- Exactly-two-entries enforcement for `capability_ids`/`arguments`
  (zero, one, three entries all rejected).
- Each declared capability independently validated against its own
  `CapabilityArgumentSpec` (missing required argument, wrong type,
  oversized string, unknown argument name - one test per rule, per
  step position).
- `internal_only` capability named in either position - rejected.
- Unknown `capability_id` in either position - rejected.
- Ordered pair present/absent from `_ALLOWED_COMPOUND_TEMPLATES` -
  present passes structural parsing; absent is rejected with
  `COMPOUND_TEMPLATE_NOT_ALLOWED` at the grounding layer (not the
  parsing layer, matching the existing execution-order convention:
  parse/validate arguments first, ground afterward).
- Worked example end-to-end: "update jarvis project state phase to
  <value> and show jarvis project state" grounds successfully for
  `(PROJECT_STATE_UPDATE_PHASE, PROJECT_STATE_SHOW)`; a request that
  additionally, coincidentally matches a third signature is refused
  with `MULTIPLE_SIGNATURES_MATCHED`-equivalent handling generalized
  to the compound case; a request naming the pair but only evidencing
  one of the two capabilities in text is refused; a request with the
  phase value not attributable to the live text is refused
  (`ARGUMENT_VALUE_MISMATCH`); a negated request
  ("do not update ... and show ...") is refused
  (`NEGATED_OR_CONFLICTING_REQUEST`).
- Structural/AST test proving `select_tool()`/`_TRUSTED_PLANNING_INSTRUCTION`
  are byte-for-byte unchanged (a diff-based or hash-based regression
  guard), and that neither calls the new functions - proving the
  "not wired live" scope boundary holds, not merely asserting it in
  prose.

## 30. Full regression requirements

- Full suite in all three required environments (normal,
  `AI_REASONING_ENABLED=false`, `PYTHON_DOTENV_DISABLED=1`) must match
  the existing 5203 passed / 3 skipped / 0 failed baseline exactly,
  since this phase adds tests but changes no existing behavior.
- Ruff clean on every changed file.
- `git diff --check` clean.

## 31. Documentation requirements

- `docs/phase_97_completion_report.md` (created at implementation
  time) documenting the foundation and its explicit non-goals.
- No `docs/user_guide.md` or `tools/builtin/help_tool.py` change - no
  user-visible behavior exists to document (Section 9).

## 32. Non-goals

- No live wiring into `select_tool()` or the trusted planning
  instruction.
- No `Plan`/`WorkflowEngine` execution of any compound request.
- No approval, no persistence, no verification of any compound request.
- No arbitrary capability pairing - only the fixed, hand-authored
  `_ALLOWED_COMPOUND_TEMPLATES` allowlist.
- No change to any existing capability, tool, verifier, or the
  existing single-capability decision path.
- No schedule creation, memory save, browser/Word/computer/phone
  control, shell/Python execution, dashboard change, or voice feature.

## 33. Deferred work

- Wiring `parse_compound_tool_selection()`/`ground_compound_decision()`
  into `select_tool()` and the trusted planning instruction (this is
  Option C's own future scope, only attempted once this foundation's
  own test suite has been in place and stable).
- Building the actual compound `Plan` construction, execution,
  approval, and verification machinery (Option C).
- Expanding `_ALLOWED_COMPOUND_TEMPLATES` beyond the one worked
  example.
- The post-execution data-propagation gap identified in Phase 96's own
  planning gate (`SCHEDULE_CREATE`/`MEMORY_SAVE`) remains fully
  deferred, unrelated to this phase's scope.
- Option B (durable sequential workflow foundation) and Option D
  (outcome/task context foundation) both remain available future
  candidates, neither selected this cycle.

## 34. Stop conditions

None of the task's listed stop conditions apply to the selected
design: it changes no persisted workflow, requires no persistence
migration, adds no model-authored step, does not weaken unique
grounding (it strictly generalizes it, gated by a trusted, static
allowlist), infers no argument not attributable to the live request,
lets no approval authorize more than its own step (approval is not
exercised at all this phase), never reruns a completed step, calls no
tool `run()` directly, mutates no store directly from the Intelligence
Core, adds no orchestrator branch of any kind (orchestrator is
untouched), verifies nothing unverified (nothing executes), retries or
replans nothing, and is small enough for one controlled phase (three
files, all additive, zero live behavior change).

## 35. Implementation batch structure

A single implementation batch is sufficient given the phase's small,
additive, non-live-wired scope:

- Batch 1 (only batch): `_ALLOWED_COMPOUND_TEMPLATES` +
  `parse_compound_tool_selection()` + `ground_compound_decision()` +
  full test coverage (Section 29) + regression + documentation +
  completion report.

## 36. Formal planning-gate conclusion

The live architecture does not yet safely support representing more
than one model-selected capability per request; the single, real
blocking cause is `intelligence/grounding.py`'s uniqueness rule, not
the execution/persistence/approval layer, which already generalizes to
an arbitrary step count (confirmed by direct inspection, Section 4).
The safest, smallest, highest-reuse-value next phase is therefore a
grounding-and-parsing-only foundation, built and fully tested in
isolation, with zero live behavior change and zero execution risk,
explicitly deferring actual compound execution (Option C) to a later,
separately-planned phase once this foundation is proven. This
conclusion is offered with the evidence, in Sections 4-6, to support
it, and does not trigger any of the task's stop conditions.
