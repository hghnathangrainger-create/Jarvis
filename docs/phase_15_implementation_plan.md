# Phase 15 Implementation Plan — Sequential Workflow Execution (Minimal Multi-Step Planner and Workflow Engine)

Status: **Planning and adversarial architecture review only. No production code,
tests, or README changes accompany this document.**

Authoritative repository state this plan builds on, verified directly, not
assumed: HEAD `9f074a5c21607f27475dec2b70266aae0c79433c` ("Centralize
memory-summary AI availability messages and close Retrieval Workflow
Maintenance"), branch `phase-4-ai-reasoning-and-write-actions`, working tree
clean. `poetry run pytest -q` — **1565 passed, 0 failed** — re-run fresh for
this planning turn. No pre-existing failure exists.

---

## 1. Purpose

The big-picture architectural review (previous turn) found that every
Jarvis request today is handled as a single, immediate, reactive step:
Planner emits exactly one `PlanStep`, the Orchestrator runs at most one tool
call or one AI-advisory reply, and returns. The `workflow/` package is an
empty `__init__.py`, despite `config/constants.py` having pre-declared its
data model (`StepStatus`, `ActionType`, `OnFailure`) since early phases.
Every later-envisioned capability (scheduling, proactive behaviour, project
management, content automation, multi-agent coordination) depends on a real
multi-step execution engine existing first. Phase 15 builds the smallest
honest version of that engine: a linear, deterministic, individually
security-gated chain of two or more already-existing actions, with visible
step-by-step progress.

**This is explicitly not the full Chapter 10 Workflow Engine.** No
branching, no parallel groups, no retries, no cross-restart checkpointing,
no AI-authored steps.

---

## 2. Repository Truth (fresh re-inspection)

- **Branch:** `phase-4-ai-reasoning-and-write-actions`. **HEAD:**
  `9f074a5c21607f27475dec2b70266aae0c79433c`. **Status:** clean.
- **Full suite:** 1565 passed, 0 failed, re-run before this planning turn.
- **`main.py`** wires exactly one composition root: settings → DB →
  `EventLogger`/`SecurityManager` → `MemoryManager` → `ApprovalHistoryStore`
  + `ApprovalManager` → `Planner(security)` → `ToolRegistry` (10 hardcoded
  tools) → `ToolExecutor` → `CommandRouter(registry)` → optional single-
  provider `AIReasoningEngine` → `JarvisOrchestrator` → `JarvisCLI`.
- **`JarvisOrchestrator.handle_request()`** (`core/orchestrator.py:528`)
  dispatches, in hardcoded precedence order, to one of seven Phase 8–14
  AI-summary terminal handlers, else falls through to `_handle_request_core`
  (`core/orchestrator.py:2661`).
- **`_handle_request_core`**: `plan = self._planner.create_plan(text)` →
  `tool_name = self._command_router.match(text)` → if matched,
  `self._executor.execute(tool_name, tool_input, session_id=...)`,
  translated to a `JarvisResponse` by `_tool_response`; if not matched,
  falls back to the plan's own single-step classification
  (`_blocked_response`/`_confirmation_response`/`_unrecognised_green_response`).
  **Confirmed: exactly one tool call per request today, never more.**
- **`CommandRouter`** (`core/command_router.py`): stateless regex/prefix
  matcher. `match(text) -> str | None` returns **at most one** registered
  tool name. `build_input(tool_name, text) -> dict` builds that one tool's
  input. Seven separate `match_*_summary` methods exist for the Phase 8–14
  AI-workflow terminal handlers, checked before `match()` in
  `handle_request()`.
- **`Planner.create_plan()`** (`planner/planner.py:72`): stateless aside
  from its `SecurityManager`. `_draft_steps()` always returns a **list of
  exactly one** `_DraftStep` (five keyword-group checks, each returning one
  step; the default fallback also returns one step). **Confirmed: the
  Planner cannot produce a multi-step plan today under any input.**
- **`Plan`/`PlanStep`** (`planner/plan_models.py`): frozen dataclasses.
  `PlanStep` has exactly `number, description, action, tier, reason` — **no
  `tool_name`, `tool_input`, `depends_on`, `on_failure`, `retry`, or status
  field of any kind.** `Plan` has `user_request, steps` plus derived
  properties (`requires_confirmation`, `has_blocked_steps`, `is_empty`,
  `highest_tier`).
- **`workflow/`**: contains only `__init__.py`, 0 lines of code. Confirmed
  via direct listing. `Planner`'s own docstring states "Does NOT: ...
  Connect to the Workflow Engine."
- **`config/constants.py`** enums (all confirmed via direct read):
  - `ActionType`: `AI_CALL`, `TOOL_CALL`, `USER_APPROVAL`, `BRANCH`,
    `PARALLEL_GROUP` — none referenced anywhere outside their own
    definition.
  - `StepStatus`: `PENDING`, `RUNNING`, `WAITING`, `PAUSED`, `COMPLETED`,
    `FAILED`, `SKIPPED` — none referenced anywhere outside their own
    definition.
  - `OnFailure`: `RETRY_WITH_ALTERNATIVE_PROVIDER`,
    `RETRY_WITH_ALTERNATIVE_TOOL`, `SKIP`, `ESCALATE_TO_USER`,
    `ABORT_PLAN` — none referenced anywhere outside their own definition.
  - `IntentType` — also unused; irrelevant to Phase 15 (no intent
    classifier exists or is proposed).
- **`SecurityManager.classify_action()`** (`security/security_manager.py`):
  deterministic ~45-rule keyword table, RED-first then YELLOW then GREEN,
  cautious YELLOW default for unmatched actions. Real, tested, unchanged by
  this plan.
- **`ToolExecutor.execute()`** (`tools/executor.py:77`): **re-classifies
  every call itself** via `self._security.classify_action(tool.action_for(request))`
  — it never trusts any tier passed in from a `Plan`/`PlanStep`. RED is
  blocked unconditionally before any approval decision is even consulted.
  YELLOW runs only with an explicit approved `ApprovalDecision`, otherwise
  returns `requires_confirmation=True`. GREEN always runs. **This is the
  single existing authority boundary Phase 15 must reuse unchanged.**
- **`ApprovalManager`** (`approval/approval_manager.py`): in-memory pending
  requests (`_pending: dict[str, ApprovalRequest]`, keyed by
  `request_id`), durable decision/creation history via
  `ApprovalHistoryStore` (never rehydrated on restart, by explicit
  design). `create_request(action, reason, security_tier, *, session_id=None, metadata=None)`
  **already accepts an arbitrary `dict[str, str]` metadata parameter** —
  confirmed by direct read. YELLOW timeout (`timeout_seconds`, default 60s
  in `main.py`) aborts a pending request; RED never enters this lifecycle
  (rejected by `ApprovalRequest`'s own validation before reaching pending
  state).
- **`ApprovalHistoryStore`**: durable, append-only, no `tool_name`/
  `tool_input` columns — history for review only, never resumable from
  storage. Unaffected by this plan.
- **`ToolRegistry`**: plain `dict[str, BaseTool]`, explicit
  `register_tool()` only. No plugin/manifest loading (out of scope,
  unrelated to this plan).
- **`EventLogger.emit()`** (`observability/logger.py:148`): `source,
  action_type, outcome, detail=None, duration_ms=None, security_tier=None,
  session_id=None`. Every existing subsystem (`ToolExecutor`,
  `ApprovalManager`, `AIRouter`) already uses this one call shape.
- **`JarvisResponse`** (`core/request_models.py`): `success, message,
  plan, tool_result, requires_confirmation, blocked, approval_request,
  tool_name, tool_input, ai_suggestion`. **`tool_name`/`tool_input` are
  exactly how today's single-step YELLOW-pending case carries "what to
  re-run" forward to `execute_approved()`.**
- **`JarvisOrchestrator.execute_approved(response, decision)`**
  (`core/orchestrator.py:443`): re-runs `response.tool_name`/
  `response.tool_input` through `ToolExecutor.execute(..., approval_decision=decision)`
  if `decision.is_approved`; otherwise returns an honest "declined" response.
  **Confirmed: the approval lifecycle is fully asynchronous/return-based —
  `handle_request()` never blocks waiting for approval.** There is no
  existing synchronous-block-and-wait primitive anywhere in the codebase.
- **`ui/cli.py`**: `JarvisCLI.run()` is a blocking, single-threaded REPL.
  `handle_request()` → print → if `response.approval_request is not None`,
  prompt via `ui/approval_prompt.py`, record decision via
  `orchestrator.approvals.approve/decline(request_id, ...)`, then if
  approved, call `orchestrator.execute_approved(response, decision)` and
  print that result. **Confirmed: the process is single-threaded and
  strictly serial by construction — no workflow can run concurrently with
  another, or with the CLI's own blocking `input()` call, without new
  concurrency machinery this plan does not propose.**
- **`AIReasoningEngine`**: holds no reference to `ToolExecutor`,
  `ApprovalManager`, or `SecurityManager` — structurally incapable of
  executing anything. Advisory only, by construction, unrelated to Phase 15
  except as an explicitly-deferred future step type (§12).
- **Unexpected-AI-action handling** (`_evaluate_unexpected_actions`,
  `core/orchestrator.py:2568`): verdict/audit only
  (FLAG/ESCALATE/BLOCK → FLAGGED/PENDING/BLOCKED `EventOutcome`), never
  executes anything. Unrelated to and unaffected by this plan.
- **Every current production call to `Planner.create_plan()`**: exactly one
  site, `core/orchestrator.py:2692` inside `_handle_request_core`. (The
  seven Phase 8–14 special-case handlers each call it once too, at their
  own top, for the same single-step transparency purpose — confirmed via
  grep, eight total call sites, all producing single-step plans today.)
- **Every current production call to `ToolExecutor.execute()`**: two sites
  — `core/orchestrator.py` inside `_handle_request_core`'s tool-matched
  branch, and inside `execute_approved`. No other call site exists.
- **Every current production approval-request-creation site**: two —
  `_confirmation_response` (plan-only YELLOW, no tool) and `_tool_response`
  (tool-backed YELLOW), both in `core/orchestrator.py`, both calling
  `self._approvals.create_request(...)`.

---

## 3. Master Specification Workflow Requirements — Exact Chapter Boundaries

Re-read directly from `docs/JARVIS_PROJECT_MASTER_SPECIFICATION_V2_1.md`
(Version 2.1):

- **Chapter 6 — Planner**: goal decomposition, dependency identification,
  parallel-task identification, recovery-strategy attachment, the full
  **Plan Schema** (Plan ID, Goal, Success Criteria, Created At, Steps; each
  Step: Step ID, Description, Action Type, Depends On, Inputs, Expected
  Output, Security Tier, Retry Policy, On Failure, On Success, Optional).
  Explicitly: "The Planner does not return executable code. It returns a
  plan," and "The Planner never calls AI providers directly... all AI
  assistance is requested through the Jarvis Core."
- **Chapter 10 — Workflow Engine**: executes, monitors, coordinates
  workflows; task states (Pending/Running/Waiting/Paused/Completed/
  Failed/Skipped — **exact match to the existing `StepStatus` enum**);
  checkpoint-to-database after each step, crash recovery, retries,
  approval-timeout-triggered pause; explicitly "The Workflow Engine does
  not generate workflows. Planning belongs to the Planner."
- **Chapter 11 — Tool Manager**: manifest-based plugin registry,
  sandboxing. Unrelated to Phase 15 (no new tools are added; existing
  `ToolExecutor`/`ToolRegistry` are reused unchanged).
- **Chapter 12 — Security Manager**: GREEN/YELLOW/RED, "No subsystem is
  permitted to bypass this validation process," approval timeout policy
  (YELLOW 60s default/abort-and-preserve-state; RED waits indefinitely),
  unexpected-action escalation. **Directly governs §7 of this plan.**
- **Chapter 29 — System Lifecycle**: startup restores "any interrupted
  workflows from checkpoints" — a durable, cross-restart capability
  explicitly deferred (§19).
- **Chapter 30 — Subsystem Interfaces**: "Workflow Engine → Security
  Manager: individual step from active plan, with parameters and declared
  tier → Approval decision: proceed, wait for user, or block permanently";
  "Workflow Engine → Tool Manager: tool name, validated input parameters,
  execution context → structured result."

### Classification

**A. Requirements Phase 15 must satisfy now:**
- Individual per-step security classification (Ch.12) — non-negotiable,
  already the repository's own invariant.
- A real, ordered, multi-step Plan that is genuinely executed, not merely
  described (Ch.6/10's core distinction between planning and execution).
- Step states drawn from the existing `StepStatus` vocabulary (Ch.10).
- The Planner does not execute; the Workflow Engine does not plan (Ch.6/10
  design separation) — already a repository convention worth preserving.

**B. Long-term requirements that may be deferred:**
- Full Plan Schema fields (Retry Policy, On Failure variety, Optional,
  parallel groups, branching) — Ch.6's schema is the eventual target, not
  a Phase 15 requirement.
- Checkpoint-to-database, crash recovery, cross-restart resumption (Ch.10,
  Ch.29) — explicitly deferred, §19.
- Multiple simultaneous workflows, dependency graphs across non-adjacent
  steps (Ch.6 "Future Expansion") — deferred, §20.

**C. Aspirational behaviour without a current technical contract:**
- AI-assisted goal decomposition (Ch.6 "Planning Process": "Understand
  Intent → Retrieve Context → ... → Generate Workflow") — no such AI
  planning contract exists in code today (`Planner` never calls AI); Phase
  15 must not invent one incidentally.
- Dynamic replanning mid-execution (Ch.6) — no current mechanism, not
  proposed here.

**D. Requirements that would be dangerous to partially implement in
Phase 15:**
- A "Retry Policy"/`OnFailure` value that silently retries a YELLOW/RED
  action without re-running it through the full classify-then-approve
  gate — would create a second, weaker authority path. Excluded (§11).
- A Plan-level or Step-level stored security tier that the Workflow Engine
  trusts instead of re-classifying at execution time — would silently
  reopen the exact class of bypass `ToolExecutor` was built to prevent.
  Explicitly rejected (§17).
- Any mechanism letting AI output become a later step's executable
  arguments without a deterministic translation boundary — directly
  named as the invariant to protect in the task instructions themselves
  (§12).

---

## 4. Exact Phase 15 User-Facing Workflow Slice

### Candidates evaluated

| Candidate | Planning authority | Execution authority | Security risk | New architecture | Proves a real Workflow Engine? | Second authority risk |
|---|---|---|---|---|---|---|
| A. Exact deterministic workflow command(s) with predefined steps | A small, dedicated deterministic factory | Existing `ToolExecutor` per step | Low — reuses existing gate exactly | Smallest: one factory + one engine | Yes — genuine multi-tool chaining with real inter-step data | None |
| B. Command accepting a fixed sequence of existing tool actions (a mini chaining grammar) | A new parser interpreting arbitrary "X then Y" phrasing | Existing `ToolExecutor` per step | Low, but larger parsing surface | Larger: needs a general two-verb grammar | Yes, more flexibly | None, but more design surface for a first vertical |
| C. `Planner.create_plan()` itself deterministically expands certain existing single requests into 2+ steps | `Planner` | Existing `ToolExecutor` per step | Low | Moderate: complicates the Planner's existing single-step contract for every caller, including the seven Phase 8-14 handlers that expect one step | Yes | Risk of accidentally changing single-step behavior for existing commands |
| D. AI proposes a multi-step plan; Jarvis validates before deterministic execution | AI (proposal) + deterministic validator (conversion) | Existing `ToolExecutor` per step | **High** — first-ever AI influence over executable step shape, even if validated | Large: needs a new validation/translation boundary with no precedent | Yes, but at meaningfully higher risk | Real risk if the validator has any gap |
| E. Other | — | — | — | — | — | — |

### Decision

**Candidate A — exact deterministic workflow command(s) with predefined
steps.** Rejected B (larger, unnecessary parsing surface for a first
vertical — a "chain any two verbs" grammar is exactly the kind of premature
generality this plan's own governing instructions warn against). Rejected C
(touches the Planner's existing single-step contract, which every one of
the eight current call sites — `_handle_request_core` plus the seven
Phase 8–14 handlers — depends on remaining single-step; overloading
`create_plan()` risks a regression in already-shipped behaviour for no
Phase-15 benefit). Rejected D (AI-authored plans; explicitly the highest-
risk candidate and squarely against the standing "AI reasoning is advisory,
never execution authority" invariant — see §5).

**Exact new commands, following the same "one dedicated `CommandRouter`
matcher + one dedicated `JarvisOrchestrator` handler" convention already
established by the seven Phase 8–14 AI-summary commands:**

1. `"remember this and show it back: <text>"` → a fixed two-step workflow:
   save a new memory, then immediately show it back by the id just
   created. All-GREEN.
2. `"remember this and forget it: <text>"` → a fixed two-step workflow:
   save a new memory, then forget that exact memory by id. GREEN → YELLOW.

Both reuse only already-existing, unmodified tools (`memory` operation
`save`/`get`, `memory_forget`) — no new tool is added. Both are genuinely
useful (a save-with-immediate-confirmation pattern, and a
save-then-retract pattern), not contrived demos invented solely to exercise
the engine.

The third required proof (a later step must never run after an earlier
block/failure) is deliberately **not** given its own new natural-language
command — inventing a third phrase whose sole purpose is to trigger a RED
classification would itself be exactly the kind of contrived demo this
plan's own adversarial review (§22) is required to reject. Instead it is
proven directly at the `WorkflowEngine`/integration-test level, by
constructing a `Plan` whose second step's action is the existing, already
RED-classified `"forget all memories"` phrase and asserting the third step
never executes (§13).

---

## 5. Planning Authority Boundary

**Who creates executable `PlanStep`s?**

| Candidate | Verdict |
|---|---|
| A. Existing deterministic `Planner` only, unchanged | Safe, but insufficient alone — `Planner.create_plan()` takes only a raw string; a two-step workflow needs a factory that knows the exact tool/input shape of each step, which is a different, narrower responsibility than free-text single-step classification |
| B. `CommandRouter`/`Orchestrator` constructs a fixed `Plan` | **Chosen, in combination with a small dedicated factory** — see below |
| C. `AIReasoningEngine` suggests steps, deterministic code converts approved suggestions into `PlanStep`s | **Unsafe for Phase 15** — even with a "conversion" boundary, this is the first architectural opening for AI to influence *which tools run*, not just what to say. No current deterministic-conversion precedent exists to build on safely. Explicitly deferred, not merely "later" — this requires its own dedicated security review before it is ever attempted (matches the standing project convention already applied to semantic retrieval, computer control, etc.) |
| D. AI directly returns executable `PlanStep`s | **Unsafe. Rejected outright.** Directly violates the standing invariant. |
| E. Other | Not needed — B is sufficient |

**Chosen design:** a new, narrow, deterministic factory —
`workflow/workflow_plan_factory.py::build_remember_and_show_plan(content: str, security: SecurityManager) -> Plan`
and `build_remember_and_forget_plan(content: str, security: SecurityManager) -> Plan`
— each hardcoded to produce an exact, fixed two-step `Plan` for its own
command, classifying each step's action through the existing
`SecurityManager.classify_action()` exactly as `Planner._classify()`
already does today (same pattern, reused, not duplicated). These factories
are called directly by two new dedicated `JarvisOrchestrator` handlers
(`_handle_remember_and_show_workflow_request` /
`_handle_remember_and_forget_workflow_request`), matched by two new
`CommandRouter` methods, mirroring the seven existing Phase 8–14 special-
case handlers exactly. `Planner.create_plan()` itself is **not** modified —
it continues to produce exactly one step for every request it already
handles, unchanged.

### Explicit answers (verified, not assumed)

- **Can AI create executable PlanSteps?** No. Nothing in this plan gives
  `AIReasoningEngine` a reference to the new factory, `WorkflowEngine`, or
  `ToolExecutor`.
- **Can AI choose tool names?** No. Tool names are hardcoded in the two
  factories.
- **Can AI choose tool arguments?** No. The only "argument" derived at
  runtime is the previous step's own `ToolResult.metadata["memory_id"]`
  (deterministic, not AI-influenced) — see §6.
- **Can AI add steps after execution begins?** No. `WorkflowEngine`
  executes a fixed-length `Plan.steps` tuple; nothing appends to it during
  execution.
- **Can AI reorder steps?** No. Tuple order is authoritative and immutable
  (`Plan.steps: tuple[PlanStep, ...]`, frozen).
- **Can AI retry a failed step?** No. Retries are not supported at all in
  Phase 15 (§11).
- **Can AI decide OnFailure behaviour?** No. Phase 15 supports exactly one
  workflow-level policy (STOP/abort), fixed, not configurable per step or
  by any caller.
- **Can AI escalate a GREEN step into a different action?** No. Every
  step's tier is (re-)classified only by `SecurityManager.classify_action()`
  inside `ToolExecutor.execute()`, at the moment it runs — never by
  anything upstream, AI or otherwise.
- **Can AI replace a blocked/failed step?** No. A blocked/failed step
  stops the workflow (§11); nothing replaces it.

---

## 6. Plan and PlanStep Schema Review

### Smallest schema extension

| Field | Add to Phase 15? | Why | Owner | Mutable? | Persist? |
|---|---|---|---|---|---|
| `tool_name: str \| None = None` | **Yes** | `PlanStep` today has no way to say which tool a step calls — the single-step path derives this separately via `CommandRouter.match()`. A multi-step plan must carry it per step. | The workflow-plan factory | No (frozen) | No — reconstructed each request |
| `tool_input: dict[str, object] = field(default_factory=dict)` | **Yes** | Same reason — the concrete input for that step's tool call. | The workflow-plan factory | No (frozen) | No |
| `input_from_previous_step: str \| None = None` | **Yes, narrowly** | The smallest possible mechanism for genuine inter-step data flow (step 2 needs step 1's created memory id). Names a single `tool_input` key to overwrite, from the *immediately preceding* completed step's `ToolResult.metadata`, before that step runs. | The workflow-plan factory (declares it); `WorkflowEngine` (resolves it at run time) | No (frozen) | No |
| `depends_on` | **No** | Pressure-tested and rejected for a purely sequential engine — list order in `Plan.steps` is already authoritative. A dependency graph is a strictly more general (and unnecessary) structure for two-and-three-step linear chains. Would only be needed for non-adjacent or parallel dependencies, neither of which Phase 15 supports. |
| `on_failure` (per step) | **No** | Every Phase 15 workflow uses exactly one fixed policy (STOP/abort). A per-step field that always holds the same value adds no information; it would only invite premature variation. Deferred to whichever future phase actually needs per-step failure policy variety. |
| `retry_count` / `max_retries` | **No** | Not genuinely needed for the first vertical (§11's own explicit pressure-test) — no Phase 15 proof workflow requires a retry, and adding the field now would dangle unused, exactly the class of "field added merely because the enum exists" this plan's own governing instructions forbid. |
| `optional` (skip-if-failed) | **No** | `StepStatus.SKIPPED` is not used in Phase 15 (§9) — nothing to attach this flag to yet. |
| A stored `status` field on `PlanStep` itself | **No** | `PlanStep` is a frozen, immutable planning-time description of *what* a step is; runtime execution *state* is a different concern with a different lifetime (mutates during a single workflow run, never persisted). Stored separately — see `WorkflowStepOutcome`, §8. |

**`depends_on` pressure test, explicit conclusion:** not necessary. A
linear engine reading `Plan.steps` in tuple order already has a total,
unambiguous execution order; introducing `depends_on` would add graph
semantics (parsing, cycle detection, partial-order execution) that no
Phase 15 proof workflow exercises. Deferred.

**Retries pressure test, explicit conclusion:** not necessary. None of the
three proof workflows (§13) require a retry; `OnFailure` in Phase 15 is
fixed to abort-on-first-failure (§11). Deferred.

---

## 7. Workflow Engine Boundary

**Proposed file:** `workflow/engine.py`
**Proposed class:** `WorkflowEngine`

### Public contract

```python
class WorkflowEngine:
    def __init__(
        self,
        *,
        executor: ToolExecutor,
        approvals: ApprovalManager,
        logger: _AuditLogger | None = None,
    ) -> None: ...

    def run(self, plan: Plan, *, session_id: int | None = None) -> WorkflowResult:
        """Execute plan.steps in order, starting from step 1."""

    def resume(
        self, workflow_id: str, decision: ApprovalDecision, *, session_id: int | None = None
    ) -> WorkflowResult:
        """Continue a previously paused workflow after an approval decision."""

    def has_paused(self, workflow_id: str) -> bool:
        """Report whether workflow_id refers to a currently paused workflow."""
```

Evaluated against the candidates in the task:

- **A. `execute(plan) -> WorkflowResult`** — insufficient alone; provides no
  way to continue a workflow paused mid-execution for approval.
- **B. `run(plan, session_id=...) -> WorkflowResult`** — necessary as the
  entry point, but alone cannot resume.
- **C. Step-at-a-time advance/resume API** — **chosen, minimally**: `run()`
  starts and runs until completion, block, failure, or a pending-approval
  pause; `resume()` is the one additional method needed to continue after
  approval. This is the smallest superset of B that satisfies the approval
  lifecycle (§8) — not a generic "advance one step at a time" API, which
  would be more machinery than any Phase 15 proof workflow needs.
- **D. Other** — not needed.

### Ownership

| Responsibility | Owner |
|---|---|
| Step ordering | `WorkflowEngine` — reads `Plan.steps` tuple order; does not reorder |
| Current-step state | `WorkflowEngine`, held only in memory for the duration of `run()`/until `resume()` completes or the process exits |
| Security classification | **`ToolExecutor`**, reused unchanged — `WorkflowEngine` never calls `SecurityManager.classify_action()` itself |
| `ToolExecutor` invocation | `WorkflowEngine`, one call per step, identical shape to `_handle_request_core`'s own existing call |
| Approval handling (decision recording) | **`ApprovalManager`**, reused unchanged, via the Orchestrator's own existing `approvals.approve()`/`approvals.decline()` — `WorkflowEngine` never records a decision itself |
| Approval request creation | `WorkflowEngine`, calling the existing `ApprovalManager.create_request(...)` exactly as `_confirmation_response`/`_tool_response` already do — not a new mechanism |
| Approval waiting | **Nobody synchronously waits.** `run()` returns immediately with a `PENDING_APPROVAL` result the moment a step needs confirmation; the CLI drives the actual wait via its own existing blocking `input()` loop, unchanged |
| Approval timeout | **`ApprovalManager`**, reused unchanged (existing YELLOW timeout policy applies identically to a workflow-step approval request as to any other) |
| Step success/failure | `WorkflowEngine`, derived directly from each step's `ToolResult` |
| Remaining-step cancellation/skipping | `WorkflowEngine` — on STOP (§11), all not-yet-run steps are left `PENDING` and never attempted |
| Event logging | `WorkflowEngine`, emitting only the new orchestration-level events (§14); tool-level/security-level/approval-level events continue to be emitted by `ToolExecutor`/`ApprovalManager` exactly as today — **no duplication** |
| Progress events | `WorkflowEngine`, via the CLI-facing trace described in §15 |
| Final workflow result | `WorkflowEngine`, as `WorkflowResult` |

**Does `WorkflowEngine` need its own `SecurityManager`?** No — it never
classifies anything itself; `ToolExecutor` already owns that.
**Does it need its own `ApprovalManager` reference?** Yes, but only to call
the two existing public methods (`create_request`) it already exposes —
no new approval logic is written.
**Does it duplicate `SecurityManager` logic?** No.
**Does it duplicate approval logic?** No.
**Does it create a second tool-execution path?** No — every step call is
`self._executor.execute(...)`, the same method and same signature
`_handle_request_core` already uses.

---

## 8. Exact Security Path Per Step

Confirmed, repository-grounded, the intended path is exactly:

```
PlanStep (tool_name, tool_input, from a fixed, factory-built Plan)
  → WorkflowEngine calls ToolExecutor.execute(tool_name, tool_input, session_id=...)
    → ToolExecutor classifies tool.action_for(request) via SecurityManager.classify_action()
      → GREEN: runs immediately, WorkflowEngine advances to the next step
      → YELLOW: ToolExecutor returns requires_confirmation=True;
                WorkflowEngine creates an ApprovalRequest via ApprovalManager.create_request(
                    ..., metadata={"workflow_id": workflow_id, "step_number": str(n)}
                ), stops the loop, and returns a PENDING_APPROVAL WorkflowResult
      → RED: ToolExecutor returns blocked=True;
             WorkflowEngine stops the loop and returns a STOPPED_BLOCKED WorkflowResult
```

This is **identical in shape** to `_handle_request_core`'s existing
single-step path — the only new behaviour is that `WorkflowEngine` loops
over more than one step and stops the loop instead of returning
immediately on the first step.

**No step ever inherits a workflow-level tier.** Every step is
independently reclassified by `ToolExecutor.execute()` at the moment it
runs — this is unchanged, existing behaviour (§2), and Phase 15 does not
add any code path that skips it.

### Mixed-workflow pressure test

| Sequence | Expected outcome |
|---|---|
| GREEN → GREEN | Both run automatically; workflow `COMPLETED`. |
| GREEN → YELLOW | Step 1 runs; step 2 pauses for approval; `PENDING_APPROVAL`. On approve, step 2 runs; workflow `COMPLETED`. On decline, workflow `STOPPED_DECLINED`, no further steps. |
| YELLOW → GREEN | Step 1 pauses first; nothing (including step 2) runs until approved. On approve, step 1 runs, then step 2 runs automatically; workflow `COMPLETED`. |
| GREEN → RED | Step 1 runs; step 2 is blocked immediately (no approval ever offered — RED is unconditional); workflow `STOPPED_BLOCKED`. |
| YELLOW → RED | Step 1 pauses for approval first. (RED is never reached until step 1 resolves, since steps execute strictly in order.) If approved, step 2 is then blocked; `STOPPED_BLOCKED`. If declined, workflow stops at step 1; `STOPPED_DECLINED`. |
| RED first | Step 1 is blocked immediately; workflow `STOPPED_BLOCKED`; step 2 never attempted. |
| Failure before a later YELLOW | Step 1's tool raises/returns `success=False`; workflow `STOPPED_FAILED`; the later YELLOW step is never reached, never given an approval request. |
| Approval timeout mid-workflow | The paused step's `ApprovalRequest` expires per the existing YELLOW timeout policy (unchanged); `WorkflowEngine.resume()` is never called for that `workflow_id`; the workflow remains permanently paused in memory until the process exits — recorded as an honest, terminal `STOPPED_TIMEOUT` the next time anything asks (see §10). No later step ever runs. |

---

## 9. Approval Pause/Resume Semantics

Confirmed from §2: the existing approval architecture is **return-based,
not blocking**. `handle_request()` returns immediately with a pending
`approval_request`; a separate, later call (`execute_approved`) continues
execution after the decision is recorded. There is no existing
synchronous-wait primitive to build on, and none is introduced here.

| Candidate | Verdict |
|---|---|
| A. Synchronous workflow execution blocks on the existing approval flow | **Not possible today** — no blocking primitive exists; would require inventing one, which is out of scope |
| B. Workflow returns PENDING and must be resumed explicitly after approval | **Chosen** — directly mirrors the existing single-step `requires_confirmation` + `execute_approved` pattern |
| C. `WorkflowEngine` owns an in-memory paused-workflow state | **Chosen, as the mechanism enabling B** — `self._paused: dict[str, _PausedWorkflow]`, keyed by `workflow_id` |
| D. Durable paused workflows | **Explicitly rejected for Phase 15** — see §19 |
| E. Other | Not needed |

**`workflow_id`** is generated once per `run()` call (a UUID, mirroring
`Event.event_id`'s own existing generation pattern) and is reused as the
**same string** passed as `ApprovalRequest`'s `metadata["workflow_id"]` —
no new correlation mechanism is invented; the existing, already-present
`metadata: dict[str, str] | None` parameter on `ApprovalManager.create_request()`
is used exactly as designed.

### Concrete answers

- **What happens when a YELLOW step is reached?** `WorkflowEngine` stops
  the loop immediately, creates an `ApprovalRequest` via the existing
  `ApprovalManager`, and returns a `WorkflowResult` with
  `status=PENDING_APPROVAL` and that `approval_request` attached.
- **What does the user see?** The Orchestrator translates this into a
  `JarvisResponse` carrying `approval_request` exactly as today (§15); the
  CLI's existing `_handle_approval` path requires no change at all to
  recognise and act on it.
- **Does workflow execution stop?** Yes — no further steps run until
  `resume()` is explicitly called.
- **Does the process wait?** No — `run()` returns immediately; the CLI's
  own blocking `input()` loop is what "waits," exactly as it already does
  for a single-step YELLOW action today.
- **When approval is accepted, what continues the workflow?** A new
  `Orchestrator.execute_approved(response, decision)` internal check: if
  `response`'s originating request correlates to a paused workflow (see
  §15's exact mechanism), delegate to `WorkflowEngine.resume(workflow_id, decision, session_id=...)`
  instead of the existing single-tool `ToolExecutor.execute(...)` call —
  **the public `execute_approved(response, decision)` signature does not
  change at all.**
- **When approval times out, what step status is recorded?** The paused
  step's own status remains `WAITING` in the engine's in-memory record;
  the existing `ApprovalManager` timeout mechanism independently expires
  the `ApprovalRequest` itself (unchanged). The workflow is never silently
  "completed" — it simply remains paused, and any later `resume()` attempt
  with an expired/unknown decision is rejected honestly.
- **What happens to remaining steps?** They stay `PENDING` and are never
  attempted while paused, and never attempted at all if the workflow never
  resumes.
- **What if approval is denied?** `resume()` returns a `WorkflowResult`
  with `status=STOPPED_DECLINED`; the paused step and all later steps
  remain un-run.
- **What if the CLI session ends?** The in-memory `_paused` dict is lost
  with the process. This is explicitly acceptable for Phase 15 (§19) —
  identical in spirit to `ApprovalManager`'s own existing, explicitly-
  documented "pending requests never survive a restart" design.
- **Is workflow state lost?** Yes, on process exit, by design.
- **Is that acceptable for Phase 15?** Yes — matches the existing
  `ApprovalManager` precedent exactly; durability is explicitly Phase 16+
  scope if scheduling ever needs it (§19).

---

## 10. Step State Machine

Using **only existing `StepStatus` enum values** — no new value is added.

| From | To | Trigger | Owner |
|---|---|---|---|
| — | `PENDING` | Step is part of a newly built `Plan`, not yet reached | Workflow-plan factory (initial), `WorkflowEngine` (unchanged until reached) |
| `PENDING` | `RUNNING` | `WorkflowEngine` begins executing this step (transient — never observed in a returned `WorkflowResult`, only held during the call) | `WorkflowEngine` |
| `RUNNING` | `COMPLETED` | `ToolExecutor.execute()` returns `success=True` | `WorkflowEngine` |
| `RUNNING` | `FAILED` | `ToolExecutor.execute()` returns `success=False` (tool raised, or reported a genuine failure) **or** `blocked=True` (RED) — both represented as `FAILED` at the `StepStatus` level, distinguished by the nested `ToolResult.blocked` flag (§12's own note: no new `BLOCKED` enum value is added; `ToolResult.blocked` already exists and is sufficient) | `WorkflowEngine` |
| `RUNNING` | `WAITING` | `ToolExecutor.execute()` returns `requires_confirmation=True` (YELLOW, no approval yet) | `WorkflowEngine` |
| `WAITING` | `RUNNING` | `WorkflowEngine.resume()` is called with an approved decision | `WorkflowEngine` |
| `WAITING` | `FAILED` | `WorkflowEngine.resume()` is called with a declined decision | `WorkflowEngine` |
| `PENDING` | (remains `PENDING`, never reached) | An earlier step ends in `FAILED` or the workflow is paused at `WAITING` | `WorkflowEngine` (by omission — later steps are simply never advanced to) |

**Forbidden transitions, explicitly identified:**
- `COMPLETED` → anything (a completed step is never re-run; no retry
  exists in Phase 15).
- `FAILED` → `RUNNING` (no retry).
- `WAITING` → `COMPLETED` directly (must pass through `RUNNING` first —
  `resume()` always re-invokes `ToolExecutor.execute()`, it never
  fabricates a success).
- `PENDING` → `RUNNING` for any step other than the next unstarted one in
  tuple order (no reordering, no skipping ahead).

**Immutable `PlanStep` vs. runtime state:** `PlanStep` remains fully
immutable (frozen dataclass, unchanged). Runtime execution state is
represented by a **new, separate** small runtime type,
`WorkflowStepOutcome` (frozen dataclass: `step: PlanStep, status: StepStatus,
tool_result: ToolResult | None = None`), one instance produced per
attempted step and collected into `WorkflowResult.step_outcomes`. Nothing
mutates `PlanStep` illegally; a new, immutable outcome object is created
for the state transition instead, exactly matching the codebase's existing
convention (`ToolExecutor._record_approval` returns a new `ToolResult` via
`dataclasses.replace` rather than mutating one).

---

## 11. Failure and OnFailure Semantics

**Existing `OnFailure` enum values:** `RETRY_WITH_ALTERNATIVE_PROVIDER`,
`RETRY_WITH_ALTERNATIVE_TOOL`, `SKIP`, `ESCALATE_TO_USER`, `ABORT_PLAN`.

**Phase 15 supports exactly one: `ABORT_PLAN`** (i.e., "STOP" from the
task's own framing — the closest existing enum value, reused rather than
inventing a new "STOP" value). This is a **workflow-level constant**, not a
per-step configurable field (§6) — every Phase 15 workflow always aborts
the remainder of the plan on the first step that does not cleanly succeed.

The other four values are **not supported and not claimed** — `SKIP`
requires an `optional` flag Phase 15 does not add; `ESCALATE_TO_USER` would
require a new interactive decision point beyond approve/decline that
doesn't exist; both `RETRY_WITH_ALTERNATIVE_*` require a retry mechanism
Phase 15 explicitly does not build (§6's own pressure test).

**How unsupported values are prevented:** the workflow-plan factories
never set anything but the implicit `ABORT_PLAN` behaviour (since Phase 15
`PlanStep` carries no `on_failure` field at all — see §6 — there is
nothing to misconfigure). `WorkflowEngine` itself has no branch for any
other policy; the only behaviour it implements is stop-on-first-failure.

### Pressure test

| Scenario | Behaviour |
|---|---|
| Tool raises | `ToolExecutor.execute()` already catches this (`_handle_run`'s existing `except Exception`) and returns `success=False`; step outcome `FAILED`; workflow `STOPPED_FAILED`. |
| `ToolExecutor` returns blocked | Step outcome `FAILED` (with `tool_result.blocked=True`); workflow `STOPPED_BLOCKED`. |
| Approval denied | Step outcome `FAILED`; workflow `STOPPED_DECLINED`. |
| Approval timeout | Workflow remains paused (§9); if later queried and the underlying `ApprovalRequest` is confirmed expired, reported as `STOPPED_TIMEOUT`. |
| Invalid tool/action | Not possible by construction — the two Phase 15 factories only ever name real, registered tools (`memory`, `memory_forget`); no user input selects the tool name. |
| Malformed step arguments | Not possible by construction for the two fixed factories (the only variable input is the free-text `content`, which the underlying `memory` tool's own existing `_run_save` already validates, failing honestly if empty). |
| Reasoning/advisory step unavailable | Not applicable — Phase 15 has no AI-advisory step (§12). |

---

## 12. AI-Advisory Step Question

| Candidate | Verdict |
|---|---|
| A. Phase 15 executes tool steps only | **Chosen** |
| B. A distinct advisory AI step producing text but not altering workflow structure | Rejected for Phase 15 (see below) — plausible for a later phase, not needed for either proof workflow |
| C. Every plan may include AI reasoning steps | Rejected — premature, no proof workflow needs it |
| D. AI steps wait for a later phase | **Confirmed as the practical outcome**, alongside A |

**Reasoning:** Both chosen proof workflows (§4) are pure deterministic
tool chains; neither needs an AI step to be genuinely useful or to prove
the engine. Introducing an AI-advisory step type in the same phase that
introduces the engine itself would conflate two separate architectural
questions. The critical invariant named in the task — **"An AI-advisory
step's output must not become executable input for a later tool step
unless a new explicit deterministic validation/translation boundary
exists"** — has no such boundary designed or reviewed yet anywhere in the
codebase. Phase 15 **excludes AI steps entirely** rather than attempt to
half-satisfy that invariant. `ActionType.AI_CALL` remains an unused enum
value after Phase 15, exactly as it is today — this is honest, not a gap,
since no workflow in this phase needs it.

---

## 13. First Real Multi-Step Workflows

### Workflow 1 — All-GREEN: `"remember this and show it back: Buy milk"`

| Step | Tool | `tool_input` | Expected tier | Approval | 
|---|---|---|---|---|
| 1 | `memory` | `{"operation": "save", "content": "Buy milk"}` | GREEN (`"save memory"`) | None |
| 2 | `memory` | `{"operation": "get", "memory_id": "<from step 1>"}` | GREEN (`"show memory"`) | None |

`input_from_previous_step="memory_id"` on step 2 tells `WorkflowEngine` to
read `step_1_outcome.tool_result.metadata["memory_id"]` and set
`tool_input["memory_id"]` before running step 2.

Progress output (CLI, §15):
```
jarvis> [WORKFLOW STARTED] remember this and show it back: Buy milk (2 steps)
jarvis>   step 1/2 [memory: save] ... completed
jarvis>   step 2/2 [memory: get] ... completed
jarvis> [WORKFLOW COMPLETED] Saved to memory under 'general': Buy milk
        [3] (general) Buy milk
```
Final result: `status=COMPLETED`, both steps `COMPLETED`.

### Workflow 2 — GREEN → YELLOW: `"remember this and forget it: Temporary note"`

| Step | Tool | `tool_input` | Expected tier | Approval |
|---|---|---|---|---|
| 1 | `memory` | `{"operation": "save", "content": "Temporary note"}` | GREEN | None |
| 2 | `memory_forget` | `{"memory_id": "<from step 1>"}` | YELLOW (`"forget memory"`) | Required |

Progress output:
```
jarvis> [WORKFLOW STARTED] remember this and forget it: Temporary note (2 steps)
jarvis>   step 1/2 [memory: save] ... completed
jarvis>   step 2/2 [memory_forget] ... awaiting approval
jarvis> [NEEDS APPROVAL] Forgetting a memory requires your confirmation...
```
CLI prompts, user approves → `orchestrator.execute_approved()` delegates to
`WorkflowEngine.resume(workflow_id, decision)` →
```
jarvis>   step 2/2 [memory_forget] ... completed
jarvis> [WORKFLOW COMPLETED] Forgot memory 4.
```
Final result on approve: `status=COMPLETED`. On decline:
`status=STOPPED_DECLINED`, step 2 outcome `FAILED`.

### Workflow 3 — Blocked stops later steps (engine/integration-test level, no new command)

A `Plan` constructed directly in a test with three steps: step 1
`{"operation": "list"}` on `memory` (GREEN), step 2 with `action="forget all memories"`-
shaped input on `memory_forget` (`{"all": True}`, classified RED), step 3
another `memory` `list` call. Expected: step 1 `COMPLETED`, step 2
`FAILED` (`blocked=True`), step 3 remains `PENDING`, `status=STOPPED_BLOCKED`,
and the test asserts the underlying `memory` tool's `run()` was invoked
exactly once (proving step 3 never executed).

---

## 14. CLI Progress Surface

| Candidate | Verdict |
|---|---|
| A. All progress returned after completion | Rejected — defeats the entire purpose (Nathan must see it *executing*, not just a final summary) |
| B. Progress callback passed into `WorkflowEngine.run()` | **Rejected** — pressure-tested directly against Retrieval Workflow Maintenance's own precedent (`docs/retrieval_workflow_maintenance_plan.md` §8): a callback threaded through the engine for something the *only* current caller (the CLI, synchronously, in the same process) can just as easily read off a returned value is exactly the "indirection with no benefit" pattern already rejected there. |
| C. Progress/event iterator (generator) | Considered, but adds an iteration-protocol contract to `WorkflowEngine.run()` that only one caller needs; simpler to satisfy the same need with D |
| D. `EventLogger`-backed CLI polling | Rejected — would require the CLI to read back its own just-emitted audit events, an awkward and indirect round-trip for something already available in memory |
| **E. Simple orchestrator-formatted step trace** | **Chosen** |
| F. Other | Not needed |

**Design:** `WorkflowResult.step_outcomes` (an ordered tuple, always fully
populated for every attempted step, in order) is exactly what the CLI
needs — no callback, no iterator, no polling. `WorkflowEngine.run()`/
`resume()` return this **after** the loop stops (on completion, block,
failure, or pause), and the Orchestrator/CLI formats each `WorkflowStepOutcome`
into one line per step, exactly mirroring the existing `format_response()`
convention (`ui/cli.py:118`) that already renders `Plan.steps` line by
line today. This does not require the engine to "stream" anything — a
two-or-three-step workflow completes fast enough (each step is a local
SQLite operation) that returning the full ordered trace at once, then
printing it line by line, is indistinguishable to Nathan from true live
streaming, at a fraction of the complexity.

**Why a callback is not justified here:** identical reasoning to
Retrieval Workflow Maintenance's own rejected callback approach — the sole
consumer (CLI) is synchronous, in-process, and already receives a complete
answer; threading a callback through `WorkflowEngine.run()` would add a
parameter and an indirection for zero behavioural gain over returning an
already-ordered list.

Nathan can distinguish every required state directly from the printed
trace: workflow started (header line with step count), each step's
attempt in order (`step N/M started` is implicit in that line's presence
— the loop only reaches step N after step N-1 resolves, so no separate
"started" event line is needed beyond ordering itself), step outcome
(`completed`/`awaiting approval`/`failed`/`blocked`), and workflow
completed/stopped (final summary line).

---

## 15. Orchestrator Ownership

- **Does `handle_request()` recognize a dedicated workflow command?**
  Yes — two new `CommandRouter.match_remember_and_show_workflow(text)` /
  `match_remember_and_forget_workflow(text)` methods, checked in
  `handle_request()` alongside (not replacing) the existing seven Phase
  8–14 special-case checks, each returning the captured `content` text or
  `None`.
- **Does `CommandRouter` identify workflow intents generically?** No — no
  intent classifier is introduced; these are two more exact phrase
  matchers in the same style as the existing seven.
- **Does `Planner.create_plan()` return a multi-step Plan for specific
  existing commands?** No — `Planner` is untouched; the two new
  `workflow/workflow_plan_factory.py` functions build these two specific
  `Plan`s directly, bypassing `Planner` entirely (mirroring how the seven
  Phase 8–14 handlers already call `self._planner.create_plan(text)` only
  for the transparency of a *displayed* plan, not for tool dispatch, which
  they also handle specially).
- **Does Orchestrator call `WorkflowEngine` only when the plan has more
  than one step?** Effectively yes, but by construction, not by a runtime
  step-count check: only the two new dedicated handlers ever call
  `WorkflowEngine.run()`; `_handle_request_core`'s existing single-step
  path is completely untouched and never touches `WorkflowEngine` at all.
- **Can existing single-step commands accidentally enter
  `WorkflowEngine`?** No — routing to the two new handlers requires an
  exact phrase match on one of the two new fixed grammars; anything else
  continues down the existing, unmodified `_handle_request_core` path.
- **Does `WorkflowEngine` return `JarvisResponse` directly?** No —
  `WorkflowEngine` returns `WorkflowResult`; a new, small
  `Orchestrator._workflow_result_to_response(result) -> JarvisResponse`
  translates it, mirroring the existing `_tool_result_to_response`
  pattern exactly.
- **Does Orchestrator translate `WorkflowResult` into `JarvisResponse`?**
  Yes, as above. `JarvisResponse`'s own schema is **not changed** — a
  `PENDING_APPROVAL` `WorkflowResult` is translated into exactly the same
  shape (`requires_confirmation=True`, `approval_request=...`) the
  existing single-step YELLOW path already produces, so `ui/cli.py`'s
  existing `_handle_approval` requires **zero changes** to recognise and
  drive it.
- **Resume wiring, exact mechanism:** `Orchestrator.execute_approved(response, decision)`
  gains one new check at its very top: if
  `self._workflow_engine.has_paused(response.approval_request.request_id)`
  (using the `ApprovalRequest.request_id` itself as the `workflow_id` —
  see §9, no separate id needed since exactly one workflow can be paused
  at a time), delegate to
  `self._workflow_engine.resume(response.approval_request.request_id, decision, session_id=...)`
  and translate that `WorkflowResult`; otherwise, fall through to the
  existing, completely unmodified single-tool `execute_approved` body.
  **The public method's signature does not change.**

`WorkflowEngine` executes a `Plan`; it does not parse text, does not match
commands, and is never called from anywhere except these two new handlers
and `execute_approved`'s new check — it is not a second top-level request
router.

---

## 16. Planner Expansion

| Candidate | Verdict |
|---|---|
| A. Add exact deterministic workflow command patterns to `Planner` | Rejected — `Planner.create_plan()`'s single-step contract is depended on by all eight existing call sites (§2); overloading it is unnecessary risk |
| B. Separate deterministic workflow-plan factory | **Chosen** — `workflow/workflow_plan_factory.py`, two functions, described in §5 |
| C. `CommandRouter` returns a workflow command variant, Orchestrator constructs the Plan | Equivalent in spirit to B, but places plan-construction logic in the Orchestrator rather than a dedicated module; **B is preferred** for the same separation-of-concerns reason `Planner`/`WorkflowEngine` are themselves kept apart |
| D. AI planning | Rejected (§5) |
| E. Other | Not needed |

`Planner` itself needs **zero code changes** for Phase 15. It remains
exactly as capable (and exactly as limited) as it is today; strengthening
it into a genuine multi-step decomposer is explicitly out of scope and not
required by either proof workflow.

Phase 15 needs, and gets, from the new factory module only: multiple
`PlanStep`s (two, fixed), tool_name/tool_input arguments per step (§6),
explicit ordering (tuple order), and validation (§17) — no branching, no
retries (§6).

---

## 17. Plan Validation

**Required — a small `WorkflowEngine`-side precondition check**, not a
full `PlanValidator` class, since only two fixed factories ever produce
Phase 15 workflow plans (no external/AI/user-authored plan input exists to
validate against arbitrary malformation).

Pressure-tested malformed-plan scenarios, all currently only reachable via
a programming error in the factories themselves (not via any user input),
each explicitly guarded:

| Scenario | Guard |
|---|---|
| Zero steps | `WorkflowEngine.run()` rejects an empty `Plan.steps` immediately with a clear internal error — never silently "completes" a no-op workflow. |
| Duplicate step ids (`number`) | Both factories assign `number` via `enumerate(..., start=1)`, identical to `Planner._classify`'s own existing pattern — structurally cannot duplicate. |
| Unordered/invalid indices | Same reasoning — `number` is always sequential and monotonic by construction. |
| Unknown action/tool | Both factories hardcode `tool_name` to `"memory"`/`"memory_forget"`, both real, always-registered tools; `WorkflowEngine` additionally checks `self._executor` can resolve the name before running (reusing `ToolExecutor`'s own existing unknown-tool handling, `_handle_unknown` — no duplicate check needed, this is naturally inherited for free). |
| Missing arguments | Delegated to the existing tool's own input validation (`memory`'s `_run_save`/`_parse_id`, `memory_forget`'s `_parse_id`) — already tested, already honest-failing. |
| Unsupported `OnFailure` | Not applicable — no `on_failure` field exists on Phase 15 `PlanStep` (§6); nothing to misconfigure. |
| Duplicate order | Same as duplicate ids — structurally impossible via `enumerate`. |
| Executable step with AI-owned free-form action | Not applicable — no AI step type exists in Phase 15 (§12). |
| RED-like action mislabeled as GREEN in the plan | **Explicitly cannot happen and is irrelevant even if it did** — see the critical rule below. |

**Critical rule, directly enforced by design, not merely documented:**
`WorkflowEngine` **never reads or trusts** any tier field from `PlanStep`
at all. (Phase 15's extended `PlanStep` still carries the original `tier`
field from `Plan`'s general shape, populated by the factory using
`SecurityManager.classify_action()` purely for **display purposes** — the
same "plan is always shown for transparency" convention `_handle_request_core`
already follows — but `WorkflowEngine.run()`'s actual execution decision
for every step is made **exclusively** by calling
`self._executor.execute(...)`, which independently reclassifies via the
real `SecurityManager.classify_action()` at that exact moment. A
`PlanStep.tier` value, even if wrong or stale, has **zero effect** on
whether a step actually runs, because `WorkflowEngine` never branches on
it.**

---

## 18. Event and Audit Architecture

**New workflow-level event family** (orchestration state only — tool-level
`tool_call`, security/approval events continue exactly as today, emitted
by `ToolExecutor`/`ApprovalManager`, unchanged, never duplicated):

| `action_type` | `EventOutcome` | `detail` fields | When |
|---|---|---|---|
| `workflow_started` | `SUCCESS` | `workflow_id=<id> steps=<n> request=<workflow command name>` | `run()` begins |
| `workflow_step_completed` | `SUCCESS` | `workflow_id=<id> step=<n>/<total> tool=<tool_name>` | A step's `ToolResult.success=True` |
| `workflow_step_failed` | `FAILURE` | `workflow_id=<id> step=<n>/<total> tool=<tool_name>` | A step's `ToolResult.success=False` |
| `workflow_step_blocked` | `BLOCKED` | `workflow_id=<id> step=<n>/<total> tool=<tool_name>` | A step's `ToolResult.blocked=True` |
| `workflow_paused` | `PENDING` | `workflow_id=<id> step=<n>/<total> tool=<tool_name>` | A step needs confirmation |
| `workflow_completed` | `SUCCESS` | `workflow_id=<id> steps_completed=<n>` | `run()`/`resume()` reaches the end of the plan |
| `workflow_stopped` | `FAILURE`/`BLOCKED`/`PENDING` (matching the stopping reason) | `workflow_id=<id> stopped_at_step=<n> reason=<blocked/failed/declined/timeout>` | The loop stops before the last step |

**Privacy rationale:** step `detail` strings log only `tool_name` and
numeric step positions — never the free-text `content` the user is
remembering, and never the memory's own content, matching the existing
`_audit_memory_set_acquisition`/`_emit_memory_acquisition_event`
convention of never embedding raw content in an audit `detail` string.
**Is step action text safe to log?** The tool name alone is; the
underlying free-text argument is not logged in any new event, exactly
mirroring the existing memory-acquisition audit precedent.

**Correlation strategy:** `workflow_id` (a UUID, generated once per
`run()`) appears in every event for that workflow, plus the existing
`session_id` parameter every `EventLogger.emit()` call already accepts —
no new correlation field type is invented.

**Audit failure isolation:** every new emit call is wrapped in the exact
same narrow, established pattern already used throughout the codebase
(e.g. `_emit_memory_acquisition_event`'s own `try/except Exception: pass`
scoped only around the `emit()` call) — a failing logger can never alter
`WorkflowEngine`'s own control flow or the `WorkflowResult` it returns.
**Workflow execution exceptions themselves are never swallowed by an
audit guard** — only the `emit()` call itself is isolated; a genuine tool
exception still surfaces as a `FAILED` step outcome through the normal
`ToolExecutor` path (which already isolates tool exceptions itself, §2).

---

## 19. Persistence Boundary

| Candidate | Verdict |
|---|---|
| A. In-memory execution only | **Chosen** |
| B. Durable workflow records | Rejected for Phase 15 |
| C. Append-only event reconstruction | Rejected for Phase 15 — the new `workflow_*` audit events (§18) are a *record* of what happened, not a mechanism designed for reconstructing a resumable workflow after restart |
| D. Other | Not needed |

Phase 15 is **in-memory only**. A process exit while a workflow is paused
(`WAITING`) loses that workflow's own execution state — the `_paused` dict
lives only in the running `WorkflowEngine` instance. This is explicitly
acceptable, for the same reason `ApprovalManager`'s own pending requests
are already, by design, never rehydrated on restart (§2).

**What remains durable regardless:** every already-completed step's real
side effect (a memory actually saved or forgotten) persists exactly as
today, because it went through the real `MemoryManager`/SQLite path,
unchanged. The audit trail of what happened up to the pause point also
persists (via `EventLogger`/`AuditLog`, and via `ApprovalHistoryStore` for
the approval request itself). **Only the "what step comes next"
in-progress workflow state is lost** — not already-applied side effects,
not the audit record of what already happened.

**No workflow resumability claim is made.** If Nathan restarts Jarvis
mid-pause, the workflow simply never continues; a fresh request must be
issued. This is the same honest, documented limitation
`ApprovalManager` already carries for a plain single-step YELLOW pending
request today.

**Does Phase 16 (scheduling/proactive) need durability first?** Yes,
almost certainly — a background-scheduled workflow that pauses for
approval while nothing is watching the CLI would need a durable resume
path (and likely a non-CLI notification surface) that Phase 15
deliberately does not build. This is flagged as required future work,
not solved here.

---

## 20. Concurrency Boundary

**Chosen: no parallel steps, no concurrent active workflows, synchronous
linear execution.** Verified, not merely asserted: `ui/cli.py`'s `run()`
loop is single-threaded and calls `self._input(_PROMPT)` (a blocking
built-in `input()` call) between every request; nothing in `main.py` or
anywhere else starts a second thread, process, or event loop. The existing
architecture already enforces "one thing happens at a time" for the
entire application, not just for workflows — `WorkflowEngine` inherits
this for free and requires no new concurrency guard of its own. No
`asyncio`, threading, or process pool is introduced.

`WorkflowEngine._paused` naturally holds at most one entry in practice
(the CLI cannot issue a second request while blocked on its own `input()`
call, and there is no other caller), but the dict-keyed design costs
nothing extra and is more honest about the actual invariant than a single
optional field would be.

---

## 21. Proposed Phase 15 Batches

Pressure-tested against the task's own suggested structure; **retained
with one adjustment** (Batch 3 and Batch 4's CLI-facing content are kept
strictly separated so the engine itself is fully proven headless before
any user-facing wiring is added, reducing the risk of debugging the engine
and the CLI integration simultaneously):

### Batch 1 — Minimal Multi-Step Plan and Workflow Models
- Extend `PlanStep` with `tool_name`, `tool_input`, `input_from_previous_step`
  (§6). No behaviour change to any existing single-step caller (all three
  fields default to `None`/empty).
- Add `WorkflowStepOutcome`, `WorkflowResult` (§7, §10) to a new
  `workflow/workflow_models.py`.
- No execution wiring yet. Focused unit tests only for the new data shapes
  and their invariants.

### Batch 2 — Sequential Workflow Engine
- `workflow/engine.py::WorkflowEngine` (§7): `run()`, `resume()`,
  `has_paused()`.
- Reuses `ToolExecutor`/`ApprovalManager` unchanged (§7, §8).
- STOP-only failure policy (§11).
- New `workflow_*` audit events (§18).
- No `CommandRouter`/`Orchestrator`/CLI wiring yet — tested directly
  against hand-built `Plan`s, including the three proof workflows (§13),
  fully headless.

### Batch 3 — Deterministic Workflow Commands and Planner/Orchestrator Wiring
- `workflow/workflow_plan_factory.py` (§5, §16): the two fixed-plan
  factories.
- Two new `CommandRouter` matchers (§15).
- Two new `JarvisOrchestrator` handlers, dispatched from
  `handle_request()` alongside the existing seven (§15).
- `Orchestrator.execute_approved()`'s new paused-workflow check (§9, §15).
- No CLI-facing progress-trace formatting change yet — responses are
  correctly translated but not yet specially formatted.

### Batch 4 — CLI Step Progress and End-to-End Security Proof
- CLI-facing step-by-step trace formatting (§14).
- Full end-to-end proof of all three workflows (§13) through the real
  CLI/`handle_request()`/`execute_approved()` path.
- Logger-failure isolation regression (§18).
- Full existing-suite regression (no Phase 1–14/maintenance behaviour
  changes).

### Batch 5 — Documentation and Closure
- README update (new commands, Phase 15 status).
- `docs/phase_15_completion_report.md`.
- Final semantic-drift/security review, full regression, closure commit.

---

## 22. Adversarial Architecture Review

- **Can AI create an executable step?** No (§5).
- **Can AI output alter a later step's arguments?** No — the only runtime-
  filled argument is `input_from_previous_step`, sourced exclusively from
  a prior step's own deterministic `ToolResult.metadata`, never from any
  AI output.
- **Can `WorkflowEngine` call a tool directly?** No — always through
  `ToolExecutor.execute()` (§7, §8).
- **Can a workflow bypass `SecurityManager`?** No — every step re-runs
  the real classification inside `ToolExecutor` (§8, §17).
- **Can an overall GREEN plan hide a YELLOW/RED step?** No — there is no
  "overall plan tier"; each step is independently classified at execution
  time, and the two factories never claim a single tier for the whole
  workflow in the first place (they classify each step individually via
  `SecurityManager.classify_action()`, purely for display, per §17).
- **Can a step-provided tier override live classification?** No (§17's
  critical rule — `WorkflowEngine` never reads `PlanStep.tier` for
  execution decisions).
- **Can a YELLOW approval be accidentally reused by a later step?** No —
  each `ApprovalRequest` is created fresh per paused step, with its own
  `request_id`, and `resume()` only ever advances the one specific step
  that request corresponds to.
- **Can approval timeout leave the workflow in an incoherent state?** No
  — it remains cleanly `WAITING` forever (in memory) or is reported
  `STOPPED_TIMEOUT` on next inspection; no step is ever silently marked
  completed.
- **Can a blocked step allow later execution?** No — STOP is unconditional
  (§11); the loop halts immediately.
- **Can a failed step be marked completed?** No — `WorkflowEngine` sets
  outcome status directly from `ToolResult.success`/`blocked`, never
  independently.
- **Can logger failure alter workflow progress or final status?** No
  (§18's isolation guarantee).
- **Can duplicate step ids corrupt status tracking?** Not reachable (§17).
- **Can a step execute twice?** No — the loop advances strictly forward
  through `Plan.steps`; `resume()` re-enters at the exact paused step
  index, never re-running an already-`COMPLETED` step.
- **Can process exit create a false "completed" workflow?** No — a
  process exit simply ends the in-memory record; nothing is ever recorded
  as completed unless the loop genuinely reached the end (§19).
- **Can progress output claim a step completed before `ToolExecutor`
  returns?** No — the trace is built from the returned `WorkflowResult`
  after `run()`/`resume()` returns, not from a live/optimistic callback
  (§14 — this is exactly why a callback was rejected).
- **Can selection/memory AI authority leak into workflow authority?** No
  — Phase 15 has no AI-advisory step at all (§12); `AIReasoningEngine` is
  never referenced by `WorkflowEngine` or the new factories.
- **Can `WorkflowEngine` become a second Orchestrator?** No — it has no
  knowledge of `CommandRouter`, natural-language text, or any command
  other than executing the `Plan` it's handed (§15).
- **Can `Planner` become a second `CommandRouter`?** No — `Planner` is
  untouched; the new command matching lives entirely in `CommandRouter`
  and the two new dedicated handlers, exactly like the existing seven.
- **Does adding `depends_on` create graph semantics Phase 15 does not
  support?** N/A — `depends_on` is not added (§6).
- **Does adding retries create failure semantics Phase 15 does not
  support?** N/A — retries are not added (§6, §11).
- **Does supporting AI-advisory steps create an implicit AI-to-tool data
  path?** N/A — not supported (§12).
- **Does CLI progress require callbacks that unnecessarily complicate the
  engine?** No — rejected in favour of a returned, ordered result (§14).
- **Is the first workflow command genuinely useful, or merely a contrived
  demo?** Genuinely useful — save-with-immediate-confirmation and
  save-then-retract are both real, sensible request shapes a user could
  plausibly want, not artefacts invented solely to exercise the engine.
  The one scenario that *would* have required a contrived command
  (proving RED-blocks-later-steps) is deliberately kept out of the
  user-facing surface and proven at the engine/test level instead (§4,
  §13).
- **Does Phase 15 unlock scheduling without requiring an immediate engine
  redesign?** Partially — scheduling additionally needs durability (§19)
  and a non-CLI trigger/notification surface, both explicitly flagged as
  required future work, not solved here; but the execution engine itself
  (`WorkflowEngine.run()`/`resume()`, step-by-step security gating) would
  not need to be redesigned, only extended with a durable pause/resume
  layer on top.

**No weakness found that changes the recommendation.** One refinement made
during this review: Batch 3 and Batch 4 were split (engine wiring vs. CLI
formatting) specifically because §14's rejection of a callback-based
design means the CLI-facing trace is a pure, separable presentation
concern that can and should be proven against the headless engine first.

---

## 23. Required Unit/Integration/End-to-End Tests (for Batches 1–4, not written this turn)

- **Unit — Batch 1:** `WorkflowStepOutcome`/`WorkflowResult` construction
  and invariants; extended `PlanStep` fields default to `None`/empty and
  do not affect any existing Phase 1–14 test.
- **Unit — Batch 2:** `WorkflowEngine.run()`/`resume()`/`has_paused()`
  against hand-built `Plan`s covering every row of §8's mixed-workflow
  table, plus §13's three proof workflows, plus the malformed-plan guards
  of §17, plus logger-failure isolation (§18), all fully headless (no
  `CommandRouter`/`Orchestrator` involvement).
- **Integration — Batch 3:** the two new `CommandRouter` matchers; the two
  new `Orchestrator` handlers producing correctly-shaped `JarvisResponse`s
  (including the paused-workflow `execute_approved` delegation); proof
  that no existing single-step command is newly captured by the two new
  matchers.
- **End-to-end — Batch 4:** full `handle_request()` → CLI-formatted trace
  → (for workflow 2) approval prompt → `execute_approved()` → continuation
  → final printed result, for all three proof workflows; a full-suite
  regression run after every batch (mirroring the one-batch-at-a-time
  verification discipline already established in Retrieval Workflow
  Maintenance).
- **Cross-subsystem regression:** re-run every existing Phase 1–14 and
  Retrieval Workflow Maintenance test file after each batch to confirm
  zero behavioural drift in any existing command.

---

## 24. Verification Commands (for if/when implementation is authorised)

```
poetry run pytest tests/unit/test_workflow_models.py -v
poetry run pytest tests/unit/test_workflow_engine.py -v
poetry run pytest tests/unit/test_command_router.py -v
poetry run pytest tests/integration -v
poetry run pytest -v
git diff --check
```

Regression floor: **1565 passed, 0 failed** — may only grow (new tests are
additive; no existing test's assertions should need to change).

---

## 25. README/Closure Requirements (Batch 5 only, not this turn)

- README "Current Status"/"Next Phase" updated with the two new commands
  and an honest statement of Phase 15's narrow linear-only scope (no
  parallel/branching/retry/durability claims).
- `docs/phase_15_completion_report.md` created at closure, following the
  established per-phase completion-report convention (distinct from the
  unnumbered maintenance-report convention used for Retrieval Workflow
  Maintenance).

---

## 26. Stop/Rollback Conditions (for if/when implementation is authorised)

Stop and report, without proceeding, if at any point during implementation:
any existing test's assertion needs to *change* (not merely be extended)
to keep passing; `ToolExecutor`'s re-classification-at-execution-time
behaviour is found to differ from §2's description; the approval
architecture is found to support a blocking-wait primitive this plan
assumed does not exist; or either proof workflow turns out to require a
tool input shape the existing `memory`/`memory_forget` tools do not
actually support as described in §13. Any of these would indicate this
planning turn's repository reading was wrong somewhere, not merely that
the design needs adjusting.

---

## 27. Risks/Debt Carried Forward

- Workflow state is in-memory only; a process restart mid-pause loses
  that workflow (not its already-applied side effects or audit trail) —
  acceptable now, but scheduling/proactive work (a likely Phase 16/17
  candidate) will need a durability design this plan does not provide.
- `PlanStep.tier`, still populated for display/transparency, remains a
  field that is never authoritative for execution — this is intentional
  (§17) but is a subtle enough invariant that it should be re-verified
  explicitly at Phase 15's own closure review, exactly as this plan does
  here.
- `ActionType.AI_CALL`, `BRANCH`, `PARALLEL_GROUP`, and four of five
  `OnFailure` values remain unused enum placeholders after Phase 15,
  unchanged from today — explicitly not a regression, since none was used
  before either.
- The existing, pre-Phase-15 architectural debts (CommandRouter keyword-
  overlap risk, ToolExecutor/classify_action bypass asymmetry for direct
  AI memory reads, AST invariant's dynamic-dispatch blind spot, SQLite
  naive-timestamp debt) are entirely unrelated to and unaffected by this
  plan.

---

## 28. Exact Recommended Batch 1 Next Action

Await explicit authorisation before starting Batch 1. If authorised,
Batch 1's exact first action is: extend `planner/plan_models.py::PlanStep`
with `tool_name: str | None = None`, `tool_input: dict[str, object] = field(default_factory=dict)`,
and `input_from_previous_step: str | None = None`; add
`workflow/workflow_models.py` with `WorkflowStepOutcome`/`WorkflowResult`;
add focused unit tests proving the three new `PlanStep` fields default
safely and do not alter any existing Phase 1–14 behaviour; run the full
existing suite to confirm zero regression before proceeding to Batch 2.

---

## 29. Batch 5 Closure Addendum — Plan-vs-Implementation Reconciliation

This section is added at Phase 15's closure (Batch 5) and is intentionally
appended, not retroactively edited into, the sections above. Sections 1–28
above are left exactly as they were written during planning, including the
places where the delivered implementation ended up narrower or different
from what was proposed there. This addendum records, for every point where
implementation diverged from this plan, which of five categories the
divergence falls into:

- **A** — implementation matches the plan as written.
- **B** — a narrow, repository-grounded refinement made during
  implementation, disclosed in the batch's own closure report at the time.
- **C** — a corrective closure of a real defect discovered empirically
  during implementation, not anticipated by this plan at all.
- **D** — an unresolved deviation from the plan with no disclosed
  justification.
- **E** — scope creep: capability delivered beyond what this plan or its
  approved batches authorised.

**Finding: there are no D or E items anywhere in Phase 15.** Every
divergence below is either B (disclosed and justified at the time) or C
(a defect fix, empirically reproduced before being made). This was
independently re-verified during this Batch 5 closure by re-reading this
entire plan document end to end and comparing it against the current
state of every Phase 15 production file.

1. **Workflow plan factory omits the `security: SecurityManager` parameter
   proposed in §5's signature.** (B) `workflow/workflow_plan_factory.py`'s
   `build_remember_and_show_plan`/`build_remember_and_forget_plan` take
   only `content: str`. Batch 3 used hardcoded, pre-verified tier/reason
   constants instead of calling `SecurityManager` at plan-construction
   time, since `PlanStep.tier` is display-only and never authoritative
   (§17) — calling `SecurityManager` before a step actually runs would
   have added a second, redundant classification path for no behavioural
   benefit. Disclosed in the Batch 3 closure report.
2. **`input_from_previous_step` is `bool`, not the `str | None` key-naming
   design implied elsewhere in this plan.** (B) `PlanStep` carries only a
   declarative boolean marker; the one concrete propagated field name
   (`memory_id`) is a private constant inside `WorkflowEngine`
   (`_PROPAGATED_FIELD`), not a value stored on `PlanStep`. Batch 1's own
   closure report flagged this narrowing explicitly at the time, on the
   grounds that Phase 15 needs exactly one propagation case, not a
   general keyed-lookup mechanism.
3. **`WorkflowStepOutcome` carries an `approval_request` field not
   itemised in this plan's original model sketch.** (B) Needed so a
   WAITING outcome can carry the exact `ApprovalRequest` the paused
   workflow is blocked on, without inventing a second approval-adjacent
   model; added in Batch 1, exercised starting Batch 3.
4. **Actual audit event names differ from this plan's proposed seven.**
   (B) This plan's earlier drafting proposed
   `workflow_paused`/`workflow_step_blocked`; the delivered set is
   `workflow_started`, `workflow_step_started`, `workflow_step_completed`,
   `workflow_step_waiting`, `workflow_step_failed`, `workflow_completed`,
   `workflow_stopped` — still exactly seven, still orchestration-state
   only. Already flagged as a deliberate refinement in the Batch 2
   closure report.
5. **`WorkflowTraceStep`/`JarvisResponse.workflow_trace` is a concrete
   realisation of this plan's more abstract CLI-presentation goal.** (B)
   Delivered in Batch 4 as a narrow, five-field, default-empty tuple,
   built once after a workflow run/resume completes — explicitly a
   post-run trace, not the live/streaming progress this plan never
   proposed and Batch 2's closure report explicitly rejected adding.
6. **Stale-paused-workflow reaping (`_reap_stale_paused`).** (C) Not
   anticipated anywhere in this plan. Discovered empirically during
   Batch 4: a missed YELLOW approval timeout permanently blocked all
   future `WorkflowEngine.run()` calls, since the paused workflow was
   never removed from the in-memory `_paused` map. Fixed with a helper
   that distinguishes genuine expiry from a decision that has been
   recorded but not yet resumed, using `ApprovalManager.has_pending()`
   and `get_decision()` together.
7. **`ToolExecutor` audit-logger isolation (`_emit_audit_event`).** (C)
   Not anticipated anywhere in this plan, and not a Phase 15 regression —
   the defect existed before Phase 15 but had never been exercised by a
   failing logger in a multi-step context until Batch 4's own
   investigation. A raising logger at any of `ToolExecutor`'s five
   pre-existing emit sites propagated uncaught, losing an already-computed
   authoritative `ToolResult` (or masking a genuine tool exception).
   Fixed in Batch 4A by wrapping only the `logger.emit(...)` call itself
   in `try/except Exception: pass`; classified and closed as **CLOSED**,
   not carried-forward debt — see §16 of the Batch 5 completion report.
8. **`ApprovalManager` audit-logger isolation (`_emit_audit_event`).** (C)
   Same class of pre-existing, not-Phase-15-introduced defect, found via
   the same investigative pattern applied to the Approval Manager in
   Batch 4B. More severe than item 7: a raising logger during
   `approve()`/`decline()` left the decision durably recorded in-memory
   (removed from `_pending`, added to `_decisions`) but never returned to
   the caller, permanently stranding any paused workflow waiting on it.
   Fixed the same way; empirically reproduced before and after the fix;
   classified and closed as **CLOSED** — see §17 of the Batch 5 completion
   report.

No other divergence was found. In particular: the STOP-only failure
policy (§10 of this plan), the reuse of `workflow_id` directly as the
`ApprovalRequest.metadata["workflow_id"]` correlation key (§13), the
single-active-workflow concurrency model (§20), the exact two workflow
commands and their mandatory-colon matching (§8), and the complete
absence of any new `SecurityManager`/`ToolRegistry` dependency inside
`WorkflowEngine` (§9, §17) all match this plan as written — Category A.
