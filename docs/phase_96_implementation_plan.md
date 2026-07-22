# Phase 96 — Next Safe Verified Write Milestone — Planning Gate

**Status:** planning gate only. No production or test code was changed by this document.
**Date:** 2026-07-22

---

## 1. Current Repository Baseline

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- HEAD at the start of this planning gate: `3991fd4` ("Close Phase 95 verified schedule disable expansion").
- Full suite: 5090 passed, 3 skipped, 0 failed, identical in the normal environment, `AI_REASONING_ENABLED=false`, and `PYTHON_DOTENV_DISABLED=1`.
- Phase 95 — Verified Schedule Disable Expansion is formally closed.

---

## 2. Existing Verified-Write Architecture

Twelve catalog entries exist today (10 model-selectable, 2 internal-only), including three paired `TWO_STEP_WORKFLOW` capabilities:

- **`PROJECT_STATE_UPDATE_FOCUS`** (one required `value: str`, YELLOW) paired with **`PROJECT_STATE_VERIFY_FOCUS`** (internal-only, GREEN, reads the singleton `ProjectStateStore` row, reports only `focus`/`last_updated`).
- **`SCHEDULE_ENABLE`** (one required `schedule_id: int`, YELLOW) and **`SCHEDULE_DISABLE`** (same shape, YELLOW) both paired with the *same*, reused **`SCHEDULE_VERIFY_ENABLED_STATE`** (internal-only, GREEN, reads `ScheduleStore.get(schedule_id)`, reports `enabled`).

The trusted workflow foundation (`intelligence/planning.py::_build_write_and_verify_workflow_plan()`, `core/orchestrator.py::_matching_two_step_write_capability()`/`_matches_two_step_workflow_shape()`/`_translate_verified_workflow_result()`) is fully catalog-driven for recognition: registering a new `TWO_STEP_WORKFLOW` capability requires zero orchestrator recognition-branch change. Two distinct, narrow mechanisms exist for threading data into a verify step's `tool_input`, and this planning gate's central finding concerns which one each candidate needs:

1. **`CapabilityAdapter.paired_verify_input_keys`** (Phase 94) — copies named keys from the write step's own **already-validated, pre-execution** `tool_input` into the verify step's `tool_input`, at **plan-construction time**, before anything executes. This is what `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE` use for `schedule_id` — safe because the target schedule's id is already known from the model's own request, before execution.
2. **`PlanStep.input_from_previous_step` + `workflow/engine.py::_PROPAGATED_FIELDS`** (Phase 15/29, pre-dating the Intelligence Core) — copies a named field from the write step's own **real, post-execution** `ToolResult.metadata` into the next step's `tool_input`, at **run time**, applied only by `WorkflowEngine._resolve_tool_input()`. Today this table contains exactly two entries (`("memory_id", "memory_id")`, `("matched_path", "source")`) and is used only by the five pre-existing fixed Phase 15 workflows (e.g. "remember this and show it back") — `_build_write_and_verify_workflow_plan()` never sets `input_from_previous_step=True` on any step it constructs, so **no Intelligence Core `TWO_STEP_WORKFLOW` capability today can target a record whose identity is only known after the write step actually runs.**

---

## 3. Files and Tests Inspected

Production: `intelligence/capability_catalog.py`, `intelligence/grounding.py`, `intelligence/planning.py`, `intelligence/verification.py`, `intelligence/structured_output.py`, `core/orchestrator.py`, `security/security_manager.py`, `approval/approval_manager.py`, `workflow/engine.py`, `workflow/paused_workflow_store.py`, `tools/executor.py`, `core/command_router.py`, `tools/builtin/schedule_create_tool.py`, `tools/builtin/schedule_enable_tool.py`, `tools/builtin/schedule_disable_tool.py`, `tools/builtin/schedule_list_tool.py`, `tools/builtin/schedule_verify_enabled_state_tool.py`, `scheduling/schedule_store.py`, `tools/builtin/memory_tool.py`, `memory/memory_manager.py`, `tools/builtin/project_state_update_tool.py`, `tools/builtin/project_state_verify_tool.py`, `tools/builtin/project_state_show_tool.py`, `project_state/project_state_store.py`, `main.py`.

Documentation: `docs/phase_94_implementation_plan.md`, `docs/phase_94_completion_report.md`, `docs/phase_95_implementation_plan.md`, `docs/phase_95_completion_report.md`.

Tests reviewed for existing/precedent behavior: `tests/unit/test_capability_catalog.py`, `tests/unit/test_trusted_workflow_foundation.py`, `tests/unit/test_verification.py`, `tests/unit/test_grounding.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_orchestrator_update_focus_workflow.py`, `tests/unit/test_orchestrator_schedule_enable_workflow.py`, `tests/unit/test_orchestrator_schedule_disable_workflow.py`, `tests/unit/test_workflow_engine.py`, `tests/unit/test_memory_tool.py`, `tests/unit/test_schedule_create_tool.py` (deterministic-side tests confirming `ScheduleCreateTool`'s real contract), `tests/unit/test_project_state_update_tool.py`, `tests/unit/test_command_router.py`.

No production or test file was modified during this inspection.

---

## 4. Candidate Inventory

1. **Candidate A — `SCHEDULE_CREATE`** (real deterministic tool exists: `ScheduleCreateTool`/`schedule_create`).
2. **Candidate B — explicit `MEMORY_SAVE`** (real deterministic operation exists: `MemoryTool`'s `"save"` operation, reachable via `remember this: <text>`).
3. **Candidate C — another `ProjectState` field update** (real deterministic tool exists and is already field-generic: `ProjectStateUpdateTool`, reachable via `update jarvis project state: <field>=<value>` for `branch`/`phase`/`commit`/`suite`/`focus`).
4. **Candidate D — existing schedule-update operation.** **Does not exist.** `tools/builtin/` contains exactly `schedule_create_tool.py`, `schedule_list_tool.py`, `schedule_enable_tool.py`, `schedule_disable_tool.py`, `schedule_verify_enabled_state_tool.py` — no update/rename/reschedule tool of any kind, and no such deterministic grammar exists in `core/command_router.py`. Per this plan's own instruction ("only evaluate this candidate if a real deterministic schedule-update operation exists"), Candidate D is **not evaluated further** — rejected outright as non-existent, not deferred.

---

## 5. Candidate A — Schedule Creation: Findings

1. **Exact tool/class**: `ScheduleCreateTool` (`tools/builtin/schedule_create_tool.py`), tool name `"schedule_create"`.
2. **Deterministic grammar**: `schedule web search summary for <query> at <HH:MM>[ as <name>]` (`core/command_router.py`'s `_SCHEDULE_CREATE_PREFIXES = ("schedule web search summary for",)`).
3. **`ToolExecutor` input schema**: `{"query": str, "time_of_day": str, "name": str | None}`.
4. **Required/optional fields**: `query` and `time_of_day` required; `name` optional.
5. **Timing representation**: a strict `"HH:MM"` 24-hour string, validated by `ScheduleStore.create()` via a fixed regex (`_TIME_OF_DAY_PATTERN`) — no recurrence concept exists (schedules are always daily).
6. **Command router timing parsing**: yes, the deterministic path already parses `<query> at <HH:MM>[ as <name>]` deterministically (`_extract_schedule_create_input()`), proving the *grammar* is parseable — but this is `core/command_router.py`'s own separate, pre-existing extraction logic, entirely distinct from the Intelligence Core's grounding/attribution mechanism (which has no multi-field, free-text-plus-time-plus-optional-name attribution precedent at all).
7. **Real `SecurityManager` action/tier**: `"schedule web search"` → `SecurityTier.YELLOW` (existing Phase 21 rule, re-verified live).
8. **Approval behavior**: YELLOW, approval-gated, identical shape to every other write tool.
9. **Durable record created**: a new `ScheduleEntry` row (auto-increment primary key `id`, `query`, `time_of_day`, `name`, `enabled=True`, `created_at`).
10. **Created-ID reliability**: **yes** — `ScheduleCreateTool.run()` already returns `metadata={"schedule_id": str(record.id)}` on success, so the real, exact new id is always available *after* execution.
11. **Duplicate-creation risk after restart/resume**: the *engine-level* duplicate-execution guard (`_paused_workflow_id_for()` finding no still-paused workflow on a second `execute_approved()` call) is structural and tool-agnostic, so it already prevents a second *resume* from re-running step 1. However, unlike `enable`/`disable`/`update_focus` (all idempotent mutations of an *existing* row), `schedule_create` is **not idempotent** — a hypothetical second real execution (e.g. from a bug elsewhere, or a future retry mechanism) would create a second, distinct row rather than harmlessly re-applying the same state. This is a materially different risk class from every verified write shipped so far.
12. **Exact record identification**: only via the real, post-execution id (finding 10) — `query`/`time_of_day`/`name` are **not unique** (`ScheduleStore.create()` enforces no uniqueness constraint of any kind; two schedules can share identical `query`+`time_of_day`+`name`).
13. **Can verification prove exact-exists / fields-match / exactly-one / not-duplicated?** **No, not with the architecture that exists today.** The verify step's `tool_input` is fixed at **plan-construction time**, before the write step ever runs (finding §2, mechanism 1) — there is no schedule id to thread into it yet, because the id does not exist until *after* `schedule_create` executes. The only mechanism that *could* supply the real post-execution id (`input_from_previous_step`/`_PROPAGATED_FIELDS`, mechanism 2) is wired only into the old Phase 15 fixed-workflow engine path, never into `_build_write_and_verify_workflow_plan()`/the `CapabilityAdapter` model. Without inventing this wiring (explicitly out of scope for a planning gate), the only fallback would be searching for a schedule by `query`/`time_of_day`/`name` — exactly the non-unique-search failure mode this plan's own instructions say must disqualify the candidate.
14. **Distinguishing success/wrong-fields/no-record/duplicate/execution-failure/verifier-failure**: not achievable exactly, for the same reason as (13) — a name/query/time search could match zero, one, or several rows, none of which certifies "the one I just created."
15. **Deterministic argument extraction**: `time_of_day` and `query` are extractable via the same kind of fixed-marker technique already proven (`" at "`/`" as "` boundaries, mirroring the deterministic command router's own parsing) — this part is *not* the blocker. The blocker is entirely verification identity (13)/(14).

**Conclusion: Candidate A fails the mandatory selection standard's "durable verification is exact" requirement, and the plan's own explicit disqualifier ("do not select schedule creation if verification depends only on searching by a non-unique name or description") applies directly.** No trusted creation receipt, created-record-id-propagation, or idempotency-key mechanism exists yet for the `TWO_STEP_WORKFLOW`/`CapabilityAdapter` path — and per this gate's own instruction, none was invented to force a selection.

---

## 6. Candidate B — Explicit Memory Save: Findings

1. **Exact tool/input schema**: `MemoryTool` (`tools/builtin/memory_tool.py`), operation-selector shape: `{"operation": "save", "content": str, "category": str | None}`.
2. **Required fields**: `content` (non-empty string); `category` optional (defaults to `"general"`).
3. **Current `SecurityManager` classification**: `"save memory"` → **`SecurityTier.GREEN`** (existing rule: "Saving a memory the user explicitly asked to store is safe.") — re-verified live.
4. **Approval requirement today**: **none** — a manual save is GREEN and runs immediately. This means a hypothetical `MEMORY_SAVE` `TWO_STEP_WORKFLOW` capability would be the **first-ever all-GREEN, no-approval, immediately-executed-and-verified** trusted workflow in this architecture — every one of the three shipped verified writes is YELLOW and pauses for approval before anything runs. Whether `WorkflowEngine.run()`/`_build_write_and_verify_workflow_plan()` correctly execute-then-verify a GREEN two-step plan in one synchronous call, with no pause and therefore no restart/duplicate-resume exposure at all, is untested territory (though likely low-risk, since GREEN steps already run immediately in every existing single-step and Phase 15 fixed-workflow path) - it would need its own dedicated test category, not merely reuse of the three existing YELLOW-workflow test suites.
5. **Duplicate-memory behavior**: **none** — `MemoryManager.save()` (confirmed by direct inspection) never deduplicates; every call creates a brand-new row unless the content is empty/whitespace or matches the "do not remember" rule. Saving identical content twice produces two distinct memory records with two distinct ids.
6. **Durable record-ID behavior**: `MemoryTool._run_save()` already returns `metadata={"operation": "save", "memory_id": str(record.id), "category": record.category}` — the real, exact new id is available after execution, exactly like `schedule_create`.
7. **Privacy implications**: memory content is arbitrary, potentially sensitive free text — any verifier reusing it must never re-expose more than what the user already saw echoed back in the save confirmation.
8. **Grounding signature feasibility**: plausible in principle (`action_tokens=("remember", "save"), domain_tokens=(...)`), but memory content is unbounded free text with no natural terminal marker the way a schedule id has (a trailing integer) or `PROJECT_STATE_UPDATE_FOCUS`'s value has (bounded by a fixed `" to "` marker convention already in use, though even that mechanism has never been asked to capture an entire free-form sentence intended to be stored verbatim, as opposed to a short value).
9. **Request-to-content attribution**: harder than any existing precedent — the *entire* remaining request text after some marker would need to become the stored content verbatim, and any ambiguity-refusal rule proven for short values (e.g. "at most one marker occurrence") has not been evaluated against long, punctuation-rich free text.
10. **Category attribution**: `category` is a small, real, bounded enum today (`memory/memory_models.py::KNOWN_CATEGORIES` — confirmed generally-known five categories, mirroring `KNOWN_PROJECT_STATE_FIELDS`'s own bounded-enum shape) - attribution of *this* argument alone would be tractable.
11. **Whether free text can be attributed safely with a fixed marker**: not established by any existing precedent in this codebase - genuinely new ground, not merely a reuse of `_extract_argument_span()`'s existing narrow discipline.
12. **Exact verifiability of the saved record**: **same blocking gap as Candidate A** — `MemoryTool`'s own `"get"` operation (already existing, already accepting `memory_id`) could serve as a verifier by construction, and `_PROPAGATED_FIELDS` already contains `("memory_id", "memory_id")` for exactly this tool (built for the *old* Phase 15 `"remember this and show it back"` fixed workflow) — but this propagation is, again, wired only into the pre-Intelligence-Core engine path, never into `_build_write_and_verify_workflow_plan()`. The verify step's `tool_input` would need the real, post-execution `memory_id`, which the current `CapabilityAdapter`/plan-construction-time architecture cannot supply.
13. **Distinguishing intended-content/duplicate-existing/newly-created/wrong-category/no-write/tool-failure**: not achievable exactly without the same missing post-execution-identity mechanism, compounded by memory's own genuine free-text attribution difficulty (8-11) that schedule enable/disable/focus-update never had to solve.
14. **Could a model silently add/summarize/alter content?** No — `_run_save()` stores `content` verbatim, and the existing structured-output validator already rejects unknown arguments; this specific risk is already well-controlled by existing mechanisms, independent of everything else.

**Conclusion: Candidate B fails the mandatory standard for the identical structural reason as Candidate A (no exact, ID-based verification path exists yet), and additionally introduces two new, unresolved difficulties Candidate A does not have: free-text content attribution, and an entirely untested GREEN/no-approval two-step-workflow execution shape.** Candidate B is materially riskier than Candidate A, not safer.

---

## 7. Candidate C — Another ProjectState Field Update: Findings

1. **Deterministic tool support**: **`ProjectStateUpdateTool` already supports all five fields generically** — `KNOWN_PROJECT_STATE_FIELDS = {"branch": "branch", "phase": "phase", "commit": "commit", "suite": "suite_result", "focus": "focus"}`. The Intelligence Core's `PROJECT_STATE_UPDATE_FOCUS` capability is a *narrowed wrapper* around this already-generic tool (via a fixed, non-model-supplied `field="focus"` literal merged into `tool_input` by `build_tool_input()`), not the tool's own limit.
2. **Exact input shape**: `{"field": <one of the five known field names>, "value": <non-empty str, verbatim>}`.
3. **Real `SecurityManager` classification**: `"update jarvis project state"` → `SecurityTier.YELLOW` (one single rule, already generic across all five fields — re-verified live; no new rule would be needed for any additional field).
4. **Manually maintained vs. live-detected**: **entirely manually maintained** — the tool "never inspects git, a subprocess, or the filesystem to determine a value itself" (confirmed directly in its own module docstring and `run()` body); this must be stated honestly in any user-facing documentation for a new field capability, exactly as it already is for `focus`.
5. **Request-to-value attribution**: the existing `" to "` marker (`_ARGUMENT_MARKER_BY_CAPABILITY[CapabilityId.PROJECT_STATE_UPDATE_FOCUS] = " to "`) is reusable verbatim for a second field-specific capability, safely, for the identical reason `" schedule "` was safely shared between `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE`: `ground_decision()` resolves a unique matching *signature* (disambiguated by `domain_tokens`, e.g. `"focus"` vs. `"phase"`) before extracting the value span.
6. **Can the current verifier be generalized narrowly?** **Yes, and this is the one real, bounded piece of new architecture Candidate C actually needs.** `ProjectStateVerifyTool.run()` today hardcodes `metadata={"focus": ..., "last_updated": ...}` — it does not read or report `branch`/`phase`/`commit`/`suite_result`. `intelligence/verification.py::verify_focus_update()` likewise hardcodes `metadata.get("focus")`. Both would need a small, narrow, already-precedented style of genericization: mirroring exactly how `verify_schedule_enabled_state()` was made generic over *which boolean* is expected (Phase 94) and *which verifier_id* to report (Phase 95's own correction), `verify_focus_update()` (or a newly-named, equally narrow sibling function) would need to compare an arbitrary *named* field's actual value against an expected value, and `ProjectStateVerifyTool` would need to report the requested field generically. This is **not a data-exposure concern**: `ProjectStateShowTool` (`project_state_show`, GREEN, already model-selectable today) already discloses the *entire* record — branch, phase, commit, suite_result, focus — so extending the internal verifier to report one additional named field exposes nothing an equally-privileged, already-shipped capability doesn't already show.
7. **Is the postcondition exact equality?** Yes — identical shape to `focus`: exact string equality between the approved `value` and the freshly-read-back stored field.
8. **Meaningful daily value?** Mixed. `phase`/`suite`/`commit` change frequently during exactly this kind of phase-cycle development work (this very session updates a "phase" concept every cycle); `branch` changes rarely. No field in this group has been observed actually being used via `ask jarvis to:` or the deterministic command during this session's own work — Nathan has not asked for AI-facing access to these fields before Phase 96's own review; this is a real, honestly-lower-certainty value case than the schedule enable/disable pair (which mirrored an existing, obviously-paired capability).
9. **Separate capabilities or one trusted enum?** Recommended: **separate capabilities, one per field**, mirroring the established `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE` precedent (two distinct capabilities sharing one reused verifier) rather than a single capability with a model-supplied `field` enum argument. This avoids ever asking the model to *select* which field to target (a new, non-precedented attribution problem - "which field word appears in the request" - the `field` value would instead remain a fixed, non-model-supplied literal per capability, exactly as `focus` already is), and keeps each capability's grounding signature simple (one new `domain_tokens` value per field, no new qualifier logic).
10. **Collision risk with `PROJECT_STATE_SHOW`/`PROJECT_STATE_UPDATE_FOCUS`**: none found — `PROJECT_STATE_SHOW` has `action_tokens=("show",)` (no `"update"`); `PROJECT_STATE_UPDATE_FOCUS` has `domain_tokens=("focus",)` exclusively. A new field capability's own `domain_tokens` (e.g. `("phase",)`) does not overlap with `"focus"` or any of the other nine existing signatures' domain tokens.

**Conclusion: Candidate C satisfies every item in the mandatory selection standard.** It requires no post-execution-identity mechanism at all (the verified record is always the one, already-existing, singleton `ProjectState` row — there is no "which row" ambiguity, no duplicate-row risk, and no missing-record case to detect, since the row already exists before any update). The one real piece of new work — narrowly generalizing the existing verifier tool/function to report/compare a second named field — is small, bounded, and directly precedented by Phase 94/95's own generalization of `verify_schedule_enabled_state()`.

---

## 8. Security and Approval Assessment (all three candidates)

| Candidate | Real action | Real tier | New SecurityManager work needed |
|---|---|---|---|
| A: `SCHEDULE_CREATE` | `"schedule web search"` | YELLOW | None |
| B: `MEMORY_SAVE` | `"save memory"` | **GREEN** | None, but a GREEN two-step workflow is unprecedented |
| C: field update (e.g. `phase`) | `"update jarvis project state"` | YELLOW | None |

No candidate requires a new `SecurityManager` rule, a tier change, or any reordering of existing rules.

---

## 9. Grounding and Argument-Attribution Assessment

- **A (`SCHEDULE_CREATE`)**: `time_of_day`/`query`/optional `name` are extractable via fixed markers mirroring the deterministic command's own grammar, but this is a **three-field** attribution problem (two required, one optional) with no existing multi-argument precedent in the Intelligence Core (every shipped capability has at most one AI-facing argument) — meaningfully harder than any candidate shipped so far, independent of the verification blocker.
- **B (`MEMORY_SAVE`)**: `category` attribution is tractable (small bounded enum); `content` attribution is **not** established by any existing precedent (unbounded free text, no natural terminal marker for "store this verbatim").
- **C (field update)**: identical, already-proven single-value attribution (`" to "` marker) as `PROJECT_STATE_UPDATE_FOCUS` — no new attribution mechanism needed at all.

---

## 10. Identity and Duplicate-Risk Assessment

- **A**: new row, non-idempotent creation, no unique non-id field, identity depends entirely on a not-yet-wired post-execution-id-propagation mechanism. **High identity risk.**
- **B**: new row, non-idempotent creation (no deduplication), identical missing-propagation gap as A, plus content is not a suitable secondary identity key (memory content may legitimately repeat). **High identity risk.**
- **C**: existing singleton row, idempotent update (writing the same value twice is harmless and always verifiable), no id concept needed at all. **No identity risk.**

---

## 11. Verification Assessment

- **A**: cannot be made exact without inventing new architecture during this planning gate (explicitly disallowed). **Fails.**
- **B**: cannot be made exact for the same reason, plus a GREEN/no-approval two-step shape is untested. **Fails.**
- **C**: exact string-equality verification, identical postcondition shape already proven for `focus`. **Passes.**

---

## 12. Candidate Comparison Table

| | `SCHEDULE_CREATE` | `MEMORY_SAVE` | ProjectState field (e.g. `phase`) | Schedule update |
|---|---|---|---|---|
| Value | Moderate-high | High | Mixed/uncertain | N/A |
| Risk | High (non-idempotent, no identity) | High (non-idempotent, no identity, free-text, untested GREEN workflow) | Low | N/A |
| Arguments | 3 (2 required + 1 optional) | 2 (content + category) | 1 (value; field is fixed per capability) | N/A |
| Attribution difficulty | Moderate (multi-field) | Hard (unbounded free text) | Trivial (identical to `focus`) | N/A |
| Identity certainty | Low (id only known post-execution) | Low (id only known post-execution) | Total (singleton row) | N/A |
| Duplicate risk | Real (non-idempotent) | Real (no dedup) | None (idempotent) | N/A |
| Verification strength | Cannot be made exact today | Cannot be made exact today | Exact, proven shape | N/A |
| Architecture required | Post-execution identity propagation for `TWO_STEP_WORKFLOW` (new) | Same, plus free-text attribution, plus GREEN-workflow proof (new) | Narrow verifier/verification-function field-genericization (small, precedented) | N/A |
| Recommendation | **Defer — requires a foundation first** | **Defer — requires a foundation first, and is riskier than A** | **Select now** | **Rejected — does not exist** |

---

## 13. Selected Outcome

### Outcome A — Select one verified write capability

**Exact Phase 96 name**: Phase 96 — Verified Project-State Phase Field Update.

**Exact capability**: `PROJECT_STATE_UPDATE_PHASE` (new `CapabilityId`/`CAPABILITY_CATALOG` entry), reusing the existing, real `project_state_update` tool with a fixed, non-model-supplied literal `field="phase"` (mirroring exactly how `PROJECT_STATE_UPDATE_FOCUS` already fixes `field="focus"`).

**Exact catalogue schema**:
```python
CapabilityId.PROJECT_STATE_UPDATE_PHASE: CapabilityAdapter(
    capability_id=CapabilityId.PROJECT_STATE_UPDATE_PHASE,
    tool_name="project_state_update",
    description=(
        "Updates the manually-maintained Jarvis project state's phase "
        "field. Requires your explicit approval, and the stored value "
        "is checked with a structured read-back after it runs."
    ),
    arguments=(CapabilityArgumentSpec(name="value", type_name="str", required=True),),
    allowed_strategy=ExecutionStrategy.TWO_STEP_WORKFLOW,
    max_execution_tier=SecurityTier.YELLOW,
    verification_strategy_id="project_state_phase_exact_match",
    internal_only=False,
    paired_verify_capability_id=CapabilityId.PROJECT_STATE_VERIFY_FOCUS,  # reused, see §14
),
```
`field="phase"` is supplied the same way `field="focus"` already is today: as a fixed, non-model-controlled literal merged into `tool_input` by the existing `build_tool_input()`/fixed-arguments mechanism (`_FIXED_ARGUMENTS_BY_CAPABILITY`-equivalent) - never a model-facing argument.

**Exact grounding signature**:
```python
CapabilityId.PROJECT_STATE_UPDATE_PHASE: _IntentSignature(
    action_tokens=("update",),
    domain_tokens=("phase",),
),
```

**Exact argument extraction**: reuse the existing `" to "` marker (`_ARGUMENT_MARKER_BY_CAPABILITY[CapabilityId.PROJECT_STATE_UPDATE_PHASE] = " to "`), identical mechanism `PROJECT_STATE_UPDATE_FOCUS` already uses - safe because signature-level `domain_tokens` disambiguation (`"focus"` vs. `"phase"`) happens before value extraction.

**Exact SecurityManager tier**: `"update jarvis project state"` → `YELLOW`, the existing, unmodified rule - no new rule.

**Exact approval flow**: identical to `PROJECT_STATE_UPDATE_FOCUS`'s own - approval → durable paused workflow → restart-safe resume → one `project_state_update` execution → one read-back verification → grounded response.

**Exact execution input**: `{"field": "phase", "value": <approved str>}` - identical shape, just a different fixed field literal.

**Exact verifier arrangement**: reuse the **same internal capability**, `PROJECT_STATE_VERIFY_FOCUS`/`ProjectStateVerifyTool` (never a new verifier capability), narrowly genericized to also report `phase` in its `metadata`, and a small, narrow genericization of `verify_focus_update()` (or an equally narrow, explicitly-parameterized sibling, mirroring Phase 95's own `verifier_id`-parameter fix) to compare an arbitrary named field instead of only `"focus"`. §14 details exactly which small change this requires.

**Exact durable postcondition**: `ProjectStateStore.get().phase == <approved value>` (exact string equality, identical shape to `focus`).

**Expected phase size**: **small — one implementation-and-closure batch**, mirroring Phase 95's own sizing exactly: no new tool, no new verifier tool/capability, no new `SecurityManager` rule, and the one required architecture change (verifier genericization) is narrow and already precedented.

**Batch breakdown**: single batch — catalog entry, grounding signature, marker reuse, verifier/verification-function genericization (proven not to change `focus`'s own behavior), full test coverage, documentation, complete regression, Ruff, completion report, closure.

**Acceptance criteria**: see §17. **Stop conditions**: see §19.

---

## 14. Exact Scope

Add exactly:
- One new user-facing capability: `PROJECT_STATE_UPDATE_PHASE` (catalog entry + `CapabilityId` member).
- One new grounding signature.
- One new string-marker entry (`" to "`, reused).
- One new `verification_strategy_id` string, cross-referenced in `intelligence/verification.py`.
- A narrow genericization of `ProjectStateVerifyTool.run()` to report the requested field (not just `focus`) - the *simplest* correct approach is for the verifier to keep reading the one singleton row and report **both** `focus` and `phase` (and, if a future field capability is ever added, that field too) in its `metadata`, exactly mirroring how the tool already reports two fields (`focus`, `last_updated`) today; this requires no new argument to the verifier itself, since it takes no input and always reads the one existing row.
- A narrow genericization of the comparison function in `intelligence/verification.py` (either a second explicit function, `verify_phase_update()`, mirroring `verify_focus_update()`'s exact shape with `metadata.get("phase")`, **or** one shared function parameterized by field name - the plan defers this specific implementation choice to the batch itself, since both are small and equally safe; the batch must not invent a third, generic "verify any field" framework).
- One new `_TRUSTED_PLANNING_INSTRUCTION` example (an eleventh model-selectable capability).
- Documentation: `docs/user_guide.md`, `tools/builtin/help_tool.py`.
- Full test coverage mirroring `PROJECT_STATE_UPDATE_FOCUS`'s own established test categories.

**No new tool, no new verifier tool/capability, no new `SecurityManager` rule, and no new `main.py` registration are required** — `ProjectStateUpdateTool`/`ProjectStateVerifyTool` already exist and are already registered, sharing the same `ProjectStateStore`.

---

## 15. Exact Non-Goals

Do not add: `SCHEDULE_CREATE`, `MEMORY_SAVE`, schedule update/delete, another field's capability beyond `phase` in this same phase, a model-selectable `field` argument, a generic "update any field" capability, a generic boolean/string verifier framework, a broad verifier registry, new `SecurityManager` rules, tier changes, arbitrary workflow step lists, retries, replanning, rollback, compensation, autonomous agents, automatic memory writes, conversation persistence, file operations, dashboard work, voice, phone control, browser control, computer control, or source-code self-modification. Do not invent post-execution identity propagation for `TWO_STEP_WORKFLOW` capabilities in this phase - that remains the correctly-scoped foundation for a future `SCHEDULE_CREATE`/`MEMORY_SAVE` phase, not something to build speculatively now.

---

## 16. Proposed Architecture

No new architectural mechanism is required beyond the narrow verifier/verification-function genericization named in §14. The trusted `TWO_STEP_WORKFLOW` foundation, the catalog-driven orchestrator recognizer, `paired_verify_input_keys` (unused here, exactly as it is already unused/empty for `PROJECT_STATE_UPDATE_FOCUS`), approval/persistence/resume machinery, and `ToolExecutor` are all reused completely unchanged.

---

## 17. Test Strategy / Acceptance Criteria

Tests required, mirroring `PROJECT_STATE_UPDATE_FOCUS`'s own established categories exactly:

1. Catalogue schema (new adapter fields, twelve total capabilities → thirteen, eleven model-selectable).
2. Wrong-type and extra-argument rejection for `value`.
3. Grounding uniqueness (no collision with `PROJECT_STATE_UPDATE_FOCUS`'s `"focus"` domain token or any of the other nine signatures).
4. Exact argument attribution (`" to "` marker, reused).
5. Negation and ambiguity refusal (mirroring `PROJECT_STATE_UPDATE_FOCUS`'s own negation/ambiguity tests).
6. Real `SecurityManager` classification (`"update jarvis project state"` → YELLOW, unchanged).
7. No execution before approval.
8. Decline/cancel-synonym behavior (mirroring Phase 94 Batch 3/Phase 95's own honest cancel-is-decline test).
9. Expiry (real `_FakeClock`/`timeout_seconds` pattern).
10. Restart-safe resume.
11. Immutable approved `value` between approval and execution.
12. Duplicate-execution prevention.
13. Exact `ToolExecutor` input (`{"field": "phase", "value": <approved>}`).
14. Durable write (`ProjectStateStore.get().phase` actually changes).
15. Exact verification success.
16. Verification mismatch (a test-double verifier reporting a different `phase` value than approved).
17. Missing state/record: N/A in the same sense as `focus` (`ProjectState` is always a real singleton row once any field has ever been set; an honest empty-string/`"not recorded yet"` case mirrors `focus`'s own never-yet-set behavior, not a "missing record" case).
18. Duplicate state/record: N/A (singleton row, not applicable).
19. Execution failure (e.g. empty value rejected by the tool itself).
20. Verifier failure (test-double verifier tool failing outright).
21. No retry or correction anywhere in the above.
22. `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE` complete regression (all pre-existing tests pass unmodified).
23. `PROJECT_STATE_UPDATE_FOCUS` complete regression (all pre-existing tests pass unmodified, including proving the verifier genericization changes zero observable behavior for `focus`).
24. All ten pre-existing user-facing capabilities unchanged.
25. Advisory (`ask jarvis:`) and deterministic (`update jarvis project state: phase=<value>`) paths unchanged.
26. Full suite in all three required environments.
27. Ruff on the exact Git-derived Phase 96 changed-Python-file set, plus `git diff --check`.

A coexistence test proving all three (soon four) `TWO_STEP_WORKFLOW` capabilities dispatch correctly through one shared orchestrator instance without ambiguity, and that the genericized verifier serves both `focus` and `phase` requests safely without cross-talk, is also required, extending Phase 95's own three-workflow coexistence test.

---

## 18. Risks and Mitigations

- **Risk**: genericizing `verify_focus_update()`/`ProjectStateVerifyTool` accidentally changes `focus`'s own observable behavior. **Mitigation**: the complete, unmodified `test_orchestrator_update_focus_workflow.py` suite must pass bit-for-bit unchanged; this is the primary acceptance gate for the genericization.
- **Risk**: scope creep toward a model-selectable `field` argument or a generic multi-field capability. **Mitigation**: §15's explicit non-goal list; `field` remains a fixed, per-capability literal, never model-supplied, exactly as `focus` already is.
- **Risk**: low real-world daily value if Nathan does not actually use phase-tracking via AI. **Mitigation**: honestly disclosed in §7 item 8 above; this is the plan's own weakest point, and the batch's completion report should invite Nathan to confirm actual usefulness before any further field capability is considered.

---

## 19. Stop Conditions

Implementation must stop and report, never improvise past, if:

- `ProjectStateUpdateTool`/`ProjectStateStore` no longer match the exact contract documented in §7.
- Genericizing the verifier or verification function changes `PROJECT_STATE_UPDATE_FOCUS`'s own observable behavior in any way.
- A grounding collision is found between the new signature and any of the ten existing signatures.
- The orchestrator's catalog-driven recognition cannot correctly distinguish the new workflow's shape from the other three.
- A persistence migration is required.
- Retries, replanning, or probabilistic/general-NLU behavior become necessary.

---

## 20. Manual Anthropic Limitation

Live Anthropic manual acceptance testing remains **postponed** because the configured API account lacks sufficient credits. This is an **external account limitation, not a Jarvis production-code failure** - no production behavior is proposed to bypass it. All Phase 96 work (if implemented) will remain verifiable with deterministic and fake-provider tests, the same way every prior phase has been verified.
