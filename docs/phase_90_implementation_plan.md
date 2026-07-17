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

**This is a planning document only. No production code has been written. Batch 1 does not begin until Nathan explicitly approves it after reviewing this plan.**
