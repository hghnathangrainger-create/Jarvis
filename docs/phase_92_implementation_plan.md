# Jarvis — Phase 92 Implementation Plan

**Status:** Planning gate — awaiting explicit approval before Batch 1 begins.
**Version:** Phase 92 — Intelligence Core V1 Next-Milestone Planning Gate
**Date:** 2026-07-20

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
