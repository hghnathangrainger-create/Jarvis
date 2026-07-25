# Phase 99 Planning Gate — Second Bounded Compound Template

Planning-only. No production code is changed by this document. Phase 99
has not started; nothing here is an implementation. Written before any
Batch 1 work, per the task's own explicit instruction to stop and wait
for approval after this gate.

## 0. Amendment (supersedes Sections 4, 6, and 8's final-step content below)

The first version of this document approved `SCHEDULE_LIST` as Phase
99's final read step on the basis that its formatter includes each
schedule's id and enabled state. A follow-up review correctly rejected
that as insufficient: printing the state is not the same as
guaranteeing the affected row is present in a bounded, ordered,
non-paginated list. Section 3.5 below proves, by direct inspection of
`scheduling/schedule_store.py` and its own existing tests, that
`SCHEDULE_LIST` **cannot** guarantee the just-enabled schedule appears
in its output once more than 50 schedules exist - and, worse, that the
ascending-by-id ordering means the *most recently created* schedules
(arguably the most likely to be interacted with) are the ones most
likely to be cut off first. **`SCHEDULE_LIST` is rejected as Phase 99's
final step.** The recommended replacement is a new, narrow,
non-internal GREEN capability - provisionally named
`SCHEDULE_SHOW_ENABLED_STATE` - detailed in Section 3.6. This is a
small, bounded addition (one new capability, reusing the exact
`get(schedule_id)` read pattern the existing internal verifier already
uses), not a schedule-query or pagination redesign - so this finding
does not, by itself, trigger Phase 99's own stop condition.

## 1. Current git status and baseline confirmation

- Branch `phase-4-ai-reasoning-and-write-actions`, HEAD `e8183d4` ("Activate
  and close Phase 98 live compound workflow").
- `git status --short`: only `?? dashboard_test.txt` (pre-existing,
  unrelated, untracked - left untouched throughout this audit and will
  remain untouched for the rest of Phase 99).
- Full suite, re-run fresh at the start of this planning pass: **5687
  passed, 3 skipped, 0 failed**.
- This document itself changes no `.py` file, so Ruff/`git diff --check`
  scopes are unaffected by writing it.

## 2. Relevant architecture and call-flow summary

The live ProjectState compound path, exactly as Phase 98 closed it:

```
CommandRouter.match_ask_jarvis_to()
  -> JarvisOrchestrator._handle_ask_jarvis_to_request()
    -> intelligence.planning.select_tool()
         - router.route() -> peek_compound_decision(response.text)
         - True -> _select_compound_tool_sequence()
             - parse_compound_tool_selection()          [intelligence/compound_structured_output.py]
             - ground_compound_decision()                [intelligence/compound_grounding.py]
             - _build_phase_update_verify_show_workflow_plan()  [intelligence/planning.py]
    -> JarvisOrchestrator._start_compound_update_phase_and_show_workflow()
         - WorkflowEngine.run(plan) -> WAITING
         - establish_compound_progress_or_isolate()      [core/compound_workflow.py]
    -> (approval, via ui/cli.py -> validate_pending_approval_for_transition() -> approvals.approve())
    -> JarvisOrchestrator._claim_and_resume_workflow()
         - _compound_step_observer_for() -> matches_compound_plan_shape() + compound_progress_identity_matches()
         - WorkflowEngine.resume(step_observer=CompoundStepObserver(...))
         - except CompoundCheckpointError: honest bounded message, row stays CLAIMED
         - translate_compound_workflow_result() -> one of 6 CompoundResultKind outcomes
main.reconcile_claimed_handoffs()  (startup, before generic fallback)
    -> repair_or_isolate_pending_compound_progress()
    -> terminalize_declined_or_expired_compound_progress()
    -> reconcile_claimed_compound_workflows() -> resume_claimed_compound_workflow()
    -> (existing, unchanged) _reconcile_claimed_rows()
```

Every layer above `intelligence/compound_structured_output.py` and
`intelligence/compound_grounding.py` (the parser and the template
allowlist) is, to varying degrees, written specifically for the one
ProjectState template - detailed in Section 9.

## 3. Candidate comparison

Both candidates share an identical shape: `SCHEDULE_{ENABLE,DISABLE}`
(YELLOW, already paired with `SCHEDULE_VERIFY_ENABLED_STATE` as an
existing, live, two-step write+verify workflow since Phase 94) followed
by a final read step (originally proposed as `SCHEDULE_LIST` - rejected
in Section 3.5 below in favor of a new, narrow read capability, Section
3.6). Both already use trusted exact-boolean verification via the same
internal verifier tool. Neither is structurally stronger than the
other - the only asymmetry is in the target boolean (`enabled: True`
vs. `enabled: False`), which is irrelevant to safety or truthfulness or
to the final-read-step question addressed below.

**Recommendation: select `SCHEDULE_ENABLE` as the write step.** "Enable"
is the more common real-world trigger for wanting to immediately
confirm the result (re-activating something you want to see is now
live), matching the same "do a thing, then see the result" motivation
the ProjectState template already serves. Disable adds no new technical
coverage - it exercises the exact same code paths with the opposite
boolean - so activating both in Phase 99 would only double the surface
area needing new tests/docs for zero additional architectural proof.
Per the task's own instruction, only one template is selected. A
`SCHEDULE_DISABLE`-paired template remains available as a trivial,
near-zero-marginal-cost future addition once Phase 99's own
generalization boundary is proven correct - not part of this batch.

## 3.5. `SCHEDULE_LIST` deterministic-visibility audit (supersedes this
document's original Section 4's approval of `SCHEDULE_LIST`)

Direct inspection of `scheduling/schedule_store.py` (the sole data
layer both `ScheduleListTool` and every other schedule tool depend on):

- **Bounded**: yes. `ScheduleStore.list_all(limit: int = 50)` clamps
  any requested value into `[1, _MAX_LIMIT]` via `_clamp_limit()`
  (`scheduling/schedule_store.py:316-329`), where `_MAX_LIMIT = 50`
  (line 48).
- **Exact maximum result count**: **50**, always - `SCHEDULE_LIST`'s
  own catalog entry declares zero arguments
  (`intelligence/capability_catalog.py:321-333`), and
  `ScheduleListTool.run()` always calls `list_all(limit=_DEFAULT_LIMIT)`
  with its own fixed `_DEFAULT_LIMIT = 50`
  (`tools/builtin/schedule_list_tool.py:17,75`) - there is no path,
  live or AI-driven, by which a caller can request more than 50.
- **Ordering**: `ORDER BY ScheduleEntry.id ASC` - ascending by primary
  key, i.e. **oldest-created-first** (`schedule_store.py:174-179`,
  docstring explicitly: "ordered oldest-created-first (by id), unlike
  every other store's newest-first convention"). Confirmed by the
  existing, passing test `test_list_all_returns_ascending_id_order`
  (`tests/unit/test_schedule_store.py:133`).
- **Filtering/pagination**: none. No enabled/disabled filter, no
  offset/cursor parameter exists anywhere in `ScheduleStore`,
  `ScheduleListTool`, or the `SCHEDULE_LIST` capability entry.
- **Disabled schedules included**: yes, unconditionally - `list_all()`
  has no `WHERE` clause on `enabled` at all; every row up to the limit
  is returned regardless of state.
- **Is an enabled schedule with an arbitrary valid `schedule_id`
  guaranteed to appear?** **No.** Confirmed by
  `test_list_all_clamps_limit_above_max`
  (`tests/unit/test_schedule_store.py:153-156`, proving `list_all()`
  never returns more than 50 rows even when more exist) combined with
  the ascending-id ordering: once more than 50 schedules exist, only
  the 50 *lowest-id* rows are ever returned. Any schedule whose id
  ranks 51st-or-later in ascending order is unconditionally excluded -
  deterministically, not probabilistically.
- **What happens when more schedules exist than the limit**: the extra
  rows are silently dropped from the returned window. The list's own
  header (`f"Schedules ({enabled_count} enabled, {disabled_count}
  disabled):"`) tallies *all* fetched records honestly, but since the
  fetch itself is already capped at 50, that tally itself only ever
  covers the same 50-row window - it never reports the true total
  count of schedules that actually exist. No error, no truncation
  notice, no indication in the output that omitted rows exist at all.
- **Can the affected schedule be omitted even though the compound
  workflow succeeded?** **Yes, deterministically reproducible.**

**Adversarial example.** 61 schedules exist, ids 1-61 (created in that
order over time - an entirely ordinary usage pattern, not a contrived
edge case). The user runs `ask jarvis to: enable schedule 61 and then
show my schedules`. Step 1 (`schedule_enable`, id=61) succeeds - it
targets exactly one row by id, independent of any list. Step 2
(`schedule_verify_enabled_state`, id=61) reads via `ScheduleStore.get(61)`
directly (also independent of any list) - succeeds, VERIFIED. Step 3's
gate passes. `schedule_list` then runs `list_all(limit=50)`, which
returns ids **1 through 50 only** (ascending order, hard limit) -
schedule 61 is completely absent. The final response reads, in effect,
"Jarvis enabled schedule 61. Verification succeeded, and here are your
schedules:" followed by a list that does not mention schedule 61 at
all. Nothing in the displayed list is individually false, but the
compound's own implicit promise - "see the result of what you just
did" - is broken: the one schedule the user just acted on is invisible
in its own confirmation. The failure mode is *worse* than a uniformly
random omission risk, too: because ordering is ascending-by-id, the
schedules most likely to be recently created (and therefore most
likely to be the ones a user is actively enabling/disabling) are
exactly the ones most likely to be cut off once the total count passes
50.

**Conclusion: `SCHEDULE_LIST` cannot guarantee the affected schedule's
visibility once more than 50 schedules exist. It is rejected as Phase
99's final step**, even though it is the nearest existing read
capability and even though this codebase is a single-user, personal
system unlikely to reach 61 schedules soon - the task's own instruction
is to prove determinism, not estimate probability, and the proof above
is unconditional (it does not depend on how many schedules Nathan
happens to have today).

## 3.6. Selected final-read alternative

Evaluating the task's own three options:

1. **Reuse an existing exact schedule-state read path.** None exists.
   Confirmed by exhaustive inspection of `core/command_router.py`'s
   complete schedule grammar (`_SCHEDULE_CREATE_PREFIXES`,
   `_SCHEDULE_LIST_EXACT`, `_SCHEDULE_ENABLE_PREFIXES`,
   `_SCHEDULE_DISABLE_PREFIXES` - lines 557-560, and their dispatch at
   lines 911-936) and `intelligence/capability_catalog.py`'s complete
   `CapabilityId` enum: the only schedule-related entries are
   `SCHEDULE_LIST` (bulk, just rejected), `SCHEDULE_ENABLE`,
   `SCHEDULE_DISABLE` (both write-only), and
   `SCHEDULE_VERIFY_ENABLED_STATE` (`internal_only=True` - never
   independently selectable, never shown to a user as a "result," and
   using it as Step 3 would collapse the deliberate internal-verify/
   public-display separation the ProjectState template establishes).
   **Option 1 is unavailable.**
2. **Add one narrow GREEN read-only capability.** Selected. New
   capability, provisionally `SCHEDULE_SHOW_ENABLED_STATE`
   (`tool_name="schedule_show_enabled_state"`), a genuinely new,
   independent tool mirroring `ScheduleVerifyEnabledStateTool`'s own
   `ScheduleStore.get(schedule_id)` read exactly, but **not**
   `internal_only` - it plays the same public, independently-nameable
   "display" role `PROJECT_STATE_SHOW` already plays for the
   ProjectState template, reading and formatting exactly one schedule's
   real, current state deterministically (a primary-key lookup has no
   ordering/limit/pagination concern of any kind - `ScheduleStore.get()`
   either finds the exact row or it does not exist at all). Threaded
   internally from Step 1's own approved `schedule_id` exactly as Step
   2 already is (Section 8 below).
3. **Stop Phase 99.** Not warranted - a single, narrow, one-argument,
   read-only GREEN capability reusing an existing store method is not
   "a broad schedule-query or pagination redesign"; it is smaller in
   scope than the `enabled_str` metadata addition itself.

This is a genuine, honest capability-surface gap closed as a
consequence of this audit (there is currently no way to check *one*
schedule's state without listing up to 50) - not scope creep invented
for its own sake. **Recommendation: do not add a deterministic
`CommandRouter` grammar line for it in Phase 99** (e.g. no new "show
schedule <id>" typed command) - keep it reachable only as (a) Step 3 of
this one compound template, and (b) incidentally, through the existing
generic `ask jarvis to:` single-capability path, since being non-
`internal_only` makes it structurally selectable there too, exactly as
`PROJECT_STATE_SHOW` already is. Deliberately keeping it *out* of the
trusted planning instruction's own numbered single-capability
enumeration (Section 8) means the model is never told about it as a
standalone option and can never emit its `capability_id` outside the
one compound paragraph that names it - mirroring how
`PROJECT_STATE_VERIFY_FOCUS`/`SCHEDULE_VERIFY_ENABLED_STATE` are kept
unreachable via `internal_only=True`, except here the capability is
real (has a genuine GREEN preflight and its own catalog entry) rather
than blocked outright, since Step 3 in this template's own established
shape requires a real, non-internal capability, not an internal one.

## 4. Recommended Phase 99 template

**`SCHEDULE_ENABLE → SCHEDULE_SHOW_ENABLED_STATE`** (not
`SCHEDULE_LIST` - see Section 3.5/3.6), using the existing
`SCHEDULE_VERIFY_ENABLED_STATE` tool as the trusted, internal, model-
invisible middle verification step - mirroring the ProjectState
template's three-role shape (write → internal verify → public show),
with one adaptation Section 8 documents: Step 3 here requires an
argument (`schedule_id`) threaded from Step 1, unlike
`PROJECT_STATE_SHOW`'s own zero-argument read of a singleton row.

`SCHEDULE_SHOW_ENABLED_STATE` is truthful and sufficient by
construction: a primary-key lookup (`ScheduleStore.get(schedule_id)`)
either returns the exact row or definitively does not exist - there is
no window size, ordering, or count for which the target could be
silently omitted while still existing. This closes the exact gap
`SCHEDULE_LIST` could not.

## 5. Exact user-facing grammar

```
ask jarvis to: enable schedule <id> and then show schedule <id>'s enabled state
```

Clause 1 reuses the exact, already-live phrasing `ask jarvis to: enable
schedule <id>` already grounds correctly today. Clause 2 is new
phrasing for the new capability (no existing live grounding to reuse,
since the capability itself is new) - grounding-signature wording is
finalized during Batch 1/2, matching `intelligence/grounding.py`'s
existing per-capability marker-phrase convention (e.g. `SCHEDULE_ENABLE`'s
own `"schedule <id>"` marker), reusing the identical `<id>` numeric-
argument attribution logic already proven for
`SCHEDULE_ENABLE`/`SCHEDULE_DISABLE`. Joined by the identical fixed
connector `" and then "` the ProjectState template already uses - no
new connector vocabulary, per the task's own constraint.

## 6. Exact trusted three-step plan

1. **`SCHEDULE_ENABLE`** (YELLOW, approval required) - `schedule_enable`
   tool, `tool_input={"schedule_id": <id>}`.
2. **`SCHEDULE_VERIFY_ENABLED_STATE`** (GREEN, internal-only, never
   AI-selectable) - `schedule_verify_enabled_state` tool,
   `tool_input={"schedule_id": <id>}` (threaded from Step 1's own
   already-validated input, via the existing
   `paired_verify_input_keys=("schedule_id",)` mechanism - unchanged).
3. **`SCHEDULE_SHOW_ENABLED_STATE`** (GREEN, real/non-internal,
   read-only) - new `schedule_show_enabled_state` tool,
   `tool_input={"schedule_id": <id>}` (threaded from Step 1's own
   already-validated input - a new, second propagation the plan-builder
   must perform, since `PROJECT_STATE_SHOW`'s own Step 3 needs no
   argument at all; this is the one genuinely new piece of plan-
   construction logic this template requires beyond mirroring the
   ProjectState builder), `requires_verified_predecessor=True`,
   `verification_field_name="enabled_str"`,
   `verification_expected_value="true"` - gated on Step 2's own
   verification outcome via the new additive string-mirror metadata key
   (Section 8's `enabled_str` contract).

## 7. Approval and progress-creation sequence

Identical in shape to the ProjectState template, Section-for-section:

1. `select_tool()` recognizes the new template pair via
   `peek_compound_decision()` (unchanged) →
   `_select_compound_tool_sequence()` (unchanged dispatcher) → a new,
   narrow `_build_schedule_enable_verify_show_workflow_plan()` builder
   (mirrors `_build_phase_update_verify_show_workflow_plan()`, with the
   two-step argument threading noted in Section 8).
2. `WorkflowEngine.run(plan)` → `WAITING` (Step 1 is unconditionally
   YELLOW, exactly as today).
3. A new `JarvisOrchestrator._start_schedule_enable_and_show_workflow()`
   calls a new `establish_schedule_compound_progress_or_isolate()`
   (mirrors `establish_compound_progress_or_isolate()` exactly, writing
   into the new, separate progress store from Section 8) **before**
   returning the approval response - identical ordering guarantee.
4. `ui/cli.py`'s existing `validate_pending_approval_for_transition()`
   call site requires no change to its own call site, but the
   orchestrator method it calls must additionally recognize the new
   template (Section 9).
5. One approval, covering only the exact recognized three-step request
   - never wider.

## 8. Required code changes by file

- **`storage/models.py`** - new ORM table, e.g. `ScheduleCompoundWorkflowProgress`
  (additive, guarded migration, mirroring `CompoundWorkflowProgress`'s
  own migration precedent): `id`, `workflow_id` (unique), `template_id`,
  `request_id`, `approved_schedule_id: int`, `approved_target_enabled: bool`,
  `pre_execution_enabled_state: bool | None`, `step_1_status`,
  `step_2_status`, `step_2_verification_outcome`, `step_3_status`,
  `overall_status`, `created_at`, `updated_at`.
- **`workflow/schedule_compound_workflow_progress_store.py`** (new) -
  `ScheduleCompoundWorkflowProgressStore`, mirroring
  `CompoundWorkflowProgressStore`'s exact method set and CAS
  discipline, reusing the *same* `CompoundStepStatus`/
  `CompoundOverallStatus`/`CompoundVerificationOutcome` enums (already
  generic, no field-name coupling) - including the new
  `NOT_EXECUTED` member and `mark_not_executed_before_start()` shape,
  and a new `reconcile_schedule_enabled_state()` pure function mirroring
  `reconcile_phase_update()` but comparing booleans, not strings.
- **`workflow/schedule_compound_progress_observer.py`** (new) - a second
  concrete `_CompoundStepObserver` implementation (duck-typed, same
  Protocol, zero `WorkflowEngine` change needed - the Protocol and
  `step_observer` parameter are already capability-agnostic), performing
  its own pre-execution `schedule_verify_enabled_state` read.
- **`tools/builtin/schedule_show_enabled_state_tool.py`** (new) - the
  new, non-`internal_only`, public GREEN capability's own tool
  (Section 3.6): `ScheduleShowEnabledStateTool`, reading exactly one
  schedule via `ScheduleStore.get(schedule_id)` and formatting a short,
  honest human-readable line (its own real, independent read - never
  reusing Step 2's already-fetched result, exactly mirroring how
  `PROJECT_STATE_SHOW`'s own Step 3 always performs a fresh read rather
  than assuming Step 2's value).
- **`tools/builtin/schedule_verify_enabled_state_tool.py`** - **one
  additive metadata key only**: alongside the existing boolean
  `metadata["enabled"]`, add `metadata["enabled_str"] = "true"/"false"`
  (a string mirror). Full derivation and fail-closed contract in
  Section 8.1 below.
- **`intelligence/capability_catalog.py`** - one new `CapabilityId`
  member (`SCHEDULE_SHOW_ENABLED_STATE`) and one new `CapabilityAdapter`
  entry: `tool_name="schedule_show_enabled_state"`,
  `arguments=(CapabilityArgumentSpec(name="schedule_id", type_name="int", required=True),)`,
  `allowed_strategy=ExecutionStrategy.SINGLE_TOOL`,
  `max_execution_tier=SecurityTier.GREEN`, `internal_only=False` (real,
  per Section 3.6 - not blocked, but also never listed in the trusted
  instruction's own single-capability enumeration, so the model is
  never told it exists as a standalone option).
- **`intelligence/compound_grounding.py`** - **one new
  `CompoundTemplate` entry** in `_ALLOWED_COMPOUND_TEMPLATES`:
  `(SCHEDULE_ENABLE, SCHEDULE_SHOW_ENABLED_STATE)`, same connector. No
  structural change - the module already iterates a tuple of templates.
  A new per-capability argument marker for
  `SCHEDULE_SHOW_ENABLED_STATE` in `intelligence/grounding.py`'s
  existing marker table (Section 5), reusing the identical numeric-
  argument attribution logic `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE`
  already use.
- **`intelligence/planning.py`** - one new paragraph in
  `_TRUSTED_PLANNING_INSTRUCTION` describing the second fixed template
  (mirroring the existing paragraph's exact prohibition wording, and
  never separately listing `SCHEDULE_SHOW_ENABLED_STATE` as a
  standalone numbered capability); one new private builder function
  `_build_schedule_enable_verify_show_workflow_plan()`, which must
  thread `schedule_id` into *two* downstream steps (verify and show),
  not one, generalizing the existing write→verify
  `paired_verify_input_keys` threading one step further as a small,
  hand-written propagation specific to this one new builder - not a
  generic framework; a small, explicit two-branch dispatch inside
  `_select_compound_tool_sequence()` (or a thin wrapper around it)
  choosing which builder to call, keyed on the *parsed* pair's own
  capability ids (never model free text) - not a generic registry, a
  fixed `if`/`elif` matching the two currently-allowed pairs.
- **`core/schedule_compound_workflow.py`** (new, parallel to
  `core/compound_workflow.py`) - `matches_schedule_compound_plan_shape()`,
  `schedule_compound_progress_identity_matches()`,
  `establish_schedule_compound_progress_or_isolate()`,
  `repair_or_isolate_pending_schedule_compound_progress()`,
  `validate_schedule_compound_approval_before_transition()`,
  `reconcile_claimed_schedule_compound_workflows()`,
  `resume_claimed_schedule_compound_workflow()`,
  `terminalize_declined_or_expired_schedule_compound_progress()`,
  `translate_schedule_compound_workflow_result()` (a new
  `ScheduleCompoundResultKind` with its own six honest outcomes, message
  text about "the schedule" rather than "the project-state phase").
  Each function's *shape* is a narrow, mechanical mirror of its
  ProjectState counterpart - not a generalized abstraction over both.
- **`core/orchestrator.py`** - `compound_progress_store` gains a sibling
  optional constructor collaborator, `schedule_compound_progress_store`;
  `validate_pending_approval_for_transition()`,
  `_compound_step_observer_for()`, `_claim_and_resume_workflow()`, and
  `_terminalize_declined_compound_progress()` each gain a small,
  explicit "try ProjectState template, then try schedule template"
  two-branch check (never a loop over an open-ended registry - exactly
  two branches, hardcoded) before falling through to "not recognized as
  either compound template." New
  `_start_schedule_enable_and_show_workflow()` mirrors
  `_start_compound_update_phase_and_show_workflow()`.
- **`main.py`** - `build_orchestrator()` constructs and passes the new
  `ScheduleCompoundWorkflowProgressStore`; `reconcile_claimed_handoffs()`
  gains one more pair of calls
  (`repair_or_isolate_pending_schedule_compound_progress()` +
  `terminalize_declined_or_expired_schedule_compound_progress()` +
  `reconcile_claimed_schedule_compound_workflows()`, using its own
  small, dedicated, throwaway tool stack mirroring the existing
  ProjectState-only one) - ordering relative to the ProjectState passes
  does not matter (disjoint rows), but both must still run before the
  generic fallback. `ReconciliationSummary` gains four more integer
  fields, mirroring the existing four.
- **`ui/cli.py`** - no call-site change; the orchestrator method it
  already calls handles recognizing either template internally.
- **`tools/builtin/help_tool.py` / `docs/user_guide.md`** - one more
  narrow, honest example line, mirroring the existing one exactly in
  style (never exposing `execute_sequence`, never the word "compound").
- **Tests** - a new
  `tests/unit/test_phase99_batch{1,2,3}_*.py` family mirroring Phase
  98's own three-batch test suite shape (dormant foundation tests, then
  live-activation end-to-end tests), plus updates to the *existing*
  dormant/confinement-proof tests (`test_compound_isolation.py` and
  siblings) to prove the new template's wiring is *also* confined to
  its own intended, narrow set of functions - exactly the same
  AST-based confinement technique already established, extended to
  cover two templates instead of one.

### 8.1. The `enabled_str` derivation and fail-closed contract

`ScheduleVerifyEnabledStateTool.run()`'s current, live body
(`tools/builtin/schedule_verify_enabled_state_tool.py:130-149`) reads
`record = self._schedules.get(schedule_id)` and returns
`metadata={"schedule_id": record.id, "enabled": record.enabled}`. The
proposed additive change is exactly one more dict entry, computed in
the same `return` statement, from the same already-fetched `record`:

```python
return ToolResult(
    tool_name=self.name,
    success=True,
    output=(...),                       # unchanged
    metadata={
        "schedule_id": record.id,       # unchanged
        "enabled": record.enabled,      # unchanged - still a real bool
        "enabled_str": "true" if record.enabled else "false",  # new
    },
)
```

- **Derived from the verifier's own observed, persisted state, never
  from the requested/expected value**: `enabled_str` reads from the
  identical `record.enabled` local variable `enabled` itself reads from
  - the same fetch, the same statement block, no second read, no
  parameter, no reference to `expected_enabled`, the write step's own
  `tool_input`, or any other value the caller supplied.
- **Only two valid values**: exactly the literals `"true"`/`"false"`
  (lowercase) - a closed, two-member vocabulary mirroring `bool`'s own
  exhaustiveness. No other casing or representation is ever produced.
- **Existing boolean key unchanged**: `metadata["enabled"]` keeps its
  exact current type, value, and key name.
- **Disagreement between `enabled` and `enabled_str` is impossible by
  construction, not merely unlikely**: both values are computed from
  the one `record.enabled` boolean, in the same expression evaluation,
  with no intervening mutation, second query, or branch that could
  observe a different state between the two - there is no code path
  that computes them from different sources or at different times.
- **Absence or malformed `enabled_str` causes verification-gate
  failure - with zero new code**: `WorkflowEngine._verification_gate_failure_reason()`
  (`workflow/engine.py:1415-1430`, unchanged) already returns a bounded
  stop reason whenever `actual_value is None or not isinstance(actual_value, str)`.
  Since `enabled_str` is unconditionally populated whenever this tool
  succeeds, there is no live path that omits it today; the existing
  gate's own pre-existing fail-closed behavior is what would catch a
  future regression (e.g. someone accidentally removing the key),
  exactly as it already protects the ProjectState template's own
  `"phase"` field.
- **No existing verifier reader changed to prefer the string field**:
  confirmed by direct source reading - `intelligence/verification.py`'s
  `verify_schedule_enabled_state()` (lines 213-260) and
  `core/orchestrator.py`'s `_schedule_enable_workflow_result_to_response()`/
  the analogous disable translator read `ToolResult.metadata["enabled"]`
  (the boolean) exclusively; neither references `enabled_str` anywhere,
  and Batch 1 must add a structural test (mirroring this codebase's own
  AST-based confinement-proof convention) asserting exactly that -
  `"enabled_str"` must not appear in either function's own source.
- **Existing single-capability schedule enable/disable workflows remain
  byte-for-byte unchanged**: the only production change is one
  additional, never-read (by existing code) dict entry; every existing
  reader accesses metadata by explicit key name, never by iterating all
  keys, so an unknown additional key is structurally inert for them.
- **Focused tests required (Batch 1, even though only the enable
  template goes live in Phase 99)**: both `record.enabled=True` (
  `enabled_str="true"`, the success/match case this batch actually
  wires) and `record.enabled=False` (`enabled_str="false"`, the
  mismatch case, and the shape a future `SCHEDULE_DISABLE` template
  would need) must be tested - `_verification_gate_failure_reason()`'s
  comparison is symmetric, and an asymmetric bug (e.g. only the "true"
  branch ever tested) would otherwise go undetected until a much later
  batch.

**Is the engine's string-only gate deliberate or accidental?** Checked
directly against `docs/phase_98_implementation_plan.md`, Section 16
("Formal amendment conclusion") and Section 17.1: `PlanStep.verification_expected_value: str | None`
and `_verification_gate_failure_reason()`'s `isinstance(actual_value, str)`
check were authored with the explicit acknowledgment that the design
was "all scoped to exactly one consumer" (the ProjectState template,
whose one relevant field, `phase`, happens to be a string). This reads
as a **deliberately narrow scope decision for its one known consumer at
the time**, not a considered, general evaluation of "should this gate
ever support a boolean" that concluded "no." It is a real, honest
limitation worth recording - **not generalized during Phase 99**, per
the task's own instruction, and resolved instead by the additive
string-mirror key above.

## 9. Template-specific assumptions and their classification

| # | Assumption | Where | Classification |
|---|---|---|---|
| 1 | `parse_compound_tool_selection()` validates *any* two-capability pair generically against the catalog | `intelligence/compound_structured_output.py` | **Already generic** - reused as-is, zero change. |
| 2 | `_ALLOWED_COMPOUND_TEMPLATES` is a tuple of `CompoundTemplate` entries, already designed for more than one | `intelligence/compound_grounding.py` | **Already an appropriate bounded registry** - append one entry, zero structural change. |
| 3 | `_CompoundStepObserver` Protocol, `step_observer` parameter, `CompoundCheckpointError`, `peek_paused_plan()`, `reconstruct_claimed_compound_plan()` | `workflow/engine.py` | **Already capability-agnostic** - reused as-is by a second, independent concrete observer. Zero engine change. |
| 4 | `PlanStep.verification_expected_value`/`verification_field_name` and `WorkflowEngine._verification_gate_failure_reason()` require the compared metadata value to be a `str` | `planner/plan_models.py`, `workflow/engine.py` | **Unsafe to generalize during Phase 99.** This is shared, already-tested engine infrastructure used by *every* verified-workflow plan (both existing two-step focus/phase/schedule workflows and both compound templates), not merely ProjectState-specific naming. Widening its type would touch code well outside this feature's own blast radius for a single new template's convenience. **Resolution: an additive string-mirror metadata key** (`enabled_str`) on the existing verifier tool - the gate itself needs no change, and the existing boolean key/every existing reader is untouched. |
| 5 | `CompoundWorkflowProgress` table's own columns (`approved_phase_value`, `pre_execution_phase_value`, `pre_execution_last_updated`) | `storage/models.py` | **Intentionally Phase-98-specific; safe (and correct) to duplicate narrowly**, not generalize - a schedule row's own approved values are typed differently (`int` schedule id + `bool` target state), and forcing a shared, generically-typed schema (e.g. a JSON blob column) would be a real, if small, redesign this phase should not attempt. A second, small, honestly-named table is simpler, safer, and equally durable. |
| 6 | `core/compound_workflow.py`'s recognizer/progress-creation/claimed-recovery/translator functions inline the literal `"phase"` field name and the three ProjectState `CapabilityId` module constants throughout | `core/compound_workflow.py` | **Intentionally Phase-98-specific; safe to duplicate narrowly** into a parallel `core/schedule_compound_workflow.py` - this module was never designed as a generic dispatcher, and retrofitting it to be one now would be exactly the "broader redesign" this phase must avoid. |
| 7 | `reconcile_phase_update()`'s crash-state comparison logic is string-equality-based | `workflow/compound_workflow_progress_store.py` | **Safe to duplicate narrowly** as `reconcile_schedule_enabled_state()` - boolean-equality-based, otherwise structurally identical. |
| 8 | `core/orchestrator.py`'s `_compound_step_observer_for()`/`_claim_and_resume_workflow()`/`validate_pending_approval_for_transition()` each call exactly one recognizer/one progress store today | `core/orchestrator.py` | **Appropriate to generalize minimally** - not into an open-ended registry, but into a small, explicit, two-branch "which of the (at most two) templates does this recognize as" check inside each method. This is the one place true duplication would be worse than a narrow, bounded, hardcoded dispatch (duplicating three fairly large methods verbatim, one per template, would itself become a maintenance burden and a correctness risk if the two copies ever silently drifted). |
| 9 | `main.reconcile_claimed_handoffs()`'s compound-first ordering assumes exactly one compound-specific block of passes | `main.py` | **Appropriate to generalize minimally** - add a second, structurally identical block of three calls for the schedule template, still strictly before the unchanged generic fallback. Not registry-based; two named blocks. |
| 10 | Help/user-guide text and the trusted planning instruction assume exactly one described exception | `tools/builtin/help_tool.py`, `docs/user_guide.md`, `intelligence/planning.py` | **Safe, mechanical duplication** - one more paragraph/line each, in the same fixed style. |

**No case required option 3 ("unsafe to generalize, and no safe
resolution exists")** except item 4, whose unsafety is resolved by an
additive metadata key rather than by declining the whole template - so
this audit does not recommend stopping.

## 10. State transitions

All transitions mirror the ProjectState template's own six-outcome
translator and non-execution terminalization exactly, substituting
"the schedule's enabled state"/"the schedule list" for "the project
phase"/"the project state":

- **Success**: Step 1 enables the schedule → Step 2 verifies
  `enabled_str == "true"` → Step 3 gate passes → `schedule_show_enabled_state`
  runs and shows that exact schedule now enabled → `FULL_SUCCESS`.
- **Tool (write) failure**: Step 1's `schedule_enable` tool fails (e.g.
  unknown schedule id) → `UPDATE_FAILURE`-equivalent, Steps 2/3 never
  attempted.
- **Verification failure (mismatch)**: Step 2 reads back `enabled_str
  == "false"` (write silently failed to persist) → `VERIFICATION_MISMATCH`-equivalent, Step 3 gated off, never runs.
- **Verification unavailable**: Step 2's tool call itself fails (schedule
  deleted between write and verify) → `VERIFICATION_UNAVAILABLE`-equivalent, Step 3 never runs.
- **Read (Step 3) failure**: `schedule_show_enabled_state` itself fails
  at read time (e.g. the schedule was deleted between Step 2's
  verification and Step 3's own fresh read - a narrow, real race the
  primary-key lookup surfaces honestly rather than silently, handled
  identically to the ProjectState template's own `FINAL_SHOW_FAILURE`)
  → the enable is still durably confirmed; only the final display
  failed.
- **Checkpoint failure**: identical mechanism, reused unchanged -
  `CompoundCheckpointError` raised by the new observer, caught in the
  same `_claim_and_resume_workflow()` block before generic `Exception`,
  honest bounded message, row stays `CLAIMED`, paused state restored.
- **Decline**: identical mechanism, reused unchanged - the new
  observer is never attached; `_terminalize_declined_compound_progress()`
  (generalized per item 8 above to recognize either template) calls the
  schedule store's own `mark_not_executed_before_start()`; zero tool
  calls; generic `WorkflowEngine` decline contract unaffected.
- **Expiry**: identical mechanism - the new
  `terminalize_declined_or_expired_schedule_compound_progress()` startup
  pass is the sole terminalization path, exactly mirroring the
  ProjectState template's own.
- **Restart/crash recovery**: `resume_claimed_schedule_compound_workflow()`
  mirrors the exact crash-state matrix (Section 15 of the reentry plan),
  substituting `reconcile_schedule_enabled_state()` for
  `reconcile_phase_update()`.

## 11. Security and regression risks

- **Risk**: the new two-branch dispatch in `core/orchestrator.py`
  (item 8) could recognize a plan as *both* templates if their shapes
  ever overlapped. **Mitigation**: the two templates use disjoint,
  non-overlapping tool-name triples (`project_state_*` vs.
  `schedule_*`) - structurally impossible to collide; a dedicated test
  proves this directly (an assertion that no plan can satisfy both
  `matches_compound_plan_shape()` and `matches_schedule_compound_plan_shape()`
  simultaneously).
- **Risk**: reusing the boolean `enabled` metadata key incorrectly
  instead of adding the new string mirror, silently breaking the
  existing gate. **Mitigation**: a dedicated regression test proving
  the existing `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE` two-step workflows'
  own response translators are completely unaffected by the new
  `enabled_str` key's addition (additive, never read by existing code).
- **Risk**: `main.reconcile_claimed_handoffs()` growing a third,
  fourth, fifth near-identical block per future template, becoming
  unreadable. **Mitigation**: explicitly out of scope for Phase 99 -
  if a third template is ever proposed, *that* planning gate must
  address whether the two-block pattern should become a small, bounded
  loop over an explicit list of exactly the accepted templates (never
  an open plugin registry) - noted here as a forward risk, not solved
  now.
- **Risk**: the new ORM table/migration destabilizing existing schema
  tests. **Mitigation**: purely additive (`CREATE TABLE IF NOT EXISTS`-
  guarded, mirroring the existing `CompoundWorkflowProgress` migration
  exactly), zero change to any existing table.
- **Regression risk to Phase 98's own ProjectState template**: every
  new two-branch check in `core/orchestrator.py`/`main.py` must try the
  *existing* ProjectState recognizer with fully unchanged logic and
  fully unchanged priority/behavior when the schedule template does not
  match - covered by re-running the complete, unmodified
  `test_phase98_batch3_live_compound_activation.py` suite unchanged
  (zero edits expected there) as part of Phase 99's own regression
  gate.
- **Regression risk to existing schedule enable/disable single-capability
  workflow**: covered by re-running
  `tests/unit/test_orchestrator_schedule_enable_workflow.py`/
  `test_orchestrator_schedule_disable_workflow.py` unchanged.

## 12. Focused and full-suite test plan

Mirrors Phase 98's own three-batch structure (dormant foundation →
dormant lifecycle → live activation), scaled down since most engine-
level infrastructure is reused unchanged:

- **New unit tests** (dormant, by direct construction, mirroring each
  Phase 98/Batch-2-equivalent test file's own shape): schedule compound
  recognizer, schedule progress store CAS primitives (including
  `mark_not_executed_before_start()` reuse and
  `reconcile_schedule_enabled_state()`), schedule compound plan builder,
  schedule compound result translator, schedule compound checkpoint
  behavior (reusing the *existing*, unmodified
  `test_workflow_engine_compound_checkpoints.py`-style fake-observer
  proof pattern against the engine's already-generic `step_observer`
  contract - no new engine test needed beyond confirming a second
  concrete observer also obeys it).
- **New live end-to-end test file**
  (`tests/unit/test_phase99_batch_live_schedule_compound_activation.py`),
  mirroring `test_phase98_batch3_live_compound_activation.py` section
  for section: decision activation, approval/progress creation, normal
  execution, six-outcome translation, checkpoint handling, decline/
  expiry terminalization, restart/crash recovery, regression
  (including the explicit "both templates coexist without dispatch
  ambiguity" test called for in Section 11).
- **Updated existing tests**: the three dormant-isolation/confinement
  files (Section 8's "Tests" bullet) - each existing confinement
  assertion widened from "confined to these ProjectState-only
  functions" to "confined to these ProjectState-only *or* these
  schedule-only functions," never weakened to "anything goes."
- **Full-suite verification**: all three required environments (normal,
  `AI_REASONING_ENABLED=false`, `PYTHON_DOTENV_DISABLED=1`); Ruff on
  both the Phase 99 batch scope and the complete Phase 98+99 combined
  scope; `git diff --check` on both ranges - identical discipline to
  every prior Phase 98 batch.

## 13. Proposed batch structure

- **Batch 1 (dormant foundation)**: new ORM table/migration, new
  `ScheduleCompoundWorkflowProgressStore`, new
  `schedule_compound_progress_observer.py`, new, real, non-`internal_only`
  `SCHEDULE_SHOW_ENABLED_STATE` capability/tool (catalog entry + new
  `schedule_show_enabled_state_tool.py` - not yet reachable, since
  nothing selects it until Batch 3's dispatch wiring), the additive
  `enabled_str` metadata key, `reconcile_schedule_enabled_state()`. All
  new, independently unit-tested, zero live wiring, zero behavior
  change to anything existing - mirrors Phase 98 Batch 1's own dormant
  scope.
- **Batch 2 (dormant lifecycle)**: new
  `core/schedule_compound_workflow.py` (recognizer, progress creation/
  isolation, approval-time validation, claimed recovery, six-outcome
  translator, decline/expiry terminalization), the new
  `_build_schedule_enable_verify_show_workflow_plan()`, the new
  `CompoundTemplate` entry in `compound_grounding.py`, the new grounding
  marker for `SCHEDULE_SHOW_ENABLED_STATE`. Fully built and tested by
  direct construction; still dormant - no call site in
  `core/orchestrator.py`/`main.py`/`select_tool()`'s live dispatch yet.
  Mirrors Phase 98 Batch 2's own dormant scope exactly.
- **Batch 3 (live activation)**: the two-branch dispatch additions in
  `intelligence/planning.py`, `core/orchestrator.py`, `main.py`; help/
  user-guide exposure; full live end-to-end + restart tests; the
  existing confinement-proof test updates; closure documentation.
  Mirrors Phase 98 Batch 3's own scope exactly.

Each batch individually passes the full suite, Ruff, and `git diff
--check` before the next begins - identical discipline to Phase 98.

## 14. Explicit non-goals

- No generic, capability-sequence-agnostic compound engine.
- No arbitrary multi-step planning, no LLM-generated tool chains.
- No loops, branching, parallelism, or variable result-passing between
  steps.
- No batching of multiple schedule ids in one compound request.
- No widening of approval scope - one approval, one exact recognized
  request, unchanged.
- No new connector vocabulary - `" and then "` reused verbatim.
- No change whatsoever to Phase 98's own ProjectState template, its
  table, its tests, or its documented guarantees.
- No change to the existing, live, single-capability `schedule_enable`/
  `schedule_disable`/`schedule_list` commands' own behavior.
- No `SCHEDULE_DISABLE`-paired template activation in Phase 99 (left
  for a trivial future addition once this template proves the pattern).
- No deterministic `CommandRouter` grammar entry for the new
  `SCHEDULE_SHOW_ENABLED_STATE` capability (Section 3.6) - it is reached
  only through this one compound template's own Step 3, and,
  incidentally, the existing generic `ask jarvis to:` single-capability
  path (never advertised there, per Section 3.6).
- No touching `dashboard_test.txt`.
- No refactor of `core/compound_workflow.py` into a shared, generalized
  module "for elegance" - it remains untouched; the new module is
  purely additive and parallel.

## 15. Stop condition for a broader redesign

If, during Batch 1 or 2 implementation, any of the following are
discovered, implementation must stop and a fresh planning amendment
must be written before continuing - mirroring exactly the discipline
that produced the Batch 2 acceptance correction and this session's own
decline/expiry correction in Phase 98:

- The `enabled_str` additive-metadata-key resolution turns out to be
  insufficient (e.g. the engine's gate needs deeper changes than a
  string mirror to work correctly for this template).
- The two-branch dispatch in `core/orchestrator.py`/`main.py` cannot
  stay small and explicit - e.g. it turns out three or more real call
  sites each need their own copy of the same two-branch logic, hinting
  a shared (but still bounded, non-generic) helper is actually required
  and was missed above.
- Any test proves a plan, request, or persisted row could be recognized
  as *both* templates simultaneously, or that recognizing one silently
  affects the other's own behavior.
- `SCHEDULE_SHOW_ENABLED_STATE`'s own primary-key read
  (`ScheduleStore.get(schedule_id)`) is found, on closer inspection, to
  have any non-deterministic visibility characteristic of its own
  (none is expected - a single-row lookup by primary key has no
  ordering/limit/pagination dimension - but this must be explicitly
  confirmed by a Batch 1 test before being relied upon).
- Threading `schedule_id` into *two* downstream steps (verify and show)
  in the new plan-builder is found to require anything beyond a small,
  hand-written propagation - e.g. if it turns out a third or fourth
  downstream step would eventually need the same value, hinting the
  existing `paired_verify_input_keys`-style mechanism itself needs a
  more general multi-step propagation primitive (out of scope for a
  three-step, single-threaded-value template like this one).

## Recommendation

**Replace the final step with a narrow exact schedule-state read.**
Proceed with **`SCHEDULE_ENABLE → SCHEDULE_SHOW_ENABLED_STATE`** (a new,
narrow, non-`internal_only` GREEN capability - Section 3.6 - not
`SCHEDULE_LIST`, which Section 3.5 proves cannot deterministically
guarantee the affected schedule's visibility once more than 50
schedules exist) as Phase 99's second bounded compound template,
structured as three batches mirroring Phase 98's own discipline exactly
(Section 13), with the `enabled_str` additive-metadata-key resolution
for the one genuine cross-cutting incompatibility found (Section 9,
item 4; full contract in Section 8.1), and the small, explicit,
two-branch (never registry-based) dispatch extensions in
`core/orchestrator.py`/`main.py` (Section 9, items 8-9) as the only
places true code-sharing across templates is introduced.

**Waiting for approval before starting Phase 99 Batch 1.**

## 16. Batch 3 closure — final live architecture and repository-discovered corrections

Phase 99 is formally closed as of Batch 3 (commit recorded in
`docs/phase_99_completion_report.md`). This section records the final,
as-built architecture and every place real implementation diverged from
this document's own earlier, illustrative sketches.

**Corrected grammar.** Sections 5-6's illustrative phrasing ("show
whether schedule `<id>` is enabled") was superseded during Batch 1 by
the actual, shipped grammar: `check the enabled state of schedule
<id>` (standalone) and `enable schedule <id> and then check the
enabled state of schedule <id>` (compound) — required by
`intelligence.grounding`'s numeric-argument-span extractor, which
requires the id to trail its clause.

**Two-template dispatch, exactly as Section 9 anticipated.**
`intelligence/planning.py`'s `_select_compound_tool_sequence()` tries
`ground_compound_decision()` (ProjectState) first; only when it reports
`CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED` (the declared capability
pair does not match the ProjectState steps at all) does it attempt
`ground_schedule_compound_decision()` (schedule). Since the two
templates' declared pairs are disjoint by construction, this is
provably never ambiguous. `PlanningOutcomeKind.EXECUTABLE_SCHEDULE_COMPOUND_WORKFLOW`
is a new, distinct enum member (never a reused/overloaded
`EXECUTABLE_COMPOUND_WORKFLOW`), letting `core/orchestrator.py`'s
`handle_request()` dispatch to the correct named start-method without
re-inspecting the Plan's own shape.

**`core/orchestrator.py`'s own two-template discriminator.**
`_compound_step_observer_for()` returns `(observer, _RecognizedCompoundKind)`
— `NONE`/`PROJECT_STATE`/`SCHEDULE` — checking the ProjectState
fingerprint first, the schedule fingerprint second, structurally unable
to match both for one workflow. `_claim_and_resume_workflow()`,
`validate_pending_approval_for_transition()`, and the decline path all
branch on this same discriminator.

**No changes to Phase 98's own live behaviour, ever.** Every
ProjectState-specific function, class, table, and test remained
untouched; every new schedule-specific counterpart is its own,
independent module or method, reusing only genuinely generic,
already-shared infrastructure (`workflow.engine.CompoundCheckpointError`,
the `_CompoundStepObserver` Protocol, `_DurableCompoundApprovalInvalidator`).

**One pre-existing observation, not fixed here (explicitly out of
scope per the Batch 3 mandate):** `terminalize_declined_or_expired_compound_progress()`
(Phase 98's own ProjectState function) does not guard against
recounting an already-`NOT_EXECUTED` row on a repeated call, so its own
docstring's "always returns 0 on every call after the first" claim does
not hold for the bare function in isolation (only the underlying
progress state is genuinely idempotent). The new schedule sibling,
`terminalize_declined_or_expired_schedule_compound_progress()`, was
written to guard against this from the start. Phase 98's own function
was deliberately left unmodified.

**Non-goals confirmed at closure:** no third compound template exists
or was started; no generic compound registry, discovery mechanism, or
generalized multi-step planner was introduced; `SCHEDULE_LIST` was
never touched; the verification engine's string-only contract was
never generalized; `dashboard_test.txt` was never touched.
