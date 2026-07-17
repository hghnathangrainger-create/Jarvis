# Jarvis — Phase 90 Implementation Plan

**Status:** Planning gate — awaiting explicit approval before Batch 1 begins.
**Version:** Phase 90 — Jarvis Intelligence Core V1 (very risky: planning gate + 3 separately-approved batches)
**Date:** 2026-07-17

---

## 1. Baseline / Closure Verification

Directly verified via `git branch --show-current`, `git log --oneline -5`, `git status --short`, and `poetry run pytest -q`:

```
Branch:        phase-4-ai-reasoning-and-write-actions
HEAD:          04a0f84  Integrate manually-recorded project state into Prompt Studio and close Phase 89 (Batch 2)
                7dfad4c  Fix E402 in new project-state test files (Phase 89, Batch 1 correction)
                cfadc24  Add manually-maintained project-state record (Phase 89, Batch 1)
                d5c582d  Apply titled section styling to Brain tab and close Phase 88 (Batch 2)   <- Phase 88 closure, confirmed present
                00d1186  Add titled section styling to Overview tab (Phase 88, Batch 1)
Full suite:    4318 passed, 3 skipped, 0 failed
git status:    ?? dashboard_test.txt   (only entry)
```

**No discrepancy found.** Phase 88 closure (`d5c582d`) and Phase 89 closure (`04a0f84`, HEAD) both confirmed directly from history. `dashboard_test.txt` was not opened, read, or interacted with — only its presence in `git status --short` output was observed, per the standing constraint.

---

## 2. Current Architecture Map

| Module | Responsibility | Main interfaces | Dependencies | Role today | Phase 90 reuse | Must not change | Gaps |
|---|---|---|---|---|---|---|---|
| `main.py` | Composition root | `build_orchestrator() -> JarvisOrchestrator` | everything below | Wires all ~30 tools + collaborators once | Reuse as-is; add new intelligence-layer wiring here, same pattern as Phase 86/89 tool wiring | The construction order invariant (`reload_pending()` before `reload_paused()`) | — |
| `core/orchestrator.py` | Request dispatch | `handle_request(text) -> JarvisResponse`, `execute_approved(response, decision)` | Planner, CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine, AIReasoningEngine | ~15-matcher dispatch chain, terminal per-match, generic fallback last | Add new private handler(s) + new position in the existing chain (additive only) | The existing dispatch order (documented as load-bearing where grammars are superset strings) | No context-assembly step exists before any AI call |
| `core/command_router.py` | Text → tool name/input | `match(text) -> str\|None`, `build_input(tool_name, text) -> dict` | none (pure string matching) | 100% deterministic, confirmed no AI import anywhere | Add new `match_*`/`build_*_input` functions, purely additive | Zero modification to existing prefix tables/functions | — |
| `core/request_models.py` | Response/request shape | `JarvisResponse` (frozen dataclass, 11 fields), `JarvisRequest`, `WorkflowTraceStep` | none | The one object every caller/test depends on | Extend with **one new optional field**, via `dataclasses.replace()` exactly as `ai_suggestion` was added | All 11 existing fields, their types, and defaults | No field carries verification/step-execution detail (deliberately narrow) |
| `planner/plan_models.py` | `Plan`/`PlanStep` shape | plain dataclasses | none | Generic, reusable executable-plan format already consumed by `WorkflowEngine` | **Reuse as the execution target** — Phase 90 constructs real `Plan`/`PlanStep` instances at execution time | `PlanStep` has **no** retry/status/depends-on fields — this is an actively-tested invariant (`test_plan_step_has_no_retry_fields`). Do not add fields here. | — |
| `workflow/workflow_plan_factory.py` | 5 hardcoded 2-step plans | `build_*_plan(...)` functions | `Plan`/`PlanStep` only | CommandRouter-matched literal-text workflows | Not reused directly (bespoke); its *pattern* (write-then-read-back) is directly reused for verification design | The 5 existing builders themselves | No general "build an arbitrary Plan" capability |
| `workflow/engine.py` | Multi-step execution | `run(plan)`, `resume(id, decision)`, `reload_paused()`, `has_paused()` | ToolExecutor, ApprovalManager, PausedWorkflowStore, WorkflowHistoryStore | Executes any valid `Plan` step-by-step through the unmodified `ToolExecutor`; STOP-only on failure; one paused workflow at a time; fixed 2-key propagation table | **Reuse unchanged as the actual execution engine** for Phase 90 plans (Batch 3) | The STOP-only, no-retry, single-paused-workflow invariants; the fixed propagation table | No retry, no replanning, no step-count limit anywhere (confirmed absent, not just unimplemented) |
| `workflow/paused_workflow_store.py` + `storage/models.py::PausedWorkflowState` | Durable pause state | `PausedWorkflowRecord` (10 fields) | `Plan`/`PlanStep` (JSON) | Restart-survivable pause | Reuse unchanged | Fail-closed `reload_paused()` revalidation chain (depends on `ApprovalManager.reload_pending()` running first) | — |
| `workflow/workflow_history_store.py` | Append-only lifecycle log | `KNOWN_WORKFLOW_STATUSES` (7 values) | none | Durable audit trail | Reuse unchanged | Append-only, no `tool_input` column (deliberate) | — |
| `tools/base_tool.py` | Tool contract | `ToolRequest` (3 fields), `ToolResult` (7 fields), `BaseTool` | none | Universal contract every tool implements | Reuse unchanged | Exact field set (confirmed, no hidden fields) | — |
| `tools/registry.py` | Tool lookup | `register_tool`, `get_tool`, `has_tool`, `list_tools`, `list_tool_names` | none | Name/description only | Reuse unchanged; **the only source of truth for "does this capability exist"** | — | **No schema/input-shape introspection exists** — only name + one-line description. |
| `tools/executor.py` | Classify + run | `execute(tool_name, input_data, session_id, approval_decision) -> ToolResult` | ToolRegistry, SecurityManager | RED never runs; YELLOW runs only with an approved decision; GREEN always runs; never touches ApprovalManager itself | **Reuse unchanged as the single execution chokepoint** — Phase 90 must never call `tool.run()` directly | Classification-before-execution ordering; no retry/timeout (confirmed absent) | — |
| `security/security_manager.py` | Tier classification | `classify_action`, `evaluate_unexpected_action`, `scan_for_injection` | none | The sole authority for GREEN/YELLOW/RED | Reuse unchanged, 100% | Rule table, most-severe-wins ordering | — |
| `approval/approval_manager.py` | YELLOW lifecycle | `create_request`, `approve`, `decline`, `reload_pending`, timeout sweep | PendingApprovalStore, ApprovalHistoryStore | Full pending→decided lifecycle, fail-closed reload | Reuse unchanged | Fail-closed reload validation, single-tier (YELLOW-only) pending invariant | — |
| `ai/reasoning_engine.py` | Advisory-only AI call | `reason(AIReasoningRequest) -> AIReasoningResult \| None` | AIRouter | "Deliberately powerless" — holds no reference to executor/registry/approvals/security by construction | Reuse unchanged as the sole AI entry point | Cannot act; degrades to `None` on any failure | — |
| `ai/router.py` | Prompt→provider→validate | `route(...)`, `is_available()` | ClaudeProvider, PromptBuilder, ResponseValidator | Re-raises failures (audited first) | Reuse unchanged | — | — |
| `ai/prompt_builder.py` + `ai/context_models.py` | Trust-boundary enforcement | `build(...)`, `AIContextBlock` | SecurityManager (injection scan, injected narrowly) | Only `ContentTrust.JARVIS_TRUSTED` (sentinel-enforced) vs `UNTRUSTED`; only untrusted content is scanned | **Reuse unchanged** — every piece of assembled context Phase 90 builds must go through this exactly as today's memory-summary workflows do | The sentinel-enforced trust invariant (cannot forge TRUSTED) | — |
| `ai/response_validator.py` | Non-empty check only | `validate`, `is_complete` | none | **Not a verification concept** — checks only that text is non-blank | Reuse for what it is (basic sanity), but do not mistake it for verification | — | **This is the confirmed gap**: no semantic/structural/scope validation exists anywhere |
| `ai/memory_selection.py` | Deterministic memory selection | `select_*_ids_*` functions | MemoryManager | Fixed ceiling of 10, no ranking/dedup/re-sort (explicit invariant) | **Reuse directly** as the memory-retrieval half of context assembly | The "no ranking" invariant, the ceiling-of-10 precedent | — |
| `ai/memory_ingestion.py` | Truncation/combination | `ingest_*_for_ai` functions | MemoryManager | `4000`/record, `20_000` total char budget, truncation notices | **Reuse the exact constants/pattern** for the new context-assembly budget | — | — |
| `memory/memory_manager.py` | Memory CRUD/search | `search`, `list_recent`, `list_by_category`, `count*` | EpisodicMemoryStore | Substring match only, reverse-chronological only, no relevance ranking | Reuse unchanged | — | No true relevance ranking exists anywhere in the memory layer |
| `project_state/project_state_store.py` | Manual project state | `get() -> ProjectStateRecord \| None` | none | Phase 89's own singleton record | Reuse unchanged — direct dependency, exactly as `PreparePromptTool` already does | Never scrape `ProjectStateShowTool` text output | — |
| `tools/builtin/jarvis_brain_tool.py` / `ai/prompt_studio.py` | Self-status / offline prompt assembly | `get_context()`, `build_prompt()` | none (prompt_studio deliberately AI-free) | Confirmed disconnected from `AIRouter`/`PromptBuilder` by design | Not reused directly (different purpose: manual copy/paste, not live reasoning) | — | — |

**Confirmed, repo-wide gaps relevant to the intelligence loop:**
1. No multi-source context-assembly layer of any kind.
2. No session/conversational history concept anywhere (confirmed absent, not partial).
3. No verification/evidence concept anywhere (`ResponseValidator` is a non-empty-text check only).
4. No generic AI-driven Plan construction — only 5 hardcoded factories.
5. No retry/replanning/step-limit concept anywhere — and this absence is **actively tested for** (`test_no_retry_on_failure`, `test_plan_step_has_no_retry_fields`, `test_green_no_retry_with_raising_logger`), meaning "no retry" is a deliberate, locked invariant of the current system, not an oversight.
6. No tool capability/schema introspection beyond name + one-line description.

---

## 3. Current Request-Lifecycle Traces

**(1) Known deterministic GREEN command** (e.g. `"list files"`):
`CommandRouter.match()` → tool name → `CommandRouter.build_input()` → `ToolExecutor.execute()` → `SecurityManager.classify_action(tool.action_for(request))` → GREEN → `tool.run()` → `ToolResult` → `JarvisResponse(success=True, message=result.output, ...)`. Zero AI involvement anywhere.

**(2) Existing AI-reasoning command** (e.g. `"summarise memories about <query>"`):
`CommandRouter.match_memory_query_summary()` (deterministic grammar detection only) → orchestrator's `_handle_memory_query_summary_request` → `ai.memory_selection.select_memory_ids_by_query()` (deterministic substring search, capped at 10) → `ai.memory_ingestion.ingest_memories_for_ai()` (truncates/combines, tags `ContentTrust.UNTRUSTED`) → `AIReasoningEngine.reason()` → `AIRouter.route()` → `PromptBuilder.build()` (wraps untrusted content, scans for injection, never scans the live request) → `ClaudeProvider.generate()` → `ResponseValidator.validate()` (non-empty only) → response composed with a fixed disclosure label (e.g. `[AI query summary - advisory only]`) → every `AISuggestedAction` funneled through `SecurityManager.evaluate_unexpected_action()` for observability only.

**(3) YELLOW write command through approval** (e.g. `"delete file x.txt"`):
`CommandRouter.match()` → `ToolExecutor.execute()` → classify YELLOW → `requires_confirmation=True`, tool never runs → orchestrator creates `ApprovalManager.create_request(..., tool_name, tool_input)` → `JarvisResponse.approval_request` set → user approves → `ApprovalManager.approve()` → `JarvisOrchestrator.execute_approved(response, decision)` → `ToolExecutor.execute(tool_name, tool_input, approval_decision=decision)` → re-classifies (still YELLOW), now runs.

**(4) Paused/resumed workflow** (e.g. `"remember this and forget it: X"`):
`workflow_plan_factory.build_remember_and_forget_plan()` → `WorkflowEngine.run()` executes step 1 (GREEN, real memory save) → step 2 (YELLOW forget) triggers `ApprovalManager.create_request(metadata={"workflow_id": ...})`, `WorkflowEngine` stores `_PausedWorkflow` in-memory + durably via `PausedWorkflowStore` → user approves → `execute_approved()` detects `workflow_id` in `approval_request.metadata` → `WorkflowEngine.resume(workflow_id, decision)` validates `decision.request_id` matches the paused workflow's own recorded id (else `WorkflowError`, zero execution) → continues via the same `ToolExecutor`.

**Integration boundaries where Phase 90 hooks can be inserted without bypassing controls:**
- Context assembly can be inserted as a **new, additive pre-step**, only ever invoked from a **new**, explicit command trigger — never intercepting any of the 15 existing matchers or the generic tool-dispatch fallback.
- Planning can construct real `Plan`/`PlanStep` instances and hand them to the **unmodified** `WorkflowEngine.run()` — this is the single most important reuse finding: Phase 90 does not need new execution/pause/resume machinery at all.
- Tool selection must be validated through `ToolRegistry.has_tool()` before ever appearing in a constructed `PlanStep.tool_name`.
- Security/approval must flow through the **unmodified** `ToolExecutor.execute()` → `SecurityManager.classify_action()` chain — a plan's own risk-tier hint is always non-authoritative (exactly matching the existing `PlanStep.tier` precedent).
- Verification is the one genuinely new concept — best inserted as a step **after** `ToolExecutor.execute()` returns, using the exact "write then read back" pattern the 5 existing fixed workflows already demonstrate.

---

## 4. Gaps in the Intelligence Loop

(Consolidated from Section 2/3 above — this is the complete list, no others found):
1. No multi-source, bounded context-assembly layer.
2. No session/conversational history.
3. No verification/evidence concept (confirmed via repo-wide grep — every "verify" hit is incidental prose).
4. No generic AI-driven Plan construction (only 5 hardcoded, CommandRouter-triggered factories).
5. No retry/replanning/step-limit concept — and its absence is an actively-enforced, tested invariant today.
6. No tool capability/schema introspection beyond name + description.
7. `PlanStep` cannot carry new bookkeeping fields (retry, verification, etc.) without breaking a locked invariant — a new, parallel contract is required.

---

## 5. Proposed Phase 90 Architecture

A new top-level package, **`intelligence/`**, holding only genuinely new contracts, kept structurally separate from `ai/` (prompt-building/reasoning), `planner/` (existing Plan/PlanStep), and `workflow/` (execution engine) — because Phase 90 is a new architectural *layer* sitting on top of all three, not an extension of any single one.

```
intelligence/
    context.py       (Batch 1: ContextItem, AssembledContext, ContextAssembler)
    intent.py        (Batch 2: InterpretedIntent, ExecutionStrategy, ExecutionStrategyDecision)
    planning.py       (Batch 2: StructuredPlan, StructuredPlanStep)
    verification.py  (Batch 3: VerificationResult, verification policy functions)
    execution.py      (Batch 3: StepExecutionRecord, RetryReplanDecision, the StructuredPlan → real Plan/PlanStep bridge)
```

Every module here is **consumed by, never replaces**, a small number of new private handlers in `core/orchestrator.py`, triggered by a small number of new, explicit grammar phrases in `core/command_router.py` — mirroring exactly how the 7 existing AI-summary workflows and 5 existing fixed workflows are already integrated. No existing dispatch-chain entry, tool, or contract is modified in place.

---

## 6. Exact Structured Contracts

For each type: exact fields, creator, consumer, persistence, limits/invariants.

**`ContextItem`** (Batch 1)
```python
@dataclass(frozen=True, slots=True)
class ContextItem:
    text: str
    source: str              # "memory" | "project_state" | "tool_registry" | "paused_workflow"
    trust: ContentTrust       # reused enum; always UNTRUSTED (see §8)
    relevance_reason: str     # short, human-readable — explainability requirement
```
Creator: `ContextAssembler`. Consumer: `AssembledContext.items`, eventually `PromptBuilder` via existing `AIContextBlock.from_untrusted()`. Persistence: none (transient, per-request). Invariant: `trust` can never be `JARVIS_TRUSTED` here — the existing sentinel mechanism in `ai/context_models.py` already makes this unforgeable.

**`AssembledContext`** (Batch 1)
```python
@dataclass(frozen=True, slots=True)
class AssembledContext:
    request_text: str                    # the live, trusted request itself
    items: tuple[ContextItem, ...]        # capped, see §8
    total_chars: int
    truncated: bool
    excluded_reason: str | None           # e.g. "no matching memories found"
```
Creator: `ContextAssembler.assemble(request_text)`. Consumer: new orchestrator handler(s); later Batches 2/3's planning step. Persistence: none. Limits: see §8.

**`InterpretedIntent`** (Batch 2)
```python
@dataclass(frozen=True, slots=True)
class InterpretedIntent:
    raw_request: str          # verbatim, always carried through
    goal: str                 # AI-paraphrased — advisory, never authoritative
    constraints: tuple[str, ...]
```
Creator: a thin wrapper over `AIReasoningEngine.reason()` given the assembled context. Consumer: planning step. Persistence: none. Invariant: **never trusted as structurally valid** — `ResponseValidator` only checks non-blank text, so `goal`/`constraints` are treated as advisory hints only; actual capability selection is independently, deterministically validated against `ToolRegistry` (see §7).

**`ExecutionStrategy`** (enum) / **`ExecutionStrategyDecision`** (Batch 2)
```python
class ExecutionStrategy(Enum):
    CONVERSATIONAL = "conversational"
    CONTEXT_RETRIEVAL_ONLY = "context_retrieval_only"
    SINGLE_TOOL = "single_tool"
    MULTI_STEP_WORKFLOW = "multi_step_workflow"

@dataclass(frozen=True, slots=True)
class ExecutionStrategyDecision:
    strategy: ExecutionStrategy
    reason: str
```
(Deterministic routing is not a member here — by the time this decision is made, `CommandRouter.match()` has already returned `None`; there is nothing left to "decide" about deterministic routing at this layer.) Creator: the planning step. Consumer: execution step (Batch 3) to decide whether to build a 1-step or N-step `StructuredPlan`. Persistence: none.

**`StructuredPlanStep`** (Batch 2/3 — deliberately separate from `planner.plan_models.PlanStep`)
```python
@dataclass(frozen=True, slots=True)
class StructuredPlanStep:
    step_number: int
    description: str
    capability_name: str          # MUST pass ToolRegistry.has_tool() before use
    arguments: dict[str, object]
    risk_tier_hint: str            # display-only, non-authoritative — mirrors PlanStep.tier precedent
    approval_required_hint: bool   # display-only — real answer always from classify_action()
    success_condition: str         # plain description, not a predicate DSL (deliberate V1 simplification)
    verification_required: bool
    max_retries: int                # capped, see §9
```
**Why a new type, not an extension of `PlanStep`**: `PlanStep` has no retry/verification fields, and this is an actively-tested invariant (`test_plan_step_has_no_retry_fields`). Adding fields there would break a locked contract. Instead, at execution time (Batch 3), a `StructuredPlanStep` is **translated** into a real `planner.plan_models.PlanStep` (dropping the Phase-90-only bookkeeping fields) so the unmodified `WorkflowEngine.run()` can execute it exactly as it executes any hand-written fixed-workflow plan.

**`StructuredPlan`** (Batch 2)
```python
@dataclass(frozen=True, slots=True)
class StructuredPlan:
    goal: str
    context_reference_ids: tuple[str, ...]   # which ContextItems were used — explainability
    constraints: tuple[str, ...]
    steps: tuple[StructuredPlanStep, ...]     # capped, see §9
    max_replans: int                          # capped, see §9
```
Creator: planning step. Consumer: Batch 3's execution bridge (→ real `Plan`) and the final response (for an honest "here's what I planned" disclosure). Persistence: **none** — transient, built and consumed within one request's lifecycle. (A durable plan-history table is explicitly rejected for V1, §18.)

*(Note: no separate `SelectedCapability` or `RiskApprovalRequirement` type is proposed — `capability_name`/`risk_tier_hint` above and the existing, already-defined `SecurityDecision` cover this without decorative wrapper types, per the "do not add types merely for decoration" instruction.)*

**`VerificationResult`** (Batch 3)
```python
@dataclass(frozen=True, slots=True)
class VerificationResult:
    verified: bool
    method: str          # "read_back_tool" | "success_condition_match" | "unverifiable"
    evidence: str         # short, real output snippet — never fabricated
    detail: str | None
```
Creator: the new verification step, after a real `ToolExecutor.execute()` call returns. Consumer: `StepExecutionRecord`, final response. Persistence: none for V1 (transient; optionally logged via the existing `EventLogger`, not a new durable table).

**`ContinuationDecision`** (enum) / **`RetryReplanDecision`** (Batch 3)
```python
class ContinuationDecision(Enum):
    CONTINUE = "continue"
    RETRY_STEP = "retry_step"
    REPLAN = "replan"
    STOP = "stop"

@dataclass(frozen=True, slots=True)
class RetryReplanDecision:
    decision: ContinuationDecision
    reason: str
    attempts_used: int
    attempts_remaining: int
```
Creator: execution loop, after each step's `ToolResult`/`VerificationResult`. Consumer: the loop itself (whether to continue). Persistence: none.

**`StepExecutionRecord`** (Batch 3 — internal bookkeeping, distinct from the existing, deliberately-narrow `WorkflowTraceStep`)
```python
@dataclass(frozen=True, slots=True)
class StepExecutionRecord:
    step_number: int
    intended_action: str
    capability_name: str
    supplied_arguments: dict[str, object]
    risk_tier: SecurityTier          # REAL tier from classify_action(), not the hint
    approval_state: str              # "not_required" | "pending" | "approved" | "declined" | "expired"
    tool_result: ToolResult | None
    verification: VerificationResult | None
    continuation: RetryReplanDecision
```
Persistence: transient, in-memory for the duration of one request. Only a narrow summary of this ever reaches the user-facing response — mirroring `WorkflowTraceStep`'s own existing "never expose raw `ToolResult`/`tool_input`" discipline.

**Final grounded response**: no new type. `JarvisResponse` gains **one new optional field**, added the exact same way `ai_suggestion` was added (via `dataclasses.replace()`, defaulting to an empty value so every existing caller/test is unaffected):
```python
intelligence_trace: tuple[str, ...] = ()   # short, human-readable step summaries only
```

**Memory/outcome policy**: not a dataclass — a plain policy statement for V1 (see §12). No new type needed.

---

## 7. Deterministic-First Routing Boundary

- **How known commands stay deterministic**: `CommandRouter.match()` is checked first, byte-for-byte unmodified, in its existing position at the head of the dispatch chain. Nothing in Phase 90 touches this function or its call order.
- **When the intelligence path is entered**: only via a **new, explicit, narrow trigger grammar** (e.g. an `"ask jarvis"`-prefixed phrase — the exact wording must be grep-verified against every existing prefix/exact table before implementation, exactly as was done for `"jarvis brain"`/`"prepare"` in Phases 86/89). This is **not** a silent catch-all for unmatched text — anything not using the new trigger falls through to the existing, unchanged `_unrecognised_green_response()` exactly as it does today.
- **Design classification**: explicit-command-driven, not fallback-only. This is a deliberate, conservative choice (see §18 for the rejected alternative).
- **Ambiguity handling**: if no real, registered capability can be identified for the interpreted goal, the honest response is "I could not find a suitable existing capability for this" — never a guess, never an invented tool name (enforced by requiring `ToolRegistry.has_tool()` to pass before any `capability_name` is used).
- **AI/provider unavailable**: reuses the existing, already-proven pattern exactly — `AIReasoningEngine.reason()` returns `None` on any failure/unavailability, and the honest "AI reasoning is not available" message already used by the 7 existing AI-summary workflows is reused verbatim.
- **Backward compatibility**: 100% — the new trigger phrase cannot collide with anything not already using those exact words (verified by grep before implementation), and every existing call path (CommandRouter, ToolExecutor, WorkflowEngine, SecurityManager, ApprovalManager) is untouched.

---

## 8. Context Policy and Hard Limits

- **Eligible sources**: current request text (the only `JARVIS_TRUSTED` item, via `AIContextBlock.from_live_user_input()`); relevant memories (via `MemoryManager.search()`, reusing `ai/memory_selection.py`'s existing ceiling-of-10 precedent); `ProjectState` fields (Phase 89); a tool-list summary (name + description only, from `ToolRegistry.list_tools()`); paused-workflow status (boolean/one-line only, via `WorkflowEngine.has_paused()` — never full plan/tool_input detail).
- **Trust/provenance labels**: reuses the existing two-value `ContentTrust` enum unchanged. **Every retrieved item (memory, project state, tool list, paused-workflow status) is `UNTRUSTED`** — this is not a new design decision, it's a direct consequence of the existing sentinel-enforced invariant in `ai/context_models.py` (only live user input / system instructions may claim `JARVIS_TRUSTED`). This means the existing `PromptBuilder` injection-scan/framing machinery covers all assembled context with **zero changes**.
- **Relevance strategy**: deterministic only for V1 — substring search via the existing `MemoryManager.search()`, no AI-assisted re-ranking (avoids a circular "AI judges its own relevance" design and matches the existing "no ranking" invariant already established for every AI-summary workflow).
- **Maximum memories**: 10 (reusing `ai/memory_selection.py`'s existing `_SELECTION_LIMIT` precedent exactly, not a new number).
- **Maximum characters**: reuse `ai/memory_ingestion.py`'s existing `4000`/record and `20_000`-total-budget constants directly if shape-compatible; otherwise a new, equally conservative constant of the same size.
- **Recency behavior**: reverse-chronological only, matching every existing memory-retrieval precedent — no time-window concept invented.
- **Deduplication**: by memory id (a memory retrieved twice by different criteria is included once).
- **Redaction/secrets**: never include `Settings.anthropic_api_key`'s raw value — reuse the existing "set"/"not set" status-only convention already established in `PromptContext`/`ConfigTool`.
- **Adversarial/injection handling**: no new mechanism needed — every context item is `UNTRUSTED` and therefore already scanned by `PromptBuilder`'s existing, unmodified injection scanner.
- **Paused-workflow inclusion**: status only (a paused workflow exists / does not exist), never its plan or tool_input — matching `WorkflowTraceStep`'s existing narrow-disclosure discipline.
- **Excluded by default**: anything not explicitly retrieved for *this* request (no "dump everything"); full raw `ProjectState.suite_result` text beyond the character budget; any memory beyond the top-10 search results.

---

## 9. Planning / Tool-Selection Policy and Hard Limits

Since **no retry/step-limit/timeout concept exists anywhere in the current system today — and this absence is actively tested for** — every limit below is new, conservative, and explicitly the safest defensible choice for a V1:

| Limit | Value | Rationale |
|---|---|---|
| Max plan steps | **5** | Existing fixed workflows are always exactly 2 steps; 5 gives real headroom for a genuine multi-step task while staying small enough to reason about and test exhaustively. |
| Max workflow "depth" | Same as max steps (5) — `Plan` is a flat sequence, not a tree; there is no separate depth axis. | Matches existing `Plan` shape exactly. |
| Max tools per plan | Bounded by max steps (≤5 distinct or repeated capability selections). | No new concept needed beyond the step cap. |
| Max retries per step | **0 for the V1 default path.** An optional, explicitly-flagged single-retry (1) enhancement is allowed only for a narrowly-defined "verification was inconclusive" case, and is called out in §14/§19 as the first thing to cut if time is short. | "No retry" is the entire existing codebase's tested, deliberate invariant today — the safest baseline is to match it, not silently introduce looping behavior into a very-risky milestone. |
| Max total retries per request | 1 (only if the single-retry enhancement above is attempted at all). | — |
| Max replans | **1** | Bounded, and only ever in direct response to a genuine verification failure — never speculative re-planning. |
| Approval pauses | Reuses `ApprovalManager`'s existing pending/timeout mechanism unchanged — a Phase-90 plan pauses exactly like today's `WorkflowEngine` already pauses (one paused workflow at a time, the existing single-slot invariant). | Zero new approval machinery. |
| Execution timeout | **None invented.** No timeout concept exists anywhere in the reused stack today (`ToolExecutor`, `WorkflowEngine`) — out of scope unless a concrete need surfaces during implementation. | Avoids inventing an unproven mechanism under time pressure. |
| Stopping conditions | Any step failure with no retry budget remaining → stop (matches `WorkflowEngine`'s existing STOP-only invariant exactly); verification failure with no repair path → stop; RED classification → stop immediately, irrecoverably; YELLOW decline/timeout → stop. | Mirrors existing, proven behavior. |

---

## 10. Execution / Approval Integration

- Batch 3 constructs real `planner.plan_models.Plan`/`PlanStep` instances from a `StructuredPlan` at the moment of execution, then hands them to the **unmodified** `WorkflowEngine.run()` — reusing 100% of the existing pause/resume/approval/history machinery. This is the single highest-leverage reuse decision in this plan: no new pause/resume logic is written at all.
- GREEN steps execute immediately via the existing `ToolExecutor.execute()` (called by `WorkflowEngine`, never called directly by the new intelligence code).
- YELLOW steps pause exactly as today — a real `ApprovalManager.create_request()` is created by `WorkflowEngine` itself (not by new code), and resume follows the existing `execute_approved()` → `WorkflowEngine.resume()` path unchanged.
- RED steps are **never** planned as executable — a `StructuredPlanStep` whose real, live `classify_action()` result is RED is refused before it ever reaches `WorkflowEngine`, and even if it somehow did, `ToolExecutor`'s own RED-first check would block it (defense in depth, no new code required to guarantee this — it's already how `ToolExecutor` behaves).

---

## 11. Verification and Bounded Recovery Policy

Per step shape:
- **GREEN read-only step**: `ToolResult.success` proves the *read happened*, not that it answered the *goal*. Verification = a bounded, deterministic check that `ToolResult.output` satisfies the step's own declared `success_condition` string (e.g. "output contains the requested field"). Never re-invoking AI to "judge" its own output — that would be circular and ungrounded.
- **YELLOW write step**: `ToolResult.success` alone is **not** sufficient. V1 policy: require a **read-back** step whenever a real, registered GREEN counterpart tool exists — this is not a new idea; it's the exact pattern the existing `"update memory <id>: X and show it back"` and `"create file X with Y and show it"` fixed workflows already use today. Phase 90 reuses this pattern rather than inventing verification from scratch.
- **When no read-back tool exists**: verification is "execution-evidence-only" (`ToolResult.success` + metadata), and the final response must **explicitly label it as unverified** — never silently upgraded to "confirmed."
- **Verification failure vs. execution failure**: execution failure = `ToolResult.success is False` (the tool itself failed). Verification failure = `ToolResult.success is True` but the read-back/success-condition check did not confirm the goal — these must be reported as distinct, honest outcomes ("Jarvis performed the action; the tool reported success; but could not confirm the change took effect").
- **Verification impossible**: stop safely, report honestly. **"No invented success" is enforced structurally**: the default state of every step is "unverified" — a step is only ever marked `verified=True` when a real check actually ran and passed, never as a default.

---

## 12. Memory / Outcome Policy

**Bias toward the safest minimal V1, stated directly: Batches 1–3 introduce zero automatic memory-writing from intelligence-loop outcomes.** The existing `"remember this: X"` GREEN command remains the *only* way a memory is created, completely unchanged.

Rationale: memory writes are the one part of this system Nathan has always treated as deliberate and manual; auto-memory risks duplicate/junk data and opens a whole new write-classification question inside an already very-risky milestone. Any future "Jarvis remembers what it learned automatically" feature is explicitly deferred to a later phase (§19) — a good candidate for a weaker model to build later, on top of Phase 90's now-proven, documented architecture, once a real need is demonstrated.

- What may be remembered: nothing automatically.
- What requires approval: N/A for V1 (no auto-memory path exists to gate).
- Duplicates: N/A.
- Failures/uncertainty: represented only in the transient `intelligence_trace`/response, never persisted.
- Preferences vs. task state: not distinguished in V1 since nothing is auto-persisted.

---

## 13. Batch 1 Plan — Context Intelligence

**Goal**: A bounded, explainable, multi-source context-assembly layer, proven by one real end-to-end natural request that automatically retrieves relevant memory + project context — no rigid search command required.

**Production files (new)**: `intelligence/__init__.py`, `intelligence/context.py` (`ContextItem`, `AssembledContext`, `ContextAssembler`).
**Production files (modified, additive only)**: `core/command_router.py` (one new `match_context_query`/`build_context_query_input` pair, mirroring the existing `match_memory_query_summary` shape exactly), `core/orchestrator.py` (one new private handler, e.g. `_handle_context_query_request`, inserted into the existing dispatch chain following the exact pattern of the 7 existing AI-summary handlers), `main.py` (wiring only, if `ContextAssembler` needs constructor dependencies).

**Tests (new)**: `tests/unit/test_context_assembly.py` (bounded/dedup/limits/trust-labeling of `ContextAssembler`, structural AST proof it never touches a write method), `tests/unit/test_context_query_routing.py` (CommandRouter match/build_input), `tests/unit/test_orchestrator_context_query.py` (real `MemoryManager` + real `ProjectStateStore` + real `AIReasoningEngine` wired to a fake, non-network provider — mirroring `test_memory_query_summary_workflow.py`'s own established structure exactly).

**Compatibility surface**: purely additive — zero existing behavior changes for any input not using the new trigger phrase.
**Security risks**: none new — every item is `UNTRUSTED`, reusing `PromptBuilder`'s existing, unmodified scanning.
**Migration/persistence**: none — `AssembledContext` is never persisted.
**Focused validation**: `poetry run pytest tests/unit/test_context_assembly.py tests/unit/test_context_query_routing.py tests/unit/test_orchestrator_context_query.py -q`, `poetry run ruff check intelligence/context.py core/command_router.py core/orchestrator.py main.py`.
**Full-suite gate**: `poetry run pytest -q` must still show 4318 + N passed, 0 failed.
**Vertical slice**: `"ask jarvis: what have I been focusing on and what's my current branch?"` → assembles relevant memories (search) + `ProjectState.focus`/`.branch` → advisory AI response labeled `[AI ... - advisory only]`, exactly matching the existing disclosure convention.
**Stop/report point**: full suite + ruff + `git diff --check` clean, Batch 1 report delivered, **explicit approval required before Batch 2 begins.**

---

## 14. Batch 2 Plan — Planning and Tool-Selection Intelligence

**Goal**: `InterpretedIntent`/`ExecutionStrategyDecision`/`StructuredPlan`/`StructuredPlanStep` contracts; bounded selection of exactly one already-registered **GREEN** capability for real, safe execution as this batch's vertical slice (YELLOW selection may be represented/reported but not executed until Batch 3's approval integration exists).

**Production files (new)**: `intelligence/intent.py`, `intelligence/planning.py`.
**Production files (modified, additive only)**: `core/command_router.py` (extend or reuse Batch 1's trigger with a planning-capable variant), `core/orchestrator.py` (new handler building a `StructuredPlan`, validating `capability_name` via `ToolRegistry.has_tool()`, and — for GREEN only — executing via the existing `ToolExecutor.execute()`).

**Tests (new)**: contract unit tests (bounded steps; a plan naming an unregistered tool fails safely, never silently substitutes); structural AST tests proving the new planning module never calls `tool.run()` directly and never bypasses `SecurityManager.classify_action()`; orchestrator/CommandRouter tests for the new path.

**Compatibility surface**: additive; this path is only ever entered when `CommandRouter.match()` already returned `None` and the explicit trigger was used.
**Security risks**: tool selection restricted to GREEN-only real execution this batch — a deliberate, incremental risk staging.
**Migration/persistence**: none.
**Focused validation**: analogous `pytest`/`ruff` commands scoped to the new/changed files.
**Full-suite gate**: unchanged baseline + N passed.
**Vertical slice**: `"ask jarvis: what does my project state currently say?"` → context assembly (Batch 1) → intent interpreted → plan selects the real, registered `project_state_show` GREEN tool → `ToolExecutor` executes it for real → response grounded in the *actual* tool output, not AI paraphrase alone.
**Stop/report point**: full suite + validations, Batch 2 report delivered, **explicit approval required before Batch 3 begins.**

---

## 15. Batch 3 Plan — Safe Execution, Verification, Recovery and Continuation Kit

**Goal**: Extend planning to allow YELLOW steps (still capped, still real registered tools only); bridge `StructuredPlan` → real `Plan`/`PlanStep` for **unmodified** `WorkflowEngine.run()`/`resume()` reuse; add verification (read-back pattern) and the bounded retry/replan policy from §9; create the Continuation Kit as the final step before closure.

**Production files (new)**: `intelligence/verification.py`, `intelligence/execution.py` (includes the `StructuredPlan` → `Plan` bridge), `docs/JARVIS_CONTINUATION_KIT.md` (see §17).
**Production files (modified, additive only)**: `core/request_models.py` (`JarvisResponse` gains one new optional field, `intelligence_trace`, via `dataclasses.replace()`), `core/orchestrator.py` (execution/verification wiring).

**Tests (new)**: full end-to-end vertical-slice tests (GREEN-only and YELLOW-involving), the 8 acceptance scenarios in §16 as concrete test functions, structural proofs that no RED plan step ever reaches execution, that retry/replan counts are hard-capped (parametrized boundary tests), and that a declined/timed-out YELLOW step correctly stops the plan.

**Compatibility surface**: this is the highest-risk batch — every existing security/approval/workflow test must still pass unmodified, since `WorkflowEngine`/`ToolExecutor`/`ApprovalManager`/`SecurityManager` are reused, not forked.
**Security risks**: highest of the three batches — this is where a real YELLOW step actually executes through the new path for the first time. Mitigated entirely by reuse (§10) rather than new execution logic.
**Migration/persistence**: none new (per §12/§18, no new durable tables for plans/verification in V1).
**Focused validation**: full new-file test suite + the acceptance-scenario suite + full regression suite.
**Full-suite gate**: unchanged baseline + N passed, with explicit before/after delta reporting exactly as every phase in this project already does.
**Vertical slice (the complete required loop)**: `"ask jarvis: update my project focus to X and confirm it"` → context assembly → intent → plan (`project_state_update` YELLOW step + `project_state_show` GREEN verification step) → real classification (YELLOW pauses for approval) → user approves → execution via the existing `ApprovalManager`/`ToolExecutor` → verification via read-back → grounded final response confirming the real, verified new value.
**Continuation Kit timing**: written last, after the full vertical slice is proven, tested, and stable — but before the final `docs/phase_90_completion_report.md` (see §17 for exact reasoning).
**Stop/report point**: full suite + validations + Continuation Kit complete, final Phase 90 closure report delivered, **explicit approval required before Phase 90 closes.**

---

## 16. End-to-End Acceptance Scenarios

1. **Batch 1 context retrieval**: `"ask jarvis: what have I been focusing on and what's my current branch?"` → response includes real memory content and real `ProjectState.branch`/`.focus` values, correctly labeled advisory, never fabricated.
2. **Batch 2 natural-request planning + read-only selection**: `"ask jarvis: what does my project state currently say?"` → real `project_state_show` GREEN tool actually executes; response grounded in its real output.
3. **Batch 3 complete loop**: `"ask jarvis: update my project focus to X and confirm it"` → context → plan → YELLOW pause → approval → execution → read-back verification → honest grounded response.
4. **YELLOW cannot execute without approval (regression)**: the Batch 3 plan's write step, run without ever approving it, must show `requires_confirmation=True` and the underlying `ProjectStateStore` record must be provably unchanged.
5. **RED refusal (regression)**: a request whose only matching capability would classify RED must never appear as an executable step in any `StructuredPlan`, and even if forced, `ToolExecutor`'s existing RED-first check blocks it — proven via a structural "never reaches `tool.run()`" test mirroring the existing `_RedTool` tripwire pattern.
6. **Bounded retry/replanning (regression)**: a step engineered to fail verification must stop after the configured limit (0 or 1 retries, 1 replan) — never loop, never silently succeed.
7. **Deterministic-command backward compatibility (regression)**: every existing representative phrase in `test_help_output_routing_consistency.py` must still route exactly as before — proving the new trigger never shadows or alters any existing command.
8. **Provider unavailable/failure honesty (regression)**: with `AI_REASONING_ENABLED=false` or a failing fake provider, every new intelligence-path command must produce the same honest "AI reasoning is not available" pattern the 7 existing AI-summary workflows already use — never a fabricated plan or result.

---

## 17. Continuation Kit Plan

**Location**: a single new file, `docs/JARVIS_CONTINUATION_KIT.md` — matching this repo's own established convention of one flat markdown file per artifact (every phase report already follows this pattern; a new directory-based convention is not introduced without a clear need).

**Contents** (all 13 required items, organized as sections within the one file): verified current project state (commit/branch/suite, restated at kit-finalization time); architecture map (a condensed version of §2 above); module relationships; the intelligence-loop contracts from §6; the security rules that must never be broken (§10's reuse guarantees, stated as hard rules); development/batching workflow (this project's established propose→approve→implement→report→approve cycle); testing/lint/git requirements (the standard validation command set used in every phase); known limits (§9's hard limits, restated); deferred features (§12's memory policy, §18's rejected redesigns); milestone roadmap (what Phase 90 achieved, what's next); a reusable strong-model prompt (for resuming Phase 90-style work with a capable model); a reusable weak-model prompt (for the incremental, lower-risk extensions named in §19); fresh-chat recovery instructions; a batch handoff template; a closure-report template; and the latest verified suite/commit/branch/status.

**When created**: at the very end of Batch 3, **after** the full vertical slice (§15/§16) is proven, tested, and stable — never before, and never as a separate micro-phase.

**Honesty enforcement**: the kit is finalized by re-running the same `git log`/`pytest -q`/`git status --short` commands already used in every phase closure report, and pasting their literal output with an "as of commit X" stamp — exactly matching how every existing completion report already grounds its own numbers. No new automated staleness-detection mechanism is proposed (that would be over-engineering beyond what's asked); the stamp itself lets any future reader immediately tell if the kit predates the current `git log`.

**Generated-from-facts vs. manually-maintained**: verified state/suite/commit/branch is copy-pasted from real command output at finalization time (facts); architecture map/contracts/rules/roadmap are manually authored, grounded in this report and the actual Batch 1–3 implementation (not generated, but fact-checked against the real code one final time before writing).

---

## 18. Risks and Rejected Alternatives

- **Rejected**: making `CommandRouter` itself AI-aware, or silently routing *any* unmatched text through the intelligence path. Violates "do not force every request through an AI planner," breaks the clean deterministic/AI separation that has been a core design principle since Phase 7, and is untestable at the boundary. **Chosen instead**: explicit, new, narrow trigger grammar (§7).
- **Rejected**: extending `planner.plan_models.PlanStep` directly with retry/verification/status fields. Breaks the actively-tested `test_plan_step_has_no_retry_fields` invariant. **Chosen instead**: a new, parallel `StructuredPlanStep` contract that translates into a plain `PlanStep` only at execution time (§6).
- **Rejected**: a general-purpose agent framework with dynamic tool-chaining or open-ended recursion. Explicitly out of scope per Nathan's own instructions; inconsistent with "prefer explicit contracts... over vague agent intelligence."
- **Rejected**: a new durable "conversation history" table for V1. Not explicitly required, carries its own privacy/retention design questions, and would meaningfully expand scope. Each request stays independently assembled from durable sources for V1; true multi-turn memory is a good later-phase candidate.
- **Rejected**: automatic memory-writing from intelligence-loop outcomes in V1 (§12).
- **Rejected**: a new durable persistence table for `StructuredPlan`/`VerificationResult`/`StepExecutionRecord` in V1. Plans are transient, built and consumed within one request only — avoids a whole new persistence/migration surface in an already very-risky milestone.
- **Genuine risk carried forward, not rejected**: Batch 3's YELLOW-execution integration is the one place a real, new code path touches the live approval/execution chain — mitigated entirely by reusing `WorkflowEngine`/`ToolExecutor`/`ApprovalManager` unchanged (§10) rather than writing new execution logic.

---

## 19. Six-Day Feasibility Assessment

Honest assessment, given the research above:

- **Batch 1 is the most achievable in isolation** — additive, reuses ~90% existing machinery (memory search, project state, `AIReasoningEngine`, `PromptBuilder`), small clear surface. Realistically ~1–2 focused days.
- **Batch 2 is medium risk** — new contracts plus careful deterministic-first boundary design, but its own scope is deliberately capped to GREEN-only real execution. Realistically ~2 days.
- **Batch 3 is by far the riskiest and most likely to need descoping.** It requires YELLOW approval integration, the `StructuredPlan`→`Plan` execution bridge, retry/replan bounding, a verification policy across multiple step shapes, all 8 acceptance scenarios, *and* the Continuation Kit. Realistically 2–3+ focused days, and the piece most likely to slip past six days.
- **Minimum valuable stopping point if all three cannot close**: Batch 1 alone, fully closed and proven, is a complete, real, safely-shippable improvement (natural-language, context-aware advisory answers) even if Batches 2/3 don't land in six days. Batch 2 is a reasonable stretch goal. Batch 3's optional single-retry enhancement (§9) is the first thing to cut, followed by narrowing the verification-policy matrix to the single YELLOW scenario proven in §16, if time is genuinely short.
- **What must not be rushed**: the security/approval integration in Batch 3 (any shortcut here directly risks the project's core safety invariant) and the "no invented success" verification-honesty guarantee.
- **Suitable for a weaker model later**: additional context sources (inbox/schedule history), broader multi-tool planning (>1 capability per plan), an eventual auto-memory-write policy, additional verification step-shapes, and dashboard visibility for the intelligence loop (explicitly frozen this milestone per Nathan's own instruction) — all good candidates once Phase 90's architecture is proven and documented in the Continuation Kit.

---

## 20. Likely Files Affected

**New**: `intelligence/__init__.py`, `intelligence/context.py`, `intelligence/intent.py`, `intelligence/planning.py`, `intelligence/verification.py`, `intelligence/execution.py`, `docs/JARVIS_CONTINUATION_KIT.md`, `docs/phase_90_completion_report.md`, plus one test file per new module and per new orchestrator/router integration point (~10-12 new test files across the three batches).
**Modified (additive only)**: `core/command_router.py`, `core/orchestrator.py`, `core/request_models.py` (one new optional field), `main.py` (wiring), `docs/user_guide.md` (if a new user-facing command is added), `tools/builtin/help_tool.py` (if a new user-facing command is added).
**Never modified**: `tools/base_tool.py`, `tools/registry.py`, `tools/executor.py`, `security/security_manager.py`, `approval/*.py`, `workflow/engine.py`, `workflow/paused_workflow_store.py`, `workflow/workflow_history_store.py`, `workflow/workflow_plan_factory.py`, `planner/plan_models.py`, `ai/reasoning_engine.py`, `ai/router.py`, `ai/prompt_builder.py`, `ai/context_models.py`, `ai/response_validator.py`, `ai/providers/*.py`, `memory/*.py`, `project_state/*.py`.

---

## 21. Validation Strategy

Per batch, the same discipline every phase in this project already uses: focused `pytest` on new/changed files → full `poetry run pytest -q` gate (exact before/after delta reported) → `poetry run ruff check` on every new/changed file (exit code 0 required, no new lint debt) → `git diff --check` → `git status --short`. Additionally, for every batch touching the intelligence path: structural AST tests proving no bypass of `SecurityManager.classify_action()` and no direct `tool.run()` call outside `ToolExecutor`.

---

## 22. Explicit Out-of-Scope Confirmation

Confirmed **not** touched by this plan or any batch within it: dashboard appearance polish or animations; dashboard write actions; voice/microphone/wake-word/hotkey/always-listening behavior; phone integration; any new paid-provider dependency (only the existing, already-optional Claude path is reused, never newly required); unrestricted autonomous agents; autonomous self-improvement; automatic source-code modification; Jarvis editing/patching/staging/committing to its own repository; live git/subprocess/filesystem project-state detection; automatic test-suite detection; RED execution; `SecurityManager` bypass or weakening; unlimited planning/retry/replanning loops; replacement of any stable deterministic command; a general plugin framework; unrelated command additions; surface-level output polish not required by the intelligence loop; unrelated cleanup; E402 cleanup.

---

## 23. `dashboard_test.txt` Confirmation

Confirmed untouched, untracked, and uncommitted throughout this planning pass — observed only as a `git status --short` entry, never opened, read, staged, or otherwise interacted with. This plan's three batches introduce no dashboard code changes of any kind (per the explicit dashboard-appearance freeze), so no batch will interact with this file either.

---

## 24. Planning Gate Amendment — Safety and Integration Corrections

**Sections 1–23 above are preserved unchanged as the original planning record.** External architecture review identified blocking contradictions and missing safety contracts in that record. This section **supersedes** every conflicting decision named below; anywhere this section is silent, Sections 1–23 still govern. Two items required direct, targeted repository inspection beyond what Sections 1–23 already established — `workflow/workflow_models.py` (`WorkflowResult`, `WorkflowStepOutcome`) and `approval/approval_models.py` (`ApprovalRequest`) were read in full during this amendment pass to ground item C.12 in real fields rather than assumption.

### A. Corrected Batch 1 context contracts

**A.1 — `ContextItem` gains a stable, deterministic `context_id`, and `source` becomes a bounded enum.** Supersedes the `ContextItem` shape in §6.

```python
class ContextSource(Enum):
    MEMORY = "memory"
    PROJECT_STATE = "project_state"
    # Batch 2/3 add new members only when a real consumer exists for them -
    # never speculatively, per the original plan's own "no decorative types" rule.

@dataclass(frozen=True, slots=True)
class ContextItem:
    context_id: str            # deterministic, see format below
    source: ContextSource
    source_record_id: str | None   # e.g. the real memory id as a string; None for the singleton ProjectState item
    text: str
    trust: ContentTrust         # always ContentTrust.UNTRUSTED for every ContextItem in Batch 1 (see A.3)
    relevance_reason: str
```

`context_id` format: `f"{source.value}:{source_record_id}"` when a real record id exists (e.g. `"memory:42"`), or `f"{source.value}:current"` for the singleton ProjectState item (e.g. `"project_state:current"`, since exactly one ProjectState record can ever exist per Phase 89's own singleton-store invariant). **Proof of no secret/raw content**: the id is built *only* from the fixed enum value string and a real, already-non-secret numeric id or the fixed literal `"current"` — it is never derived from `.text`, never from any memory content, project-state field value, or credential. This is provable by construction: the format string takes only `source` and `source_record_id` as inputs, never `text`.

The live request itself is **not** a `ContextItem` — it remains `AssembledContext.request_text` exactly as in the original §6 design, since it is the one `ContentTrust.JARVIS_TRUSTED` piece of the whole assembly and keeping it structurally separate (never itemized) makes that trust boundary impossible to blur by construction.

**A.2 — `AssembledContext.excluded_reason` (singular, `str | None`) is replaced with `notes: tuple[str, ...]`.** Supersedes the corresponding field in §6.

```python
@dataclass(frozen=True, slots=True)
class AssembledContext:
    request_text: str
    items: tuple[ContextItem, ...]
    total_chars: int
    truncated: bool
    notes: tuple[str, ...]   # e.g. ("no matching or recent memories found", "project state has no recorded focus")
```

This allows multiple, independently true omissions/truncations to be reported honestly at once (e.g. "no memories matched" and "project state was never recorded" can both be true in the same assembly) rather than forcing a single reason to stand in for several.

**A.3 — Batch 1 context sources are exactly three, and tool/security data is explicitly excluded.** Supersedes §8's "eligible sources" list for Batch 1 specifically (Batch 2/3 introduce their own, separately-governed mechanisms below — not via `ContextItem`).

Batch 1's vertical slice draws from exactly: (1) the live request (`request_text`, trusted, not itemized); (2) memory items selected per A.4; (3) one singleton `ProjectState` item per A.6. **Tool capability names/descriptions and security/approval rules are never represented as `ContextItem`s in any batch** — they are deterministic internal authority, governed entirely by the new capability-catalog mechanism in §24.B, never AI-reinterpretable free text. Paused-workflow status is deferred entirely out of Batch 1 — no concrete Batch 1 vertical-slice requirement consumes it, and inventing a placeholder relevance rule for a source nothing yet needs would be exactly the "types/sources added for decoration" the original plan already disclaimed.

**A.4 — Exact deterministic memory-selection algorithm.** Supersedes §8's "deterministic only... substring search" description, which the original plan left too vague to prove genuine relevance (a raw multi-word natural-language sentence passed whole to `MemoryManager.search()` as a single substring query would almost never match real memory content).

- **Query derivation**: lowercase the raw request, split on non-alphanumeric characters, drop any token in a small, fixed, hand-maintained stopword tuple — `("the", "a", "an", "is", "are", "was", "were", "what", "have", "has", "had", "i", "my", "me", "you", "your", "it", "do", "does", "did", "can", "could", "and", "or", "to", "for", "on", "in", "of", "about", "currently", "current")` — and drop any remaining token shorter than 4 characters. Take up to the first 5 surviving tokens, in their original left-to-right order, as the query terms. If zero terms survive, skip lexical search entirely and go straight to recency fallback.
- **Lexical pass**: for each query term, in order, call `MemoryManager.search(term, limit=5)`. Merge results across terms in term order; deduplicate by memory id, first occurrence wins (preserving whichever term found it first). Stop adding once the memory-item budget (5, see A.5) is reached.
- **Recency fallback**: if the memory-item count after the lexical pass is still below the budget (including the zero-terms case), fill the remaining slots with `MemoryManager.list_recent(limit=<remaining slots>)`, skipping any id already included from the lexical pass.
- **Merge order**: lexical matches first (in term order), recency-fallback matches appended after.
- **Dedup rule**: by memory id, first occurrence kept.
- **Zero-match behavior**: if both passes return nothing (e.g. an empty memory store), this is not an error — record a `notes` entry (`"no matching or recent memories found"`) and continue assembling the rest of the context.
- **Search-failure behavior**: if either `MemoryManager` call raises, catch it, record a `notes` entry (`"memory retrieval failed: <short, non-sensitive reason>"`), and continue with whatever other sources succeeded — one source's failure never aborts the whole assembly, mirroring this project's own established per-source isolation discipline (e.g. the dashboard read model's per-panel isolation).
- **No AI selects memories in Batch 1** — the entire algorithm above is deterministic string processing only.

**A.5 — Exact context budgets.** Supersedes §8's "maximum memories: 10" / character-limit language, which reused the ingestion module's own 4000/20,000 constants without adjusting them for this narrower, single-turn feature.

| Item | Value |
|---|---|
| Maximum total `ContextItem`s | 6 (up to 5 memory + up to 1 ProjectState) |
| Maximum memory items | 5 (deliberately tighter than `ai/memory_selection.py`'s existing ceiling-of-10 precedent, since that ceiling was sized for a dedicated memory-summary command, not a multi-source assembly that must also reserve room for ProjectState) |
| Maximum characters per item | 500 |
| Maximum total assembled-context characters | 3000 |
| Does `request_text` count toward the budget? | No — the budget governs only `items`; the live request is bounded only by whatever the user actually typed, unchanged from today. |
| Do labels/framing count? | No — the budget counts each `ContextItem.text`'s own raw length only; `PromptBuilder`'s header/footer framing is applied afterward and is that module's own, separate, already-existing concern. |
| Source priority | ProjectState is always attempted first (cheap, singleton, ≤1 item) and reserves 500 characters off the top of the 3000 total; the remaining 2500 characters are available for up to 5 memory items at 500 characters each. |
| Truncation vs. whole-item omission | Per-item truncation (reusing `ai/memory_ingestion.py`'s existing truncate-with-notice pattern) applies when one item's own text exceeds its 500-character cap. Whole-item omission applies only when even a fully truncated item would exceed the *remaining* total budget — in that case the item is dropped entirely and a `notes` entry records how many items were omitted this way. |
| Unused-reservation behavior | If ProjectState's real content is under 500 characters (typical), the unused remainder is **not** reallocated to memory items in Batch 1 — a deliberate, simple, fixed-reservation policy; dynamic budget-sharing is a plausible future refinement, not required for V1. |

**A.6 — Phase 89 honesty is reused verbatim, not reinvented.** The single ProjectState `ContextItem.text` embeds the exact same disclosures Phase 89 Batch 2 already established for Prompt Studio's "Project Context" section: every included field is labeled manually recorded, not auto-detected, possibly stale; `last_updated` is shown as the real timestamp or `"not recorded yet"`; any individual field never recorded shows the same `[FILL IN]` placeholder `ai/prompt_studio.py`'s `ProjectStateContext`/`_field_or_fill_in` already produces. This is a direct reuse of that existing formatting logic, not new wording.

**A.7 — Exact Batch 1 command grammar and dispatch position.**

- Exact phrase: `"ask jarvis: <request>"` (colon required, mirroring the `"update jarvis project state:"` colon-prefix convention Phase 89 already established for unambiguous prefix/remainder splitting). The literal wording is grep-verified against every existing exact-phrase/prefix table in `core/command_router.py` as the *first concrete step of Batch 1 implementation itself* — not asserted here without that check.
- Empty-request behavior: `"ask jarvis:"` with nothing (or only whitespace) after the colon returns an honest failure ("Please include what you'd like to ask after 'ask jarvis:'") — it never proceeds to context assembly or AI reasoning with an empty goal.
- Near-miss behavior: `"ask jarvis"` (no colon), `"ask jarvis about X"`, and `"jarvis, ask: X"` must not match — only the exact, case-insensitive `"ask jarvis:"` prefix matches, proven by dedicated near-miss tests mirroring this project's established "near-misses do not accidentally route" convention.
- Dispatch-chain position: added as the **last** of `core/orchestrator.py`'s special matchers, checked immediately before the existing generic fallback (`_handle_request_core`). Since no existing deterministic command or special matcher starts with `"ask jarvis:"` (per the grep check above), this cannot shadow or steal priority from any of them — any request not starting with this exact prefix falls through to the existing, completely unchanged deterministic path.
- HelpTool/`docs/user_guide.md`: updated **in Batch 1 itself**, not deferred — following this project's own established Phase 86/87/89 discipline of documenting a new command in the same batch it ships, to avoid recreating the Phase-58-class "shipped but undocumented" gap.

### B. Bounded capability-adapter architecture for Batch 2

**B.8 — `ToolRegistry.has_tool()` is a final existence check, never an input-schema validator.** A new, narrow, hand-maintained allowlist governs what the intelligence layer may even consider:

```python
class CapabilityId(Enum):
    PROJECT_STATE_SHOW = "project_state_show"
    # Batch 3 adds: PROJECT_STATE_UPDATE_FOCUS, PROJECT_STATE_VERIFY_FOCUS

@dataclass(frozen=True, slots=True)
class CapabilityArgumentSpec:
    name: str
    type_name: str        # one of a small fixed set for V1: "str" | "int" | "bool"
    required: bool

@dataclass(frozen=True, slots=True)
class CapabilityAdapter:
    capability_id: CapabilityId
    tool_name: str                          # the real, registered ToolRegistry name
    description: str                        # user-facing only, never sent as an instruction
    arguments: tuple[CapabilityArgumentSpec, ...]
    build_tool_input: Callable[[dict[str, object]], dict[str, object]]  # deterministic, validated builder
    allowed_strategy: ExecutionStrategy
    max_execution_tier: SecurityTier         # highest tier this batch may execute for this capability
    verification_strategy_id: str | None     # None until Batch 3 defines a real one
    internal_only: bool                      # True: never reachable via CommandRouter, only via this catalog
```

A single, hand-maintained `CAPABILITY_CATALOG: dict[CapabilityId, CapabilityAdapter]` is the *only* source of truth for what the intelligence layer may select. `ToolRegistry.has_tool(adapter.tool_name)` is still checked at the moment of execution as a defensive final existence check (a catalog entry could in principle reference a tool later removed from the registry), but the catalog — not the full registry — governs selectability. **Not every registered tool is exposed to intelligence planning in V1.**

**B.9 — Batch 2 is narrowed to exactly one real GREEN capability.** Supersedes §9's "max plan steps: 5" for Batch 2 specifically (Batch 3 gets its own, separately justified limit in C.13).

`CAPABILITY_CATALOG` in Batch 2 contains exactly one entry: `PROJECT_STATE_SHOW`, `tool_name="project_state_show"`, `arguments=()` (it takes no input), `max_execution_tier=SecurityTier.GREEN`, `verification_strategy_id=None`. Batch 2 execution limits: **max plan steps = 1; max executable capabilities = 1; GREEN only; no multi-step execution; no YELLOW execution; no retry; no replan.** `project_state_show` is chosen because it requires zero arguments (no argument-validation complexity needed yet — deliberately deferred to Batch 3, where it's actually required), it is already fully tested and stable (Phase 89), and it directly supports the exact vertical slice already named in §14.

**B.10 — Strict structured-output parser.** AI prose never directly becomes executable input. Exact Batch 2 response schema:

```json
{"capability_id": "project_state_show", "arguments": {}}
```

Rules: exactly two top-level keys, both required — `capability_id` (string, must exactly match a `CapabilityId` value present in the *current batch's* `CAPABILITY_CATALOG`; any other value, including a real but non-catalogued tool name, is rejected) and `arguments` (a JSON object, possibly empty; every key must match a `CapabilityArgumentSpec.name` for the selected capability; unknown keys are rejected; missing required keys are rejected; a string argument longer than 500 characters is rejected, not truncated, since silently mutating AI-supplied input before validation is never acceptable). The parser may strip exactly one leading/trailing triple-backtick fence (with or without a `json` language tag) as its *only* pre-processing step, since models habitually wrap JSON in markdown fences — anything else non-conforming (extra prose, multiple fences, nested blocks) is rejected outright, never guessed at. Argument types are checked exactly against `type_name` with no coercion (a string `"5"` is never silently accepted for an `int`-typed argument). **Any failure at any stage of parsing/validation executes zero tools, creates zero approvals, and returns an honest, specific failure message — never a "best guess" repaired plan.**

**B.11 — Intent is advisory until deterministic validation succeeds; hint fields are removed, not just labeled non-authoritative.** Supersedes `StructuredPlanStep.risk_tier_hint`/`approval_required_hint` in §6 — on reflection, keeping fields that are simultaneously present and "non-authoritative" invites exactly the confusion this amendment exists to close, so they are **deleted**, not retained-but-caveated.

AI-derived `goal`/`constraints`/`ExecutionStrategyDecision`/`capability_id`/`arguments` remain advisory right up until B.10's parser and the catalog check both succeed. Only then does a real preflight run: look up the real tool via `ToolRegistry.get_tool(adapter.tool_name)`, build the real `ToolRequest` via `adapter.build_tool_input(validated_arguments)`, call the tool's own real `action_for(request)`, and classify via the real `SecurityManager.classify_action(...)`. `StructuredPlanStep` now stores the real, already-computed `SecurityDecision` (or its `.tier`) obtained from *this* preflight call — a real fact, not a guess needing a separate hint field. `ToolExecutor` still independently re-classifies at actual execution time, completely unchanged, exactly as it already does for every other tool call in the system; the preflight exists only for the intelligence layer's own internal gating decision (e.g. "is this GREEN enough to execute in Batch 2"), never as a substitute for `ToolExecutor`'s own authoritative, real-time classification.

### C. Corrected Batch 3 execution, approval, and verification

**C.12 — The `WorkflowEngine` contradiction, resolved by direct inspection, not assertion.**

Directly confirmed by reading `workflow/workflow_models.py` and `approval/approval_models.py` in full during this amendment:
- `WorkflowEngine.run()`/`resume()` return a `WorkflowResult(plan: Plan, workflow_id: str, step_outcomes: tuple[WorkflowStepOutcome, ...], session_id: int | None, message: str)`, with `.overall_status` and `.pending_approval_request` computed properties.
- Each `WorkflowStepOutcome(step: PlanStep, status: StepStatus, tool_result: ToolResult | None, approval_request: ApprovalRequest | None)` carries the **real, complete `ToolResult`** for every step actually attempted, including its `output` and `metadata` — this is already returned, already available, for free, after `run()`/`resume()` returns.
- `ApprovalRequest.metadata: dict[str, str]` is real, string-keyed/valued, and already durably persisted via `PendingApprovalStore`.
- `Plan`/`PlanStep` (including each step's own `tool_input`) are already durably persisted as JSON via `PausedWorkflowStore.plan_steps_json`, and already fully reconstructed by the existing, unchanged `reload_paused()`/`resume()` path after a restart.

**This resolves the contradiction: no new persistence and no `WorkflowEngine` change are needed at all.** The design is genuinely **Option A**, with one clarification of what "unchanged" means precisely:

- Verification is encoded as an explicit **second `PlanStep`** (a read-back capability, C.15). `workflow/engine.py` itself is not touched in any way.
- The "expected value" for verification is never separately persisted anywhere new — it is simply the write step's own real, already-durable `tool_input["value"]` (`WorkflowResult.step_outcomes[0].step.tool_input["value"]`), available identically whether the workflow ran synchronously or was reconstructed from `plan_steps_json` after a restart.
- No "intelligence-origin marker" or "verifier id" needs to be persisted anywhere either: Batch 3 supports **exactly one** plan shape (C.13), so after any `run()`/`resume()` call returns, my own orchestrator-level code recognizes that shape purely structurally — by checking whether `step_outcomes[0].step.tool_name` and `step_outcomes[-1].step.tool_name` match the two allowlisted Batch-3 capabilities' real tool names. No new field, anywhere, is required for this recognition.
- The one small, additive, new piece of logic lives entirely in `core/orchestrator.py` (already a file the original plan approved for Batch 3 changes): a new branch, appended at the end of the existing `execute_approved()` method, that — *after* the existing, completely unchanged resume logic produces its `WorkflowResult`/response — checks for the recognized plan shape and, only if matched, runs verification (C.15) and attaches `intelligence_trace`. Any resumed workflow that is *not* this shape (i.e., every one of the 5 existing fixed workflows) takes the exact same code path it does today, provably unchanged, since the new branch is purely additive and conditioned on a shape only Phase 90's own plans can ever produce.

**C.13 — Batch 3 is narrowed to exactly one YELLOW vertical slice, two executable steps, two allowlisted capabilities.** Supersedes §9's generic 5-step/5-tool ceiling for Batch 3 specifically.

`ask jarvis: update my project focus to X and confirm it` is the only supported Batch 3 request shape. `CAPABILITY_CATALOG` gains exactly two new entries: `PROJECT_STATE_UPDATE_FOCUS` (`tool_name="project_state_update"`, `arguments=(CapabilityArgumentSpec("value", "str", required=True),)`, `build_tool_input` fixes `field="focus"` and passes the validated `value` through, `max_execution_tier=SecurityTier.YELLOW`, `internal_only=False`) and `PROJECT_STATE_VERIFY_FOCUS` (`tool_name="project_state_verify"`, a new internal-only tool, see C.15, `arguments=()`, `max_execution_tier=SecurityTier.GREEN`, `internal_only=True`). **Maximum executable plan steps: 2. No other capability is allowlisted. No arbitrary YELLOW tool and no generic multi-step plan is enabled in this phase.**

**C.14 — V1 recovery limits are 0, not "1 as an optional enhancement."** Supersedes §9's "max retries per step: 0 default, optional 1" and §6's `RetryReplanDecision`/`ContinuationDecision.RETRY_STEP`/`REPLAN`.

`max retries per step = 0`; `max total retries = 0`; `max replans = 0`, unconditionally, for all of Batch 2 and Batch 3 — the "optional single-retry enhancement" named in the original §9/§19 is **removed as a V1 possibility entirely**, not merely deprioritized. On any execution or verification failure: stop; report the exact distinction between execution failure and verification failure (§C.16); never rerun a write step; never silently construct a replacement plan. `RetryReplanDecision`/`ContinuationDecision.RETRY_STEP`/`ContinuationDecision.REPLAN` are **removed** from the contracts entirely, since they no longer describe any real V1 behavior — `ContinuationDecision` is reduced to exactly `{CONTINUE, STOP}`, and `RetryReplanDecision` is removed in favor of a plain `stopped: bool` / `reason: str` pair on `StepExecutionRecord` where needed. Future bounded retry/replanning remains a named, deferred future extension (§19), not a V1 contract.

**C.15 — Typed verification, never free-text/substring matching. A new, internal-only, structured-metadata verifier tool.** Supersedes §6's `success_condition: str` free-text field and §11's "output satisfies the step's own declared success_condition string" language for the Batch 3 write+verify slice specifically.

Direct inspection confirms `ProjectStateShowTool.run()` (Phase 89) returns only a human-readable text blob via `self.ok(...)` — `ToolResult.metadata` is empty. It provides no structured per-field values today, and per this amendment's explicit instruction, its human-readable output is **not** parsed for verification. Instead, Batch 3 adds one new, small, GREEN, **internal-only** tool:

```python
# tools/builtin/project_state_verify_tool.py
class ProjectStateVerifyTool(BaseTool):
    # name -> "project_state_verify"
    # action_for -> "show jarvis project state" (the same, already-GREEN action string
    #   ProjectStateShowTool itself uses - semantically the same read-only action,
    #   reused rather than duplicated, needing zero new SecurityManager rule)
    # run(request) -> ToolResult(
    #     success=True,
    #     output=<a short, human-readable status line, for audit-trail/log readability only>,
    #     metadata={
    #         "branch": <real value or "">, "phase": <real value or "">,
    #         "commit": <real value or "">, "suite_result": <real value or "">,
    #         "focus": <real value or "">, "last_updated": <real value or "not recorded yet">,
    #     },
    # )
```

It takes the exact same `ProjectStateStore` dependency `ProjectStateShowTool` already takes (read-only, `.get()` only — no new store, no new dependency wiring beyond reusing the existing instance), is registered in `ToolRegistry` under the new name `"project_state_verify"` so it produces a **real, audited plan step** through the unmodified `WorkflowEngine`/`ToolExecutor` path, and is marked `internal_only=True` in `CAPABILITY_CATALOG` — it is never given a `CommandRouter` grammar entry, so it is not reachable as a user-typed command, only ever selectable as the fixed second step of the one Batch 3 plan shape. `tools/builtin/project_state_show_tool.py` itself is **not modified** — Phase 89's already-shipped, already-tested tool stays exactly as it is.

Verification comparison, computed after `run()`/`resume()` returns a `WorkflowResult`: `expected = step_outcomes[0].step.tool_input["value"]` (the real, already-durable submitted value) compared for **exact string equality** against `actual = step_outcomes[-1].tool_result.metadata.get("focus")` (the real, freshly-read, structured value) — never a substring or fuzzy match.

**C.16 — `VerificationResult` uses a typed outcome, not `verified: bool`.** Supersedes `VerificationResult` in §6.

```python
class VerificationOutcome(Enum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"       # the verify step itself did not execute/succeed
    NOT_REQUIRED = "not_required"     # e.g. Batch 2's GREEN-only 1-step plans, which have nothing to verify

@dataclass(frozen=True, slots=True)
class VerificationResult:
    outcome: VerificationOutcome
    verifier_id: str      # fixed for V1: "project_state_focus_exact_match" (the only verifier this phase defines)
    evidence: str          # short, real, already-non-secret value only (e.g. the real focus string) - never fabricated
    detail: str | None
```

`UNAVAILABLE` is distinct from `FAILED`: `FAILED` means the verify step ran and the values genuinely differ; `UNAVAILABLE` means the verify step itself could not produce a real answer (e.g. `tool_result.success is False`). Execution failure (`ToolResult.success is False` on the *write* step) is reported as its own distinct outcome, never conflated with either verification state.

**C.17 — Approval/restart persistence, proven from real fields, not asserted.** Directly enabled by C.12's findings: the plan **can** pause for YELLOW approval (via the existing, unchanged `ApprovalManager.create_request()` call `WorkflowEngine` already makes), survive a restart (via the existing, unchanged `PausedWorkflowStore`/`reload_paused()` chain, since `Plan`/`PlanStep` — including the write step's own `tool_input["value"]` — round-trip through `plan_steps_json` unchanged), resume (via the existing, unchanged `WorkflowEngine.resume()`), run its verification step as the plan's own second step, and return an honest result. **No new durable field is required anywhere**: the expected value lives in the already-durable `PlanStep.tool_input`; the "which verifier/is this an intelligence plan" question is answered by structural plan-shape recognition (C.12), never a stored marker; the `workflow_id` `WorkflowEngine` already generates serves as the natural trace-correlation id. Nothing depends on the transient `StructuredPlan` object or the in-memory `JarvisResponse` surviving a restart — both are freely reconstructible (or simply absent, and replaced by direct inspection of the real `WorkflowResult`) after one.

**C.18 — RED handling.** `CAPABILITY_CATALOG` never contains a RED-tier entry in any batch. B.11's preflight rejects any capability whose real, live `SecurityDecision.tier` is RED *before* a plan is ever handed to `WorkflowEngine`. `ToolExecutor`'s own existing, unmodified RED-first check remains the second, authoritative line of defense regardless. A forced-plan regression test (constructing a real `Plan` that references a RED-classified action directly, bypassing the intelligence layer's own preflight) proves `ToolExecutor` still blocks it and `tool.run()` is never reached — mirroring this project's existing `_RedTool` tripwire test pattern.

### D. Trace and privacy policy

**D.19 — Exact `intelligence_trace` contents.** Supersedes the bare `intelligence_trace: tuple[str, ...]` mention in §6 with concrete bounds.

Never included: raw `ToolRequest`/`tool_input` dictionaries; full file contents; memory contents beyond what the ordinary response already shows the user; API keys or secret-like values; unbounded user-supplied text. Limits: at most one trace entry per executed plan step (≤1 for Batch 2, ≤2 for Batch 3 — already small by construction); at most 200 characters per entry. Allowed content per entry: step number, the capability's `tool_name` (already non-secret), approval state, and — for a verification entry — only the `VerificationOutcome` enum value (e.g. `"confirmed"`/`"could not confirm"`), never `VerificationResult.evidence`'s full string unless that exact value is already independently visible in the ordinary response text. `StepExecutionRecord` may transiently hold validated arguments in memory for the duration of one request (needed to construct the real `ToolRequest`), but raw arguments are never copied into `JarvisResponse.intelligence_trace` and never logged verbatim.

### E. Revised hard limits (supersedes §9 for Batches 2 and 3)

| | Batch 1 | Batch 2 | Batch 3 |
|---|---|---|---|
| Tool execution | none | 1 step, 1 allowlisted GREEN capability | exactly 2 steps: 1 allowlisted YELLOW + 1 allowlisted GREEN verifier |
| Retries per step / total | n/a | 0 / 0 | 0 / 0 |
| Replans | n/a | 0 | 0 |
| Approval | n/a | n/a (GREEN only) | reuses `ApprovalManager` unchanged |

Any generic five-step, multi-capability architecture remains a named, deferred future extension after Phase 90 V1 is proven — not part of this phase.

### F. Continuation Kit finalization honesty (supersedes §17's finalization description)

The kit cannot truthfully contain its own final commit hash before it is committed. Exact sequence: (1) once Batch 3's implementation is complete and its full validation suite is green, record that commit hash and suite result, explicitly labeled the **implementation baseline**; (2) write `docs/JARVIS_CONTINUATION_KIT.md` referencing that already-real baseline; (3) commit the kit and the final `docs/phase_90_completion_report.md` as a separate, later, docs-only commit, which necessarily produces a different, later hash; (4) the closure report states both hashes distinctly — "implementation baseline: `<hash-B>`" and "documentation commit: `<hash-C>`" — and never implies either one is the other. This mirrors exactly the relationship already visible in this very document today (planning commit `bc2bbaa` describing the separate, earlier implementation baseline `04a0f84`).

### G. Revised batch file lists (supersedes §20 for the items below; everything in §20 not restated here is unchanged)

**Batch 1** — new: `intelligence/__init__.py`, `intelligence/context.py` (per §A). Modified: `core/command_router.py`, `core/orchestrator.py`, `main.py`, `tools/builtin/help_tool.py`, `docs/user_guide.md`. Tests: `tests/unit/test_context_assembly.py`, `tests/unit/test_context_query_routing.py`, `tests/unit/test_orchestrator_context_query.py`, plus updates to `tests/unit/test_help_tool.py` and `tests/unit/test_help_output_routing_consistency.py`.

**Batch 2** — new: `intelligence/intent.py`, `intelligence/planning.py`, `intelligence/capability_catalog.py`, `intelligence/structured_output.py` (per §B). Modified: `core/command_router.py`, `core/orchestrator.py`, `main.py`; HelpTool/`docs/user_guide.md` only if a genuinely new user-facing phrase is introduced (to be determined at implementation time). Tests: capability-catalog unit tests, structured-output parser tests (malformed JSON, unknown capability, unknown/extra argument, wrong type, fence-stripping), preflight/`SecurityManager` integration tests, orchestrator/CommandRouter tests.

**Batch 3** — new: `intelligence/verification.py`, `intelligence/execution.py` (per §C), `tools/builtin/project_state_verify_tool.py` (per C.15), `docs/JARVIS_CONTINUATION_KIT.md`, `docs/phase_90_completion_report.md`. Modified: `core/request_models.py` (one new optional `intelligence_trace` field), `core/orchestrator.py` (additive branch in `execute_approved()`, per C.12), `main.py` (wiring the new internal tool + capability catalog). **Never modified** (reaffirmed): `workflow/engine.py`, `workflow/paused_workflow_store.py`, `approval/*.py`, `tools/builtin/project_state_show_tool.py`, `tools/builtin/project_state_update_tool.py`, `security/security_manager.py`.

### Revised end-to-end acceptance scenarios (supersedes §16's list)

Natural request with lexical + recency context selection; context provenance/`context_id` presence; context budget exhaustion (whole-item omission vs. per-item truncation); ProjectState stale/manual labeling and `[FILL IN]`/`"not recorded yet"` honesty; malformed AI JSON; unknown capability id; unknown/extra argument; invalid argument type; a real tool that exists in `ToolRegistry` but is not in `CAPABILITY_CATALOG`; GREEN preflight + real execution (Batch 2 slice); YELLOW no-approval store-unchanged proof; approval → restart → resume → verification (full C.17 chain); declined/expired approval stops cleanly; exact-value verification mismatch (`FAILED`); verify-step-itself-fails (`UNAVAILABLE`); RED forced-plan refusal; provider unavailable/failure honesty; deterministic-command backward compatibility; zero-retry/zero-replan proof; `intelligence_trace` redaction and bounds.

## 25. Batch 2 Contract Gate — Explicit Tool Intent and Exact Planning Contracts

**Sections 1–24 above are preserved unchanged.** This section clarifies Batch 2 only and **supersedes** any conflicting Batch 2 wording in Sections 1–24 (in particular, wherever earlier sections left the Batch 2 trigger phrase implicit or assumed it reused the bare `"ask jarvis:"` prefix). Its purpose is to remove any ambiguity between Batch 1's already-shipped, unchanged advisory `ask jarvis:` behavior and Batch 2's real tool-selection behavior.

### A. Exact user-facing routing boundary

Two separate, distinctly-triggered commands exist side by side:

1. **`ask jarvis: <request>`** (Batch 1, already shipped, commit `8462446`) — context-aware advisory answer only. No tool selection, no tool execution, no approval. Behavior is exactly as implemented in Batch 1 and is **not modified in any way by Batch 2**.
2. **`ask jarvis to: <request>`** (new, Batch 2) — a natural-language tool-intent request: structured AI capability selection, deterministic validation, at most one allowlisted GREEN capability (per §B.9, unchanged), and real execution through the existing, unmodified `ToolExecutor`.

Exact grammar requirements for the new command:
- The colon after `to` is mandatory: `"ask jarvis to"` (no colon) does not match.
- Matching is case-insensitive, mirroring `match_ask_jarvis`'s own `casefold()` convention exactly.
- An empty or whitespace-only trailing request (`"ask jarvis to:"` with nothing meaningful after the colon) returns an honest, fixed error message and performs **no** AI call and **no** tool execution of any kind - mirroring Batch 1's own empty-request handling exactly.
- Near misses must not match: `"ask jarvis to"` (no colon), `"ask jarvis"` (unrelated to this new command), `"jarvis, ask to: X"`, and `"ask jarvis: to X"` (a legitimate Batch 1 request whose own text happens to start with the word "to") must all fail to match the new command's grammar.

**Collision proof.** `"ask jarvis to:"` is never a prefix of `"ask jarvis:"`, and `"ask jarvis:"` is never a prefix of `"ask jarvis to:"`, in either direction: comparing character-by-character after the shared `"ask jarvis"` stem, the very next character diverges immediately (`:` for the Batch 1 phrase vs. a space beginning `" to:"` for the Batch 2 phrase) - confirmed by direct string comparison, not assumed. This means dispatch order between the two matchers is **not** a correctness requirement on its own (neither can ever swallow the other), unlike the genuine Batch 1 §A.7 collision risk which required a real, resolved check against every *other* existing table. That existing check is re-confirmed here for the new phrase specifically: no exact/prefix table anywhere in `core/command_router.py` contains the word `"ask"` other than the Batch 1 `_ASK_JARVIS_PREFIX` entry itself (re-grepped as part of this amendment), so the new phrase cannot collide with any command family other than its own Batch 1 sibling, which is already proven non-colliding above.

**Exact dispatch-chain position.** The new matcher (`CommandRouter.match_ask_jarvis_to`, or equivalently-named) is checked in `JarvisOrchestrator.handle_request()` immediately **before** the existing `match_ask_jarvis` check, in the same final special-handler cluster, still immediately before the generic `_handle_request_core` fallback. Because the two phrases are proven non-colliding above, this ordering choice is a matter of narrative grouping (newer command checked first, alongside its sibling) rather than a correctness necessity - but it is fixed here, explicitly, so Batch 2 implementation does not need to re-derive or guess it.

**Backward compatibility.** Every existing deterministic command, every existing special matcher (including Batch 1's own `ask jarvis:`), and the generic fallback retain their current dispatch order and behavior, completely unchanged - the new matcher is purely additive, exactly mirroring how Batch 1's own matcher was added relative to the commands that already existed before it.

**Documentation.** `tools/builtin/help_tool.py` and `docs/user_guide.md` are updated **in Batch 2 itself**, not deferred - this is a new user-facing command, following the same same-batch documentation discipline Batch 1 (and Phases 86/87/89 before it) already established.

### B. Exact Batch 2 structured AI output

The structured model output schema is **exactly** the one already fixed in §B.10 (unchanged by this section) - restated here only to make explicit that it now governs responses to the new `ask jarvis to:` command, not `ask jarvis:`:

```json
{
  "capability_id": "project_state_show",
  "arguments": {}
}
```

Exactly two top-level keys - `capability_id` and `arguments` - both required. No other keys are accepted.

**The parser must reject:**
- malformed JSON;
- empty output;
- leading or trailing prose;
- multiple JSON objects;
- nested Markdown blocks;
- more than one outer code fence;
- unknown top-level keys;
- missing keys;
- unknown capability IDs;
- capability IDs not present in `CAPABILITY_CATALOG`;
- unknown argument names;
- missing required arguments;
- invalid argument types;
- oversized string arguments;
- duplicate JSON keys at any object level.

**Duplicate keys must never be silently overwritten by the JSON decoder.** Python's `json.loads()` silently keeps only the *last* occurrence of a repeated key by default - exactly the silent-overwrite behavior this contract forbids. The parser therefore never calls plain `json.loads(text)`; it calls `json.loads(text, object_pairs_hook=_reject_duplicate_keys)`, where `_reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]` raises a parse-rejection error the first time it observes a key already present in the dict it is building, and otherwise returns the built dict unchanged. Because `object_pairs_hook` is invoked by the decoder for **every** JSON object encountered - top-level and nested alike - this single hook rejects a duplicate key at any nesting depth, not only at the top level, with no separate recursive check needed.

**Exactly one optional outer triple-backtick fence** may be stripped, and only that: with no language tag, or with the `json` language tag, appearing as the first and last non-whitespace content of the raw text. Nothing else may be repaired, guessed, coerced, extracted, or normalized into an executable request - no extraction of "the first JSON-looking substring," no stripping of explanatory prose around the object, no coercion of a stringified number into an int, no truncation of an oversized string argument to make it fit.

**Any parsing or validation failure** (any single item in the reject-list above) must: execute zero tools; create zero approvals; mutate zero stores; return an honest, bounded error naming *which* rule failed (e.g. "unknown capability", "duplicate key", "argument too long") without echoing raw, potentially-adversarial model output back verbatim; never fall back to a guessed capability; and never silently reroute into Batch 1's `ask jarvis:` advisory answering - a failed `ask jarvis to:` request stays a failed `ask jarvis to:` request, it never quietly becomes a different command's behavior.

### C. Exact capability catalog for Batch 2

`CAPABILITY_CATALOG` contains **exactly one entry**:

| Field | Value |
|---|---|
| `capability_id` | `CapabilityId.PROJECT_STATE_SHOW` |
| `tool_name` | `"project_state_show"` (the real, already-registered `ToolRegistry` name) |
| `arguments` | `()` - none accepted |
| `allowed_strategy` | `ExecutionStrategy.SINGLE_TOOL` |
| `max_execution_tier` | `SecurityTier.GREEN` |
| `verification_strategy_id` | `None` |
| `internal_only` | `False` - the real tool is already reachable directly via `"show jarvis project state"` (Phase 89); intelligence-layer *selection* of it is possible only through this one catalog entry, never through any other path |

`ToolRegistry` is explicitly **not** the intelligence allowlist - it is only Phase 1's general tool-execution registry, already used for many tools Batch 2 must never expose to AI selection. Execution requires **both**, checked independently: (1) the capability exists in `CAPABILITY_CATALOG`, and (2) its mapped real tool name still exists in `ToolRegistry` (`ToolRegistry.has_tool(adapter.tool_name)`, per §B.8, unchanged). A real, registered tool that is absent from `CAPABILITY_CATALOG` (every tool other than `project_state_show` in Batch 2) must be rejected the moment a structured response names it, before any further processing - the catalog check happens first, since a tool that fails the catalog check has no adapter to even look up in the registry.

### D. Exact revised Batch 2 contracts

Decorative or currently-unconsumed contracts from §6 are removed. The final Batch 2 shape, exactly:

```python
class CapabilityId(Enum):
    PROJECT_STATE_SHOW = "project_state_show"


@dataclass(frozen=True, slots=True)
class CapabilityArgumentSpec:
    name: str
    type_name: str
    required: bool


class ExecutionStrategy(Enum):
    SINGLE_TOOL = "single_tool"


@dataclass(frozen=True, slots=True)
class CapabilityAdapter:
    capability_id: CapabilityId
    tool_name: str
    description: str
    arguments: tuple[CapabilityArgumentSpec, ...]
    allowed_strategy: ExecutionStrategy
    max_execution_tier: SecurityTier
    verification_strategy_id: str | None
    internal_only: bool


@dataclass(frozen=True, slots=True)
class ExecutionStrategyDecision:
    strategy: ExecutionStrategy
    reason: str


@dataclass(frozen=True, slots=True)
class StructuredPlanStep:
    step_number: int
    description: str
    capability_id: CapabilityId
    tool_name: str
    arguments: dict[str, object]
    security_tier: SecurityTier


@dataclass(frozen=True, slots=True)
class StructuredPlan:
    goal: str
    context_ids_supplied: tuple[str, ...]
    steps: tuple[StructuredPlanStep, ...]
```

`context_ids_supplied` means only, and exactly, that those `ContextItem.context_id` values were included in the context supplied to the reasoning prompt for this request - it is never described as "used by," "consulted by," or otherwise implying the AI's reasoning process actually drew on any particular item; the AI's own internal reasoning is opaque and unverifiable, so this field records only a plain fact about what was supplied, not a causal claim about what was read. `goal` may remain the verbatim natural request text for V1 - no AI-derived paraphrase or extracted constraint list is invented, since the strict schema in §B (above) never asks the model to return one.

**Removed entirely, not merely deprioritized** (superseding any earlier §6 mention): `risk_tier_hint`, `approval_required_hint` (already removed by §B.11), free-text `success_condition`, `max_retries`, `max_replans`, any retry contract, and any verification contract - none of these describe real Batch 2 behavior; verification remains exclusively a Batch 3 concept (§C.15-C.17), and Batch 2's own recovery policy is the unconditional zero/zero already fixed by §C.14 for Batch 3, applied identically here (Batch 2 has exactly one step, so "zero retries, zero replans" means simply: on any failure, stop and report - there is nothing to retry or replan into in the first place).

**`InterpretedIntent` has no real Batch 2 consumer.** The minimal contract set above - `StructuredPlan`/`StructuredPlanStep` built directly from the parsed, validated `{capability_id, arguments}` response - requires no separate intermediate "interpreted intent" object; `goal` is carried directly on `StructuredPlan` itself. Introducing `InterpretedIntent` now, with no code path that reads it, would be exactly the "decorative type" this amendment exists to prevent. **`intelligence/intent.py` is therefore deferred, not created in Batch 2** - a future batch may introduce it if a genuine multi-step or multi-turn intent-tracking consumer emerges, but that consumer does not exist today.

### E. Context provenance in the planning prompt

Direct inspection of Batch 1's real, shipped `build_ai_context_block()` (`intelligence/context.py`, commit `8462446`): each supplied item is rendered into the combined text as `f"\n----- {item.context_id} -----\n{item.text}"` - so **`context_id` is already present**, verbatim, as every item's own delimiter label. `source` is not rendered as a separately-labeled field in that text, but it does not need to be: `source` is already encoded inside `context_id` itself by construction (`"memory:<id>"` vs. `"project_state:current"`, per §A.1), so nothing about `source` is lost. Bounded text: yes, unchanged, per the existing §A.5 budgets. Clear untrusted framing: yes - `PromptBuilder.build()` wraps the whole combined block in its existing `_UNTRUSTED_CONTEXT_HEADER`/`_UNTRUSTED_CONTEXT_FOOTER` markers before it ever reaches the model, exactly as it already does for Batch 1's `ask jarvis:` requests; this framing happens at the `PromptBuilder` layer, not inside `build_ai_context_block()` itself, and Batch 2 does not change that division of responsibility.

**Conclusion: no change to `intelligence/context.py` is required for Batch 2.** The planner never needs to parse `context_id`s back out of the combined prompt text (which would be a fragile, unnecessary round-trip through untrusted-adjacent formatting) - it already has direct, structural access to the real `AssembledContext` object `ContextAssembler.assemble()` returned for this request, and populates `StructuredPlan.context_ids_supplied` as `tuple(item.context_id for item in assembled_context.items)` directly from that object's own `.items`, independent of anything the AI returns. This is deterministic, requires no new parsing, and cannot be spoofed by adversarial model output, since the AI's response never influences this field at all.

This conclusion leaves every one of the following genuinely untouched, as required: Batch 1's context budgets (§A.5), the deterministic memory-selection algorithm (§A.4), source selection (§A.3), trust classification (§A.1/§A.3 - every item remains `ContentTrust.UNTRUSTED`), and `ask jarvis:` advisory behavior (unmodified, per §A above).

### F. Deterministic security preflight

After strict parsing (§B) and catalog validation (§C) both succeed, in exact order:

1. Resolve the `CapabilityAdapter` for the validated `capability_id` from `CAPABILITY_CATALOG`.
2. Verify its `tool_name` still exists in `ToolRegistry` (`has_tool()`) - a defensive check for a catalog entry whose real tool was since removed.
3. Build the real tool input only through the adapter's own deterministic builder (never by hand-assembling a dict from the raw model output).
4. Retrieve the real tool instance via `ToolRegistry.get_tool(adapter.tool_name)`.
5. Construct the real request shape (`ToolRequest`) that tool's own `action_for()` expects.
6. Call that real tool's own `action_for(request)` - never a guessed or hard-coded action string.
7. Classify the returned action string through the real, unmodified `SecurityManager.classify_action()`.
8. Require the actual resulting tier to be `SecurityTier.GREEN`.
9. If the actual tier is `YELLOW` or `RED`, reject immediately: zero execution, zero approval creation - Batch 2 has no approval flow of any kind, so a `YELLOW` result is not paused for confirmation, it is simply refused.
10. Store the real, already-computed `SecurityTier` on `StructuredPlanStep.security_tier` - a recorded fact from step 7, never a separate guess or hint field (§B.11's own reasoning, applied identically here).
11. Only then call `ToolExecutor.execute(...)`, which independently re-classifies the same action from scratch, exactly as it already does for every other tool call in the system.

This preflight is **advisory to the intelligence layer's own gating decision only** - it is never authoritative over, and can never replace, `ToolExecutor`'s own real-time classification. `tool.run()` is never called directly by any Batch 2 code; the only execution path is through the real, unmodified `ToolExecutor`.

### G. Execution and grounded response

Batch 2 permits, unconditionally: exactly one plan step; exactly one capability (`PROJECT_STATE_SHOW`, per §C); GREEN only; zero retries; zero replans; no `WorkflowEngine` involvement of any kind (a single-step GREEN execution needs no multi-step engine); no approval creation; no verification requirement (`verification_strategy_id` is `None` for this one capability, per §C).

After `ToolExecutor.execute(...)` returns a real `ToolResult`: on success, the response is **grounded in that real `ToolResult.output`** - the AI is never asked to invent, paraphrase, or re-summarize what the tool actually returned; the response may wrap `ToolResult.output` with a short, fixed disclosure sentence (mirroring Batch 1's own fixed-label convention, e.g. `_ASK_JARVIS_LABEL`), but the substantive content is the tool's own real output, verbatim, never an AI re-telling of it. On failure, the response reports the real `ToolResult`'s own failure honestly (its `.error`, or a generic message if none), never claiming a tool ran when `ToolExecutor` never returned success, and never claiming execution happened at all when parsing/validation/preflight rejected the request before `ToolExecutor` was ever called.

`intelligence_trace` remains deferred to Batch 3 (per §C.12/§D.19) - Batch 2 does not modify `JarvisResponse` to add this field, and does not populate any equivalent of it anywhere.

### H. Provider and parser failure behavior

**AI disabled, unavailable, or failing:** execute zero tools; create zero approvals; mutate zero stores; return an honest "unavailable"/"failed" message - mirroring Batch 1's own `_ASK_JARVIS_AI_REASONING_NOT_ENABLED_MESSAGE`/`_ASK_JARVIS_AI_REASONING_UNAVAILABLE_MESSAGE` pattern, with new, distinct wording for the `ask jarvis to:` command specifically (never reusing Batch 1's exact strings, since these are a different command with a different failure surface).

**Malformed or invalid structured output** (any §B reject-list item): execute zero tools; create zero approvals; mutate zero stores; return a specific, bounded validation-failure message naming which check failed.

**`ask jarvis to:` never falls back to:** guessed tool execution (no "best effort" interpretation of a malformed response); Batch 1's advisory `ask jarvis:` output (a failed tool-intent request is never silently answered as if it had been an advisory question instead); or the generic unmatched-command fallback message after an AI attempt was already made (once `ask jarvis to:` matches, the request is committed to this workflow's own honest success/failure reporting - it never reverts to looking like an unrecognized command after the fact).

### I. Exact Batch 2 files

**New:** `intelligence/capability_catalog.py` (§C/§D), `intelligence/structured_output.py` (§B), `intelligence/planning.py` (§D/§E/§F/§G orchestration of the above into a `StructuredPlan` and its execution).

**Not created in Batch 2:** `intelligence/intent.py` / `InterpretedIntent` - deferred per §D, no real consumer exists yet.

**Modified:** `core/command_router.py` (new `match_ask_jarvis_to`, per §A); `core/orchestrator.py` (new dispatch branch and handler, per §A/§F/§G/§H); `main.py` (wiring the capability catalog/structured-output parser/planner into the orchestrator, mirroring how `ContextAssembler` was wired in Batch 1); `tools/builtin/help_tool.py` and `docs/user_guide.md` (new command documentation, per §A); relevant tests (per §J).

**Not modified:** `intelligence/context.py` (per §E's conclusion - no change required); `workflow/engine.py`; `tools/executor.py` (`ToolExecutor`'s own implementation); `security/security_manager.py`; `approval/approval_manager.py`; `planner/plan_models.py`; Batch 1's context budgets/retrieval algorithm (§A.4/§A.5, both unchanged); any dashboard code.

### J. Required Batch 2 acceptance tests

**Routing:** exact `ask jarvis to:` match; case-insensitive match; empty request; near misses; `ask jarvis:` remains advisory and unchanged; existing deterministic commands unchanged; unmatched-request fallback unchanged.

**Parser:** valid bare JSON; valid single-fenced JSON; malformed JSON; extra leading/trailing prose; unknown top-level key; missing required key; duplicate top-level key; duplicate nested key; unknown capability id; extra/unrecognized argument; wrong argument type; oversized string argument; multiple code fences; multiple JSON objects; zero coercion of any kind (proving, e.g., a numeric-looking string argument is rejected, not silently cast).

**Catalog:** only `PROJECT_STATE_SHOW` is selectable; a real, `ToolRegistry`-registered-but-not-catalogued tool is rejected when named; a catalogued-but-since-unregistered tool is rejected; exact zero-argument validation for `project_state_show`.

**Security:** a real GREEN preflight succeeds; a forced-YELLOW preflight (a test double capability/tool pinned to YELLOW) is rejected with zero execution/approval; a forced-RED preflight is rejected identically; `ToolExecutor` is proven to still independently classify (e.g. via a regression-style forced-plan test mirroring §C.18's own `_RedTool` tripwire precedent); no code path calls `tool.run()` directly.

**Execution:** a real `project_state_show` execution through the real, unmodified `ToolExecutor`; the response is proven grounded in the real `ToolResult.output` (not an AI paraphrase); `ToolResult` failure is reported honestly; AI provider unavailable; AI provider failure; malformed model output; zero approvals created in any scenario; zero store mutation in any scenario; at most one execution ever occurs per request; zero retries; zero replans.

**Context:** `context_ids_supplied` on the real `StructuredPlan` contains exactly the real `context_id`s from the real `AssembledContext` used for that request; no id is fabricated or derived from item content; every supplied context item remains `ContentTrust.UNTRUSTED` throughout (unchanged from Batch 1).

**Help and documentation:** both commands are documented distinctly - `ask jarvis:` as advisory-only/no-tools, `ask jarvis to:` as selecting at most one allowlisted GREEN tool - with no wording that could cause either to be mistaken for the other's behavior.

### K. Batch 2 stop gate

This turn remains planning clarification only - Sections 1-24 are unchanged, Section 25 (A through K) supersedes any conflicting Batch 2 wording in earlier sections, and Batch 2 implementation does not begin until Nathan explicitly approves it after reviewing this completed section.

## 26. Batch 2 Final Safety Gate — Unsupported Requests and Execution-Time Divergence

**Sections 1–25 above are preserved unchanged.** This section **supersedes only** the conflicting structured-output rules in §25.B and any Batch 2 contract that assumed every valid request must select a tool.

### A. Required unsupported-request outcome

§25.B's schema had no valid way for the model to say the single allowlisted capability cannot satisfy the user's request - every schema-valid response would otherwise have to select `project_state_show`, even for a wholly unrelated request. That is unsafe and dishonest, and is corrected here.

**The Batch 2 model-output schema is replaced with exactly one of these two objects** (superseding §25.B's schema, which carried no `decision` key):

Execute outcome:
```json
{
  "decision": "execute",
  "capability_id": "project_state_show",
  "arguments": {}
}
```

Unsupported outcome:
```json
{
  "decision": "unsupported",
  "capability_id": null,
  "arguments": {}
}
```

Exactly three top-level keys are required - `decision`, `capability_id`, `arguments` - no others are accepted. Allowed `decision` values are exactly `"execute"` and `"unsupported"`.

**Cross-field rules.** For `decision == "execute"`: `capability_id` must be a string; it must equal a real `CapabilityId` value; it must be present in `CAPABILITY_CATALOG`; in Batch 2 the only accepted value is `"project_state_show"`; `arguments` must pass the selected adapter's exact argument validation (§25.C).

For `decision == "unsupported"`: `capability_id` must be JSON `null`; `arguments` must be exactly an empty object; no plan is constructed; no security preflight runs; no tool executes; no approval is created; no store is mutated; the fixed response returned is exactly: `"Jarvis could not find an allowlisted capability that can safely complete that request."`

**Rejected** (all fall under §25.B's existing parser-failure contract, unchanged): unknown `decision` values; missing `decision`; `execute` with a null `capability_id`; `unsupported` with a non-null `capability_id`; `unsupported` with any non-empty `arguments`; any other inconsistent field combination.

**The unsupported outcome is a successful parse and a valid planning decision, not a parser failure.** It is represented and handled distinctly from every §25.B reject-list failure (§F below).

### B. Exact parsed-decision contract

One new parser-result contract, added only because Batch 2 implementation requires it to represent the two-outcome decision from §A:

```python
class ToolSelectionDecision(Enum):
    EXECUTE = "execute"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ParsedToolSelection:
    decision: ToolSelectionDecision
    capability_id: CapabilityId | None
    arguments: dict[str, object]
```

The parser returns a `ParsedToolSelection` only after every JSON, duplicate-key, key-set, type, cross-field, size (§D), catalog, and argument rule has passed. `arguments` is a dict newly built by the parser itself for this call - never a reference to a dict object supplied by, or shared with, any other layer (the decoder's own `object_pairs_hook`, per §25.B, already constructs a fresh dict per object; the parser must not hand that same dict reference onward without an explicit copy if it performs any further transformation on it).

`StructuredPlan` (§25.D) is constructed only for a `ParsedToolSelection` with `decision is ToolSelectionDecision.EXECUTE`. A `ToolSelectionDecision.UNSUPPORTED` decision creates no `StructuredPlan` of any kind. No free-text model-supplied "reason" field is added anywhere in Batch 2, and raw model output is never exposed to the user in any response, success or failure.

### C. Trusted planning instruction

The model must receive a fixed, Jarvis-authored planning instruction stating: exactly one capability is available; its id is `project_state_show`; it may be selected only when showing the current manually-recorded ProjectState record can satisfy the request; otherwise the model must return the exact `unsupported` schema from §A; output must be JSON only, with no Markdown beyond the one permitted outer fence, and no explanation or extra prose.

**Inspection finding**, performed directly against the real, current code before any implementation, per this section's own requirement:

- `AIReasoningRequest` (`ai/reasoning_models.py`) carries exactly `user_input`, `context_block`, `session_id` - **no field exists for a caller to supply or extend a system/trusted instruction.**
- `AIReasoningEngine.reason()` (`ai/reasoning_engine.py`) unconditionally passes one fixed, module-level constant, `_SYSTEM_INSTRUCTION`, as `system_instruction` on every call it makes, regardless of what `AIReasoningRequest` contains. This same fixed instruction is shared, today, by every existing AI-summary feature (file/memory/web-search/webpage summaries) and by Batch 1's own `ask jarvis:` handler. **There is no existing path through `AIReasoningRequest`/`AIReasoningEngine` for a caller to supply a different or additional trusted instruction for one specific call.**
- One layer down, `AIRouter.route(*, system_instruction: str, user_message: str, context: AIContextBlock | None, session_id: int | None)` (`ai/router.py`) **already accepts an arbitrary trusted instruction string as a plain parameter, per call** - this is the exact mechanism `AIReasoningEngine.reason()` itself uses internally to supply its own fixed instruction. `PromptBuilder.build(*, system_instruction: str, ...)` places whatever string it is given into the trusted "system" block of the resulting `AIRequest`, with no `ContentTrust` gating on `system_instruction` at all (the `ContentTrust`/`AIContextBlock`/`_TRUSTED_ORIGIN_KEY` sentinel machinery governs only the `context` parameter, never `system_instruction`).

**Conclusion: the existing, unmodified `AIRouter.route(system_instruction=...)` path already carries a fixed trusted planning instruction, without touching any trust-boundary enforcement code (`AIContextBlock`'s construction guards, `PromptBuilder`'s injection scanner, and its untrusted-context framing are all untouched).** This is not a blocking limitation - a real, already-existing, already-parameterized path exists - but it does mean Batch 2's capability-selection call is made by calling the same, already-constructed `AIRouter` instance's `route()` method **directly**, rather than through `AIReasoningEngine.reason()`, whose own hardcoded `_SYSTEM_INSTRUCTION` must not be altered, branched on, or parameterized for this one narrow purpose (doing so would be a shared, cross-feature change to a component every existing AI-summary workflow and Batch 1's `ask jarvis:` also depend on - exactly the kind of broader, undisclosed change this amendment exists to prevent). This narrowly supersedes any earlier wording in §20/§24/§25 that described Batch 2 as reusing "`AIReasoningEngine`" for its capability-selection call specifically: `AIRouter`, `PromptBuilder`, the provider boundary, response validation, and the disclosure convention are all still reused completely unchanged, exactly as already required - only the one hardcoded-instruction call site (`AIReasoningEngine.reason()` itself) is bypassed for this specific call, in favor of the lower-layer method that already supports it. `main.py`'s wiring passes the same, already-constructed `AIRouter` instance to the new planning module (never a second instance) alongside the existing `AIReasoningEngine` still used unchanged for Batch 1.

The capability instruction is supplied exclusively through this trusted `system_instruction` path. It is never mixed into retrieved memory text, the manually-maintained ProjectState text, or any other `ContextItem` - every `ContextItem` supplied to this call remains `ContentTrust.UNTRUSTED`, unchanged from Batch 1 (§25.E). No protected AI trust boundary is modified or weakened by this finding.

### D. Raw model-output size limit

Before fence removal or JSON parsing, model output exceeding 2,000 characters is rejected outright. The valid Batch 2 object is tiny (well under 100 characters in either shape from §A); unbounded output is unnecessary, and a fixed limit prevents excessive parser, log, or error-handling load from a misbehaving or adversarial response.

Boundary behavior: output of exactly 2,000 characters proceeds to normal validation; output of 2,001 characters or more is rejected before fence stripping or JSON parsing are ever attempted. On size rejection: execute zero tools; create zero approvals; mutate zero stores; never echo the raw output; return a fixed, bounded validation error. Whitespace surrounding otherwise-valid output may still be ignored exactly as §25.B already allows, but the 2,000-character check is applied to the raw, untrimmed string returned by the provider, before any trimming occurs.

### E. Execution-time classification divergence

`SecurityManager`'s preflight classification (§25.F) is advisory to the intelligence layer's own gating decision only, never authoritative over `ToolExecutor`, which independently classifies again at the moment of execution (§25.F.11, unchanged).

**Inspection finding**, performed directly against the real `ToolExecutor.execute()`/`ToolResult` contract (`tools/executor.py`, `tools/base_tool.py`) before any implementation, per this section's own requirement - `ToolResult` carries exactly `tool_name`, `success`, `output`, `error`, `requires_confirmation`, `blocked`, `metadata`; it carries **no** field naming the tier that was actually applied. Each divergence case is represented as follows, using only these real, existing fields:

| Case | Real representation |
|---|---|
| Confirmation is required (execution-time reclassifies GREEN → YELLOW) | `result.requires_confirmation is True`, `result.success is False`; `tool.run()` was never called |
| Execution was blocked (execution-time reclassifies GREEN → RED) | `result.blocked is True`, `result.success is False`; `tool.run()` was never called |
| The tool did not actually execute | Either of the two rows above, or (structurally near-impossible in Batch 2's single-process, synchronous request/response flow, but honestly represented if it ever occurred) the tool having been deregistered between preflight and execution, surfacing as `result.success is False` with an error naming the tool unregistered and both `requires_confirmation`/`blocked` False |
| Execution failed (the tool itself ran and failed, or raised) | `result.success is False`, `result.blocked is False`, `result.requires_confirmation is False`, `result.error` set to the tool's own honest failure message |

There is no `SecurityTier` returned on `ToolResult` to compare against the preflight's own recorded tier directly - divergence is detected structurally, from `requires_confirmation`/`blocked` alone, never invented as a new field that does not exist today.

**Batch 2's required handling**, for any of the first three rows above: do not create an approval request (Batch 2 has no approval flow at all, per §25.G); do not retry; do not replan; do not claim execution succeeded; return an honest refusal or failure message distinguishing "this needs confirmation" from "this was blocked" using the real fields above; leave every store unchanged except whatever audit event `ToolExecutor` itself already, unconditionally emits (unchanged, pre-existing behavior). For the fourth row (an ordinary tool-level failure), report the real failure honestly, per §25.G, unchanged.

**Batch 2 must never convert an unexpected YELLOW result into an approval flow.** Approval integration for this workflow shape belongs exclusively to a future batch, mirroring how Batch 3's own approval/verification machinery (§24.C) is scoped to the separate `ask jarvis: ... and confirm it` write-workflow, not this one.

### F. Grounded-response rule

For a `ParsedToolSelection` with `decision is ToolSelectionDecision.EXECUTE` that reaches real execution: the substantive successful response comes only from the real `ToolResult.output` - no second AI call ever summarizes, rewrites, reinterprets, or embellishes it; a short, fixed label may be prepended (mirroring Batch 1's own `_ASK_JARVIS_LABEL` convention); if `ToolResult` reports failure (§E, row 4), that real failure is reported honestly; execution is never claimed unless `ToolExecutor` itself returned `success is True`.

For a `ParsedToolSelection` with `decision is ToolSelectionDecision.UNSUPPORTED`: the fixed message from §A is used verbatim; no `StructuredPlan` is constructed; no security preflight runs; no `ToolExecutor` call is made; no approval is created; no store is mutated; there is no fallback to Batch 1's `ask jarvis:` advisory answering and no fall-through to the generic unmatched-command handler - an `unsupported` decision is its own complete, honest, terminal outcome.

For any parser (§25.B, §26.A/D), catalog (§25.C), registry, or preflight (§25.F, §26.E) failure: a distinct, bounded failure response is used - never presented as an `unsupported` decision unless the model's response was itself a genuinely valid, schema-conformant `unsupported` object (§A); raw model output or exception internals are never exposed in any response.

### G. Revised Batch 2 tests

The following are added to §25.J's acceptance-test matrix (all of §25.J's original items remain required, unchanged):

**Structured decision tests:** valid `execute` decision; valid `unsupported` decision; unknown `decision` value; missing `decision`; `execute` with null `capability_id`; `execute` with non-string `capability_id`; `unsupported` with non-null `capability_id`; `unsupported` with non-empty `arguments`; any other inconsistent field combination; `unsupported` produces no `StructuredPlan`; `execute` produces exactly one `StructuredPlanStep`; parsed `arguments` are copied into a newly-constructed dict, never a shared reference.

**Output-bound tests:** raw output of exactly 2,000 characters reaches normal parsing validation; raw output of 2,001+ characters is rejected before fence stripping; oversized output is never echoed in any error; oversized output executes zero tools and creates zero approvals.

**Unsupported-behavior tests:** an unrelated natural request, with a fake provider configured to return the valid `unsupported` schema, produces the fixed honest unsupported response; zero `StructuredPlan` construction; zero security preflight; zero tool execution; zero approvals; zero store mutation; no fallback to Batch 1 `ask jarvis:` behavior; no fallback to the generic unmatched-command response.

**Trusted-instruction tests:** the exact capability id `project_state_show` appears in the trusted planning instruction passed as `system_instruction`; the rule to return `unsupported` when the capability cannot satisfy the request appears in that same instruction; the JSON-only/no-prose rules appear in it; memory and ProjectState context remain framed as untrusted (unchanged from Batch 1); adversarial memory content cannot alter the schema or the capability catalog (a memory record containing a fake `capability_id`/schema override has no effect); model output cannot add a capability through context injection; no capability authority is ever sourced from an untrusted `ContextItem`.

**Execution-time-divergence tests:** preflight returns GREEN but the execution-time result requires confirmation (`requires_confirmation is True`) - no approval created, no success claimed, zero retry, zero replan, honest refusal returned; preflight GREEN but execution is blocked (`blocked is True`) - same guarantees; preflight GREEN but the tool itself reports failure (`success is False`, both flags False) - honest failure reported, no second AI call is made after execution in any of these three cases.

**Regression tests retained from §25:** duplicate top-level keys rejected; duplicate nested keys rejected; malformed JSON rejected; unknown capability rejected; a registered-but-not-allowlisted tool rejected; a catalogued-but-unregistered tool rejected; forced-YELLOW preflight rejected; forced-RED preflight rejected; real GREEN execution through the real `ToolExecutor`; `ask jarvis:` remains advisory and unchanged; existing deterministic commands remain unchanged; the unmatched-request fallback remains unchanged; no direct `tool.run()` call anywhere in Batch 2 code; zero retries; zero replans.

### H. Batch 2 implementation scope after this amendment

Once §26 is approved, Batch 2 remains strictly limited to: one explicit command, `ask jarvis to: <request>`; one allowlisted capability, `project_state_show`; one maximum executable step; GREEN only; a valid `unsupported` outcome (§A); strict JSON with the exact three-key decision schema; deterministic capability and argument validation; a real `SecurityManager` preflight; real `ToolExecutor` execution; zero approvals; zero retries; zero replans; no `WorkflowEngine`; no verification; no `intelligence_trace`; no automatic memory writes; no change to Batch 1's advisory `ask jarvis:` behavior; no expansion of the capability catalog beyond `project_state_show`.

Expected Batch 2 files remain those listed in §25.I, with one narrow, explicitly-justified addition proven necessary by §C's inspection: the new `intelligence/planning.py` module calls `AIRouter.route()` directly (the same, already-constructed instance `main.py` already builds for `AIReasoningEngine`, passed through unchanged) rather than routing this one call through `AIReasoningEngine`. This touches no file beyond what §25.I already listed as new/modified - `AIRouter`/`PromptBuilder`/`ai/reasoning_engine.py` themselves are not modified in any way - and is protected by the trusted-instruction regression tests in §G above.

### I. Planning-only stop gate

This turn is documentation only. Sections 1–25 are unchanged; §26 (A through I) supersedes only the conflicting Batch 2 wording named in its own preamble.

---

**This is a planning document only. No production code has been written. Batch 1 does not begin until Nathan explicitly approves it after reviewing this plan.**
