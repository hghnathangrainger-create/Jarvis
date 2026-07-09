# Jarvis — Phase 15 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 15 — Sequential Workflow Execution — Minimal Multi-Step Planner and Workflow Engine (Batches 1–4, 4A, 4B, 5, complete)
**Date:** 2026-07-10

---

## Executive Summary

Phase 15 of the Jarvis AI Operating System is **complete** for the scope defined in `docs/phase_15_implementation_plan.md`: it is the first phase in which Jarvis executes more than one step per request. A short, fixed, two-step **workflow** — save-then-show, and save-then-forget — now runs through a new, headless **Sequential Workflow Engine**, with every step still individually classified by `SecurityManager.classify_action()` and gated by the unmodified `ToolExecutor`, exactly as every single-step action already was. This is deliberately **not** the general-purpose Workflow Engine described in the Master Specification's Chapter 10: there is no branching, no parallel execution, no retries, no cross-restart checkpointing, no AI-authored steps, and no user-definable workflow syntax. Two commands exist, both hardcoded, both fixed at two steps.

Six implementation batches, plus this closure batch, delivered it:

- **Batch 1** (`a8d7d03`) — minimal multi-step plan and workflow runtime models.
- **Batch 2** (`e75365e`) — the headless `WorkflowEngine` itself.
- **Batch 3** (`97780c9`) — the deterministic workflow-plan factory, the two exact commands, and orchestrator wiring.
- **Batch 4** (`d4aa698`) — the CLI workflow trace and full end-to-end proof through the real approval flow.
- **Batch 4A** (`6117503`) — a corrective fix: `ToolExecutor`'s audit logger could previously escape and mask an authoritative `ToolResult` (or a genuine tool exception); isolated the same way every other optional audit call in Jarvis already is.
- **Batch 4B** (`154f4d2`) — a corrective fix, found via the same investigative method applied to a second collaborator: `ApprovalManager`'s audit logger could previously escape and strand an already-decided, paused workflow. Isolated the same way.
- **Batch 5** (this report) — final semantic-drift, security, and observability-invariant review; documentation; closure.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and every test uses a fake provider. No live Claude API call is made anywhere in this codebase's test suite. (Phase 15's own workflows do not themselves involve the advisory AI reasoning path at all — they are deterministic tool-execution sequences.)

---

## Phase 15 Objective

Prove that Jarvis can run more than one already-existing, already-gated action as a single ordered job — with the same per-step security classification, the same approval flow, and the same audit trail every single-step action already has — without introducing any general workflow authoring capability, any new execution authority, or any new approval gate. The engine had to be built so narrowly that "can a user or the AI define a new workflow" has an unambiguous "no" answer at every layer.

---

## Scope and Non-Goals

**In scope:** three new optional `PlanStep` fields; two new runtime models (`WorkflowStepOutcome`, `WorkflowResult`); one new headless `WorkflowEngine` (`run`/`resume`/`has_paused`); one new deterministic workflow-plan factory producing exactly two fixed two-step plans; two new exact commands; orchestrator wiring reusing the existing approval flow; a CLI-visible, post-run workflow trace; seven new orchestration-only audit events; and the closure of two pre-existing (not Phase-15-introduced) audit-logger isolation gaps in `ToolExecutor` and `ApprovalManager`, discovered while exercising them under Phase 15's own multi-step, multi-approval activity.

**Explicitly out of scope, confirmed untouched or not introduced by this phase:** AI-authored or AI-planned workflows; natural-language or user-definable workflow syntax; arbitrary tool chaining; `depends_on`/branching/`ActionType.BRANCH`/`ActionType.PARALLEL_GROUP`; retries or any `OnFailure` policy beyond STOP; more than one concurrently active workflow; durable, crash-recoverable, or cross-restart workflow state; scheduled or background/proactive workflow execution; live/streaming step-by-step progress display; GUI, voice, phone, or computer-control surfaces; a plugin architecture; semantic/vector retrieval; multi-agent execution; any change to `SecurityManager.classify_action()`'s rule table, `ToolRegistry`, any concrete tool, `PromptBuilder`, `AIRouter`, or `AIReasoningEngine`.

---

## Repository Starting State

HEAD `9f074a5c21607f27475dec2b70266aae0c79433c` ("Centralize memory-summary AI availability messages and close Retrieval Workflow Maintenance"), full suite passing, working tree clean, before Phase 15 Batch 1 began.

---

## Batch Summaries

### Batch 1 — Minimal Multi-Step Plan and Workflow Runtime Models (commit `a8d7d03`)

Extended `planner/plan_models.py::PlanStep` with three fully backward-compatible optional fields: `tool_name: str | None = None`, `tool_input: dict[str, object] = field(default_factory=dict)`, `input_from_previous_step: bool = False`. Added `workflow/workflow_models.py` with `WorkflowStepOutcome` (strict `__post_init__` invariants tying each `StepStatus` to the fields it may/must carry) and `WorkflowResult` (enforcing only the last outcome may be non-`COMPLETED`, with derived `overall_status`/`pending_approval_request` properties). Zero existing Phase 1–14 construction site was affected — proven by the full pre-existing suite passing unmodified.

### Batch 2 — Headless Sequential Workflow Engine (commit `e75365e`)

Added `workflow/engine.py::WorkflowEngine`, a synchronous, single-workflow-at-a-time engine with exactly three public methods: `run(plan, *, session_id=None)`, `resume(workflow_id, decision, *, session_id=None)`, `has_paused(workflow_id)`. The engine sequences steps and delegates every single execution to the existing, unmodified `ToolExecutor` — it never imports `SecurityManager`, `ToolRegistry`, any concrete tool, or any AI module. A private `_PausedWorkflow` holds exactly the state needed to resume after a YELLOW approval pause. Seven narrow, orchestration-only audit events were added, each wrapped only around its own `logger.emit()` call.

### Batch 3 — Deterministic Workflow Commands and Orchestrator Wiring (commit `97780c9`)

Added `workflow/workflow_plan_factory.py` with exactly two builder functions, `build_remember_and_show_plan(content: str)` and `build_remember_and_forget_plan(content: str)`, each producing a fixed two-`PlanStep` `Plan` from hardcoded, pre-verified tier/reason constants — no `SecurityManager` dependency, no arbitrary tool-name selection possible from user input. Added the two exact command matchers to `CommandRouter` (mandatory colon, case-insensitive) and wired both into `JarvisOrchestrator`, reusing the existing `execute_approved()` approval path by storing `workflow_id` directly in `ApprovalRequest.metadata`.

### Batch 4 — CLI Workflow Trace and End-to-End Proof (commit `d4aa698`)

Added `WorkflowTraceStep`/`JarvisResponse.workflow_trace` (a default-empty tuple, fully backward compatible) and `Orchestrator._build_workflow_trace()`, converting an already-returned `WorkflowResult` into a CLI-displayable, **post-run** trace — never live/streaming progress. `ui/cli.py::format_response()` renders it when non-empty. Full end-to-end proof added through the real `ApprovalManager`, including the save-then-forget workflow's YELLOW pause, approval, and resume. During this batch's own investigation, a genuine in-memory paused-workflow leak was found and fixed: a missed approval timeout previously left a paused workflow permanently blocking all future `WorkflowEngine.run()` calls. Fixed with `_reap_stale_paused()`, which distinguishes genuine expiry from "decided but not yet resumed" using `ApprovalManager.has_pending()` together with `get_decision()`.

### Batch 4A — ToolExecutor Observability Isolation Closure (commit `6117503`)

Discovered while investigating Batch 4's own logger-isolation coverage: a raising audit logger at any of `ToolExecutor`'s five pre-existing emit sites propagated uncaught, losing an already-computed authoritative `ToolResult` — including, in one path, masking a genuine tool exception behind an unrelated logger failure. Empirically reproduced with a standalone script before any production change. Fixed with a new private `_emit_audit_event()` helper wrapping only the `logger.emit(...)` call itself in `try/except Exception: pass`; all five sites now route through it with byte-identical arguments. Not a Phase 15 regression — the defect pre-dated Phase 15 and was simply never exercised by a failing logger inside a multi-step workflow context until now.

### Batch 4B — ApprovalManager Observability Isolation Closure (commit `154f4d2`)

Same investigative method applied to a second collaborator, per the user's explicit follow-up instruction. Found a more severe variant: a raising audit logger during `approve()`/`decline()` left the decision durably recorded in memory (removed from `_pending`, added to `_decisions`) but the exception prevented the caller from ever learning this — permanently stranding any paused workflow waiting on that decision. A related failure during timeout-sweep could also corrupt an unrelated `has_pending()` check. Empirically reproduced before and after. Fixed with the identical narrow isolation pattern (`_emit_audit_event()`), applied to both `_audit()` and `_audit_timeout()`.

### Batch 5 — Final Review, Documentation, and Closure (this report)

Detailed in full below.

---

## Exact Command Grammar

| Command | Workflow | Step 1 | Step 2 |
|---|---|---|---|
| `remember this and show it back: <text>` | save-then-show | `memory` save (GREEN) | `memory` get (GREEN) |
| `remember this and forget it: <text>` | save-then-forget | `memory` save (GREEN) | `memory_forget` (YELLOW, requires approval) |

Both matched case-insensitively via `.casefold().startswith()` against the exact literal prefix including the mandatory trailing colon, in `core/command_router.py::match_remember_and_show_back_workflow`/`match_remember_and_forget_workflow`. No other phrasing (missing colon, `"and then"`, semicolons, or any other connector) matches — such text falls through to ordinary single-step command handling, exactly as before Phase 15.

---

## Capability Audit — What Phase 15 Does and Does Not Provide

**Does provide:** exactly two fixed, hardcoded, two-step workflows; per-step, live re-classification through the unmodified `SecurityManager`/`ToolExecutor`; a single structured data-flow mechanism (`memory_id` propagated from step 1's `ToolResult.metadata` into step 2's `tool_input`); approval pause/resume for a YELLOW step, reusing the existing `ApprovalManager` unmodified; STOP-only failure semantics; a post-run CLI trace; seven orchestration-only audit events.

**Does NOT provide, and must not be described as providing:** general autonomous planning; AI-created or AI-suggested workflows; arbitrary user-defined workflows or tool chaining; more than two steps; more than one data field propagated between steps; more than one active workflow at a time; live/streaming progress; durable or crash-recoverable workflow state; scheduled, background, or proactive workflow execution; retries of a failed step; rollback of an already-applied side effect; branching or parallel execution; any new approval gate beyond the existing single-decision flow; any new AI execution authority.

---

## Final Planning-Authority Review

Confirmed by direct inspection of `workflow/workflow_plan_factory.py`: both builder functions take only `content: str`, select from exactly two fixed tool names (`"memory"`, `"memory_forget"`) hardcoded as module constants, and construct `PlanStep`s with hardcoded `tier`/`reason` values never derived from user input and never derived by calling `SecurityManager`. There is no code path by which user-supplied text can select a tool name, a tier, or a step count — the only user-controlled value is the memory content string itself. Planning authority is therefore fully deterministic and closed.

---

## Final Execution-Authority Review

Confirmed by direct inspection of `workflow/engine.py`: `WorkflowEngine` holds no reference to `SecurityManager`, `ToolRegistry`, or any concrete tool class, and its module-level imports contain none of these. Every step's actual execution is delegated to `self._executor.execute(...)` — the same, unmodified `ToolExecutor` instance every non-workflow action already uses, which performs its own fresh `SecurityManager.classify_action()` call at the moment of execution. `PlanStep.tier` is read by `WorkflowEngine` nowhere; grepped and confirmed absent from `workflow/engine.py`. Execution authority is therefore identical, per step, to every pre-Phase-15 action, and is fully closed.

---

## Structured Data-Flow Closure Review

Confirmed: the sole propagated field is the module constant `_PROPAGATED_FIELD = "memory_id"` in `workflow/engine.py`. `_resolve_tool_input()` reads only `ToolResult.metadata.get("memory_id")` from the immediately preceding `COMPLETED` outcome, and only when the current step's `PlanStep.input_from_previous_step` is `True`. No parsing of `.message`/`.output`, no AI involvement, no arbitrary earlier-step reference, and no general templating exist anywhere in this path. This is the one narrow mechanism both workflows rely on to pass the just-saved memory's id into their second step.

---

## Approval Pause/Resume Closure Review

Confirmed: no new approval model was introduced. A YELLOW step's `ToolResult.requires_confirmation=True` and its `ApprovalRequest` produce a `WAITING` `WorkflowStepOutcome`; the workflow's own `workflow_id` is stored directly in `ApprovalRequest.metadata["workflow_id"]` — no separate correlation id was invented. `JarvisOrchestrator.execute_approved()` now checks `_paused_workflow_id_for(response)` first (validating both that the metadata key is present and that `WorkflowEngine.has_paused(workflow_id)` is true) before delegating to `WorkflowEngine.resume()`; if neither condition holds, it falls through to the exact, byte-for-byte original single-tool approval body. The public `execute_approved(response, decision)` signature is unchanged.

---

## Workflow State/Result Closure Review

Confirmed via `workflow/workflow_models.py`: `WorkflowStepOutcome.__post_init__` enforces, per status, exactly which fields may be present (`PENDING`/`RUNNING` carry nothing; `WAITING` requires both a confirmation-required `ToolResult` and an `ApprovalRequest`; `COMPLETED` requires a successful `ToolResult` and no approval request; `FAILED` requires a failed `ToolResult` and no approval request; `PAUSED`/`SKIPPED` are rejected outright — never produced by Phase 15). `WorkflowResult.__post_init__` enforces only the last outcome in `step_outcomes` may be non-`COMPLETED`. `overall_status` derives cleanly from the last outcome; `RUNNING` never appears in a returned `WorkflowResult`, since the synchronous engine only returns once the run loop has stopped.

---

## STOP-Only Failure Review

Confirmed by direct inspection of `_run_from()`/`_stop()` in `workflow/engine.py`: the first non-`COMPLETED` step outcome (`FAILED`, a RED-blocked step surfaced as `FAILED` via `ToolResult.blocked=True`, or `WAITING`) ends the workflow immediately. No retry loop exists anywhere. No already-applied side effect (e.g., a memory already saved by step 1) is ever rolled back when step 2 fails or is blocked. Steps never attempted are simply absent from `step_outcomes` — Phase 15 never synthesizes a `SKIPPED`/`PENDING` placeholder for them.

---

## Workflow Trace/Presentation Closure Review

Confirmed: `WorkflowTraceStep`/`JarvisResponse.workflow_trace` is built once, by `Orchestrator._build_workflow_trace()`, from an already-complete `WorkflowResult` — after `run()`/`resume()` has returned. There is no callback, no partial-trace emission mid-run, and no mechanism by which the CLI could observe a step while it is still executing. This is an explicit, deliberate restatement of Batch 2's own original rejection of a live-progress callback design.

---

## Workflow Audit-Event Review

Confirmed exactly seven events, all emitted only from `workflow/engine.py`: `workflow_started`, `workflow_step_started`, `workflow_step_completed`, `workflow_step_waiting`, `workflow_step_failed`, `workflow_completed`, `workflow_stopped`. Each carries orchestration-state fields only (workflow id, step index/description, status) — never tool input, never memory content, never duplicating the `tool_call`/`security_classification`/`approval_*` events `ToolExecutor`/`ApprovalManager` already emit for the same underlying step.

---

## ToolExecutor Observability Closure Review — CLOSED

**Status: CLOSED, not carried-forward debt.** The defect (a raising logger propagating uncaught through any of five emit sites, losing an authoritative `ToolResult` or masking a genuine tool exception) was empirically reproduced in Batch 4A before any fix, and empirically re-verified absent after the fix. `_emit_audit_event()` now wraps only the `logger.emit(...)` call in `try/except Exception: pass` at all five sites, with security classification, tool execution, and result construction entirely outside that block. 23 dedicated tests in `tests/unit/test_tool_executor_logger_isolation.py`, plus workflow-level proofs in `tests/unit/test_cli_workflow_commands.py`, confirm a failing logger never alters an outcome. This is not listed as risk/debt below.

---

## ApprovalManager Observability Closure Review — CLOSED

**Status: CLOSED, not carried-forward debt.** The more severe defect (a raising logger during `approve()`/`decline()` leaving the decision durably recorded but never returned to the caller, permanently stranding a paused workflow; a related timeout-sweep failure corrupting an unrelated `has_pending()` check) was empirically reproduced in Batch 4B before any fix, and empirically re-verified absent after the fix. Both `_audit()` and `_audit_timeout()` now route through the same narrow `_emit_audit_event()` pattern. 28 dedicated tests in `tests/unit/test_approval_manager_logger_isolation.py`, plus workflow-level proofs, confirm this. This is not listed as risk/debt below.

---

## Full Observability-Invariant Review — Scoped to the Phase 15 Execution Chain

Scope: `WorkflowEngine`, `ToolExecutor`, `ApprovalManager`, and the orchestrator's workflow-dispatch helpers only — not a whole-repository audit. The standing invariant, restated: **a logger/observability failure must never alter an authoritative workflow outcome.** Confirmed closed across all four:

- `WorkflowEngine._emit`/`_emit_step_event` — narrow isolation since Batch 2, never modified since.
- `ToolExecutor._emit_audit_event` — closed in Batch 4A (above).
- `ApprovalManager._emit_audit_event` — closed in Batch 4B (above).
- `Orchestrator`'s workflow-dispatch helpers (`_handle_workflow_request`, `_paused_workflow_id_for`, `_workflow_result_to_response`, `_build_workflow_trace`) contain no logger calls of their own — they only translate already-computed, already-audited results.

The three symptom shapes found across Phase 15's history are distinct and not claimed identical: the historical `AIRouter` bug (Phase 8-era, pre-Phase-15) was **silent misrepresentation** (a real success converted into "reasoning unavailable"); `ToolExecutor`'s was a **loud crash** (an uncaught exception); `ApprovalManager`'s was **silent authoritative-state orphaning** (the decision was real and recorded, but the caller never learned it happened). All three now honor the same standing invariant, via the same narrow pattern, without being the same defect.

---

## Timeout/Paused-State Closure Review

Confirmed: `_reap_stale_paused()` (added Batch 4) runs at the start of both `run()` and `has_paused()`. For each entry in the in-memory `_paused` map, it checks `ApprovalManager.has_pending(request_id)`; if `False`, it attempts `get_decision(request_id)` — an `ApprovalError` means the request genuinely expired with no decision ever recorded (reaped), while a successful `get_decision()` means a decision was recorded but not yet resumed (left in place, not reaped). This distinction was necessary because `has_pending()` alone returns `False` in both cases. Proven by dedicated tests in `tests/unit/test_workflow_engine.py` that a stale, expired pause is reaped and does not block a subsequent `run()`, while a decided-but-not-yet-resumed pause is never prematurely discarded.

---

## Concurrency Closure Review

Confirmed: Phase 15 is fully synchronous. `run()` raises `WorkflowError` if `self._paused` is already non-empty — only one workflow may be paused awaiting approval at a time. There is no asyncio, threading, or process pool anywhere in `workflow/engine.py` or its call sites. This is naturally sufficient given the CLI's own single-threaded, blocking `input()` loop; it is not, and is not claimed to be, a general concurrency-safety guarantee for any future multi-session or networked front end.

---

## Existing-Subsystem Compatibility Review

Confirmed by full-suite regression (below) and by direct diff inspection: no behavioural line of `SecurityManager`, `ToolRegistry`, any concrete tool, `PromptBuilder`, `AIRouter`, `AIReasoningEngine`, `MemoryManager`, or any Phase 1–14 command handler was touched. `JarvisOrchestrator.__init__`'s new `workflow_engine` parameter defaults to `None` and is fully backward compatible; `PlanStep`'s three new fields and `JarvisResponse.workflow_trace` all default safely. Every pre-existing Phase 1–14 test passes unmodified.

---

## Plan-vs-Implementation Reconciliation

Performed in full as **§29 (Batch 5 Closure Addendum)** of `docs/phase_15_implementation_plan.md`, appended (not retroactively rewritten) after the plan's original 28 sections. Nine specific points of divergence were found and classified: eight as **B** (a disclosed, narrow, repository-grounded refinement made and reported at the time) and one point covering three related items as **C** (a corrective closure of a real, empirically-reproduced defect not anticipated by the plan at all: stale-paused-workflow reaping, `ToolExecutor` logger isolation, `ApprovalManager` logger isolation). **Finding: there are no unresolved D (undisclosed deviation) or E (scope creep) items anywhere in Phase 15.**

---

## Full Phase-15 Diff Classification

Every file changed between `9f074a5` and `154f4d2` (20 files, 5,883 insertions, 30 deletions) classifies as:

- **A (required workflow models):** `planner/plan_models.py`, `workflow/workflow_models.py`, `tests/unit/test_plan_models.py`, `tests/unit/test_workflow_models.py`.
- **B (required headless engine):** `workflow/engine.py`, `tests/unit/test_workflow_engine.py`.
- **C (required deterministic workflow planning/routing):** `workflow/workflow_plan_factory.py`, `tests/unit/test_workflow_plan_factory.py`, `core/command_router.py`, `tests/unit/test_command_router.py`, `core/orchestrator.py` (planning/routing portions), `tests/unit/test_orchestrator_workflow_commands.py`, `main.py`.
- **D (required CLI trace/end-to-end integration):** `core/request_models.py`, `ui/cli.py`, `core/orchestrator.py` (trace-building portion), `tests/unit/test_cli_workflow_commands.py`.
- **E (required Phase 15 integration defect correction):** the `_reap_stale_paused()` addition inside `workflow/engine.py`, and its tests inside `tests/unit/test_workflow_engine.py`.
- **F (required standing-invariant closure):** `tools/executor.py`, `tests/unit/test_tool_executor_logger_isolation.py`, `approval/approval_manager.py`, `tests/unit/test_approval_manager_logger_isolation.py`.
- **G (required tests/proof):** covered inline above — every test file listed is itself a G in addition to its structural category.
- **H (required documentation/closure):** `README.md`, `docs/phase_15_implementation_plan.md`, `docs/phase_15_completion_report.md` (this report).
- **I (unrelated/scope creep): none found.**

---

## Direct Architecture Inspection Summary

`planner/plan_models.py` — three new optional fields, no behavioural change to existing construction. `workflow/workflow_models.py` — two new frozen-shape dataclasses with strict `__post_init__` invariants, no dependency on any other Phase 15 file. `workflow/engine.py` — no imports of `SecurityManager`/`ToolRegistry`/concrete tools/AI modules; all execution delegated to the injected `ToolExecutor`. `workflow/workflow_plan_factory.py` — no `SecurityManager` dependency; two fixed builder functions only. `core/orchestrator.py` — workflow dispatch is two new pre-fallback checks plus shared glue; `execute_approved()`'s original single-tool body is preserved unchanged as a fallback. `ui/cli.py` — an additive, empty-by-default trace-rendering block. `tools/executor.py` — five emit sites now routed through one narrow helper; no change to classification or execution logic. `approval/approval_manager.py` — two emit call sites (`_audit`, `_audit_timeout`) now routed through the same narrow helper; no change to decision-recording or timeout-sweep logic.

---

## Exact Files Changed, By Batch

- **Batch 1** (`a8d7d03`): `planner/plan_models.py`, `workflow/workflow_models.py` (new), `tests/unit/test_plan_models.py` (new), `tests/unit/test_workflow_models.py` (new).
- **Batch 2** (`e75365e`): `workflow/engine.py` (new), `tests/unit/test_workflow_engine.py` (new).
- **Batch 3** (`97780c9`): `workflow/workflow_plan_factory.py` (new), `core/command_router.py`, `core/orchestrator.py`, `main.py`, `tests/unit/test_workflow_plan_factory.py` (new), `tests/unit/test_command_router.py`, `tests/unit/test_orchestrator_workflow_commands.py` (new).
- **Batch 4** (`d4aa698`): `core/request_models.py`, `core/orchestrator.py`, `ui/cli.py`, `workflow/engine.py` (`_reap_stale_paused`), `tests/unit/test_cli_workflow_commands.py` (new), `tests/unit/test_workflow_engine.py` (extended), `tests/unit/test_orchestrator_workflow_commands.py` (extended).
- **Batch 4A** (`6117503`): `tools/executor.py`, `tests/unit/test_tool_executor_logger_isolation.py` (new), `tests/unit/test_cli_workflow_commands.py` (extended).
- **Batch 4B** (`154f4d2`): `approval/approval_manager.py`, `tests/unit/test_approval_manager_logger_isolation.py` (new), `tests/unit/test_cli_workflow_commands.py` (extended).
- **Batch 5** (this closure): `README.md`, `docs/phase_15_implementation_plan.md` (tracked, §29 addendum added), `docs/phase_15_completion_report.md` (this report).

**Not touched anywhere in Phase 15:** `SecurityManager`, `ToolRegistry`, any concrete tool implementation, `PromptBuilder`, `AIRouter`, `AIReasoningEngine`, `AIReasoningRequest`, `MemoryManager`, `MemoryTool`, `EpisodicMemoryStore`, `ai/memory_selection.py`, `ai/memory_ingestion.py`, any Phase 1–14 command handler or matcher.

---

## Full-Suite Totals Before and After Phase 15

| | Total |
|---|---|
| Before Phase 15 (Retrieval Workflow Maintenance closure) | 1546 |
| After Batch 4B (pre-closure baseline for this batch) | 1815 |
| After Batch 5 (final, this closure) | see Final Test Result below |

---

## Final Test Result

**Full suite, run directly in the development environment** (`poetry run pytest -q`, Python 3.14.6, pytest 9.1.1) — see the verification run performed as part of this closure, recorded in the final closure report delivered alongside this document.

No live Claude API call is made anywhere in the suite.

### Test commands

```powershell
poetry run pytest -v

poetry run pytest tests/unit/test_plan_models.py -v
poetry run pytest tests/unit/test_workflow_models.py -v
poetry run pytest tests/unit/test_workflow_engine.py -v
poetry run pytest tests/unit/test_workflow_plan_factory.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/unit/test_orchestrator_workflow_commands.py -v
poetry run pytest tests/unit/test_cli_workflow_commands.py -v
poetry run pytest tests/unit/test_tool_executor_logger_isolation.py -v
poetry run pytest tests/unit/test_approval_manager_logger_isolation.py -v
```

---

## Git/Diff Verification

`git diff --check` — exit 0 (only pre-existing LF/CRLF line-ending warnings across the repository, not new errors). Full diff from pre-Phase-15 HEAD `9f074a5c21607f27475dec2b70266aae0c79433c` inspected directly; every material change classifies as a required Phase 15 capability, a required Phase 15 defect correction, or required documentation/closure — no unrelated or scope-creep change was found (see Full Phase-15 Diff Classification above; no Category I).

---

## Risks and Debt Carried Forward

**A — Intentional limitations (by design, not defects):**
- Workflow state is in-memory only; a process restart mid-pause loses that specific paused workflow (not any already-applied tool side effect, and not the audit trail).
- Only one field (`memory_id`) can ever be propagated between steps, and only from the immediately preceding step — not a general data-flow mechanism.
- Only one workflow may be paused at a time; a second `run()` while one is paused raises `WorkflowError`.
- The workflow trace is a post-run summary, never a live/streaming view.
- Exactly two workflows exist; there is no mechanism for a user or the AI to define a third.

**B — Architectural debt (pre-existing, unrelated to Phase 15, unaffected by it):** the broad `CommandRouter.match()` keyword-overlap risk; the `ToolExecutor`/`classify_action()` bypass asymmetry for direct AI memory reads; the AST invariant's dynamic-dispatch blind spot; the SQLite naive-timestamp-on-read-back debt. None of these was touched, worsened, or improved by Phase 15.

**C — Prerequisites for specific future capabilities (not started here):**
- **Scheduling or background/proactive workflow execution** would require a durable, crash-recoverable workflow-state design (Phase 15's in-memory `_paused` map is explicitly insufficient for this) and a re-review of the single-active-workflow concurrency assumption, which today relies on the CLI's own single-threaded blocking loop.
- **Remote or phone-based execution** would require a review of how approval pause/resume interacts with a non-local, potentially disconnected client, which Phase 15 has never been exercised against.
- **Computer/application control** would require an entirely new tool and security-tier category this phase does not define or touch.
- **AI-assisted or AI-authored planning** would require a fresh security review of what it means for an AI to select or construct a step sequence, distinct from today's fixed, hardcoded, human-authored two plans — Phase 15's deterministic plan factory is explicitly not a template for this.

**Explicitly not listed as debt:** the ToolExecutor and ApprovalManager audit-logger isolation issues found in Batches 4A/4B are **closed**, not carried-forward debt — see their dedicated closure reviews above.

---

## Recommended Next Architectural Action

None is selected or authorized by this report. Phase 15 unlocks the underlying mechanics a future scheduling, remote-execution, or AI-planning capability would need, but none of those is thereby pre-authorized — each requires its own separately-scoped design and security review, per the prerequisites listed above. The next architectural direction is intentionally left open pending fresh review.

---

## Status Statement

**Phase 15 complete for its defined scope: a minimal, fully deterministic, two-step Sequential Workflow Engine, with every step individually classified and gated by the completely unmodified `SecurityManager`/`ToolExecutor`, reusing the existing `ApprovalManager` unchanged for its one pause/resume case, with zero changes to `SecurityManager`, `ToolRegistry`, any concrete tool, or any AI module, and with both a genuine in-engine state-leak defect and two pre-existing audit-logger isolation defects found, empirically reproduced, and closed along the way.**

Phase 15 is not, and must not be described as, general-purpose workflow execution, AI-planned or AI-authored automation, user-definable workflow syntax, durable or crash-recoverable job execution, or scheduled/background/proactive automation — it is exactly two fixed, hardcoded, two-step jobs, gated the same way every single Jarvis action already was.
