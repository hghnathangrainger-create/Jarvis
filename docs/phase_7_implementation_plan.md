# Jarvis Phase 7 Implementation Plan

**Version:** Phase 7 — Core Simplification and AI Safety Hardening
**Builds on:** `5039011` (Phase 6 complete: Durable Approvals and Approval-Lifecycle Timeout Enforcement)
**Date:** 2026-07-06

---

## 1. Purpose

Phase 6 closed Jarvis's approval-lifecycle gap. This formal architecture checkpoint that followed it found two things worth fixing before Jarvis gains any more capability: `core/orchestrator.py` has accumulated a large, ordering-sensitive command-matching cascade that the Master Specification explicitly warns against ("the Core should never become a collection of business logic"), and the Master Specification's prompt-injection defence — the mechanism the specification calls the highest-consequence risk for an AI system — is only one-third built. Neither gap is visible to a user today. Both become expensive to retrofit the moment Jarvis gains its first tool that feeds external content (a file, a web page, a memory record) into an AI prompt.

Phase 7 closes both gaps now, while there is still nothing at stake: no tool in this codebase feeds external content into an AI prompt yet, and the command-matching logic, however large, is still small enough to move without a large-scale rewrite. This is a **safety and structure phase**, not a capability phase — Jarvis gains no new user-facing command, no new AI power, and no new execution authority anywhere in Phase 7.

---

## 2. Architectural Context

Two findings from reading the current code directly, not from the specification, drive this plan:

- **`_match_tool`** in `core/orchestrator.py` is an ordered cascade of ~150 lines and 15+ private helper methods matching request text to a registered tool and building its input. It works, and every routing test passes through it indirectly via `handle_request()`, but its size and ordering sensitivity is exactly the code smell the Master Specification's Ch. 5 warns against.
- **`AIReasoningEngine` does not go through `AIRouter` or `PromptBuilder`.** It imports `AIProvider`/`AIRequest`/`AIMessage` directly and builds its own request in `_build_prompt()`. Separately, **`main.py` never constructs an `AIReasoningEngine`, `AIRouter`, or `PromptBuilder` at all** — `AI_REASONING_ENABLED` is loaded into `Settings` but nothing outside `config/settings.py` ever reads it, and `JarvisOrchestrator(...)` in `main.py` never receives a `reasoning_engine=`. **AI reasoning is completely dead in the running application today.** It is exercised only by tests (`test_ai_core_safety.py`, `test_ai_reasoning_engine.py`), never by a real session.

This second finding matters directly: hardening a prompt-construction path that never runs in production protects nothing real. Phase 7 must both harden the AI-input path *and* make it genuinely reachable, or the hardening is theatre.

Also confirmed by direct inspection: `IntentType` and `ActionType` (`config/constants.py`) have **zero usages anywhere** outside their own definitions — pure forward-looking vocabulary for a Workflow Engine that does not exist. This shapes the naming decision in Batch 1 (§4.1) and the vocabulary-reuse decisions in Batch 4/5 (§8).

---

## 3. Phase Objective

**Close the current Core intent-routing architectural debt, and complete the Master Specification's prompt-injection defence, before Jarvis gains external-content ingestion or greater AI autonomy — without adding any new user-facing capability, without changing GREEN/YELLOW/RED policy, and without increasing what AI output is ever allowed to do.**

Five batches deliver this:

| Batch | Focus |
|---|---|
| 1 | Command Routing Extraction |
| 2 | Trusted vs Untrusted AI Context Model and AI Path Consolidation |
| 3 | Prompt Injection Pattern Detection |
| 4 | Unexpected AI Action Escalation |
| 5 | End-to-End Security Verification and Documentation |

---

## 4. Batch Definitions

### 4.1 Batch 1 — Command Routing Extraction

*(The checkpoint's proposed title, "Intent Classification Extraction," is deliberately not used — see naming rationale below.)*

**Purpose.** Remove the command-matching cascade from `JarvisOrchestrator` into its own component, with zero behavior change.

**Architectural problem being solved.** `core/orchestrator.py` currently holds both coordination logic (its proper role) and command-matching business logic (`_match_tool`, `_build_tool_input`, and every private helper they call). This is the concrete instance of the Master Specification's warning that the Core must never become "a collection of business logic."

**Naming decision.** The new component is named **`CommandRouter`**, not `IntentClassifier`. `_match_tool` does not produce an `IntentType` value (`CONVERSATIONAL`/`TASK_SINGLE`/`TASK_MULTI`/`MEMORY_QUERY`/`MEMORY_COMMAND`/`SYSTEM_COMMAND`) — that enum is unused, forward-looking vocabulary for a richer NLU-style classifier this component is not. `_match_tool` matches known phrasings to a registered tool name and extracts that tool's input. `CommandRouter` names exactly that, without borrowing a name already reserved in the specification's vocabulary for something else.

**Exact scope.** Move, verbatim, into a new `core/command_router.py`:
- `_match_tool` → `CommandRouter.match(text: str) -> str | None`
- `_build_tool_input` → `CommandRouter.build_input(tool_name: str, text: str) -> dict[str, object]`
- Every private helper each depends on: `_file_prefix`, `_extract_path`, `_extract_create_input`, `_extract_append_input`, `_strip_write_prefix`, `_split_on_keyword`, `_clean_path`, `_clean_content`, `_build_memory_input`, `_extract_after`, `_extract_between`, `_build_memory_update_input`, `_build_approval_history_input`, `_extract_memory_id`, `_extract_trailing_id`.
- All module-level keyword/prefix/alias constant tuples currently in `core/orchestrator.py` (`_ECHO_KEYWORDS`, `_INFO_KEYWORDS`, `_MEMORY_KEYWORDS`, `_FILE_LIST_PREFIXES`, `_FILE_READ_PREFIXES`, `_WORKFLOW_ALIASES`, `_APPROVAL_HISTORY_EXACT`, `_APPROVAL_DETAIL_PREFIXES`, `_FILE_CREATE_PREFIXES`, `_FILE_APPEND_PREFIXES`, `_SEARCH_KEYWORDS`).

**Explicit non-goals.** No new matching logic, no new commands or aliases, no change to any existing command's matched tool or extracted input, no `IntentType` usage, no change to `handle_request`'s public contract.

**Current files/components involved.** `core/orchestrator.py` (shrinks), `tools/registry.py` (read-only dependency via `has_tool`), `main.py` (constructs the new collaborator).

**Proposed new components.** `core/command_router.py` — a single `CommandRouter` class, constructed with a `ToolRegistry` reference, exposing `match()` and `build_input()`.

**Interface/model changes.** `JarvisOrchestrator.__init__` gains a required `command_router: CommandRouter` collaborator. `_handle_request_core` calls `self._command_router.match(text)` / `.build_input(...)` in place of the removed private methods. No change to `JarvisRequest`/`JarvisResponse`.

**Security invariants.** Unchanged and re-asserted by test: `CommandRouter` only ever selects a tool name and builds its input dict; it never classifies risk (that stays with `SecurityManager`), never executes anything, and cannot be used to bypass `ToolExecutor` — it has no reference to the executor at all.

**Tests required.** New `tests/unit/test_command_router.py` testing the matching logic directly (previously reachable only indirectly). Every existing routing/CLI/integration test file must pass **completely unchanged**: `test_core.py`, `test_write_tool_routing.py`, `test_file_tool_routing.py`, `test_memory_command_routing.py`, `test_memory_change_routing.py`, `test_workflow_commands.py`, `test_cli_end_to_end.py`, `test_cli_write_end_to_end.py`, `test_memory_cli_end_to_end.py`.

**Success criteria.** Full suite passes with the same test count as pre-Batch-1 plus the new `CommandRouter` tests; zero modified assertions in any pre-existing routing test; `core/orchestrator.py` shrinks by roughly the size of the moved code; `CommandRouter` is unit-testable without constructing a full `JarvisOrchestrator`.

**Dependencies on earlier batches.** None — first batch.

**Risks and rollback.** Low risk: a pure, mechanical move fully covered by the existing test suite as a regression net. Rollback is a single-commit revert; no later batch depends on `CommandRouter`'s internals, only on its existence as a constructor argument.

---

### 4.2 Batch 2 — Trusted vs Untrusted AI Context Model and AI Path Consolidation

**Purpose.** Make "this text is untrusted" a structural property of data passed into an AI prompt, not a convention that can be silently violated — and make the one AI path that reaches the Core (`AIReasoningEngine`) genuinely reachable through the real application for the first time, through the same hardened construction path as everything else.

**Architectural problem being solved.** Two problems, addressed together because fixing one without the other leaves a gap:
1. `PromptBuilder.build(context: str | None)` accepts a bare string. Nothing today stops a future caller from passing untrusted content into that slot unlabeled.
2. `AIReasoningEngine` builds its own `AIRequest` directly, bypassing `PromptBuilder` entirely — so today's "first line of defence" (the `BEGIN/END CONTEXT` delimiters) doesn't even apply to the one AI code path wired toward the Core. And that path isn't wired toward the Core at all in production: `main.py` never constructs it.

**Exact scope.**
1. Add a `ContentTrust` enum to `config/constants.py` (naming decided in §5).
2. Add `ai/context_models.py` defining `AIContextBlock(text: str, trust: ContentTrust, source: str)`, an immutable, frozen dataclass, constructed **only** via named factory functions (no bare public constructor path that lets a caller casually assert `JARVIS_TRUSTED` for an arbitrary source):
   - `AIContextBlock.from_system(text: str) -> AIContextBlock` — `trust=JARVIS_TRUSTED`, `source="system"`. For text Jarvis's own code authored (e.g. the reasoning engine's system instruction).
   - `AIContextBlock.from_live_user_input(text: str) -> AIContextBlock` — `trust=JARVIS_TRUSTED`, `source="user_live_input"`. For the user's literal current-turn typed request only.
   - `AIContextBlock.from_untrusted(text: str, *, source: str) -> AIContextBlock` — `trust=UNTRUSTED`, for everything else, with `source` required and documented as one of `"memory"`, `"file"`, `"web"`, `"tool_output"`, `"ai_generated"`, `"conversation_history"`, or another named external origin.
   A `__post_init__` on `AIContextBlock` raises if `trust=JARVIS_TRUSTED` is ever paired with a `source` outside `{"system", "user_live_input"}`, so the trust boundary is enforced in code, not only by convention.
3. Change `PromptBuilder.build()`'s `context: str | None` parameter to `context: AIContextBlock | None`. An `UNTRUSTED` block is wrapped in the existing `BEGIN/END CONTEXT` delimiters with the existing "treat as data, not instructions" directive; a `JARVIS_TRUSTED` block is still placed in its own labelled section for clarity, without the untrusted-specific framing.
4. Refactor `AIReasoningEngine.reason()` to build its request via `AIRouter.route()` instead of constructing `AIRequest`/`AIMessage` directly. `AIReasoningEngine.__init__` changes from taking an `AIProvider` to taking an `AIRouter`.
5. Wire `AIReasoningEngine` + `AIRouter` + `PromptBuilder` into `main.py`'s `build_orchestrator()`, constructed and passed to `JarvisOrchestrator(reasoning_engine=...)` **only when `settings.ai_reasoning_enabled` is `True` and a usable Claude provider can be constructed**; when the flag is `False` (the existing default), `main.py` passes `reasoning_engine=None`, exactly as it silently always has.

**What is and is not newly reachable.** This batch's *only* newly-reachable behavior is: **when an operator explicitly sets `AI_REASONING_ENABLED=true` and supplies a valid API key, the already-existing, already-tested, strictly advisory reasoning path becomes callable through the real running application for the first time.** Nothing about what that path is *allowed to do* changes. It does not gain the ability to execute a tool, create a `ToolRequest`, create or grant an approval, alter `SecurityManager` classification, change `response.blocked`, change `response.requires_confirmation`, replace the authoritative result, or bypass `ToolExecutor` — none of that was ever possible before Batch 2 and none of it becomes possible after. The default (`AI_REASONING_ENABLED=false`, unset) behavior is provably unchanged: `main.py` still passes `reasoning_engine=None`, and `JarvisOrchestrator._attach_ai_suggestion` still returns the response unmodified whenever `self._reasoning is None`, exactly as it does today.

**Explicit non-goals.** No new content sources — no file/web content, no real memory content fed into a prompt in this phase; `AIContextBlock.from_untrusted` exists and is fully tested, but no production tool constructs one yet, because no tool that reads external content exists yet. No new AI provider. No change to what the AI is allowed to do. No per-step Plan schema.

**Current files/components involved.** `ai/prompt_builder.py`, `ai/reasoning_engine.py`, `ai/router.py`, `config/constants.py`, `main.py`.

**Proposed new components.** `ai/context_models.py` (`AIContextBlock` and its factory functions); `ContentTrust` enum in `config/constants.py`.

**Interface/model changes.** `PromptBuilder.build()` signature change (breaking, single existing caller: `AIRouter.route()`, updated in lockstep). `AIReasoningEngine.__init__` changes its dependency from `AIProvider` to `AIRouter`. `main.py`'s `build_orchestrator()` gains conditional construction of `AIRouter`/`PromptBuilder`/`AIReasoningEngine`/a `Claude` provider instance, behind the existing flag.

**Security invariants (restated as explicit, testable properties).**
- With `AI_REASONING_ENABLED=false` (default): `main.py` behavior, `JarvisOrchestrator` construction, and every response field are bit-for-bit identical to pre-Batch-2 behavior.
- AI reasoning remains strictly advisory in every configuration.
- The authoritative `JarvisResponse` is always fully built by the rule-based path (`Planner` → `SecurityManager` → `ToolExecutor`/`ApprovalManager`) before `_attach_ai_suggestion` is ever called — unchanged from today's ordering in `handle_request()`.
- AI output cannot, in any configuration: execute a tool, construct a `ToolRequest`, create or grant an `ApprovalRequest`/`ApprovalDecision`, alter a `SecurityDecision`, change `response.blocked`, change `response.requires_confirmation`, replace `response.message`/`response.tool_result`/`response.plan`, or reach `ToolExecutor` in any way. `_attach_ai_suggestion` only ever adds `response.ai_suggestion`, via `dataclasses.replace`, to an already-fully-decided, frozen response.
- Exactly one AI request-construction path exists after this batch: `AIReasoningEngine` → `AIRouter.route()` → `PromptBuilder.build()` → provider. No module anywhere constructs `AIRequest`/`AIMessage` directly except `PromptBuilder` itself.

**Tests required.**
- Unit tests for `AIContextBlock`'s three factory functions, including the `__post_init__` guard rejecting a `JARVIS_TRUSTED`/non-canonical-source combination.
- Unit tests for `PromptBuilder.build()` with `JARVIS_TRUSTED` and `UNTRUSTED` blocks.
- `test_ai_reasoning_engine.py` updated so its fakes exercise the `AIRouter`-based path (test *intent* unchanged: enabled/disabled/unavailable/failure/empty-text behavior all still proven).
- `test_ai_core_safety.py` re-run with **zero assertion changes** — this is the batch's primary safety proof.
- A new `main.py` composition test (or extension of an existing one) proving: `AI_REASONING_ENABLED` unset/false → `reasoning_engine is None` in the constructed orchestrator; `AI_REASONING_ENABLED=true` with a fake/test provider → a live-callable `AIReasoningEngine` is actually constructed and wired — with no real network call in the test.

**Success criteria.** Exactly one code path builds every AI request. `test_ai_core_safety.py` passes unchanged. `AI_REASONING_ENABLED` genuinely toggles reachability in `main.py` for the first time since the flag was introduced in Phase 4. Full suite passes.

**Dependencies on earlier batches.** Benefits from Batch 1 (touches `main.py`'s composition root and later batches touch `_attach_ai_suggestion`, both easier against a smaller `core/orchestrator.py`), but has no hard technical dependency on it.

**Risks and rollback.** Medium — the one batch with a real interface change and the one batch that makes previously-dead code reachable for the first time. Mitigated by: the flag still defaulting to `False` (zero behavior change for every user who does not opt in); `test_ai_core_safety.py` re-run byte-for-byte unchanged as the primary regression gate; the `AIContextBlock` factory-function-only construction preventing accidental trust mislabeling. Rollback is a revert of the batch's commit(s); because the flag still defaults off, reverting late costs nothing to any user who never enabled it.

---

### 4.3 Batch 3 — Prompt Injection Pattern Detection

**Purpose.** Implement the specification's mandatory scan of untrusted content for instruction-like patterns before it can reach any AI provider.

**Architectural problem being solved.** Rule 4 of the specification's injection-defence table ("Suspicious pattern detection") has no code today.

**Exact scope.** Add `SecurityManager.scan_for_injection(text: str) -> InjectionScanResult`, detecting a small, explicit, auditable set of instruction-like patterns via straightforward string/regex matching — imperatives directed at an AI ("ignore previous instructions," "disregard the above"), explicit role/system-override phrasing ("system instruction:", "you are now," "new instructions:"), tool-call-like syntax embedded in prose, and common jailbreak phrasing — consistent with the existing rule-based, auditable style of `classify_action`. Wire the scan to run automatically inside `PromptBuilder.build()` whenever an `AIContextBlock` with `trust=UNTRUSTED` is supplied; a `JARVIS_TRUSTED` block is never scanned (there is nothing external to scan for).

**Explicit non-goals.** No ML/semantic detection. No continuously-updated pattern library (the specification's "advanced injection pattern libraries" is explicitly Future Expansion). No blocking of legitimate user input — the scan never runs on `JARVIS_TRUSTED` content, so the user's own live request is never subject to it.

**Current files/components involved.** `security/security_manager.py`, `ai/prompt_builder.py`.

**Proposed new components.** `InjectionScanResult` dataclass (`suspicious: bool`, `matched_patterns: tuple[str, ...]`, `text: str`) alongside `SecurityDecision` in `security_manager.py`.

**Interface/model changes.** New public method on `SecurityManager`. `PromptBuilder` gains a narrow injected dependency — a `Callable[[str], InjectionScanResult]` (not the whole `SecurityManager`), matching the "narrow interfaces and dependency injection" development rule.

**Security invariants.** Detection is never itself enforcement: a scan finding does not block prompt construction by itself (rules 1–3 hold regardless of the scan's result); every finding is unconditionally reported for audit (rule 6), never silently dropped; the scan only ever inspects `UNTRUSTED`-tagged content.

**Tests required.** Unit tests with synthetic untrusted strings containing each pattern category (positive cases) and clean strings including representative ordinary text — README excerpts, existing memory-record-shaped strings — as negative fixtures (no false positives). A test proving the scan is never invoked for `JARVIS_TRUSTED` content or the live user request.

**Success criteria.** Every enumerated pattern category has at least one passing positive test; zero false positives against the negative fixture set.

**Dependencies on earlier batches.** Requires Batch 2's `AIContextBlock`/`ContentTrust` model — a scan cannot be scoped to "untrusted content" without that type existing first.

**Risks and rollback.** Low-medium: false positives are the main risk, mitigated by a small, explicit pattern list tested against negative fixtures before any future expansion. Rollback is a single revert; nothing yet depends on scan results triggering an action (Batch 4 wires the escalation policy on top).

---

### 4.4 Batch 4 — Unexpected AI Action Escalation

**Purpose.** Implement the specification's rule that an AI response requesting something outside the request's original expected scope must be escalated by tier, never silently allowed.

**Architectural problem being solved.** No code today compares an AI's suggested actions against what was actually planned for the request; `AISuggestedAction.suggested_tier` is currently unvalidated advisory text.

**Representing "expected scope" without a Workflow Engine.** No new schema is introduced. The set of `PlanStep.action` strings the Planner already produced for *this specific request* is the expected scope: `frozenset(step.action for step in response.plan.steps)`. This is honestly single-turn, not a persistent multi-step workflow — the correct, scoped-down interpretation given that Phase 7 does not build a Workflow Engine.

**Exact scope.** Add `SecurityManager.evaluate_unexpected_action(action: str, expected_actions: frozenset[str]) -> UnexpectedActionDecision`. It classifies `action` via the existing `classify_action` and, only if `action not in expected_actions`, returns a verdict: `FLAG` for a GREEN action, `ESCALATE` for a YELLOW action, `BLOCK` for a RED action. Wire this into `JarvisOrchestrator._attach_ai_suggestion`: for each `AISuggestedAction` in an `AIReasoningResult`, compute the expected-actions set from `response.plan` and call the new method **purely for observability** — emit the corresponding audit event. `response` itself is not modified beyond the existing, unchanged advisory-suggestion attachment.

**Why this is "armed but currently unreachable."** No code path in this codebase — before, during, or after Phase 7 — lets an `AISuggestedAction` become a `ToolRequest`. So the `ESCALATE`/`BLOCK` verdicts are fully implemented and fully unit-tested against synthetic scenarios, proving the policy logic is correct, but they have no live trigger today, because nothing ever tries to execute what the AI suggests. This must be stated plainly in this document and in Batch 5's completion report — it would be dishonest to claim this batch "protects" a live execution path when no such path exists.

**Explicit non-goals.** No execution path from `AISuggestedAction` to `ToolRequest` — creating one would violate the standing rule that AI cannot execute tools, and is explicitly out of scope. No multi-turn or cross-request workflow scope.

**Current files/components involved.** `security/security_manager.py`, `core/orchestrator.py` (`_attach_ai_suggestion`), `ai/reasoning_models.py` (`AISuggestedAction`, read-only).

**Proposed new components.** `UnexpectedActionDecision` (verdict enum or small dataclass carrying `verdict: {FLAG, ESCALATE, BLOCK}` and `reason: str`) in `security_manager.py`.

**Interface/model changes.** New public method on `SecurityManager`. Small addition to `_attach_ai_suggestion` (made easier to review because Batch 1 already reduced this file's size).

**Security invariants.** `classify_action`'s existing GREEN/YELLOW/RED logic is reused, never reimplemented or duplicated. This batch adds an escalation *layer* on top, not a new classifier. Must be proven to never affect `response.success`, `response.blocked`, `response.requires_confirmation`, or `response.tool_result` for any input — a direct, explicit test requirement, since the whole point is that this is observability-only until (if ever) a future phase deliberately opens an AI-to-execution path.

**Tests required.** New `tests/unit/test_security_unexpected_action.py` covering all three verdicts against synthetic "AI suggested a RED/YELLOW/GREEN action not in the plan" scenarios, plus the "AI suggested an action already in the plan → no escalation" negative case. An extension of `test_ai_core_safety.py` proving the audit event fires but every `response` field is identical to the pre-Batch-4 value for the same inputs.

**Success criteria.** All three verdicts independently tested and correct. Zero change to any existing `test_ai_core_safety.py` assertion. The "armed but unreachable" framing is explicit in code comments and documentation, not implied to be a live protection.

**Dependencies on earlier batches.** Logically independent of Batches 2/3 (uses `Plan`/`AISuggestedAction`, which already exist, not the trust model), but ordered after them thematically, and benefits from Batch 1's smaller `core/orchestrator.py`.

**Risks and rollback.** Low: purely additive observability with no behavior-affecting change to `JarvisResponse`. Single-commit revert; nothing downstream depends on it.

---

### 4.5 Batch 5 — End-to-End Security Verification and Documentation

**Purpose.** Prove, in one consolidated place, that all six Master Specification injection-defence rules are satisfied, and document Phase 7 in the established voice of Phases 1–6.

**Architectural problem being solved.** None — this batch is verification and documentation.

**Exact scope.** One new integration test file, e.g. `tests/integration/test_ai_injection_defence_end_to_end.py`, exercising the full path through the real `AIRouter`/`SecurityManager`/`EventLogger` stack (fake provider, as in every prior phase, no real network call): a synthetic `AIContextBlock.from_untrusted(...)` containing a known injection pattern → `PromptBuilder` → scan flagged → audited with the new outcome/action-type vocabulary; a synthetic AI suggestion naming an action outside the plan, at each of GREEN/YELLOW/RED → escalation verdict → audited. `docs/phase_7_completion_report.md` written once all batches land, plus a README Phase 7 section (both deferred until implementation is complete — not part of this planning document).

**Explicit non-goals.** No new production code beyond what Batches 1–4 already added. No Phase 8 planning.

**Security invariants.** The six-rule coverage table (§8) must appear in the completion report exactly as in this plan, including the explicit "rule 5 is armed but currently unreachable" caveat — this batch must not overstate what was built.

**Tests required.** The consolidated end-to-end file above; a final full-suite run reporting the new authoritative total.

**Success criteria.** Full suite passes; the six-rule table is present and honest; documentation follows the established structural conventions (Executive Summary, What Was Added, Safety Model, Tests, Verification, Known Limitations, Status Statement).

**Dependencies on earlier batches.** Requires Batches 1–4 complete.

**Risks and rollback.** Minimal — documentation and test-only batch.

---

## 5. Trust-Boundary Rules

**Final naming decision: `ContentTrust.JARVIS_TRUSTED` and `ContentTrust.UNTRUSTED`.** Bare `TRUSTED` is rejected as a value name: it invites a future caller to reason "I trust this content" subjectively, rather than checking whether the content's *origin* actually qualifies. `JARVIS_TRUSTED` names the boundary precisely: trusted because it originates from Jarvis's own authored system text, or from the user's own literal current-turn instruction — never because of any judgment call about the content itself.

```python
class ContentTrust(Enum):
    JARVIS_TRUSTED = "jarvis_trusted"
    UNTRUSTED = "untrusted"
```

**What qualifies as `JARVIS_TRUSTED` — exhaustively:**
- Text authored directly by Jarvis's own code (e.g. `AIReasoningEngine`'s system instruction) — origin `"system"`.
- The user's own literal, current-turn typed request — origin `"user_live_input"`.

**What must always be treated as `UNTRUSTED` when supplied as contextual source material to an AI request, unless a future, explicit, documented security decision changes this** — per your instruction, listed exhaustively and not to be silently reclassified by any future batch:
- Stored memory (episodic or otherwise) — even though the user wrote it, it was not written in this live turn and could itself have been influenced by something injected earlier.
- File contents.
- Web/network content.
- Tool output (any `ToolResult.output` text, if ever re-fed into a subsequent AI prompt rather than shown directly to the user).
- AI-generated content (including Jarvis's own prior AI output, if ever re-fed into a later prompt).
- Historical conversation text (anything beyond the current turn's live input).

**Enforcement.** `AIContextBlock` has no public constructor path that allows `trust=JARVIS_TRUSTED` for an arbitrary `source`; only `AIContextBlock.from_system()` and `AIContextBlock.from_live_user_input()` can produce it, and `__post_init__` rejects any other combination. A future caller wanting to feed memory, file, web, or tool content into a prompt is structurally forced through `AIContextBlock.from_untrusted(..., source=...)`, which is unconditionally scanned (Batch 3) and unconditionally delimited (Batch 2).

---

## 6. Master Specification Six-Rule Coverage Table

| # | Rule | Satisfied by | Status at end of Phase 7 |
|---|---|---|---|
| 1 | Separate prompt contexts | Already true today via `PromptBuilder`'s `BEGIN/END CONTEXT` delimiters; Batch 2 makes it structurally unavoidable (`AIContextBlock`, not a bare string) and extends it to `AIReasoningEngine`'s path | Fully satisfied, structurally enforced |
| 2 | Explicit data-only directive | Already true today (`_CONTEXT_HEADER` text); unchanged by Batch 2 except now unavoidable for every caller | Fully satisfied |
| 3 | No raw concatenation | Already true today (`AIRequest`/`AIMessage` are structured, never joined into one string); Batch 2 closes the `AIReasoningEngine` bypass so both paths comply | Fully satisfied |
| 4 | Suspicious pattern detection | Batch 3 | Satisfied, tested against synthetic untrusted content |
| 5 | Unexpected action escalation | Batch 4 | Satisfied at the policy/detection level; RED/YELLOW enforcement is armed but has no live trigger, because no code path lets an AI suggestion execute |
| 6 | Flagging and reporting | Batches 3 + 4, consolidated in Batch 5 | Satisfied — every detection and escalation is unconditionally audited |

---

## 7. Testing Strategy

- **Regression-first.** Every batch's primary success gate is that all pre-existing tests pass with zero assertion changes, especially `test_ai_core_safety.py` (Batches 2 and 4) and the full routing/CLI/integration suite (Batch 1).
- **Unit tests per new component**, following existing conventions: fakes/spies for loggers and providers, no real network calls anywhere, real in-memory SQLite for anything touching the database.
- **Synthetic adversarial fixtures** for Batches 3 and 4 — since no real external-content tool exists yet (a deliberate non-goal), injection patterns and unexpected-action scenarios are tested against hand-constructed synthetic input, not real web/file content.
- **One consolidated end-to-end test** in Batch 5 exercising the real `AIRouter`/`SecurityManager`/`EventLogger` stack together.
- **No live Claude API call anywhere**, in any batch — a fake provider is used throughout, exactly as in every phase since Phase 1.

---

## 8. Success Criteria (Phase-Level)

- All five batches individually meet their own success criteria (§4).
- The full test suite passes throughout, with the count only ever growing.
- `AI_REASONING_ENABLED=false` (the existing default) produces behavior provably identical to pre-Phase-7 Jarvis.
- Exactly one AI request-construction path exists in the codebase.
- All six Master Specification injection-defence rules have corresponding, tested code, with the Batch 4/Rule 5 reachability caveat stated honestly, not hidden.
- No GREEN/YELLOW/RED classification changes for any existing action string.
- No new user-facing command, tool, or capability exists at the end of Phase 7.

---

## 9. Rollback Concerns (Phase-Level)

Each batch is an independent, revertable commit (or small commit set) with the dependency order: Batch 1 → independent; Batch 2 → depends on nothing but is a prerequisite for 3; Batch 3 → depends on 2; Batch 4 → depends on 1 and 4 only for code-cleanliness reasons, not a hard technical dependency; Batch 5 → depends on 1–4 all landing. The highest-risk single point is Batch 2's `main.py` wiring change, because it is the only batch that makes previously-unreachable code reachable — its rollback safety net is that the feature flag still defaults to `False`, so even a late revert costs nothing to any user who never opted in. No batch introduces a database migration, so no batch has schema rollback concerns.

---

## 10. Deferred Work

Explicitly out of scope for Phase 7, to be revisited only in a future, separately-scoped phase with its own design:

- A Workflow Engine of any kind (checkpointing, task states, retries, `OnFailure` policy, `ActionType.BRANCH`/`PARALLEL_GROUP` execution).
- Per-step `approval_timeout_seconds` overrides (requires a per-step Plan schema that does not exist).
- True multi-turn or cross-request "expected workflow scope" (Phase 7's scope is single-request only, via the current `Plan`).
- Web search, real file-content ingestion into AI prompts, computer control, agents, new AI providers, resumable approvals — all remain untouched, per your explicit constraints.
- Any path that lets an `AISuggestedAction` become executable. Phase 7 builds the gate for that day; it does not open the door.
- An "advanced," continuously-updated injection-pattern library (specification's own Future Expansion item).

---

## 11. Development Rules for Phase 7

Carried forward from the project's established discipline and your explicit constraints for this phase:

1. Never develop directly on `main`; one batch per short-lived branch, matching the pattern of every prior phase.
2. Prefer a mechanical, zero-behavior-change move before any behavior change (Batch 1 in full; Batches 2–4's non-AI-facing refactors where applicable).
3. Narrow interfaces and dependency injection over broad ones — e.g., `PromptBuilder` receives a scan `Callable`, not a whole `SecurityManager`.
4. No new subsystem or new distributed/async mechanism — everything stays in-process Python function calls, consistent with the Master Specification's own Phase 1 communication model.
5. Every new action type or audit-relevant event still emits through the existing `EventLogger`/`EventOutcome` machinery — no new logging subsystem.
6. A batch is not complete until its own tests pass **and** the full suite, including every pre-existing test, passes unchanged.
7. GREEN/YELLOW/RED classification logic (`SecurityManager.classify_action`) is reused everywhere a tier is needed; it is never duplicated or reimplemented for a new purpose.
8. AI remains advisory in every batch, in every configuration, without exception — proven by `test_ai_core_safety.py` passing with zero assertion changes throughout the phase.

---

## Summary

Phase 7 — **Core Simplification and AI Safety Hardening** — removes the one identified piece of Core architectural debt (command-matching logic fused into `JarvisOrchestrator`) and completes the three still-missing Master Specification prompt-injection defence rules, while making the already-built, already-tested advisory AI reasoning path genuinely reachable in the running application for the first time — strictly behind its existing, still-defaulted-off feature flag, and without ever increasing what AI output is permitted to do. No new capability, no new provider, no new autonomy, no Workflow Engine, and no change to GREEN/YELLOW/RED policy. The phase's entire purpose is to make the *next* phase — whatever introduces real external-content ingestion — start from a codebase that is already honest about trust boundaries, rather than retrofitting that honesty after the fact.
