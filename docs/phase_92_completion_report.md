# Phase 92 — Intelligence Decision Grounding and Reliability V1 — Completion Report

**Checkpoint:** complete through Batch 2, its originally-scoped final batch.
**Version:** Phase 92 — Intelligence Decision Grounding and Reliability V1 (medium milestone: planning gate + 2 batches)
**Date:** 2026-07-20

---

## 1. Phase Objective

Add a deterministic, deny-only safety layer between the AI's structured "ask jarvis to: <request>" tool-selection decision and every downstream consequential step (`SecurityManager` preflight, `ApprovalManager`, `ToolExecutor`, verification). This layer independently confirms that the model's selected capability, and any model-supplied argument value, is genuinely attributable to the live user request — never to `AssembledContext`, retrieved memory, model rationale, or any other source. It can only refuse an otherwise-valid decision; it never selects a replacement capability, never repairs or modifies an argument value, and never calls another model. The full Phase 90/91 Intelligence Core pipeline, the advisory `ask jarvis:` path, and every deterministic command were required to remain exactly unchanged.

---

## 2. Planning and Amendment Commit History

| Commit | Content |
|---|---|
| `5568cfd` | Planning gate — `docs/phase_92_implementation_plan.md`, candidate inspection (A–E), selection of Candidate B (Intelligence Decision Grounding and Reliability) |
| `13fb9c2` | First planning amendment — extends scope from capability-selection grounding alone to also cover model-supplied argument-value grounding |
| `a403dd6` | Second planning amendment — action-and-domain intent signatures (replacing domain-keyword-only grounding) and marker-based argument-span attribution (replacing whole-request significant-term attribution) |
| `fa01678` | Final planning correction — the exact, final six-capability signature table; catalogue-wide uniqueness rule; collision matrix; exact negation/punctuation rules; drop of the "and confirm it" special case |

---

## 3. Batch 1 and Batch 2 Commit History

| Commit | Content |
|---|---|
| `ed0047b` | Batch 1 — `intelligence/grounding.py` (the deterministic `ground_decision()` contract), `PlanningOutcomeKind.UNGROUNDED_SELECTION` wired into `select_tool()`, a minimal crash-preventing orchestrator branch, and the required fixture-consistency corrections |
| *(this commit)* | Batch 2 and closure — completed two-category public refusal-message mapping, end-to-end zero-side-effect proofs, full regression verification, documentation, and formal closure (see §21 in this report for the exact commit) |

---

## 4. Production Architecture

`intelligence/grounding.py::ground_decision(*, request_text, capability_id, arguments) -> GroundingResult` is a pure function — no AI provider call, no I/O, no retained state between calls, no argument beyond the three named (verified by a dedicated signature-purity test). `intelligence/planning.py::select_tool()` calls it immediately after resolving the capability adapter and before `_preflight_capability()`, covering both the `EXECUTABLE` and `EXECUTABLE_WORKFLOW` paths identically. A refusal produces `PlanningOutcomeKind.UNGROUNDED_SELECTION` with a bounded `detail` string; `core/orchestrator.py::_handle_ask_jarvis_to_request()` maps that outcome to one of exactly two fixed, honest, non-technical public messages (§13) before returning — no preflight, approval, execution, or verification of any kind is ever attempted for a refused decision.

Direct audit of Batch 1's production diff (`ed0047b`, re-verified in Batch 2 — see §17) confirmed the diff is limited to exactly the pieces above: no unrelated refactoring, no duplicated orchestration architecture, no new capability behavior, no hidden retry/replanning, no request/argument mutation, no additional AI call, no probabilistic interpretation, no security-rule change, and no approval bypass.

---

## 5. Exact Six-Capability Signature Table

Each capability requires independent action evidence **and** domain evidence (**and**, for one capability, a recency qualifier) — never substituting for one another:

| Capability | Required action | Required domain | Required qualifier |
|---|---|---|---|
| `PROJECT_STATE_SHOW` | `"show"` | adjacent phrase `"project state"` | — |
| `PROJECT_STATE_UPDATE_FOCUS` | `"update"` | `"focus"` | — |
| `HEALTH_CHECK` | `"check"` | `"health"` (deliberately not `"status"` — see §17) | — |
| `SCHEDULE_LIST` | `"show"` or `"list"` | `"schedule"` or `"schedules"` | — |
| `MEMORY_LIST_RECENT` | `"show"` or `"list"` | `"memory"`, `"memories"`, `"remember"`, or `"remembered"` | `"recent"` or `"recently"` (mandatory, separate from action) |
| `MEMORY_SEARCH` | `"search"` or `"find"` | `"memory"` or `"memories"` | — |

---

## 6. Catalogue-Wide Uniqueness Architecture Behavior

`ground_decision()` evaluates the live `request_text` against **all six** signatures, not only the model-selected one, in this exact order:

1. Negation/conflict gate (§8) — checked first, unconditionally.
2. Evaluate all six signatures; collect the set of capability ids whose full signature is satisfied.
3. Empty set → refuse (`no_signature_matched`).
4. More than one member → refuse (`multiple_signatures_matched`), **even if** the model's selection is among the matched set — a genuinely ambiguous request is never resolved by trusting the model's own choice among the candidates.
5. Exactly one member, not equal to the model's selection → refuse (`selected_capability_not_unique_match`).
6. Otherwise (unique member equals the selection): proceed to argument-span attribution (§9/§10) if the capability declares a string argument, else proceed directly to `_preflight_capability()`.

---

## 7. Request Normalization

Before any matching: casefold; replace the curly apostrophe `’` (U+2019) with the straight apostrophe `'`; collapse runs of whitespace to a single space; strip leading/trailing whitespace. Tokenization for signature matching splits on `[^a-z0-9]+`. No stemming, synonym expansion, or fuzzy matching of any kind is performed anywhere in the contract.

---

## 8. Exact Negation/Conflict Behavior

Checked first, unconditionally, for every capability including zero-argument ones:
- **Whole-word markers** (space-padded substring match, so a word merely containing the same letters without a surrounding space never triggers): `" not "`, `" never "`. Catches `"do not"`, `"does not"`, `"is not"`, etc. via `" not "`. Does **not** trigger inside `"notebook"`, `"notice"`, `"whenever"`, or `"nevertheless"`.
- **Contraction substrings** (matched after apostrophe normalization): `"don't"`, `"doesn't"`, `"isn't"`, `"won't"`, `"can't"`.
- **Fixed phrase substrings**: `"cannot"`, `"instead of"`, `"rather than"`, `"but not"`.

A request containing any of these markers is refused as `negated_or_conflicting_request` before any signature or argument logic runs.

---

## 9. MEMORY_SEARCH Argument-Span Attribution

Marker `" for "` (case-insensitive). Must occur **exactly once** (zero → `missing_argument_span`; more than one → `ambiguous_argument_span`). The trimmed text after the marker is the candidate span; it must be non-empty and must not contain the space-padded substring `" or "` (both → `ambiguous_argument_span`). The model's already-validated `value` is compared to the candidate span via exact normalized equality (§11) — never containment, never a fuzzy or partial match. A mismatch is refused as `argument_value_mismatch`.

---

## 10. PROJECT_STATE_UPDATE_FOCUS Argument-Span Attribution

Identical mechanism to §9, using marker `" to "` instead of `" for "`. No suffix-stripping special case exists (the historical "and confirm it" exception was investigated and dropped — see §17 fixture table) — extra trailing text of any kind causes an exact-equality mismatch like any other non-matching span.

---

## 11. Punctuation and Ambiguity Rules

Before the exact-equality comparison, at most **one** trailing character is stripped from the end of *both* the candidate span and the model-supplied value, if and only if that trailing character is one of exactly `.`, `!`, `?`. No other punctuation (commas, colons, semicolons, quotation marks, parentheses) is ever stripped, from either end, at any position, and never more than one character even if two or more terminal characters are present. Ambiguity (zero/multiple markers, empty span, or an internal `" or "` disjunction) is refused before this comparison is ever reached.

---

## 12. Planning Outcome and Bounded Reasons

`PlanningOutcomeKind.UNGROUNDED_SELECTION` is the single, shared public outcome kind. Its bounded, internal `detail` string distinguishes exactly seven `UngroundedReason` values — one more than the planning document's own §20.9 (which merged the two argument-span failure modes into one): `negated_or_conflicting_request`, `no_signature_matched`, `multiple_signatures_matched`, `selected_capability_not_unique_match`, `missing_argument_span`, `ambiguous_argument_span`, `argument_value_mismatch`. This is purely additional internal diagnostic granularity — it changes no refusal/acceptance outcome, and both new members map to the same public message (§13). No detail string ever includes the raw request text, the candidate span, the rejected value, retrieved context, or model reasoning.

---

## 13. Public Refusal-Message Behavior

Batch 2 maps the seven bounded reasons to exactly **two** fixed, honest, non-technical public messages, chosen to be the smallest useful mapping (never seven distinct wordings):

- **Action-selection refusal** (`no_signature_matched`, `multiple_signatures_matched`, `selected_capability_not_unique_match`): *"Jarvis could not safely match that request to one supported action, so nothing was run. Please restate exactly what you'd like Jarvis to do."*
- **Exact-request refusal** (`negated_or_conflicting_request`, `missing_argument_span`, `ambiguous_argument_span`, `argument_value_mismatch`): *"Jarvis could not safely confirm the exact request or value, so nothing was run. Please restate it directly and exactly."*

Neither message ever exposes the internal reason code, the live request, a candidate argument span, or a rejected/candidate value. `test_ungrounded_message_mapping_is_exhaustive_and_exactly_two_valued` proves every real `UngroundedReason` member (read from the enum itself) maps to exactly one of these two strings. `test_public_refusal_messages_expose_no_internal_mechanics` proves neither message contains `signature`, `span`, `enum`, `reason`, `grounding`, `capability_id`, `parse`, `negation`, or `regex`, and both are under 200 characters.

---

## 14. Execution-Order Guarantees

Grounding runs, in this fixed order relative to every other subsystem: after strict structured parsing and argument validation (`intelligence/structured_output.py`), after capability-adapter resolution, **before** `_preflight_capability()` (which calls `SecurityManager.classify_action()`), before `ApprovalManager.create_request()`, before `ToolExecutor.execute()`, and before `intelligence/verification.py::verify_focus_update()`. This is proven directly, not merely asserted: `test_ungrounded_selection_never_reaches_security_manager_preflight` uses a real, counting `SecurityManager` subclass to prove zero `classify_action()` calls on refusal, while `test_grounded_selection_still_reaches_security_manager_preflight` proves the identical fixture records exactly one call for a genuinely grounded request (ruling out the zero-call result being a fixture artifact rather than a real execution-order guarantee).

---

## 15. Zero-Side-Effect Refusal Evidence

Proven end-to-end, across both the ordinary `EXECUTABLE` path and the `EXECUTABLE_WORKFLOW` (`PROJECT_STATE_UPDATE_FOCUS`) path, using real `SecurityManager`, `ToolRegistry`/`ToolExecutor`, `ApprovalManager`, `WorkflowEngine`, and `ProjectStateStore`/`PausedWorkflowStore` over a real in-memory SQLite database (never mocks of these components):

- **Zero `SecurityManager` classification** — `test_ungrounded_selection_never_reaches_security_manager_preflight`.
- **Zero approval creation, zero pending workflow** — `test_ungrounded_selection_creates_no_approval`, `test_ungrounded_update_focus_value_creates_no_approval_and_no_write`, `test_negated_update_focus_request_creates_no_approval_and_no_write`, and `test_update_focus_argument_mismatch_creates_no_durable_pending_workflow` (a fresh `PausedWorkflowStore` instance over the same session factory reads back zero rows).
- **Zero `ToolExecutor` invocation** — `test_ungrounded_selection_causes_zero_tool_executor_calls`, `test_capability_mismatch_executes_neither_the_correct_nor_selected_tool`, `test_multiple_signature_match_returns_action_selection_message_and_executes_nothing`, `test_capability_mismatch_for_update_focus_executes_neither_tool`.
- **Zero verifier invocation** — structural proof (`test_ungrounded_update_focus_never_reaches_workflow_engine`) that the refusal branch never calls `_start_update_focus_workflow()`, the sole path capable of reaching `WorkflowEngine.run()` and, downstream, the verifier.
- **Zero `ProjectState` write** — `project_state_store.get() is None` asserted on every update-focus refusal test.
- **Zero memory search / zero memory-result exposure** — `test_ungrounded_memory_search_argument_never_exposes_search_results` proves a pre-saved private memory never appears in a refusal response, and `response.tool_result is None`.
- **Zero retry, zero replanning, zero second model call** — `test_no_second_ai_call_on_any_grounding_refusal`, parametrized across no-signature, multiple-signature, capability-mismatch, and negation cases: exactly one `AIProvider.generate()` call each.
- **Rejected values never echoed** — `test_ungrounded_update_focus_response_message_never_leaks_the_candidate_value` and the message-content assertions in the memory-search and update-focus mismatch tests.

---

## 16. Preserved Success Paths

All six capabilities were confirmed still functioning exactly as before, through pre-existing tests unmodified in Batch 2 (only fixture wording was made internally consistent in Batch 1 — see §17):

- `PROJECT_STATE_SHOW` — `test_project_state_show_behavior_is_unaffected_by_new_capabilities`, `test_real_execution_through_real_tool_executor_grounds_the_response`.
- `PROJECT_STATE_UPDATE_FOCUS` — `test_approval_executes_the_workflow_exactly_once` (real YELLOW classification, real approval creation, real durable write), `test_durable_restart_end_to_end` (real resume across a simulated process restart), `test_exact_mismatch_reports_failed_verification` / `test_write_failure_means_verifier_never_runs` (real durable verification).
- `HEALTH_CHECK` — `test_health_check_executes_through_real_tool_executor_and_grounds_response`.
- `SCHEDULE_LIST` — `test_schedule_list_executes_through_real_tool_executor_and_grounds_response`.
- `MEMORY_LIST_RECENT` — `test_memory_list_recent_executes_through_real_tool_executor_and_grounds_response`.
- `MEMORY_SEARCH` — `test_memory_search_executes_through_real_tool_executor_and_grounds_response`.

The advisory `ask jarvis:` path is structurally proven (new, Batch 2) never to reference `select_tool(`, `ground_decision(`, or `ToolExecutor` (`test_advisory_ask_jarvis_handler_never_calls_select_tool_or_grounding`), and the pre-existing `test_ask_jarvis_advisory_command_remains_unaffected`, `test_existing_deterministic_commands_are_unaffected`, `test_ask_jarvis_advisory_remains_unaffected_by_update_focus_addition`, and `test_existing_deterministic_command_remains_unaffected` all continue to pass unmodified.

---

## 17. Compatibility and Fixture Wording Changes

Every fixture wording change made in Batch 1 was re-verified directly against `ed0047b`'s diff for this report (not from memory):

| File | Old request wording | New request wording | Why the old wording lacked evidence |
|---|---|---|---|
| `test_intelligence_planning.py` (×2), `test_orchestrator_ask_jarvis_to.py` (×1) | `"what have I asked you to remember recently"` | `"show me what I have asked you to remember recently"` | Contained no listing/display action token (`"show"`/`"list"`) required by `MEMORY_LIST_RECENT`'s corrected signature — only the domain word and recency qualifier were present. |
| `test_intelligence_planning.py` (×9) | `request_text="update my focus"` | `request_text="update my focus to a new focus value"` | Contained the action and domain tokens but no `" to "` marker, so no argument span could ever be extracted for the paired fake value. |
| `test_orchestrator_update_focus_workflow.py` (`_REQUEST` + all `_update_focus_text()` fixtures) | `_REQUEST` ended `"...and confirm it"`; fake values varied (`"new focus value"`, `"restart-tested focus"`, `"intended value"`, `"some value"`, `"new focus"`, `"grounded focus value"`, `"some private-looking value"`, `"no second call test"`) | `_REQUEST` drops the suffix; every fake value realigned to `"batch 3 verification"`, matching `_REQUEST`'s own `" to "` span exactly | None of the varied fake values were ever the literal text following `" to "` in `_REQUEST` — argument grounding did not exist before Batch 1, so this mismatch was invisible until it did. |

**Confirmation: no assertion was weakened.** Every downstream literal-value assertion was updated to the same new, consistent value — never loosened, never replaced with a substring check or wildcard. The one deliberately new restriction — the planning document's own illustrative `"Show me the current project focus"` phrasing, never previously accepted, correctly refused as `no_signature_matched` — is a documented, intentional narrowing, not a regression. No inconsistent fixture was restored to preserve historical text. One additional, deliberate narrowing beyond the plan's own §20.2 was made and is disclosed here: `HEALTH_CHECK`'s domain requirement is `"health"` only, not `"health"` or `"status"` as originally allowed — investigation (`tests/unit/test_orchestrator_ask_jarvis_to.py`, `test_intelligence_planning.py`, `test_health_check_tool.py`, `docs/user_guide.md`, `tools/builtin/help_tool.py`) confirmed no test or documented behavior requires bare `"status"`. All accepted safe Phase 90/91 user-facing examples still pass unchanged (§18).

---

## 18. Focused and Complete Verification

- Focused Phase 92 suite (`test_grounding.py` 71, `test_intelligence_planning.py` 43, `test_orchestrator_ask_jarvis_to.py` 54, `test_orchestrator_update_focus_workflow.py` 31): **199 passed**.
- Phase 90/91 regression sweep (approval manager/history/audit/models/prompt, capability catalog, CLI/core approval, health-check tool + wiring, pending-approval wiring, project-state wiring/store/show/update/verify tools, memory tool, orchestrator context-query/workflow-commands, pending approval store, structured output, tool-executor approval + logger isolation, verification — 29 files): **649 passed**.
- Full suite, normal environment: **4760 passed, 3 skipped** (13 more than Batch 1's 4747 — exactly the 13 Batch 2 tests added).
- Full suite, `AI_REASONING_ENABLED=false`: **4760 passed, 3 skipped** — identical.
- Full suite, `PYTHON_DOTENV_DISABLED=1`: **4760 passed, 3 skipped** — identical.
- Ruff (`ruff check` on every Python file changed across both batches: `core/orchestrator.py intelligence/planning.py intelligence/grounding.py tests/unit/test_intelligence_planning.py tests/unit/test_orchestrator_ask_jarvis_to.py tests/unit/test_orchestrator_update_focus_workflow.py tests/unit/test_grounding.py`): **All checks passed! Exit code 0.** No new or pre-existing findings.
- `git diff --check`: exit code 0. Only pre-existing `LF will be replaced by CRLF` advisory notices (Windows `core.autocrlf`), never a whitespace error.

---

## 19. Manual Anthropic API Acceptance Status

Live Anthropic manual acceptance testing remains **postponed**. The configured API account lacks sufficient credits to run a genuine live-model verification pass. This is an **external account limitation, not a Jarvis code failure** — no production behavior was changed to bypass it, and no live manual test is claimed to have passed. Phase 92 is closed on the basis of repository-level fake-provider, deterministic, security, approval, execution, verification, and full-suite tests (all real, all executed, all passing) — not on a live-model acceptance run, exactly as every prior phase closure has been.

---

## 20. Deferred Scope and Non-Goals

Phase 92 did not add or expose: any new capability, any new write action, any new `SecurityManager` rule, any security-tier change, arbitrary `ToolRegistry` access, multi-tool plans, capability substitution, retries, replanning, autonomous agents, automatic memory writes, conversation persistence, verifier generalization, dynamic natural-language parsing, embeddings, semantic similarity, confidence scoring, request rewriting, argument rewriting, dashboard changes, voice, microphone, wake-word, phone integration, browser control, general computer control, or source-code self-modification. The fixed grounding vocabulary (six signatures, negation markers, argument-span markers) was not broadened in Batch 2; no alias was added merely to make more natural-language phrasing pass.

---

## 21. Final Repository Status

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- HEAD before this closure commit: `ed0047b` (Phase 92 Batch 1).
- This report's own commit — "Close Phase 92 decision grounding and reliability" — follows immediately, containing the Batch 2 production/test changes (`core/orchestrator.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_orchestrator_update_focus_workflow.py`), the documentation updates (`docs/phase_92_implementation_plan.md` §22, `docs/user_guide.md`, `tools/builtin/help_tool.py`), and this completion report.
- `git status --short` immediately before that commit: only `?? dashboard_test.txt` beyond the intended changes — confirmed untouched, untracked, and uncommitted throughout both Batch 1 and Batch 2.
- Full suite: 4760 passed, 3 skipped, 0 failed (normal environment, `AI_REASONING_ENABLED=false`, and `PYTHON_DOTENV_DISABLED=1`, identical across all three).

---

## 22. Final Closure Statement

Phase 92 — Intelligence Decision Grounding and Reliability V1 is **formally closed**. The deterministic, deny-only grounding contract (`intelligence/grounding.py`) is fully wired into `select_tool()` ahead of every consequential subsystem, refuses exactly the seven bounded, non-sensitive reason categories specified by the accepted planning document, and is now paired with exactly two honest, non-technical, bounded public refusal messages. Every one of the six existing Intelligence Core capabilities continues to function exactly as before; every refusal category is proven, end-to-end, to stop before `SecurityManager` classification, approval creation, `ToolExecutor` invocation, verification, durable writes, and memory-result exposure. The advisory `ask jarvis:` path and all deterministic command grammar remain exactly as Phase 90/91 left them. Manual live-AI acceptance remains postponed for external account-credit reasons, honestly disclosed above, and this closure does not claim otherwise. No Phase 93 work of any kind has begun.
