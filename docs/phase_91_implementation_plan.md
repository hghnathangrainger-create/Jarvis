# Jarvis — Phase 91 Implementation Plan

**Status:** Batches 1 and 2 implemented and verified. Phase 91 is **implementation-complete**, pending Nathan's review and the still-postponed manual Anthropic API acceptance test (an external API-credit limitation, not a production-code failure) — not independently marked as closed.
**Version:** Phase 91 — Safe Intelligence Capability Expansion (medium milestone: planning gate + 2 batches)
**Date:** 2026-07-20 (planning gate); Batch 1 implemented 2026-07-20; Batch 2 implemented 2026-07-20

---

## 1. Verified Current Repository Baseline

Directly verified via `git branch --show-current`, `git log --oneline -8`, `git status --short`, and `poetry run pytest -q`:

```
Branch:      phase-4-ai-reasoning-and-write-actions
HEAD:        84c3f06  Add Phase 90 closure docs: Continuation Kit and completion report
             7af43c1  Add Phase 90 Batch 3: Safe YELLOW Execution, Durable Approval, Exact Verification, and Grounded Recovery
             0b62595  Add Phase 90 Batch 2: Planning and Safe GREEN Tool Selection
             8ba73de  Add Phase 90 Section 26: Batch 2 final safety gate
Full suite:  4607 passed, 3 skipped, 0 failed
git status:  ?? dashboard_test.txt   (only entry)
```

No discrepancy found against the Continuation Kit's own recorded baseline. `dashboard_test.txt` was not opened, read, or interacted with — only observed in `git status --short` output, per the standing constraint. The Phase 90 manual AI acceptance test remains postponed for account-credit reasons unrelated to code correctness; this plan does not depend on it.

---

## 2. Phase 90 Behavior That Must Remain Unchanged

- `ask jarvis: <request>` remains advisory-only, forever: no tool selection, no execution, no approval, no writes.
- `ask jarvis to: <request>` remains the only tool-selection/execution command; Phase 91 adds no new user-facing command or grammar.
- `project_state_show` (GREEN) and `project_state_update_focus` (YELLOW, two-step workflow with approval and exact verification) keep their exact existing behavior, unmodified.
- `project_state_verify_focus` remains internal-only, never model-selectable, never a user command.
- `CAPABILITY_CATALOG` remains the sole intelligence-layer allowlist, independent of `ToolRegistry` — a registered tool absent from the catalog stays unselectable.
- The strict three-key `{decision, capability_id, arguments}` schema, the 2000-char cap, duplicate-key rejection, single-fence leniency, and generic string-argument hygiene all remain exactly as Batch 2/3 built them.
- `SecurityManager` remains the sole classification authority; `ToolExecutor` remains the sole execution chokepoint; no direct `tool.run()` calls anywhere in the intelligence layer.
- Zero retries, zero replans, zero automatic memory writes, zero new persistence tables.

---

## 3. Candidate GREEN Read-Only Tools Inspected

Every already-registered, already-tested GREEN tool with no write path was read in full (`action_for()`, `run()`, and `main.py` wiring) to assess real fit:

| Tool | `action_for()` result(s) | Real tier (confirmed) | Input shape | Notes |
|---|---|---|---|---|
| `health_check` | fixed `"show system health"` | GREEN | none | Zero-argument, no internal operation switch. |
| `schedule_list` | fixed `"list schedules"` | GREEN | none | Zero-argument, no internal operation switch. |
| `quarantine_list` | fixed `"list quarantine"` | GREEN | none | Zero-argument, no internal operation switch. |
| `info` | fixed `"show system information"` | GREEN | none | Zero-argument; static app identity only — marginal daily value. |
| `memory` | varies by `operation`: `"list memories"`, `"search memories"`, `"save memory"`, `"show memory"`, `"show memory categories"` | GREEN (all) | `operation` switch + optional `query`/`category`/`content` | Multi-operation; a fixed-operation injection is required to expose only a read operation safely (`"save"` must never be reachable via AI selection). |
| `workflow_history` | varies by `operation`: `"show workflow history"`, `"show recent workflows"`, `"show workflow details"` | GREEN (all) | `operation` switch + optional `workflow_id` | Multi-operation; would need the same fixed-operation treatment. |
| `approval_history` | varies by `operation`: `"show approval history"`, `"show recent approvals"`, `"show approved actions"`, `"show declined actions"`, `"show approval details"` | GREEN (all) | `operation` switch + optional `request_id` | Multi-operation, five branches — largest ambiguity surface of any candidate. |
| `file_search` | fixed `"search files"` | GREEN | `mode` (enum), `query` (required str), `path` (optional, defaults to `"."`), `limit` | Searches an arbitrary filesystem path, not bounded to the repository — real risk of exposing data too broadly if the AI is allowed to name any `path`. |
| `file_list` | fixed `"list files in directory"` | GREEN | `path` (required str) | Same arbitrary-path exposure risk as `file_search`, with no default scoping. |

`ToolRegistry` confirms every tool above is already registered in `main.py` with all its dependencies wired — no new construction or wiring is needed for any candidate.

---

## 4. Candidate Ranking Table

Scored against: daily usefulness, safety, argument-schema simplicity, deterministic validation, existing test coverage, existing `ToolExecutor` compatibility, risk of ambiguity, risk of exposing data too broadly. (`+` favorable, `-` unfavorable.)

| Candidate | Usefulness | Safety | Schema simplicity | Ambiguity risk | Data-exposure risk | Existing tests | Verdict |
|---|---|---|---|---|---|---|---|
| `health_check` | + high | + | + zero-arg, no switch | + none | + none | `test_health_check_tool.py`, `test_main_health_check_wiring.py` | **Select — Batch 1** |
| `schedule_list` | + high | + | + zero-arg, no switch | + none | + none | `test_schedule_tools.py` | **Select — Batch 1** |
| `memory` (list) | + high | + | + zero-arg, needs fixed-operation injection | + low (operation fixed, never model-chosen) | + low (only recent memories, same as existing `list_recent` limit) | `test_memory_tool.py` | **Select — Batch 1** |
| `memory` (search) | + high | + | bounded 1 required string arg | + low (operation fixed; query hygiene already generic) | + low (same data as `memory` list, just filtered) | `test_memory_tool.py` | **Select — Batch 2** |
| `quarantine_list` | moderate | + | + zero-arg, no switch | + none | + low | `test_quarantine_list_tool.py` | Deferred (see §6) |
| `workflow_history` | moderate | + | zero-arg needs fixed-operation injection | low | low | `test_workflow_history_tool.py` | Deferred (see §6) |
| `approval_history` | moderate | + | zero-arg needs fixed-operation injection; 5-way branch | moderate (widest operation surface) | low | `test_approval_history_tool.py` | Deferred (see §6) |
| `info` | low | + | + zero-arg | + none | + none | (covered incidentally by CLI tests) | Deferred (see §6) |
| `file_search` | high | - real risk | required `mode` enum + string, optional `path` | moderate | **high** — unbounded path | `test_file_search_tool.py` | Deferred (see §6) |
| `file_list` | high | - real risk | required `path` string | moderate | **high** — unbounded path | `test_file_list_tool.py` | Deferred (see §6) |

---

## 5. Selected Phase 91 Capabilities

**Batch 1 (zero-argument, GREEN, `SINGLE_TOOL`):**
1. `HEALTH_CHECK` → `health_check` tool.
2. `SCHEDULE_LIST` → `schedule_list` tool.
3. `MEMORY_LIST_RECENT` → `memory` tool, fixed `operation="list"`.

**Batch 2 (bounded, argument-taking, GREEN, `SINGLE_TOOL`) — only if Batch 1 closes cleanly and this batch's own preflight/argument-validation tests confirm it is safe:**
4. `MEMORY_SEARCH` → `memory` tool, fixed `operation="search"`, one required string argument `value` → `query`.

All four reuse `ExecutionStrategy.SINGLE_TOOL` — the exact same strategy `project_state_show` already uses. Direct code inspection (§9) confirms `intelligence/planning.py::select_tool()`'s existing `SINGLE_TOOL` branch and `core/orchestrator.py::_handle_ask_jarvis_to_request()`'s existing `EXECUTABLE` branch already handle any `SINGLE_TOOL` capability generically — **neither file's control flow needs to change** for Phase 91.

---

## 6. Rejected or Deferred Capabilities, With Reasons

- **`quarantine_list`, `workflow_history`, `approval_history`** — deferred, not rejected as unsafe. All three are genuinely GREEN and read-only. Deferred purely to keep this milestone conservative (a small, well-tested expansion rather than exposing every audit-style GREEN tool at once). `workflow_history`/`approval_history` also carry a wider operation-branching surface (3 and 5 operations respectively) than any Batch 1/2 capability, which would mean more structural tests to prove the AI can never reach `"get"`. Good candidates for a future, narrowly-scoped Phase.
- **`info`** — deferred. Real, safe, zero-argument, but its content (static app name/version/description) offers materially less daily value than `project_state_show` already provides; not worth a catalog slot in a conservative expansion.
- **`file_search` / `file_list`** — deferred, and flagged as a genuine safety question rather than a simple staging choice. Both accept an arbitrary filesystem `path` with no repository- or workspace-scoping; letting the AI choose an unrestricted `path` risks exposing directories well beyond the project (this machine's user profile, other drives, etc.). Exposing either safely would require a new, bounded design (e.g., a fixed or allowlisted root, or omitting `path` entirely and hardcoding the repository root) that does not exist today — out of scope for Phase 91 without a dedicated design pass and its own planning-gate scrutiny.
- **`memory` `"save"`/`"get"`/`"categories"` operations** — rejected for AI selection. Phase 91 is GREEN-and-read-only by explicit constraint; even though `"save memory"` itself classifies GREEN, exposing a write operation (`"save"`) through the intelligence layer is a new write capability, explicitly out of scope. `"get"`/`"categories"` are simply not selected because `"list"`/`"search"` already cover the daily-usefulness case with the simplest possible arguments; they remain unreachable because a capability's `build_tool_input()` always fixes `operation` to exactly one literal value the AI never supplies or controls, mirroring `project_state_update_focus`'s existing `field="focus"` precedent exactly.

---

## 7. Exact Capability IDs

```python
class CapabilityId(Enum):
    PROJECT_STATE_SHOW = "project_state_show"                  # unchanged
    PROJECT_STATE_UPDATE_FOCUS = "project_state_update_focus"   # unchanged
    PROJECT_STATE_VERIFY_FOCUS = "project_state_verify_focus"   # unchanged, internal_only
    HEALTH_CHECK = "health_check"                               # new, Batch 1
    SCHEDULE_LIST = "schedule_list"                             # new, Batch 1
    MEMORY_LIST_RECENT = "memory_list_recent"                   # new, Batch 1
    MEMORY_SEARCH = "memory_search"                             # new, Batch 2
```

---

## 8. Exact Mapping From Capability IDs to Existing Tools

| Capability ID | Real `tool_name` | Fixed (non-model) tool-input keys | Model-supplied argument(s) |
|---|---|---|---|
| `HEALTH_CHECK` | `health_check` | none | none |
| `SCHEDULE_LIST` | `schedule_list` | none | none |
| `MEMORY_LIST_RECENT` | `memory` | `operation="list"` | none |
| `MEMORY_SEARCH` | `memory` | `operation="search"` | `query` (mapped from the model's `value` argument — see §9) |

No new tool is created. Every mapping targets an already-registered, already-tested `BaseTool` instance.

---

## 9. Exact Argument Schemas for Each Selected Capability

```python
CapabilityId.HEALTH_CHECK: CapabilityAdapter(
    tool_name="health_check",
    arguments=(),
    allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
    max_execution_tier=SecurityTier.GREEN,
    verification_strategy_id=None,
    internal_only=False,
)

CapabilityId.SCHEDULE_LIST: CapabilityAdapter(
    tool_name="schedule_list",
    arguments=(),
    allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
    max_execution_tier=SecurityTier.GREEN,
    verification_strategy_id=None,
    internal_only=False,
)

CapabilityId.MEMORY_LIST_RECENT: CapabilityAdapter(
    tool_name="memory",
    arguments=(),
    allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
    max_execution_tier=SecurityTier.GREEN,
    verification_strategy_id=None,
    internal_only=False,
)

CapabilityId.MEMORY_SEARCH: CapabilityAdapter(
    tool_name="memory",
    arguments=(CapabilityArgumentSpec(name="query", type_name="str", required=True),),
    allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
    max_execution_tier=SecurityTier.GREEN,
    verification_strategy_id=None,
    internal_only=False,
)
```

**Required, narrow generalization of `build_tool_input()`:** today's `_FIXED_FIELD_BY_CAPABILITY: dict[CapabilityId, str]` only ever injects one hardcoded key literally named `"field"` (built for `project_state_update_focus`'s one need). `MEMORY_LIST_RECENT`/`MEMORY_SEARCH` need a *different* fixed key (`"operation"`), so this dict must generalize to `_FIXED_ARGUMENTS_BY_CAPABILITY: dict[CapabilityId, dict[str, object]]`, merged into `tool_input` the same way, still never derived from model output, still never overriding a model-supplied key. This is the one real, non-trivial production code change Phase 91 requires in `intelligence/capability_catalog.py`; `project_state_update_focus`'s existing `field="focus"` behavior is preserved unchanged by migrating it into the new structure (`{CapabilityId.PROJECT_STATE_UPDATE_FOCUS: {"field": "focus"}, CapabilityId.MEMORY_LIST_RECENT: {"operation": "list"}, CapabilityId.MEMORY_SEARCH: {"operation": "search"}}`).

`MEMORY_SEARCH`'s single model-facing argument is named `value` (not `query`) to stay consistent with `project_state_update_focus`'s own established single-string-argument convention; `build_tool_input()` maps it to the real tool's `query` key, the same way it already maps to `ProjectStateUpdateTool`'s `value` key today (no renaming precedent is broken — this mirrors, not deviates from, the fixed-field mechanism above).

---

## 10. Validation and Rejection Rules

No changes to `intelligence/structured_output.py` are required. Its existing, generic `_validate_arguments()` already:
- Rejects any argument name not in the capability's declared `arguments` tuple (so a model can never smuggle `operation`, `category`, or any other `memory`-tool key through `MEMORY_SEARCH`).
- Rejects a missing required argument (`MEMORY_SEARCH` without `value`).
- Rejects a wrong type.
- Applies the existing generic string hygiene to `value`: non-empty, non-whitespace-only, ≤500 chars, no NUL, no leading/trailing control character.
- Rejects `capability_id`s not present in `CAPABILITY_CATALOG`, and any `internal_only` capability (unaffected — no new `internal_only` capability is introduced this phase).

---

## 11. SecurityManager Preflight Behavior

No new `SecurityManager` rule is needed for any selected capability — every one of their real `action_for()` outputs already classifies GREEN via existing, unchanged generic rules, confirmed by direct reading of `security/security_manager.py`'s `_RULES` table:
- `"show system health"` → existing fixed GREEN rule.
- `"list schedules"` → existing generic `"list"` GREEN rule.
- `"list memories"` → existing fixed GREEN rule.
- `"search memories"` → existing fixed GREEN rule.

`intelligence/planning.py::_preflight_capability()`'s existing exact-tier-match check (GREEN required, not merely "at most GREEN") applies unchanged to all four — a live classification other than GREEN for any of them would be refused as a safety mismatch, exactly as it already is for `project_state_show`.

---

## 12. ToolExecutor Execution Path

Unchanged. A selected, preflighted `SINGLE_TOOL` capability produces a one-step `StructuredPlan`, exactly as `project_state_show` already does; `core/orchestrator.py::_handle_ask_jarvis_to_request()`'s existing `PlanningOutcomeKind.EXECUTABLE` branch calls `self._executor.execute(step.tool_name, step.arguments, session_id=session_id)` — the same, real, unmodified `ToolExecutor.execute()` every other tool call in the system goes through, which independently re-classifies the action from scratch. No direct `tool.run()` call is introduced anywhere.

---

## 13. Grounded-Response Behavior

Unchanged. A successful execution's response is grounded in the real `ToolResult.output`, with the existing fixed `[Jarvis tool result]`-style label prepended — no second AI call ever summarizes, paraphrases, or embellishes it, exactly as `project_state_show`'s existing response path already guarantees.

---

## 14. Failure and Unsupported Outcomes

Unchanged and already fully generic: `PROVIDER_UNAVAILABLE`, `PROVIDER_FAILED`, `INVALID_OUTPUT` (parser/preflight failure), and `UNSUPPORTED` (a valid "no matching capability" decision) all already have distinct, honest, existing response messages in `core/orchestrator.py` that require no modification to serve the new capabilities — they are reached through the exact same `PlanningOutcome.kind` values Batch 2/3 already defined.

---

## 15. Batch 1 Scope

**Goal:** add `HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT` — three zero-argument GREEN capabilities — to `ask jarvis to:`, proven end-to-end.

**Production files (modified, additive only):**
- `intelligence/capability_catalog.py` — three new `CapabilityId` members, three new `CAPABILITY_CATALOG` entries, the `_FIXED_FIELD_BY_CAPABILITY` → `_FIXED_ARGUMENTS_BY_CAPABILITY` generalization (§9).
- `intelligence/planning.py` — extend `_TRUSTED_PLANNING_INSTRUCTION` text only (describe the three new capabilities and their exact JSON shapes); no control-flow change.
- `tools/builtin/help_tool.py` — mention the expanded `ask jarvis to:` capability set.
- `docs/user_guide.md` — document the three new read-only capabilities.

**Never modified:** `core/orchestrator.py`, `core/command_router.py`, `core/request_models.py`, `intelligence/structured_output.py`, `main.py` (no new tool construction needed — all three are already registered), `workflow/*`, `approval/*`, `tools/executor.py`, `security/security_manager.py`.

**Tests (new/modified):** `tests/unit/test_capability_catalog.py` (three new adapters + the generalized fixed-arguments mechanism, including a regression proving `project_state_update_focus`'s `field="focus"` behavior is unchanged), `tests/unit/test_intelligence_planning.py` (each new capability's preflight/execution path; a structural proof that `MEMORY_LIST_RECENT` can never resolve to any `operation` other than `"list"`), `tests/unit/test_help_tool.py`.

**Vertical slices:**
- `"ask jarvis to: check jarvis's health"` → `HEALTH_CHECK` executes → real `health_check` output.
- `"ask jarvis to: show my schedules"` → `SCHEDULE_LIST` executes → real `schedule_list` output.
- `"ask jarvis to: what have I asked you to remember recently"` → `MEMORY_LIST_RECENT` executes → real `memory` list output.

**Stop/report point:** full suite + Ruff + `git diff --check` clean, Batch 1 report delivered, **explicit approval required before Batch 2 begins.**

---

## 16. Batch 2 Scope

**Goal:** add `MEMORY_SEARCH` — one bounded, single-required-string-argument GREEN capability — only after Batch 1's fixed-argument mechanism and structural tests have proven stable in real use.

**Production files (modified, additive only):** `intelligence/capability_catalog.py` (one new entry, one new `_FIXED_ARGUMENTS_BY_CAPABILITY` mapping), `intelligence/planning.py` (trusted-instruction text only), `docs/user_guide.md`.

**Never modified:** everything listed as never-modified in §15, plus `intelligence/capability_catalog.py`'s Batch 1 entries themselves (additive only).

**Tests (new/modified):** argument-validation tests (unknown-key/missing-required/oversized/whitespace/control-character rejection reusing the existing generic string-hygiene test pattern from `project_state_update_focus`), a structural proof `MEMORY_SEARCH` can never resolve to any `operation` other than `"search"`, an end-to-end preflight/execution test.

**Vertical slice:** `"ask jarvis to: search my memories for the deployment checklist"` → `MEMORY_SEARCH` executes with `query="the deployment checklist"` → real `memory` search output, including its existing honest truncation notice when applicable.

**Stop/report point:** full suite + validations, Batch 2 report delivered, **explicit approval required before Phase 91 closes.**

---

## 17. Test Strategy

Each batch: focused `pytest` on every new/changed file; a structural (AST-based, mirroring Batch 1-3's own established pattern) proof per fixed-operation capability that the AI-supplied arguments can never influence the real, fixed `operation`/`field` value; an end-to-end preflight-through-execution test per new capability using a real `SecurityManager` and a real registered tool (never a mocked classification); a parser-level test confirming each new `CapabilityId` round-trips through `parse_tool_selection()` exactly like `project_state_show` already does.

---

## 18. Regression Strategy

Full existing suites for: `intelligence/` (context, capability_catalog, structured_output, planning, verification), `core/orchestrator.py`'s `ask jarvis`/`ask jarvis to` handlers, `tools/executor.py`, `security/security_manager.py`, each affected tool's own existing test file (`test_health_check_tool.py`, `test_schedule_tools.py`, `test_memory_tool.py`), `test_help_output_routing_consistency.py`, and the full suite (`poetry run pytest -q`) with an exact before/after delta reported per batch, exactly as every prior phase already does.

---

## 19. Documentation Strategy

`docs/user_guide.md`'s existing "Jarvis Intelligence: Tool Selection" section is extended (not replaced) to list all six capabilities and their exact GREEN/YELLOW/internal status. `tools/builtin/help_tool.py`'s `ask jarvis to:` entry is updated to reflect the wider read-only capability set while preserving its existing YELLOW-update-focus description unchanged. No new documentation file is created for either batch; `docs/phase_91_completion_report.md` and any Continuation Kit update are explicitly deferred to Phase 91's own final closure, not either batch individually (mirroring Phase 90's own Batch-vs-closure-doc separation).

---

## 20. Explicit Non-Goals

No new user-facing command or grammar. No YELLOW or RED capability. No write capability of any kind (including `memory`'s own already-GREEN `"save"` operation). No arbitrary `ToolRegistry` exposure — `CAPABILITY_CATALOG` remains the sole, independent allowlist. No multi-tool plans, capability chaining, or generic N-step planning. No retries, replans, or AI-based verification. No automatic memory writes. No conversation-history persistence. No dashboard expansion. No voice/microphone/phone/browser/computer-control work. No source-code self-modification. No change to `ask jarvis:`'s advisory-only behavior. No `file_search`/`file_list` exposure until a bounded-path design is separately proposed and approved.

---

## 21. Risks and Mitigations

- **Risk:** a multi-operation tool (`memory`) could let the AI reach an operation not intended for AI use (e.g. `"save"`, `"get"`). **Mitigation:** `operation` is never a model-facing argument for either `MEMORY_LIST_RECENT` or `MEMORY_SEARCH` — it is always injected by `build_tool_input()` from a fixed, per-capability literal the parser never even sees as an argument name, so no malformed or adversarial model output can select it. A dedicated structural test proves this per capability.
- **Risk:** the `_FIXED_FIELD_BY_CAPABILITY` → `_FIXED_ARGUMENTS_BY_CAPABILITY` generalization could regress `project_state_update_focus`'s existing `field="focus"` injection. **Mitigation:** a direct regression test re-asserts the exact existing tool-input shape for `project_state_update_focus` is unchanged after the generalization, run before either batch is considered complete.
- **Risk:** expanding the trusted planning instruction's length/complexity could degrade the model's selection accuracy across all six capabilities. **Mitigation:** keep each capability's instruction paragraph as short as `project_state_show`'s existing one; the acceptance criteria (§23) require a real, manual smoke-test pass (subject to the current API-credit postponement) covering all newly-added capabilities before Phase 91 closes.
- **Risk (carried forward, not for this phase):** `file_search`/`file_list`'s unbounded `path` argument. **Mitigation:** deferred entirely (§6) rather than exposed with an inadequate bound.

---

## 22. Rollback Boundaries

Both batches are purely additive to `intelligence/capability_catalog.py` and `intelligence/planning.py`'s instruction text, plus documentation. Rolling back either batch means reverting exactly those files' diffs — no data migration, no persisted state, and no other module's behavior depends on the new catalog entries existing. `project_state_show`/`project_state_update_focus` continue to function identically whether or not Phase 91's entries are present, since `CAPABILITY_CATALOG` is a plain dict and every new entry is independent of the existing ones.

---

## 23. Acceptance Criteria

1. All four new capabilities are present in `CAPABILITY_CATALOG` with the exact adapters in §9.
2. Each new capability's real, live preflight classification is confirmed GREEN via a real `SecurityManager().classify_action()` call against the real tool's real `action_for()` output — never assumed.
3. A model response naming `MEMORY_LIST_RECENT`/`MEMORY_SEARCH` can never cause any `operation` other than `"list"`/`"search"` to reach the real `memory` tool, proven structurally.
4. `MEMORY_SEARCH`'s `value` argument is validated by the existing generic string-hygiene rules with zero new parser code.
5. `project_state_show`/`project_state_update_focus`/`project_state_verify_focus` behavior is provably unchanged (full regression pass).
6. Full suite passes with an exact, reported before/after delta; Ruff clean with zero new E402 debt; `git diff --check` clean.
7. `docs/user_guide.md` and `HelpTool` accurately describe every new capability's read-only, GREEN nature.

---

## 24. Expected Files That May Be Changed in Each Future Batch

**Batch 1:** `intelligence/capability_catalog.py`, `intelligence/planning.py` (instruction text only), `tools/builtin/help_tool.py`, `docs/user_guide.md`, `tests/unit/test_capability_catalog.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_help_tool.py`.

**Batch 2:** `intelligence/capability_catalog.py`, `intelligence/planning.py` (instruction text only), `docs/user_guide.md`, `tests/unit/test_capability_catalog.py`, `tests/unit/test_intelligence_planning.py`.

**Phase 91 closure (not part of either batch):** `docs/phase_91_completion_report.md` (new), a Continuation Kit update if warranted.

**Never expected to change in Phase 91:** `core/orchestrator.py`, `core/command_router.py`, `core/request_models.py`, `intelligence/structured_output.py`, `intelligence/context.py`, `intelligence/verification.py`, `main.py`, `workflow/*`, `approval/*`, `tools/executor.py`, `tools/registry.py`, `tools/base_tool.py`, `security/security_manager.py`, any individual tool file (`health_check_tool.py`, `schedule_list_tool.py`, `memory_tool.py` themselves are consumed exactly as they already exist), any dashboard code.

---

## 25. `dashboard_test.txt` Confirmation

Confirmed untouched, untracked, and uncommitted throughout this planning pass — observed only as a `git status --short` entry, never opened, read, staged, or otherwise interacted with. Neither batch in this plan touches any dashboard code or file.

---

## 26. Batch 1 Implementation and Verification Evidence

**Implemented exactly as planned in §5/§7-§15**, with no scope deviation: `HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT` added to `CAPABILITY_CATALOG`, all zero-argument, GREEN, `SINGLE_TOOL`. `MEMORY_SEARCH` (Batch 2) was **not** implemented.

**Files actually changed (all as predicted in §24's "Batch 1" row, no extras):**
- `intelligence/capability_catalog.py` — three new `CapabilityId` members and `CAPABILITY_CATALOG` entries; `_FIXED_FIELD_BY_CAPABILITY: dict[CapabilityId, str]` generalized to `_FIXED_ARGUMENTS_BY_CAPABILITY: dict[CapabilityId, dict[str, object]]` (a strict superset behaviorally — `project_state_update_focus`'s existing `field="focus"` injection is preserved unchanged, now expressed as `{"field": "focus"}`; `memory_list_recent` adds `{"operation": "list"}`).
- `intelligence/planning.py` — `_TRUSTED_PLANNING_INSTRUCTION` text extended to describe all five model-selectable capabilities and their exact JSON shapes. No control-flow change: `select_tool()`'s existing `SINGLE_TOOL` branch handles all three new capabilities with zero new code, confirmed by direct testing.
- `tools/builtin/help_tool.py`, `docs/user_guide.md` — documentation of the three new capabilities, preserving every existing required phrase (`ask jarvis to: <request>`, `AI_REASONING_ENABLED`, `no supported capability can satisfy`, `update only its focus field`, `requires your explicit approval`, `structured read-back`, `no arbitrary tool access, no autonomous behavior`).
- `tests/unit/test_capability_catalog.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_help_tool.py` — new/updated focused tests (see below).

**Confirmed unchanged (zero diff):** `core/orchestrator.py`, `core/command_router.py`, `core/request_models.py`, `intelligence/structured_output.py`, `intelligence/context.py`, `intelligence/verification.py`, `main.py`, `workflow/*`, `approval/*`, `tools/executor.py`, `tools/registry.py`, `tools/base_tool.py`, `security/security_manager.py`, every individual tool file, all dashboard code.

**Exact capability behavior implemented:**
- `HEALTH_CHECK` → real `health_check` tool, `arguments=()`, `tool_input == {}` always.
- `SCHEDULE_LIST` → real `schedule_list` tool, `arguments=()`, `tool_input == {}` always.
- `MEMORY_LIST_RECENT` → real `memory` tool, `arguments=()`, `tool_input == {"operation": "list"}` always — the `"operation"` key is a fixed literal from `_FIXED_ARGUMENTS_BY_CAPABILITY`, never model-supplied or model-overridable (the capability declares zero arguments, so the strict parser rejects any model-supplied `"operation"` key before `build_tool_input()` is ever reached — proven by `test_memory_list_recent_execute_with_stray_argument_is_rejected`).

**Real `SecurityManager` preflight confirmed:** all three real actions (`"show system health"`, `"list schedules"`, `"list memories"`) classify GREEN via existing, unchanged `_RULES` entries — no new `SecurityManager` rule was added or needed. `intelligence/planning.py::_preflight_capability()`'s existing exact-tier-match check applies unchanged.

**Real `ToolExecutor` execution confirmed:** each capability's one-step `StructuredPlan` is executed via `core/orchestrator.py`'s existing, unmodified `PlanningOutcomeKind.EXECUTABLE` branch, calling `self._executor.execute(...)` — the same real `ToolExecutor` every other tool call uses. Proven end-to-end in `tests/unit/test_orchestrator_ask_jarvis_to.py` with real, SQLite-backed `HealthCheckTool`/`ScheduleListTool`/`MemoryTool` instances (never mocks), asserting exactly one `tool_call` audit event per request.

**No direct `tool.run()` call added:** `test_no_direct_tool_run_call_anywhere_in_planning_module` (pre-existing, unmodified) continues to pass against the extended `intelligence/planning.py`.

**Test results:**
- Focused (`test_capability_catalog.py` + `test_intelligence_planning.py` + `test_orchestrator_ask_jarvis_to.py` + `test_help_tool.py`): **309 passed, 0 failed**.
- Phase 90 regressions (`test_ask_jarvis_to_routing.py`, `test_structured_output.py`, `test_orchestrator_update_focus_workflow.py`, `test_verification.py`, `test_project_state_verify_tool.py`) plus core regressions (`test_workflow_engine.py`, `test_approval_manager.py`, `test_tool_executor_approval.py`, `test_tool_executor_logger_isolation.py`, `test_security.py`, `test_security_injection_scan.py`, `test_security_unexpected_action.py`, `test_command_router.py`, `test_help_output_routing_consistency.py`, `test_project_state_store.py`, `test_project_state_show_tool.py`, `test_project_state_update_tool.py`, `test_health_check_tool.py`, `test_schedule_tools.py`, `test_memory_tool.py`): **901 passed, 0 failed**.
- Full suite (`poetry run pytest -q`): **4627 passed, 3 skipped, 2 failed**. The 2 failures (`test_main_ai_wiring.py::test_ai_disabled_orchestrator_has_no_reasoning_engine`, `test_main_jarvis_brain_wiring.py::test_jarvis_brain_tool_reports_real_config_through_real_wiring`) are **pre-existing and environmental**, not caused by this batch: both assert AI reasoning is disabled by default, but this machine's real `.env`/environment currently has AI reasoning enabled (a real Anthropic API key is configured, separately noted as currently low on credits). Confirmed by `git stash`-ing every Batch 1 change and re-running both tests against the unmodified `e9abab3` baseline — they fail identically. Delta from the 4607/3/0 Batch 90-closure baseline: **+20 passed** (new Batch 1 tests) **+0 skipped, +2 pre-existing/environmental failures unrelated to this diff**.
- Ruff (`poetry run ruff check` on every changed file): **clean, zero violations**.
- `git diff --check`: **clean**.

**Not implemented (confirmed):** `MEMORY_SEARCH`, `quarantine_list`, `workflow_history`, `approval_history`, `info`, `file_search`, `file_list`, `memory` `save`/`get`/`categories`, any YELLOW/RED capability, any multi-tool plan, chaining, retry, replan, or dashboard change.

**Post-Batch-1 addendum:** the 2 pre-existing/environmental full-suite failures noted above were separately diagnosed and fixed in a dedicated, test-only maintenance commit (`dc72a54`, "Fix test environment isolation before Phase 91 Batch 2") — the two affected fixtures now set `PYTHON_DOTENV_DISABLED=1` instead of deleting `AI_REASONING_ENABLED`, and the scheduled-inbox integration test file gained one autouse fixture supplying its own already-established fake `ANTHROPIC_API_KEY`. No production code changed. Verified: full suite in the normal environment, with `AI_REASONING_ENABLED=false`, and with `PYTHON_DOTENV_DISABLED=1` all passed with zero failures after that commit.

**Phase 91 remains open** — Batch 2 (`MEMORY_SEARCH`) requires its own separate approval before implementation begins.

---

## 27. Batch 2 Implementation and Verification Evidence

**Implemented exactly as planned in §5/§7-§10/§16**, with no scope deviation: `MEMORY_SEARCH` added to `CAPABILITY_CATALOG` as the fourth and final Phase 91 capability - GREEN, read-only, `SINGLE_TOOL`, one required bounded string argument. No other capability was added; no write behavior of any kind was introduced.

**Files actually changed:**
- `intelligence/capability_catalog.py` — one new `CapabilityId` member and `CAPABILITY_CATALOG` entry; `_FIXED_ARGUMENTS_BY_CAPABILITY` gained `{CapabilityId.MEMORY_SEARCH: {"operation": "search"}}`; a new, narrow `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY` mechanism was added (a real, non-trivial gap found during repository inspection — see below) so `build_tool_input()` can rename a capability's validated argument key to the real tool's own input key name.
- `intelligence/planning.py` — `_TRUSTED_PLANNING_INSTRUCTION` text extended to describe the sixth model-selectable capability and its exact JSON shape; module docstring header updated for accuracy. No control-flow change: `select_tool()`'s existing `SINGLE_TOOL` branch handles `memory_search` with zero new code, exactly as it already does for every other `SINGLE_TOOL` capability.
- `tools/builtin/help_tool.py`, `docs/user_guide.md` — documentation of the new capability.
- `tests/unit/test_capability_catalog.py`, `tests/unit/test_structured_output.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_help_tool.py` — new/updated focused tests (see below).

**Confirmed unchanged (zero diff):** `core/orchestrator.py`, `core/command_router.py`, `core/request_models.py`, `intelligence/structured_output.py`, `intelligence/context.py`, `intelligence/verification.py`, `main.py`, `workflow/*`, `approval/*`, `tools/executor.py`, `security/security_manager.py`, `tools/builtin/memory_tool.py` itself, all dashboard code.

**Repository-inspection finding requiring a planning clarification (reported, not silently assumed):** this plan's own §9 asserted `build_tool_input()` "already maps [`value`] to the real tool's `query` key, the same way it already maps to `ProjectStateUpdateTool`'s `value` key today" — on inspection this was inexact: `project_state_update_focus`'s `value` argument keeps the identical key name in the real tool's input (no rename occurs there; `build_tool_input()` only ever *added* a fixed extra key). No existing mechanism renamed an argument's key. Implementing `memory_search`'s explicit requirement to map the AI-facing `value` argument onto the real `MemoryTool`'s `query` input key therefore required one small, new, narrow addition — `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY: dict[CapabilityId, dict[str, str]]`, applied inside `build_tool_input()` before the existing fixed-argument merge. This is additive only: every other capability has no entry in this new dict and is completely unaffected (proven by `test_build_tool_input_rename_does_not_affect_other_capabilities`, which re-confirms `project_state_update_focus`'s exact pre-existing behavior is unchanged).

**Exact MEMORY_SEARCH catalogue definition:**
```python
CapabilityId.MEMORY_SEARCH: CapabilityAdapter(
    capability_id=CapabilityId.MEMORY_SEARCH,
    tool_name="memory",
    description="Searches your stored memories for text matching a query. Read-only and safe.",
    arguments=(CapabilityArgumentSpec(name="value", type_name="str", required=True),),
    allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
    max_execution_tier=SecurityTier.GREEN,
    verification_strategy_id=None,
    internal_only=False,
)
```

**Exact AI-facing argument:** `value` — `type_name="str"`, `required=True`. Bounds are the existing, unmodified generic string-argument hygiene rule in `intelligence/structured_output.py::_validate_string_argument()` (the same rule `project_state_update_focus`'s own `value` argument already uses): non-empty and non-whitespace-only after considering surrounding whitespace (effective minimum: one non-whitespace character), maximum 500 characters (`_MAX_STRING_ARGUMENT_CHARS`), no NUL character, no leading/trailing C0-control/DEL character. Zero new parser code was needed or added.

**Exact real `MemoryTool` input produced:** `{"query": <validated value>, "operation": "search"}` — `build_tool_input()` renames the validated `value` key to `query` (via `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY`), then merges in the fixed `operation="search"` (via `_FIXED_ARGUMENTS_BY_CAPABILITY`). Neither key is ever model-supplied or model-overridable: `operation` is not a declared argument at all (an attempt to supply it is rejected by the strict parser as an unknown argument, before `build_tool_input()` ever runs), and `value` is unconditionally renamed away, never left alongside `query` in the final input (proven by `test_build_tool_input_memory_search_never_leaves_a_stray_value_key`).

**Real `SecurityManager` preflight confirmed:** the real action `"search memories"` (from `MemoryTool.action_for()` with `operation="search"`) classifies **GREEN** via the existing, unchanged `_RULES` entry — no new `SecurityManager` rule was added or needed, and the real, live classification exactly matched this plan's own expectation (§9), so no mismatch was found and no security rule was touched.

**Real `ToolExecutor` execution confirmed:** `memory_search`'s one-step `StructuredPlan` is executed via `core/orchestrator.py`'s existing, unmodified `PlanningOutcomeKind.EXECUTABLE` branch, calling `self._executor.execute(...)` — the same real `ToolExecutor` every other tool call uses. Proven end-to-end in `tests/unit/test_orchestrator_ask_jarvis_to.py` with a real, SQLite-backed `MemoryTool` instance (never a mock), asserting exactly one `tool_call` audit event per request.

**No direct `tool.run()` call added:** `test_no_direct_tool_run_call_anywhere_in_planning_module` (pre-existing, unmodified) continues to pass against the extended `intelligence/planning.py`.

**Grounded-response behavior:** a successful search's response is the real `MemoryTool` search output verbatim, labelled `[Jarvis tool result]` — real matching memory content, real non-matching content correctly absent (`test_memory_search_executes_through_real_tool_executor_and_grounds_response`). A real no-match search returns the tool's own existing honest "none found" text unchanged (`test_memory_search_real_no_results_grounds_the_response`) — never a fabricated or AI-paraphrased result, and no second AI generation step of any kind runs after execution.

**Test results:**
- Focused (`test_capability_catalog.py` + `test_structured_output.py` + `test_intelligence_planning.py` + `test_orchestrator_ask_jarvis_to.py` + `test_help_tool.py`): **271 passed, 0 failed**.
- Phase 91 Batch 1 + Phase 90 regressions (`test_ask_jarvis_to_routing.py`, `test_orchestrator_update_focus_workflow.py`, `test_verification.py`, `test_project_state_verify_tool.py`): **67 passed, 0 failed**.
- Deterministic/security/executor regressions (`test_memory_tool.py`, `test_command_router.py`, `test_help_output_routing_consistency.py`, `test_security.py`, `test_security_injection_scan.py`, `test_security_unexpected_action.py`, `test_tool_executor_approval.py`, `test_tool_executor_logger_isolation.py`, `test_health_check_tool.py`, `test_schedule_tools.py`, `test_project_state_show_tool.py`, `test_project_state_update_tool.py`): **799 passed, 0 failed**.
- Full suite, normal environment (`poetry run pytest -q`): **4658 passed, 3 skipped, 0 failed**.
- Full suite with `AI_REASONING_ENABLED=false`: **4658 passed, 3 skipped, 0 failed** — identical.
- Ruff (`poetry run ruff check` on every changed file): exit code 0, **no findings** (new or pre-existing) on any Batch 2 file.
- `git diff --check`: clean.

**Not implemented (confirmed):** memory `save`/`get`/`categories`/update/forget, any user-selectable result limit or category filter, `quarantine_list`, `workflow_history`, `approval_history`, `info`, `file_search`, `file_list`, any new YELLOW/RED capability, any multi-tool plan, chaining, retry, replan, or dashboard change.

**Phase 91 is now implementation-complete** (all four planned capabilities across both batches are implemented and verified) but is **not** being marked closed here — it awaits Nathan's own review, and the manual Anthropic API acceptance test remains postponed for external API-credit reasons, not a code defect. No Phase 92 work of any kind has begun.
