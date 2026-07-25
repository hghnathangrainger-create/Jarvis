# Phase 100 Planning Gate — Intelligence Core V1 Gap Audit and Next Foundation Selection

**Status: planning only. Not committed. No production code, test, or migration changes were made during this pass.**

## 0. Amendment (supersedes Sections 12–23 below)

The primary objective (Section 12) is provisionally accepted: the missing
Intelligence Core link is `Remember → Context`, and the single Phase 100
objective is **Verified Action Context V1**. Before this pass's amendment,
Sections 12–23 bundled a "Candidate A" typed-verification prerequisite in
with Verified Action Context on the assumption it would be convenient to
build both together. Section 12A below audits the actual proposed data
path and proves that assumption false: Verified Action Context V1 needs
**no** change to `PlanStep.verification_expected_value` or
`WorkflowEngine`. Sections 12–23 are therefore replaced in place with the
corrected, single-objective scope. Nothing above Section 12 changes.

## 1. Repository baseline

- Current branch: `phase-4-ai-reasoning-and-write-actions`
- Current HEAD: `502202d` ("Activate and close Phase 99 live schedule compound workflow")
- Recent commit chain: `502202d` (Phase 99 Batch 3/closure) → `e019ba8` (Phase 99 Batch 2) → `f7b956f` (Phase 99 Batch 1) → `fa2f983` (Phase 99 planning gate) → `e8183d4` (Phase 98 Batch 3/closure) → `a5cfa58` → `867a959` → `ef7ede0`
- `git status`: clean except `?? dashboard_test.txt`
- `dashboard_test.txt`: confirmed pre-existing, untracked, untouched
- No Phase 100 artifacts exist anywhere in the repository prior to this document
- Phase 99 completion documentation (`docs/phase_99_completion_report.md`, `docs/phase_99_second_compound_template_planning.md`) confirmed committed in `502202d`
- Baseline health check: `tests/unit/test_phase98_batch3_live_compound_activation.py` + `tests/unit/test_phase99_batch3_live_schedule_compound_activation.py` → **61 passed, 0 failed**

Repository matches the authoritative closure state exactly. No stop condition triggered.

## 2. Current Intelligence Core call flow

For the AI-driven `ask jarvis to: <request>` path (the only path that exercises the full loop):

1. **Context** — `intelligence/context.py::ContextAssembler.assemble()` — reads `MemoryManager`/`ProjectStateStore` only, builds a bounded `AssembledContext`.
2. **Prompt preparation** — `ai/prompt_builder.py::PromptBuilder` — combines the trusted system instruction, the untrusted `AIContextBlock`, and the live request into one `AIRequest`, scanning for injection patterns.
3. **Structured tool/compound selection** — `intelligence/planning.py::select_tool()` — calls the real `AIRouter`, then `peek_compound_decision()` discriminates `execute` / `execute_sequence` / `unsupported`.
4. **Parsing** — `intelligence/structured_output.py::parse_tool_selection()` (single) or `intelligence/compound_structured_output.py::parse_compound_tool_selection()` (compound) — strict JSON schema validation, no coercion.
5. **Grounding** — `intelligence/grounding.py::ground_decision()` (single) or `intelligence/compound_grounding.py::ground_compound_decision()` / `intelligence/schedule_compound_grounding.py::ground_schedule_compound_decision()` (compound) — deny-only, deterministic, request-text-only re-confirmation.
6. **Trusted plan construction** — `_build_write_and_verify_workflow_plan()` / `_build_phase_update_verify_show_workflow_plan()` / `_build_schedule_enable_verify_show_workflow_plan()` in `intelligence/planning.py` — hand-authored, fixed-shape `Plan`/`PlanStep` construction; the AI never sees or configures Steps 2/3.
7. **Exact plan recognition** — `core/compound_workflow.py::matches_compound_plan_shape()` / `core/schedule_compound_workflow.py::matches_schedule_compound_plan_shape()` — structural fingerprint checks against already-durable state, never model output.
8. **Risk-tier and approval handling** — `SecurityManager.classify_action()` (deterministic keyword rules) → `ApprovalManager.create_request()`/`approve()`/`decline()`.
9. **Durable handoff** — `PendingApprovalStore` (`PendingApprovalHandoffStatus`: PENDING → APPROVED_UNCONSUMED → CLAIMED → CONSUMED/CLAIM_INTERRUPTED, or DECLINED/EXPIRED).
10. **Execution** — `WorkflowEngine.run()`/`resume()` → `ToolExecutor.execute()` (the sole security gate).
11. **Verification** — either `intelligence/verification.py`'s typed comparison functions (single-capability two-step workflows) or `WorkflowEngine._verification_gate_failure_reason()` (compound workflows, string-only).
12. **Result translation** — capability-specific translators in `core/orchestrator.py` (single-capability) or `core/compound_workflow.py`/`core/schedule_compound_workflow.py`'s six-outcome translators (compound).
13. **Final response** — `JarvisResponse`, rendered by `ui/cli.py::format_response()`.
14. **Memory/durable state updates** — only ever user-explicit `MemoryManager.save()` calls, or the durable execution-bookkeeping tables (`WorkflowHistoryStore`, `ApprovalHistoryStore`, the two compound progress stores) — **never reconnected to stage 1**.

### Per-stage summary

| Stage | Responsible code | Trusted vs AI-controlled | Deterministic? | Durable evidence? | Restart-safe? |
|---|---|---|---|---|---|
| Context | `intelligence/context.py` | Trusted read of durable state; combined into UNTRUSTED block | Yes, fully | N/A (read-only) | N/A |
| Prompt prep | `ai/prompt_builder.py`, `ai/router.py` | Trusted instruction + untrusted context | Yes (assembly); model call itself is not | N/A | N/A |
| Selection | `intelligence/planning.py` | AI proposes; every consequence is trusted-validated after | No (AI call) | No | N/A |
| Parsing | `structured_output.py` / `compound_structured_output.py` | Deny-only validation of AI output | Yes | No | N/A |
| Grounding | `grounding.py` / `compound_grounding.py` / `schedule_compound_grounding.py` | Deny-only, request-text-only | Yes | No | N/A |
| Plan construction | `planning.py` builders | 100% trusted, hand-authored | Yes | No (until paused) | N/A |
| Plan recognition | `core/compound_workflow.py` / `core/schedule_compound_workflow.py` | 100% trusted | Yes | Reads durable progress | Yes |
| Risk/approval | `security_manager.py`, `approval_manager.py` | 100% trusted | Yes | Yes (`PendingApprovalState`, `ApprovalHistoryEntry`) | Yes |
| Execution | `workflow/engine.py`, `tools/executor.py` | 100% trusted | Yes | Yes (`WorkflowHistoryEntry`, `PausedWorkflowState`) | Yes |
| Verification | `intelligence/verification.py` (typed) vs `workflow/engine.py` gate (string-only) | 100% trusted | Yes | Read from ToolResult | Yes |
| Translation | orchestrator translators | 100% trusted | Yes | Reads durable evidence | Yes |
| Response | `JarvisResponse` / `ui/cli.py` | 100% trusted | Yes | N/A | N/A |
| Remember | `MemoryManager` (user-explicit only) | 100% trusted, but **disconnected** | Yes | Yes, but never read back into context | N/A |

Support level: single actions — full coverage across the whole catalogue. Two-step verified single-capability workflows — 4 (focus/phase update, schedule enable/disable). Exact compounds — exactly 2 (ProjectState, schedule). No broader/generic multi-step behavior exists anywhere.

## 3. Context audit

`ContextAssembler` (`intelligence/context.py`) is the **entire** context surface. It has exactly two sources: `ContextSource.MEMORY` and `ContextSource.PROJECT_STATE`. Confirmed by direct reading, not inference.

**What's missing, concretely:**
- No schedule context (a request like "check the enabled state of schedule 5" gets zero context about that schedule's history).
- No conversation/request history context — each request is assembled in total isolation from any prior turn.
- No approval/workflow history context.
- No Prompt Studio-specific context (though the ProjectState formatter deliberately reuses Prompt Studio's own honesty disclosures).
- No explicit time/environment context beyond whatever `ProjectState.last_updated` implies.

**What's already solid:**
- Freshness is honestly represented: `_format_last_updated()` renders `"not recorded yet"` or a real timestamp; `_field_or_fill_in()` renders `"[FILL IN]"` for unset fields — stale/absent context is always distinguishable, never silently blank.
- Every `ContextItem` is `ContentTrust.UNTRUSTED` by construction — there is no code path that can produce a trusted context item, so cross-subsystem influence on tool selection is already safety-bounded by the same mechanism that already protects memory content.
- Context is bounded by two independent, fixed character budgets (500/item, 500 for ProjectState, 2,500 for memory, max 5 memory items) — no unbounded growth is possible.
- **Context is assembled identically** for the advisory `ask jarvis:` path and the tool-selection `ask jarvis to:` path (both single-capability and compound) — the same `ContextAssembler.assemble()` call, confirmed by tracing `core/orchestrator.py`'s dispatch for both commands.

**Answering the audit questions directly:**
- *Can Jarvis reason about the user's current situation, or mostly only the current command?* Mostly only the current command plus a fixed snapshot of ProjectState/memory — no session/turn continuity exists at all.
- *Does Jarvis know what it just did?* **No.** `WorkflowHistoryStore`/`ApprovalHistoryStore`/both compound progress stores are never imported by anything under `intelligence/` or `ai/` (confirmed by a repository-wide grep — zero hits).
- *Does Jarvis know whether previous work is paused, failed, or awaiting approval?* **No**, for the same reason.
- *Could stale manually maintained ProjectState data cause a false plan?* Only in the same way it already could for the two-step ProjectState workflows today — this is a pre-existing, disclosed characteristic (the honesty banner already exists specifically because staleness is expected), not a new risk this audit introduces.
- *Is context assembled consistently for single-capability and compound decisions?* Yes, confirmed.

This is the single largest, most concrete gap in the whole loop: durable evidence of Jarvis's own recent actions already exists in four separate tables, and none of it is reachable from the reasoning/selection path.

## 4. Intent/planning audit

Jarvis **selects from fixed shapes; it does not plan.** Every executable outcome — single capability, two-step verified workflow, or three-step compound — is a hand-authored, pre-existing `Plan`/`StructuredPlan` shape the trusted code assembles; the AI only ever picks a discriminator (`execute` / `execute_sequence` / `unsupported`) and, for `execute`, a bounded set of arguments that are then independently re-grounded against the request text. This is a deliberate, load-bearing design choice (never AI-generated plans) and the audit does not challenge it.

- The AI cannot "explain why" it selected a capability in any exposed way — there is no captured rationale, confidence, or alternative-candidates record anywhere in the pipeline. `ParsedToolSelection`/`ParsedCompoundToolSelection` carry only the decision, the capability id(s), and arguments.
- Ambiguity is not represented explicitly as a distinct concept — an ungrounded selection collapses into one of a small number of generic refusal messages (`UngroundedReason`/`CompoundUngroundedReason` values), which are logged internally but the **user-facing** message is deliberately generic (`_ask_jarvis_to_ungrounded_message()`), never naming the specific competing interpretation.
- No confidence score or competing-interpretation concept exists anywhere.
- Unsupported multi-step requests fail honestly: `PlanningOutcomeKind.UNGROUNDED_COMPOUND_SELECTION`/`INVALID_COMPOUND_OUTPUT` never fall back to a single-capability interpretation (verified directly in Phase 98/99's own isolation tests).
- Compound parsing/grounding is **structurally shared** (`compound_structured_output.py`'s parser and `compound_grounding.py`'s clause-splitting/signature-matching helpers are fully generic and reused verbatim by `schedule_compound_grounding.py`) — only the per-template allowlist and the per-template argument-attribution helper (string vs numeric marker table) differ. This is not yet "duplicated paths" in the harmful sense; it is two thin, parallel modules sharing one real engine.
- Adding a **third** safe compound today would require: one more allowlist module (~30 lines, mostly copy-paste of the schedule module's own shape), one more trusted plan builder, one more exact-fingerprint recognizer, one more progress store/table, one more observer, one more six-outcome translator, and one more `_RecognizedCompoundKind` branch in `core/orchestrator.py` plus one more recovery stack in `main.py`. This is real, measurable duplication — not disproportionate for a second template, but the linear per-template cost is now empirically known (Batch 1+2+3 together were roughly 4,800+2,700+2,400 lines across the three batches) and would keep growing linearly with no shared abstraction.
- Plan representation (`PlanStep`) can already express a bounded future workflow safely (`requires_verified_predecessor`, `verification_field_name`, `verification_expected_value`) — the concept generalizes; only the **verification value's type** does not.
- **String-only verification expectations are a real, already-triggered architectural blocker** — not hypothetical. See Section 8 for the concrete evidence.
- `enabled_str` is honestly a **temporary compatibility bridge**, not an acceptable permanent boundary: it exists solely because `WorkflowEngine._verification_gate_failure_reason()` hardcodes `isinstance(actual_value, str)` (`workflow/engine.py:1425`), forcing every future non-string verified compound step to invent its own shadow string field. A third compound needing, say, integer or enum verification would need a third such shadow field.

## 5. Tool-selection and grounding audit

- Capability signatures (`intelligence/grounding.py::_IntentSignature`) are `(action_tokens, domain_tokens, qualifier)` tuples matched against the whole request text. Selection **does** depend heavily on wording — grounding is deliberately literal (exact clause/argument-span matching), which is the entire safety property, not an accidental side effect.
- Valid natural variants are sometimes rejected by design (documented precedent: `_extract_numeric_argument_span` requires the id to trail its clause, which is why the schedule grammar had to be redesigned during Phase 99 Batch 1 rather than accepting the more natural "schedule 5 is enabled" phrasing). This is a real, disclosed cost of the current literal-grounding approach, not a bug.
- Permissive wording would create unsafe collisions: confirmed concretely — `SCHEDULE_SHOW_ENABLED_STATE`'s own signature deliberately avoids `"show"`/`"list"` action tokens specifically because `SCHEDULE_LIST` already claims them; any move toward fuzzier matching would need a collision-resolution mechanism that does not exist today.
- Capability-signature uniqueness is currently maintained **by hand, per addition** — every new capability's own construction required a manual audit against every existing signature (documented in this session's own history for `SCHEDULE_SHOW_ENABLED_STATE`). This does not yet break at 12 signatures but has no automated collision-detection test at catalogue-construction time (only per-capability, per-addition manual tests). This is a maintainability risk as the catalogue grows, not yet a defect.
- Bounded pronoun/reference support ("that schedule") is explicitly *not* supported and would require either (a) session-level state the current stateless request model has no place for, or (b) an untrusted inference step — the same reasoning that led Phase 99 Batch 1 to reject pronoun inference for cross-step schedule-id agreement applies identically here. Any future support would need a trusted, structural binding mechanism (e.g., "the previous request's own ground truth id" sourced from durable state), not model inference.
- The selection pipeline cannot currently produce an explicit "ambiguous — did you mean X or Y" outcome; `SELECTED_CAPABILITY_NOT_UNIQUE_MATCH` exists as an internal reason code but is surfaced to the user as the same generic refusal as every other ungrounded case.
- The two compound-specific grounding paths (`compound_grounding.py`, `schedule_compound_grounding.py`) have **not** drifted apart in the harmful sense — `schedule_compound_grounding.py` deliberately imports and reuses `compound_grounding.py`'s own generic helpers (`CompoundTemplate`, `CompoundGroundingResult`, `CompoundUngroundedReason`, `_ground_clause_signature`, `_reject`, `_split_clauses`) rather than re-deriving them. The one genuine, disclosed divergence is the argument-attribution helper (string vs. numeric marker table), which is inherent to the underlying argument types, not accidental drift.

## 6. Risk/approval audit

- Risk is attached to the exact trusted capability and its already-validated arguments — `SecurityManager.classify_action()` runs on the tool's own fixed `action_for()` string, never on raw model output, both at preflight and at real execution time (re-derived fresh each time, never trusted from the `Plan`'s own cached `action` field).
- Approval summaries are accurate but **generic**: `action_for()` strings are fixed, capability-level literals (e.g., `"enable schedule"`) that never embed the concrete argument value (confirmed directly: neither the ProjectState nor the schedule compound's approval text embeds the literal phase value or schedule id — this is consistent, pre-existing behavior across the whole codebase, not a defect introduced by either compound). The concrete argument is visible only in the rendered `Plan.steps[].description`/CLI step listing, not the approval action/reason text itself.
- One approval always remains bound to exactly one plan; the two compound builders both preflight all three steps before any approval is shown, and `establish_compound_progress_or_isolate()`/`establish_schedule_compound_progress_or_isolate()` both run before the approval is ever returned to the caller (proven directly in this session's own Phase 99 Batch 3 tests).
- Compound progress creation and approval ordering are consistent across both templates (same call order, same isolate-on-failure contract).
- Declined/expired operations are always terminalized honestly as `NOT_EXECUTED` for both templates (Phase 98 and Phase 99 both proven directly).
- Approval state is **not** available to later context/reasoning (same gap as Section 3 — `ApprovalHistoryStore`/`PendingApprovalStore` are never read by `intelligence/`/`ai/`).
- Jarvis can explain *that* approval is required and give a fixed, honest reason (`_Rule.reason` — deterministic, keyword-driven, never AI-generated) but cannot explain the *specific* consequences of this exact argument value beyond the generic capability description.
- Approval wording is already generated safely without any model interpretation — it is 100% deterministic today.

## 7. Execution/recovery audit

- The two parallel compound lifecycle implementations (`workflow/compound_workflow_progress_store.py` + `core/compound_workflow.py` for ProjectState; `workflow/schedule_compound_workflow_progress_store.py` + `core/schedule_compound_workflow.py` for schedule) are **semantically aligned** by direct construction — the schedule modules were written as line-by-line mirrors of the ProjectState modules, verified in this session. One genuine, disclosed, and intentional divergence exists: `terminalize_declined_or_expired_schedule_compound_progress()` (schedule) guards against recounting an already-`NOT_EXECUTED` row on a repeated call; `terminalize_declined_or_expired_compound_progress()` (ProjectState) does not, so its own docstring's "always returns 0 after the first call" claim is not actually enforced by its code. This was identified and deliberately left unmodified per this session's own explicit instruction — it is an accurate-count inaccuracy only; the underlying progress *state* is genuinely idempotent either way, so no double-execution or lost-state risk exists.
- Recovery ordering (`main.reconcile_claimed_handoffs()`) is not yet fragile at two templates, but it is already fully manual and linear — each template needs its own dedicated tool-registry/executor/workflow-engine recovery stack constructed inline in that one function. A third template would add a third such stack with no shared abstraction; this function would grow markedly longer and harder to review with a third compound, though it would not yet be *incorrect*.
- A third template would indeed require another fully duplicated lifecycle (table, store, observer, six-outcome translator, recognizer, recovery stack) under the current architecture — this is the concrete cost Candidate D's "hardening" framing and Candidate E's "third template" framing both need to weigh honestly.
- Durable evidence (both progress stores, `WorkflowHistoryStore`, `PendingApprovalStore`) is sufficient in principle for Jarvis to explain interrupted work — every field needed (workflow id, step-by-step status, verification outcome, handoff status) already exists durably. The gap is entirely on the consumption side (Section 3/6): nothing currently reads this evidence back into a user-facing or reasoning-facing form outside of the one-shot response translators.
- An interrupted workflow cannot currently be shown to the user or resumed *intentionally* — only automatic startup reconciliation ever touches a `CLAIM_INTERRUPTED`/`NEEDS_RECONCILIATION` row; there is no user-facing "show me what's stuck" or "resume my paused request" capability today.

## 8. Verification audit — the key finding of this audit

Two **separate, differently-typed** verification mechanisms coexist:

1. `intelligence/verification.py` (used by the four two-step single-capability verified workflows: focus/phase update, schedule enable/disable) — **already typed per field**: `verify_project_state_field()` does exact **string** equality; `verify_schedule_enabled_state()` does exact **boolean identity** (`actual is expected_enabled`, never a truthiness check). This module has supported both types since Phase 94/95.
2. `WorkflowEngine._verification_gate_failure_reason()` (used by both three-step compound workflows) — hardcoded to `isinstance(actual_value, str)` (`workflow/engine.py:1425`), unconditionally rejecting any non-string value regardless of correctness. `PlanStep.verification_expected_value: str | None` (`planner/plan_models.py:129`) enforces the same restriction at the type level.

**This mismatch already caused a real workaround.** The schedule compound's Step 2 needs to gate on a *boolean* (`ScheduleEntry.enabled`), but the compound engine's gate cannot compare a bool. Phase 99 Batch 1's resolution was to add an **additive, canonical string mirror** — `enabled_str: "true"/"false"` — to `schedule_verify_enabled_state_tool.py`'s metadata, derived from the exact same boolean in the exact same expression, purely so the string-only gate could be satisfied. This was the correct, minimal, backward-compatible fix *at the time*, but it is a workaround for a real limitation, not a coincidence — and it is now a **precedent**: the next boolean- or integer-verified compound would need to invent its own shadow string field the same way, and every future consumer of that compound's own metadata would need to remember two keys carry the same fact.

**Direct answers:**
- *Is the string-only contract now the main limitation to future verified actions?* Yes, concretely — it is the one place this whole session's own compound work needed a workaround rather than a direct mechanism.
- *Are canonical strings safe enough?* Yes, for what they cover today (exact equality, no coercion) — the workaround is not unsafe, only awkward and non-scaling.
- *Would typed scalar verification materially improve correctness?* It would remove a whole workaround category and its own future-recurrence risk; it would not change any *outcome* of the two compounds that exist today (they already work correctly), so its value is architectural/future-facing, not a current-bug fix.
- *What types would actually be needed?* Concretely, from the real catalogue today: **string** (phase/focus values) and **boolean** (schedule enabled state). No integer- or enum-verified capability exists yet, though `schedule_id` itself is an integer *argument* (not a verified *value*) elsewhere in the same templates. A minimal typed contract covering `str | bool` would already close every real gap found; supporting `int` as a third type is cheap to add at the same time since the comparison logic is identical (`isinstance` + `==`).
- *Can a typed change remain backward compatible?* Yes — every existing persisted `Plan`/`PlanStep` (in `PausedWorkflowState`, `WorkflowHistoryEntry`) stores `verification_expected_value` as a plain JSON-compatible scalar already; widening the type union from `str | None` to `str | bool | int | None` requires no migration, since JSON (and the existing dict-based `_plan_step_to_dict()`/reconstruction path) already round-trips bools and ints natively. The one code change with real teeth is `_verification_gate_failure_reason()`'s `isinstance(actual_value, str)` check, which must become a type-matched comparison (`type(actual_value) is type(expected_value)` or an explicit small type-tag) rather than a hardcoded string check.
- *Does serialization/durable-plan/workflow-restoration/tests assume strings?* Partially: `_plan_step_to_dict()`/its reverse both currently pass `verification_expected_value` through untyped (`s.get("verification_expected_value")`), so no change is needed there. The hardcoded `isinstance(actual_value, str)` check at `workflow/engine.py:1425` is the one real assumption. A handful of existing tests assert the exact string `TypeError`/rejection-message wording for a non-string actual value — these would need narrow, expected updates (not weakening) to reflect the widened contract.
- *Can verifier metadata contain contradictory values?* Not today — every existing verifier tool derives its string/bool value from one real observation in one expression (`enabled_str` is derived from the same `record.enabled` read as `enabled`, in the same line), so the two representations of one fact can never diverge. A typed contract would let the `enabled_str` mirror be *removed* entirely (the bool alone would suffice), eliminating this whole shadow-field pattern rather than merely tolerating it.
- *Should comparison remain exact rather than coercive?* Yes, unambiguously — this is a hard, load-bearing safety property already established for both existing mechanisms and this audit does not suggest weakening it.

## 9. Response audit

Jarvis can already distinguish, honestly and with durable evidence:
- action failed (`UPDATE_FAILURE`/`ENABLE_FAILURE`),
- verification mismatched (`VERIFICATION_MISMATCH`),
- verification unavailable (`VERIFICATION_UNAVAILABLE`),
- final confirmation/read failed (`FINAL_SHOW_FAILURE`),
- checkpoint interrupted (`_COMPOUND_CHECKPOINT_INTERRUPTED_MESSAGE`, identical fixed message for both templates),
- approval declined/expired (routed to `NOT_EXECUTED`, never conflated with `UPDATE_FAILURE`).

"Action may have completed" (genuinely ambiguous, e.g. `POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED`) exists as an internal reconciliation concept but has no direct user-facing translation today — it currently only ever resolves to `CLAIM_INTERRUPTED`, a "try again later" state, rather than a distinct honest message of its own. This is a minor, narrow gap, not a safety problem (it still never claims false success).

Every response is derived from durable evidence — no translator fabricates a claim from the approved/requested value; this was directly, repeatedly verified in this session's own Phase 99 tests (`TestNeverAssumesEnabledMerelyBecauseApproved`, etc.). The same event class is described consistently across the two compound domains (the schedule translator is a deliberate structural mirror of the ProjectState translator, verified side-by-side in this session). Internal implementation wording (class names, exception text, stack traces) never leaks — confirmed by dedicated tests in both compound translator test files. Final responses are honest about outcome but do not always proactively suggest a next action (e.g., a `CLAIM_INTERRUPTED` response does not tell the user "try your request again in a moment" or "this will resolve automatically on next restart" as directly as it could).

## 10. Remember audit

Direct answer: **Jarvis remembers only user-saved memories and manually-recorded ProjectState.** It does not remember verified action results, paused work, or approval history in any form reachable by reasoning or context assembly — confirmed by the same repository-wide grep in Section 3 (zero references to either history store or either progress store anywhere under `intelligence/`/`ai/`).

- Jarvis cannot currently say "I enabled that schedule earlier" from a later request — there is no mechanism connecting a completed workflow's outcome to any future request's context.
- There is no durable action-result/episode model distinct from the existing audit-log-shaped tables (`WorkflowHistoryEntry` is append-only audit history, not designed or indexed for reasoning consumption).
- Automatically storing every tool result as a memory would create real noise/privacy/trust problems: `MemoryManager` is user-curated by design (explicit `save()` calls only), and mixing in automatic entries would blur the "Nathan wrote this" trust boundary `memory_models.py`'s own docstring establishes.
- **A narrow, high-value "verified action memory" concept is concretely worth building** — not as a new memory store, but as a **read-only, bounded context view derived from already-existing durable evidence** (the two progress stores + `PendingApprovalStore`'s own current handoff statuses). This requires no new table and no new write path — only a new, bounded *reader* that Section 3's `ContextAssembler` could consume, mirroring the existing ProjectState/memory pattern exactly (a third `ContextSource` member, added only because a real consumer — this exact use case — now exists, which is precisely the bar `ContextSource`'s own docstring already sets for adding a member).
- Existing workflow/approval history **can** serve this role directly without adding another memory store — this is the central architectural insight the audit surfaces.

## 11. Candidate comparison

| Criterion | A: Typed Verification | B: Decision Explanation | C: Verified Action Context | D: Lifecycle Hardening | E: Third Compound |
|---|---|---|---|---|---|
| Impact on Jarvis intelligence | Medium (removes a workaround pattern; no new user-facing capability) | Medium (improves trust/debuggability, not capability) | **High** (closes the single largest gap: Jarvis genuinely gains situational awareness) | Low (no new capability at all) | Low (adds one more template, same shape as existing two) |
| Safety | High (preserves exact-match, adds no new inference) | High (exposes only already-computed deterministic facts) | High if read-only and bounded (no new write path, no inference) | High (audit-only) | Neutral-to-risk (every new template is new attack surface) |
| Reliability | Improves (removes shadow-field divergence risk) | Neutral | Neutral-to-improves (surfaces existing truth) | Improves slightly (fixes one docstring/behavior mismatch) | Neutral (mirrors proven pattern) |
| Support for future capabilities | **High** (removes the one concrete blocker found) | Medium | High (a real prerequisite for any future "what did you just do" capability) | Low | Low |
| Reduces future duplication | High (no more `enabled_str`-style shadow fields) | Low | Medium | Targets duplication but doesn't reduce it (audit-only) | **Negative** (adds a third full duplicated lifecycle) |
| Implementation size | Small (one type-check site + widened type union + narrow test updates) | Medium | Small-medium (one new read-only context source + tests) | Small (audit + one narrow, optional fix) | Large (full lifecycle x3) |
| Regression risk | Low (additive type widening, existing string paths untouched) | Low | Low (read-only, bounded, isolated like existing sources) | Very low (no behavior change unless the one fix is taken) | Medium (new live wiring, as Phase 99 required) |
| Migration risk | None (JSON already round-trips bool/int) | None | None (new reader only) | None | None (proven pattern) |
| Explainability | Improves (verification failures become type-honest) | **High** (this is its whole purpose) | Improves (Jarvis can cite real evidence) | Neutral | Neutral |
| Testability | High (narrow, mirrors existing verifier test patterns) | Medium | High (mirrors existing context-source test patterns) | High (already largely covered) | High (proven repeatable process) |
| User-visible value | Low-medium (indirect, via future capabilities) | Medium (only if surfaced in responses) | **High** (directly answers "does Jarvis know what it just did") | None | Medium (one more useful command) |
| Compatible with weaker models | Improves (less for the model to get right; comparison logic unchanged) | Neutral | Neutral (context assembly is deterministic either way) | Neutral | Neutral |
| Useful without more features | Yes (a foundation, even if no new compound ever uses it) | Yes (useful for any future decision) | **Yes, standalone** — improves every future request immediately, without requiring anything else to be built afterward | Yes (documentation/correctness value alone) | No (a third template alone doesn't compound with anything) |

## 12. Recommended Phase 100 objective (superseded — see 12A)

~~**Candidate C — Verified Action Context V1**, with **Candidate A's minimal type-tag widening** as a strictly necessary, small prerequisite.~~

This framing is corrected by the amendment below: Candidate A is **not** a dependency of Candidate C. The recommended objective is **Verified Action Context V1 alone** (Section 12A.2).

## 12A. Amendment — typed-verification dependency proof and exact Verified Action Context contract

### 12A.1 Proof of the typed-verification dependency, answered against the actual code

**1. Which source records would provide a boolean verified fact?**
`ScheduleCompoundWorkflowProgressRecord.step_2_verification_outcome` — a `ScheduleCompoundVerificationOutcome` enum (`VERIFIED` / `FAILED` / `UNAVAILABLE`), already typed, read directly from `workflow/schedule_compound_workflow_progress_store.py`. The record also carries the trusted `schedule_id: int` column directly (never re-parsed from JSON tool_input).

**2. Which context dataclass field would hold it?**
A field on a new, Phase-100-owned dataclass (Section 12A.4) — e.g. `VerifiedActionEntry.status: VerifiedActionStatus`, a bounded enum Phase 100 defines itself (`VERIFIED_SUCCESS` / `AWAITING_APPROVAL` / `INTERRUPTED` / `VERIFICATION_MISMATCH` / `VERIFICATION_UNAVAILABLE` / `DECLINED` / `EXPIRED`), derived one-to-one from `ScheduleCompoundVerificationOutcome`/`CompoundVerificationOutcome` plus the row's own `overall_status`/handoff status. This is a brand-new type Phase 100 owns; it has no dependency on `PlanStep.verification_expected_value`'s own type at all.

**3. Which formatter would render it?**
A new, dedicated deterministic formatter inside the proposed `intelligence/verified_action_context.py` (Section 12A.13). It renders directly from the progress record's own already-typed fields (`schedule_id: int`, `step_2_verification_outcome` enum, `updated_at: datetime`) — it never touches `WorkflowEngine`, `PlanStep`, or any live verification-gate code path.

**4. Which code path would fail if `PlanStep.verification_expected_value` remained string-based?**
**None.** The context reader never reads `PlanStep.verification_expected_value` or calls `WorkflowEngine._verification_gate_failure_reason()`. By the time a progress row exists to read, the live verification gate has already run to completion (during the original `resume()` call) and recorded its *outcome* as a typed enum on the durable row — the string-only gate is a purely internal, already-passed, execution-time mechanism with zero bearing on how a row is read back afterward.

**5. Does context construction need to execute or restore a plan, or only read durable evidence?**
Only read durable evidence. No `Plan`/`PlanStep` is ever reconstructed. The reader operates entirely on the stores' own plain, detached record dataclasses (`CompoundWorkflowProgressRecord`, `ScheduleCompoundWorkflowProgressRecord`, `PendingApprovalRecord`) — the same kind of already-detached, session-independent objects `ContextAssembler` already reads from `MemoryManager`/`ProjectStateStore` today.

**6. Could the context read model represent a boolean directly without changing `WorkflowEngine`?**
Yes, trivially. The schedule domain's "boolean fact" (verified enabled or not) is fully reconstructed from `step_2_verification_outcome`'s three-valued enum plus one fixed, already-true architectural constant: the one live schedule compound template only ever verifies `"true"` (no `SCHEDULE_DISABLE`-paired compound exists — confirmed in `core/schedule_compound_workflow.py`). `VERIFIED` under that fixed template can only ever mean "verified enabled." No raw boolean comparison is ever performed by the context reader itself.

**7. Is typed verification a true dependency, or merely a nearby architectural improvement?**
**Merely a nearby architectural improvement.** Section 8 of the base audit's finding stands on its own merits (the `enabled_str` shadow-field pattern is a real, disclosed workaround and would recur for a future non-string verified compound) — but it is causally unrelated to Verified Action Context, which was discovered by the same audit pass, not because the two are linked.

### 12A.2 Decision: **Option A — defer typed verification**

Verified Action Context V1 is built correctly and completely from existing durable evidence, using types (`ScheduleCompoundVerificationOutcome`, `CompoundVerificationOutcome`, `schedule_id: int`, `approved_phase_value: str`) that are already exactly as typed as they need to be. Typed verification is recorded as a **separate, independent future phase candidate** (unchanged from the base audit's Section 8 finding, simply decoupled from this phase). `enabled_str`, all current plan shapes, and all current live workflow behaviour are left completely unchanged by Phase 100.

Phase 100 now contains **only Verified Action Context V1**. `planner/plan_models.py` and `workflow/engine.py` are **not** in the Phase 100 file list (Section 12A.13 below replaces the earlier, now-incorrect Section 15).

### 12A.3 Why this was not obvious before auditing the exact data path

The base audit (Section 8) correctly found a real limitation and a real, already-triggered workaround. It was reasonable to *suspect* a new feature reading "verified facts" might hit the same wall. Tracing the exact, concrete field-by-field data path (12A.1) shows it does not: the compound progress stores already expose the verified *outcome* as a clean, independent enum, entirely upstream of the string-only comparison that produced it. The two findings are both real; they are simply not coupled.

### 12A.4 Exact `VerifiedActionContext` schema

```python
class VerifiedActionDomain(Enum):
    PROJECT_STATE_PHASE = "project_state_phase"
    SCHEDULE_ENABLE = "schedule_enable"

class VerifiedActionStatus(Enum):
    VERIFIED_SUCCESS = "verified_success"
    AWAITING_APPROVAL = "awaiting_approval"
    INTERRUPTED = "interrupted"
    VERIFICATION_MISMATCH = "verification_mismatch"
    VERIFICATION_UNAVAILABLE = "verification_unavailable"
    DECLINED = "declined"
    EXPIRED = "expired"

@dataclass(frozen=True, slots=True)
class VerifiedActionEntry:
    domain: VerifiedActionDomain
    target_id: str          # "project_state" (fixed singleton) or str(schedule_id)
    status: VerifiedActionStatus
    detail_value: str | None   # approved_phase_value for PROJECT_STATE_PHASE only; always None for SCHEDULE_ENABLE (fixed "enabled" semantic needs no value)
    observed_at: datetime      # the source row's own updated_at
    text: str                  # the pre-rendered, deterministic sentence (Section 12A.9)

@dataclass(frozen=True, slots=True)
class VerifiedActionContext:
    entries: tuple[VerifiedActionEntry, ...]
    truncated: bool
    notes: tuple[str, ...]
```

**Per-field documentation:**

| Field | Source table/store | Source column/evidence | Trusted? | User-controlled? | May be sensitive? | Sanitisation/bound | Freshness | Absence meaning |
|---|---|---|---|---|---|---|---|---|
| `domain` | n/a | fixed enum, one of exactly two | Yes | No | No | N/A (fixed vocabulary) | N/A | N/A |
| `target_id` | `ScheduleCompoundWorkflowProgressRecord.schedule_id` (int→str) or a fixed literal `"project_state"` | trusted int column / fixed literal | Yes | Indirectly (user named the schedule id in their own request) | No | N/A (int stringified, or fixed literal) | N/A | N/A |
| `status` | `step_2_verification_outcome` + `overall_status` + `PendingApprovalRecord.handoff_status` (see 12A.5) | derived, bounded enum | Yes | No | No | N/A (fixed vocabulary) | N/A | N/A |
| `detail_value` | `CompoundWorkflowProgressRecord.approved_phase_value` (PROJECT_STATE_PHASE only) | plain `str` column, the user's own typed phase text | Yes (the field itself); the *text* is user-authored | Yes, fully (it is the literal phase name the user requested) | Low-moderate (free text the user chose to record as a "phase name" — same trust class as ProjectState's existing context item) | Truncated to a fixed per-entry char cap (mirrors `_MAX_CHARS_PER_ITEM`); scanned by the same injection scanner as every other UNTRUSTED item | N/A | `None` for the schedule domain (no value needed) |
| `observed_at` | row's own `updated_at` | trusted timestamp column | Yes | No | No | N/A | This *is* the freshness signal | N/A (always present) |
| `text` | derived | pre-rendered sentence (Section 12A.9) | Yes | No (wording is fixed; only `target_id`/`detail_value`/`observed_at` vary) | Only via `detail_value` above | Bound by the per-entry template + `detail_value`'s own truncation | Embeds `observed_at` | N/A |

No raw database row, no arbitrary tool output, no hidden model reasoning, and no unbounded user argument is ever included. `request_id`/`workflow_id` (internal correlation identifiers) are **never** exposed — no supported V1 user action consumes them, satisfying "expose an ID only if necessary for a supported action."

### 12A.5 Source-of-truth hierarchy and conflict resolution

Exactly two durable stores are read as primary evidence: the ProjectState compound progress store and the schedule compound progress store — each is **authoritative for its own compound's step-level state**, since each row is uniquely, structurally bound to one recognized template instance (proven throughout Phase 98/99's own recognizer tests). `PendingApprovalStore`'s **current** `handoff_status` (not `ApprovalHistoryStore`) is authoritative for whether a recognized request is still awaiting a decision, claimed, declined, or expired.

`WorkflowHistoryStore` is **excluded as a V1 source entirely**: its own record (`WorkflowHistoryRecord`) deliberately carries no `tool_input` and no target-identifying field at all (confirmed directly in `storage/models.py`'s own docstring: "there is no tool_input column... deliberately excluded, by design, not oversight") — it can prove *that* a transition happened but never *which schedule id or phase value* it concerned, so it cannot supply an identity-bound `VerifiedActionEntry` and is not needed as a source when the two progress stores already carry that identity directly. `ApprovalHistoryStore` is similarly excluded from V1 — it is the append-only decision audit trail (who approved/declined and when), fully redundant with `PendingApprovalStore`'s own current `handoff_status` for this feature's purposes.

**Direct answers:**
- *Workflow history or compound progress authoritative for a compound step?* Compound progress (workflow history is not consulted at all).
- *Approval history authoritative only for approval state?* `PendingApprovalStore`'s current status is authoritative for approval/handoff state; `ApprovalHistoryStore` is not consulted in V1.
- *Workflow says completed but compound progress says interrupted?* Cannot occur in V1's actual design (workflow history is never read), but if it were, compound progress would win — it is the purpose-built, exact-fingerprint-linked record.
- *Approval is approved but execution never began (`APPROVED_UNCONSUMED`/`CLAIMED` with `step_1_status == PENDING`)?* Rendered as `AWAITING_APPROVAL`/not-yet-started — never as started or completed.
- *Handoff is `CLAIMED` but the last durable checkpoint is incomplete?* Rendered as `INTERRUPTED` — mirrors the six-outcome translator's own existing `INTERRUPTED` distinction exactly.
- *Progress is `NOT_EXECUTED` but the approval record exists (`DECLINED`/`EXPIRED`)?* Rendered as `DECLINED`/`EXPIRED` from the handoff status — both durable facts already agree; no conflict is possible here since `NOT_EXECUTED` is precisely the progress-side mirror of a declined/expired handoff.
- *Stale/partially-written combinations?* If a `PendingApprovalRecord` names a `workflow_id` that structurally should have a progress row (its own `tool_name` matches one of the two eligible templates) but no such row exists, the entry is **omitted entirely** — never guessed, never labelled with a fabricated status.
- *Omitted, labelled uncertain, or surfaced as reconciliation-needed?* Genuinely inconsistent/impossible combinations are **omitted** (fail-closed). The one already-modeled "can't confirm" state (`NEEDS_RECONCILIATION` overall status) is not a new "uncertain" category — it maps directly onto `INTERRUPTED`, since that is already this system's own honest "cannot confirm, will resolve automatically" signal.

The context **fails closed** in every case above: never approved→executed, never attempted→completed, never completed→verified, never unavailable→mismatch, never interrupted→failed, never declined/expired→tool failure. Every one of these six specific non-conversions maps to an existing, already-tested distinction in the six-outcome translators (Section 9 of the base audit) — Verified Action Context reuses the same honest vocabulary, never inventing a new one.

### 12A.6 Eligible event set

**Eligible for V1:**
- Verified ProjectState phase updates (`CompoundWorkflowProgressRecord`, `step_2_verification_outcome == VERIFIED`).
- Verified schedule-enable operations (`ScheduleCompoundWorkflowProgressRecord`, `step_2_verification_outcome == VERIFIED`).
- Currently pending approvals for either of the two compound templates (`PendingApprovalStore.handoff_status` in `{PENDING, APPROVED_UNCONSUMED}`, cross-referenced against a matching progress row).
- Interrupted/needs-reconciliation recognized compound workflows (`handoff_status == CLAIMED` with an incomplete checkpoint, or `overall_status == NEEDS_RECONCILIATION`).
- Recent verification mismatch/unavailable outcomes for either compound (`step_2_verification_outcome in {FAILED, UNAVAILABLE}`).
- Recent declined/expired compound requests (`handoff_status in {DECLINED, EXPIRED}` with `overall_status == NOT_EXECUTED`) — included specifically so Jarvis can avoid re-suggesting an identical action the user already declined, or falsely implying an expired request executed.

**Excluded from V1 (no independent justification found for including them now):** generic GREEN reads (e.g. `schedule_show_enabled_state`'s own standalone calls carry no durable "verified" concept — they are point-in-time reads, not verified writes); ordinary unverified single-tool output; memory search results (already in context via the existing memory source, not duplicated here); help/configuration reads; raw workflow errors (no identity-bound evidence, per 12A.5); old completed actions beyond the bounded recency window (Section 12A.7); dashboard-only records (no such records exist as a durable store today); malformed/inconsistent records (omitted per 12A.5).

**Verified single-capability two-step workflows (focus/phase update, schedule enable/disable) are excluded from V1.** Unlike the two compounds, these workflows have no dedicated, structured, identity-bound durable progress table of their own — their verification result is computed transiently in `core/orchestrator.py`'s own response-builders from a live `ToolResult`, and the only durable trace is `WorkflowHistoryStore`'s identity-free record (Section 12A.5). Including them in V1 would require inventing new durable evidence (out of scope — no migration, Section 12A.14) rather than reading what already exists. **V1 begins with the two verified compound domains only** — the smallest source set that proves the `Remember → Context` loop end-to-end, exactly as instructed.

### 12A.7 Deterministic selection and bounds

- **Maximum total entries:** 5 (mirrors the existing memory source's own `_MAX_MEMORY_ITEMS` precedent).
- **Priority tiers, highest first:** (1) `AWAITING_APPROVAL` and `INTERRUPTED` (both currently actionable/blocking — uncapped relative to each other, but jointly bounded by the overall max of 5); (2) most recent `VERIFICATION_MISMATCH`/`VERIFICATION_UNAVAILABLE`; (3) most recent `VERIFIED_SUCCESS`; (4) most recent `DECLINED`/`EXPIRED`.
- **Ordering within a tier:** most-recent-first, by the source row's own `updated_at`.
- **Tie-breaking:** by the source row's own primary-key `id`, descending (matches each store's own insertion order — deterministic given identical database contents).
- **Maximum age:** none, deliberately. A calendar-based cutoff would add a clock/timezone dependency with no proven need; count-based recency (bounded to 5 total, newest-first per tier) is simpler, fully deterministic, and every entry always carries its own real `observed_at` regardless of age, so staleness is never hidden.
- **Pending/interrupted priority over old successes:** yes (Tier 1 above).
- **Same-target collapsing:** yes, for *settled* facts — see Section 12A.8.

The same database contents always produce the same context order and text: every field of the ordering/tie-break/selection policy is a pure function of already-durable, already-ordered data — no wall-clock "now" is compared against anything except the bounded max-entries/tier logic, which is itself deterministic.

### 12A.8 Target identity and deduplication

- **`PROJECT_STATE_PHASE` identity:** the fixed singleton literal `"project_state"` — mirrors `intelligence/context.py`'s own existing `"project_state:current"` convention exactly (only one ProjectState record can ever exist).
- **`SCHEDULE_ENABLE` identity:** the trusted `schedule_id: int` column, read directly from the progress row — never re-parsed from `tool_input` JSON, never hashed.
- **Same-target, both settled facts** (e.g. two historical verified-enable rows for schedule 5): only the newest is retained — a later fact naturally supersedes an earlier one for the same identity, exactly like a database's own "current row" semantics.
- **Same-target, one settled + one active** (e.g. schedule 5 was verified enabled yesterday, and a new enable request for schedule 5 is awaiting approval today): **both are retained** — they are different classes of evidence (a durable past fact vs. a currently pending action) and the user benefits from seeing both ("this is what's true, and here's what's in flight").
- **Declined does not suppress an earlier success:** a declined attempt never happened; a previously verified fact durably did. Both may coexist within the bounded window.
- **Interrupted coexists with the last verified fact:** same reasoning as above.
- **Unrelated targets always remain separate:** identity is always the exact `(domain, target_id)` tuple — no cross-target collapsing of any kind.
- No generic JSON argument hashing is introduced; both domains' identity is already a plain, typed, durable column.

### 12A.9 Deterministic wording (illustrative; exact strings decided at implementation time)

| Status | Example |
|---|---|
| `VERIFIED_SUCCESS` (schedule) | `Schedule 12 was verified enabled at 2026-07-25 14:02 UTC.` |
| `VERIFIED_SUCCESS` (ProjectState) | `The project phase was verified set to "Phase 100" at 2026-07-25 14:02 UTC.` |
| `AWAITING_APPROVAL` | `A request to enable schedule 12 is awaiting approval; it has not executed.` |
| `INTERRUPTED` | `Enabling schedule 12 was interrupted after its last durable checkpoint; completion is not confirmed.` |
| `VERIFICATION_MISMATCH` | `The enable action for schedule 12 ran, but its enabled state was not verified.` |
| `VERIFICATION_UNAVAILABLE` | `Jarvis could not verify the persisted enabled state of schedule 12.` |
| `DECLINED` | `A request to enable schedule 12 was declined and was not executed.` |
| `EXPIRED` | `A request to enable schedule 12 expired and was not executed.` |

The formatter never says "I remember" (no such user-facing framing is introduced by this phase); never claims success from approval alone; never claims execution when durable evidence says unconfirmed; never states an old verified fact without its own `observed_at` timestamp attached in the same sentence.

### 12A.10 Historical-versus-current truth contract

Every `VerifiedActionEntry` is **always historical evidence**, never a current-state claim — `observed_at` is mandatory on every entry (not optional), and every `VERIFIED_SUCCESS`/mismatch/unavailable sentence embeds its own timestamp in the same sentence (Section 12A.9). **No domain has evidence strong enough to be treated as current rather than historical**: both ProjectState and a schedule's enabled flag can be changed by a means entirely outside this evidence trail (a direct future enable/disable, a direct ProjectState edit) between the observed row's own timestamp and "now," and neither store has any mechanism to detect such an out-of-band change. Tool selection may use a `VerifiedActionEntry` as relevant context, but a current read (the existing `SCHEDULE_SHOW_ENABLED_STATE`/`PROJECT_STATE_SHOW` capabilities, or a fresh verified write) remains the sole source of current truth whenever current truth is actually required — historical context never bypasses or suppresses a user's explicit request to verify again.

### 12A.11 Intelligence injection point

`ContextAssembler.assemble()` (`intelligence/context.py`) is the single, already-shared point — confirmed by the base audit (Section 3) to feed the advisory `ask jarvis:` path and the tool-selection `ask jarvis to:` path (both single-capability and compound) **identically**, via one `assemble()` call each. Verified Action Context is added as a **third, isolated, `try/except`-wrapped source** inside `assemble()`, exactly mirroring the existing ProjectState/memory pattern — never a second, separate assembly point, which would make Jarvis reason differently depending on whether a request later becomes compound (explicitly prohibited by the amendment).

Prompt Studio (`ai/prompt_studio.py`) and `PreparePromptTool` are **not** integration points for V1: Prompt Studio produces text for a user to paste into an *external* LLM session — a fundamentally different consumer and trust boundary than this system's own `AIRouter` call. Exposing durable execution evidence into a copy-pasteable external prompt is a separate, larger decision explicitly out of scope (Section 12A.17).

**Specifics:**
- **Files/classes/functions:** new `intelligence/verified_action_context.py` (dataclasses + reader + formatter, Section 12A.13); `intelligence/context.py::ContextSource` gains one new member; `ContextAssembler.__init__()` gains two new, optional collaborator parameters (the two progress stores) plus the existing `PendingApprovalStore` reference it does not currently hold; `ContextAssembler.assemble()` gains one new private `_build_verified_action_items()` step.
- **Constructor/dependency changes:** `ContextAssembler` must be constructed with the two compound progress stores and `PendingApprovalStore` — all three already exist as real, already-constructed instances in `main.py::build_orchestrator()`, so no new store is created, only new references threaded through.
- **Behaviour when stores are unavailable:** identical to the existing ProjectState/memory pattern — isolated in its own `try/except`, contributes a short, fixed, non-sensitive note (e.g. "verified action history unavailable"), never raises, never blocks the other two sources.
- **No eligible entries:** the item is **omitted entirely** (mirrors the memory source's own behavior when nothing matches — it adds a note but produces no item — rather than the ProjectState source's own "always present, even to say not-recorded-yet" behavior, since there is no meaningful "singleton" concept here).
- **Maximum rendered size:** a new, small, independent fixed character budget (proposed: 1,000 characters — comfortably covers 5 short one-line entries), never subtracted from the existing 500 (ProjectState) or 2,500 (memory) budgets.

Store failure fails safely (an isolated note, ordinary requests remain fully usable) — this already matches `ContextAssembler`'s own existing, established policy for its other two sources; no hard-failure precedent exists anywhere in this module to deviate from.

### 12A.12 Context cannot become authority (explicit proof)

- **Cannot bypass approval:** the reader only ever reads `PendingApprovalStore`'s current status; it has no reference to `ApprovalManager.approve()`/`decline()`/`claim_for_resume()` and calls none of them.
- **Cannot supply trusted tool arguments:** `VerifiedActionEntry` is consumed only as prompt text inside an `AIContextBlock`; the existing grounding pipeline (`ground_decision()`/`ground_compound_decision()`/`ground_schedule_compound_decision()`) re-derives every argument from the live request text alone, exactly as today — context text is never read as a source of arguments anywhere in `intelligence/planning.py`.
- **Cannot alter the grounded schedule id or ProjectState value:** same reasoning — grounding only ever consults `request_text` and the model's own already-parsed, already-validated arguments.
- **Cannot create a compound plan:** plan construction (`_build_schedule_enable_verify_show_workflow_plan()` etc.) takes `approved_schedule_id`/`approved_phase_value` from the already-grounded decision, never from context.
- **Cannot mark a workflow complete, satisfy a verification gate, or trigger recovery:** the reader has no reference to `WorkflowEngine`, `ToolExecutor`, or either progress store's own write methods (`mark_*`, `start_step_*`) — it is constructed with, at most, read-only access (the store classes' own `get()`/`list_all()` methods).
- **Cannot replace a live store read:** `SCHEDULE_SHOW_ENABLED_STATE`/`PROJECT_STATE_SHOW` remain the only current-truth reads; Section 12A.10 makes this explicit and testable.
- **Cannot cause a current-truth claim from historical success:** every rendered sentence embeds its own `observed_at` (Section 12A.9/10) — this is directly testable by asserting no `VERIFIED_SUCCESS` sentence omits a timestamp.

### 12A.13 Repository architecture

- New module: `intelligence/verified_action_context.py` — houses `VerifiedActionDomain`, `VerifiedActionStatus`, `VerifiedActionEntry`, `VerifiedActionContext`, a deterministic builder function (e.g. `build_verified_action_context(...)`), and the deterministic formatter.
- The builder accepts the two progress stores and `PendingApprovalStore` **by their existing narrow public interfaces** (`get()`/`list_all()`/`list_by_handoff_status()`) — it never imports a SQLAlchemy ORM model or `storage.models` directly, mirroring how `intelligence/context.py` already only ever calls `MemoryManager`/`ProjectStateStore` methods, never touching `storage.models.EpisodicMemory`/`ProjectState` directly.
- `intelligence/context.py`: `ContextSource` gains one new member; `ContextAssembler` gains the new optional collaborators and the new `_build_verified_action_items()` method, following the existing `_build_project_state_item()`/`_build_memory_items()` pattern exactly.
- **No table merge.** The four evidence areas (workflow history, approval history, ProjectState progress, schedule progress) remain four separate, unmodified stores/tables.
- **No new persistence table.** Every field `VerifiedActionEntry` needs already exists on one of the two existing progress records or `PendingApprovalRecord`.

### 12A.14 Migration conclusion

**None.** Confirmed directly: no new table, no altered table, no new column. `ContextAssembler`'s constructor signature changes (new optional parameters) but this is a Python-level dependency-injection change, not a migration — `main.py::build_orchestrator()` is the only call site needing an update to pass the already-existing store instances through.

### 12A.15 Backward-compatibility requirements

- `ContextAssembler.assemble()`'s existing return shape (`AssembledContext`) is unchanged; the new source contributes additional `items` within the existing tuple, exactly like memory/ProjectState already do.
- Every existing consumer (`build_ai_context_block()`, `AIReasoningEngine`, `select_tool()`) requires no change beyond receiving a context block that may now include one more section.
- `ContextAssembler`'s new constructor parameters must be optional (defaulting to `None`, mirroring `JarvisOrchestrator`'s own established optional-collaborator convention throughout this codebase) so every existing test/call site that constructs a `ContextAssembler` without them continues to work unchanged, with the new source simply contributing nothing (an isolated "unavailable" note, never a hard failure) when omitted.
- No change to `planner/plan_models.py`, `workflow/engine.py`, `enabled_str`, or either compound's live behaviour — all deferred per the Option A decision (12A.2).

### 12A.16 Security risks

- The new reader must never surface anything beyond what the two progress stores/`PendingApprovalStore` already durably and truthfully record — no inference, no fabrication.
- Every new `ContextItem`/`VerifiedActionEntry`-derived text remains `ContentTrust.UNTRUSTED`, scanned by the same injection scanner as every existing context item — `detail_value` (the one field carrying free user-authored text, the ProjectState phase name) is explicitly called out as the one field needing the same truncation/scanning discipline as existing memory content.
- Durable history/approval text is treated strictly as data: the allowlist approach (12A.4) means only a fixed, bounded set of typed fields is ever read — no `action`/`reason`/`tool_input` free text from `PendingApprovalRecord` is ever included in a `VerifiedActionEntry`, closing off the one place prompt-injection-style text could otherwise enter (an approval's own `reason` or `metadata` are attacker/user-influenced-adjacent fields that this design simply never reads).
- No approval or execution authority changes — this phase touches only context assembly (read-only).

### 12A.17 Explicit non-goals

- Not general long-term memory; not autonomous memory writing (`MemoryManager` remains user-explicit only).
- Not raw workflow-history injection (`WorkflowHistoryStore` is excluded as a V1 source entirely, Section 12A.5/6).
- Not a generic event-stream system — exactly two eligible domains, an allowlisted, bounded schema, never a general "history feed."
- Not an LLM-generated retrospective — 100% deterministic, trusted formatting.
- Not a dashboard expansion.
- Not a third compound workflow.
- Not a generic verification redesign — typed verification is deferred as an independent, separate future candidate (Section 12A.2), not bundled in.
- No new capability catalogue entries.
- No migration (Section 12A.14).
- No integration with Prompt Studio/`PreparePromptTool` (Section 12A.11).
- No `dashboard_test.txt` changes.
- No Phase 98/99 cleanup — the one pre-existing Phase 98 count-accuracy observation remains explicitly out of scope, unchanged from the base audit.

### 12A.18 Revised test plan

**Context construction:** no eligible records (item omitted, honest note only if a store is genuinely unavailable); one verified ProjectState action; one verified schedule action; multiple actions with deterministic ordering across all four tiers; bound enforcement (6th-most-relevant entry excluded); same-target deduplication (two settled facts for the same schedule id collapse to the newest); pending approval retained alongside an older settled fact for the same target; interrupted work; verification mismatch; verification unavailable; declined; expired; inconsistent evidence (approval references a workflow_id with no matching progress row → omitted); missing related row; store failure (each of the three stores independently); restart/new-store-instance reconstruction (same DB contents via a fresh store instance produce byte-identical entries and ordering).

**Truthfulness:** approval never becomes execution; execution never becomes verification; historical verified state is never phrased as guaranteed current state (every `VERIFIED_SUCCESS` sentence contains its own timestamp); interrupted enable is never reported as completed; `NOT_EXECUTED`/declined/expired is never reported as a tool failure; a `PendingApprovalRecord`'s own `action`/`reason`/`tool_input` text is never rendered as part of any entry (proving the allowlist is enforced, not merely intended); unsupported/ineligible action classes (Section 12A.6's excluded list) never produce an entry.

**Prompt integration:** the new context appears in the `AIContextBlock` reaching `select_tool()`'s prompt for both the single-capability and compound-decision cases identically (same `assemble()` call); ordinary request text is unchanged; empty-context behaviour (item omitted, `AssembledContext` otherwise unaffected); deterministic ordering across repeated calls with unchanged DB contents; maximum rendered size enforced; the new context cannot override or replace the live request text (`AssembledContext.request_text` remains structurally separate, exactly as today); Prompt Studio's own existing ProjectState section remains textually unchanged (proving no accidental cross-wiring).

**Regression:** Phase 98 ProjectState compound behaviourally unchanged; Phase 99 schedule compound behaviourally unchanged; ordinary tool selection unchanged when the new context is empty; approval and execution flows unchanged; no autonomous memory writes; zero new database rows ever created by this feature; no new capability catalogue entry; no new compound; no dashboard changes.

No typed-verification test section is needed (Option A) — if a future, independent phase later revisits Candidate A, it would define its own separate test section and its own separate batch acceptance boundary at that time.

### 12A.19 Revised batch structure

**Batch 1 — Dormant Verified Action Context Read Model**
- `intelligence/verified_action_context.py`: dataclasses/enums, the bounded store reader, deterministic selection/ordering/dedup, the deterministic formatter.
- No `ContextAssembler`/prompt wiring yet — fully dormant, exercised only by its own dedicated tests, mirroring this codebase's own established "dormant foundation batch" convention (Phase 98/99 Batch 1).
- No live behaviour change of any kind.

**Batch 2 — Intelligence Context Integration and Closure**
- `ContextAssembler` gains the new optional collaborators and `_build_verified_action_items()`.
- `main.py::build_orchestrator()` threads the already-existing store instances through.
- Full integration tests (Section 12A.18's "Prompt integration" + "Regression" categories).
- Documentation updates (`docs/user_guide.md` if user-visible wording changes are warranted — to be assessed at implementation time, likely minimal since this is context, not a new command).
- `docs/phase_100_completion_report.md`, formal Phase 100 closure.

No Batch 3 is anticipated (there is no "live activation" concept here — Verified Action Context is a read-only context addition, not a new execution path) but this should be confirmed, not assumed, once Batch 2's real implementation size is known — exactly as the base audit already noted.

### 12A.20 Final recommendation

**Verified Action Context V1, alone, as Sections 12A.2–12A.19 define it.** Typed verification (Candidate A) is real, valuable, and independently recorded for a future phase, but it is not a prerequisite, and bundling it in would violate the instruction not to combine large candidates for a convenience that the evidence does not actually require.

## 13–23. (superseded)

Sections 13 through 23 of the original audit are superseded in full by Section 12A above and should be read as historical draft content only.

---

**This document is pending review. It has not been committed. No Phase 100 implementation has begun.**
