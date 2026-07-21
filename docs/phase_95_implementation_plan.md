# Phase 95 — Verified Schedule Disable Expansion — Planning Gate

**Status:** planning gate only. No production or test code was changed by this document.
**Date:** 2026-07-21

---

## 1. Current Baseline

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- HEAD at the start of this planning gate: `0c14857` ("Close Phase 94 verified schedule enable expansion").
- Full suite: 4985 passed, 3 skipped, 0 failed, identical in the normal environment, `AI_REASONING_ENABLED=false`, and `PYTHON_DOTENV_DISABLED=1`.
- Phase 94 — Safe Verified Write Expansion is formally closed. Its authoritative final closure commit is `0c14857`; the earlier `ba2a085` documentation-only closure remains in history but was superseded by `0c14857`'s corrected architecture (verifier action-string honesty, catalog-driven orchestrator dispatch, explicit expiry evidence, honestly-documented absence of a distinct cancellation mechanism).

---

## 2. Phase 94 Architecture Inherited

Eleven catalog entries exist today (nine model-selectable, two internal-only), including two paired `TWO_STEP_WORKFLOW` capabilities:

- **`PROJECT_STATE_UPDATE_FOCUS`** (`TWO_STEP_WORKFLOW`, YELLOW) paired with **`PROJECT_STATE_VERIFY_FOCUS`** (internal-only, GREEN).
- **`SCHEDULE_ENABLE`** (`TWO_STEP_WORKFLOW`, YELLOW, one required `schedule_id: int`) paired with **`SCHEDULE_VERIFY_ENABLED_STATE`** (internal-only, GREEN).

The trusted verified-workflow foundation (`intelligence/planning.py::_build_write_and_verify_workflow_plan()`, `core/orchestrator.py::_matching_two_step_write_capability()`/`_matches_two_step_workflow_shape()`/`_translate_verified_workflow_result()`) supports exactly: **approval → one write → one deterministic read-only verification → grounded response**, entirely driven by trusted, static `CAPABILITY_CATALOG` data (`paired_verify_capability_id`, `paired_verify_input_keys`). Recognition of which `TWO_STEP_WORKFLOW` capability a `WorkflowResult` belongs to is a catalog iteration, not a per-capability `if`/`elif` chain (Phase 94, Batch 3's corrected final architecture). Only the final response-*formatting* step is a small, static, per-capability lookup (`response_builders` dict inside `_translate_verified_workflow_result()`), because each capability's grounded response wording genuinely differs.

---

## 3. Live Schedule-Disable Findings

Direct inspection of the current repository (not the Phase 94 design documents alone) confirms:

1. **`ScheduleDisableTool` already exists and is already registered** in `main.py` (line 261: `registry.register_tool(ScheduleDisableTool(schedule_store))`) - a real Phase 21 tool, unrelated to Phase 94, requiring **zero new registration wiring**.
2. It targets exactly one durable `schedule_id`, identical in shape to `ScheduleEnableTool`.
3. **Exact `ToolExecutor` input contract**: `{"schedule_id": <int>}` - `ScheduleDisableTool.run()`'s only recognised input key is `schedule_id`, parsed by the identical `_parse_id()` static method `ScheduleEnableTool` already uses (explicit `bool` rejection, `int` passthrough, numeric-string acceptance).
4. **Real `action_for()` string**: `"disable schedule"` (`tools/builtin/schedule_disable_tool.py:68`), unchanged since Phase 21.
5. **Real `SecurityManager` classification**: `SecurityTier.YELLOW`, via the pre-existing, unmodified rule `_Rule("disable schedule", SecurityTier.YELLOW, "Disabling a scheduled action changes state and should be confirmed.")` (`security/security_manager.py:224`). Re-verified live: `SecurityManager().classify_action("disable schedule").tier -> SecurityTier.YELLOW`.
6. **Behavior**:
   - *Enabled schedule*: `ScheduleStore.disable(schedule_id)` sets `entry.enabled = False` and returns the updated record - succeeds unconditionally.
   - *Already-disabled schedule*: identical code path - `disable()` has no conditional check on the current state, so re-disabling an already-disabled schedule succeeds normally and reports the same success text, exactly mirroring `ScheduleEnableTool`'s own already-enabled behavior.
   - *Missing schedule*: `ScheduleStore.disable()` returns `None` when `db.get(ScheduleEntry, schedule_id)` finds nothing; `ScheduleDisableTool.run()` returns `self.fail(f"No schedule found with id {schedule_id}.")` - an honest failure, never a crash or a silent no-op treated as success.
   - *Store failure*: no code path in `ScheduleStore.disable()` raises for a well-formed integer id against a reachable database; `session_scope()` handles the transaction boundary identically to every other write in this store. No new failure mode exists beyond "missing schedule."
7. **Mutates only the `enabled` state**: confirmed by direct inspection of `ScheduleStore.disable()` (`scheduling/schedule_store.py:215-233`) - it touches exactly one field (`entry.enabled = False`) and calls `db.flush()`; `query`, `time_of_day`, `name`, and `last_run_at` are never touched.
8. **The same `ScheduleStore.get(schedule_id)` can verify the result**: yes, trivially. `ScheduleVerifyEnabledStateTool.run()` (already built in Phase 94, Batch 2) calls `self._schedules.get(schedule_id)` and reports `metadata={"schedule_id": record.id, "enabled": record.enabled}` - this is **already fully agnostic to which boolean value is expected**. No change to the verifier tool is required for a `False` postcondition; it already reports whatever the real, current `enabled` value is.
9. **Schedule IDs remain visible through `schedule-list` output**: yes, unchanged - `list schedules`/`show schedules` (`ScheduleListTool`, GREEN, untouched by Phase 94) is the only source of schedule ids, exactly as it already is for `SCHEDULE_ENABLE`.
10. **Disable is reversible through the existing enable capability**: yes - `SCHEDULE_ENABLE` (Phase 94) already exists as the exact inverse operation, reachable both deterministically (`enable schedule <id>`) and through the Intelligence Core.

**Conclusion: all ten viability items are confirmed safe. No stop condition is triggered.**

---

## 4. Security Classification (re-verified live)

```
SecurityManager().classify_action("disable schedule").tier -> SecurityTier.YELLOW
SecurityManager().classify_action("show schedule enabled state").tier -> SecurityTier.GREEN
```

Both via existing, unmodified rules. No new `SecurityManager` rule or tier is required anywhere in this plan.

---

## 5. Tool Input Contract

`ScheduleDisableTool` accepts exactly `{"schedule_id": <int>}`, identical in shape to `ScheduleEnableTool`. No `operation`, `expected_state`, or any other key is read, accepted, or required.

---

## 6. Existing Deterministic Behavior (unaffected, confirmed unchanged)

`core/command_router.py` already defines `_SCHEDULE_DISABLE_PREFIXES: tuple[str, ...] = ("disable schedule",)` (Phase 21) and dispatches `disable schedule <id>` to `ScheduleDisableTool` via the existing `_extract_memory_id(text, "disable schedule")` argument extraction - entirely separate machinery from the Intelligence Core's grounding/attribution path, and not modified by this plan. `core/command_router.py` is not in this plan's file-change list.

---

## 7. Verifier Options Assessed

### Option A — Reuse the existing internal verifier tool/capability (SELECTED)

`SCHEDULE_VERIFY_ENABLED_STATE`'s real tool (`ScheduleVerifyEnabledStateTool`) and real `intelligence/verification.py` function (`verify_schedule_enabled_state(*, expected_enabled: bool, verify_tool_result)`) are **already fully parameterized by `expected_enabled: bool`** - direct inspection confirms the only hardcoded `True` literal in the entire Phase 94 codebase lives at exactly one call site: `core/orchestrator.py:2311`, inside `_schedule_enable_workflow_result_to_response()`. The verifier tool and verification function themselves contain no capability-specific assumption about which boolean is expected. This means:
- expected state remains entirely trusted - a fixed Python literal (`True` for enable, `False` for disable) supplied only at each capability's own orchestrator response-builder call site, never read from model output;
- the model cannot supply or override it - `SCHEDULE_VERIFY_ENABLED_STATE` has zero AI-facing arguments and no grounding signature;
- `SCHEDULE_ENABLE` continues to call `verify_schedule_enabled_state(expected_enabled=True, ...)`, completely unchanged;
- `SCHEDULE_DISABLE` would call the identical function with `expected_enabled=False`, in its own new, separate response-builder method;
- zero changes to `tools/builtin/schedule_verify_enabled_state_tool.py` or `intelligence/verification.py` are required;
- no ambiguous runtime inference is introduced - the boolean is a compile-time-fixed literal per call site, never inferred from context.

**This is the smallest possible design**: reusing one already-generic tool and one already-generic verification function, adding only a second orchestrator-level call site with the literal flipped.

### Option B — Add a separate verification strategy ID (SELECTED, alongside Option A)

`CapabilityAdapter.verification_strategy_id` is confirmed, by direct inspection, to be **purely static, descriptive metadata** - it is defined on the catalog entry and cross-referenced by a matching constant in `intelligence/verification.py` (e.g. `SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID = "schedule_enabled_exact_match"`), but it is **never read, dispatched on, or consumed by any runtime code path** (confirmed: no match for `verification_strategy_id` outside `intelligence/capability_catalog.py`'s own field definition and `intelligence/verification.py`'s own constant declaration). Adding a second, distinct string - `"schedule_disabled_exact_match"` - costs nothing behaviorally and preserves the established one-label-per-real-postcondition convention, avoiding a shared, ambiguous label that would claim two different real postconditions ("enabled" vs "disabled") under one name.

### Option C — Add a separate internal verifier capability (REJECTED)

Not needed. The verify step's real tool (`schedule_verify_enabled_state`) is identical regardless of which boolean is expected - `ScheduleDisableTool`'s workflow would pair with the exact same `SCHEDULE_VERIFY_ENABLED_STATE` catalog entry `SCHEDULE_ENABLE` already uses (`paired_verify_capability_id=CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE`, reused verbatim). Duplicating the internal verifier capability merely to give it a differently-named twin would violate the anti-overgeneralization requirement (no duplicate read-only tool merely for naming convenience) with zero safety benefit - the write-tool-name half of the two-step shape check (`steps[0].tool_name`) already disambiguates `SCHEDULE_ENABLE`'s workflow (`schedule_enable` + `schedule_verify_enabled_state`) from `SCHEDULE_DISABLE`'s workflow (`schedule_disable` + `schedule_verify_enabled_state`) unambiguously, even though both share the same verify-tool name.

---

## 8. Selected Verifier Arrangement

- Reuse `SCHEDULE_VERIFY_ENABLED_STATE` (`ScheduleVerifyEnabledStateTool`, unmodified) as `SCHEDULE_DISABLE`'s `paired_verify_capability_id`.
- Reuse `verify_schedule_enabled_state()` (unmodified) as the verification function, called with `expected_enabled=False`.
- Add one new, distinct `verification_strategy_id`: `"schedule_disabled_exact_match"`.
- Add one new, small orchestrator response-builder method (`_schedule_disable_workflow_result_to_response()`), mirroring `_schedule_enable_workflow_result_to_response()`'s exact shape with `expected_enabled=False` and disable-specific wording, registered in the existing `response_builders` dict inside `_translate_verified_workflow_result()` - a one-entry data addition, never a new `if`/`elif` branch.

---

## 9. Grounding and ID Attribution

**Signature (new, additive only):**
```python
CapabilityId.SCHEDULE_DISABLE: _IntentSignature(
    action_tokens=("disable",),
    domain_tokens=("schedule", "schedules"),
),
```
No qualifier token is needed - direct inspection of every one of the nine existing signatures confirms no other signature's `action_tokens` contains `"disable"`, so no collision requires a third dimension (mirroring `SCHEDULE_ENABLE`'s own reasoning for omitting a qualifier).

**Numeric attribution (reuses the existing marker):**
```python
_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY = {
    CapabilityId.SCHEDULE_ENABLE: " schedule ",
    CapabilityId.SCHEDULE_DISABLE: " schedule ",  # new
}
```
Both capabilities safely share the identical `" schedule "` marker text: `ground_decision()` first resolves a unique matching capability *signature* (disambiguated by `action_tokens` - "enable" vs "disable" - before numeric extraction ever runs), and only then extracts the argument using that one matched capability's own marker. There is no ambiguity between "enable schedule 5" and "disable schedule 5", exactly as documented by `core/command_router.py`'s own existing comment that no `_SCHEDULE_*_PREFIXES` phrase can be confused with another.

**Accepted request form**: `"ask jarvis to: disable schedule <id>"` (mirroring `_SCHEDULE_DISABLE_PREFIXES = ("disable schedule",)`'s own real deterministic grammar).

**Collision analysis** (re-verified live against all nine existing signatures):
- `SCHEDULE_ENABLE` (`action_tokens=("enable",)`) - distinct action token, no collision.
- `SCHEDULE_LIST` (`action_tokens=("show", "list")`, `domain_tokens=("schedule", "schedules")`) - distinct action token, no collision.
- All seven other signatures use unrelated domain tokens (`focus`, `health`, `memory`/`memories`, `approval`/`approvals`, `workflow`/`workflows`) - no collision.
- The internal verifier (`SCHEDULE_VERIFY_ENABLED_STATE`) has no signature and is never evaluated by grounding.

**No fuzzy matching, no schedule names, no list positions, no assembled context, no number words, no semantic similarity, and no second AI call are used anywhere in this mechanism** - identical, unmodified discipline to `SCHEDULE_ENABLE`'s own attribution rule.

---

## 10. Approval and Persistence Flow

`SCHEDULE_DISABLE` reuses the existing workflow lifecycle unchanged, byte-for-byte identical to `SCHEDULE_ENABLE`'s own:

```
request
→ strict structured decision (existing, unmodified _validate_arguments())
→ grounding and ID attribution (new signature + reused numeric marker)
→ YELLOW preflight (existing, unmodified SecurityManager rule)
→ one approval (existing, unmodified ApprovalManager)
→ durable paused workflow (existing, unmodified PausedWorkflowStore)
→ approved resume (existing, unmodified WorkflowEngine.resume())
→ one schedule-disable execution (existing, unmodified ScheduleDisableTool)
→ one read-only verification (existing, unmodified ScheduleVerifyEnabledStateTool, expected_enabled=False)
→ grounded response (new response-builder, mirroring the enable path)
```

- **No execution before approval**: guaranteed by the existing, unmodified `WorkflowEngine.run()`/`ApprovalManager` pairing - no new code path bypasses it.
- **Decline/cancel-synonym behavior**: identical to `SCHEDULE_ENABLE` - `ui/approval_prompt.py`'s `_DECLINE_INPUTS` (`{"n", "no", "decline", "cancel"}`) resolves "cancel" to the identical `ApprovalManager.decline()` call. This repository has **no distinct cancellation lifecycle**, confirmed again during this planning gate; Phase 95 will document this honestly rather than inventing one, exactly as Phase 94's own closure did.
- **Expiry**: identical, unmodified `ApprovalManager._sweep_expired()`/`_expire()` mechanism, tied to `timeout_seconds` - genuinely distinct from decline, real and already proven end-to-end for `SCHEDULE_ENABLE` in Phase 94; the same `_FakeClock` pattern will prove it for `SCHEDULE_DISABLE`.
- **Restart-safe resume**: identical, unmodified `PausedWorkflowStore`/`ApprovalManager.reload_pending()`/`WorkflowEngine.reload_paused()` mechanism - no `SCHEDULE_DISABLE`-specific persistence code is needed, since the paused-plan row already stores `tool_name`/`tool_input` generically.
- **Immutable approved schedule ID**: guaranteed by the same mechanism `SCHEDULE_ENABLE` already relies on - the approved `Plan`/`PlanStep.tool_input` is durable and never re-derived from a fresh model call at resume time.
- **Duplicate-execution prevention**: identical, unmodified `_paused_workflow_id_for()` behavior - a second `execute_approved()` call finds no still-paused workflow and falls through honestly.
- **No verification after failed execution / no retry after mismatch / no stale approval reuse**: all guaranteed by the same, unmodified `_build_write_and_verify_workflow_plan()`/`WorkflowEngine` machinery already proven for `SCHEDULE_ENABLE`.

---

## 11. Failure-State Behavior (planned)

- **Enabled schedule**: remains enabled before approval; becomes disabled after approved execution; `verify_schedule_enabled_state(expected_enabled=False, ...)` succeeds (`VERIFIED`).
- **Already-disabled schedule**: `ScheduleDisableTool`'s real, unmodified behavior succeeds unconditionally (no special-cased failure, mirroring `SCHEDULE_ENABLE`'s own already-enabled behavior); the `False` postcondition still verifies honestly as `VERIFIED`.
- **Missing schedule at execution**: `ScheduleDisableTool.run()` returns an honest failure (`"No schedule found with id {id}."`); the workflow's own existing "write did not execute" branch means verification never runs.
- **Schedule disappears before verification**: the verifier reports a genuine missing-target failure (`UNAVAILABLE`), never recreated or retried - identical mechanism already proven for `SCHEDULE_ENABLE`.
- **Verification mismatch** (durable `enabled=True` despite a reported disable success): `verify_schedule_enabled_state(expected_enabled=False, ...)` returns `FAILED` when `actual is True`; the tool's own success text can never override this; no automatic second disable ever occurs.
- **Verifier failure**: reported as `UNAVAILABLE`, distinct from a genuine mismatch; no correction or retry occurs.

---

## 12. Candidate Comparison

| Candidate | Daily usefulness | Risk | Grounding difficulty | Argument-attribution difficulty | Verification strength | Selected now? |
|---|---|---|---|---|---|---|
| **`SCHEDULE_DISABLE`** | Moderate - the natural, expected inverse of the already-shipped `SCHEDULE_ENABLE`; completes a pair Nathan can already reach deterministically. | Low - reuses an already-registered, already-tested Phase 21 tool; reuses 100% of Phase 94's verified-workflow machinery; zero new architecture. | Trivial - one new signature, zero collision risk, reuses the exact numeric marker already proven for `SCHEDULE_ENABLE`. | Trivial - identical mechanism, zero new code. | Strong - reuses the exact, already-generic, already-parameterized `verify_schedule_enabled_state()` function; only a new call-site literal (`expected_enabled=False`) and a new response-builder. | **Yes** |
| **`SCHEDULE_CREATE`** | Higher - creating schedules is a real, frequent action - but already fully served deterministically (`schedule web search summary for <query> at <HH:MM> [as <name>]`). | Higher - multiple required arguments (`query`, `time_of_day`, optional `name`), free-text attribution risk for `query`/`name`, `HH:MM` format validation the Intelligence Core has never attempted. | Hard - a multi-field free-text capability with no established single-marker attribution precedent in this codebase. | Hard - `query` is unbounded free text; `time_of_day` needs format validation; no existing generic mechanism handles either safely today. | Would need an entirely new verification shape (confirming the new record exists with the exact fields) - not a reuse of any existing verifier. | Not now - explicitly deferred at the Phase 94 planning gate, and this plan does not re-open that assessment (per this document's own scope: no new repository-wide candidate search). |
| **`MEMORY_SAVE`** | High - saving memories is one of the most common actions. | Higher - unbounded free-text argument (the memory content itself), category selection, and this repository's existing string-hygiene rules would need extending, not just reusing. | Moderate-to-hard - no existing numeric-marker precedent; would need a new free-text attribution rule distinct from `PROJECT_STATE_UPDATE_FOCUS`'s `" to "` marker (different grammar, different risk of ambiguous trailing text). | Hard - free-text content has no natural terminal marker the way a schedule id or a focus value does. | Would need a new, real write-then-verify shape (confirming the saved memory's content matches exactly) - a new verifier, not a reuse. | Not selected now - a materially larger, riskier scope than `SCHEDULE_DISABLE`, and out of this plan's stated scope (no new capability search; Phase 94 already assessed and deferred it). |
| **Another `ProjectState` field** | Low-to-moderate - `focus` already covers the one field Nathan actively uses; other fields (`branch`, `phase`, `commit`, `suite_result`) are set far less often. | Low - would reuse the exact `PROJECT_STATE_UPDATE_FOCUS` shape. | Trivial - same marker mechanism as `focus`. | Trivial. | Strong - reuses `verify_focus_update()`'s exact shape (generalized to any field). | Not selected now - lower daily usefulness than completing the enable/disable pair, and not the subject of this planning gate's live-code investigation (which focused on `SCHEDULE_DISABLE` per the task's own primary-candidate instruction). |

`SCHEDULE_DISABLE` is the clear, narrow, low-risk choice: it is the only candidate requiring **zero new tool code, zero new verifier tool, zero new SecurityManager rule, and zero new architecture** - purely a catalog entry, a grounding signature, a numeric-marker entry, and one small orchestrator response-builder, all reusing Phase 94's own proven machinery.

---

## 13. Selected Outcome

### Outcome A — Select `SCHEDULE_DISABLE`

**Exact Phase 95 name**: Phase 95 — Verified Schedule Disable Expansion.

**Exact catalogue definition** (new entry in `intelligence/capability_catalog.py`):
```python
CapabilityId.SCHEDULE_DISABLE: CapabilityAdapter(
    capability_id=CapabilityId.SCHEDULE_DISABLE,
    tool_name="schedule_disable",
    description=(
        "Disables one of your configured schedules by its exact id. "
        "Requires your explicit approval, and the stored enabled "
        "state is checked with a structured read-back after it runs."
    ),
    arguments=(
        CapabilityArgumentSpec(name="schedule_id", type_name="int", required=True),
    ),
    allowed_strategy=ExecutionStrategy.TWO_STEP_WORKFLOW,
    max_execution_tier=SecurityTier.YELLOW,
    verification_strategy_id="schedule_disabled_exact_match",
    internal_only=False,
    paired_verify_capability_id=CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE,
    paired_verify_input_keys=("schedule_id",),
),
```
Also requires one new `CapabilityId` member: `SCHEDULE_DISABLE = "schedule_disable"`. No new `CapabilityId` member is needed for the verifier - `SCHEDULE_VERIFY_ENABLED_STATE` is reused verbatim.

**Exact schema**: one required argument, `schedule_id: int` - identical shape to `SCHEDULE_ENABLE`, validated by the existing, unmodified `_validate_arguments()` (explicit bool rejection via the existing `isinstance(value, bool)` branch, no coercion).

**Exact grounding signature**: `action_tokens=("disable",), domain_tokens=("schedule", "schedules")` - see §9.

**Exact ID-attribution rule**: reuse `_extract_numeric_argument_span()` unchanged; add `CapabilityId.SCHEDULE_DISABLE: " schedule "` to `_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY` - see §9.

**Exact real SecurityManager classification**: `"disable schedule"` → `SecurityTier.YELLOW`, via the existing, unmodified rule at `security/security_manager.py:224`. No new rule.

**Exact approval path**: identical to `SCHEDULE_ENABLE`'s own - see §10.

**Exact execution input**: `{"schedule_id": <approved int>}`, identical shape to `SCHEDULE_ENABLE`.

**Exact verifier arrangement**: reuse `SCHEDULE_VERIFY_ENABLED_STATE`/`ScheduleVerifyEnabledStateTool`/`verify_schedule_enabled_state()` unchanged; new `verification_strategy_id="schedule_disabled_exact_match"`; new orchestrator response-builder `_schedule_disable_workflow_result_to_response()` calling `verify_schedule_enabled_state(expected_enabled=False, ...)`; one new entry in the existing `response_builders` dict.

**Exact expected postcondition**: `ScheduleStore.get(schedule_id).enabled is False`.

**Phase size**: **small** - see §14 (one implementation-and-closure batch).

**Batch breakdown**: see §14.

**Acceptance criteria**: see §18.

**Stop conditions**: see §20.

---

## 14. Exact Scope

Add exactly:
- One new user-facing capability: `SCHEDULE_DISABLE` (catalog entry + `CapabilityId` member).
- One new grounding signature (`_INTENT_SIGNATURES` entry).
- One new numeric-marker entry (`_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY`).
- One new `verification_strategy_id` string constant, cross-referenced in `intelligence/verification.py`'s module docstring/constants exactly as `SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID` already is (no new function - `verify_schedule_enabled_state()` is reused verbatim).
- One new orchestrator response-builder method + one new `response_builders` dict entry.
- One new `_TRUSTED_PLANNING_INSTRUCTION` example (tenth model-selectable capability).
- Documentation: `docs/user_guide.md`, `tools/builtin/help_tool.py` (truthful grammar only).
- Full test coverage mirroring every `SCHEDULE_ENABLE` test category (see §17).

**No new tool, no new verifier tool, no new SecurityManager rule, and no new `main.py` registration are required** - `ScheduleDisableTool` and `ScheduleVerifyEnabledStateTool` already exist and are already registered, sharing the same `ScheduleStore`.

---

## 15. Exact Non-Goals

Do not add: `SCHEDULE_CREATE`, schedule deletion, schedule updates, schedule-name targeting, model-selectable expected state, automatic/unapproved disable, new `SecurityManager` rules, weakened tiers, arbitrary verifier predicates, a generic boolean-verifier framework, a broad verifier registry, generic workflow languages, retries, replanning, rollback, compensation, autonomous behavior, memory automation, file operations, dashboard work, voice, phone control, browser control, computer control, or source-code self-modification. Do not invent a distinct cancellation mechanism - "cancel" remains a documented decline synonym.

---

## 16. Phase Size and Batch Breakdown

Per Nathan's milestone mode, this is a **small phase: one implementation-and-closure batch**, not Phase 94's three-batch structure - because `SCHEDULE_DISABLE` requires **zero new architecture**: it purely instantiates the already-generalized, already-proven Phase 94 trusted-workflow foundation with a second, already-existing, already-registered tool pair. There is no equivalent of Phase 94 Batch 1's foundation-generalization work to redo; that work is already complete and already proven generic (§2-§3, §7-§8).

**Batch 1 (single batch)**: add the catalog entry, grounding signature, numeric-marker entry, `verification_strategy_id` constant, orchestrator response-builder, planning-instruction example, full test coverage (all 26 categories in §17), documentation updates, complete regression across Phase 90-94 plus all three environments, Ruff on the exact Git-derived diff, `docs/phase_95_completion_report.md`, and formal closure - all in one batch, since no foundational risk justifies splitting implementation from closure.

If, during implementation, any item in §3's ten-point viability list or the orchestrator dispatch mechanism turns out to behave differently than this plan's live-code inspection found, the implementer must stop and report rather than improvise - but no such finding is expected, given the exact code already read during this planning gate.

---

## 17. Test Strategy

Mirroring `test_orchestrator_schedule_enable_workflow.py`'s and `test_capability_catalog.py`'s established patterns exactly, a new `tests/unit/test_orchestrator_schedule_disable_workflow.py` plus targeted additions to the existing catalogue/grounding/planning/verification test files will cover:

1. Capability catalogue (new `SCHEDULE_DISABLE` adapter shape, twelve-entry/ten-model-selectable counts).
2. Integer validation and bool rejection (reusing the existing generic mechanism - tests only).
3. Unique grounding (no collision with any of the nine other signatures).
4. Exact ID attribution (marker reuse, single-occurrence, digit-only span).
5. `SCHEDULE_ENABLE`/`SCHEDULE_DISABLE` collision separation (both "enable schedule 5" and "disable schedule 5" ground to their own distinct capability, never each other).
6. Real YELLOW classification (`"disable schedule"` live re-check).
7. No execution before approval.
8. Decline/cancel-synonym behavior (mirroring Phase 94 Batch 3's honest cancellation-is-decline test).
9. Expiry (mirroring Phase 94 Batch 3's `_FakeClock`/`timeout_seconds` test).
10. Restart-safe resume (durable pause/reload/resume cycle).
11. Immutable approved ID.
12. Duplicate-execution prevention.
13. Exact disable execution input (`{"schedule_id": <int>}`).
14. Durable `False` verification success.
15. Already-disabled behavior (preserves existing unconditional-success tool behavior).
16. Missing target at execution (honest failure, no verification attempted).
17. Missing target at verification (narrow test-double verifier, honest `UNAVAILABLE`).
18. Verification mismatch (durable `enabled=True` fails the expected-`False` check).
19. Verifier failure (honest `UNAVAILABLE`, no retry).
20. No retry or correction anywhere in the above.
21. `SCHEDULE_ENABLE` complete regression (all 33 existing tests pass unmodified).
22. `PROJECT_STATE_UPDATE_FOCUS` complete regression (all 31 existing tests pass unmodified).
23. All other existing capabilities unchanged (catalogue/structured-output/grounding/planning regression sweep).
24. Advisory (`ask jarvis:`) and deterministic (`disable schedule <id>`, `enable schedule <id>`, `list schedules`) paths unchanged.
25. Full suite in all three required environments (normal, `AI_REASONING_ENABLED=false`, `PYTHON_DOTENV_DISABLED=1`).
26. Ruff on the exact Git-derived Phase 95 changed-Python-file set, plus `git diff --check`.

A coexistence test proving all three `TWO_STEP_WORKFLOW` capabilities (`PROJECT_STATE_UPDATE_FOCUS`, `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`) dispatch correctly through one shared orchestrator instance without ambiguity is also required, extending Phase 94 Batch 3's own two-capability coexistence test.

---

## 18. Acceptance Criteria

- `SCHEDULE_DISABLE` classifies YELLOW, requires real approval, executes through the real, unmodified `ScheduleDisableTool`, and verifies `enabled is False` through the real, unmodified `ScheduleVerifyEnabledStateTool`/`verify_schedule_enabled_state()`.
- Zero new `SecurityManager` rules or tier changes.
- Zero new tool files; zero new `main.py` wiring.
- Orchestrator dispatch remains catalog-driven with no new per-capability `if`/`elif` branch in the recognition step (only a new `response_builders` dict entry).
- `SCHEDULE_ENABLE` and `PROJECT_STATE_UPDATE_FOCUS` remain provably unchanged (complete regression suites pass unmodified).
- All required tests (§17) pass; full suite passes identically in all three environments.
- Ruff clean on the exact Git-derived Phase 95 diff; `git diff --check` clean.
- Documentation (`docs/user_guide.md`, `tools/builtin/help_tool.py`) accurately describes only the real, accepted grammar - does not advertise any non-goal from §15.

---

## 19. Risks and Mitigations

- **Risk**: a future implementer assumes the verifier needs a new capability or tool. **Mitigation**: this plan explicitly documents (§7, Option C) why that is unnecessary and rejects it.
- **Risk**: the numeric marker collides between enable/disable. **Mitigation**: §9 documents why sharing `" schedule "` is safe (signature-level disambiguation happens first).
- **Risk**: scope creep toward `SCHEDULE_CREATE` or a generic verifier framework. **Mitigation**: §15's explicit non-goal list, mirroring Phase 94's own successful discipline.
- **Risk**: cancellation is fabricated as a distinct mechanism to satisfy a test requirement. **Mitigation**: §10 documents the real, honest architecture (cancel-as-decline-synonym) up front, before implementation begins.

---

## 20. Stop Conditions

Implementation must stop and report, never improvise past, if any of the following is found true at implementation time (none is expected, given this planning gate's live-code findings):

- `ScheduleDisableTool` or `ScheduleStore.disable()` no longer matches the exact contract documented in §3.
- `verify_schedule_enabled_state()` cannot be safely called with `expected_enabled=False` without modification.
- A grounding collision is found between the new `SCHEDULE_DISABLE` signature and any of the nine existing signatures.
- The orchestrator's catalog-driven recognition (`_matching_two_step_write_capability()`) cannot correctly distinguish `SCHEDULE_ENABLE`'s and `SCHEDULE_DISABLE`'s workflow shapes.
- `PROJECT_STATE_UPDATE_FOCUS` or `SCHEDULE_ENABLE` behavior changes in any way.
- A persistence migration is required.
- Retries, replanning, or probabilistic/general-NLU behavior become necessary to make the design work.

---

## 21. Manual Anthropic Limitation

Live Anthropic manual acceptance testing remains **postponed** because the configured API account lacks sufficient credits. This is an **external account limitation, not a Jarvis production-code failure** - no production behavior is proposed to bypass it, and Phase 95 (if implemented) will be verified the same way every prior phase has been: repository-level deterministic, fake-provider, grounding, security, `ToolExecutor`, real-SQLite, and full-suite tests.
