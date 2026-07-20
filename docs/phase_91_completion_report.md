# Phase 91 — Safe Intelligence Capability Expansion — Completion Report

**Checkpoint:** complete through Batch 2, its originally-scoped final batch.
**Version:** Phase 91 — Safe Intelligence Capability Expansion (medium milestone: planning gate + 2 batches)
**Date:** 2026-07-20

---

## 1. Phase Objective

Expand the existing Phase 90 `ask jarvis to: <request>` Intelligence Core path with a small, conservative set of additional GREEN, read-only capabilities, reusing the exact Phase 90 architecture (capability allowlist, strict structured decision, exact argument validation, real `SecurityManager` preflight, real `ToolExecutor` execution, grounded response) with zero weakening of any existing security or approval behavior. The advisory `ask jarvis: <request>` path and every Phase 90 capability were required to remain unchanged.

---

## 2. Planning and Batch Commit History

| Commit | Content |
|---|---|
| `e9abab3` | Phase 91 planning gate — `docs/phase_91_implementation_plan.md`, candidate inspection, ranking, and the two-batch split |
| `01e21c9` | Batch 1 — zero-argument GREEN read-only capabilities: `HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT` |
| `dc72a54` | Separate, test-only pre-Batch-2 test-isolation repair (see §10 — not a Phase 91 production feature) |
| `1a144b4` | Batch 2 — bounded `MEMORY_SEARCH` capability |

---

## 3. Files and Architectural Areas Changed

**Production (Batches 1 + 2 combined):**
- `intelligence/capability_catalog.py` — four new `CapabilityId` members and `CAPABILITY_CATALOG` entries; the fixed-argument mechanism generalized from a single hardcoded `"field"` key (`_FIXED_FIELD_BY_CAPABILITY`) to an arbitrary per-capability dict (`_FIXED_ARGUMENTS_BY_CAPABILITY`); a new, additive `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY` mechanism added in Batch 2 for `memory_search`'s `value`→`query` rename.
- `intelligence/planning.py` — `_TRUSTED_PLANNING_INSTRUCTION` text extended across both batches to describe all six model-selectable capabilities and their exact JSON shapes. **No control-flow change in either batch** — every new capability reuses the pre-existing `SINGLE_TOOL` branch of `select_tool()` and the pre-existing `PlanningOutcomeKind.EXECUTABLE` branch of `core/orchestrator.py::_handle_ask_jarvis_to_request()`, both completely unmodified.
- `tools/builtin/help_tool.py`, `docs/user_guide.md` — documentation of all four new capabilities.

**Tests (Batches 1 + 2 combined):** `tests/unit/test_capability_catalog.py`, `tests/unit/test_structured_output.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_help_tool.py`.

**Test-isolation repair only (`dc72a54`, test files, no production code):** `tests/unit/test_main_ai_wiring.py`, `tests/unit/test_main_jarvis_brain_wiring.py`, `tests/integration/test_scheduled_inbox_notice_end_to_end.py`.

**Confirmed unchanged throughout Phase 91:** `core/orchestrator.py`, `core/command_router.py`, `core/request_models.py`, `intelligence/structured_output.py`, `intelligence/context.py`, `intelligence/verification.py`, `main.py`, `workflow/*`, `approval/*`, `tools/executor.py`, `tools/registry.py`, `tools/base_tool.py`, `security/security_manager.py`, `tools/builtin/health_check_tool.py`, `tools/builtin/schedule_list_tool.py`, `tools/builtin/memory_tool.py`, `tools/builtin/project_state_show_tool.py`, `tools/builtin/project_state_update_tool.py`, `tools/builtin/project_state_verify_tool.py`, all dashboard code.

---

## 4. Exact Capability Schemas

### HEALTH_CHECK
- Explicitly catalogued, GREEN, read-only.
- AI-facing arguments: exactly none (`arguments=()`).
- Real tool input: `{}`.
- Real tool: `health_check` (`HealthCheckTool`), unmodified.

### SCHEDULE_LIST
- Explicitly catalogued, GREEN, read-only.
- AI-facing arguments: exactly none (`arguments=()`).
- Real tool input: `{}`.
- Real tool: `schedule_list` (`ScheduleListTool`), unmodified.

### MEMORY_LIST_RECENT
- Explicitly catalogued, GREEN, read-only.
- AI-facing arguments: exactly none (`arguments=()`).
- Real tool: `memory` (`MemoryTool`), unmodified.
- Trusted internal real tool input: `{"operation": "list"}` — fixed by `_FIXED_ARGUMENTS_BY_CAPABILITY`, never a model-facing argument, so the model can neither choose nor override it.

### MEMORY_SEARCH
- Explicitly catalogued, GREEN, read-only.
- AI-facing argument: `value` — `str`, required.
- Validation (existing, unmodified generic string-hygiene rule in `intelligence/structured_output.py::_validate_string_argument()`, the same rule `project_state_update_focus`'s own `value` argument already uses): non-empty, not whitespace-only, maximum 500 characters, no NUL character, no leading or trailing control character. No additional normalization, coercion, trimming, truncation, filters, categories, or limits exist or were added.
- Trusted argument rename: AI-facing `value` → real `MemoryTool` input key `query`, via the new `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY` mechanism.
- Trusted fixed internal argument: `operation="search"`, via `_FIXED_ARGUMENTS_BY_CAPABILITY`.
- Exact resulting real tool input: `{"query": <validated value>, "operation": "search"}`.
- The model cannot provide or override `query` as an undeclared key (the capability declares only `value`; any other key is rejected by the strict parser as an unknown argument before `build_tool_input()` ever runs).
- The model cannot provide or override `operation` (not a declared argument; same rejection path).

---

## 5. Trusted Internal Arguments and Rename Behavior

Two independent, additive mechanisms in `intelligence/capability_catalog.py::build_tool_input()`, applied in this fixed order:
1. **Key rename** (`_ARGUMENT_KEY_RENAMES_BY_CAPABILITY`) — renames a validated argument's key to the real tool's own input key name. Only `memory_search` has an entry (`{"value": "query"}`). Every other capability is unaffected.
2. **Fixed-argument merge** (`_FIXED_ARGUMENTS_BY_CAPABILITY`) — merges in literal, non-model-controlled key/value pairs after the rename. Entries: `project_state_update_focus` → `{"field": "focus"}` (Phase 90, unchanged), `memory_list_recent` → `{"operation": "list"}`, `memory_search` → `{"operation": "search"}`.

Both mechanisms are keyed by `CapabilityId`, populated once in this module, never derived from or influenced by parsed model output. A repository-inspection finding during Batch 2 (documented in the implementation plan's §27) established that no rename mechanism previously existed — `project_state_update_focus`'s `value` key already matched its real tool's key name, so Batch 3 of Phase 90 never actually needed one. The rename mechanism was added as a small, additive change specifically for `memory_search`; `test_build_tool_input_rename_does_not_affect_other_capabilities` re-confirms every pre-existing capability's behavior is bit-for-bit unchanged.

---

## 6. SecurityManager Evidence

Every one of the four new capabilities' real actions classifies GREEN via existing, unmodified `SecurityManager._RULES` entries — no new rule was added or needed for any of them:
- `HEALTH_CHECK` → `"show system health"` → GREEN (fixed rule).
- `SCHEDULE_LIST` → `"list schedules"` → GREEN (generic `"list"` rule).
- `MEMORY_LIST_RECENT` → `"list memories"` → GREEN (fixed rule).
- `MEMORY_SEARCH` → `"search memories"` → GREEN (fixed rule).

`intelligence/planning.py::_preflight_capability()`'s existing exact-tier-match check (a live classification must equal the catalog's declared `max_execution_tier` exactly, not merely be "at most" it) applies unchanged to all four; every real, live classification matched this repository's own planning-document expectations, so no security-classification mismatch was ever found and no `SecurityManager` rule was broadened, weakened, or bypassed.

---

## 7. ToolExecutor Evidence

Each capability's one-step `StructuredPlan` executes via `core/orchestrator.py`'s existing, unmodified `PlanningOutcomeKind.EXECUTABLE` branch, calling `self._executor.execute(...)` — the identical, real `ToolExecutor` every other tool call in the system uses. Proven end-to-end in `tests/unit/test_orchestrator_ask_jarvis_to.py` with real, SQLite-backed `HealthCheckTool`/`ScheduleListTool`/`MemoryTool` instances (never mocks), each asserting exactly one `tool_call` audit event per request. No direct `tool.run()` call exists anywhere in the Intelligence Core path — the pre-existing structural test `test_no_direct_tool_run_call_anywhere_in_planning_module` continues to pass unmodified against the extended `intelligence/planning.py`. The full `ToolRegistry` is never exposed to the model; `CAPABILITY_CATALOG` remains the sole, independent, individually-hand-maintained allowlist. Only one capability executes per request — the strict three-key schema names at most one `capability_id`, with no mechanism anywhere for a second.

---

## 8. Grounded-Response Behavior

Every successful response is the real `ToolResult.output` verbatim, labelled `[Jarvis tool result]` — never an AI paraphrase, and never a second, unrestricted AI generation step capable of rewriting factual content. Proven concretely:
- Real matching memory content is returned and non-matching content correctly absent (`test_memory_search_executes_through_real_tool_executor_and_grounds_response`).
- A real no-match search returns the tool's own existing honest "none found" text, unchanged (`test_memory_search_real_no_results_grounds_the_response`).
- Real schedule records, real health-check status, and real recent-memory listings are returned verbatim for their respective capabilities (Batch 1 tests).

---

## 9. Validation and Rejection Behavior

Malformed decisions fail safely at the existing, unmodified strict parser (`intelligence/structured_output.py`), before any preflight or execution:
- Unsupported capability names — rejected (`"capability id not present in catalog"`).
- Missing required arguments — rejected (`"missing required argument"`).
- Extra/unrecognised arguments (including any attempt to supply the internal `operation` field) — rejected (`"unknown argument name in model output"`).
- Wrongly typed arguments (numbers, booleans, arrays, objects where a string is required) — rejected (`"invalid argument type"`).
- Non-object `"arguments"` containers — rejected (`"arguments must be a JSON object"`).
- Malformed structured output (duplicate keys at any depth, wrong top-level key set, oversized raw output, unsupported code-fence shapes) — rejected with their own existing, bounded reasons.
- Values outside accepted bounds (empty, whitespace-only, over 500 characters, containing NUL, or a leading/trailing control character) — rejected with their own existing, exact reasons.

Jarvis does not coerce, guess, repair, silently truncate, or silently ignore unknown fields; does not retry or replan; and cannot chain multiple capabilities in one request — all proven by existing, unmodified structural and behavioral tests extended in Batches 1 and 2.

---

## 10. Test-Isolation Repair Summary (`dc72a54`)

A separate, test-only maintenance commit, made between Batch 1 and Batch 2, fixing pre-existing environment leakage discovered while verifying Batch 1:
- Two unit-test fixtures (`test_main_ai_wiring.py`, `test_main_jarvis_brain_wiring.py`) used `monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)` intending to simulate the disabled default, but `load_settings()`'s own `load_dotenv(override=False)` call repopulated the deleted key from a real developer `.env` file. Both fixtures now set `PYTHON_DOTENV_DISABLED=1` (a real, documented python-dotenv mechanism) instead, so "unset" genuinely means unset regardless of `.env` content.
- `tests/integration/test_scheduled_inbox_notice_end_to_end.py` gained one autouse fixture supplying its own already-established fake `ANTHROPIC_API_KEY` test value, removing an implicit dependency on a real `.env` file.

**This was not a Phase 91 production feature.** No production code changed in this commit — only test fixtures. It exists solely so Phase 91's own test suite could be verified honestly, independent of any individual developer machine's `.env` configuration.

---

## 11. Focused and Full-Suite Verification Results (re-run at closure, HEAD `1a144b4`)

- Focused (`test_capability_catalog.py` + `test_structured_output.py` + `test_intelligence_planning.py` + `test_orchestrator_ask_jarvis_to.py` + `test_help_tool.py`): **271 passed, 0 failed**.
- Phase 90 Intelligence Core regressions (`test_ask_jarvis_to_routing.py`, `test_orchestrator_update_focus_workflow.py`, `test_verification.py`, `test_project_state_verify_tool.py`): **67 passed, 0 failed**.
- Deterministic health/schedule/memory tool + command-router + help-routing regressions (`test_health_check_tool.py`, `test_schedule_tools.py`, `test_memory_tool.py`, `test_command_router.py`, `test_help_output_routing_consistency.py`, `test_project_state_show_tool.py`, `test_project_state_update_tool.py`): **674 passed, 0 failed**.
- SecurityManager/ToolExecutor regressions (`test_security.py`, `test_security_injection_scan.py`, `test_security_unexpected_action.py`, `test_tool_executor_approval.py`, `test_tool_executor_logger_isolation.py`): **125 passed, 0 failed**.
- Full suite, normal environment (`poetry run pytest -q`): **4658 passed, 3 skipped, 0 failed**.
- Full suite with `AI_REASONING_ENABLED=false`: **4658 passed, 3 skipped, 0 failed** — identical.
- Ruff (`poetry run ruff check` on every `.py` file changed across `01e21c9`, `dc72a54`, `1a144b4`): exit code **1**. Findings: **20 `E402`** in `tests/integration/test_scheduled_inbox_notice_end_to_end.py`, all at its own established `pytest.importorskip("sqlalchemy")`-then-import lines — **confirmed pre-existing** (identical count verified directly against that file's content at `dc72a54`'s parent commit, before Phase 91 touched it). **Zero new findings** were introduced by any Phase 91 commit. Every other changed file (`intelligence/capability_catalog.py`, `intelligence/planning.py`, `tools/builtin/help_tool.py`, `tests/unit/test_capability_catalog.py`, `tests/unit/test_structured_output.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_help_tool.py`, `tests/unit/test_main_ai_wiring.py`, `tests/unit/test_main_jarvis_brain_wiring.py`) is individually clean.
- `git diff --check`: clean.

---

## 12. Manual API Acceptance Limitation

Manual live-AI acceptance testing remains **postponed**. The configured Anthropic API account lacked sufficient API credits to run a genuine live-model verification pass. This is an **external account limitation**, not a Jarvis code failure — no production code was changed to work around it, and no manual live-AI acceptance test is claimed to have passed. Phase 91 is being closed on the basis of repository-level implementation, focused tests, integration tests, security tests, executor tests, and complete-suite verification (all real, all executed, all passing) — not on a live-model acceptance run.

---

## 13. Deferred Scope and Non-Goals

Phase 91 did not implement or expose: memory `save`, memory `get`, memory `categories`, memory update, memory forget, any model-selectable memory result limit, any memory category filter, `quarantine_list`, `workflow_history`, `approval_history`, general `info`, `file_search`, `file_list`, arbitrary tools, dynamic `ToolRegistry` exposure, multi-tool plans, retries, replanning, autonomous agent loops, automatic memory writes, conversation persistence, source-code self-modification, dashboard changes, voice, microphone, wake-word, phone control, browser control, or general computer control. No new YELLOW or RED capability was introduced. No new write capability of any kind was introduced.

---

## 14. Final Repository Status

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- HEAD at closure verification: `1a144b4` (this report's own commit follows, documentation-only).
- `git status --short`: only `?? dashboard_test.txt` — confirmed untouched, untracked, and uncommitted throughout Phase 91, including this closure pass.
- Full suite: 4658 passed, 3 skipped, 0 failed (normal environment and with `AI_REASONING_ENABLED=false`, identical).

---

## 15. Final Closure Statement

Phase 91 — Safe Intelligence Capability Expansion is **formally closed**. All four planned capabilities (`HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT`, `MEMORY_SEARCH`) are implemented exactly as planned, preserve the full Phase 90 Intelligence Core pipeline unmodified, introduce no new write capability, and are verified by a complete, zero-failure test suite in two independent environment configurations. The advisory `ask jarvis: <request>` path, `PROJECT_STATE_SHOW`, `PROJECT_STATE_UPDATE_FOCUS`'s YELLOW approval flow, its durable focus verifier, and every deterministic command remain exactly as Phase 90 left them. Manual live-AI acceptance remains postponed for external account-credit reasons, honestly disclosed above, and this closure does not claim otherwise. No Phase 92 work of any kind has begun.
