# Phase 97 — Compound Request Grounding Foundation (Planning Gate, Amended)

Status: **planning gate only**. No production code changed. This
amendment supersedes the version committed at `aa4792c`, which
proposed adding a new `"execute_sequence"` literal directly to the
existing, live decision schema and used unordered set equality to
"prove" clause order - both defects are corrected below. The accepted
title and general direction (a non-live-wired foundation proving one
trusted, hand-authored two-capability template can be parsed,
grounded, and safely rejected) are unchanged.

## 0. Summary of what changed in this amendment

1. **Isolation defect fixed.** The compound decision type, parser, and
   grounding function now live in two wholly new, separate modules
   that the live path never imports. The existing `ToolSelectionDecision`
   enum does **not** gain an `"execute_sequence"` member; the existing
   `parse_tool_selection()` continues to reject that string exactly as
   it does today, with zero code change.
2. **Ordering defect fixed.** The compound template allowlist is an
   ordered tuple of ordered pairs, never a `frozenset`. Grounding no
   longer compares an unordered matched-signature set against the
   declared pair (a check that could not actually detect reversed
   order, since it evaluated signatures against the *whole* request
   text regardless of clause position). It now splits the request into
   two ordered clauses by a single fixed connector and grounds each
   clause independently against its own template position.
3. Production scope shrank as a result: **zero existing production
   file is modified at all** (not three, as the prior version
   proposed) - both new pieces live in two brand-new files, imported by
   nothing the live path touches.

## 1. Current repository checkpoint

- Branch: `phase-4-ai-reasoning-and-write-actions`.
- Starting HEAD (before any Phase 97 planning): `d7d16ff`.
- Prior Phase 97 planning commit being amended: `aa4792c`.
- Verified baseline: 756 focused tests (capability catalog, structured
  output, grounding, planning, approval manager, workflow engine,
  pending-approval store, paused-workflow store, trusted workflow
  foundation, verification, and the three orchestrator workflow test
  files) all passed, re-confirmed during the prior planning gate and
  unaffected by this amendment (no production file changes).
- `dashboard_test.txt` remains untouched, untracked, uncommitted.

## 2. Existing live parser isolation (Planning defect 1)

### 2.1 Inspection

Direct, live inspection (not assumption) of
`intelligence/structured_output.py` confirms:

- `ToolSelectionDecision` is a two-member `Enum`: `EXECUTE = "execute"`,
  `UNSUPPORTED = "unsupported"`.
- `parse_tool_selection()`'s decision handling is exactly:
  ```python
  decision_raw = parsed_json["decision"]
  if decision_raw == "execute":
      decision = ToolSelectionDecision.EXECUTE
  elif decision_raw == "unsupported":
      decision = ToolSelectionDecision.UNSUPPORTED
  else:
      raise ToolSelectionParseError("unknown decision value")
  ```
  Any string other than these two exact literals - including
  `"execute_sequence"` - already falls through to the `else` branch and
  raises today, with **no code change required** to keep rejecting it.
- `intelligence/planning.py`'s `_TRUSTED_PLANNING_INSTRUCTION` only ever
  echoes `"execute"`/`"unsupported"` as valid response shapes; it
  contains no compound/sequence wording of any kind.
- `core/orchestrator.py` only ever consumes `PlanningOutcome`/
  `PlanningOutcomeKind` values `select_tool()` itself produces, all of
  which stem from the single-capability schema.

**Conclusion: adding `"execute_sequence"` as a literal accepted by the
*existing*, shared `ToolSelectionDecision`/`parse_tool_selection()`
would be a live-behavior change to the most heavily audited trust
boundary in the codebase - even though, mechanically, the *rest* of
`parse_tool_selection()`'s validation logic would still reject a
two-capability payload today (since `capability_id` is validated as a
single string). The correctness risk is that a live decision type must
never be given a member the live parser does not fully, safely handle
end-to-end; growing that enum for a decision shape the rest of the
function does not understand is the kind of change this planning
amendment exists to prevent.**

### 2.2 Required final design

Two wholly new, separate modules - never edited into the existing
files:

- `intelligence/compound_structured_output.py` (new file):
  - `CompoundToolSelectionDecision` - its own `Enum` with exactly one
    member, `EXECUTE_SEQUENCE = "execute_sequence"`. This is a
    **distinct Python type** from `ToolSelectionDecision`; the two
    share no class relationship, no common base beyond `Enum` itself,
    and no instance of one is ever compared with or substitutable for
    the other.
  - `ParsedCompoundToolSelection` - its own frozen dataclass (mirrors
    `ParsedToolSelection`'s shape, but is a distinct class).
  - `CompoundToolSelectionParseError` - its own exception class (mirrors
    `ToolSelectionParseError`'s bounded-reason contract, but is a
    distinct class, so a caller can never confuse a compound parse
    failure with a live single-capability one via `except` clauses).
  - `parse_compound_tool_selection(raw_text, catalog, allowed_templates)` -
    the only entry point; never aliased as, wrapped by, or exposed
    through `parse_tool_selection()`.
- `intelligence/compound_grounding.py` (new file):
  - `CompoundTemplate`, `_ALLOWED_COMPOUND_TEMPLATES`,
    `CompoundGroundingResult`, `CompoundUngroundedReason`,
    `ground_compound_decision()` (full design in Section 3).

**Reuse strategy (what may safely be imported, one direction only):**
both new modules may import already-existing, pure, stateless helper
functions - `intelligence.structured_output._validate_arguments()`
(and its own small helpers) for argument-shape validation, and
`intelligence.grounding._normalize()`, `_padded()`, `_tokenize()`,
`_contains_negation_marker()`, `_grounded_capability_ids()`,
`_extract_argument_span()`, `_extract_numeric_argument_span()`,
`_ARGUMENT_MARKER_BY_CAPABILITY`, and
`_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY` for request-text evaluation.
Every one of these is a pure function of already-real strings/data,
with **zero coupling to which decision literals the live schema
accepts** - reusing them avoids duplicating already-audited logic
without importing anything that could let the live parser's own
accepted literal set change. The import direction is strictly one-way:
`compound_structured_output.py`/`compound_grounding.py` may import
from `structured_output.py`/`grounding.py`; neither existing file, nor
`intelligence/planning.py`, nor `core/orchestrator.py`, may ever import
anything from either new file (proved structurally - Section 9).
Whether the reused helpers are imported as-is (currently
underscore-prefixed) or first promoted to non-underscore, explicitly
shared utility names is an implementation-time decision, not a
planning-gate one - either way changes no existing behavior.

**What must remain byte-for-byte unchanged:** `ToolSelectionDecision`,
`ParsedToolSelection`, `ToolSelectionParseError`,
`parse_tool_selection()`, `_TRUSTED_PLANNING_INSTRUCTION`,
`select_tool()`, every `PlanningOutcomeKind`, and every existing
`core/orchestrator.py` code path. None of these files are edited by
this phase at all.

## 3. Ordered clause grounding (Planning defect 2)

### 3.1 Why the prior design was wrong

The version committed at `aa4792c` proposed: "the matched signature set
must equal exactly `frozenset(capability_ids)`." This is defective for
two independent reasons:

1. A `frozenset` has no order - comparing two frozensets can never
   distinguish `(A, B)` from `(B, A)`.
2. More fundamentally, `_grounded_capability_ids(request_text)` was to
   be evaluated against the **whole** request string. Swapping the
   order of two clauses in the text (e.g. "show project state and then
   update phase to 97" vs. "update phase to 97 and then show project
   state") produces the *identical* whole-text matched-signature set
   either way, since both capabilities' tokens are present somewhere in
   the text regardless of which clause they sit in. The prior design
   could not have detected reversed order at all, structurally, no
   matter how its equality check was written.

### 3.2 Corrected design

`_ALLOWED_COMPOUND_TEMPLATES` becomes an **ordered tuple of ordered
templates**, never a `frozenset`:

```python
@dataclass(frozen=True, slots=True)
class CompoundTemplate:
    template_id: str
    steps: tuple[CapabilityId, CapabilityId]  # position matters
    connector: str  # the one fixed, padded connector this template splits on

_ALLOWED_COMPOUND_TEMPLATES: tuple[CompoundTemplate, ...] = (
    CompoundTemplate(
        template_id="project_state_update_phase_then_show",
        steps=(
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            CapabilityId.PROJECT_STATE_SHOW,
        ),
        connector=" and then ",
    ),
)
```

`steps` is a 2-tuple - tuple equality is positional, so
`(PHASE, SHOW) != (SHOW, PHASE)` structurally; no set is ever used
anywhere in this design. "Expected argument-bearing step" and
"expected zero-argument step" are **derived, never duplicated**, from
each step capability's own already-trusted
`CAPABILITY_CATALOG[capability_id].arguments` tuple (empty means
zero-argument) - avoiding a second, independently-maintained copy of
data the catalog already owns.

`ground_compound_decision()`'s algorithm, run in this exact order:

1. Reject on the existing negation gate
   (`_contains_negation_marker(request_text)`), applied once to the
   whole request, unchanged.
2. Look up `(steps[0], steps[1])` (the declared, *structured* order) as
   a member of `_ALLOWED_COMPOUND_TEMPLATES` by exact positional tuple
   match. Not found (including the reversed pair) →
   `TEMPLATE_NOT_ALLOWED`. This alone already rejects a *structurally*
   reversed declaration, before any text is even examined.
3. Split the live request into exactly two ordered clauses using the
   matched template's own `connector` (Section 4). Failure here →
   `CONNECTOR_MISSING` / `CONNECTOR_REPEATED` / `EMPTY_CLAUSE`.
4. For **each** clause, independently, at its own fixed position `i`:
   compute `_grounded_capability_ids(clause_text)` (the existing,
   unchanged, whole-catalog signature evaluator - now applied to one
   clause's text alone, not the whole request):
   - empty → `CLAUSE_NO_SIGNATURE_MATCHED`;
   - more than one → `CLAUSE_MULTIPLE_SIGNATURES_MATCHED` (this is also
     how an embedded third action inside a clause is caught - Section
     6);
   - exactly one, but not equal to `template.steps[i]` →
     `CLAUSE_CAPABILITY_MISMATCH` (this is also how a text-level
     reversed order is caught: swapping the clauses swaps which
     clause's own text evidences which capability, so the position
     check now genuinely fails when the request is reversed, unlike
     the prior whole-text design).
5. For each clause whose expected capability declares an argument
   marker (`_ARGUMENT_MARKER_BY_CAPABILITY`/
   `_NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY`, keyed by
   `template.steps[i]`), extract that clause's own candidate span and
   require it to exactly equal the structured step's own already-
   validated argument value, exactly reusing
   `_extract_argument_span()`/`_normalize_for_argument_comparison()`.
   Failure → `CLAUSE_ARGUMENT_MISMATCH`. **This is evaluated only
   against that one clause's own text** - the other clause's text is
   never consulted for this step's value (directly closing "text in
   clause 2 must never supply, complete, alter, or ground the phase
   value").
6. All checks pass → `CompoundGroundingResult(grounded=True)`.

This design makes "reject reversed order even when both capability
names are otherwise present" true in **two independent, redundant**
ways: a structurally-reversed declared pair fails step 2 before any
text is read; a text-reversed request (with a correctly-declared pair)
fails step 4's per-position check. Neither relies on set equality
anywhere.

## 4. Exact request template

- Exact normalized template:
  `"update phase to <value> and then show project state"`.
- Exact fixed, padded connector: `" and then "` (one leading and one
  trailing space, mirroring the existing padding convention already
  used for negation markers and argument markers elsewhere in
  `intelligence/grounding.py`).
- Splitting algorithm (mirrors `_extract_argument_span()`'s own
  established count/find/strip technique exactly): pad the whole
  already-`_normalize()`d request with one leading and trailing space
  (as `_padded()` already does for negation markers); `count()` the
  connector in the padded text - zero occurrences →
  `CONNECTOR_MISSING`; more than one → `CONNECTOR_REPEATED`; otherwise
  split at the single occurrence into two substrings, `.strip()` each
  - either side empty → `EMPTY_CLAUSE`.
- Confirmed against current Phase 92/96 grounding rules: `"update"` and
  `"phase"` are `PROJECT_STATE_UPDATE_PHASE`'s existing action/domain
  tokens (Phase 96); `" to "` is its existing, unchanged value marker
  (Phase 90/96); `"show"` and the adjacent phrase `"project state"` are
  `PROJECT_STATE_SHOW`'s existing action token/domain phrase (Phase
  90/92). No new token, phrase, or marker is introduced for either
  capability - only the new, compound-only `" and then "` connector is
  new, and it is scoped entirely to the new module. **No conflict with
  existing signature or value-attribution behavior was found**; the
  exact template is accepted as specified, with no broadening.
- No alternative connector (plain `and`, `then` alone, a comma, a
  semicolon, `after that`) is ever recognized - the splitting function
  looks for the one exact literal `" and then "` and nothing else, so a
  plain `" and "` naturally produces zero occurrences (`CONNECTOR_MISSING`)
  without any extra rejection logic being needed.
- No inference of order from word position outside this one exact
  connector - order is established solely by which side of the single
  `" and then "` occurrence a clause falls on, per Section 3.

## 5. Ordered clause grounding - clause-specific detail

### Clause 1 (must uniquely ground `PROJECT_STATE_UPDATE_PHASE`)

- Contains the required `"update"` action token and `"phase"` domain
  token (Section 4).
- Contains exactly one `" to "` value marker (reusing
  `_extract_argument_span()` unchanged, applied to clause 1's own text).
- Produces one exact, non-empty phase value, using the existing
  `_normalize_for_argument_comparison()` normalization and
  single-trailing-terminal-punctuation policy, unchanged.
- Rejects negation (whole-request gate, Section 3 step 1), an internal
  `" or "` alternative within the value span (reusing
  `_extract_argument_span()`'s own existing check unchanged), and any
  ambiguity (more than one `" to "` occurrence, or an empty span).
- Must match the structured step 1 `value` exactly
  (`CLAUSE_ARGUMENT_MISMATCH` otherwise).
- **The phase value is attributed only from clause 1's own text.**
  Clause 2's text is never passed to the value-extraction step for
  clause 1 under any circumstance - the two clauses are evaluated as
  fully separate strings from the moment they are split (Section 4),
  and clause 1's argument check only ever receives clause 1's own
  substring.

### Clause 2 (must uniquely ground `PROJECT_STATE_SHOW`)

- Contains the accepted `"show"` action token and the adjacent phrase
  `"project state"` (Section 4).
- Exposes exactly zero arguments -
  `PROJECT_STATE_SHOW` has no entry in
  `_ARGUMENT_MARKER_BY_CAPABILITY`, so no value-extraction step ever
  runs for this clause; its structured step's `arguments` must simply
  be `{}` (enforced at the parser level, Section 7).
- Must match structured step 2 exactly (capability id only - it has no
  argument to compare).
- Must not contain another attributable executable argument: since
  `_grounded_capability_ids(clause_2_text)` must evaluate to exactly
  `{PROJECT_STATE_SHOW}` (Section 3 step 4), any additional real action
  embedded in clause 2's own text (e.g. "...and list schedules") is
  independently caught as `CLAUSE_MULTIPLE_SIGNATURES_MATCHED` before
  any argument question even arises.

## 6. Extra-signature refusal

Every clause is evaluated against the **complete** current user-facing
signature catalogue via the unchanged, fully generic
`_grounded_capability_ids()` - never only against its own expected
capability's signature in isolation, exactly mirroring the existing
single-capability rule's own "never merely check the selected
capability's signature in isolation" philosophy.

Worked refusals for the task's five required examples (all evaluated
against the one worked template, `PROJECT_STATE_UPDATE_PHASE` →
`PROJECT_STATE_SHOW`):

1. `"update phase to 97 and then show project state and list
   schedules"` → clause 2 text is `"show project state and list
   schedules"`, which matches both `PROJECT_STATE_SHOW` and
   `SCHEDULE_LIST` → `CLAUSE_MULTIPLE_SIGNATURES_MATCHED`.
2. `"update phase to 97 and then show project state and show recent
   memories"` → clause 2 matches both `PROJECT_STATE_SHOW` and
   `MEMORY_LIST_RECENT` → `CLAUSE_MULTIPLE_SIGNATURES_MATCHED`.
3. `"show project state and then update phase to 97"` → clause 1 text
   is `"show project state"`, which uniquely matches `PROJECT_STATE_SHOW`,
   not the expected position-1 capability
   (`PROJECT_STATE_UPDATE_PHASE`) → `CLAUSE_CAPABILITY_MISMATCH`
   (reversed order, caught at the text level).
4. `"update focus to testing and then show project state"` → clause 1
   text uniquely matches `PROJECT_STATE_UPDATE_FOCUS` (action
   `"update"` + domain `"focus"`), not the expected
   `PROJECT_STATE_UPDATE_PHASE` → `CLAUSE_CAPABILITY_MISMATCH`. (This
   request would also never reach grounding in practice, since its own
   correctly-declared structured pair would have to be
   `(PROJECT_STATE_UPDATE_FOCUS, PROJECT_STATE_SHOW)`, which is not a
   member of `_ALLOWED_COMPOUND_TEMPLATES` and is already rejected as
   `TEMPLATE_NOT_ALLOWED` before clause splitting runs - both layers
   independently refuse this request, by design, in depth.)
5. `"update phase to 97 and then show schedules"` → clause 2 text
   uniquely matches `SCHEDULE_LIST`, not the expected
   `PROJECT_STATE_SHOW` → `CLAUSE_CAPABILITY_MISMATCH`.

No extra supported action is ever silently ignored - every clause's
full signature set is checked, every time.

## 7. Exact compound structured schema

```json
{
  "decision": "execute_sequence",
  "steps": [
    {"capability_id": "project_state_update_phase", "arguments": {"value": "..."}},
    {"capability_id": "project_state_show", "arguments": {}}
  ]
}
```

- Top level: exactly the two keys `{"decision", "steps"}` - any extra
  top-level key (e.g. a stray `"context"` or `"capability_id"` at the
  top) is rejected.
- `"decision"` must equal exactly `"execute_sequence"` (the
  `CompoundToolSelectionDecision`'s own one member) - any other value
  is rejected by this parser (it is not a fallback for the existing
  `"execute"`/`"unsupported"` values, which this parser never accepts
  either).
- `"steps"` must be a JSON array of **exactly two** entries - fewer or
  more are rejected.
- Each entry must itself be a JSON object (a non-object entry, e.g. a
  string or array, is rejected) with **exactly** the two keys
  `{"capability_id", "arguments"}` - a missing key, or an extra key
  (e.g. a stray `"tier"`, `"verifier_id"`, or `"approval_required"`),
  is rejected.
- `capability_id` must name a real `CAPABILITY_CATALOG` member that is
  not `internal_only` - an unknown string or an internal-only
  capability (e.g. `project_state_verify_focus`,
  `schedule_verify_enabled_state`) is rejected.
- The two steps' `capability_id`s must be distinct - a duplicate (the
  same capability declared twice) is rejected before any allowlist or
  grounding check runs.
- `arguments` must be a JSON object, validated against that specific
  step's own declared `CapabilityArgumentSpec` tuple by reusing
  `intelligence.structured_output._validate_arguments()` unchanged -
  every existing rule (unknown argument name, missing required
  argument, wrong type, oversized/empty/control-character string) is
  reused verbatim, per step.
- This parser never checks `_ALLOWED_COMPOUND_TEMPLATES` membership
  itself - that is `ground_compound_decision()`'s own first check
  (Section 3), mirroring how the existing single-capability parser
  never performs grounding either.

## 8. Internal verifier exclusion

- A compound declaration may name only user-facing capabilities -
  `parse_compound_tool_selection()` rejects any `internal_only`
  capability in either position (Section 7), exactly reusing the
  existing `adapter.internal_only` check `parse_tool_selection()`
  already applies to a single capability.
- `PROJECT_STATE_UPDATE_PHASE`'s own existing, fixed internal verifier
  (`PROJECT_STATE_VERIFY_FOCUS`, reused per Phase 96) is **not** a
  third compound step and is never declared by the model in this
  design. The compound pair here names exactly two **user-facing
  goals** - update the phase, then show the record - both independently
  real, selectable capabilities today.
- `PROJECT_STATE_UPDATE_PHASE`'s own future trusted execution lifecycle
  (its existing `TWO_STEP_WORKFLOW` write-then-verify shape) is
  entirely unrelated to and untouched by this compound foundation.
  Should a future phase ever wire this template into real execution,
  that internal verifier would still run as part of
  `PROJECT_STATE_UPDATE_PHASE`'s own existing write step - it is never
  counted as, declared as, or confused with a third compound capability.
- Phase 97 itself still executes, approves, persists, and verifies
  nothing (Sections 12-16).

## 9. Bounded failure taxonomy

**Parser-level** (`CompoundToolSelectionParseError`, raised before
grounding ever runs): malformed JSON/schema (reusing the existing
2,000-char cap, single-fence-stripping, and duplicate-key rejection
unchanged), wrong step count, non-object step container, missing
`capability_id`, missing/malformed `arguments`, extra top-level or step
fields, unsupported (unknown) capability id, internal-only capability
declared, duplicate capability declared, and every existing argument
validation failure reused from `_validate_arguments()`.

**Grounding-level** (`CompoundGroundingResult`/`CompoundUngroundedReason`,
a new, separate enum - never extending the existing `UngroundedReason`):

- `NEGATED_OR_CONFLICTING_REQUEST` - whole-request negation gate.
- `TEMPLATE_NOT_ALLOWED` - declared, ordered pair is not a member of
  `_ALLOWED_COMPOUND_TEMPLATES` (also the first, structural line of
  defense against a reversed pair).
- `CONNECTOR_MISSING` - the fixed `" and then "` connector is absent.
- `CONNECTOR_REPEATED` - the connector occurs more than once.
- `EMPTY_CLAUSE` - either side of the single connector occurrence is
  empty after trimming.
- `CLAUSE_NO_SIGNATURE_MATCHED` - a clause's text matches zero
  catalogue signatures.
- `CLAUSE_MULTIPLE_SIGNATURES_MATCHED` - a clause's text matches more
  than one catalogue signature (the extra-signature-present case,
  Section 6).
- `CLAUSE_CAPABILITY_MISMATCH` - a clause's text uniquely matches
  exactly one signature, but not the one its template position
  expects (the reversed-order-in-text case, Section 3.2/6).
- `CLAUSE_ARGUMENT_MISMATCH` - a clause's own extracted value span does
  not exactly equal its structured step's already-validated argument.

No public wording is added in Phase 97 - none of this taxonomy is ever
surfaced to a user; it exists only for this phase's own internal test
assertions (mirroring how `UngroundedReason` itself is never shown
verbatim to a user today).

## 10. Live-behavior isolation

Phase 97 has zero live behavior. This is required to be proven, not
merely asserted:

- `_TRUSTED_PLANNING_INSTRUCTION`'s exact text is unchanged (a
  hash/string-equality regression test against its known-good content).
- `select_tool()`'s own source contains no reference, by AST inspection,
  to `compound_structured_output` or `compound_grounding` - no import
  statement, no `ast.Name`/`ast.Attribute` naming either module or any
  symbol from it.
- `core/orchestrator.py`'s own source is checked the same way - no
  import, no reference.
- No approval is ever created, no workflow is ever persisted, no
  `ToolExecutor.execute()` call ever occurs, and no verifier ever runs,
  as a direct, structural consequence of the above: nothing in the live
  call graph reaches the new modules at all.
- `tools/builtin/help_tool.py` and `docs/user_guide.md` are not
  modified - there is no compound command to document.
- Every existing single-capability request behaves identically - proved
  by re-running the full existing test suites for
  `structured_output.py`/`grounding.py`/`planning.py`/`orchestrator.py`
  unmodified (Section 17) and confirming the unchanged baseline.
- No dead branch is added to any live runtime file - the two new
  modules are never imported by any live file, so there is no branch
  to add in the first place.

## 11. Immediate concrete consumer

This foundation is justified only because it has one explicit,
near-term consumer: **a separately approved first bounded compound
execution for exactly `PROJECT_STATE_UPDATE_PHASE` → `PROJECT_STATE_SHOW`**,
to be planned and implemented in a future phase once this foundation's
own test suite is in place and stable. That future phase is not
planned in detail here (it remains Option C from the prior planning
gate, deliberately deferred).

**`intelligence/compound_structured_output.py` and
`intelligence/compound_grounding.py` must not be generalized to a
second template, a longer allowlist, or any live wiring before that
consumer phase is separately proposed and approved.** If, at
implementation time, no such near-term consumer is actually intended,
the correct action is to **reject Phase 97 outright** rather than build
unused production architecture - this plan's own justification for
existing at all rests entirely on that one named, concrete future
consumer.

## 12-16. Execution, approval, persistence, verification, restart/resume

Unchanged from the prior version of this plan: **none of these are
exercised this phase.** No `Plan` is built, no `ApprovalRequest` is
created, nothing is persisted, no `VerificationResult` is produced, and
there is nothing to restart or resume, since nothing ever executes.

## 17. Required production files

**None.** Two brand-new files only:

- `intelligence/compound_structured_output.py` (new).
- `intelligence/compound_grounding.py` (new).

Every existing production file - `intelligence/capability_catalog.py`,
`intelligence/structured_output.py`, `intelligence/grounding.py`,
`intelligence/planning.py`, `intelligence/verification.py`,
`core/orchestrator.py`, `workflow/engine.py`,
`workflow/paused_workflow_store.py`, `approval/approval_manager.py`,
`security/security_manager.py`, `tools/executor.py`, `main.py`,
`docs/user_guide.md`, `tools/builtin/help_tool.py` - remains completely
untouched.

## 18. Required test files

Two brand-new test files, mirroring the two new production files (not
extensions of existing test files, to keep the "no existing test file
changes" story trivially provable):

- `tests/unit/test_compound_structured_output.py` (new).
- `tests/unit/test_compound_grounding.py` (new).

Plus one small, new, structural isolation test file (or a dedicated
section inside one of the two above):

- `tests/unit/test_compound_isolation.py` (new) - houses the AST-based
  import/reference checks (Section 10).

## 19. Required tests

### Existing parser isolation
1. Full existing `test_structured_output.py` suite passes unmodified.
2. A new test proves `parse_tool_selection()` raises
   `ToolSelectionParseError("unknown decision value")` for
   `{"decision": "execute_sequence", ...}` - and that this required
   zero code change to achieve.
3. A new test asserts `_TRUSTED_PLANNING_INSTRUCTION` contains neither
   `"execute_sequence"` nor `"steps"` as a JSON-shape reference.
4. An AST-based test asserts `intelligence/planning.py` contains no
   import of, or reference to, `compound_structured_output` or
   `compound_grounding`.
5. An AST-based test asserts `core/orchestrator.py` contains no import
   of, or reference to, either new module.

### Compound parser
6. The exact allowed two-step schema (Section 7) parses successfully.
7. One step, and three steps, both reject (wrong step count).
8. Reversed structured order, `(PROJECT_STATE_SHOW,
   PROJECT_STATE_UPDATE_PHASE)`, rejects during grounding
   (`TEMPLATE_NOT_ALLOWED`).
9. The same capability declared in both positions rejects (duplicate).
10. An internal-only capability (either verifier) in either position
    rejects.
11. An extra top-level field and an extra step field both reject.
12. A wrong argument type (e.g. an int for `value`) rejects, reusing
    `_validate_arguments()`.
13. Existing strict per-capability argument schemas (required/optional,
    string hygiene, size cap) are proven reused, not reimplemented, via
    a shared-function-identity or behavior-equivalence test.

### Ordered request template
14. The exact `"update phase to <value> and then show project state"`
    template grounds successfully for the one worked template.
15. No connector present rejects (`CONNECTOR_MISSING`).
16. The connector appearing twice rejects (`CONNECTOR_REPEATED`).
17. An empty first clause (`"and then show project state"`) rejects.
18. An empty second clause (`"update phase to 97 and then"`) rejects.
19. Plain `" and "` (no `"then"`) rejects (`CONNECTOR_MISSING`, no
    special-cased logic needed).
20. `"show project state and then update phase to 97"` rejects
    (`CLAUSE_CAPABILITY_MISMATCH`, text-level reversed order).
21. Each of the five worked extra-signature examples (Section 6)
    rejects with the documented reason.

### Clause grounding
22. Clause 1 uniquely grounds `PROJECT_STATE_UPDATE_PHASE`.
23. Clause 1's exact value matches structured step 1's `value`.
24. Clause 2 uniquely grounds `PROJECT_STATE_SHOW`.
25. Clause 2 accepts exactly zero arguments (a non-empty `arguments`
    for step 2 rejects at the parser level, Section 7).
26. A phase value present only in clause 2's own text (never clause 1's)
    is never attributed to clause 1 - `CLAUSE_ARGUMENT_MISMATCH`.
27. `ground_compound_decision()` never accepts an `AssembledContext`
    parameter at all - proven by its own signature, mirroring
    `ground_decision()`'s existing contract.
28. A negated/conflicting compound request refuses
    (`NEGATED_OR_CONFLICTING_REQUEST`).
29. A wrong phase value (matching neither clause 1's text nor a
    plausible variant) refuses (`CLAUSE_ARGUMENT_MISMATCH`).
30. An "expanded" phase value (declared value is a superset of the text
    span, or vice versa) refuses (`CLAUSE_ARGUMENT_MISMATCH`), exactly
    reusing today's exact-equality rule.
31. A structured pair naming `PROJECT_STATE_UPDATE_FOCUS` (or any other
    ProjectState field) instead of `PROJECT_STATE_UPDATE_PHASE` rejects
    at the parser/allowlist layer (`TEMPLATE_NOT_ALLOWED`) - only the
    one worked template is ever supported.
32. The full, existing `test_grounding.py` suite passes unmodified -
    single-capability grounding behavior is untouched.

### No side effects
33. No `SecurityManager.classify_action()` call occurs anywhere in
    either new module (grep/AST-based).
34. No `ApprovalManager` reference of any kind in either new module.
35. No `PausedWorkflowStore`/`PendingApprovalStore` reference in either
    new module.
36. No `ToolExecutor` reference in either new module.
37. No `intelligence.verification` reference in either new module.
38. No `JarvisResponse` is ever constructed by either new module.
39. `docs/user_guide.md` and `tools/builtin/help_tool.py` have zero
    diff versus their current committed content.

## 20. Implementation scope reassessment

A small, one-batch Phase 97 remains fully justified after these
corrections - if anything, more so than before, since the corrected
design touches **zero existing production files** (versus the prior
version's three):

- New: `intelligence/compound_structured_output.py`,
  `intelligence/compound_grounding.py`.
- New tests: `test_compound_structured_output.py`,
  `test_compound_grounding.py`, `test_compound_isolation.py`.
- New docs: `docs/phase_97_completion_report.md`.

No existing single-capability decision type, parser, `select_tool()`,
planning control flow, orchestrator, `SecurityManager`,
`ApprovalManager`, workflow persistence, `ToolExecutor`, verification,
`main.py` wiring, user guide, or help output is modified. If
implementation discovers this scope cannot actually be held (for
example, if a genuinely new shared type turns out to be unavoidable),
the correct action is to **stop and recommend combining this
foundation with its first concrete execution consumer in a later,
larger phase instead** - not to weaken the isolation guarantee to fit
one phase.

## 21. Non-goals (unchanged, reaffirmed)

No live wiring into `select_tool()` or the trusted planning
instruction; no `Plan`/`WorkflowEngine` execution; no approval,
persistence, or verification of any compound request; no arbitrary
capability pairing beyond the one hand-authored template; no change to
any existing capability, tool, verifier, or the existing
single-capability decision path; no second template; no schedule
creation, memory save, browser/Word/computer/phone control,
shell/Python execution, dashboard change, or voice feature.

## 22. Deferred work (unchanged, reaffirmed)

Wiring the new modules into `select_tool()`/the trusted instruction;
building the actual compound `Plan`/execution/approval/verification
machinery; expanding `_ALLOWED_COMPOUND_TEMPLATES` beyond the one
worked example; the post-execution data-propagation gap from Phase
96's own planning gate (`SCHEDULE_CREATE`/`MEMORY_SAVE`); Option B
(durable sequential workflow foundation, already shown largely
unnecessary given the engine's existing generality) and Option D
(outcome/task context foundation) both remain available, unselected,
future candidates.

## 23. Updated stop conditions

Stop and report a conflict if implementation would require: any
existing production file to change; the existing `ToolSelectionDecision`
or `UngroundedReason` enums to gain a member; any live wiring of the
new modules; a second compound template before the named consumer
phase is approved; unordered-set-based order proof of any kind; a
capability pairing outside the one hand-authored allowlist; an
approval, persisted workflow, `ToolExecutor` call, or verifier call
from either new module; or any user-visible command/help/documentation
change. None of these conditions are triggered by the design in this
amendment.

## 24. Updated acceptance criteria

Phase 97 implementation is acceptance-ready only when all of the
following hold simultaneously: (1) both new modules exist, are mutually
consistent with this plan's exact schema/algorithm; (2) zero diff to
any existing production file; (3) all 39 tests in Section 19 pass; (4)
the full existing suite (5203 passed / 3 skipped / 0 failed baseline)
is reproduced exactly, in all three required environments; (5) Ruff
and `git diff --check` are clean; (6) the AST-based isolation tests
(items 4, 5, 33-38) pass, structurally proving zero live reachability;
(7) the completion report documents the one named future consumer
(Section 11) and explicitly states no further generalization occurs
before it is separately approved.

## 25. Formal planning-gate conclusion (reaffirmed)

The live architecture does not yet safely support representing more
than one model-selected capability per request; the real blocking
cause remains `intelligence/grounding.py`'s uniqueness rule, not the
execution/persistence/approval layer, which already generalizes past
two steps. This amendment corrects the two defects identified in the
prior planning commit (`aa4792c`) - a live-schema isolation risk and an
order-blind grounding check - by moving the entire foundation into two
new, wholly separate modules the live path never imports, and by
replacing unordered set comparison with a genuinely ordered,
connector-based clause split independently grounded per position. The
design continues to trigger none of this task's stop conditions and
remains small enough for one controlled implementation phase.
