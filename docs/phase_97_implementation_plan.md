# Phase 97 — Bounded Three-Step Verified Workflow Foundation (Planning Gate)

Status: **planning gate only**. No production code changed. This
document is the sole deliverable of this phase.

## 1. Repository checkpoint at the start of this planning gate

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- Latest closed phase: Phase 96 — Verified ProjectState Phase Update,
  closed at commit `d7d16ff`.
- Trusted verified-write foundation currently supports exactly four
  `TWO_STEP_WORKFLOW` capabilities: `PROJECT_STATE_UPDATE_FOCUS`,
  `PROJECT_STATE_UPDATE_PHASE`, `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`.
- Full suite baseline: 5203 passed, 3 skipped, 0 failed, in all three
  required environments.
- `dashboard_test.txt` remains untouched, untracked, uncommitted.

## 2. Architecture inspection summary

Direct inspection of the live code (not memory of prior phases) covered:

- `workflow/engine.py` — `WorkflowEngine.run()`/`resume()`/`_run_from()`
  already execute a `Plan` of **arbitrary length**, strictly in order,
  one step at a time, pausing only at a step that
  `requires_confirmation` (i.e. a real YELLOW step) and stopping
  outright (STOP-only policy) at the first step that does not cleanly
  succeed. `_validate_executable_plan()` enforces only that step
  numbers are `1, 2, 3, ...` with no gaps and every step names a real
  `tool_name` — it does **not** cap the plan at two steps. The engine
  itself is therefore already a general N-step sequential executor;
  nothing in `workflow/engine.py` needs to change for this phase.
- `workflow/paused_workflow_store.py`-backed persistence
  (`_persist_paused_state`/`_try_reconstruct_paused_workflow`) already
  serializes the full `plan_steps` list and `completed_outcomes` list
  generically, with no assumption about exactly two steps. A paused
  workflow with three steps would already survive a restart correctly
  using existing code, unchanged.
- `intelligence/capability_catalog.py` — `CapabilityAdapter` already
  carries `paired_verify_capability_id`/`paired_verify_input_keys` as
  trusted, static, catalog-only data (never model-supplied), read by
  `intelligence/planning.py`'s workflow builder. This is exactly the
  established pattern a third, fixed step would extend.
- `intelligence/planning.py` — `_build_write_and_verify_workflow_plan()`
  deterministically builds an **exactly-two-step** `Plan`
  (write, then its catalog-paired verifier), with no per-capability
  branch; the AI never selects, orders, or configures step 2. This is
  the one place that would need to grow a third, still fully
  catalog-driven step.
- `intelligence/structured_output.py` and the trusted planning
  instruction in `intelligence/planning.py`
  (`_TRUSTED_PLANNING_INSTRUCTION`) enforce, at the schema level, that
  a model response selects **at most one** `capability_id` per
  request. This is a deeply audited, heavily-tested trust boundary
  (duplicate-key rejection, exact three-key schema, catalog/argument
  validation) and is **not** touched by this phase's selected design —
  see Section 4, Candidate B, for why a multi-capability-selection
  schema was considered and rejected.
- `core/orchestrator.py` — `_matching_two_step_write_capability()` /
  `_matches_two_step_workflow_shape()` recognise a completed/paused
  `WorkflowResult` purely structurally, from `CAPABILITY_CATALOG` data,
  with a hardcoded `len(steps) != 2` check; `_translate_verified_
  workflow_result()` then dispatches to one of four bespoke,
  capability-specific response-builder methods via a small
  `response_builders` data lookup (never an if/elif chain). Both would
  need small, honest generalization to recognise and translate a
  three-step shape for exactly one capability.
- `tools/builtin/project_state_verify_tool.py` — confirmed live: `run()`
  is documented and implemented to **never fail** ("Never fails
  outright" per its own docstring); it always returns
  `ToolResult(success=True, ...)`. This means the *engine* never stops
  the workflow because of a verification mismatch — mismatch is a
  purely semantic conclusion `intelligence/verification.py`'s
  `verify_project_state_field()` draws afterward, in
  `core/orchestrator.py`, by comparing the write step's own
  already-durable expected value against the verify step's real
  `ToolResult.metadata`. This fact is central to this phase's design
  (see Section 11): a third, fixed GREEN context step appended after
  the verify step will always execute once the write step completes,
  regardless of whether verification matched — because it is never the
  engine's job to know or act on that semantic conclusion.
- `intelligence/grounding.py` — one `_IntentSignature` per
  model-selectable `CapabilityId`, checked independently of workflow
  step count. Adding a third, fixed, non-model-selectable step to an
  existing capability's workflow requires **no** grounding change at
  all, since grounding only ever concerns the single capability_id the
  model selected, never the internal step count of its resulting plan.
- `docs/phase_90_implementation_plan.md` through
  `docs/phase_96_implementation_plan.md`/completion reports — confirm
  every one of the four existing `TWO_STEP_WORKFLOW` capabilities was
  deliberately kept to exactly two steps, and that Phase 96's own
  planning gate explicitly identified (and this phase's inspection
  re-confirms) that the only real blocker to a *different* kind of
  multi-step growth — sequencing a write whose target identity is only
  known **post-execution** (`SCHEDULE_CREATE`, `MEMORY_SAVE`) — is the
  complete absence of any Intelligence-Core-wired post-execution
  data-propagation mechanism. That specific gap is **not** solved by
  this phase (see Section 4, Candidate C) and remains correctly
  deferred, per the repository's own "never speculative" catalog
  philosophy (`CapabilityId`'s own class docstring).

## 3. Exact remaining Intelligence Core gap

After Phase 96, the Intelligence Core can select and safely execute
exactly **one** capability per request, whose execution is either a
single tool call or a fixed, catalog-paired **write-then-verify** pair.
It cannot yet:

- Execute more than two fixed steps for any capability.
- Give a verified-write capability a richer final response drawn from a
  second, independent read after the write is confirmed.
- Prove, with real code and real tests, that the existing generic
  workflow machinery (`WorkflowEngine`, the paused-state store, the
  catalog-driven shape-matcher) actually generalizes past N=2 — today
  this is an untested assumption, not a demonstrated fact.

This is the gap Phase 97 closes: a small, bounded, honestly-named proof
that the trusted workflow foundation generalizes to a fixed N=3 shape,
instantiated on exactly one real, already-existing capability.

## 4. Candidate Phase 97 options considered

### Candidate A — Selected: bounded three-step workflow for `PROJECT_STATE_UPDATE_PHASE`

Add a new, honestly-named `ExecutionStrategy.THREE_STEP_WORKFLOW`,
migrate only `PROJECT_STATE_UPDATE_PHASE` to it, and give it a third,
fixed, catalog-declared, model-uninvolved context step:
`PROJECT_STATE_SHOW` (already catalogued, already `SINGLE_TOOL`,
already GREEN, already zero-argument). After a phase update is written
and verified, the final grounded response also shows the complete,
current project-state record — not just the one field that changed.

### Candidate B — Rejected: let the AI select an ordered list of capabilities

Change the model-facing schema from one `capability_id` to an ordered
list (bounded to, say, 2). Rejected: this reaches directly into the
most heavily audited trust boundary in the codebase
(`intelligence/structured_output.py`'s exact three-key schema,
duplicate-key rejection, per-capability argument validation) and into
`intelligence/grounding.py` (which is currently defined entirely in
terms of one selected capability_id). It would require a second
grounding pass per selected item, a redesigned trusted planning
instruction, and materially larger attack surface for one planning
gate. It is also the closest of all candidates to the explicitly
excluded "generic model-authored workflow chaining" — the model would
be choosing *which* capabilities to combine and in what order, not
merely supplying arguments to one pre-authored template. Rejected as
disproportionate risk for the value gained, and in tension with the
explicit exclusions.

### Candidate C — Rejected (this phase): wire post-execution data propagation into the Intelligence Core path

Generalize `workflow/engine.py`'s existing `input_from_previous_step` /
`_PROPAGATED_FIELDS` mechanism (today wired only into the old
Phase 15/29 fixed-workflow path) into
`intelligence/planning.py`'s `_build_write_and_verify_workflow_plan()`,
so a later step could consume a write step's real, post-execution
`ToolResult.metadata` (unblocking `SCHEDULE_CREATE`/`MEMORY_SAVE` in a
future phase). Rejected for *this* phase specifically because it would
be built with **no real, currently-authorized consumer** — both
concrete candidates that would use it are explicitly excluded from
this phase's scope, and the repository's own catalog philosophy
("never speculatively") argues against building trusted-propagation
plumbing with nothing real plugged into it yet. This remains a strong
candidate for a **future** phase, once a specific write-with-real-id
capability is explicitly authorized.

### Candidate D — Rejected: prepend a read step before the write (show current state, then update it)

Symmetrical to Candidate A but showing the *old* state before the
write rather than the *new* state after it. Rejected as lower value:
knowing the state *after* a confirmed, verified write is what a user
actually wants to see; knowing the state immediately before is
redundant with the user's own prior "ask jarvis: ..." or "show jarvis
project state" calls, and does not improve confidence in the write
that just happened.

### Candidate E — Rejected (for this phase): a new compound read-only "briefing" capability

A wholly new, additive `CapabilityId` chaining three independent GREEN
reads (e.g. `project_state_show` + `health_check` + `schedule_list`)
with no write/approval involved at all. Rejected: it requires new
catalog entries, a new grounding signature, and new trusted-instruction
text (growing the model-facing capability count for its own sake) —
exactly the shape the exclusions warn against ("new ... capabilities
merely to increase the catalogue count"), and it answers fewer of the
required planning questions than Candidate A (it never exercises how a
GREEN step interacts with a preceding YELLOW step, since none of its
three steps ever need approval).

## 5. Honest comparison

| | New model-facing surface | Touches AI-decision schema/grounding | Proves GREEN+YELLOW step interaction | Reuses only existing catalog capabilities | Blast radius on existing, tested behavior |
|---|---|---|---|---|---|
| A (selected) | None (same `project_state_update_phase` request) | No | Yes | Yes (`project_state_show`) | Small — only `PROJECT_STATE_UPDATE_PHASE`'s own response gains detail; `PROJECT_STATE_UPDATE_FOCUS`/schedule enable/disable untouched |
| B | New (list-valued selection) | Yes, heavily | Yes | Not necessarily | Large — redesigns the core trust schema |
| C | None | No | N/A | N/A | None, but produces no visible capability this phase |
| D | None | No | Yes | Yes | Same size as A, lower value |
| E | New (`CapabilityId` addition) | Yes (new signature + instruction) | No | Yes | Small, but adds catalogue surface without a write/approval proof point |

Candidate A is the only option that is simultaneously additive-only
(no existing, tested capability's contract changes), fully answers the
required planning questions about GREEN/YELLOW interaction and
generalized step count, and needs no change to the trust-critical
decision schema or grounding module.

## 6. Selected Phase 97 objective

**Add `ExecutionStrategy.THREE_STEP_WORKFLOW` and give
`PROJECT_STATE_UPDATE_PHASE` a third, fixed, catalog-declared context
step (`PROJECT_STATE_SHOW`), proving the trusted workflow foundation
generalizes past two fixed steps, entirely through existing,
already-catalogued capabilities.**

`PROJECT_STATE_UPDATE_FOCUS`, `SCHEDULE_ENABLE`, and `SCHEDULE_DISABLE`
remain exactly as they are today — still `TWO_STEP_WORKFLOW`, zero
behavior change, zero test change required for any of the three.

## 7. Why this is the highest-value next phase

- It is the smallest concrete change that turns "the engine
  theoretically supports N steps" into "a real, user-reachable
  capability actually uses three steps, tested end-to-end" — directly
  answering the stated priority ("bounded multi-step planning...
  preserving trusted context between steps... step-by-step execution
  and verification").
- It reuses 100% existing, already-implemented, already-tested pieces
  (`PROJECT_STATE_SHOW`, `WorkflowEngine`, the paused-state store) — no
  new tool code, no new user-facing command, no new argument surface.
- It leaves the single riskiest trust boundary in the codebase (the
  one-capability-per-response AI decision schema) completely
  untouched.
- It generalizes a mechanism (`paired_context_capability_id` +
  `THREE_STEP_WORKFLOW`) that a future phase can reuse for
  `PROJECT_STATE_UPDATE_FOCUS` or `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE`
  with zero further architecture — satisfying "prefer a reusable
  intelligence improvement over another isolated capability."
- It gives Nathan a genuinely more useful response today: after
  updating the phase, Jarvis shows the whole current record, not just
  the one field that changed.

## 8. Exact in-scope behavior

- New `ExecutionStrategy.THREE_STEP_WORKFLOW` member.
- New `CapabilityAdapter.paired_context_capability_id: CapabilityId | None = None`
  field (defaults to `None` for every capability defined before this
  phase — zero behavior change for all of them).
- `CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_PHASE]` changes
  `allowed_strategy` from `TWO_STEP_WORKFLOW` to `THREE_STEP_WORKFLOW`
  and sets `paired_context_capability_id=CapabilityId.PROJECT_STATE_SHOW`.
  `paired_verify_capability_id` stays `PROJECT_STATE_VERIFY_FOCUS`,
  unchanged.
- `intelligence/planning.py`'s workflow builder is extended (not
  duplicated) so that, after building the existing write+verify pair,
  it checks `write_adapter.paired_context_capability_id`; if set, it
  preflights that capability exactly like the verifier (zero
  arguments, expects its own declared `max_execution_tier`, currently
  always GREEN for `PROJECT_STATE_SHOW`) and appends it as step 3. If
  unset (every other existing capability), behavior is byte-for-byte
  identical to today.
- `core/orchestrator.py`'s shape-matcher and dispatcher are extended to
  recognise a 2-step *or* 3-step shape, based on the matched
  capability's own `paired_context_capability_id` — never a hardcoded
  per-capability branch.
- `_project_state_update_phase_workflow_result_to_response()` is
  extended to include the third step's real `ToolResult.output`
  (the full, current project-state text) in its message, and to record
  a third `intelligence_trace` entry, whenever the third step actually
  ran.

## 9. Exact non-goals

- No change to `PROJECT_STATE_UPDATE_FOCUS`, `SCHEDULE_ENABLE`, or
  `SCHEDULE_DISABLE` — all three remain `TWO_STEP_WORKFLOW`.
- No change to the AI decision schema, `intelligence/structured_output.py`,
  the trusted planning instruction's capability count/wording, or
  `intelligence/grounding.py`. The model still selects exactly one
  `capability_id`; nothing about *that* contract changes.
- No new `CapabilityId`, no new user-facing command, no new tool.
- No data propagation from step 1 or step 2's `ToolResult.metadata`
  into step 3 — `PROJECT_STATE_SHOW` takes zero arguments, so none is
  needed. The post-execution propagation gap (Candidate C) remains
  fully deferred.
- No retries, no replanning, no rollback/compensation of any kind.
- No change to `workflow/engine.py` or `workflow/paused_workflow_store.py` —
  both already support N-step plans generically; this phase only
  proves it.
- No schedule creation, no memory save, no browser/Word/computer/phone
  control, no shell/Python execution, no dashboard change.

## 10. Security and approval design

- Step 1 (write) is the only step that can ever require approval —
  unchanged: still classified YELLOW, still pauses via the existing,
  unmodified `ApprovalManager`.
- Steps 2 (verify) and 3 (context) are both GREEN and execute
  immediately, back-to-back, the moment step 1's approval is granted
  and the write succeeds — exactly how step 2 already behaves today;
  this phase's only new fact is that a *second* consecutive GREEN step
  can immediately follow, with zero new approval-interaction code.
- If step 1 is declined or its approval expires, steps 2 and 3 never
  run — identical to today's exactly-one-approval contract.
- `_preflight_capability()` (already shared by every step) still
  enforces that `PROJECT_STATE_SHOW`'s live classification exactly
  matches its own catalog-declared `max_execution_tier` (GREEN) before
  it is ever added as step 3 — a live safety mismatch there fails the
  whole plan construction honestly (mirrors today's verifier preflight
  failure path), never silently downgrading or skipping step 3.

## 11. Persistence and restart design

- No change to `workflow/paused_workflow_store.py` or
  `WorkflowEngine`'s persistence code — both already serialize an
  arbitrary-length `plan_steps` list and `completed_outcomes` list.
- A workflow paused at step 1 (awaiting approval) persists exactly as
  today, just with a 3-step `plan_steps` list instead of 2.
- `reload_paused()`'s existing revalidation (tool still registered,
  waiting step still classifies YELLOW) is unaffected — it only ever
  inspects the *waiting* step (step 1), never later steps.
- Because `ProjectStateVerifyTool`/`ProjectStateShowTool` never fail,
  once step 1 resumes and succeeds, steps 2 and 3 always run to
  completion in the same `resume()` call — there is no new pause point
  introduced by step 3.

## 12. Verification design

- No change to `intelligence/verification.py`. `verify_project_state_field()`
  is called exactly as today, against step 2's real
  `ToolResult.metadata["phase"]` — step 3's result plays no role in the
  VERIFIED/FAILED/UNAVAILABLE determination.
- Step 3's own `ToolResult` is never treated as a verification signal —
  it is purely an additional, honest, real read appended to the
  response, shown regardless of whether step 2's verification matched.
  This is deliberate and will be documented plainly in the completion
  report and in code comments: showing the true current state is
  honest either way, including when it reveals a mismatch.

## 13. Failure and partial-completion behavior

- Step 1 fails/blocked/declined → workflow stops at step 1 (unchanged);
  steps 2 and 3 never attempted; response mirrors today's exact
  "update did not execute; no verification attempted" behavior.
- Step 1 succeeds, step 2 (verify) — cannot fail today (confirmed live,
  Section 2) but the response builder still defensively handles a
  `None`/unsuccessful step 2 outcome exactly as today, and in that case
  step 3 is checked defensively the same way: if absent, its content is
  simply omitted from the response, never fabricated.
- Step 1 and step 2 succeed, step 3 fails (currently believed
  impossible for `PROJECT_STATE_SHOW`, which also never fails, but
  handled defensively regardless): the response still reports the
  write and verification outcome accurately (this cannot regress), and
  simply omits the step-3 context content with an honest note that the
  final state could not be read, rather than fabricating it. No retry.
- STOP-only policy is preserved throughout — the engine itself already
  enforces this; no new stop/rollback logic is added.

## 14. Grounding requirements

None. `intelligence/grounding.py` continues to check exactly one
`_IntentSignature` for `PROJECT_STATE_UPDATE_PHASE`
(`action_tokens=("update",), domain_tokens=("phase",)`), unchanged —
grounding concerns only which single capability_id the model selected
and its declared arguments, never the internal step count of the
resulting workflow plan.

## 15. Backward-compatibility requirements

- Every existing `PROJECT_STATE_UPDATE_PHASE` test that exercises the
  *write* and *verify* steps' own contracts (approval, expiry, restart,
  duplicate-prevention, VERIFIED/FAILED/UNAVAILABLE outcomes) must
  continue to pass with updated step-count expectations only (2→3) —
  the write/verify semantics themselves do not change.
- `PROJECT_STATE_UPDATE_FOCUS`, `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`:
  zero test changes required; all three remain untouched
  `TWO_STEP_WORKFLOW` capabilities.
- `CapabilityId` and `ExecutionStrategy` are never persisted (confirmed
  in Phase 96's own audit, re-applicable here) — adding a new
  `ExecutionStrategy` member and a new optional `CapabilityAdapter`
  field breaks no persisted row.
- A `PROJECT_STATE_UPDATE_PHASE` workflow paused *before* this phase's
  deployment (2-step persisted plan) would, if ever reloaded after a
  code upgrade, still reconstruct and resume correctly — `reload_paused()`
  reconstructs a `Plan` purely from its own persisted `plan_steps`
  list, never from the live catalog's current step count.

## 16. Required production files likely affected

- `intelligence/capability_catalog.py` — new `ExecutionStrategy` member,
  new `CapabilityAdapter` field, `PROJECT_STATE_UPDATE_PHASE`'s entry
  updated.
- `intelligence/planning.py` — workflow builder extended to
  conditionally append step 3.
- `core/orchestrator.py` — shape-matcher and
  `_project_state_update_phase_workflow_result_to_response()` extended.
- `docs/user_guide.md`, `tools/builtin/help_tool.py` — updated wording
  for the phase-update command's richer response.

## 17. Required focused and regression tests

- `tests/unit/test_capability_catalog.py` — new strategy member, new
  field default, updated catalog-shape assertions.
- `tests/unit/test_intelligence_planning.py` — three-step plan
  construction, step-3 preflight failure handling, capability with no
  `paired_context_capability_id` unaffected.
- `tests/unit/test_orchestrator_update_phase_workflow.py` — updated for
  3 steps: durable restart with 3 persisted steps, duplicate-execution
  prevention, VERIFIED/FAILED/UNAVAILABLE outcomes with step 3 present,
  approval/decline/expiry evidence, GREEN-steps-run-without-approval
  evidence (steps 2 and 3 both execute in the same call once step 1 is
  approved).
- `tests/unit/test_workflow_engine.py` — a structural, catalog-agnostic
  test proving `WorkflowEngine` executes a 3-step plan with no engine
  change (regression only, no new engine behavior to test).
- Full regression: `test_orchestrator_schedule_enable_workflow.py`,
  `test_orchestrator_schedule_disable_workflow.py`, and the focus
  workflow's own test file must all pass **unmodified**.
- Full suite in all three required environments.

## 18. Stop conditions

Per this task's own instruction: stop after committing and reporting
this Phase 97 **planning gate**. No production code is changed in this
phase. Implementation begins only on a fresh, explicit user
instruction to implement Phase 97.
