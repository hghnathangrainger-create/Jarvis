# Jarvis — Phase 92 Implementation Plan

**Status:** Planning gate — awaiting explicit approval before Batch 1 begins. Amended three times: §18 extended the grounding contract from capability selection alone to also cover model-supplied executable string arguments (via whole-request significant-term attribution); §19 replaced §18's domain-keyword-only capability grounding and whole-request significant-term argument attribution with capability-specific action-and-domain intent signatures and capability-specific argument-span extraction; §20 corrects a remaining signature defect in §19 (`MEMORY_LIST_RECENT` treated the recency modifiers `"recent"`/`"recently"` as action evidence, which they are not) and finalizes every previously-approximate rule — the catalogue-wide uniqueness check, the exact six-capability signature table, the collision matrix, the exact terminal-punctuation policy, the exact negation-marker list and normalization, and the final disposition of the `"and confirm it"` suffix rule (dropped, in favor of a fixture wording update). Sections 1-17 are the original planning record; §18 and §19 are preserved as the record of prior amendments, but **§20 is the current, sole authoritative source** for the capability-grounding and argument-attribution design — where §20 differs from §18/§19, §20 governs.
**Version:** Phase 92 — Intelligence Core V1 Next-Milestone Planning Gate
**Date:** 2026-07-20 (original); amended 2026-07-20; amended again 2026-07-20; finalized 2026-07-20

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

---

## 19. Second Planning Amendment — Action-and-Domain Signatures and Argument-Span Attribution

**Sections 1-17 remain the original planning record. §18 is preserved as the record of the first amendment, but its two central mechanisms — domain-keyword-only capability grounding, and whole-request significant-term-subset argument attribution — are each shown below to admit unsafe cases, and are superseded by this section.** Where this section is silent, §18's supporting material (the outcome-kind choice, execution-order guarantees, and general test-strategy shape) still governs.

### 19.1 Why domain-keyword-only capability grounding (§18.3) was insufficient

Direct re-examination of §18.3's own design against the task's own worked example: `PROJECT_STATE_UPDATE_FOCUS`'s `grounding_keywords = ("focus",)` matches any request containing the bare word "focus" — including **"Show me the current project focus,"** a read-only request with no update intent at all. Under §18.3 alone, a model mistakenly selecting `PROJECT_STATE_UPDATE_FOCUS` for this request would pass capability-selection grounding and proceed toward a real YELLOW approval. The same structural flaw applies to `MEMORY_LIST_RECENT`/`MEMORY_SEARCH`, which share the keyword set `("memory", "memories", "remember", "remembered")` in §18.3 — a request naming only the memory *domain*, with no action evidence, could ground either capability regardless of which one is actually being asked for. **The root cause: a domain keyword identifies the subject matter, never the requested action** — and every capability pair sharing a domain in this catalog (`project_state_show`/`project_state_update_focus`; `memory_list_recent`/`memory_search`) differs precisely in the action performed on that shared subject, not the subject itself.

### 19.2 Why whole-request significant-term attribution (§18.4) was insufficient

§18.4's fallback rule accepted a model-supplied value whenever every one of its significant terms appeared anywhere in `request_text` — with no regard for the term's grammatical role. Direct testing of the task's own worked examples against this rule confirms the flaw: for **"Set the focus to testing, not deployment,"** the value `"deployment"` has exactly one significant term, `"deployment"`, which *is* present in the request — §18.4 would have **accepted** an explicitly-rejected alternative. The same failure applies to **"Search memories for school, not passwords"** (value `"passwords"` — present, wrongly accepted) and **"Do not change the focus to marketing"** (value `"marketing"` — present, wrongly accepted, and the request additionally negates the entire action). **§18.4's exact-substring primary check does not fix this either**, as the task's own inspection notes: the wrong or negated value is frequently an exact substring of the request too. The root cause: membership-in-the-whole-request proves a word was *mentioned*, never that it was *the value assigned to the argument, as opposed to a rejected alternative, an old value, or unrelated explanatory text*.

### 19.3 Exact per-capability action-and-domain intent signatures

Grounded only in language actually used in real, currently-passing tests, or in the real, already-shipped `_TRUSTED_PLANNING_INSTRUCTION` text in `intelligence/planning.py` (both inspected directly — see the exact phrasings enumerated in 19.3.1 below) — no invented synonym is included anywhere in this table:

| Capability | Required action evidence (≥1 of) | Required domain evidence | Why this combination, not domain alone |
|---|---|---|---|
| `PROJECT_STATE_SHOW` | `"show"` (token) | the adjacent phrase `"project state"` (substring, not the two words independently) | shares the `project_state` domain with `PROJECT_STATE_UPDATE_FOCUS` — domain alone cannot distinguish read from write |
| `PROJECT_STATE_UPDATE_FOCUS` | `"update"` (token) | `"focus"` (token) | same reason; `"update"` is the one action word ever used, in tests or in the shipped trusted instruction, for this capability |
| `HEALTH_CHECK` | `"check"` (token) | `"health"` or `"status"` (token) | `"status"` is not test-evidenced but *is* real, already-shipped instructional text (`_TRUSTED_PLANNING_INSTRUCTION`: "asks about Jarvis's health or status") — included on that basis, not invented |
| `SCHEDULE_LIST` | `"show"` or `"list"` (token) | `"schedule"` or `"schedules"` (token) | both action words are real: `"show"` from the real test, `"list"` from the shipped instruction text ("asks to see or list schedules") |
| `MEMORY_LIST_RECENT` | `"recent"` or `"recently"` (token), or `"list"` (token) | `"memory"`, `"memories"`, `"remember"`, or `"remembered"` (token) | `"recent"/"recently"` is the real test's own action evidence; `"list"` is real, shipped instruction text |
| `MEMORY_SEARCH` | `"search"` or `"find"` (token) | `"memory"` or `"memories"` (token) | both action words are real, shipped instruction text ("asks to search or find stored memories"); the real test uses `"search"` |

A request is capability-grounded **only if it satisfies both columns** for its selected capability — never one alone. `HEALTH_CHECK` and `SCHEDULE_LIST` still require an action word even though only one Intelligence Core capability exists per domain today: consistency across all six signatures keeps the design uniform, reviewable, and equally strict everywhere, at zero cost against real evidence (every real accepted phrasing for these two already includes its required action word anyway).

**Multi-word terms**: `"project state"` is matched as a single, adjacent, normalized-phrase substring of the request — never satisfied by `"project"` or `"state"` appearing independently or non-adjacently, exactly per the task's own instruction.

**Action collisions this design prevents, directly**:
- "Show me the current project focus." → contains `"show"` + `"focus"`, but **not** `"update"` → does not ground `PROJECT_STATE_UPDATE_FOCUS`. It also does not contain the adjacent phrase `"project state"` (it says "project focus") → does not ground `PROJECT_STATE_SHOW` either. Both capabilities are refused for this phrasing; see §19.7 for why this is a safe, deliberate compatibility boundary, not a regression.
- A genuine update-focus request (e.g. `"update my focus to X"`) contains neither `"show"` nor the phrase `"project state"` → cannot ground `PROJECT_STATE_SHOW`.
- `"what have I asked you to remember recently"` contains `"remember"` + `"recently"` → grounds `MEMORY_LIST_RECENT`; it contains no `"search"`/`"find"` → cannot ground `MEMORY_SEARCH`.
- `"search my memories for X"` contains `"search"` + `"memories"` → grounds `MEMORY_SEARCH`; it contains no `"recent"`/`"recently"`/`"list"` → cannot ground `MEMORY_LIST_RECENT`.
- A request containing only a generic action word (`"show"`, `"list"`, `"update"`, etc.) with no matching domain evidence for the selected capability grounds nothing, by construction (the domain column is mandatory).
- A request containing only a shared domain word (`"memory"`, `"focus"`, `"project"`, `"state"` in isolation) with no matching action evidence grounds nothing.

#### 19.3.1 Exact evidence sources for the table above

- Real, currently-passing test phrasings (enumerated by direct `grep` of `tests/unit/test_orchestrator_ask_jarvis_to.py`, `test_intelligence_planning.py`, `test_orchestrator_update_focus_workflow.py`): `"show my project state"` / `"show my project state please"`; `"update my project focus to batch 3 verification and confirm it"` / `"update my focus to a new focus value"` / `"update my focus"` / `"please update my focus to something new"`; `"check jarvis's health"`; `"show my schedules"`; `"what have I asked you to remember recently"`; `"search my memories for the deployment checklist"` / `"search my memories for deployment checklist"` / `"search my memories for x"`.
- The real, already-shipped `_TRUSTED_PLANNING_INSTRUCTION` text in `intelligence/planning.py` (read directly, quoted verbatim): "shows... Use this only when the request asks to **show or read** the manually-maintained **project state**"; "updates only... Use this only when the request explicitly asks to **update** the project state's **focus**"; "reports basic Jarvis system **health**... Use this only when the request asks about Jarvis's **health or status**"; "lists your configured web-search-summary **schedules**... asks to **see or list schedules**"; "lists your most recently stored **memories**... asks to see or **list recently** stored **memories**"; "searches your stored **memories**... asks to **search or find** stored **memories**".
- No word outside these two evidence sources was added to any signature.

### 19.4 Exact candidate argument-span extraction rules

Applies only to `PROJECT_STATE_UPDATE_FOCUS` and `MEMORY_SEARCH` — the two capabilities with a model-supplied string argument — and only after that specific capability has already passed its own action-and-domain signature (§19.3) and the request has already passed the negation/conflict gate (§19.6).

**Reused, not reinvented, primitive**: `core/command_router.py` already implements a real, tested, deterministic `_extract_after(text, marker)` helper for the existing deterministic `"search memories ... for <query>"` command grammar — find the first occurrence of a fixed marker phrase, return the trimmed, unquoted text after it, or empty if the marker is absent. This planning-amendment's extraction logic reuses the identical *technique* (first-occurrence marker splitting), reimplemented locally in the `intelligence/` package rather than imported across the architectural layer boundary — mirroring `intelligence/context.py`'s own established convention of locally reimplementing small, pure helpers rather than reaching into a sibling layer for a few lines of logic.

**MEMORY_SEARCH**: the fixed marker is `" for "` (case-insensitive), matching every real accepted phrasing (`"search my memories for the deployment checklist"`, `"...for deployment checklist"`, `"...for x"`) and the shipped instruction text's own framing ("searches your stored memories for text matching a query").
- If `" for "` occurs **exactly once** in `request_text`, the candidate span is the trimmed text after it.
- If `" for "` occurs **zero or more than one** times, no unambiguous span exists — refuse (detail: ambiguous argument span).

**PROJECT_STATE_UPDATE_FOCUS**: the fixed marker is `" to "` (case-insensitive), matching every real accepted phrasing (`"update my focus to X"`, `"update my project focus to X"`).
- If `" to "` occurs **exactly once**, the candidate span is the trimmed text after it, **then** one fixed, hand-maintained suffix is stripped if present: the case-insensitive trailing phrase `"and confirm it"` (with any trailing period and surrounding whitespace) — this exact phrase is the real, repeatedly-used Phase 90 vertical-slice idiom (`"update my project focus to X and confirm it"`, appearing verbatim in `tests/unit/test_orchestrator_update_focus_workflow.py`'s own `_REQUEST` constant and in Phase 90's own planning document), not a general clause-stripping grammar. This is a single, explicitly-named special case, mirroring this repository's own established preference (e.g. `WorkflowEngine._PROPAGATED_FIELDS`) for a small, fixed, named list over a generalized parser.
- If `" to "` occurs zero or more than one times, refuse (detail: ambiguous argument span).

Neither rule ever constructs, infers, or guesses a span when the marker condition is not met exactly once — a request that does not match the one supported shape for its capability is refused, never approximately parsed.

### 19.5 Exact normalization and comparison rules

1. **Normalize** both the extracted candidate span and the model-supplied value independently: casefold, collapse runs of internal whitespace to one space, strip leading/trailing whitespace, strip one trailing sentence-ending mark (`.`, `!`, or `?`) if present.
2. **Compare for exact equality.** The normalized model-supplied value must equal the normalized candidate span exactly — not merely contain or be contained by it. If equal, the argument is **accepted** and the *original, unmodified, already-validated* value (never the normalized or extracted text) proceeds into `build_tool_input()` exactly as today. If not equal, **reject** (detail: argument value mismatch).

This is deliberately stricter than §18.4's containment/subset rule: because exactly one unambiguous candidate span is now established structurally (§19.4) before comparison ever runs, exact equality is both safe and sufficient — there is no remaining role for partial/subset matching to play, and no legitimate accepted value differs from its own request span once whitespace/case/trailing-punctuation are normalized (verified directly against every real existing `MEMORY_SEARCH` test pairing below, §19.7).

### 19.6 Exact negation, conflict, and ambiguity refusal rules

A single, request-level, deny-only gate — checked once, immediately after a structured `"execute"` decision is parsed, **before** any capability-signature or argument-span logic runs, and applied uniformly to **every** capability (including the four zero-argument ones, since a negated read request is just as unsafe to silently execute as a negated write):

**Rule**: pad `request_text` with a leading and trailing space, casefold it, and check for the presence of any of the following fixed substrings: `" not "`, `"do not"`, `"don't"`, `"does not"`, `"doesn't"`, `"is not"`, `"isn't"`, `"cannot"`, `"can not"`, `"will not"`, `"won't"`, `"never"`, `"instead of"`, `"rather than"`, `"but not"`. If any is present, refuse immediately (detail: negated or conflicting request) — before capability-signature checking, before argument-span extraction, regardless of which capability the model selected.

The single-token check for bare `" not "` (padded with surrounding spaces before searching) is deliberately whole-word: it matches `"...for school, not passwords..."` and `"do not change..."` correctly, while **not** false-triggering on words that merely contain the letters "not" as a substring (e.g. "notes", "notice", "notebook") — `" notes "` does not contain the four-character sequence `" not "`, since "notes" is followed by a letter, not a space, immediately after "t".

This single, simple, request-level check is deliberately **not** a natural-language parser: it detects the *presence* of a fixed, small set of negation/contrast markers as an unconditional ambiguity signal, and never attempts to resolve which side of a "not"/"instead of"/"rather than" construction is the real intent. This directly implements "false refusal is preferable to executing or requesting approval for the wrong action": every one of the task's three worked examples (`"Set the focus to testing, not deployment"`, `"Search memories for school, not passwords"`, `"Do not change the focus to marketing"`) is refused outright by this one rule, independent of §19.3/§19.4/§19.5, before either the correct or incorrect value could ever be considered.

**Disjunction inside an argument span**: additionally, if a capability's extracted candidate span (§19.4) itself contains the padded substring `" or "`, this is treated as a second candidate ambiguity signal and refused (detail: ambiguous argument span) — e.g. `"search memories for cats or dogs"` is refused rather than guessing which term is the real query.

### 19.7 Compatibility impact on existing accepted phrasing

- **Zero impact for capability-selection grounding**: every real, currently-tested phrasing for all six capabilities was checked directly against the §19.3 table and satisfies both its required action and domain evidence, with no wording change.
- **Zero impact for `MEMORY_SEARCH` argument attribution**: both real existing value/request pairings (`"search my memories for the deployment checklist"` / `"the deployment checklist"`, and `"search my memories for deployment checklist"` / `"deployment checklist"`) already produce an exact match under §19.4/§19.5 with no fixture change.
- **Real, disclosed impact for `PROJECT_STATE_UPDATE_FOCUS` test fixtures**: direct inspection found that the large majority of `tests/unit/test_intelligence_planning.py`'s update-focus tests, and several of `tests/unit/test_orchestrator_update_focus_workflow.py`'s, deliberately pair an arbitrary `request_text` (e.g. `"update my focus"`, `"please update my focus to something new"`) with one shared, fixed fake model value (`"a new focus value"` / `"new focus value"`) that was never intended to be content-consistent — these tests exist to exercise workflow/plan-construction mechanics (tier handling, step shape, preflight-mismatch handling, durable approval/verification), not content fidelity, and today nothing checks that relationship. **Batch 1 must give each such test a mutually consistent `request_text`/value pair** (e.g. `request_text="update my focus to a new focus value"` paired with value `"a new focus value"`, or an equivalent adjustment per test) — a mechanical, disclosed, low-risk fixture change that preserves every test's original assertion and intent unchanged. This is a larger set of fixture edits than §18.7 originally estimated (nearly every update-focus test in `test_intelligence_planning.py` uses a mismatched pairing today); it remains, however, a purely mechanical string-consistency edit, not a design or behavior change, and is explicitly budgeted into Batch 1 (§19.9).
- **One deliberate new compatibility restriction, explicitly identified and justified**: the hypothetical phrasing "Show me the current project focus" (used only as the task's own illustrative example, never a real, currently-accepted phrasing in any test) would be refused under the new design (grounds neither `PROJECT_STATE_SHOW` nor `PROJECT_STATE_UPDATE_FOCUS` — see §19.3). This is judged safe and correct rather than a regression: it was never an existing accepted phrasing, and refusing an under-specified request that plausibly could mean either "show my focus" or "update my focus" is exactly the conservative behavior this milestone exists to add.
- No other currently-accepted phrasing is restricted.

### 19.8 Updated outcome design

`PlanningOutcomeKind.UNGROUNDED_SELECTION` (introduced in §18, unchanged as the public shape) remains the smallest sufficient design. Its bounded, internal `detail` string now distinguishes exactly four cases, superseding §18.8's two-case sketch:

1. **Negated or conflicting request** (§19.6) — checked first, applies to any capability.
2. **Capability action/domain mismatch** (§19.3) — the selected capability's required action-and-domain evidence is not both present.
3. **Ambiguous argument span** (§19.4/§19.6) — the capability's fixed extraction marker occurs zero or more than once, or the extracted span itself contains a disjunction marker.
4. **Argument value mismatch** (§19.5) — exactly one candidate span was extracted, but the model-supplied value does not exactly equal it after normalization.

No `detail` string ever includes the raw candidate span, the rejected model-supplied value, retrieved memory/context content, or any internal parser state — each is a short, fixed, non-sensitive category label, mirroring `ToolSelectionParseError.reason`'s own existing convention exactly. The public, user-facing refusal message (constructed in Batch 2, in `core/orchestrator.py`) is similarly fixed and generic per category, never echoing the specific rejected content, and may suggest the user restate the request more directly without guessing at their intent.

### 19.9 Updated Batch 1 and Batch 2 scope

**Batch 1 — Action-and-Domain Signatures, Argument-Span Attribution, Negation Gate (internal only):**
- Replace §18.3's `grounding_keywords` field/table with the §19.3 action-and-domain signature table (two required evidence sets per capability, matched independently).
- Implement the request-level negation/conflict gate (§19.6), applied first, before any other grounding check.
- Implement capability-specific argument-span extraction (§19.4) for `PROJECT_STATE_UPDATE_FOCUS`/`MEMORY_SEARCH`, reusing the first-occurrence-marker-splitting technique already proven in `core/command_router.py`.
- Implement the normalize-and-compare rule (§19.5).
- Refine `UNGROUNDED_SELECTION`'s `detail` taxonomy to the four categories in §19.8.
- Update the pre-identified, content-decoupled `PROJECT_STATE_UPDATE_FOCUS` test fixtures (§19.7) so every test's `request_text`/value pair is mutually consistent, preserving each test's original assertion intent unchanged; confirm both real `MEMORY_SEARCH` fixture pairings already pass unmodified.
- Focused unit and adversarial tests (§19.10).
- Stop/report; explicit approval required before Batch 2.

**Batch 2 — Orchestrator Integration, Grounded Refusal, Full Regression, Docs** (unchanged in shape from §18.9):
- Wire `UNGROUNDED_SELECTION` into `core/orchestrator.py`, with a distinct, honest, non-sensitive message per `detail` category, and an `intelligence_trace` entry.
- Prove structurally and behaviorally: zero preflight, zero approval, zero execution, zero verification, zero memory-result exposure for every refusal category.
- Full regression across every Phase 90/91 capability, including a *legitimately grounded* `PROJECT_STATE_UPDATE_FOCUS` request through real YELLOW approval and durable focus verification (must remain bit-for-bit unaffected).
- Update `docs/user_guide.md`/`tools/builtin/help_tool.py` only if the new refusal needs user-facing disclosure.
- Full suite + Ruff + `git diff --check`.
- Stop/report; explicit approval required before Phase 92 closes.

**Two batches remain sufficient.** Every mechanism specified above (signature table lookup, marker-based extraction reusing an already-proven technique, normalize-and-compare, a fixed substring-based negation gate) is a small, pure, deterministic function over two already-real strings; none requires new external dependencies, persistence, or a parser of unbounded scope. The larger-than-originally-estimated test-fixture edit set (§19.7) is still mechanical string-consistency work, not new design, and is explicitly budgeted into Batch 1 rather than discovered mid-batch.

### 19.10 Updated required tests

**Read versus write separation**: `"Show me the current project focus."` cannot ground `PROJECT_STATE_UPDATE_FOCUS` (fails action evidence: no `"update"`); a valid update-focus request (e.g. `"update my focus to a new focus value"`) grounds `PROJECT_STATE_UPDATE_FOCUS`; that same request cannot ground `PROJECT_STATE_SHOW` (fails domain evidence: no adjacent `"project state"` phrase); a rejected/refused update decision creates no YELLOW approval (`approvals.list_pending() == []`).

**Memory action separation**: `"what have I asked you to remember recently"` grounds `MEMORY_LIST_RECENT` but not `MEMORY_SEARCH` (fails action evidence: no `"search"`/`"find"`); `"search my memories for X"` grounds `MEMORY_SEARCH` but not `MEMORY_LIST_RECENT` (fails action evidence: no `"recent"`/`"recently"`/`"list"`); a request containing only `"memory"`/`"memories"` with no action word grounds neither; a request containing only a generic action word (`"show"`, `"list"`, `"search"`) with no matching domain word grounds nothing.

**Argument-span attribution, `MEMORY_SEARCH`**: the exact requested span (text after the single `" for "` occurrence) is accepted; an unrelated model-supplied fragment is rejected; a negated alternative (`"...for school, not passwords"`, model value `"passwords"`) is rejected via the negation gate before argument-span logic even runs; two or more `" for "` occurrences produce a refusal (ambiguous argument span), never a guessed span; a model-expanded value (real content plus extra invented words) is rejected by exact-equality comparison; case/whitespace/trailing-punctuation differences are accepted per the documented §19.5 normalization, and any other difference is rejected — proven by a small, explicit matrix of normalization-boundary tests; rejection is proven to cause zero `MemoryTool` invocation and zero memory-content exposure in the response or trace.

**Argument-span attribution, `PROJECT_STATE_UPDATE_FOCUS`**: the exact requested new-focus span (text after the single `" to "` occurrence, with the fixed `"and confirm it"` suffix stripped when present) is accepted through to a real pending YELLOW approval; a current/old focus value substituted for the requested one is rejected (it does not match the extracted span) with zero `ApprovalManager.create_request()` call; a negated alternative is rejected via the negation gate; two or more `" to "` occurrences produce a refusal; an invented expansion is rejected by exact-equality comparison; the existing, real, now-fixture-consistent (§19.7) YELLOW approval → resume → write → durable focus-verification flow is fully re-run and remains unaffected.

**Ambiguity and negation**: each of the task's three worked examples (`"Set the focus to testing, not deployment"`, `"Search memories for school, not passwords"`, `"Do not change the focus to marketing"`) is refused via the negation gate, proven independent of which value the (fake) model supplied; a request with two extraction-marker occurrences is refused as ambiguous; a candidate span containing `" or "` is refused as ambiguous; adversarial or retrieved `AssembledContext`/memory content cannot satisfy any grounding check, since none of the three checks (§19.3/§19.4/§19.6) ever receive `assembled_context` as an input — proven by a structural test asserting the grounding function's own signature.

**Structural safety** (unchanged in shape from §18.10, re-verified against the revised mechanism): grounding runs after parsing/hygiene validation and before `_preflight_capability()`/`ApprovalManager`/`ToolExecutor`; grounding only narrows, never widens, an outcome; no second AI call, confidence score, or embedding is introduced anywhere; `ask jarvis:`'s advisory path and its own separate parser remain untouched.

**Regression**: every real, currently-accepted Phase 90/91 request phrasing remains accepted (§19.7); the one identified, deliberate new compatibility boundary (the task's own illustrative "Show me the current project focus" phrasing, never a previously-accepted phrasing) is explicitly listed and justified in §19.7, not silently introduced.

### 19.11 Confirmation: deterministic, deny-only, pre-execution

Every mechanism in this section — the negation gate, the action-and-domain signature table, marker-based span extraction, and normalize-and-compare — is a pure function of `request_text` and (for argument attribution) the already-validated model-supplied value; none calls an AI provider, computes a similarity score, or retains state between requests. Each check can only convert an otherwise-proceeding decision into a refusal; none can cause a decision already invalid for any other reason (malformed output, an unsupported decision, a hygiene-failing argument, a tier mismatch) to become valid. All four checks run strictly after `intelligence/structured_output.py`'s existing parsing/type/hygiene validation and strictly before `_preflight_capability()`, `ApprovalManager.create_request()`, `ToolExecutor.execute()`, and `intelligence/verification.py`'s verifier — identical execution-order placement to §18, unchanged by this amendment.

### 19.12 Updated stop conditions (supersedes §18.12)

- Stop and report before implementing if any currently-existing, real vertical-slice request phrasing for any of the 6 capabilities cannot satisfy its §19.3 action-and-domain signature without a false refusal.
- Stop and report before implementing if either real `MEMORY_SEARCH` value/request pairing, or the `PROJECT_STATE_UPDATE_FOCUS` pairings after their disclosed §19.7 fixture updates, cannot satisfy the §19.4/§19.5 extraction-and-comparison rule without a false refusal.
- Stop and report if the negation-marker list (§19.6) is found, during Batch 1 implementation, to false-trigger on any currently-accepted real phrasing — none were found during this planning pass, but this must be re-confirmed against the real fixture strings at implementation time.
- Stop and report, and propose a smaller safe Phase 92 design instead, if capability-specific argument-span extraction is found during Batch 1 to require anything beyond a small, fixed, per-capability marker-splitting rule — in particular, do not expand this into a general natural-language span parser under any circumstances.
- Stop after Batch 2's report. Do not begin Phase 93, additional capabilities, verification generalization, or any other unrelated work without Nathan's explicit approval.

---

## 20. Final Planning Correction — Exact Intent Signatures and Collision Proof

**Sections 1-17 are the original planning record. §18 and §19 are preserved as the record of prior amendments. This section is the current, sole authoritative source for capability-grounding and argument-attribution design; where it differs from §18/§19, this section governs.**

### 20.1 The remaining defect in §19's `MEMORY_LIST_RECENT` signature

§19.3 accepted `"recent"`/`"recently"`/`"list"` as interchangeable action evidence for `MEMORY_LIST_RECENT`. `"recent"`/`"recently"` are recency **modifiers**, not actions — they describe *which* memories, never *what to do* with them. Concretely: **"Search memories for recent work."** contains a memory-domain word (`"memories"`) and `"recent"`, and under §19.3 this combination alone satisfied `MEMORY_LIST_RECENT`'s signature — even though the request's real action word, `"search"`, unambiguously asks for `MEMORY_SEARCH`. A model mistakenly selecting `MEMORY_LIST_RECENT` for this request would have passed §19.3's grounding check. This section corrects the signature to require a genuine listing/display action word, independent of and in addition to the recency qualifier.

### 20.2 Exact final six-capability signature table

Each capability requires **all** of: (1) action evidence, (2) domain evidence, and (3) any listed qualifier — every dimension independently, never substituting for one another. No `"e.g."` shorthand is used below; every phrasing listed is a real string this repository currently accepts or already ships as instructional text (sources given in §20.2.1).

**1. `PROJECT_STATE_SHOW`**
1. Required action token: `"show"`.
2. Required domain phrase: `"project state"`, matched only as an adjacent, normalized substring — never `"project"` or `"state"` independently.
3. Required qualifier: none.
4. Prohibited collision: must not be satisfied by any request whose action token is `"update"` (that is `PROJECT_STATE_UPDATE_FOCUS`'s own signature) merely because the word `"project"` or `"state"` appears without the adjacent phrase.
5. Exact existing phrasings satisfying it: `"show my project state"`; `"show my project state please"`.

**2. `PROJECT_STATE_UPDATE_FOCUS`**
1. Required action token: `"update"`.
2. Required domain token: `"focus"`.
3. Required qualifier: none.
4. Prohibited collision: must not be satisfied merely by the presence of `"focus"` without `"update"` (this is exactly the "Show me the current project focus" case — `"focus"` present, `"update"` absent → not grounded here); must not itself satisfy `PROJECT_STATE_SHOW`'s signature (it contains no `"show"` and no adjacent `"project state"` phrase — real phrasings say "project **focus**," never "project **state**").
5. Exact existing phrasings satisfying it: `"update my project focus to batch 3 verification"` (§20.7 fixture wording, suffix removed); `"update my focus to a new focus value"`; `"please update my focus to something new"` (paired, after §20.7's fixture-consistency pass, with a value matching its own extracted span).

**3. `HEALTH_CHECK`**
1. Required action token: `"check"`.
2. Required domain token: `"health"` or `"status"` (`"status"` is real, shipped `_TRUSTED_PLANNING_INSTRUCTION` text — "asks about Jarvis's health **or status**" — not test-evidenced but not invented either).
3. Required qualifier: none.
4. Prohibited collision: must not be satisfied by a request whose domain token is `"schedule"`/`"schedules"` (that is `SCHEDULE_LIST`'s own domain) even though both capabilities may share the generic action word `"check"`/`"show"`/`"list"` in isolation.
5. Exact existing phrasing satisfying it: `"check jarvis's health"`.

**4. `SCHEDULE_LIST`**
1. Required action token: `"show"` or `"list"` (`"list"` is real, shipped instruction text — "asks to see or **list** schedules").
2. Required domain token: `"schedule"` or `"schedules"`.
3. Required qualifier: none.
4. Prohibited collision: must not be satisfied by a request whose domain token is `"health"`/`"status"` (`HEALTH_CHECK`'s own domain); must not itself satisfy `PROJECT_STATE_SHOW`'s signature merely because both use `"show"` (`PROJECT_STATE_SHOW` additionally requires the adjacent `"project state"` phrase, which `"show my schedules"` does not contain).
5. Exact existing phrasing satisfying it: `"show my schedules"`.

**5. `MEMORY_LIST_RECENT`** (corrected, §20.1)
1. Required action token: `"show"` or `"list"` (real, shipped instruction text — "asks to see or **list** recently stored memories"; `"see"` is also shipped text but is deliberately excluded from the accepted-token set here, since as a single common word it carries a materially higher false-positive risk than `"show"`/`"list"` and is not needed once the fixture wording change in §20.7 is applied).
2. Required domain token: `"memory"`, `"memories"`, `"remember"`, or `"remembered"`.
3. **Required qualifier: `"recent"` or `"recently"`** — mandatory, in addition to (never instead of) the action token above. This is the corrected dimension: recency is necessary evidence, but is never by itself sufficient action evidence.
4. Prohibited collision: must not be satisfied by a request whose action token is `"search"`/`"find"` (that is `MEMORY_SEARCH`'s own signature) merely because a recency word or a shared domain word is also present — e.g. `"Search memories for recent work"` contains the domain word and the recency qualifier, but contains neither `"show"` nor `"list"`, so it fails this signature's action requirement and is correctly **not** grounded here.
5. Exact existing phrasing: **none currently satisfies the corrected signature as written** — see §20.7 for the required, disclosed fixture wording change (`"what have I asked you to remember recently"` → `"show me what I've asked you to remember recently"`), after which that phrasing satisfies it (`"show"` + `"remember"` + `"recently"`).

**6. `MEMORY_SEARCH`**
1. Required action token: `"search"` or `"find"` (both real, shipped instruction text — "asks to **search or find** stored memories"; the real test uses `"search"`).
2. Required domain token: `"memory"` or `"memories"`.
3. Required qualifier: none.
4. Prohibited collision: must not be satisfied by a request whose action token is `"show"`/`"list"` with a `"recent"`/`"recently"` qualifier (`MEMORY_LIST_RECENT`'s own signature) merely because the shared domain word is present — e.g. `"Show recent memories"` contains `"show"`, `"recent"`, and `"memories"`, but contains no `"search"`/`"find"`, so it fails this signature's action requirement and is correctly **not** grounded here.
5. Exact existing phrasings satisfying it: `"search my memories for the deployment checklist"`; `"search my memories for deployment checklist"`; `"search my memories for x"`.

#### 20.2.1 Evidence sources

Identical to §19.3.1: every action/domain token above is sourced either from a real, currently-passing test's literal `request_text`, or from the real, already-shipped `_TRUSTED_PLANNING_INSTRUCTION` string in `intelligence/planning.py` (both re-quoted verbatim in §19.3.1 and re-verified during this pass). No token was added that is not traceable to one of these two sources.

### 20.3 Catalogue-wide uniqueness rule

Grounding evaluates the live `request_text` against **all six** signatures above, not only the one the model selected, in this exact order:

1. Run the negation/conflict gate (§20.6) once, against the whole request, independent of any capability. If it triggers, refuse immediately (detail: `negated_or_conflicting_request`) — no signature is evaluated.
2. Evaluate every one of the six signatures in §20.2 independently against `request_text`, and collect the set of capability ids whose full signature (action + domain + qualifier, where required) is satisfied.
3. If this set is **empty**, refuse (detail: `no_signature_matched`).
4. If this set has **more than one member**, refuse (detail: `multiple_signatures_matched`) — **even if the model-selected capability is one of the matched members.** A request that is genuinely ambiguous between two real capabilities is never resolved by trusting the model's own choice among them.
5. If this set has **exactly one member** and it is **not equal** to the model-selected `capability_id`, refuse (detail: `selected_capability_not_unique_match`).
6. Otherwise (exactly one member, equal to the model's selection): proceed to argument-span extraction/attribution (§20.4) if the capability declares a string argument, else proceed directly to the existing `_preflight_capability()`.

Direct re-verification (§20.2, per-capability item 5, and the collision matrix in §20.5) confirms every real, currently-accepted phrasing for all six capabilities — after the one disclosed §20.7 fixture change — produces a set of size exactly one, equal to its own intended capability, so this rule introduces no new false refusal beyond that one disclosed change.

### 20.4 Exact argument-span extraction rules (final)

Unchanged in mechanism from §19.4 except for the removal of the `"and confirm it"` special case (§20.7). Applies only after the capability has already passed the uniqueness rule (§20.3) as the unique, matching, model-selected capability.

**`MEMORY_SEARCH`**:
1. The one accepted search marker, supported by every real phrasing, is `" for "` (case-insensitive).
2. If `" for "` occurs **exactly once**, the candidate span is the trimmed text after it.
3. **Reject** (detail: `ambiguous_argument_span`) if the marker occurs **zero** times or **more than once**.
4. **Reject** (same detail) if the extracted candidate span, after trimming, is **empty**.
5. **Reject** (same detail) if the candidate span contains the space-padded substring `" or "` (a disjunction/conflict signal within the span itself — see §20.6).
6. Otherwise, compare the model-supplied `value` to the candidate span under the exact normalization-and-equality rule (§20.5-adjacent; see below). Equal → **accept**, original validated value passes through unchanged. Not equal → **reject** (detail: `argument_value_mismatch`).

**`PROJECT_STATE_UPDATE_FOCUS`**:
1. The one accepted focus-value marker, supported by every real phrasing, is `" to "` (case-insensitive).
2. If `" to "` occurs **exactly once**, the candidate span is the trimmed text after it.
3. **Reject** (detail: `ambiguous_argument_span`) if the marker occurs zero or more than once.
4. **Reject** (same detail) if the extracted candidate span, after trimming, is empty.
5. **Reject** (same detail) if the candidate span contains the space-padded substring `" or "`.
6. No suffix stripping of any kind is applied (the `"and confirm it"` exception is dropped — §20.7). Otherwise, compare the model-supplied `value` to the candidate span under the exact normalization-and-equality rule below. Equal → accept, unchanged. Not equal → reject (detail: `argument_value_mismatch`).

Neither rule ever falls back to a partial match, a second marker, or a best-effort guess — a request not shaped exactly as above for its capability is refused, never approximately parsed.

### 20.5 Terminal punctuation policy (final)

**Inspection finding**: no currently-accepted request phrasing, in any test, ends with terminal sentence punctuation (`.`, `!`, `?`) — every real `request_text` string in this repository is a bare phrase with no trailing punctuation. Terminal punctuation is therefore not required for compatibility with any existing test.

**Chosen rule** (the narrow-stripping option, chosen for forward-looking real-usage robustness rather than test compatibility, since a real user typing a request at a keyboard commonly ends a sentence with punctuation while a model's own extracted argument value typically does not): before the exact-equality comparison (§20.4), strip **at most one** trailing character from the end of *both* the candidate span and the model-supplied value, if and only if that trailing character is one of exactly `.`, `!`, `?`. No other punctuation (commas, colons, semicolons, quotation marks, parentheses) is ever stripped, from either end, at any position. This is applied identically to both sides being compared, after casefolding and internal-whitespace collapsing, before the final equality check.

**Compatibility consequence**: none for any currently-accepted phrasing (confirmed by the inspection finding above — no real fixture is affected either way by this rule, since none currently has trailing punctuation to strip). This rule only matters for future real-world requests that do include terminal punctuation.

**Required tests**: a candidate span ending in exactly one of `.`/`!`/`?`, paired with a model value that omits it, is accepted; a candidate span or value containing internal (non-terminal) punctuation is compared unchanged (rejected if it differs); a candidate span with two consecutive terminal characters (e.g. `"...checklist?!"`) has only the single trailing character stripped, and the remaining terminal character causes the two sides to be compared as still containing it (so both sides must agree on whatever remains).

### 20.6 Exact negation-marker list and normalization (final)

**Normalization applied before matching**: casefold; replace the curly apostrophe `’` (U+2019) with the straight apostrophe `'` (U+0027); collapse runs of whitespace to a single space; strip leading/trailing whitespace; then pad with exactly one leading and one trailing space for the whole-word checks below.

**Whole-word markers** (matched as the padded substring `" <word> "`, so they can never trigger on a word that merely contains the same letters without a surrounding space on both sides):
- `" not "` — catches the standalone word `"not"` in any position, and therefore also catches every multi-word construction that contains `"not"` as its own word: `"do not"`, `"does not"`, `"is not"`, `"will not"`, `"can not"`, `"should not"`, etc. Does **not** match inside `"notebook"` or `"notice"` (no space immediately follows `"not"` in either word).
- `" never "` — catches the standalone word `"never"`. Does **not** match inside `"whenever"` or `"nevertheless"` (in both words, `"never"`'s letters are not bounded by spaces on both sides once the whole word is padded).

**Contraction substrings** (matched as a direct substring of the casefolded, apostrophe-normalized text — safe without padding, since the apostrophe itself is a sufficiently distinctive boundary): `"don't"`, `"doesn't"`, `"isn't"`, `"won't"`, `"can't"`.

**Fixed single-word/phrase substrings** (safe as direct substrings; `"cannot"` is checked separately from `" not "` because it has no internal space for that check to find): `"cannot"`, `"instead of"`, `"rather than"`, `"but not"`.

**Required tests** (directly satisfying every case named in the task): `"not"` triggers as an independent word; `"do not"` triggers (via the `" not "` whole-word check); `"don't"` triggers; `"don't"` with a curly apostrophe (`"don’t"`) triggers once normalized; `"never"` triggers; `"instead of"` triggers; `"notebook"` and `"notice"` do **not** trigger merely because they contain the letters "not".

**Deliberate conservative limitation, documented**: a legitimate, literal memory-search value that itself happens to contain one of these markers (for example, searching for a note whose real content includes the word "never") may be refused in Phase 92 V1 and require simpler restatement. No quotation-parsing, clause-boundary detection, or general negation understanding is attempted — this is an accepted, disclosed, intentionally conservative limitation of V1, not an oversight.

### 20.7 Final decision on the `"and confirm it"` suffix rule: dropped

**Investigation**: the phrase `"and confirm it"` has no functional or parsing significance anywhere in the live production code or live user-facing documentation — `docs/user_guide.md` and `tools/builtin/help_tool.py` (the current, authoritative user-facing docs) never mention it as required or suggested phrasing. Its only appearances are: (a) historical, frozen `docs/phase_90_implementation_plan.md` illustrative example text (never a literal grammar requirement — the actual verification behavior runs automatically regardless of the request's exact wording), and (b) the one literal test fixture `_REQUEST` constant in `tests/unit/test_orchestrator_update_focus_workflow.py`. It exists only to preserve that one fixture's artificial wording and has no real supported user-facing value.

**Decision**: the suffix-stripping exception is **dropped entirely** from the production design (§20.4 above no longer strips anything). Instead, Batch 1 will update the `_REQUEST` constant to remove the trailing clause — e.g. `_REQUEST = "ask jarvis to: update my project focus to batch 3 verification"` — and pair every test using it with a model-supplied value that exactly equals its own extracted span (`"batch 3 verification"`), per the same mechanical, disclosed fixture-consistency work already required by §19.7. This keeps the production span-extraction rule uniform and free of any bespoke, historically-motivated special case.

**Required tests confirming the design contains no such exception**: a candidate span that happens to contain the words "and confirm it" *internally* (not as the request's own trailing clause, but genuinely part of the requested focus text) is compared unchanged — no stripping occurs anywhere, at any position, under any condition; a request built by appending arbitrary extra trailing text after the real focus value (with or without "and confirm it") is refused as an exact-equality mismatch, exactly like any other non-matching span, since there is no longer any suffix-specific handling to interact with it.

### 20.8 Collision matrix

All of the following are direct consequences of §20.2's signature table and §20.3's uniqueness rule, individually re-verified during this pass:

**Project State**
- A project-state read request (`"show my project state"`) grounds `PROJECT_STATE_SHOW` only — it contains no `"update"` and cannot satisfy `PROJECT_STATE_UPDATE_FOCUS`.
- A focus-update request (`"update my project focus to batch 3 verification"`) grounds `PROJECT_STATE_UPDATE_FOCUS` only — it contains no `"show"` and no adjacent `"project state"` phrase, so it cannot satisfy `PROJECT_STATE_SHOW`.
- `"Show the current project focus"` satisfies neither signature (`"show"` present but `"update"` absent for the update capability; `"show"` present but the adjacent `"project state"` phrase absent for the show capability) — refused as `no_signature_matched`, not a regression (§19.7/§20.2 item 5).
- An update request cannot ground the show capability merely because it mentions "project" — the show signature requires the literal adjacent phrase `"project state"`, which no real update-focus phrasing contains (they all say "project **focus**").

**Memory**
- A recent-memory listing request (post-§20.7 fixture wording: `"show me what I've asked you to remember recently"`) grounds `MEMORY_LIST_RECENT` only — it contains no `"search"`/`"find"`.
- A memory-search request (`"search my memories for the deployment checklist"`) grounds `MEMORY_SEARCH` only — it contains no `"show"`/`"list"` action token paired with a recency qualifier (and no recency qualifier at all).
- `"Search memories for recent work"` cannot ground `MEMORY_LIST_RECENT` (no `"show"`/`"list"` action token present — `"search"` is not an accepted action token for that capability) — it grounds `MEMORY_SEARCH` only.
- `"Show recent memories"` cannot ground `MEMORY_SEARCH` (no `"search"`/`"find"` present) — it grounds `MEMORY_LIST_RECENT` only (`"show"` + `"memories"` + `"recent"`, all three dimensions present).
- `"memory"`, `"memories"`, `"recent"`, `"show"`, `"list"`, `"search"`, or `"find"` alone (without their required paired evidence) grounds neither capability — each signature requires action **and** domain (**and**, for `MEMORY_LIST_RECENT`, the recency qualifier) together.

**Health and Schedules**
- A health request (`"check jarvis's health"`) cannot ground `SCHEDULE_LIST` (no `"schedule"`/`"schedules"` domain token).
- A schedule-list request (`"show my schedules"`) cannot ground `HEALTH_CHECK` (no `"health"`/`"status"` domain token).
- The shared generic words `"show"`, `"check"`, `"list"`, or `"status"` are each insufficient alone — every signature in §20.2 also requires its own specific domain token, which these generic words never supply by themselves.

### 20.9 Updated outcome details

`PlanningOutcomeKind.UNGROUNDED_SELECTION` remains the single, shared public outcome kind. Its bounded, internal `detail` string now distinguishes exactly six cases (supersedes §19.8's four):

1. `negated_or_conflicting_request` (§20.6, checked first).
2. `no_signature_matched` (§20.3 step 3).
3. `multiple_signatures_matched` (§20.3 step 4).
4. `selected_capability_not_unique_match` (§20.3 step 5).
5. `ambiguous_argument_span` (§20.4 — zero/multiple markers, empty span, or an internal disjunction).
6. `argument_value_mismatch` (§20.4 — exactly one span extracted, but the model's value does not equal it).

No detail string ever includes the raw request text, the candidate span, the rejected value, retrieved context, or model reasoning — each is a short, fixed, non-sensitive category label only, exactly mirroring `ToolSelectionParseError.reason`'s existing convention. The public, Batch-2-constructed refusal message stays simple and generic per category and never exposes parser internals.

### 20.10 Compatibility impact (final)

- **Zero impact** for `PROJECT_STATE_SHOW`, `PROJECT_STATE_UPDATE_FOCUS`'s capability-selection grounding (as opposed to its argument fixtures, below), `HEALTH_CHECK`, `SCHEDULE_LIST`, and `MEMORY_SEARCH` — every real, currently-tested phrasing satisfies its corrected signature and is the unique catalogue-wide match.
- **One disclosed compatibility restriction, `MEMORY_LIST_RECENT`**: the sole existing test phrasing, `"what have I asked you to remember recently"`, does not satisfy the corrected signature (no listing/display action token). Batch 1 must update this fixture's wording to `"show me what I've asked you to remember recently"` (or an equivalent phrasing containing `"show"`/`"list"`), preserving the test's assertion and intent unchanged — this is a required, disclosed, mechanical fixture edit, not a silent behavior change.
- **Larger, already-disclosed `PROJECT_STATE_UPDATE_FOCUS` argument-fixture work** (from §19.7, unchanged by this section except that the target span no longer includes "and confirm it"): most existing update-focus tests pair a fake model value with a `request_text` that does not contain it; Batch 1 must make each pairing mutually consistent.
- **One deliberate new restriction, already named in §19.7 and reconfirmed here**: the task's own illustrative "Show me the current project focus" phrasing was never a previously-accepted phrasing and is now refused as `no_signature_matched` — judged safe and correct, not a regression.
- No other currently-accepted phrasing is restricted by any rule in this section.

### 20.11 Updated required tests

In addition to every test already specified in §19.10 (superseded only where this section's exact rules differ — the `MEMORY_LIST_RECENT` signature, the dropped suffix exception, and the punctuation/negation specifics), the final plan requires:

1. Every currently-accepted phrasing (post-§20.7 fixture update) produces a catalogue-wide signature-match set of size exactly one, equal to its own real capability.
2. The model-selected `capability_id` is proven required to equal that unique match — a test forcing a mismatch (fake model selects capability A, but only capability B's signature matches) is refused (detail: `selected_capability_not_unique_match`), even though capability A's own signature, checked in isolation, would have matched.
3. A request matching zero signatures is refused (detail: `no_signature_matched`).
4. A constructed request matching more than one signature is refused (detail: `multiple_signatures_matched`), even when the model's selection is one of the matched capabilities.
5. `"Search memories for recent work"` does not ground `MEMORY_LIST_RECENT`.
6. `"Show recent memories"` does not ground `MEMORY_SEARCH`.
7. A genuine read request does not ground any write capability (`PROJECT_STATE_UPDATE_FOCUS`).
8. A genuine write request does not ground `PROJECT_STATE_SHOW`.
9. `"not"` triggers negation as an independent word; `"do not"`, `"don't"`, `"don’t"` (curly apostrophe), `"never"`, and `"instead of"` each trigger.
10. `"notebook"` and `"notice"` do not trigger negation.
11. The exact requested argument span is accepted for both `MEMORY_SEARCH` and `PROJECT_STATE_UPDATE_FOCUS`.
12. A wrong, expanded, old/superseded, rejected-alternative, or negated value is rejected for both capabilities.
13. Terminal punctuation is handled exactly per §20.5 (single trailing `.`/`!`/`?` stripped from both sides only; nothing else stripped anywhere).
14. The `"and confirm it"` suffix is never specially handled: internal occurrences of similar wording are compared unchanged, and extra trailing text of any kind causes a mismatch refusal.
15. Every refusal category (all six in §20.9) produces zero `SecurityManager` preflight, zero `ApprovalManager.create_request()`, zero `ToolExecutor.execute()`, zero verifier call, zero write, and zero memory-result exposure.
16. All currently-accepted, real Phase 90/91 request phrasings remain accepted after the one disclosed `MEMORY_LIST_RECENT` fixture-wording change (§20.10) — no other compatibility restriction exists.

### 20.12 Updated stop conditions (final, supersedes §19.12)

- Stop and report before implementing if, after the §20.7 `MEMORY_LIST_RECENT` fixture wording change, any currently-accepted real phrasing for any of the six capabilities still cannot satisfy its exact §20.2 signature, or produces a catalogue-wide match set other than the single, correct capability.
- Stop and report if the negation-marker list (§20.6) is found, during Batch 1, to false-trigger on any real, currently-accepted phrasing (none were found in this planning pass).
- Stop and report, and propose a smaller safe Phase 92 design, if any capability's action, domain, or qualifier evidence cannot be represented as a small, fixed token/phrase set without inventing unproven synonyms.
- Stop and report if argument-span extraction for either `MEMORY_SEARCH` or `PROJECT_STATE_UPDATE_FOCUS` is found to require anything beyond the single fixed marker, single-occurrence rule in §20.4 — never expand into general natural-language parsing.
- Stop and report if punctuation or suffix handling is found to require anything beyond the single, narrow, two-sided terminal-character rule in §20.5 — never introduce broad punctuation normalization.
- Stop and report if any part of this design is found to require a probabilistic, learned, or similarity-scored judgment of any kind — the entire contract must remain deterministic string/token/substring logic only.
- Stop after Batch 2's report. Do not begin Phase 93, additional capabilities, verification generalization, or any other unrelated work without Nathan's explicit approval.

## 21. Batch 1 Implementation Evidence

**Status: Batch 1 complete and committed. Phase 92 remains open — Batch 2 (final, per-reason user-facing refusal wording) has not been started.**

### 21.1 Files changed

- `intelligence/grounding.py` (new) — the deterministic, deny-only `ground_decision()` contract: the negation/conflict gate, the six `_IntentSignature` definitions, catalogue-wide uniqueness evaluation, and the two marker-based argument-span extractors, exactly per §20.
- `intelligence/planning.py` (modified) — added `PlanningOutcomeKind.UNGROUNDED_SELECTION`; wired `ground_decision()` into `select_tool()` immediately after capability-adapter lookup and before `_preflight_capability()`, so both the `EXECUTABLE` and `EXECUTABLE_WORKFLOW` paths are covered by the same single check.
- `core/orchestrator.py` (modified) — added the fixed `_ASK_JARVIS_TO_UNGROUNDED_MESSAGE` constant and a minimal branch in `_handle_ask_jarvis_to_request()` returning an honest `success=False` response for `UNGROUNDED_SELECTION`, placed before the `EXECUTABLE`/`EXECUTABLE_WORKFLOW` handling that would otherwise assume a populated plan/workflow_plan. This is crash-prevention wiring only; Batch 2 owns the final, per-reason public wording.
- `tests/unit/test_grounding.py` (new, 71 tests) — direct unit coverage of `ground_decision()` and its private helpers: real per-capability grounding, uniqueness/collision cases, negation markers (including false-positive avoidance), both capabilities' argument-span rules, terminal-punctuation policy, and structural/contract-shape proofs.
- `tests/unit/test_intelligence_planning.py` (modified: 9 existing fixture edits + 10 new tests, 33 → 43 tests) — new tests prove `select_tool()`'s real wiring: ungrounded-capability and ungrounded-argument outcomes, grounding running before any `SecurityManager.classify_action()` call (via a real counting subclass, not a mock), adversarial `AssembledContext` content failing to ground a capability the live request never asked for, and that an already-`INVALID_OUTPUT` decision is never widened by grounding.
- `tests/unit/test_orchestrator_ask_jarvis_to.py` (modified: 1 existing fixture edit + 4 new tests, 41 → 45 tests) — new tests prove zero `ToolExecutor` calls and zero approvals on an ungrounded `EXECUTABLE`-path refusal, and that a fabricated `memory_search` value never exposes real stored memory content.
- `tests/unit/test_orchestrator_update_focus_workflow.py` (modified extensively: `_REQUEST`/all `_update_focus_text()` values realigned to `"batch 3 verification"` + 4 new tests, 23 → 27 tests) — new tests prove zero pending approvals and zero store writes on both an argument-mismatch refusal and a negated-request refusal on the workflow (`EXECUTABLE_WORKFLOW`) path, a structural proof the `UNGROUNDED_SELECTION` branch never calls `_start_update_focus_workflow()`, and that the refusal message never echoes the rejected candidate value.

`dashboard_test.txt` was not opened, read, staged, or otherwise touched at any point during this batch.

### 21.2 Production grounding architecture (as implemented)

`ground_decision(*, request_text, capability_id, arguments) -> GroundingResult` is a pure function: no AI provider call, no I/O, no retained state between calls, no argument beyond the three named above (verified by a dedicated signature-purity test in `test_grounding.py`). Order of internal checks, matching §20.3 exactly:

1. Negation/conflict gate (§20.6) — checked first, unconditionally, for every capability including zero-argument ones.
2. Catalogue-wide signature evaluation against all six `_IntentSignature` entries — empty match set, multiple-match set, and selected-not-unique-match are each refused with their own distinct reason.
3. For the two capabilities with a declared string argument (`PROJECT_STATE_UPDATE_FOCUS`, `MEMORY_SEARCH`), marker-based single-span extraction followed by exact normalized-equality comparison against the model's already-validated value.

`select_tool()` calls `ground_decision()` immediately after resolving the capability adapter and before `_preflight_capability()` — confirmed both by direct code inspection and by `test_ungrounded_selection_never_reaches_security_manager_preflight`, which proves a real, counting `SecurityManager` subclass records zero `classify_action()` calls on refusal, while `test_grounded_selection_still_reaches_security_manager_preflight` proves the same fixture records exactly one call for a genuinely grounded request (ruling out the zero-call result being a fixture artifact).

### 21.3 Exact final six-capability signature table (as implemented, matches §20.2 with one disclosed narrowing — see §21.6)

Implemented verbatim from §20.2 for `PROJECT_STATE_SHOW`, `PROJECT_STATE_UPDATE_FOCUS`, `SCHEDULE_LIST`, `MEMORY_LIST_RECENT`, and `MEMORY_SEARCH`. `HEALTH_CHECK`'s domain requirement was narrowed from §20.2's `"health"` or `"status"` to `"health"` only — see §21.6 for the investigation and reasoning.

### 21.4 Catalogue-wide uniqueness (as implemented)

`_grounded_capability_ids(request_text)` evaluates every one of the six signatures against the live request and returns the `frozenset` of matches. `ground_decision()` refuses on an empty set (`no_signature_matched`), a set with more than one member (`multiple_signatures_matched`), and a singleton set whose sole member is not the model-selected `capability_id` (`selected_capability_not_unique_match`) — otherwise the unique member equals the selection and evaluation proceeds. All three cases, plus the "genuinely grounded and matching" case, are directly tested in both `test_grounding.py` and, through the real `select_tool()`, in `test_intelligence_planning.py`.

### 21.5 Negation markers and argument-span/punctuation behavior (as implemented, matches §20.6/§20.4/§20.5 exactly)

Negation gate: whole-word markers `" not "`, `" never "` (space-padded substring match); contraction substrings `"don't"`, `"doesn't"`, `"isn't"`, `"won't"`, `"can't"` (matched after curly-apostrophe-to-straight normalization); phrase substrings `"cannot"`, `"instead of"`, `"rather than"`, `"but not"`. `"notebook"`/`"notice"`/`"whenever"`/`"nevertheless"` do not trigger — directly tested.

Argument spans: `MEMORY_SEARCH` uses marker `" for "`; `PROJECT_STATE_UPDATE_FOCUS` uses marker `" to "`. Each requires the marker to occur exactly once (zero or multiple → rejected), a non-empty trimmed span, and no internal `" or "` disjunction. The model's value is compared to the span via exact normalized-equality (casefold, whitespace-collapse, at most one trailing `.`/`!`/`?` stripped from each side independently) — never containment, never a fuzzy or partial match.

### 21.6 Disclosed implementation deviations from §20

Two deliberate, investigated deviations from the plan's exact wording were made during implementation, both narrowing (never widening) what is accepted, and both are safe:

1. **`HEALTH_CHECK` domain narrowed to `"health"` only, dropping `"status"`.** §20.2 allowed `"health"` or `"status"` as domain evidence, sourced from shipped instructional text rather than any real test. Per the task's own required stop-condition check, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_health_check_tool.py`, `docs/user_guide.md`, and `tools/builtin/help_tool.py` were inspected and confirmed that no test or documented behavior requires bare `"status"` as sufficient domain evidence — only `"check jarvis's health"` is real, tested language. Since `"status"` alone is materially more generic and collision-prone than `"health"` (e.g. it appears in "check project status", "check schedule status"), it was dropped entirely rather than kept. No stop condition was triggered by this finding, since the investigation confirmed narrowing was safe rather than finding a conflict requiring escalation.
2. **`UngroundedReason` carries seven values, not six.** §20.9 merged the argument-span failure modes (marker missing entirely vs. marker ambiguous/empty/disjunctive) into a single `ambiguous_argument_span` detail. During implementation, the zero-occurrences case (no marker at all) was given its own distinct `missing_argument_span` reason, separate from `ambiguous_argument_span` (marker present but multiple times, or the extracted span is empty or contains a disjunction), since these are diagnostically distinct situations sharing no common cause. This is purely additional granularity in an internal, non-user-facing detail string — it changes no refusal/acceptance outcome and satisfies §20.9's own stated invariant that no detail string ever exposes sensitive content.

No other deviation from §20's design was made. No new capability, write action, security rule, retry/replan behavior, or autonomous behavior was introduced.

### 21.7 Evidence refusals cause zero side effects

Directly proven, not merely asserted:
- `test_ungrounded_selection_never_reaches_security_manager_preflight` (planning-level, `EXECUTABLE` path) — zero `classify_action()` calls.
- `test_ungrounded_selection_causes_zero_tool_executor_calls` / `test_ungrounded_selection_creates_no_approval` (orchestrator-level, `EXECUTABLE` path) — zero tool-call log events, zero pending approvals.
- `test_ungrounded_memory_search_argument_never_exposes_search_results` (orchestrator-level) — a fabricated `memory_search` value never reaches the real `MemoryTool`, so stored memory content already present is never exposed in the refusal response.
- `test_ungrounded_update_focus_value_creates_no_approval_and_no_write` / `test_negated_update_focus_request_creates_no_approval_and_no_write` (orchestrator-level, `EXECUTABLE_WORKFLOW` path) — zero pending approvals, `ProjectStateStore.get()` remains `None`.
- `test_ungrounded_update_focus_never_reaches_workflow_engine` — structural AST proof that the `UNGROUNDED_SELECTION` branch in `_handle_ask_jarvis_to_request()` never calls `_start_update_focus_workflow()`, the sole path capable of reaching `WorkflowEngine.run()`.
- `test_ungrounded_update_focus_response_message_never_leaks_the_candidate_value` — the fixed refusal message never echoes the rejected argument value.

### 21.8 Test fixture wording changes and why each was required

- `"what have I asked you to remember recently"` → `"show me what I have asked you to remember recently"` (three occurrences: two in `test_intelligence_planning.py`, one in `test_orchestrator_ask_jarvis_to.py`) — the original phrasing contains no listing/display action token (`"show"`/`"list"`), failing the corrected `MEMORY_LIST_RECENT` signature (§20.1/§20.10); this is the one compatibility restriction disclosed in §20.10, resolved exactly as specified there.
- `_REQUEST` and every `_update_focus_text()` fake-model value in `test_orchestrator_update_focus_workflow.py`, plus the matching literal-value assertions, realigned to a single consistent value, `"batch 3 verification"` — most existing tests paired a fixed fake value with a `request_text` that never actually contained it (a pre-existing inconsistency invisible before argument grounding existed, since nothing previously checked the two against each other); this was disclosed and pre-authorized as necessary mechanical work in §19.7/§20.10, and the trailing `"and confirm it"` clause was dropped from `_REQUEST` per the final §20.7 decision.
- `request_text="update my focus",` → `request_text="update my focus to a new focus value",` (9 occurrences in `test_intelligence_planning.py`) — same category of pre-existing request/value inconsistency, corrected the same way.
- No fixture wording was weakened to make a test pass; every change either supplied missing action evidence the corrected signature genuinely requires, or made an already-intended request/value pairing actually consistent.

### 21.9 Verification results

- Focused: `test_grounding.py` (71), `test_intelligence_planning.py` (43), `test_orchestrator_ask_jarvis_to.py` (45), `test_orchestrator_update_focus_workflow.py` (27) — **186 passed**, run together.
- Broader Phase 90/91 regression sweep (approval manager/history/audit/models/prompt, capability catalog, CLI approval, core approval, health check tool + wiring, pending-approval wiring, project-state wiring/store/show/update/verify tools, memory tool, orchestrator context-query/workflow-commands, pending approval store, structured output, tool executor approval + logger isolation, verification): **649 passed**.
- Full suite, normal environment: **4747 passed, 3 skipped**.
- Full suite, `AI_REASONING_ENABLED=false`: **4747 passed, 3 skipped** — identical counts to the normal run.
- Ruff (`ruff check` on all seven changed/new files: `core/orchestrator.py intelligence/planning.py intelligence/grounding.py tests/unit/test_intelligence_planning.py tests/unit/test_orchestrator_ask_jarvis_to.py tests/unit/test_orchestrator_update_focus_workflow.py tests/unit/test_grounding.py`): **All checks passed! Exit code 0.** No new or pre-existing findings.
- `git diff --check` (tracked changes, plus the two new files included via `git add -N`): **exit code 0**. Only pre-existing `LF will be replaced by CRLF` advisory notices on Windows `core.autocrlf`, not whitespace errors — identical in kind to every prior phase's result.
- Final `git status --short` before commit: five modified files (`core/orchestrator.py`, `intelligence/planning.py`, `tests/unit/test_intelligence_planning.py`, `tests/unit/test_orchestrator_ask_jarvis_to.py`, `tests/unit/test_orchestrator_update_focus_workflow.py`) and two new files (`intelligence/grounding.py`, `tests/unit/test_grounding.py`); `dashboard_test.txt` remains untracked and untouched.

### 21.10 Confirmation of scope boundaries

No new capability, write action, security rule, retry/replan/multi-tool-plan behavior, embedding, confidence score, or autonomous behavior was added. `ground_decision()` can only ever refuse an outcome the existing structured-output parser and capability catalog already produced — it never approves, repairs, widens, or modifies a decision. Phase 92 remains open; Batch 2 (final, per-reason user-facing refusal wording) has not been started, and no Batch 2 documentation was added in this section.

## 22. Batch 2 Implementation Evidence and Phase 92 Closure

**Status: Batch 2 complete. Phase 92 is formally closed by this section and the accompanying `docs/phase_92_completion_report.md`.**

### 22.1 Batch 1 production audit (performed before any Batch 2 code change)

Direct inspection of `ed0047b`'s diff to `intelligence/grounding.py`, `intelligence/planning.py`, and `core/orchestrator.py` confirmed:

- Exactly three production files changed; no other production module was touched.
- `intelligence/planning.py`'s diff is a single, minimal insertion: one new import, one new `PlanningOutcomeKind` member, and one `ground_decision()` call placed after argument validation and before `_preflight_capability()` — no existing logic was altered or reordered.
- `core/orchestrator.py`'s diff is a single fixed message constant and one new `if outcome.kind is ...` branch, placed before the pre-existing `EXECUTABLE` fallthrough — no existing branch was altered.
- `intelligence/grounding.py`'s only imports are `re`, `collections.abc.Mapping`, `dataclasses.dataclass`, `enum.Enum`, and `intelligence.capability_catalog.CapabilityId` — no AI provider, no `ToolExecutor`/`ApprovalManager`/`WorkflowEngine`, no network/file/subprocess access, no retry/replan construct, no probabilistic or embedding-based logic.
- The module's 545 lines are proportionate to this repository's own established documentation convention (matching `intelligence/verification.py`/`intelligence/planning.py`'s own docstring density) — production logic, once docstrings are excluded, is exactly the negation gate, six fixed signatures, catalogue-wide matching, and two argument-span extractors specified in §20, nothing more.

**Conclusion: no stop condition was triggered.** Batch 1's production diff contains no unrelated refactoring, no duplicated orchestration architecture, no new capability behavior, no hidden retry/replanning, no request/argument mutation, no additional AI call, no probabilistic interpretation, no security-rule change, and no approval bypass. No part of Batch 1 was rewritten in Batch 2 — the accepted contract (signature table, negation markers, punctuation handling, ambiguity handling, span markers) is unchanged, since no failing test ever demonstrated a defect in it.

### 22.2 Completed orchestrator handling: two public refusal-message categories

`core/orchestrator.py` now maps `PlanningOutcomeKind.UNGROUNDED_SELECTION`'s bounded `detail` to exactly one of two fixed, generic public messages via `_ask_jarvis_to_ungrounded_message()`:

- **Action-selection refusal** (`_ASK_JARVIS_TO_ACTION_SELECTION_REFUSAL_MESSAGE`) — used for `no_signature_matched`, `multiple_signatures_matched`, and `selected_capability_not_unique_match`: *"Jarvis could not safely match that request to one supported action, so nothing was run. Please restate exactly what you'd like Jarvis to do."*
- **Exact-request refusal** (`_ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE`) — used for `negated_or_conflicting_request`, `missing_argument_span`, `ambiguous_argument_span`, and `argument_value_mismatch`: *"Jarvis could not safely confirm the exact request or value, so nothing was run. Please restate it directly and exactly."*

Neither message ever contains the internal reason code, the live request, a candidate argument span, or a rejected/candidate value. `test_ungrounded_message_mapping_is_exhaustive_and_exactly_two_valued` proves every one of the seven real `UngroundedReason` members (read from the enum itself, never a hardcoded duplicate list) maps to exactly one of these two strings — no third, per-reason message exists, and no reason is left unmapped. `test_public_refusal_messages_expose_no_internal_mechanics` proves neither message contains any of `signature`, `span`, `enum`, `reason`, `grounding`, `capability_id`, `parse`, `negation`, or `regex`, and that both are under 200 characters.

### 22.3 End-to-end zero-side-effect proof (Batch 2 additions)

New orchestrator-level tests, covering both the ordinary `EXECUTABLE` path and the `EXECUTABLE_WORKFLOW` (`project_state_update_focus`) path:

- **Capability mismatch**: `test_capability_mismatch_executes_neither_the_correct_nor_selected_tool` (health_check uniquely grounded, schedule_list selected — neither runs) and `test_capability_mismatch_for_update_focus_executes_neither_tool` (project_state_show uniquely grounded, project_state_update_focus selected with a fabricated value — no approval, no write, no workflow attempt).
- **No signature**: `test_no_signature_match_returns_action_selection_message` — "do my laundry" against a health_check selection; zero preflight, zero tool calls, action-selection message.
- **Multiple signatures**: `test_multiple_signature_match_returns_action_selection_message_and_executes_nothing` — a request satisfying both `project_state_show` and `health_check` at once; zero tool calls, zero approvals, action-selection message, no automatic choice between the two.
- **Negation/conflict**: `test_negation_in_executable_path_returns_exact_request_message` (ordinary path) and `test_negated_update_focus_returns_exact_request_message` (workflow path) — both zero-execution, exact-request message.
- **MEMORY_SEARCH argument mismatch**: `test_memory_search_argument_mismatch_returns_exact_request_message` and the pre-existing `test_ungrounded_memory_search_argument_never_exposes_search_results` — no MemoryTool call, no stored memory content exposed, exact-request message, rejected value never echoed.
- **PROJECT_STATE_UPDATE_FOCUS argument mismatch**: `test_ungrounded_update_focus_argument_mismatch_returns_exact_request_message`, the pre-existing `test_ungrounded_update_focus_value_creates_no_approval_and_no_write`, and the new `test_update_focus_argument_mismatch_creates_no_durable_pending_workflow` (a fresh `PausedWorkflowStore` instance over the same session factory reads back zero rows) — no YELLOW approval, no durable pending workflow, no store write, rejected value never echoed.
- **No second model call on any refusal category**: `test_no_second_ai_call_on_any_grounding_refusal`, parametrized across no-signature, multiple-signature, capability-mismatch, and negation cases — exactly one AI call each.

Every one of these tests uses the real `SecurityManager`, real `ToolRegistry`/`ToolExecutor`, real `ApprovalManager`, real `WorkflowEngine`, and real `ProjectStateStore`/`PausedWorkflowStore` over a real in-memory SQLite database — no mocks of these components. Only the `_CountingSecurityManager` subclass (Batch 1, planning-level) and the fake, in-memory `AIProvider` (used throughout Phase 90/91/92) are test doubles, and both exist solely to make an absence of calls provable rather than to fabricate a result.

### 22.4 Successful vertical-slice regressions (unchanged, confirmed)

All six capabilities were confirmed still functioning exactly as before, through pre-existing tests unmodified in Batch 2: `test_project_state_show_behavior_is_unaffected_by_new_capabilities` / `test_real_execution_through_real_tool_executor_grounds_the_response` (`PROJECT_STATE_SHOW`), `test_approval_executes_the_workflow_exactly_once` / `test_durable_restart_end_to_end` / `test_exact_mismatch_reports_failed_verification` (`PROJECT_STATE_UPDATE_FOCUS` — real YELLOW classification, real approval, real resume, real durable write, real durable verification), `test_health_check_executes_through_real_tool_executor_and_grounds_response` (`HEALTH_CHECK`), `test_schedule_list_executes_through_real_tool_executor_and_grounds_response` (`SCHEDULE_LIST`), `test_memory_list_recent_executes_through_real_tool_executor_and_grounds_response` (`MEMORY_LIST_RECENT`), and `test_memory_search_executes_through_real_tool_executor_and_grounds_response` (`MEMORY_SEARCH`).

### 22.5 Advisory and deterministic path confirmation

`test_advisory_ask_jarvis_handler_never_calls_select_tool_or_grounding` (new, Batch 2) is a structural proof that `_handle_ask_jarvis_request` (the advisory `ask jarvis:` handler) never references `select_tool(`, `ground_decision(`, or `ToolExecutor` — the executable grounding contract is used solely by `_handle_ask_jarvis_to_request`. Combined with the pre-existing, unmodified `test_ask_jarvis_advisory_command_remains_unaffected`, `test_existing_deterministic_commands_are_unaffected`, `test_ask_jarvis_advisory_remains_unaffected_by_update_focus_addition`, and `test_existing_deterministic_command_remains_unaffected` (all still passing, all unchanged), this confirms the advisory path never executes a tool through the new contract and deterministic command grammar is untouched.

### 22.6 Compatibility review of Batch 1 fixture wording changes

Every fixture wording change made in Batch 1 was re-verified directly against `ed0047b`'s diff (not from memory):

| File | Old request wording | New request wording | Why the old wording lacked evidence |
|---|---|---|---|
| `test_intelligence_planning.py` (×2), `test_orchestrator_ask_jarvis_to.py` (×1) | `"what have I asked you to remember recently"` | `"show me what I have asked you to remember recently"` | Contained no listing/display action token (`"show"`/`"list"`) required by `MEMORY_LIST_RECENT`'s corrected signature (§20.1) — only the domain word and recency qualifier were present. |
| `test_intelligence_planning.py` (×9) | `request_text="update my focus"` | `request_text="update my focus to a new focus value"` | Contained the action token (`"update"`) and domain token (`"focus"`) but no `" to "` marker at all, so no argument span could ever be extracted for the paired fake value. |
| `test_orchestrator_update_focus_workflow.py` (`_REQUEST` + all `_update_focus_text()` fixtures) | `_REQUEST` ended `"...and confirm it"`; fake values varied (`"new focus value"`, `"restart-tested focus"`, `"intended value"`, `"some value"`, `"new focus"`, `"grounded focus value"`, `"some private-looking value"`, `"no second call test"`) | `_REQUEST` drops the suffix (final §20.7 decision); every fake value realigned to the single value `"batch 3 verification"`, matching `_REQUEST`'s own `" to "` span exactly | None of the varied fake values were ever the literal text following `" to "` in `_REQUEST` — argument grounding did not exist before Batch 1, so this mismatch was invisible until it did. |

**Confirmation: no assertion was weakened.** Every downstream literal-value assertion (`project_state_store.get().focus == ...`, `"... " in final.message`, `persisted_rows[0].plan_steps[0]["tool_input"]["value"] == ...`) was updated to the same new, consistent value — never loosened to a wildcard, a substring check, or removed. The one deliberately new restriction (the task's own illustrative `"Show me the current project focus"` phrasing, never previously accepted, correctly refused as `no_signature_matched`) remains a documented, intentional narrowing, not a regression. No inconsistent fixture was restored to preserve historical wording. The full Phase 90/91 regression sweep (§21.9, re-run in Batch 2 — see §22.7) confirms every accepted safe Phase 90/91 user-facing example still passes unchanged.

### 22.7 Verification results (Batch 2)

- Focused Phase 92 suite (`test_grounding.py` 71, `test_intelligence_planning.py` 43, `test_orchestrator_ask_jarvis_to.py` 54, `test_orchestrator_update_focus_workflow.py` 31): **199 passed**.
- Phase 90/91 regression sweep (same 29 files as §21.9): **649 passed**.
- Full suite, normal environment: **4760 passed, 3 skipped** (13 more than Batch 1's 4747 — exactly the 13 new Batch 2 tests).
- Full suite, `AI_REASONING_ENABLED=false`: **4760 passed, 3 skipped** — identical.
- Full suite, `PYTHON_DOTENV_DISABLED=1`: **4760 passed, 3 skipped** — identical.
- Ruff (`ruff check` on every Python file changed across both batches: `core/orchestrator.py intelligence/planning.py intelligence/grounding.py tests/unit/test_intelligence_planning.py tests/unit/test_orchestrator_ask_jarvis_to.py tests/unit/test_orchestrator_update_focus_workflow.py tests/unit/test_grounding.py`): **All checks passed! Exit code 0.** No new or pre-existing findings.
- `git diff --check`: exit code 0. Only pre-existing `LF will be replaced by CRLF` advisory notices, no whitespace errors.
- `dashboard_test.txt` was not opened, read, staged, or otherwise touched at any point during Batch 2.

### 22.8 Manual Anthropic API acceptance status

Live Anthropic manual acceptance remains postponed because the configured API account lacks sufficient credits — an external account limitation, not a Jarvis code failure. No production behavior was changed to bypass it, and no live manual test is claimed to have passed. Repository-level fake-provider, deterministic, security, approval, execution, verification, and full-suite tests remain the sole closure evidence, exactly as in every prior phase.

### 22.9 Formal closure

Phase 92 is closed as of this section and `docs/phase_92_completion_report.md`. No new capability, write action, security rule, security-tier change, retry, replanning, autonomous behavior, embedding, semantic similarity, confidence scoring, request/argument rewriting, or scope-excluded behavior (dashboard, voice, phone, browser/computer control, source-code self-modification) was added in either batch. Phase 93 has not been started.
