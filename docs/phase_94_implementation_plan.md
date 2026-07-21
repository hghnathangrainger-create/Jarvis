# Phase 94 — Safe Verified Write Expansion — Planning Gate

**Status: Planning gate only. No production or test code has been implemented.**

---

## 1. Current Repository Baseline

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- HEAD at the start of this planning gate: `c153a9c` (Phase 93 Batch 2 and closure).
- Verified baseline: **4843 passed, 3 skipped, 0 failed**.
- Phase 90 — Jarvis Intelligence Core V1: closed. Phase 91 — Safe Intelligence Capability Expansion: closed. Phase 92 — Intelligence Decision Grounding and Reliability V1: closed. Phase 93 — Safe Read-Only Audit History Expansion: formally closed.
- The Intelligence Core currently catalogues exactly eight model-selectable capabilities: `PROJECT_STATE_SHOW`, `PROJECT_STATE_UPDATE_FOCUS`, `HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT`, `MEMORY_SEARCH`, `APPROVAL_HISTORY`, `WORKFLOW_HISTORY` - plus one internal-only capability, `PROJECT_STATE_VERIFY_FOCUS`.
- Manual Anthropic API acceptance remains postponed (insufficient account credits) - an external limitation, not a code defect; see §20.

---

## 2. Architecture Inspected

**Intelligence Core (read, no changes made):**
- `intelligence/capability_catalog.py` — `CapabilityId` (9 members), `CapabilityAdapter` (8 fields: `capability_id`, `tool_name`, `description`, `arguments`, `allowed_strategy`, `max_execution_tier`, `verification_strategy_id`, `internal_only`), `ExecutionStrategy` (`SINGLE_TOOL`, `TWO_STEP_WORKFLOW`), `_FIXED_ARGUMENTS_BY_CAPABILITY`, `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY`, `build_tool_input()`. **No field exists today for pairing a write capability with its own verify capability** - the pairing is currently hardcoded in `intelligence/planning.py` (see below), not data-driven.
- `intelligence/grounding.py` — `ground_decision()`, `_IntentSignature` (action/domain/qualifier tokens/phrases), 8 real signatures, the negation gate, and exactly two argument-span extractors (`MEMORY_SEARCH`'s `" for "` marker, `PROJECT_STATE_UPDATE_FOCUS`'s `" to "` marker) - **both string-only**. No numeric-argument attribution mechanism exists yet.
- `intelligence/planning.py::select_tool()` — the exact execution order (parse → validate → ground → preflight → execution-strategy branch) is unchanged since Phase 92. The `TWO_STEP_WORKFLOW` branch calls `_build_update_focus_workflow_plan()`, which **hardcodes** `catalog.get(CapabilityId.PROJECT_STATE_VERIFY_FOCUS)` at line 550 - the one and only verify-capability lookup in the entire codebase, and it is not parameterized by the write capability at all.
- `intelligence/verification.py` — exactly one verifier function, `verify_focus_update()`, comparing a write step's expected string value against a verify step's `ToolResult.metadata["focus"]`, producing one of `VERIFIED`/`FAILED`/`UNAVAILABLE`/`NOT_REQUIRED`. No second verifier, and no generic verifier registry, exists.
- `core/orchestrator.py` — `select_tool()`'s `EXECUTABLE_WORKFLOW` outcome dispatches, at the call site, generically to `_start_update_focus_workflow()` for *any* `TWO_STEP_WORKFLOW` capability (this dispatch is already generic). However, **inside** that method and inside `execute_approved()`'s resume path, the workflow's *identity* is recognised only by the hardcoded structural check `_is_update_focus_workflow_result()` (`steps[0].tool_name == "project_state_update" and steps[1].tool_name == "project_state_verify"`, line ~2044), and the only response-translation method, `_update_focus_workflow_result_to_response()`, is hardcoded to focus-specific wording and calls `verify_focus_update()` directly by name.
- `security/security_manager.py` — a flat, ordered list of `_Rule(action_substring, tier, reason)` entries; `classify_action()` is a pure string-match function with no capability-specific logic.
- `tools/executor.py` — `ToolExecutor.execute()` is fully generic (tool name + input → real classification → real `tool.run()` → audit event); it has no capability-specific logic anywhere.
- `approval/approval_manager.py`, `approval/pending_approval_store.py`, `workflow/engine.py`, `workflow/paused_workflow_store.py` — **directly re-confirmed via `grep -in "project_state\|focus"` producing zero matches in all four files.** The entire approval-creation, durable-pending-state, `WorkflowEngine.run()`/`resume()`, and durable-paused-workflow-state architecture is completely generic, operating only on `Plan`/`PlanStep`/`WorkflowResult` - it already fully supports a second `TWO_STEP_WORKFLOW` capability with **zero changes** to any of these four files.

**Existing write-tool pattern re-confirmed:** `tools/builtin/project_state_verify_tool.py` is the one existing internal-only, read-only "verify tool" - it wraps `ProjectStateStore.get()`, is registered in `ToolRegistry` (so `ToolExecutor`/audit apply normally), has no `CommandRouter` grammar entry, and is marked `internal_only=True` in the catalog so `intelligence/structured_output.py` rejects any AI attempt to select it directly. This is the exact template a second verify tool must follow.

**Existing tests inspected:** `tests/unit/test_capability_catalog.py`, `tests/unit/test_grounding.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_structured_output.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_orchestrator_update_focus_workflow.py`, `tests/unit/test_verification.py`, `tests/unit/test_project_state_update_tool.py`, `tests/unit/test_project_state_verify_tool.py`, `tests/unit/test_schedule_tools.py` (or its real equivalent test file for schedule enable/disable), `docs/phase_90_completion_report.md` through `docs/phase_93_completion_report.md`, `docs/phase_90_implementation_plan.md` through `docs/phase_93_implementation_plan.md`.

---

## 3. Existing Complete Write Pipeline

Only `PROJECT_STATE_UPDATE_FOCUS` exercises the full pipeline today:

```
request → bounded context → strict structured AI decision → exact schema validation
  → deterministic grounding → catalogue-wide unique intent match → exact argument attribution
  → real SecurityManager preflight (YELLOW) → real ApprovalManager (durable, restart-safe)
  → real WorkflowEngine (two fixed steps) → real ToolExecutor (write, then verify)
  → intelligence.verification.verify_focus_update() (exact string equality)
  → grounded, verification-aware JarvisResponse
```

Every one of the eight other capabilities is either `SINGLE_TOOL`/GREEN (no approval, no verification) or, for `PROJECT_STATE_VERIFY_FOCUS`, internal-only and unreachable directly. No other capability has ever exercised YELLOW classification, approval, durable resume, or exact verification.

---

## 4. Candidate Inventory

Real, currently-registered write-capable tools inspected (`ls tools/builtin/` cross-checked against `security/security_manager.py`'s real rules and `main.py`'s real wiring - no name in this plan is assumed without this cross-check):

| Candidate | Real tool/class | Real action string | Real tier |
|---|---|---|---|
| Schedule create | `ScheduleCreateTool` (`schedule_create`) | `"schedule web search"` | YELLOW |
| Schedule enable | `ScheduleEnableTool` (`schedule_enable`) | `"enable schedule"` | YELLOW |
| Schedule disable | `ScheduleDisableTool` (`schedule_disable`) | `"disable schedule"` | YELLOW |
| Schedule update | *(no such tool exists)* | — | — |
| Schedule delete | *(no such tool exists - disabling is the only way to stop a schedule)* | — | — |
| Memory save | `MemoryTool` (`memory`, `operation="save"`) | `"save memory"` | **GREEN** |
| Memory update | `MemoryUpdateTool` (`memory_update`, `operation="update"`) | `"update memory"` | YELLOW |
| Memory move/recategorize | `MemoryUpdateTool` (`memory_update`, `operation="move"`) | `"move memory"` | YELLOW |
| Memory forget | `MemoryForgetTool` (`memory_forget`) | `"forget memory"` | YELLOW |
| Memory forget-all | *(blocked outright)* | `"forget all memories"` | RED |
| Project-state fields beyond focus | `ProjectStateUpdateTool` (`project_state_update`, `field` ∈ `branch`/`phase`/`commit`/`suite`) | `"update jarvis project state"` | YELLOW |
| File delete (quarantine) | `FileDeleteTool` | `"delete file"` | YELLOW |
| File create/append/copy/move/restore | `FileCreateTool`/etc. | `"write file"`/`"copy file"`/`"move file"`/`"restore file"` | YELLOW |

`send email`/`send message`/`install`/`run command`/`purchase`/`pay` and similar `_Rule` entries in `security_manager.py` have **no corresponding real registered tool anywhere in `tools/builtin/`** - they are defensive rules with no live consumer, so they are not real candidates and are excluded per this plan's own "do not invent candidate actions absent from the repository" instruction. File-writing tools exist but are excluded per this task's own explicit scope boundary (no arbitrary file writes/broad system mutation).

---

## 5. Per-Candidate Safety and Verification Assessment

### Schedule enable (`schedule_enable`)
1-6. Real class `ScheduleEnableTool`; deterministic grammar `"enable schedule <id>"` (`core/command_router.py` line ~559, `_SCHEDULE_ENABLE_PREFIXES`); real `ToolExecutor` input `{"schedule_id": <int>}`; one required field, `schedule_id` (int); real action `"enable schedule"`; real classification **YELLOW** (`security_manager.py` line 223).
7-8. Existing approval behavior: identical to every other YELLOW tool - `ToolExecutor` withholds execution until `ApprovalManager` records an approved decision; this is the same generic, already-restart-safe `PendingApprovalStore`/`ApprovalManager` architecture `PROJECT_STATE_UPDATE_FOCUS` already uses (re-confirmed generic, §2).
9. Durable store modified: `scheduling.schedule_store.ScheduleStore` (the `schedules` table's `enabled` column, via `ScheduleStore.enable(schedule_id)`).
10-11. Exact postcondition: `ScheduleStore.get(schedule_id).enabled is True`. `ScheduleStore.get()` already exists, is read-only, and is exactly analogous to `ProjectStateStore.get()`.
12. Verification can be exact (boolean equality), deterministic, read-only (`get()` performs no write), and side-effect-free.
13. Rollback/failure: a missing `schedule_id` fails honestly with no write (`ScheduleStore.enable()` returns `None`, mirrored by the tool's own `self.fail(...)`); no partial-write state is possible (`enabled` is a single boolean column).
14. Privacy/data-loss risk: **none** - flipping a boolean on an already-user-created schedule; no data is lost or exposed.
15. Grounding-signature feasibility: **high** - action tokens (`"enable"`) are already distinct from every other capability's vocabulary; domain token `"schedule"`/`"schedules"` already exists as `SCHEDULE_LIST`'s own domain, but `SCHEDULE_LIST`'s signature requires action `"show"`/`"list"`, never `"enable"`, so no collision.
16. Argument-span attribution feasibility: **new but small** - no existing Phase 92 mechanism extracts a numeric argument; a new, narrow, marker-based numeric extractor (mirroring the existing string-span technique, adapted to parse a trailing integer instead of a trailing string) is required. See §6.
17. Expected daily value: moderate-to-high - re-enabling a paused schedule via natural language is a plausible, low-frequency-but-real request.
18. Required architectural changes: see §13.
19. Required tests: see §16.
20. **Recommendation: select now** (see §9 for the exact chosen capability).

### Schedule disable (`schedule_disable`)
Identical shape to schedule enable in every respect (1-16, 18-19), differing only in the expected boolean (`enabled is False`) and the real action string/classification (`"disable schedule"`, YELLOW, `security_manager.py` line 224).
17. Expected daily value: comparable to enable - "turn off that schedule" is an equally plausible request.
20. **Recommendation: defer to an immediate, near-zero-marginal-cost follow-up** once schedule enable's foundation (generalized workflow-builder, generalized orchestrator dispatch, numeric argument attribution) exists - adding this second capability afterward requires only one more catalogue entry, one more signature, and its own tests, reusing every other piece of new architecture unchanged.

### Schedule create (`schedule_create`)
1-6. Real class `ScheduleCreateTool`; real action `"schedule web search"`; YELLOW; three fields (`query` required, `time_of_day` required, `name` optional).
7-9. Same generic approval architecture as any YELLOW tool; durable store `ScheduleStore` (a **new row**, not a mutation of an existing one).
10-11. Postcondition is weaker: a created schedule's `id` does not exist until *after* the write executes, so there is no pre-known id to attribute or re-check deterministically before execution - verification would need to search for a schedule matching the requested `query`/`time_of_day`, which is not an exact-identity check the way `enabled is True` is.
12. Verification would be a **best-match search, not exact equality** - a materially weaker guarantee than every other candidate.
13-14. Duplicate creation after a restart-resume is a real, currently-unaddressed risk: nothing in `ScheduleStore.create()` is idempotent by request content, so a resumed-and-re-executed create could plausibly produce two rows for the same request without a new idempotency key.
15-16. `query` is unbounded free text with no reliable single marker to extract exactly (unlike `memory_search`'s `" for "` marker, a schedule query could contain almost any phrase); `time_of_day` parsing (`"HH:MM"`) is more constrained but still a second free-form attribution target alongside `query` and optional `name` - three attribution targets, not one.
20. **Recommendation: reject for Phase 94**, exactly as this plan's own candidate-specific caution anticipated ("creation is likely higher risk than enable/disable"). No repository evidence overcomes the exact-identity and duplicate-creation risks above.

### Memory save (`memory`, `operation="save"`)
1-6. Real class `MemoryTool`; real action `"save memory"`; **classifies GREEN**, not YELLOW (`security_manager.py`'s comment explains: "a manual save is a single, explicit, user-requested store, not a broad state change").
7. **No approval exists or is required** - this candidate does not exercise the YELLOW/approval/resume pipeline this phase's own strategic objective is about at all.
9-12. Durable store: `EpisodicMemoryStore` (via `MemoryManager`); postcondition (`memory.get(new_id).content == content`) is exact and read-only, but only reachable *after* execution, since the id is assigned at save time - the same weaker-identity problem as schedule creation, on a smaller scale (one field, `content`, vs. three).
15-16. Domain word `"memory"`/`"memories"` already exists in two current signatures (`MEMORY_LIST_RECENT`, `MEMORY_SEARCH`); a `"save"` action token would need to be added and kept collision-free against both. `content` attribution (a potentially long, free-form string) has weaker single-marker reliability than a short search query.
20. **Recommendation: defer.** Because it is GREEN, it cannot demonstrate this phase's actual objective (a second YELLOW-classified, approval-gated, verified write) at all; it is architecturally simple but answers a different question than the one this phase was chartered to answer. Also explicitly not to be confused with, or used to justify, automatic memory writes (which remain out of scope regardless).

### Memory update / move (`memory_update`)
1-6. Real class `MemoryUpdateTool`; real actions `"update memory"`/`"move memory"`; YELLOW; **two required fields each** (`memory_id` + `content`, or `memory_id` + `category`), plus an `operation` selector.
9-12. Durable store: `EpisodicMemoryStore`; postcondition is exact and read-only (`memory.get(id).content == new_content` / `.category == new_category`).
14. Privacy risk: real, stored memory content would need to be echoed back into an intent-signature/grounding discussion path if a mismatch occurs - the existing Phase 92 discipline (never echo a rejected value) still applies, but the *content* argument itself is far more likely to contain sensitive free text than a short search query or a schedule id.
15-16. Two model-facing arguments per operation (`memory_id` + one free-text value), plus an internal `operation` selector that itself would need grounding-level disambiguation (mirroring the "one bounded enum vs. two capabilities" question this plan already resolved for schedule enable/disable, but with the *added* complication of a second, free-text argument on top). Free-text `content`/`category` attribution is materially less reliable than schedule enable's single integer.
20. **Recommendation: defer.** More attribution surface (two arguments, one of them unbounded free text) than any accepted candidate; higher achievable risk for no corresponding gain in verification rigor, since the underlying verification mechanism (exact equality) is no stronger than schedule enable's simpler boolean check.

### Memory forget (`memory_forget`)
1-9. Real class `MemoryForgetTool`; real action `"forget memory"`; YELLOW; one field (`memory_id`); durable store `EpisodicMemoryStore` - a genuine **deletion**, not quarantined (no memory-equivalent of `.jarvis_trash/`; `MemoryManager.forget()` removes the row outright).
10-12. Postcondition (`memory.get(id) is None`) is exact, deterministic, and read-only to check - the *mechanism* of verification is not the problem here.
13-14. **Not recoverable.** This plan's own mandatory instruction is explicit: "Do not select it unless: ... deletion is recoverable or quarantined." No recovery or quarantine mechanism exists for memories today (unlike `FileDeleteTool`, which does quarantine).
20. **Recommendation: reject for Phase 94**, per this plan's own explicit deletion-caution standard. Simple in argument shape, but fails the irreversibility requirement outright. "Prefer deferral" is the correct call here, not narrowing or redesign - no redesign of `MemoryForgetTool` within this phase's scope could add quarantine without itself becoming a separate, larger memory-quarantine feature.

### Project-state fields beyond focus (`project_state_update`, other `field` values)
1-9. Same real tool (`ProjectStateUpdateTool`) and same real action/tier (`"update jarvis project state"`, YELLOW) `PROJECT_STATE_UPDATE_FOCUS` already uses - the *tool* is not new, only the currently-fixed `field` value would become model-selectable.
10-12. Exact, deterministic, read-only verification is achievable in principle (an extended `ProjectStateVerifyTool` already reads the whole record), but would require the *verifier itself* to become field-aware (comparing whichever field was written, not always `"focus"`) - i.e., **generalizing** `verify_focus_update()` into a multi-field verifier, not adding a second, narrow, independent one.
15-16. Grounding: the domain word `"focus"` is already fixed to `PROJECT_STATE_UPDATE_FOCUS`'s own signature; supporting `branch`/`phase`/`commit`/`suite` as additional, model-selectable field values would require **either** four new field-specific signatures **or** a single capability with a `field` enum argument requiring its own dedicated attribution rule (mirroring the enable/disable "bounded enum" question, but for four values instead of two, and layered on top of the existing `value` string attribution).
20. **Recommendation: reject for Phase 94.** This is best understood as *modifying* the existing `PROJECT_STATE_UPDATE_FOCUS` capability's scope (and generalizing its dedicated verifier into a shared one) rather than adding a cleanly separate second write capability - exactly the kind of premature verifier generalization this plan's own instructions caution against ("do not propose a generic verifier registry unless at least two concrete strategies now justify it"). Schedule enable gives a cleaner, narrower second concrete strategy without touching `PROJECT_STATE_UPDATE_FOCUS`'s own existing, accepted behavior at all.

### File tools (delete/create/append/copy/move/restore)
Excluded outright per this plan's own explicit scope boundary ("do not recommend arbitrary file writes ... or other broad system mutation"), regardless of their individual safety properties (e.g. `FileDeleteTool`'s quarantine mechanism is in fact recoverable). Not assessed further.

---

## 6. Grounding and Argument-Attribution Assessment

**Signature feasibility for `SCHEDULE_ENABLE`:** action tokens `("enable",)`; domain tokens `("schedule", "schedules")`; no qualifier needed (unlike `MEMORY_LIST_RECENT`/the two Phase 93 capabilities, there is no ambiguous shared-qualifier collision to resolve - `"enable"` does not appear in any other signature's action tokens).

**Collision check against all eight current signatures:** `"enable"` is not an action token of any existing signature. `"schedule"`/`"schedules"` is currently a domain token only of `SCHEDULE_LIST` (action tokens `"show"`/`"list"`) - since `SCHEDULE_ENABLE` requires action `"enable"` and `SCHEDULE_LIST` requires action `"show"`/`"list"`, a real request can satisfy at most one of the two (a request combining both, e.g. "show and enable my schedules", would correctly refuse as `multiple_signatures_matched` - the same, already-proven Phase 92 behavior).

**Exact accepted request example grounded in current deterministic grammar:** `"enable schedule 5"` - already a real, accepted deterministic command phrase (`core/command_router.py`'s own `_SCHEDULE_ENABLE_PREFIXES = ("enable schedule",)`).

**Argument-span attribution (new mechanism required):** no existing Phase 92 extractor handles a *numeric* argument - both existing extractors (`MEMORY_SEARCH`, `PROJECT_STATE_UPDATE_FOCUS`) extract and compare *strings*. A small, deterministic, marker-based numeric extractor is required, following the exact same technique (never the code) as the existing string extractors:
- Marker: `" schedule "` (case-insensitive, matching the real, accepted `"enable schedule <id>"` grammar).
- The marker must occur **exactly once** (zero or multiple → refuse, mirroring `missing_argument_span`/`ambiguous_argument_span`).
- The trimmed text after the marker must be **entirely decimal digits** (no leading/trailing non-digit characters, no sign, no whitespace-separated extra tokens) - anything else refuses (a new, analogous reason, e.g. `non_numeric_argument_span`, or reuse of `ambiguous_argument_span` - to be decided in Batch 1's own precise design work, not this planning gate).
- The parsed integer is compared to the model's already-validated `schedule_id` argument via **exact integer equality** - never a substring, never a range, never a fuzzy match.

This is a small, bounded, fully deterministic rule - no significant-term fallback, fuzzy matching, semantic similarity, additional model call, confidence scoring, or broad synonym table is introduced. It is a narrow generalization of an established technique (marker + single occurrence + exact comparison), applied to a second value type (int instead of str), not a new attribution philosophy.

---

## 7. Approval and Resume Assessment

Re-confirmed directly (§2): `ApprovalManager`, `PendingApprovalStore`, `WorkflowEngine`, and `PausedWorkflowStore` contain **zero** project-state/focus-specific logic - all four already operate generically on `Plan`/`PlanStep`/`WorkflowResult`, and so already provide, without modification:
- **One approval request per write** - `ApprovalManager.create_request()` is called exactly once per `WorkflowEngine.run()` pause, regardless of which two-step `Plan` is running.
- **No execution before approval** - `ToolExecutor` never executes a YELLOW-classified step without an approved `ApprovalDecision`, enforced identically for any capability.
- **Exact approved arguments, no argument change between approval and execution** - the paused `Plan`'s own `PlanStep.tool_input` is the single source of durable truth; `WorkflowEngine.resume()` re-executes exactly that stored input, never a freshly-recomputed one.
- **Durable pending state and restart-safe resume** - `PendingApprovalStore`/`PausedWorkflowStore` durably persist the exact pending request and paused plan; `main.py`'s own reload-on-startup path (`approvals.reload_pending()`/`workflow_engine.reload_paused()`) already restores this state generically for *any* two-step plan, not specifically the focus-update one.
- **No duplicate execution after restart** - `WorkflowEngine`'s own resume logic executes a paused plan's remaining steps exactly once; nothing in this architecture is capability-specific.
- **No verification before execution, no execution after rejection/cancellation** - enforced by `WorkflowEngine`'s own step-ordering and `ApprovalManager.decline()`/`invalidate_pending()`, both already fully generic.
- **No stale approval reuse** - `ApprovalManager`'s existing one-time-decision semantics apply identically to any request id.

**What is *not* yet generic**, and must be added in Batch 1 (§13): the *identity recognition* of a resumed/completed workflow (`_is_update_focus_workflow_result()`) and the *response translation* (`_update_focus_workflow_result_to_response()`, which calls `verify_focus_update()` by name) are both hardcoded to the one existing workflow's tool-name pair and wording. A second, analogous structural recognizer and response-translation method (or a small, explicitly two-case dispatch, not a generic plugin system) are required - see §13.

**Conclusion: the existing approval/workflow architecture can support this candidate without duplicating its durable-state or resume guarantees** - only the response-shaping layer above it needs a second, narrow, parallel path.

---

## 8. Security Classifications

Re-confirmed directly against the live `security/security_manager.py` rule list (no rule added or changed by this plan):
- `"enable schedule"` → **YELLOW** (line 223: `"Re-enabling a scheduled action resumes unattended runs and should be confirmed."`).
- `"disable schedule"` → **YELLOW** (line 224, for the deferred follow-up capability).
- The new internal-only verify tool's own action reuses `SCHEDULE_LIST`'s existing `"list schedules"`-equivalent read semantics or a comparably worded, already-GREEN-classifying read action (exact final string to be fixed in Batch 1's own design pass, mirroring `ProjectStateVerifyTool`'s own reuse of `ProjectStateShowTool`'s action string rather than inventing a new rule).

No `SecurityManager` rule is added, changed, or weakened by this plan.

---

## 9. Selected Outcome

**Outcome A — select one verified write capability: `SCHEDULE_ENABLE`.**

Rationale against the mandatory selection standard (§ of the task, all satisfied): existing real write action (`ScheduleEnableTool`); narrow explicit schema (one integer argument); deterministic live-request attribution (new small numeric span rule, §6); unique, collision-free intent signature against all eight current signatures (§6); unchanged, appropriate real YELLOW classification; approval before execution (existing, generic architecture, §7); execution through `ToolExecutor` (unchanged); exact durable verification (`ScheduleStore.get(schedule_id).enabled is True`, a real boolean equality check, never a "the tool said it succeeded" check); verification is read-only and side-effect-free; the verifier can distinguish exact success, no change, wrong/partial change (not applicable here - the postcondition is a single boolean, so "wrong change" collapses into "still False"), missing target (`ScheduleStore.get()` returns `None`), and execution failure (the write step's own `ToolResult.success` remains inspectable independent of the verify step); a safe grounded response is constructible from real execution + verification results only; no retries, replanning, or autonomous correction anywhere in the design.

`SCHEDULE_DISABLE` is deferred (§5) as a near-zero-marginal-cost follow-up once the shared foundation exists. `SCHEDULE_CREATE`, memory save/update/move/forget, and project-state fields beyond focus are all deferred or rejected (§5) - none meets the full mandatory selection standard as cleanly as schedule enable, primarily due to weaker exact-identity verification (creation), unbounded free-text attribution (memory content/category, schedule query), irreversibility (memory forget), or premature verifier generalization (other project-state fields).

---

## 10. Exact Proposed Capability

- **`CapabilityId.SCHEDULE_ENABLE`** = `"schedule_enable"`.
- `tool_name`: `"schedule_enable"` (the real, already-registered `ScheduleEnableTool`).
- `arguments`: exactly one - `CapabilityArgumentSpec(name="schedule_id", type_name="int", required=True)`.
- `allowed_strategy`: `ExecutionStrategy.TWO_STEP_WORKFLOW`.
- `max_execution_tier`: `SecurityTier.YELLOW`.
- `verification_strategy_id`: a new fixed string, e.g. `"schedule_enabled_exact_match"`.
- `internal_only`: `False`.
- A new, paired, internal-only capability, e.g. **`CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE`** = `"schedule_verify_enabled_state"`, `tool_name="schedule_verify_enabled_state"` (a new tool, §13), `arguments=()`, `SINGLE_TOOL`, `SecurityTier.GREEN`, `verification_strategy_id=None`, `internal_only=True` - the direct structural analogue of `PROJECT_STATE_VERIFY_FOCUS`/`ProjectStateVerifyTool`.

---

## 11. Exact Scope

- Add exactly one new model-selectable capability (`SCHEDULE_ENABLE`) and exactly one new internal-only paired verify capability (`SCHEDULE_VERIFY_ENABLED_STATE`).
- Add exactly one new, narrow verify tool (`ScheduleVerifyEnabledStateTool`), registered in `ToolRegistry` like every other tool, with no `CommandRouter` grammar entry.
- Add exactly one new verifier function in `intelligence/verification.py` (e.g. `verify_schedule_enabled_state()`), mirroring `verify_focus_update()`'s exact shape (pure function, `VerificationOutcome`, no new outcome values needed).
- Add exactly one new grounding signature and exactly one new numeric argument-attribution rule.
- Generalize `intelligence/planning.py`'s workflow-plan builder to look up its paired verify capability from a new, explicit `CapabilityAdapter` field (e.g. `paired_verify_capability_id: CapabilityId | None = None`) instead of a hardcoded name - a small, mechanical, two-value-only generalization, not a plugin registry.
- Add exactly one new structural workflow recognizer and one new response-translation method in `core/orchestrator.py`, extending the existing two-branch dispatch (`_is_update_focus_workflow_result` / generic fallback) to a three-branch dispatch (add one more named check before the same generic fallback).

## 12. Exact Non-Goals

Do not add: `SCHEDULE_DISABLE` (deferred to an explicit, separate follow-up), `SCHEDULE_CREATE`, any memory write capability, any additional `PROJECT_STATE_UPDATE_FOCUS` field, any file-system write capability, a generic/pluggable verifier registry, a generic/pluggable workflow-pairing registry, any new `SecurityManager` rule or tier change, arbitrary `ToolRegistry` exposure, multi-tool plans, retries, replanning, autonomous loops, automatic memory writes, conversation persistence, dashboard changes, voice/microphone/wake-word/phone/browser/computer control, or source-code self-modification.

---

## 13. Proposed Architecture

**New production components:**
1. `tools/builtin/schedule_verify_enabled_state_tool.py` — `ScheduleVerifyEnabledStateTool(schedules: ScheduleStore)`, internal-only, read-only, returns `ToolResult(metadata={"schedule_id": ..., "enabled": <bool>})` for a `schedule_id` in its input, or an honest failure if the id does not exist - mirroring `ProjectStateVerifyTool` exactly.
2. `intelligence/capability_catalog.py` — one new field on `CapabilityAdapter`, `paired_verify_capability_id: CapabilityId | None = None` (defaults to `None` for all 8 existing entries, so their behavior is provably unchanged); `PROJECT_STATE_UPDATE_FOCUS`'s own entry gains `paired_verify_capability_id=CapabilityId.PROJECT_STATE_VERIFY_FOCUS` (making its existing hardcoded pairing explicit and data-driven for the first time); the two new catalog entries (§10).
3. `intelligence/grounding.py` — one new `_IntentSignature` entry; one new marker-based numeric argument-span extractor (§6), added beside (never replacing) the two existing string extractors.
4. `intelligence/planning.py` — `_build_update_focus_workflow_plan()` generalized to read `write_adapter.paired_verify_capability_id` instead of the hardcoded `CapabilityId.PROJECT_STATE_VERIFY_FOCUS` literal; likely renamed to reflect its now-general purpose (e.g. `_build_write_and_verify_workflow_plan()`) - a rename and one lookup-source change, no behavioral change for the existing workflow.
5. `intelligence/verification.py` — one new function, `verify_schedule_enabled_state(*, expected_enabled: bool, verify_tool_result: ToolResult | None) -> VerificationResult`, reusing the existing `VerificationOutcome`/`VerificationResult` types unchanged.
6. `core/orchestrator.py` — one new structural recognizer (`_is_schedule_enable_workflow_result()`, checking the tool-name pair `("schedule_enable", "schedule_verify_enabled_state")`); one new response-translation method (`_schedule_enable_workflow_result_to_response()`, mirroring `_update_focus_workflow_result_to_response()`'s shape exactly, with schedule-specific wording); the existing two-way dispatch in `execute_approved()` (and the equivalent dispatch reached via `_start_update_focus_workflow`'s own generic call path) extended to check the new recognizer before falling back to the generic `_workflow_result_to_response()`.
7. `main.py` — register `ScheduleVerifyEnabledStateTool` alongside the existing `ScheduleEnableTool`/`ScheduleDisableTool` registration, sharing the same already-constructed `ScheduleStore`.
8. `tools/builtin/help_tool.py`, `docs/user_guide.md` — truthful documentation of the new capability, mirroring the existing `project_state_update_focus` documentation pattern.

**Explicitly not changed:** `security/security_manager.py`, `tools/executor.py`, `approval/approval_manager.py`, `approval/pending_approval_store.py`, `workflow/engine.py`, `workflow/paused_workflow_store.py`, `core/command_router.py`, `tools/builtin/schedule_enable_tool.py` (the real write tool itself is reused completely unmodified).

---

## 14. Proposed Verifier Contract

- **Verifier strategy ID**: `"schedule_enabled_exact_match"`.
- **Trusted verifier tool**: `ScheduleVerifyEnabledStateTool` (new, internal-only), depending only on `ScheduleStore` (already-constructed, already-injected everywhere else this store is used).
- **Trusted verification inputs**: the write step's own already-durable `PlanStep.tool_input["schedule_id"]` (the exact integer the write step used - never re-derived, never model-supplied a second time) is threaded into the verify step's own `tool_input` (`{"schedule_id": <same int>}`) by the workflow-builder, exactly mirroring how the existing focus-update workflow's verify step needs no input at all (it reads the singleton project-state row) - here the verify step needs the id to know *which* schedule to re-read, but never anything else, and never anything model-selected at verification time.
- **Expected durable value**: `True` (fixed - enabling always expects the schedule to end up enabled; there is no model-supplied "expected" value, exactly as `verify_focus_update`'s `expected_value` comes from the write step's own already-validated input, never a second model output).
- **Actual durable value**: `verify_tool_result.metadata["enabled"]` (a real `bool`, read from `ScheduleStore.get(schedule_id)` at verify time).
- **Exact equality predicate**: `actual_enabled is True` (boolean identity, not a string comparison - the one deliberate shape difference from `verify_focus_update`'s string equality, since the underlying field is a `bool`, not a `str`).
- **Success outcome**: `VerificationOutcome.VERIFIED` when the verify step succeeded and `metadata["enabled"] is True`.
- **Mismatch outcome**: `VerificationOutcome.FAILED` when the verify step succeeded but `metadata["enabled"] is False` (the write appeared to succeed but the durable state disagrees - a genuine, real mismatch, never assumed).
- **Missing-record outcome**: if `ScheduleVerifyEnabledStateTool` cannot find the schedule at verify time (an internal-consistency anomaly, since the write step itself already required the schedule to exist), this is `VerificationOutcome.UNAVAILABLE` with an honest `detail`, exactly mirroring `verify_focus_update`'s own "no usable value" `UNAVAILABLE` case - never fabricated as a false `FAILED`.
- **Verifier-failure behavior**: if the verify step's own `ToolResult.success` is `False`, or it produced no usable `"enabled"` key, `VerificationOutcome.UNAVAILABLE` - identical shape to `verify_focus_update`'s existing `verify_tool_result is None or not verify_tool_result.success` branch.
- The model never selects the verifier, its inputs, the expected value, or the verification strategy - all four are fixed by the trusted `CapabilityAdapter.paired_verify_capability_id` entry and the workflow-builder's own deterministic construction, exactly as today.

---

## 15. Batch Breakdown

**Large/risky phase — three batches** (per Nathan's own milestone-sizing rule: "use more batches if approval, durable resume, idempotency, and verification changes are substantial" - this phase touches the shared workflow-builder and orchestrator dispatch that `PROJECT_STATE_UPDATE_FOCUS` already depends on, so the regression risk to existing, accepted behavior is real and must be proven, not assumed):

- **Batch 1 — Foundation generalization, zero new user-facing capability.** Add the `paired_verify_capability_id` field (defaulted `None` everywhere except the now-explicit `PROJECT_STATE_UPDATE_FOCUS` entry); generalize the workflow-builder to read it; add the new structural recognizer/response-translation method *shape* in the orchestrator but exercise it only through the existing focus-update workflow's own tests (no new capability selectable yet). Full regression proving `PROJECT_STATE_UPDATE_FOCUS`'s behavior (approval, resume, durable write, durable verification, all existing test assertions) is bit-for-bit unchanged. This isolates all shared-code risk into one reviewable batch before any new capability exists.
- **Batch 2 — Add `SCHEDULE_ENABLE` and `SCHEDULE_VERIFY_ENABLED_STATE`.** New tool, new verifier function, new catalog entries, new grounding signature, new numeric argument-attribution rule, full focused/grounding/planning/orchestration/approval/resume/verification tests for the new capability specifically.
- **Batch 3 — Full regression, documentation, and closure.** Complete-suite verification across all three required environments, Ruff on the full Git-derived diff, `docs/user_guide.md`/help-text updates, completion report, formal closure - mirroring the established Phase 90-93 closure pattern.

---

## 16. Test Strategy

1. **Capability catalogue schema** — `SCHEDULE_ENABLE`/`SCHEDULE_VERIFY_ENABLED_STATE` exist, declare the exact fields in §10, and `paired_verify_capability_id` is `None` for all pre-existing entries except `PROJECT_STATE_UPDATE_FOCUS`.
2. **Rejection of extra/wrongly-typed arguments** — non-`schedule_id` keys, non-int `schedule_id` (string, bool, float, null), missing `schedule_id`, all rejected by the existing, unmodified `structured_output.py` validator.
3. **Grounding signature uniqueness** — `"enable schedule 5"` uniquely grounds `SCHEDULE_ENABLE` against the full nine-signature catalogue (eight existing plus this one); no collision with `SCHEDULE_LIST`.
4. **Exact argument attribution** — the model's `schedule_id` must equal the integer following the request's own `" schedule "` marker; mismatched, missing, or multiple-marker requests refuse.
5. **Negation and ambiguity refusal** — `"do not enable schedule 5"` refuses via the existing, unmodified negation gate; a request naming two schedule ids refuses via the new marker-occurs-more-than-once rule.
6. **Real SecurityManager classification** — `"enable schedule"` still classifies YELLOW; the new verify tool's action still classifies GREEN.
7. **No execution before approval** — zero `ToolExecutor` calls, zero durable write, until a real `ApprovalManager` approval exists.
8. **Approval creation** — a real, durable `PendingApprovalStore` row is created for the write step, exactly like the existing focus-update workflow.
9. **Approval rejection and cancellation** — declining or invalidating the pending approval results in zero write, zero verification attempt, honest response.
10. **Restart-safe resume** — a durable, paused two-step plan (write + verify) survives a simulated process restart and resumes correctly, exactly mirroring `test_durable_restart_end_to_end` for the existing workflow.
11. **Exact ToolExecutor input** — the real `ToolRequest.input_data` is exactly `{"schedule_id": <int>}` for the write step and `{"schedule_id": <same int>}` for the verify step.
12. **Duplicate-execution prevention** — resuming an already-completed or already-approved workflow does not re-execute the write step a second time (reusing the existing, already-proven `WorkflowEngine` guarantee, re-tested against this new workflow shape specifically).
13. **Real durable write** — `ScheduleStore.get(schedule_id).enabled is True` after a real, approved, executed run, over a real in-memory SQLite store.
14. **Exact postcondition verification** — `VerificationOutcome.VERIFIED` when the real durable state matches.
15. **Verification mismatch** — a test double forcing `enabled is False` at verify time (mirroring the existing `_MismatchingVerifyTool` pattern) produces `VerificationOutcome.FAILED`, never a false success.
16. **Missing-target behavior** — a `schedule_id` that no longer exists at verify time (or never existed) produces an honest `UNAVAILABLE`/failure, never a crash or a false `VERIFIED`.
17. **Tool failure** — the write step's own tool failure (e.g. unknown `schedule_id` at write time) means the verify step never runs, mirroring `test_write_failure_means_verifier_never_runs`.
18. **Verifier failure** — the verify step itself failing (test double) produces `UNAVAILABLE`, never crashes the response path.
19. **Grounded final success response** — the real, durable enabled state and the real schedule's own identifying details are reflected honestly in the final message - never AI-paraphrased.
20. **Honest failure response** — mismatch/unavailable/rejection/tool-failure paths all produce `success=False` with an honest, non-technical message.
21. **No automatic retry or correction** — exactly one write attempt, exactly one verify attempt, per approved decision; no hidden re-execution anywhere.
22. **All existing eight capabilities unchanged** — full re-run of every Phase 90-93 focused test file, asserting zero regressions, with particular emphasis on every existing `PROJECT_STATE_UPDATE_FOCUS` test (approval, resume, write, verification) passing bit-for-bit unchanged after the Batch 1 generalization.
23. **Advisory path unchanged** — `ask jarvis:` remains advisory-only, unaffected.
24. **Deterministic commands unchanged** — `"enable schedule <id>"`/`"disable schedule <id>"` and all other `CommandRouter` grammar remain byte-for-byte unchanged.
25. **Complete-suite verification without live API credits** — full suite, normal environment, `AI_REASONING_ENABLED=false`, and `PYTHON_DOTENV_DISABLED=1`, all zero-failure, using only the existing fake-provider/deterministic test infrastructure - no live Anthropic call anywhere.

---

## 17. Acceptance Criteria

Phase 94 may be closed only when: `SCHEDULE_ENABLE` executes end-to-end (grounding → preflight → approval → durable write → durable verification → grounded response) using only real, unmodified `SecurityManager`/`ToolExecutor`/`ApprovalManager`/`WorkflowEngine` components plus the new, narrow verify tool and verifier function; `PROJECT_STATE_UPDATE_FOCUS`'s own existing behavior is proven bit-for-bit unchanged after the shared-code generalization; the new grounding signature is collision-free against all eight pre-existing signatures; the new numeric argument-attribution rule rejects every mismatch/ambiguity case exactly like the existing string rules; no `SecurityManager` rule changed; documentation is truthful; and the complete three-environment full-suite verification passes with zero failures.

---

## 18. Risks and Mitigations

- **Risk**: generalizing the shared workflow-builder/orchestrator dispatch could silently change `PROJECT_STATE_UPDATE_FOCUS`'s own behavior. **Mitigation**: Batch 1 isolates this exact risk into its own reviewable unit, with a full, explicit regression pass before any new capability is even added.
- **Risk**: the new numeric argument-attribution rule could be under- or over-strict in a way not anticipated here. **Mitigation**: Batch 2's own design work must re-derive, and this document does not presume to finalize, the exact non-numeric/ambiguous-span reason code and boundary rules - flagged as a Batch 2 design decision, not assumed settled by this planning gate.
- **Risk**: a second `TWO_STEP_WORKFLOW` capability could reveal the current two-branch orchestrator dispatch does not generalize as cleanly as this plan expects once actually written. **Mitigation**: explicit stop condition (§19) requires stopping and reporting if this proves true, rather than forcing an awkward workaround.
- **Risk**: `SCHEDULE_DISABLE` deferral could be seen as leaving the phase's own strategic question ("enable vs. disable, or both") unresolved. **Mitigation**: the deferral is explicit and the follow-up cost is explicitly documented as near-zero, reusing every piece of new architecture unchanged.

---

## 19. Stop Conditions

- Stop and report before Batch 2 if Batch 1's generalization of the workflow-builder/orchestrator dispatch cannot be made to preserve `PROJECT_STATE_UPDATE_FOCUS`'s existing behavior exactly, as proven by its own existing test suite passing unmodified.
- Stop and report if the real `"enable schedule"` action is found, at implementation time, to classify anything other than YELLOW.
- Stop and report if `ScheduleStore.get()` is found to not provide an exact, read-only, side-effect-free way to check `enabled` state.
- Stop and report if the new numeric argument-attribution rule is found to require anything beyond a single fixed marker, single-occurrence, all-digits rule - never expand into general numeric or natural-language parsing.
- Stop and report if any part of this design is found to require a probabilistic, learned, or similarity-scored judgment of any kind.
- Stop after Batch 3's closure report. Do not begin Phase 95, `SCHEDULE_DISABLE`, or any other unrelated work without Nathan's explicit approval.

---

## 20. Manual API Limitation

Live Anthropic manual acceptance remains **postponed** because the configured API account lacks sufficient credits. This is an external account limitation, not a Jarvis code failure. No production behavior will be changed to bypass it. Phase 94, like Phases 90-93 before it, must remain fully verifiable through deterministic, fake-provider, and full-suite tests - never through a claimed live-model acceptance run.

---

## 21. Batch 1 Implementation Evidence

**Status: Batch 1 complete and committed. Phase 94 remains open - Batch 2 (adding SCHEDULE_ENABLE itself) has not been started.**

### 21.1 Schedule-ID viability checkpoint (performed before any code change)

All eight mandatory items were directly re-confirmed from live production code, not assumed:

1. **Canonical target**: `ScheduleEnableTool.run()` (`tools/builtin/schedule_enable_tool.py`) reads `request.input_data.get("schedule_id")` and calls `self._schedules.enable(schedule_id)` - `schedule_id` is the tool's one and only targeting field.
2. **Real durable stored identifier**: `ScheduleRecord.id` is the primary key of `storage.models.ScheduleEntry`, a normal SQLAlchemy ORM table (`storage/models.py` line 480) - not a list position or any ephemeral value.
3. **Restart-stable**: `ScheduleEntry` uses the exact same durable SQLite persistence mechanism as every other store in the repository (`ApprovalHistoryEntry`, `WorkflowHistoryEntry`, `ProjectStateStore`'s own table, etc.) - a database primary key survives a process restart by construction.
4. **Unique**: primary-key semantics guarantee uniqueness by definition; `ScheduleStore.get()`/`.enable()`/`.disable()` all resolve via `db.get(ScheduleEntry, schedule_id)`, SQLAlchemy's own primary-key lookup.
5. **User-obtainable today**: via the existing, real, deterministic `"show my schedules"`/`"list schedules"` command (`ScheduleListTool`, GREEN) - already reachable both deterministically and through the existing `SCHEDULE_LIST` Intelligence Core capability.
6. **Clearly labelled**: `ScheduleListTool._format_entry()` renders each row as `"  [{record.id}]{label} '{query}' at {time} daily - {state}, last run: {last_run}"` - the bracketed `[id]` prefix exactly mirrors the established `[id]` convention already used by `WorkflowHistoryTool`/`ApprovalHistoryTool`.
7. **`ScheduleStore.get(schedule_id)` consistency**: re-confirmed directly - `get()`, `enable()`, and `disable()` all call `db.get(ScheduleEntry, schedule_id)` against the identical table; `get()` is the exact same durable record `enable()` mutates.
8. **YELLOW classification, no rule change**: `ScheduleEnableTool.action_for()` returns the fixed string `"enable schedule"`, which matches the existing, unmodified `security_manager.py` rule (line 223: `_Rule("enable schedule", SecurityTier.YELLOW, ...)`) - re-confirmed live via a direct `SecurityManager().classify_action("enable schedule")` call during this batch, returning `SecurityTier.YELLOW`.

**All eight items passed. No schedule-list behavior was added or changed to manufacture viability - `tools/builtin/schedule_list_tool.py`, `tools/builtin/schedule_enable_tool.py`, `tools/builtin/schedule_disable_tool.py`, and `scheduling/schedule_store.py` were read only, never modified, in this batch.**

### 21.2 Exact hardcoded workflow limitations found before the change

Two, and only two, hardcoded pieces prevented a second `TWO_STEP_WORKFLOW` capability from being added later:

1. `intelligence/planning.py::_build_update_focus_workflow_plan()` (line 550, pre-Batch-1): `verify_adapter = catalog.get(CapabilityId.PROJECT_STATE_VERIFY_FOCUS)` - a literal `CapabilityId` reference inside the function body, not derived from `write_adapter` at all. A second `TWO_STEP_WORKFLOW` capability would have silently been paired with `PROJECT_STATE_VERIFY_FOCUS` too - an actual correctness defect, not merely a style issue.
2. `core/orchestrator.py::JarvisOrchestrator._is_update_focus_workflow_result()` (pre-Batch-1): two bare string literals, `"project_state_update"` and `"project_state_verify"`, hardcoded inside the method body, duplicating information the catalog already owns.

Every other piece of the approval/workflow/resume architecture was re-confirmed, by direct `grep -in "project_state\|focus"` producing **zero matches**, to already be fully generic: `approval/approval_manager.py`, `approval/pending_approval_store.py`, `workflow/engine.py`, `workflow/paused_workflow_store.py`. None of these four files needed, or received, any change.

### 21.3 Exact trusted foundation architecture implemented

- **`intelligence/capability_catalog.py`**: one new field on the existing, frozen `CapabilityAdapter` dataclass - `paired_verify_capability_id: CapabilityId | None = None`. Defaults to `None`, so all eight capabilities defined before this batch need no change; only `PROJECT_STATE_UPDATE_FOCUS`'s own entry now explicitly sets `paired_verify_capability_id=CapabilityId.PROJECT_STATE_VERIFY_FOCUS`.
- **`intelligence/planning.py`**: `_build_update_focus_workflow_plan()` renamed to `_build_write_and_verify_workflow_plan()` (matching this plan's own §13 anticipation); its one hardcoded literal replaced with `write_adapter.paired_verify_capability_id`, with an added explicit `None`-guard returning the same pre-existing honest failure string (`"the internal verification capability is not configured"`) when a write adapter has no paired verifier configured, or the named verifier is absent from the supplied catalog.
- **`core/orchestrator.py`**: one new import (`from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId`); `_is_update_focus_workflow_result()` rewritten to derive its expected `(write_tool_name, verify_tool_name)` pair from `CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]` and its `paired_verify_capability_id`, instead of two literal strings. The method's own dispatch in `execute_approved()` is unchanged (still a single named check, since no second capability of this shape exists yet); `_update_focus_workflow_result_to_response()` is completely unmodified (still the correct, only-needed response translator for the one existing workflow).

No dataclass, enum, mapping, or function name outside this exact set was introduced. No workflow-definition field of any kind is exposed to the model - `paired_verify_capability_id` is read only from the trusted, static `CapabilityAdapter`, never from parsed model output, `arguments`, or `tool_input` (directly proven: `test_workflow_builder_ignores_tool_input_contents_when_selecting_the_verifier`).

### 21.4 Exact production configuration representing PROJECT_STATE_UPDATE_FOCUS

```python
CapabilityId.PROJECT_STATE_UPDATE_FOCUS: CapabilityAdapter(
    ...,
    verification_strategy_id="project_state_focus_exact_match",
    internal_only=False,
    paired_verify_capability_id=CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
),
```

This is the only catalog entry touched. All eight other entries are byte-for-byte unchanged (re-confirmed: `git diff` shows no line changed inside any other `CapabilityAdapter(...)` construction).

### 21.5 Persistence-schema impact

**None.** `planner/plan_models.py`, `workflow/paused_workflow_store.py`, `approval/pending_approval_store.py`, and `storage/models.py` were not modified at all in this batch (confirmed: absent from `git status --short`'s changed-file list). No persisted approval or paused-workflow row's shape changed in any way.

### 21.6 Backward-compatibility evidence

Because no persistence-affecting file changed, every previously-persisted `PROJECT_STATE_UPDATE_FOCUS` paused-workflow row remains resumable exactly as before, with zero migration of any kind required - re-confirmed behaviorally by `test_durable_restart_end_to_end` (in `tests/unit/test_orchestrator_update_focus_workflow.py`) passing unmodified, which exercises a real durable pause/restart/resume cycle end-to-end over a real SQLite session factory.

### 21.7 Approval lifecycle preservation

Re-confirmed via the full, unmodified existing test suite in `test_orchestrator_update_focus_workflow.py`: exactly one approval created (`test_initial_request_creates_a_real_pending_approval`), zero execution before approval (`test_update_focus_cannot_execute_without_approval`), zero verification while pending (`test_verifier_does_not_execute_while_pending`), decline performs zero writes (`test_decline_executes_zero_writes`), no fabricated approval from intelligence code (`test_no_fabricated_approval_is_ever_created_by_intelligence_code`) - all passing bit-for-bit unchanged after the generalization.

### 21.8 Resume and duplicate-execution preservation

`test_durable_restart_end_to_end` (pre-existing, unmodified) proves restart-safe resume continues to work. Two new tests added this batch: `test_duplicate_resume_does_not_duplicate_the_write` (a second `execute_approved()` call for an already-executed response/decision performs zero additional writes - the real, unmodified `_paused_workflow_id_for()` finds no still-paused workflow the second time and falls through to the existing, honest "no runnable tool for this action" response, never a second `resume()` or direct `ToolExecutor.execute()` call) and `test_approved_arguments_are_immutable_between_approval_and_execution` (mutating the fake AI provider's own future output after approval has zero effect on the already-durable, already-approved value that actually executes).

### 21.9 Execution-input preservation

`test_real_update_focus_workflow_still_builds_the_exact_existing_plan` (new) directly re-confirms `_build_write_and_verify_workflow_plan()` still produces `plan.steps[0].tool_name == "project_state_update"` and `plan.steps[0].tool_input == {"field": "focus", "value": <exact value>}` for the real capability - unchanged from before this batch.

### 21.10 Verification-input and postcondition preservation

Same test confirms `plan.steps[1].tool_name == "project_state_verify"` and `plan.steps[1].tool_input == {}` - unchanged. `intelligence/verification.py` itself was not modified at all (confirmed: absent from the changed-file list); `test_no_new_verification_function_exists_in_verification_module` (new) confirms the module still defines exactly one function, `verify_focus_update`.

### 21.11 Public-response preservation

`test_approved_verified_response_is_grounded_in_real_values`, `test_exact_mismatch_reports_failed_verification`, `test_write_failure_means_verifier_never_runs`, `test_declined_response_says_no_update_was_made`, and every other pre-existing response-shape test in `test_orchestrator_update_focus_workflow.py` pass unmodified - the exact success/mismatch/missing-state/tool-failure/verifier-failure wording is untouched, since `_update_focus_workflow_result_to_response()` itself was never edited.

### 21.12 Anti-overgeneralization evidence

- `test_only_one_two_step_workflow_capability_exists_in_the_real_catalog` - `PROJECT_STATE_UPDATE_FOCUS` remains the sole `TWO_STEP_WORKFLOW` entry in the real `CAPABILITY_CATALOG`.
- `test_no_schedule_enable_capability_exists_yet` - the real `CapabilityId` enum still contains exactly the same nine members Phase 93 left it with; no member name contains `"SCHEDULE_ENABLE"`.
- `test_no_schedule_verifier_strategy_id_exists_yet` - the only non-`None` `verification_strategy_id` anywhere in the catalog is still `"project_state_focus_exact_match"`.
- `test_no_new_verification_function_exists_in_verification_module` - exactly one verifier function exists.
- `test_workflow_builder_never_calls_forbidden_execution_or_ai_apis` (AST-based, docstring-excluded) - the generalized workflow-builder calls no `ToolExecutor`, `WorkflowEngine`, `ApprovalManager`, AI provider, or `.run()`.
- `test_workflow_builder_signature_accepts_no_model_output_parameter` - the function's exact parameter set contains only trusted, already-resolved values.
- `test_capability_adapter_field_is_never_exposed_as_a_model_facing_argument` - `paired_verify_capability_id` never appears as a declared `CapabilityArgumentSpec` name for any capability.
- The test-local write/verify capability pairing used to prove genericity (`_test_local_write_and_verify_catalog()` in `tests/unit/test_trusted_workflow_foundation.py`) reuses two existing `CapabilityId` enum values purely as local dict keys; it is never assigned to, or merged into, the real `CAPABILITY_CATALOG` module object, is never registered in `main.py`, and adds no real user-facing capability - satisfying this batch's own explicit test-local-specification allowance.

### 21.13 Confirmation no SCHEDULE_ENABLE capability or schedule verifier was added

Confirmed by §21.12's own tests, by `git diff`/`git status` showing no change to `main.py`, `tools/builtin/help_tool.py`, or `docs/user_guide.md`, and by direct inspection: no `schedule_verify_enabled_state_tool.py` or equivalent file was created; no `SCHEDULE_ENABLE`/`SCHEDULE_VERIFY_ENABLED_STATE` `CapabilityId` member exists; no new grounding signature was added to `intelligence/grounding.py` (confirmed unmodified - absent from the changed-file list).

### 21.14 Verification results

- Focused (`test_trusted_workflow_foundation.py` (new, 17 tests), `test_capability_catalog.py`, `test_structured_output.py`, `test_grounding.py`, `test_intelligence_planning.py`, `test_orchestrator_ask_jarvis_to.py`, `test_orchestrator_update_focus_workflow.py`, `test_verification.py`, run together): **424 passed**.
- Approval/workflow/executor/project-state regression sweep (approval manager/history/audit/models/prompt, CLI/core approval, pending approval store, tool executor approval + logger isolation, project-state show/store/update/verify tools): **301 passed**.
- Phase 91-93 capability regression + command-router/help sweep (health-check tool + wiring, pending-approval wiring, project-state wiring, quarantine-list wiring, memory tool, orchestrator context-query/workflow-commands, approval-history/workflow-history store/tool/CLI, command router, help tool): **848 passed**.
- Full suite, normal environment: **4864 passed, 3 skipped** (21 more than Phase 93's closing baseline of 4843 - exactly the 21 new tests added this batch).
- Full suite, `AI_REASONING_ENABLED=false`: **4864 passed, 3 skipped** - identical.
- Full suite, `PYTHON_DOTENV_DISABLED=1`: **4864 passed, 3 skipped** - identical.
- Ruff, Git-derived file set (tracked diff against HEAD plus the one new untracked file): exactly **6 files** - `core/orchestrator.py`, `intelligence/capability_catalog.py`, `intelligence/planning.py`, `tests/unit/test_capability_catalog.py`, `tests/unit/test_orchestrator_update_focus_workflow.py`, `tests/unit/test_trusted_workflow_foundation.py`. `ruff check` on all 6: **all checks passed, exit code 0, zero findings** (no new, no pre-existing).
- `git diff --check`: exit code 0 (tracked changes plus the new file, checked via `git add -N`). Only pre-existing `LF will be replaced by CRLF` advisory notices, never a whitespace error.

### 21.15 Scope confirmation

No `SecurityManager` rule or tier was changed (re-confirmed: `security/security_manager.py` absent from the changed-file list). No new write path was introduced - the one and only executable write remains `PROJECT_STATE_UPDATE_FOCUS`'s own, pre-existing `project_state_update` tool call. No retry, replanning, or autonomous behavior exists anywhere in the new code. `docs/user_guide.md` and `tools/builtin/help_tool.py` were not touched. `docs/phase_94_completion_report.md` was not created. Phase 94 remains open; Batch 2 (adding `SCHEDULE_ENABLE` itself) and Phase 95 were not started.

---

## 22. Batch 2 implementation and verification evidence (as actually built)

### 22.1 What was added

Exactly one new user-facing capability, `SCHEDULE_ENABLE`, and its paired internal-only verifier, `SCHEDULE_VERIFY_ENABLED_STATE`, added to the real `CAPABILITY_CATALOG` alongside the existing nine entries (ten total; nine model-selectable, one internal-only). `SCHEDULE_ENABLE` is classified `TWO_STEP_WORKFLOW`, YELLOW, one required integer argument `schedule_id` (`CapabilityArgumentSpec(name="schedule_id", type_name="int", required=True)`), `verification_strategy_id="schedule_enabled_exact_match"`, `paired_verify_capability_id=CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE`, `paired_verify_input_keys=("schedule_id",)`. `SCHEDULE_VERIFY_ENABLED_STATE` is `internal_only=True`, GREEN, zero grounding signature, never model-selectable.

### 22.2 Numeric argument-attribution mechanism

`intelligence/grounding.py` gained a second, numeric argument-extraction path (`_extract_numeric_argument_span()`, marker `" schedule "`, exact-integer-equality check, no sign guessing, no coercion) alongside the pre-existing string-span extractor, dispatched from `ground_decision()`'s existing tail based on which extractor a capability's own trusted config declares it needs. Non-numeric, multi-token, multi-marker, and zero-marker cases all fall back to the same, pre-existing `AMBIGUOUS_ARGUMENT_SPAN` reason - no 8th reason was added, matching the plan's own explicit design allowance (§14).

### 22.3 `paired_verify_input_keys` - a small, necessary addition beyond the original plan wording

The original accepted plan (§10/§14) anticipated that the verify step would need to know which schedule to re-read, but did not name the implementation mechanism. Building `_build_write_and_verify_workflow_plan()`'s generalized version against a second real workflow surfaced the gap directly (`test_schedule_enable_workflow_plan_step_2_input_is_the_same_schedule_id` initially failed with `{} == {'schedule_id': 5}`). The fix: a new, generic, trusted, static `CapabilityAdapter.paired_verify_input_keys: tuple[str, ...] = ()` field, naming which keys to copy verbatim from the write step's own already-validated `tool_input` into the verify step's `tool_input`. Empty for `PROJECT_STATE_UPDATE_FOCUS` (unchanged behavior - verified by `test_real_update_focus_workflow_still_builds_the_exact_existing_plan` passing bit-for-bit), `("schedule_id",)` for `SCHEDULE_ENABLE`. Not schedule-specific, not hardcoded to any one capability, consistent with the plan's own stated intent.

### 22.4 Orchestrator response-translation generalization

A latent gap in `_start_update_focus_workflow`'s own final line (`return self._update_focus_workflow_result_to_response(result)` - hardcoded, never actually generalized in Batch 1 despite `execute_approved()`'s resume path being generalized) was found and fixed: both call sites now share one `_translate_verified_workflow_result()` method, matching the plan's own explicit anticipation (§9) that both dispatch points would need updating. `_is_update_focus_workflow_result`/new `_is_schedule_enable_workflow_result` both delegate to one private static helper, `_matches_two_step_workflow_shape(result, write_capability_id)`, parameterized only by the capability id to check - never a generic/pluggable dispatch table.

### 22.5 Tool registration

`ScheduleVerifyEnabledStateTool` registered in `main.py` immediately after the existing schedule tools, sharing the same `ScheduleStore` instance as `ScheduleEnableTool`/`ScheduleListTool` - confirmed by `test_schedule_verify_enabled_state_tool.py` and the coexistence/workflow tests reading back real store state after execution.

### 22.6 Test coverage added this batch

- `tests/unit/test_capability_catalog.py` - catalogue-shape tests for the two new adapters, `paired_verify_input_keys`/`paired_verify_capability_id` defaults, ten-entry/nine-model-selectable counts.
- `tests/unit/test_structured_output.py` - "Phase 94, Batch 2" section: valid selection, boundary integers (negative/zero/large), explicit rejection of missing/null/bool/string/float/array/object for `schedule_id` (bool rejected via the existing, unmodified generic `isinstance(value, bool)` branch in `_validate_arguments()` - zero new production code needed for this case), extra-argument rejection, internal-only flag enforcement.
- `tests/unit/test_grounding.py` - "Section 14": real phrasing, exact numeric extraction, wrong-id/missing/multiple-marker/multiple-candidate/ambiguous-trailing-text/negation/conflicting-request/action-without-domain/domain-without-action refusals, catalogue-wide non-collision (including against `SCHEDULE_LIST`), internal verifier absent from all signatures, unsupported-synonym rejection (activate/turn on/start/resume/switch on/reactivate/allow all refused).
- `tests/unit/test_intelligence_planning.py` - `select_tool()`-level integration: two-step workflow shape/order, exact step 1/step 2 `tool_input` (including the `paired_verify_input_keys` merge), tiers, capability mismatch, wrong id, adversarial context, stray argument, bool rejection.
- `tests/unit/test_trusted_workflow_foundation.py` - updated to reflect the legitimate two-workflow/eleven-entry/two-verifier-function state; new `test_schedule_enable_recognizer_also_delegates_to_the_shared_helper` (required extending the shared AST helper to also collect `ast.Attribute.attr`, not just `ast.Name.id`, since `JarvisOrchestrator._matches_two_step_workflow_shape(...)` parses as an attribute access).
- `tests/unit/test_schedule_verify_enabled_state_tool.py` (new, 18 tests) - isolated tool-contract tests mirroring `test_project_state_verify_tool.py`.
- `tests/unit/test_orchestrator_schedule_enable_workflow.py` (new, 31 tests) - full end-to-end orchestration: approval lifecycle (no execution before approval, exactly one pending approval, store unchanged while pending, decline performs zero writes, no fabricated approval), durable restart/resume, verification (exact mismatch, write failure skips verification, missing-schedule-at-execution honest failure, schedule-disappears-before-verification honest failure via a narrow test-double verifier, verifier-tool-failure honest reporting, already-enabled-schedule preserves the real tool's existing unconditional-success behavior), response/trace grounding (no raw dictionaries, no second AI call, ≤200-char trace entries), routing regressions (`ask jarvis:` advisory and the deterministic `show schedules` command both unaffected), structural checks (planning module never touches `ScheduleStore` directly, response translator never bypasses `WorkflowEngine`), Phase 92 zero-side-effect grounding refusals (wrong id, negation, capability mismatch), duplicate-resume/argument-immutability, and a coexistence test proving `PROJECT_STATE_UPDATE_FOCUS` and `SCHEDULE_ENABLE` dispatch correctly through one shared orchestrator/registry/executor/approvals/workflow-engine instance without cross-talk.

### 22.7 Regression preservation

`PROJECT_STATE_UPDATE_FOCUS` behavior is bit-for-bit unchanged: `intelligence/verification.py`'s `verify_focus_update()` was not modified (only a new, separate `verify_schedule_enabled_state()` function was added); `_build_write_and_verify_workflow_plan()`'s output for the focus capability is unchanged (`paired_verify_input_keys=()` means no merge occurs); every pre-existing test in `test_orchestrator_update_focus_workflow.py` (including Batch 1's `test_duplicate_resume_does_not_duplicate_the_write` and `test_approved_arguments_are_immutable_between_approval_and_execution`) passes unmodified. The new coexistence test additionally proves both workflows can run back-to-back on one real orchestrator instance without dispatch ambiguity.

### 22.8 Verification results

- Focused (all files touched this batch, run together - `test_capability_catalog.py`, `test_trusted_workflow_foundation.py`, `test_verification.py`, `test_structured_output.py`, `test_grounding.py`, `test_intelligence_planning.py`, `test_orchestrator_update_focus_workflow.py`, `test_orchestrator_schedule_enable_workflow.py`, `test_schedule_verify_enabled_state_tool.py`, `test_help_tool.py`, `test_command_router.py`): **1028 passed**.
- Full suite, normal environment: **4981 passed, 3 skipped**.
- Full suite, `AI_REASONING_ENABLED=false`: **4981 passed, 3 skipped** - identical.
- Full suite, `PYTHON_DOTENV_DISABLED=1`: **4981 passed, 3 skipped** - identical.
- Ruff, Git-derived file set (`git diff --name-only 5a05044 -- '*.py'` plus untracked new `.py` files): exactly **17 files** - `core/orchestrator.py`, `intelligence/capability_catalog.py`, `intelligence/grounding.py`, `intelligence/planning.py`, `intelligence/verification.py`, `main.py`, `tests/unit/test_capability_catalog.py`, `tests/unit/test_grounding.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_structured_output.py`, `tests/unit/test_trusted_workflow_foundation.py`, `tests/unit/test_verification.py`, `tools/builtin/__init__.py`, `tools/builtin/help_tool.py`, `tests/unit/test_orchestrator_schedule_enable_workflow.py`, `tests/unit/test_schedule_verify_enabled_state_tool.py`, `tools/builtin/schedule_verify_enabled_state_tool.py`. `ruff check` on all 17: **all checks passed, exit code 0, zero findings**.
- `git diff --check`: exit code 0 for both the working tree and the staged diff. Only pre-existing `LF will be replaced by CRLF` advisory notices, never a whitespace error.

### 22.9 Scope confirmation

No `SCHEDULE_DISABLE`/`SCHEDULE_CREATE` capability, no schedule update/delete/name-targeting/search capability, no model-selectable expected-verification-state, no generic verifier registry, no arbitrary workflow steps, no retries/replanning/rollback, and no `SecurityManager` rule or tier change were added (`enable schedule` continues to classify YELLOW via its existing, unchanged rule; the verifier's own `list schedules` action continues to classify GREEN via its existing, unchanged rule). `docs/phase_94_completion_report.md` was not created. Phase 94 is not marked closed - Batch 3 (full regression/docs/closure) has not started, and Phase 95 has not started.
