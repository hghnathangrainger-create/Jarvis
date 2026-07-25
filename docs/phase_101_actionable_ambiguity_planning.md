# Phase 101 Planning Gate — Actionable Ambiguity and Clarification V1

**Status: planning and repository-audit only. Not committed. No production code, test, migration, capability, help-text, or user-documentation change was made during this pass.**

## 1. Repository baseline

- Current branch: `phase-4-ai-reasoning-and-write-actions`
- Current HEAD: `d108f4c` ("Add Phase 100 Batch 2: live Verified Action Context integration and close Phase 100")
- Recent chain: `d108f4c` → `0b3efd8` → `f69c649` → `24946db` → `502202d` (Phase 99 closure)
- `git status`: clean except `?? dashboard_test.txt` (pre-existing, untouched, untracked)
- No `docs/phase_101_*` file existed before this document
- Targeted regression before this pass (`-k "phase100 or grounding or intelligence_planning or structured_output or compound"`): **1086 passed, 0 failed**

Repository matches the authoritative Phase 100 closure state exactly. No stop condition triggered.

## 2. Current non-success call flow

For `ask jarvis to: <request>` (`intelligence/planning.py::select_tool()`):

1. Empty request / AI disabled / context unavailable / provider unavailable / provider raised → five distinct, already-fixed, already-actionable-enough messages (not this phase's concern).
2. `AIRouter.route()` returns raw text.
3. **Discriminator peek** (`peek_compound_decision()`) — inspects only the top-level `"decision"` key to choose the single-capability parser or the compound parser, before either runs.
4. **Single-capability path**: `intelligence.structured_output.parse_tool_selection()` — strict JSON-shape validation, then `_validate_arguments()` against the selected capability's own `CapabilityAdapter.arguments`. Any failure (unknown top-level keys, unknown capability, unknown argument name, **missing required argument**, **invalid argument type**, oversized/malformed string) raises `ToolSelectionParseError(reason: str)` — one of nine fixed but generic strings, with no capability id, argument name, or expected format attached to the exception itself (both are known at the raise site and discarded). Surfaces as `PlanningOutcomeKind.INVALID_OUTPUT`, `detail=reason`.
5. **Grounding** (`intelligence.grounding.ground_decision()`) — runs only after parsing succeeds and only for a valid `"execute"` decision. Checks, in order: negation/conflict, signature-match count (0/1/>1), model-selected id matches the unique signature match, then (if the capability has a declared argument marker) independently re-extracts the argument's value **from the live request text** and compares it byte-for-byte against the model's own value. Never trusts the model's value alone. Returns `GroundingResult(grounded=False, reason: UngroundedReason)` — exactly one of 7 members (Section 3). Surfaces as `PlanningOutcomeKind.UNGROUNDED_SELECTION`, `detail=reason.value`.
6. **Compound path**: `parse_compound_tool_selection()` (schema/step-count/order/duplicate-key validation) → `PlanningOutcomeKind.INVALID_COMPOUND_OUTPUT` on failure. Then `ground_compound_decision()` (ProjectState template) or, only on that function's own `TEMPLATE_NOT_ALLOWED` result, `ground_schedule_compound_decision()` (schedule template) — exactly one of 9 `CompoundUngroundedReason` members (Section 3). Surfaces as `PlanningOutcomeKind.UNGROUNDED_COMPOUND_SELECTION`.
7. A valid `"unsupported"` decision → `PlanningOutcomeKind.UNSUPPORTED` (a **positive**, `success=True` response today).

**Ordinary-versus-compound precedence:** the discriminator peek commits to exactly one path before either parser runs; there is no fallback from a failed compound parse/ground to a single-capability interpretation, and vice versa (an explicit, tested "no fallback" contract).

## 3. Existing outcome inventory (exhaustive)

### `intelligence.grounding.UngroundedReason` — exactly 7 members

| Member | Trusted evidence at the raise site | Currently shown to user |
|---|---|---|
| `NEGATED_OR_CONFLICTING_REQUEST` | Whole request text matched a fixed negation/conflict marker | Generic "exact request" message |
| `NO_SIGNATURE_MATCHED` | Zero capability signatures matched the request text | Generic "action selection" message |
| `MULTIPLE_SIGNATURES_MATCHED` | ≥2 capability signatures matched (**which ones is computed, then discarded**) | Generic "action selection" message |
| `SELECTED_CAPABILITY_NOT_UNIQUE_MATCH` | Exactly one signature matched, but it differs from the model's own selected `capability_id` (both ids are known) | Generic "action selection" message |
| `MISSING_ARGUMENT_SPAN` | The capability's fixed marker (e.g. `" schedule "`) does not occur in the normalized request text at all | Generic "exact request" message |
| `AMBIGUOUS_ARGUMENT_SPAN` | Marker occurs more than once, or the text after it isn't a single clean candidate value | Generic "exact request" message |
| `ARGUMENT_VALUE_MISMATCH` | A candidate span was found in the request text, but it doesn't equal the model's own supplied value | Generic "exact request" message |

`core/orchestrator.py::_ask_jarvis_to_ungrounded_message()` collapses all 7 into exactly 2 fixed sentences (`_ACTION_SELECTION_UNGROUNDED_REASONS` = the first three; everything else = the "exact request" message). Neither sentence names the capability, the missing argument, or an example.

### `intelligence.compound_grounding.CompoundUngroundedReason` — exactly 9 members

`NEGATED_OR_CONFLICTING_REQUEST`, `TEMPLATE_NOT_ALLOWED`, `CONNECTOR_MISSING`, `CONNECTOR_REPEATED`, `EMPTY_CLAUSE`, `CLAUSE_NO_SIGNATURE_MATCHED`, `CLAUSE_MULTIPLE_SIGNATURES_MATCHED`, `CLAUSE_CAPABILITY_MISMATCH`, `CLAUSE_ARGUMENT_MISMATCH`. All 9 collapse into **one** fixed message (`_ASK_JARVIS_TO_COMPOUND_UNGROUNDED_MESSAGE`) regardless of which fired.

**Important finding:** `intelligence/schedule_compound_grounding.py`'s own cross-step "the two clauses' schedule ids must match" check (`ground_schedule_compound_decision()`, lines ~243–246) **reuses `CLAUSE_ARGUMENT_MISMATCH`** — the identical enum value already used for "one clause's own argument didn't match its own clause text." The two differing id *values* are known locally at the comparison site but are not attached to the returned reason. **The enum alone cannot distinguish a cross-step id mismatch from an ordinary single-clause mismatch** — a real, working example of "do not merge materially different failures" already existing in the repository today, not merely a risk to avoid introducing.

### `ToolSelectionParseError` reasons (structured_output.py) — 9 fixed strings, generic

Includes, distinctly, `"missing required argument"` and `"invalid argument type"` — both raised inside `_validate_arguments()`, which has `adapter` (hence `capability_id`) and `spec.name`/`spec.type_name` in scope at the raise site, all discarded before the string reaches `PlanningOutcomeKind.INVALID_OUTPUT`.

### The three-way split for "user forgot the argument"

A single real-world situation — "the user's request names no schedule id" — can surface through **three different, model-dependent outcome kinds**, depending only on how the model happens to respond, never on anything Jarvis controls:

1. Model omits the `schedule_id` key entirely (or gives it the wrong type) → `ToolSelectionParseError("missing required argument"/"invalid argument type")` → `INVALID_OUTPUT`.
2. Model invents/hallucinates a `schedule_id` value anyway → parsing succeeds, but `ground_decision()`'s own independent re-extraction from the request text fails → `UNGROUNDED_SELECTION` / `MISSING_ARGUMENT_SPAN`.
3. Model gives up and returns `"unsupported"` → `UNSUPPORTED` (a `success=True`, encouraging-sounding response today).

All three already have distinct, sufficient trusted evidence (capability id + argument spec, or capability id + `UngroundedReason`); none is an internal error. This is the central problem Phase 101 should solve — not by unifying the three code paths, but by giving each one the same small, deterministic, capability-aware translation instead of a generic string.

### `UNSUPPORTED`

Always `success=True`, always the same fixed sentence, regardless of how close the request came to a real capability. Correctly not an error today (Jarvis genuinely found nothing) — but a request that recognizably named a real domain (e.g. "enable schedule" with no id, if the model chose `"unsupported"` instead of trying `"execute"`) gets no more help than a request about something Jarvis has never heard of.

## 4. Trusted-evidence audit per failure class

| Failure class | Trusted evidence available today | Sufficient for safe clarification without guessing? |
|---|---|---|
| Missing required int/str argument (parse-level) | `capability_id`, `CapabilityArgumentSpec.name`/`.type_name` (catalog, already deterministic) | **Yes** |
| Missing required argument (grounding-level, `MISSING_ARGUMENT_SPAN`) | `capability_id` (known at call site), same catalog spec | **Yes** |
| Malformed/ambiguous argument (`AMBIGUOUS_ARGUMENT_SPAN`, `"invalid argument type"`) | `capability_id`, expected type/shape from the catalog | **Yes** |
| Argument value mismatch (`ARGUMENT_VALUE_MISMATCH`) | `capability_id` only (never the candidate span or the rejected value — deliberately withheld today, Section 20.9) | **Explainable only** — a generic "please restate exactly" remains correct; surfacing the specific rejected value would leak a candidate span this module's own docstring says must never be exposed |
| Capability-signature collision (`MULTIPLE_SIGNATURES_MATCHED`) | Presently **discarded** — `_grounded_capability_ids()` computes the matched set but `ground_decision()` only checks its length | **Not today** — would need `ground_decision()` (or a thin wrapper) to retain and return the matched set, a small, narrow, justified typed-evidence extension |
| Model selection not the unique match (`SELECTED_CAPABILITY_NOT_UNIQUE_MATCH`) | Both the model's id and the unique signature match are known locally, then discarded | **Yes, cheaply** — same small extension as above would carry both |
| Negation/conflict | Fixed marker set only; no capability identity at all (checked before signature matching) | **Explainable only, never actionable** — Section 9's own requirement |
| Cross-step schedule-id mismatch (compound) | Both ids known locally, then collapsed into the same enum value as an ordinary single-clause mismatch | **Not today without a small return-value extension** (the two int values, not new inference) |
| Unsupported compound pairing / extra clause / connector issues | `CompoundUngroundedReason` member alone; no captured clause text | **Explainable only** — a fixed corrected-grammar example (not derived from the failure) is safe, since the "two supported compounds" are a closed, hardcoded set |
| Internal parsing failure (malformed JSON, unexpected top-level keys) | Generic, capability-independent | **Must never be shown as user ambiguity** — stays fail-closed/generic |

Classification (per Section 3 of the request):
1. **Safely actionable today, no new typed record needed:** missing/invalid argument (parse- and grounding-level), for the eligible single-argument capabilities.
2. **Safely explainable but not actionable:** argument-value mismatch, negation/conflict, unsupported compound pairing/connector/extra-clause.
3. **Generic fail-closed only:** internal/malformed-output failures, `NO_SIGNATURE_MATCHED`.
4. **Internal error, never user ambiguity:** provider failure, context unavailable, compound-progress infrastructure failure (all already handled by their own distinct, already-correct messages).

Capability-collision (`MULTIPLE_SIGNATURES_MATCHED`/`SELECTED_CAPABILITY_NOT_UNIQUE_MATCH`) and cross-step id mismatch move from class 3 to class 1/2 only if a small, narrow return-value extension is added — evaluated as Candidate E below, and treated as optional, not required, for the recommended V1 scope.

## 5. Candidate comparison

| Criterion | A: Missing Argument | B: Format Correction | C: Collision Explanation | D: Compound Correction | E: Decision-Evidence Foundation | F: Typed Verification | G: Third Compound |
|---|---|---|---|---|---|---|---|
| Trusted evidence already sufficient | **Yes, fully** | **Yes, fully** | No — needs a small extension | No — needs a small extension | N/A (it *is* the extension) | N/A | N/A |
| User-visible value | High (the exact "forgot the id" case in the prompt) | Medium (rarer in practice — models rarely emit a well-typed but wrong-shaped value) | Medium (rare in a 13-capability catalog with disjoint signatures) | Medium (compound requests are already narrow/rare) | None directly | None directly, foundation only | None, duplicates a proven pattern |
| Implementation size | Small | Small | Medium (grounding return-shape change) | Small–medium | Medium, and only justified if A/B need it (they don't) | Small, but scope-irrelevant here | Large |
| Regression risk | Low (additive only) | Low | Low–medium (touches `ground_decision()`'s return path) | Low | Low if kept ephemeral | N/A | Medium (new live wiring) |
| Safety/determinism | High — no guessing, catalog-only | High | High | High | High | High | Neutral |
| Compatible with Verified Action Context boundary | Yes, trivially (no context involved at all) | Yes | Yes | Yes | Yes | N/A | N/A |
| Migration needed | None | None | None | None | None if ephemeral | N/A | None |

**Candidate F (typed verification)** is excluded from recommendation for the same reason Phase 100 excluded it: it is a real, independently valuable, but *causally unrelated* improvement — nothing in Sections 2–4 above ever needed it. **Candidate G (third compound)** is excluded: nothing in this audit found ambiguity handling to require a new compound shape, and a third compound would duplicate the existing per-template lifecycle cost documented in Phase 100's own audit without addressing ambiguity at all.

## 6. Recommended Phase 101 objective

**Candidates A + B, combined as one objective: "Missing/Invalid Required-Argument Guidance."** Both are fully supported by evidence that already exists at the exact point of failure, for a small, explicit allowlist of capabilities (Section 14), requiring no new typed decision-evidence record, no return-shape change to `ground_decision()`, and no new persistence.

**Candidate C and D are deferred**, not rejected: both are real and safe, but each needs the same small, narrow "retain what's already computed instead of discarding it" extension to `ground_decision()`/`ground_schedule_compound_decision()`'s own return values — worth doing later, as its own small, separately-reviewed batch, once A/B's translation-layer pattern is proven in production. Retaining and returning an already-computed local value (the matched-signature set; the two differing ids) is not "hidden reasoning" or "typed verification" — it is Section 16's own encouraged narrow evidence capture — but bundling it into V1 would repeat the exact mistake Phase 100's own amendment corrected: combining two large candidates for convenience the evidence does not require. Following that same discipline, **Phase 101 V1 does not touch `ground_decision()`'s or `ground_schedule_compound_decision()`'s return shape at all.**

## 7. Eligible issue kinds

Two members only, matching exactly what Section 4 proved sufficient:

- `MISSING_REQUIRED_ARGUMENT` — parse-level (`ToolSelectionParseError("missing required argument")`) or grounding-level (`UngroundedReason.MISSING_ARGUMENT_SPAN`) for an eligible capability.
- `INVALID_ARGUMENT_FORMAT` — parse-level (`"invalid argument type"`) or grounding-level (`UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN`) for an eligible capability.

Every other listed candidate value (`AMBIGUOUS_CAPABILITY_MATCH`, `CONFLICTING_REQUEST`, `NEGATED_ACTION`, `UNSUPPORTED_COMPOUND`, `COMPOUND_ARGUMENT_MISMATCH`, `UNSUPPORTED_REQUEST`, `INTERNAL_SELECTION_FAILURE`) is explicitly **not** added in V1 — each either needs the deferred extension (Section 6) or is already correctly generic/fail-closed and must stay that way (negation, conflict, internal failure, unsupported-with-no-signal).

## 8. Eligible capabilities (Section 14 of the request)

| Capability | Argument | Type | Risk tier | Unique signature | Safe retry example | Include in V1? |
|---|---|---|---|---|---|---|
| `SCHEDULE_ENABLE` | `schedule_id` | int | YELLOW | Yes | `ask jarvis to: enable schedule <schedule id>` | **Yes** — one int arg, one YELLOW write |
| `SCHEDULE_DISABLE` | `schedule_id` | int | YELLOW | Yes | `ask jarvis to: disable schedule <schedule id>` | **Yes** — proves the pattern generalizes to a second capability sharing the same argument shape |
| `SCHEDULE_SHOW_ENABLED_STATE` | `schedule_id` | int | GREEN | Yes | `ask jarvis to: check the enabled state of schedule <schedule id>` | **Yes** — one GREEN read, proves approval-warning suppression |
| `MEMORY_SEARCH` | `value` | str | GREEN | Yes | `ask jarvis to: search my memories for <search text>` | **Yes** — one string arg, one GREEN read |
| `PROJECT_STATE_UPDATE_PHASE` | `value` | str | YELLOW | Yes | `ask jarvis to: update my project phase to <phase value>` | **Yes** — one YELLOW write, one string arg |
| `PROJECT_STATE_UPDATE_FOCUS` | `value` | str | YELLOW | Yes | `ask jarvis to: update my project focus to <focus value>` | Deferred — identical shape to `PROJECT_STATE_UPDATE_PHASE`; adding it teaches nothing new about the design and only grows the allowlist. Add trivially in Batch 2 once the pattern is proven, not required to prove it. |

**V1 eligible set: `SCHEDULE_ENABLE`, `SCHEDULE_DISABLE`, `SCHEDULE_SHOW_ENABLED_STATE`, `MEMORY_SEARCH`, `PROJECT_STATE_UPDATE_PHASE`** — five capabilities, covering one int argument, one string argument, one GREEN read, and two YELLOW writes, exactly the required breadth, kept small per Section 13's explicit preference for a bounded allowlist.

## 9. Exact typed object design

```python
class ActionableIssueKind(Enum):
    MISSING_REQUIRED_ARGUMENT = "missing_required_argument"
    INVALID_ARGUMENT_FORMAT = "invalid_argument_format"

@dataclass(frozen=True, slots=True)
class ActionableDecisionIssue:
    kind: ActionableIssueKind
    capability_id: CapabilityId          # always set - always known and trusted
    argument_name: str                   # from CapabilityArgumentSpec.name, catalog-derived
    argument_type_name: str              # "int" | "str", catalog-derived
    retry_example: str                   # fixed, allowlisted template - never AI text
    requires_approval: bool              # from CapabilityAdapter.max_execution_tier == YELLOW
```

No field for model rationale, raw prompt text, raw exception text, or a candidate/rejected value. `capability_id`/`argument_name`/`argument_type_name`/`requires_approval` are all sourced from `CAPABILITY_CATALOG` (already-trusted, hand-maintained data); `retry_example` comes only from a new, small, fixed dict (Section 11), never generated.

**Integration point:** `PlanningOutcome` gains one new optional field, `actionable_issue: ActionableDecisionIssue | None = None`, populated only when the failing capability is in the V1 allowlist and the failure is one of the two eligible kinds. `kind` stays `INVALID_OUTPUT`/`UNGROUNDED_SELECTION` exactly as today for every other case — this is strictly additive, so every existing caller/test that only reads `kind`/`detail` is unaffected. This is the smallest possible integration point: no new `PlanningOutcomeKind` member, no branching change in `core/orchestrator.py`'s existing kind-dispatch `if` chain beyond one added check before the existing generic message is built.

## 10. Exact deterministic wording rules

One new, narrow formatter, `_format_actionable_issue_message(issue: ActionableDecisionIssue) -> str`, colocated with `core/orchestrator.py`'s existing message constants (not a new module — this is pure string assembly from an already-fully-trusted object, the same class of work `_ask_jarvis_to_ungrounded_message()` already does).

Fixed structure (Section 12 of the request):

```
I need the {argument_display_label} before I can prepare this action. Try: {retry_example}. {approval_clause}
```

- `argument_display_label`: a small, fixed dict keyed by `(capability_id, argument_name)` → e.g. `"schedule ID"`, `"search text"`, `"phase value"` — never the raw catalog `argument_name` string verbatim (`schedule_id` is not user-facing wording).
- `approval_clause`: `"Enabling/disabling a schedule will still require approval."` (or the capability-specific equivalent) when `requires_approval` is true; the empty string when false — never a generic "this may require approval" hedge, since the tier is a known, trusted fact.
- No “I think you meant”, “probably”, capability ids, enum names, or parser terminology anywhere in the output — enforced by a dedicated test that greps the rendered string for a fixed denylist of internal terms.

## 11. Retry-example source

A new, small, fixed dict, `_RETRY_EXAMPLE_BY_CAPABILITY: dict[CapabilityId, str]`, one literal per V1-eligible capability (Section 8's own table), each containing a `<placeholder>` where the value is unknown. Never templated from the live request, never touched by Verified Action Context, never generated by a model. Lives beside `ActionableDecisionIssue`'s construction site (`intelligence/planning.py`), not inside `intelligence/capability_catalog.py` — Section 13's own "prefer a bounded allowlist over editing every capability" conclusion.

## 12. Negation/conflict handling

Unaffected by this phase: negation is detected *before* signature matching even runs (Section 2, step 5), so an `ActionableDecisionIssue` is structurally never constructed for a negated/conflicting request — there is no capability_id to attach one to yet, and `NEGATED_OR_CONFLICTING_REQUEST` is not in the V1 eligible-issue-kind set (Section 7). The existing fixed, neutral `_ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE` continues to be shown, unchanged. A dedicated regression test proves `"do not enable schedule 5"` never produces a retry example.

## 13. Verified Action Context boundary

`ActionableDecisionIssue` is constructed entirely from `capability_id` (already validated against the live request by grounding) and `CAPABILITY_CATALOG` (static). It has no reference to `AssembledContext`, `ContextAssembler`, or `VerifiedActionContextBuilder` anywhere in its construction path. A dedicated adversarial test creates a verified `schedule_id=12` entry in Verified Action Context, sends `"ask jarvis to: enable schedule"` (no id), and asserts the resulting message still says the schedule ID is missing and never mentions `12`.

## 14. Approval boundary

`ActionableDecisionIssue` construction happens entirely inside `select_tool()`, before `core/orchestrator.py` ever reaches its approval/execution dispatch — the same point `UNGROUNDED_SELECTION`/`INVALID_OUTPUT` already return at today, with zero preflight, zero `ApprovalManager` call, zero progress-store write. `requires_approval` is a read-only fact copied from the catalog, never a live approval creation. A dedicated test asserts zero `PendingApprovalStore`/progress-store rows exist after a clarification response.

## 15. Live-flow integration point

```
1. current request text                      (unchanged)
2. AIRouter.route()                          (unchanged)
3. parse_tool_selection() / ground_decision() (unchanged logic; call site gains one small wrapper)
4. on eligible failure: build ActionableDecisionIssue from capability_id + catalog (new, ~30 lines, intelligence/planning.py)
5. PlanningOutcome.actionable_issue set        (new optional field)
6. core/orchestrator.py: one new check before the existing INVALID_OUTPUT/UNGROUNDED_SELECTION message construction (new, ~10 lines)
7. no approval, no execution                  (unchanged)
```

**Files expected to change in a future implementation batch:**
- `intelligence/planning.py`: `ActionableIssueKind`, `ActionableDecisionIssue`, `_RETRY_EXAMPLE_BY_CAPABILITY`, `_ARGUMENT_DISPLAY_LABEL_BY_CAPABILITY`, one small helper called from the two existing failure branches inside `select_tool()`, `PlanningOutcome.actionable_issue` field.
- `core/orchestrator.py`: one new formatter function, one new check ahead of the existing generic-message construction for `INVALID_OUTPUT`/`UNGROUNDED_SELECTION`.
- No change to `intelligence/grounding.py`, `intelligence/structured_output.py`, `intelligence/compound_grounding.py`, `intelligence/schedule_compound_grounding.py`, `intelligence/capability_catalog.py`, `intelligence/context.py`, `intelligence/verified_action_context.py`, `ai/*`, `workflow/*`, `approval/*`, or `storage/models.py`.

No second AI call anywhere in this flow.

## 16. Telemetry/explainability boundary

`ActionableDecisionIssue` is ephemeral — constructed, used to build one message, and discarded, exactly like `GroundingResult`/`ToolSelectionParseError` are today. **No persistence in V1.** It records only already-catalog-derived facts (capability id, argument name/type, a fixed example, a fixed approval fact) — never chain-of-thought, never raw model text. If a future phase wants durable clarification analytics, that is an independent, separately-justified decision outside this phase's scope.

## 17. Expected files

See Section 15. No new file is strictly required; `ActionableIssueKind`/`ActionableDecisionIssue` are small enough to live in `intelligence/planning.py` beside `PlanningOutcomeKind`/`PlanningOutcome`, which they extend.

## 18. Migration conclusion

**None.** No new table, no new column, no schema change of any kind. `PlanningOutcome` gains one new optional dataclass field — a Python-level, backward-compatible change (every existing construction of `PlanningOutcome` omits it, defaulting to `None`).

## 19. Privacy/security analysis

- Every field of `ActionableDecisionIssue` is sourced from either the static `CAPABILITY_CATALOG` or a small fixed local dict — never from raw model output, raw request text spans, or any stored/historical content.
- The one field that could theoretically leak something request-derived — a rejected argument *value* — is deliberately never included (Section 4's `ARGUMENT_VALUE_MISMATCH` row stays in the "explainable only" class specifically to preserve `intelligence/grounding.py`'s own existing "never expose a candidate/rejected span" contract, Section 20.9).
- No prompt-injection surface is added: nothing user- or model-supplied is ever interpolated into the rendered message.

## 20. Focused test plan

**Classification:** missing int argument (`SCHEDULE_ENABLE`, both the parse-level and grounding-level paths independently), missing string argument (`MEMORY_SEARCH`), malformed int (`AMBIGUOUS_ARGUMENT_SPAN`), invalid type at parse level, empty string, negation (no issue constructed), conflict (no issue constructed), unsupported compound (unaffected, still generic), cross-step id mismatch (unaffected, still generic — explicitly deferred), internal/malformed-JSON failure (still fully generic, no issue constructed, dedicated test proving `ActionableDecisionIssue` is never populated for this class).

**Retry guidance:** exact wording per eligible capability; exact fixed example string equality (not merely "contains"); no substring of the rendered message ever equals raw model output; YELLOW capabilities always carry the approval clause; GREEN capabilities never do; a capability outside the V1 allowlist (e.g. `PROJECT_STATE_UPDATE_FOCUS`) never receives an example even on an otherwise-identical missing-argument failure — falls back to today's generic message untouched.

**Trust boundaries:** Verified Action Context adversarial test (Section 13); current request remains authoritative (the issue is always built from the *current* call's own `capability_id`/failure, never a stored one); zero `PendingApprovalStore` rows; zero progress-store rows; zero `WorkflowEngine`/`ToolExecutor` calls; zero verification-gate interaction.

**Regression:** every existing `intelligence_planning`/`grounding`/`structured_output`/`compound` test suite passes unchanged (the new field is additive and optional); Phase 98/99 compound behaviour unchanged; Phase 100 Verified Action Context unchanged; `CommandRouter` untouched (this feature is `ask jarvis to:`-only, has no deterministic-grammar counterpart); no Prompt Studio change; no migration; no new capability; no third compound.

## 21. Proposed batch structure

Two batches, mirroring this codebase's own established "dormant foundation, then live wiring" convention where it adds real value, adapted since this feature has no meaningful dormant-vs-live split (it only ever affects a refusal message, never execution):

- **Batch 1 — Deterministic issue classification and message formatting.** Add `ActionableIssueKind`/`ActionableDecisionIssue`/the two fixed dicts/the formatter, wired directly into `select_tool()`'s two existing failure branches and `core/orchestrator.py`'s existing dispatch, for the five-capability allowlist (Section 8). Full test suite from Section 20. This *is* the live behaviour — there is no separate integration batch needed, since the change is confined to a refusal message with no approval/execution surface to activate afterward.
- **Batch 2 — Closure.** Documentation (`docs/user_guide.md` honest description of the new guidance, matching Phase 100's own precedent), `docs/phase_101_completion_report.md`, full three-environment validation, formal closure. `PROJECT_STATE_UPDATE_FOCUS` may be added to the allowlist here if Batch 1's pattern proves stable, at zero design cost (identical shape to `PROJECT_STATE_UPDATE_PHASE`).

Given the small size of Batch 1 itself, the user may prefer a single combined batch; either is compatible with this design.

## 22. Explicit non-goals

- No typed verification.
- No third compound workflow.
- No stateful/pending clarification persistence or table.
- No arbitrary multi-turn plan memory ("12" is never bound to a prior incomplete request in V1).
- No second AI call to generate or rephrase clarification text.
- No hidden reasoning storage or exposure.
- No Verified Action Context expansion or new source.
- No Prompt Studio change.
- No dashboard change.
- No browser/computer automation.
- No expansion of the capability catalog's own schema (no new required field added to every entry) — only two small, new, standalone lookup dicts scoped to the five-capability allowlist.
- No change to `CommandRouter`'s deterministic grammar.
- No exposure of a rejected argument value, a candidate span, model rationale, or parser/enum terminology to the user.

## 23. Stop conditions (checked against this audit — none triggered)

- Clarification cannot be produced without guessing intent — **not triggered**: both eligible issue kinds are built entirely from already-trusted catalog data.
- A safe retry example cannot be generated deterministically — **not triggered**: fixed per-capability templates suffice.
- The architecture cannot distinguish user ambiguity from internal failure — **not triggered**: `ToolSelectionParseError`/`UngroundedReason` already separate them cleanly; internal/malformed-JSON failures stay generic by design.
- Stateful pending intent is required for any useful behaviour — **not triggered**: retry guidance alone (Section 5's audit, request explicitly anticipates this) is useful and sufficient for V1; no trusted mechanism exists today to safely bind a bare follow-up like `"12"` to a prior request without trusting conversational context as tool input, creating a new durable store, or risking stale/confused pending state — so V1 correctly stays stateless.
- Clarification requires historical context to become trusted input — **not triggered**: `ActionableDecisionIssue` never references Verified Action Context.
- Approval would need to be created before full grounding — **not triggered**: no approval is ever created for a clarification response.
- The design requires a migration or generic event framework — **not triggered**: fully ephemeral, additive-only.
- Successful request behaviour would need broad changes — **not triggered**: every existing `EXECUTABLE*`/`UNSUPPORTED` path is completely untouched.
- Phase 98/99/100 would regress — **not triggered**: no file any of those phases depend on is touched.
- No single narrow candidate clearly provides enough value — **not triggered**: Candidates A+B together directly solve the exact example in this phase's own prompt (`"enable schedule"` → a concrete, correct retry example) using zero new inference.

## 24. Why this should be done before typed verification or a third compound

Typed verification (Candidate F, and Phase 100's own deferred Candidate A) is a real architectural improvement, but it removes a workaround (`enabled_str`) that already works correctly today — its value is entirely future-facing, and nothing audited in this phase depends on it. A third compound (Candidate G) would duplicate a proven pattern at real, already-measured linear cost (Phase 100's own audit: ~4,800+2,700+2,400 lines across the schedule compound's own three batches) while addressing zero ambiguity cases. Actionable-ambiguity guidance, by contrast, directly improves the reliability of *every* existing capability against a weaker or less careful model, is provably safe (no new trust boundary crossed), and costs less to build than either alternative — the same "smallest, highest-leverage, already-supported-by-evidence" standard Phase 100's own amendment applied to typed verification applies here to Candidates C, D, F, and G.

---

**This document is pending review. It has not been committed. No Phase 101 implementation has begun.**
