# Jarvis — Phase 92 Implementation Plan

**Status:** Planning gate — awaiting explicit approval before Batch 1 begins. Amended once (§18) to extend the grounding contract from capability selection alone to also cover model-supplied executable string arguments — see §18 for the full amendment; Sections 1-17 below are preserved as the original planning record and should be read together with §18, which supersedes any conflicting detail in them (in particular §4, §6, §8, §10-14, and §16).
**Version:** Phase 92 — Intelligence Core V1 Next-Milestone Planning Gate
**Date:** 2026-07-20 (original); amended 2026-07-20

---

## 1. Current Repository Baseline

Directly verified via `git branch --show-current`, `git log --oneline -6`, and `git status --short`:

```
Branch:      phase-4-ai-reasoning-and-write-actions
HEAD:        05c4120  Close Phase 91 safe intelligence capability expansion
             1a144b4  Phase 91 Batch 2: add bounded memory search capability
             dc72a54  Fix test environment isolation before Phase 91 Batch 2
             01e21c9  Phase 91 Batch 1: add zero-argument read-only intelligence capabilities
             e9abab3  Add Phase 91 implementation plan
             84c3f06  Add Phase 90 closure docs
Full suite:  4658 passed, 3 skipped, 0 failed (verified baseline, not re-run for this
             planning-only gate — see §17 for why)
git status:  ?? dashboard_test.txt   (only entry)
```

Phase 90 (Jarvis Intelligence Core V1) and Phase 91 (Safe Intelligence Capability Expansion) are both closed. `dashboard_test.txt` was not opened, read, or interacted with — only observed via `git status --short`, per the standing constraint.

---

## 2. Architecture Inspected

Read directly from the live repository (not merely from documentation) for this planning pass:

- `intelligence/context.py` — `ContextAssembler`, `AssembledContext`, `ContextItem`, `derive_query_terms()`, character budgets, provenance/trust labelling.
- `intelligence/capability_catalog.py` — `CapabilityAdapter`, `CAPABILITY_CATALOG` (7 entries, 6 model-selectable), `build_tool_input()`, the fixed-argument and key-rename mechanisms.
- `intelligence/structured_output.py` — `parse_tool_selection()`, the strict three-key schema, generic string-argument hygiene.
- `intelligence/planning.py` — `select_tool()`, `_TRUSTED_PLANNING_INSTRUCTION`, `_preflight_capability()`, the two-step workflow builder.
- `intelligence/verification.py` — `verify_focus_update()`, confirmed hardcoded to the one `project_state_update_focus` workflow (not a generic contract).
- `core/orchestrator.py` — `_handle_ask_jarvis_request()` (advisory path, in full), `_handle_ask_jarvis_to_request()`, `_start_update_focus_workflow()`, `execute_approved()`.
- `ai/reasoning_engine.py` — confirmed the advisory path's own parser (`_parse()`) is a simple, forgiving first-line/remaining-lines split, structurally distinct from and much looser than `intelligence/structured_output.py`'s strict schema.
- `approval/approval_manager.py` — full lifecycle (`create_request`, `approve`/`decline`, timeout sweep, `reload_pending()` revalidation).
- `workflow/engine.py` — full `run()`/`resume()`/`reload_paused()` sequential engine, STOP-only policy, the fixed, narrow `_PROPAGATED_FIELDS` previous-step-propagation list.
- `ai/memory_selection.py` — four deterministic, never-AI-assisted memory-selection primitives (query/category/recency/count-bounded), each with a small, hand-maintained, never-collapsed result-state dataclass.
- `security/security_manager.py` — the `_RULES` keyword table (already inspected in Phase 91).
- `tools/builtin/memory_tool.py`, `health_check_tool.py`, `schedule_list_tool.py`, `project_state_show_tool.py`, `project_state_update_tool.py`, `project_state_verify_tool.py` — real tool implementations behind every current capability.
- `docs/phase_90_completion_report.md`, `docs/phase_90_implementation_plan.md`, `docs/JARVIS_CONTINUATION_KIT.md`, `docs/phase_91_completion_report.md`, `docs/phase_91_implementation_plan.md` — cross-checked against the above; no discrepancy found between documented and actual behavior.
- `ai/prompt_studio.py`, `project_state/project_state_store.py`, `ai/memory_ingestion.py` — class/function inventory confirmed to match their documented responsibilities (no full-text re-read needed beyond what Phase 90/91 already established).

No missing architecture, tool, schema, or behavior was invented; every claim below is grounded in one of the files above.

---

## 3. Current Intelligence Core Strengths

- **Deterministic-first routing** — `CommandRouter.match()` remains untouched and checked before any AI involvement; the AI path is only ever entered via the explicit `ask jarvis[ to]:` prefixes.
- **A genuinely strict, closed decision schema** for `ask jarvis to:` — exact three-key JSON, duplicate-key rejection at every depth, one optional fence, generic string-argument hygiene, capability-scoped argument validation. No coercion, guessing, or repair anywhere in this path.
- **A real, independent allowlist** (`CAPABILITY_CATALOG`) separate from `ToolRegistry` — a registered tool is never automatically selectable.
- **Exact-tier-match preflight** — a capability's live classification must equal its declared tier exactly (not merely "at most"), catching both over- and under-classification drift.
- **A single execution chokepoint** (`ToolExecutor`) and a single multi-step engine (`WorkflowEngine`), both fully reused, never duplicated or bypassed, for every capability including the one YELLOW write.
- **A real, durable, restart-safe approval lifecycle** — `ApprovalManager`/`WorkflowEngine` already support pause, resume, timeout, and fail-closed reload revalidation, proven end-to-end for `project_state_update_focus`.
- **Bounded, provenance-labelled, trust-separated context** — `ContextAssembler` already enforces fixed per-item/per-source character budgets, honest truncation/omission notes, and structurally prevents an assembled item from ever claiming `JARVIS_TRUSTED`.
- **A consistent, hand-maintained "never collapse distinct outcomes into one" convention** repeated across `ai/memory_selection.py`, `intelligence/planning.py`'s `PlanningOutcomeKind`, and `intelligence/verification.py`'s `VerificationOutcome` — a strong, reusable stylistic and architectural precedent.

---

## 4. Current Concrete Weaknesses

1. **No grounding check between the live request and the AI's selected capability.** Once a model response passes schema validation, catalog membership, and exact-tier preflight, it executes — regardless of whether the selected capability has any real relationship to what the live request actually asked for. A model (especially a weaker one, or one nudged by adversarial content already proven reachable via untrusted context) could select a real, validly-shaped, correctly-classified capability that simply has nothing to do with the request, and nothing today would catch it before a GREEN capability executes. (The one YELLOW capability, `project_state_update_focus`, is incidentally protected by the human approval step — but the five GREEN capabilities have zero such friction.)
2. **`intelligence/verification.py` is hardcoded to one workflow.** `verify_focus_update()` is not a reusable contract; it is a single function name-matched to one field (`"focus"`). This is *appropriate* today (there is exactly one write capability), but is a real limiter the moment a second verified write capability is ever proposed.
3. **No separate, inspectable "interpreted intent" object.** The model's structured decision *is* the intent representation — there is no intermediate "here is what Jarvis understood you to want" step independent of the capability it ultimately selected. Phase 90's own planning gate considered and explicitly deferred this (`intelligence/intent.py`/`InterpretedIntent`) for lack of a concrete consumer; that remains true today.
4. **No deterministic ambiguity signal.** If a request could plausibly match more than one capability, the model silently picks one with no representation of "this was close" anywhere in the response or trace.
5. **The advisory `ask jarvis:` path uses a materially looser, older parser** (`AIReasoningEngine._parse()` — first line is a summary, remaining lines are suggested steps, no structural validation at all) than the strict `ask jarvis to:` schema. This is a pre-existing, deliberate architectural split (advisory vs. tool-selection), not a defect, but it means any future reliability work on structured decisions should target the tool-selection path specifically, not assume the advisory path shares its guarantees.

---

## 5. Candidate Comparison

### Candidate A — Explicit Intent and Plan Contract V1

1. **Problem it solves:** makes "what Jarvis thinks you want" explicit and separate from "which capability it picked."
2. **Evidence the problem exists:** none concrete. `StructuredPlan`/`StructuredPlanStep` (single-tool) and the real `planner.plan_models.Plan`/`PlanStep` (two-step workflow) already provide an explicit, bounded, inspectable execution-step representation for every existing capability. What is genuinely missing — a free-standing `InterpretedIntent` distinct from the selected capability — has no real consumer today; Phase 90 planning already reached this exact conclusion once (`docs/phase_90_implementation_plan.md`, §9: "Deliberately not created... no real consumer exists").
3. **Existing architecture reusable:** `StructuredPlan`, `planner.plan_models.Plan`, `PlanningOutcomeKind`.
4. **Expected intelligence benefit:** speculative — would only pay off once a real consumer (disambiguation UI, multi-step planning, clarification prompts) exists.
5. **Risk:** low security risk, but real risk of unused abstraction and added surface for no behavioral gain.
6. **Foundational or surface:** would be foundational *if* a consumer existed; today it does not.
7. **Estimated size:** medium (2 batches) if attempted.
8. **Dependencies:** none blocking, but no concrete pull either.
9. **Reject now.** No concrete consumer exists; building it speculatively repeats a mistake this project has already explicitly declined to make once.

### Candidate B — Intelligence Decision Reliability V1

1. **Problem it solves:** the AI's capability selection is trusted structurally (schema + catalog + tier) but never checked against whether it actually relates to the live request.
2. **Evidence the problem exists:** confirmed directly — `select_tool()` has no step, anywhere, that compares `request_text` against the selected capability beyond what the model itself decided. `test_adversarial_memory_content_cannot_add_a_capability` proves adversarial context cannot invent a *new* capability id, but there is no equivalent test (because no mechanism exists) proving adversarial or ambiguous context cannot cause selection of a real, wrong, unrelated capability.
3. **Existing architecture reusable:** `intelligence/context.py::derive_query_terms()` (already a deterministic, tested, hand-maintained tokenizer/stopword-filter), the `PlanningOutcomeKind` enum's own "never collapse distinct outcomes" convention, `intelligence_trace` (Phase 90 Batch 3) for honest disclosure of a new refusal reason.
4. **Expected intelligence benefit:** a real, load-bearing safety property that becomes *more* valuable, not less, as weaker/cheaper models take over this path — directly matching Nathan's stated strategic priority.
5. **Security/correctness risk:** very low if scoped as a pure, additive, deterministic post-selection check (never a model-facing "confidence score"); the main risk is over-tight keyword sets causing false-refusal of a legitimately-worded request — mitigated by deliberately generous, hand-reviewed keyword sets and by requiring every existing real vertical-slice phrasing (across all 6 capabilities) to keep passing.
6. **Foundational or surface:** foundational — a defense-in-depth property every future capability inherits for free.
7. **Estimated size:** medium (2 batches).
8. **Dependencies:** none; reuses only already-existing, already-tested modules.
9. **Select.** Concrete, present-tense problem; small, reusable, safely bounded; directly reusable by every future capability without per-capability bespoke work.

### Candidate C — Verification Framework Expansion V1

1. **Problem it solves:** whether post-execution verification should be generalized beyond `project_state_update_focus`.
2. **Evidence the problem exists:** none *yet*. There is exactly one write capability in the entire Intelligence Core; every read-only capability's grounding is already the real `ToolResult` itself (Phase 90/91's own "grounded response" guarantee) — a read has nothing further to verify beyond having actually run through `ToolExecutor`.
3. **Existing architecture reusable:** `VerificationOutcome`/`VerificationResult` shapes are already generic in *type*, just not in *application*.
4. **Expected intelligence benefit:** none until a second verified write capability is actually proposed and approved.
5. **Risk:** generalizing now would be architecture for its own sake — exactly what the task instructions warn against ("Do not recommend generic verification merely for architectural appearance").
6. **Foundational or surface:** would be foundational, but only in service of a concrete future write capability that does not exist yet.
7. **Estimated size:** small-to-medium, but only meaningful bundled with a real second write capability.
8. **Dependencies:** a genuinely new, approved, verified write capability — none proposed here.
9. **Reject now, revisit only alongside a concrete new write capability proposal.**

### Candidate D — Safe Read-Only Capability Expansion

1. **Problem it solves:** more surface-area capabilities (`quarantine_list`, `workflow_history`, `approval_history`, `info`).
2. **Evidence the problem exists:** these were deferred in Phase 91 purely for conservatism (§6 of `docs/phase_91_implementation_plan.md`), not because they are unsafe — they remain genuinely low-risk, GREEN, already-tested tools.
3. **Existing architecture reusable:** the entire Phase 91 pattern (catalog entry, zero/bounded arguments, `SINGLE_TOOL` strategy) applies unchanged.
4. **Expected intelligence benefit:** low — more surface area, no new reliability property, and Nathan's own stated priority explicitly deprioritizes "capability-count growth for its own sake."
5. **Risk:** each additional model-selectable capability *increases* the surface Candidate B's grounding gap would need to cover — i.e., capability growth without Candidate B first makes the existing weakness (§4.1) larger, not smaller.
6. **Foundational or surface:** surface expansion, explicitly.
7. **Estimated size:** small (1 batch) — genuinely easy, which is exactly why it should not be mistaken for high-leverage.
8. **Dependencies:** none technically, but logically safer *after* Candidate B lands.
9. **Reject as the Phase 92 primary.** Legitimate, low-risk, and shovel-ready — a strong **Phase 93** candidate once Phase 92's grounding foundation exists to cover the larger resulting selection surface.

### Candidate E — Context Quality Foundation V1

1. **Problem it solves:** whether bounded context construction is the current largest intelligence weakness.
2. **Evidence the problem exists:** weak. Direct inspection of `intelligence/context.py` shows deterministic relevance selection (lexical-then-recency), fixed independent budgets, honest truncation/omission notes, provenance labels, and structural trust separation are *already implemented and shared* by both `ask jarvis:` and `ask jarvis to:`. No test failure, no user-reported confusion, and no code-level gap (stale-context handling, conflict handling) was found beyond what already exists.
3. **Existing architecture reusable:** all of it, already mature.
4. **Expected intelligence benefit:** low marginal benefit right now — the context layer is not where the current concrete weakness (§4.1) lives.
5. **Risk:** low, but effort here would not address the highest-leverage gap.
6. **Foundational or surface:** already foundational; further investment here is not currently the bottleneck.
7. **Estimated size:** would be small if ever needed.
8. **Dependencies:** none.
9. **Reject for Phase 92** — not because it is a bad idea in the abstract, but because repository evidence does not support it being the current bottleneck. Notably, Candidate B's own selected design *reuses* `derive_query_terms()` from this exact layer, so Context Quality's maturity is precisely what makes Candidate B cheap to build well.

---

## 6. Selected Phase 92 Milestone

**Phase 92 — Intelligence Decision Grounding and Reliability V1** (Candidate B).

This is higher-leverage than simply adding more capabilities (Candidate D) because it is a **multiplier, not an addend**: every capability that exists today, and every capability Phase 93+ might add, inherits this safety property for free, for the cost of one small, deterministic, reused-architecture check. Growing the capability count first (Candidate D) would only widen the exact gap Phase 92 closes, making a future retrofit strictly harder and riskier than building the check now, while the catalog is still small enough to hand-review completely.

---

## 7. Rejected or Deferred Alternatives

- **Candidate A** (explicit intent/plan contract) — rejected for lack of a concrete consumer, exactly as Phase 90 planning already concluded once.
- **Candidate C** (verification framework generalization) — deferred until a second real, approved write capability exists to justify it.
- **Candidate D** (more read-only capabilities) — deferred as the likely **Phase 93** direction, explicitly safer to pursue *after* Phase 92's grounding check exists.
- **Candidate E** (context quality foundation) — deferred; repository evidence shows this layer is already mature and is not the current bottleneck.

---

## 8. Exact Scope and Non-Goals

**In scope:**
- One new, deterministic, additive check in the `ask jarvis to:` decision path: after a structured decision names a valid, catalogued, non-internal capability, confirm the live request text is plausibly grounded in that specific capability before preflight/execution proceed.
- A new, honest, distinct `PlanningOutcomeKind` member for a selection that fails this check — never collapsed into `INVALID_OUTPUT` or `UNSUPPORTED`, and never silently executed.
- A small, hand-maintained, per-capability keyword/relevance set (mirroring this repository's existing `_RULES`/`_STOPWORDS`-style hand-maintained tuples), reusing `intelligence/context.py::derive_query_terms()`'s tokenization approach rather than inventing a second one.
- Honest orchestrator-level response wording and an `intelligence_trace` entry for the new refusal shape.
- Comprehensive tests (deterministic, fake-provider-based — no live API needed) covering every existing capability's real vertical-slice phrasing, adversarial-content resistance, and the new refusal path.

**Out of scope (non-goals):**
- No new capability of any kind.
- No confidence score, probability, or any AI-judged "certainty" value of any kind — the check is a deterministic, explainable, binary pass/fail, never a fabricated number.
- No change to `CommandRouter`, deterministic commands, or the advisory `ask jarvis:` path's own (separate, looser) parser.
- No change to `SecurityManager`, `ToolExecutor`, `ApprovalManager`, or `WorkflowEngine`.
- No change to `PROJECT_STATE_UPDATE_FOCUS`'s YELLOW approval flow or its durable focus verifier.
- No retries, replanning, multi-tool plans, or autonomous behavior of any kind.
- No automatic memory writes, conversation persistence, or source-code self-modification.
- No dashboard, voice, microphone, wake-word, phone, browser-control, or general computer-control work.
- No weakening of any existing validation, preflight, or approval requirement — this milestone only ever *adds* a new way to refuse, never a new way to proceed.

---

## 9. Security Model

- The new check runs **after** structured-decision parsing (so a malformed decision is still rejected first, exactly as today) and **before** `_preflight_capability()`/`SecurityManager.classify_action()`/`ToolExecutor.execute()` — it is an additional gate, never a replacement for any existing one.
- A failed grounding check produces **zero** preflight, **zero** tool execution, and **zero** approval creation — identical in blast radius to today's `INVALID_OUTPUT`/`UNSUPPORTED` outcomes.
- The check is **advisory-blocking, never advisory-permissive**: it can only ever prevent an execution that would otherwise have proceeded; it can never cause an otherwise-rejected decision to proceed.
- `PROJECT_STATE_UPDATE_FOCUS` remains additionally protected by its existing, unmodified YELLOW approval gate regardless of this new check — defense in depth, not a replacement.
- No model output ever influences the keyword/relevance sets themselves — they are static, hand-maintained, catalog-adjacent data, exactly like `SecurityManager._RULES`.

---

## 10. Proposed Architecture

- `intelligence/capability_catalog.py`: add a new field to `CapabilityAdapter`, e.g. `grounding_keywords: tuple[str, ...]` — a small, hand-reviewed, per-capability set of terms (including synonyms already used in real test phrasings and the capability's own description words). Populated for all 6 model-selectable entries; the internal-only `project_state_verify_focus` entry needs none (never AI-selected).
- `intelligence/planning.py` (or a new, small, focused module `intelligence/grounding.py` if the check's own logic and tests are large enough to warrant separation — decided during Batch 1 based on actual size, not pre-decided here): a small, pure function comparing `derive_query_terms(request_text)` (imported from `intelligence/context.py`, not duplicated) against a capability's `grounding_keywords`, returning a plain boolean or a short, honest reason string.
- `PlanningOutcomeKind`: one new member (exact name decided during Batch 1 inspection/writing — e.g. `UNGROUNDED_SELECTION`), with a `detail` string exactly like the existing `INVALID_OUTPUT` shape.
- `core/orchestrator.py::_handle_ask_jarvis_to_request()`: one new `if outcome.kind is PlanningOutcomeKind.<new>:` branch, mirroring the existing `INVALID_OUTPUT` branch's shape, with its own distinct, honest message and an `intelligence_trace` entry.
- No change to `CapabilityArgumentSpec`, `ExecutionStrategy`, `build_tool_input()`, `_FIXED_ARGUMENTS_BY_CAPABILITY`, or `_ARGUMENT_KEY_RENAMES_BY_CAPABILITY`.

---

## 11. Proposed Batch Breakdown

**Batch 1 — Deterministic Grounding Check (mechanism + unit tests)**
- Add `grounding_keywords` to every model-selectable `CapabilityAdapter`.
- Implement the grounding-check function, reusing `derive_query_terms()`.
- Add the new `PlanningOutcomeKind` member and wire it into `select_tool()` (after parsing, before preflight).
- Focused tests: real per-capability acceptance (every existing vertical-slice phrasing from Phase 90/91 tests must still pass), real per-capability rejection (a request clearly about one capability naming a different one), adversarial-content resistance (an injected memory item naming an unrelated capability must not defeat the check), structural proof the check never touches `SecurityManager`/`ToolExecutor`/`ApprovalManager`.
- Stop/report; explicit approval required before Batch 2.

**Batch 2 — Orchestrator Wiring, Grounded Refusal Response, Full Regression, Docs**
- Wire the new outcome into `core/orchestrator.py`'s response construction, with `intelligence_trace`.
- Update `docs/user_guide.md`/`tools/builtin/help_tool.py` only if the new refusal behavior needs user-facing disclosure (likely a short addition, not a rewrite).
- Full regression across every Phase 90/91 capability and the YELLOW approval/verification flow (must remain bit-for-bit unaffected).
- Full suite + Ruff + `git diff --check`.
- Stop/report; explicit approval required before Phase 92 closes.

---

## 12. Test Strategy

All tests are deterministic and fake-provider-based, requiring **no live Anthropic API credits** — directly satisfying the manual-API-limitation requirement (§15):
- Reuse the existing `_FakeAIProvider` pattern already established in `tests/unit/test_intelligence_planning.py` and `tests/unit/test_orchestrator_ask_jarvis_to.py`.
- Reuse the existing real-tool-registry, real-`SecurityManager` integration-test pattern (never mocking security classification).
- Add one new focused test module (or extend `test_intelligence_planning.py`, decided by actual size in Batch 1) plus new orchestrator-level tests for the grounded-refusal response shape.
- Full regression: every existing Phase 90/91 test file must pass unchanged (no test weakened, skipped, or deselected).
- Full suite (`poetry run pytest -q`) in the normal environment and with `AI_REASONING_ENABLED=false`, both expected to finish with zero failures, exactly as Phase 91's own closure standard.

---

## 13. Acceptance Criteria

1. Every one of the 6 model-selectable capabilities' real, existing vertical-slice request phrasing continues to pass the new grounding check unchanged.
2. A request clearly unrelated to a model's selected capability is refused before any preflight or execution, via the new, honestly-distinct `PlanningOutcomeKind`.
3. The check never fires for, nor is bypassable via, `arguments` content — only `request_text` is compared.
4. No new capability, write path, or security rule is introduced.
5. `PROJECT_STATE_UPDATE_FOCUS`'s YELLOW approval flow and durable focus verifier are provably unaffected (full regression pass).
6. Zero new production dependency; zero new persistence.
7. Full suite: zero failures, both in the normal environment and with `AI_REASONING_ENABLED=false`.
8. Ruff clean (zero new findings) on every changed file.

---

## 14. Risks and Mitigations

- **Risk: false-refusal of a legitimately-worded but unusually-phrased request.** Mitigation: deliberately generous, hand-reviewed keyword sets validated against every existing real test phrasing; the check is a coarse safety net, not a strict matcher, and its exact reason is always honestly disclosed (never a silent "unsupported").
- **Risk: keyword sets could be seen as a second, drifting source of truth alongside each capability's `description`.** Mitigation: keyword sets are reviewed alongside (not instead of) each adapter's existing `description` field during Batch 1, and a structural test can assert every declared keyword appears in, or is a reasonable synonym of, the adapter's own description text — a lightweight consistency check, not a generalized system.
- **Risk: scope creep into a "real NLU relevance model."** Mitigation: explicitly out of scope (§8); the check is pure deterministic string/token matching, nothing more.

---

## 15. Manual API-Test Limitation

The Anthropic API account configured for this repository lacks sufficient credits for a live manual acceptance pass; this remains an external account limitation, not a code defect, and no production change is proposed to work around it (per Phase 90/91's own established, unchanged position). Every test this plan requires — focused, regression, and full-suite — is deterministic and fake-provider-based, so Phase 92 can be fully implemented and verified without live API access, exactly as Phase 91 was.

---

## 16. Stop Conditions

- Stop and report before implementing if the exact real per-capability request phrasings already used in existing tests cannot be satisfied by any reasonably-sized, hand-reviewed keyword set without an unacceptable false-refusal rate.
- Stop and report before implementing if adding `grounding_keywords` to `CapabilityAdapter` is found, on inspection during Batch 1, to require any change to `intelligence/structured_output.py`'s parsing/validation logic (it should not — the new field is never AI-facing).
- Stop after Batch 2's report. Do not begin Phase 93, additional capabilities, verification generalization, or any other unrelated work without Nathan's explicit approval.

---

## 17. Note on This Planning Gate's Own Verification

This is a planning-only gate: no production or test file was modified. The full suite was not re-run for this specific commit, per the task's own instruction ("Do not run the full suite unless repository convention requires it for documentation-only planning commits") — the same convention Phase 91's own planning gate (`e9abab3`) followed. The verified baseline quoted in §1 is the real, most recently confirmed full-suite result (Phase 91 closure, `05c4120`), re-stated here, not re-executed.

---

## 18. Planning Amendment — Executable Argument Grounding

**Sections 1-17 above are preserved unchanged as the original planning record.** Direct repository inspection (below) found that the original plan's grounding contract, as written, covered only *capability selection* and left a materially identical gap open for *model-supplied executable argument values*. This section amends the plan to close that gap. This section **supersedes** any conflicting detail in Sections 1-17 (principally §4, §6, §8, §10-14, §16); anywhere this section is silent, Sections 1-17 still govern.

### 18.1 Whether argument grounding currently exists

**It does not.** Confirmed by direct inspection, not assumption:

- `intelligence/structured_output.py::_validate_arguments()`/`_validate_string_argument()` validate an argument's *type* and *hygiene* only (non-empty, non-whitespace-only, ≤500 chars, no NUL, no leading/trailing control character) — never its relationship to `request_text`. The parser has no access to `request_text` at all; it only ever sees the raw model response.
- `intelligence/planning.py::select_tool()` and `_preflight_capability()`: every use of `request_text` in this module was enumerated directly (`grep -n "request_text" intelligence/planning.py`) — it is used only to (a) send as `user_message` to the model, and (b) store verbatim as `StructuredPlan.goal`/`Plan.user_request` for disclosure. It is **never** compared against `parsed.arguments` or the constructed `tool_input` anywhere in this module.
- `intelligence/capability_catalog.py::build_tool_input()` only copies, renames, and merges fixed keys — it performs no comparison against any request text (it does not even receive `request_text` as a parameter).
- `core/orchestrator.py`'s `_start_update_focus_workflow()`/`_handle_ask_jarvis_to_request()` paths, and `MemoryTool`'s own `run()` for the `"search"` operation, contain no request-to-argument consistency check.
- A repository-wide search for `grounded`/`grounding`/`attribut`/`consisten` across every `.py` file found no match related to request-argument attribution — every "grounded" hit refers to the existing, unrelated *response*-grounding guarantee (a response is grounded in the real `ToolResult`, a completely different property).
- No existing test (`tests/unit/test_structured_output.py`, `test_intelligence_planning.py`, `test_orchestrator_ask_jarvis_to.py`, `test_orchestrator_update_focus_workflow.py`) asserts any request-to-argument consistency. On the contrary: most of `test_intelligence_planning.py`'s existing update-focus tests deliberately pair `request_text="update my focus"` with a fixed fake model value of `"a new focus value"` — two strings that share no meaningful content — precisely because today nothing checks the relationship between them; these tests exist purely to exercise workflow-construction mechanics (tier handling, step shape, preflight-mismatch handling), decoupled from content.

### 18.2 The exact uncovered risk

A capability can be genuinely relevant to a live request (and would pass the new capability-selection grounding check from §5/§6) while the specific value the model supplies for its one executable argument is fabricated, silently substituted, or altered — and nothing today would catch this before `SecurityManager` preflight, `ApprovalManager.create_request()` (for the YELLOW capability), or `ToolExecutor.execute()`. Concretely: a request asking to search memories for one subject could execute a search for an entirely different subject the model invented; a request asking to set the project focus to one value could create a real, user-facing YELLOW approval for a different focus value than the one actually requested — and if approved (reasonably, since the approval UI shows the *real* value the model supplied, not what was actually asked), the durable focus verifier would faithfully confirm that the wrong value was stored, exactly as requested of it. Verification proves the write matches what was *approved*; it was never designed to prove the approved value matches what was *originally asked for* — that is a distinct property this amendment adds.

### 18.3 Exact amended capability-grounding rule

Unchanged in mechanism from §10/§11 of the original plan, refined only in keyword selection to satisfy the explicit generic-term constraint (§18.5):

For each of the 6 model-selectable capabilities, a hand-maintained `grounding_keywords: tuple[str, ...]` of **specific, non-generic** domain terms:

| Capability | `grounding_keywords` |
|---|---|
| `PROJECT_STATE_SHOW` | `("focus", "branch", "commit", "phase", "project state")` |
| `PROJECT_STATE_UPDATE_FOCUS` | `("focus",)` |
| `HEALTH_CHECK` | `("health",)` |
| `SCHEDULE_LIST` | `("schedule", "schedules")` |
| `MEMORY_LIST_RECENT` | `("memory", "memories", "remember", "remembered")` |
| `MEMORY_SEARCH` | `("memory", "memories", "remember", "remembered")` |

A single-word keyword is matched by token membership in the request's own tokenized, casefolded terms. The one multi-word entry, `"project state"`, is matched as a literal, normalized, adjacent-phrase substring of the request text — deliberately **not** decomposed into `"project"` and `"state"` checked independently, since both of those words are on the generic-term exclusion list (§18.5) and must never grounded anything alone. A request is capability-grounded if **at least one** of its selected capability's `grounding_keywords` entries matches.

`MEMORY_LIST_RECENT` and `MEMORY_SEARCH` intentionally share the same keyword set — capability-selection grounding only needs to confirm the request is plausibly *about memory at all*; distinguishing "list recent" from "search for X" is already handled structurally (one capability takes no argument, the other requires one) and, for `MEMORY_SEARCH` specifically, further by argument-attribution grounding (§18.4).

### 18.4 Exact amended string-argument attribution rule

Applies only to a capability that declares a string argument — today, exactly `PROJECT_STATE_UPDATE_FOCUS` and `MEMORY_SEARCH`'s `value`. Runs only after that capability has already passed capability-selection grounding (§18.3); if capability-selection grounding fails, argument-attribution grounding is never reached (moot).

**Step 1 — normalize.** Both `request_text` and the argument value are independently normalized: casefold, collapse runs of internal whitespace to a single space, strip leading/trailing whitespace. This normalization is used only to *decide* attribution — the original, validated argument value is never altered; if accepted, the exact, unmodified, already-validated value proceeds into `build_tool_input()` exactly as today.

**Step 2 — primary check: exact normalized containment.** If the normalized argument value appears as a contiguous substring of the normalized request text, the argument is **accepted**. This is the common case for both real capabilities: e.g. request `"search my memories for the deployment checklist"` / value `"the deployment checklist"`; request `"update my project focus to batch 3 verification and confirm it"` / value `"batch 3 verification"`.

**Step 3 — fallback check: significant-term attribution.** If Step 2 fails, tokenize the argument value the same way `intelligence/context.py::derive_query_terms()` tokenizes (alphanumeric-run splitting, casefold) but against a **grounding-specific exclusion set**, not `derive_query_terms()`'s own `_STOPWORDS`/4-character minimum: exclude common English stopwords (reusing `intelligence.context._STOPWORDS`) **and** the explicit generic command/domain-word set from §18.5, with **no minimum token length** (unlike `derive_query_terms()`, since a short but specific value token — e.g. a version number or an acronym — must still count as real content; argument text is short, user-authored, and not a memory-relevance search string, so `derive_query_terms()`'s own 4-character/5-term memory-relevance tuning is not reused here, only its tokenizer). Call the result the value's *significant terms*.
- If the value's significant-term set is **empty** (the entire value reduces to stopwords/generic terms), the argument is **rejected** — fail closed, exactly as required: an argument with no attributable specific content can never be accepted merely because it passed hygiene validation.
- Otherwise, tokenize `request_text` identically into its own significant-term set, and **accept only if every one of the value's significant terms is present in the request's significant terms** (i.e. the value's terms are a subset of the request's terms). Any single significant term present in the value but absent from the request causes **rejection** — this is what correctly rejects a partially-overlapping-but-expanded value (e.g. value `"the deployment checklist and also delete everything"` against the same request above: `"delete"`/`"everything"` are not in the request → rejected).

**Never:** invents, paraphrases, replaces, trims, truncates, coerces, or otherwise modifies the argument value. The rule only ever answers accept/reject; the executable value is either the original, unchanged validated string, or the request is refused entirely before it is ever used.

### 18.5 Why the rules are deterministic and deny-only

Both rules are pure functions of two already-real strings (`request_text`, and — for argument-attribution — the already-validated argument value) using only casefold/whitespace/substring/token-set operations — no AI call, no embedding, no probability, no learned model of any kind, and no external state. Both rules can only ever move an otherwise-proceeding decision to a refusal; neither rule can cause an otherwise-invalid decision (a malformed structured output, an unsupported capability, a hygiene-failing argument) to become valid. This mirrors the existing, load-bearing `_preflight_capability()` exact-tier-match design precedent exactly: a new, independent gate that can only narrow, never widen, what proceeds.

### 18.6 How generic-term false positives are prevented

A new, explicit, hand-maintained exclusion set — distinct from, and applied in addition to, `intelligence.context._STOPWORDS` — is defined for grounding purposes only:

```python
_GENERIC_GROUNDING_TERMS: frozenset[str] = frozenset({
    "show", "list", "get", "find", "search", "update", "change", "set",
    "jarvis", "project", "state",
})
```

This set is applied identically in two places: (a) implicitly, by construction, in the hand-chosen `grounding_keywords` table (§18.3), which contains none of these words as standalone entries (the sole multi-word exception, `"project state"`, is matched only as an adjacent phrase, never via either word alone); and (b) explicitly, in the significant-term tokenizer (§18.4 Step 3), so a value consisting only of these words plus stopwords (e.g. a hypothetical adversarial value like `"update the project state"`) reduces to an empty significant-term set and is rejected outright by Step 3's fail-closed rule, never accepted merely because a generic word happens to match. This directly satisfies the requirement that "a model-supplied argument containing unrelated meaningful terms must be refused even when one generic word overlaps," and its inverse — a generic word alone must never be sufficient to accept anything.

### 18.7 How false refusals are bounded and tested

- **Capability-selection grounding**: every existing real vertical-slice phrasing already used in Phase 90/91 tests (`"show my project state"`, `"update my project focus to X"`, `"check jarvis's health"`, `"show my schedules"`, `"what have I asked you to remember recently"`, `"search my memories for the deployment checklist"`) is re-verified in Batch 1 to satisfy its own capability's `grounding_keywords` — none require a wording change.
- **Argument-attribution grounding**: direct inspection of `tests/unit/test_intelligence_planning.py` found that most existing update-focus tests use `request_text="update my focus"` paired with a fixed fake value `"a new focus value"` that shares no content with it — these two strings were never meant to be content-consistent (they test workflow mechanics, not content fidelity). **Batch 1 must update these specific test fixtures'** `request_text` (not their assertions, not their intent) to genuinely contain their paired fake value — e.g. `request_text="update my focus"` becomes `request_text="update my focus to a new focus value"` — a mechanical, low-risk, disclosed fixture change, not a behavior change. `tests/unit/test_orchestrator_update_focus_workflow.py`'s own `_REQUEST` constant (`"...update my project focus to batch 3 verification and confirm it"`) is paired, in several tests, with a fake value of `"new focus value"` (unrelated) — these fixtures need the same treatment. `tests/unit/test_orchestrator_ask_jarvis_to.py`'s `MEMORY_SEARCH` tests already use naturally consistent request/value pairs (`"search my memories for deployment checklist"` / `"deployment checklist"`) and need no fixture change. This finding is treated as an explicit, bounded, pre-identified Batch 1 task (§18.9), not a surprise regression.
- Bounded, adversarial rejection tests (§18.10) confirm the rule cannot be defeated by injected/retrieved context, since it only ever consults `request_text` and the argument value — never `AssembledContext`/memory/project-state content.

### 18.8 Updated outcome/refusal design

One new, shared public `PlanningOutcomeKind` member — `UNGROUNDED_SELECTION` — covers both failure classes, distinguished only by a deterministic, bounded `detail` string (mirroring how `INVALID_OUTPUT` already carries a bounded `detail` for many distinct parser failures without needing a separate outcome kind per reason). This is the smallest design that still supports precise testing and honest handling:

- Malformed structured output → existing `INVALID_OUTPUT` (unchanged).
- A structurally valid `"unsupported"` decision → existing `UNSUPPORTED` (unchanged).
- A structurally valid `"execute"` decision whose capability is not grounded in the request → new `UNGROUNDED_SELECTION`, `detail` naming the capability-grounding failure (e.g. `"the selected capability does not appear related to your request"`).
- A structurally valid `"execute"` decision whose capability is grounded but whose argument is not attributable to the request → new `UNGROUNDED_SELECTION`, `detail` naming the argument-attribution failure (e.g. `"the supplied value does not appear to come from your request"`) — never the raw, rejected value itself, and never any retrieved memory/context content.

Every `UNGROUNDED_SELECTION` outcome guarantees, by construction (it is returned from `select_tool()` before any of the following are ever called): no `SecurityManager.classify_action()` call beyond what capability-selection grounding itself never performs, no `ApprovalManager.create_request()`, no `ToolExecutor.execute()`, no verifier call, no write, and no memory-tool result of any kind is ever produced or exposed.

### 18.9 Updated Batch 1 and Batch 2 scope

**Batch 1 — Deterministic Grounding Contract (capability + argument), internal only:**
- Add `grounding_keywords` to every model-selectable `CapabilityAdapter` (table in §18.3).
- Implement capability-selection grounding (token/phrase matching against `grounding_keywords`).
- Implement argument-attribution grounding (normalized containment + significant-term fallback, §18.4), applied only to `PROJECT_STATE_UPDATE_FOCUS`/`MEMORY_SEARCH`.
- Add the new `_GENERIC_GROUNDING_TERMS` exclusion set (§18.6).
- Add the new `UNGROUNDED_SELECTION` `PlanningOutcomeKind` member and wire both grounding checks into `select_tool()`, in this order: parse → (if EXECUTE) capability-selection grounding → (if the capability declares a string argument) argument-attribution grounding → existing `_preflight_capability()` → existing plan construction. No orchestrator-level response wiring beyond the minimum needed to construct/return the new outcome.
- Update the pre-identified, content-decoupled test fixtures in `test_intelligence_planning.py`/`test_orchestrator_update_focus_workflow.py` (§18.7) so their `request_text`/value pairs are mutually consistent, preserving every existing test's original assertion intent.
- Focused unit and adversarial tests (§18.10).
- Stop/report; explicit approval required before Batch 2.

**Batch 2 — Orchestrator Integration, Grounded Refusal, Full Regression, Docs** (unchanged in shape from the original plan's §11, extended to also prove the argument-attribution path):
- Wire `UNGROUNDED_SELECTION` into `core/orchestrator.py`'s response construction, with an `intelligence_trace` entry, using a distinct, honest, non-sensitive message per `detail` class.
- Prove structurally and behaviorally: no preflight, no approval, no execution, no verification, no memory-result exposure on either refusal path.
- Full regression across every Phase 90/91 capability, including `PROJECT_STATE_UPDATE_FOCUS`'s real YELLOW approval and durable focus-verifier flow with a *legitimately grounded* focus value (must remain bit-for-bit unaffected).
- Update `docs/user_guide.md`/`tools/builtin/help_tool.py` only if the new refusal needs user-facing disclosure.
- Full suite + Ruff + `git diff --check`.
- Stop/report; explicit approval required before Phase 92 closes.

Two batches remain sufficient. Repository inspection found no evidence this is unsafe or unrealistic: both grounding checks are small, pure functions reusing only already-existing tokenization/normalization patterns, the required test-fixture updates are mechanical and already precisely identified (§18.7), and no new persistence, dependency, or cross-cutting architectural change is introduced.

### 18.10 Updated required tests

**Capability grounding** (extends §12 of the original plan): relevant phrasing accepted for every one of the 6 capabilities using their real vertical-slice test phrasing; a request clearly about one capability with a different capability_id selected is rejected; a request containing only generic words (`"show"`, `"update"`, `"jarvis"`, `"project"`, `"state"` in isolation, never as the `"project state"` phrase) never grounds any capability; a request genuinely about one capability's domain does not ground an unrelated capability even when the model selects it; an adversarial memory/context item naming an unrelated capability's own domain words cannot ground a selection absent from `request_text` itself (the check never consults `AssembledContext`).

**Argument grounding**, for `MEMORY_SEARCH`: a value attributable via exact containment is accepted; a value attributable only via significant-term subset (different case/punctuation/order) is accepted; a wholly model-invented, unrelated value is rejected; a value that is a superset of request content (contains extra, unrelated significant terms) is rejected; a value reducing entirely to stopwords/generic terms is rejected (fail-closed); rejection is proven to cause zero `MemoryTool` invocation and to expose zero memory content in the response or trace.

**Argument grounding**, for `PROJECT_STATE_UPDATE_FOCUS`: a value attributable to the request is accepted through to a real pending YELLOW approval, exactly as today; a different or expanded model-invented value is rejected with zero `ApprovalManager.create_request()` call (proven via `approvals.list_pending() == []`); the existing, real, legitimately-grounded YELLOW approval → resume → write → durable focus-verification flow (`tests/unit/test_orchestrator_update_focus_workflow.py`) is fully re-run and must remain unaffected once its fixtures are updated per §18.7.

**Structural safety**: grounding is proven (via direct call-order assertions and/or structural AST checks, mirroring this repository's existing `test_no_direct_tool_run_call_anywhere_in_planning_module` pattern) to run after parsing/argument-hygiene validation and before `_preflight_capability()`/`ApprovalManager`/`ToolExecutor`; grounding is proven to only ever narrow (never widen) an outcome — a decision already invalid for any other reason is never made valid by passing grounding; no second AI call is introduced anywhere in either check; no confidence score, probability, or learned-model output is introduced; `ask jarvis:`'s advisory path and its own, separate parser (`AIReasoningEngine._parse()`) are proven completely untouched.

### 18.11 Updated acceptance criteria (extends §13)

9. Every model-supplied string argument for `PROJECT_STATE_UPDATE_FOCUS`/`MEMORY_SEARCH` is proven attributable to `request_text` before it can reach preflight, approval, or execution.
10. A fabricated, substituted, or materially-expanded argument value is refused before `SecurityManager` preflight, before `ApprovalManager.create_request()`, and before `ToolExecutor.execute()` — proven by direct assertion, not inference.
11. Zero-argument capabilities (`PROJECT_STATE_SHOW`, `HEALTH_CHECK`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT`) are proven unaffected by the argument-attribution rule (it is never invoked for them).
12. The pre-identified existing test-fixture updates (§18.7) are completed with no change to any test's original assertion intent.

### 18.12 Explicit stop conditions (extends §16)

- Stop and report before implementing if any currently-existing, real vertical-slice request phrasing for any of the 6 capabilities cannot satisfy the §18.3 `grounding_keywords` table without a false refusal.
- Stop and report before implementing if any currently-existing, real vertical-slice `MEMORY_SEARCH`/`PROJECT_STATE_UPDATE_FOCUS` value/request pairing (after the disclosed, mechanical §18.7 fixture updates) still cannot satisfy the §18.4 attribution rule without a false refusal.
- Stop and report if implementing argument-attribution grounding is found, on inspection during Batch 1, to require any change to `intelligence/structured_output.py`'s parsing/validation logic, `build_tool_input()`'s signature, or the executable value itself (it should not — grounding only ever decides accept/reject on the already-validated value).
- Stop after Batch 2's report. Do not begin Phase 93, additional capabilities, verification generalization, or any other unrelated work without Nathan's explicit approval.
