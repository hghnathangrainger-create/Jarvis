# Phase 17 Implementation Plan — Broader Deterministic Workflow Commands

Status: **Planning only. No production code, tests, or README changes
accompany this document.**

Authoritative repository state this plan builds on, verified directly:
HEAD `bab82899e71b3d0b6025196897945f3bacbf73ee` ("Close Phase 16: web
search end-to-end verification and documentation"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean. `poetry run
pytest -q` — **1947 passed, 0 failed**, re-run fresh for this planning
turn. No pre-existing failure exists.

---

## 1. Purpose

Add exactly two new deterministic, fixed, hand-authored two-step
workflow commands to the existing Sequential Workflow Engine, exactly as
approved by the prior architectural and product-value review: **create
and read back a file**, and **update a memory and show the result**.
Both reuse the exact `WorkflowEngine`, `ToolExecutor`, `SecurityManager`,
and `ApprovalManager` machinery Phase 15 already built, unmodified. This
is a workflow-*command* expansion, not a Planner realization and not an
engine change.

## 2. Scope

**In scope:** two new `workflow_plan_factory.py` functions, two new
`CommandRouter` matchers, two new thin `JarvisOrchestrator` dispatch
handlers reusing the existing shared `_handle_workflow_request` glue, and
full test/documentation coverage.

**Explicitly out of scope**, repeated here for closure-time reference,
exactly as authorized:
`move_and_show`; `create_and_append`; any list-then-act or search-then-act
workflow (memory or file); any history-chaining workflow; any workflow
using `web_search`; any `WorkflowEngine` change (`_PROPAGATED_FIELD`
remains exactly `"memory_id"`; no arbitrary output-field mapping, no
path propagation, no structured result references, no multiple-output
propagation, no template/expression language, no branching, retries,
rollback, or compensation); any new tool or modification to
`file_create`/`file_read`/`memory_update`/`memory` behavior; any AI
involvement of any kind; any new `ApprovalManager` capability (no
workflow-level, batch, implicit, or pre-approval; no approval reuse or
bypass); any checkpoint/resumption/crash-recovery architecture.

## 3. Repository Evidence

Directly inspected this turn, not recalled from memory:

- **`tools/builtin/file_create_tool.py`**: YELLOW (`action_for` always
  returns `"create text file"`); input `path` (required), `content`
  (optional, default `""`); on success, `metadata={"path": ..., "chars_written": ..., "operation": "create"}`.
  **Key finding: this metadata key is `"path"`, not `"memory_id"` —
  `WorkflowEngine` cannot and will not read it.** This workflow's second
  step does not need it to, however (see §5).
- **`tools/builtin/file_read_tool.py`**: GREEN (`action_for` always
  returns `"read file"`); input `path` (required), `max_chars` (optional);
  output is a single formatted string (`"Contents of {path}:\n{text}"`),
  **no metadata at all**.
- **`tools/builtin/memory_update_tool.py`**: YELLOW for both `"update"`
  and `"move"` operations (`action_for` returns `"update memory"` or
  `"move memory"`); the `"update"` operation requires `memory_id` and
  `content`; on success, `metadata={"operation": "update", "memory_id": str(record.id), "category": ...}`.
  **This is the exact field name `WorkflowEngine` already propagates.**
- **`tools/builtin/memory_tool.py`**: the `"get"` operation is GREEN
  (`action_for` returns `"show memory"`), requires `memory_id`, and
  returns the persisted record's own current content directly from
  `MemoryManager.get()` — never an echo of whatever text a prior step
  happened to submit. This is what makes step 2 a genuine, independent
  verification rather than a restatement.
- **`workflow/workflow_plan_factory.py`**: exactly two existing
  functions, each taking only a `content: str` parameter, each
  hardcoding `SecurityTier`/reason constants for display purposes only,
  with zero `SecurityManager`/`ToolExecutor`/`ToolRegistry` dependency.
  This plan's two new functions follow the identical shape.
- **`workflow/engine.py`**: `_PROPAGATED_FIELD = "memory_id"` is a
  module-level constant, read once in `_resolve_tool_input()`. Confirmed
  by direct inspection: this is the **only** field the engine ever
  copies from one step's `tool_result.metadata` into the next step's
  `tool_input`, under the identical key name. No generalization exists
  or is touched by this plan.
- **`core/orchestrator.py`**: `_handle_workflow_request(plan, *, session_id)`
  is already fully generic — it accepts any `Plan` and runs it through
  `WorkflowEngine.run()`, returning a translated `JarvisResponse` via the
  existing, unmodified `_workflow_result_to_response()`. **Both new
  handlers need only call their own factory function and pass the result
  to this exact, already-shared method — no new orchestrator execution
  logic of any kind.** The two existing workflow dispatch checks are
  placed immediately before the generic `_handle_request_core` fallback,
  each returning early only on an actual match; this plan's two new
  checks are added directly after them, in the same position relative to
  the fallback, for the identical reason (preventing the generic
  single-tool dispatch from ever seeing workflow-shaped text).
- **`core/command_router.py`**: `_FILE_CREATE_PREFIXES`,
  `_strip_write_prefix()`, `_split_on_keyword()`, `_clean_path()`, and
  `_extract_create_input()` (which composes the first three) already
  implement exactly the `"<prefix> <path> with <content>"` parse this
  plan's first workflow needs, unmodified. `_extract_memory_id()` and
  the existing `"update memory <id>: <content>"` colon-split (in
  `_build_memory_update_input()`) already implement exactly the parse
  this plan's second workflow needs, unmodified. Both are directly
  reusable, not reimplemented (§7).

## 4. Workflow Factory Design

Two new functions added to `workflow/workflow_plan_factory.py`,
matching the existing two in every structural respect (frozen `Plan`,
hardcoded display-only tier/reason constants, zero
`SecurityManager`/`ToolExecutor`/`ToolRegistry` dependency, no
step-result inspection of any kind):

```python
def build_create_and_read_plan(path: str, content: str) -> Plan:
    """Step 1: file_create with the given path and content (YELLOW).
    Step 2: file_read of the SAME literal path (GREEN) - the factory
    itself holds and reuses `path` for both steps; no engine propagation
    is used or needed, since Nathan already supplied the path directly."""

def build_update_and_show_plan(memory_id: int, content: str) -> Plan:
    """Step 1: memory_update (operation="update") with the given
    memory_id and content (YELLOW). Step 2: memory (operation="get"),
    with input_from_previous_step=True - memory_id is propagated from
    step 1's own metadata via WorkflowEngine's existing, unmodified
    mechanism, exactly as the two Phase 15 templates already do."""
```

**Exact `Plan`/`PlanStep` shapes:**

`build_create_and_read_plan(path, content)`:
- `Plan.user_request = f"create file {path} with {content} and show it"`
- Step 1: `number=1`, `action="create text file"`, `tier=SecurityTier.YELLOW`
  (the exact, already-verified classification `FileCreateTool.action_for()`
  produces), `tool_name="file_create"`, `tool_input={"path": path, "content": content}`,
  `input_from_previous_step=False`.
- Step 2: `number=2`, `action="read file"`, `tier=SecurityTier.GREEN`,
  `tool_name="file_read"`, `tool_input={"path": path}`,
  `input_from_previous_step=False` (**not** `True` — this step does not
  use engine propagation at all; the factory closes over the same
  `path` value for both steps, exactly as both existing templates
  already close over the same `content` value for their own step 1).

`build_update_and_show_plan(memory_id, content)`:
- `Plan.user_request = f"update memory {memory_id}: {content} and show it back"`
- Step 1: `number=1`, `action="update memory"`, `tier=SecurityTier.YELLOW`,
  `tool_name="memory_update"`, `tool_input={"operation": "update", "memory_id": memory_id, "content": content}`,
  `input_from_previous_step=False`.
- Step 2: `number=2`, `action="show memory"`, `tier=SecurityTier.GREEN`,
  `tool_name="memory"`, `tool_input={"operation": "get"}`,
  `input_from_previous_step=True` — identical propagation mechanism to
  `build_remember_and_show_plan`'s own step 2, unchanged.

**Both `tier` values remain exactly what they already are today** —
hardcoded display-only constants confirmed against `SecurityManager`'s
real, unmodified rule table (`"create text file"`/`"update memory"` →
YELLOW; `"read file"`/`"show memory"` → GREEN), never authoritative for
execution, exactly as the module's own existing docstring already
states for the first two templates.

## 5. Command Parsing — Proof of Non-Collision

**This is the most safety-critical part of this plan.** Unlike the two
existing Phase 15 commands (which use a *prefix*-plus-mandatory-colon
shape — the trigger phrase is matched before any free text begins, so
free text after the colon can never be confused with the trigger), both
of this phase's approved commands use a *suffix* shape — the trigger
phrase comes **after** Nathan's own free-form content. This is a
materially different, and inherently more fragile, grammar shape, and
this plan treats it accordingly rather than glossing over the
difference.

**`create file <path> with <content> and show it`:**

- New matcher `CommandRouter.match_create_and_read_workflow(text) -> tuple[str, str] | None`:
  1. Return `None` immediately unless `text` (casefolded) starts with one
     of the existing `_FILE_CREATE_PREFIXES` **and** ends with the exact
     literal suffix `" and show it"` (casefolded comparison, via
     `str.endswith`, checked against the fully stripped text — not a
     substring search, so an occurrence of those words in the *middle*
     of content never triggers anything).
  2. If both hold, remove exactly that trailing suffix (by length, not
     by re-searching) to get the pre-suffix text.
  3. Pass the pre-suffix text directly to the existing, **completely
     unmodified** `_extract_create_input()` classmethod, which already
     implements the `"<prefix> <path> with <content>"` split. **No new
     path/content-splitting logic is written — the existing one is
     reused verbatim.**
- Placement: checked in `JarvisOrchestrator.handle_request()`
  immediately after the two existing workflow checks, before
  `_handle_request_core`. **Proof this does not swallow the standalone
  command**: the standalone `create file <path> with <content>` (with no
  trailing `" and show it"`) fails the `endswith` check in step 1 above
  and returns `None` immediately, falling through to the ordinary,
  completely unmodified generic `match()`/`build_input()` → `file_create`
  path — proven by inspection, not merely asserted, and to be locked in
  by a dedicated regression test (§9) re-confirming the standalone
  command's behavior is byte-for-byte unchanged.
- **Disclosed, honest edge case**: if Nathan's own intended file content
  itself legitimately ends with the literal words "and show it" (for
  example, `create file note.txt with content: please read this and show it`),
  the workflow trigger is indistinguishable from that content and will
  always fire, stripping those literal trailing words from what is
  actually written to the file. This is a genuine, narrow limitation of
  a suffix-triggered grammar and is called out explicitly here, in the
  tool's own test suite (§9), and in the completion report at closure —
  not silently accepted as a non-issue. Given the words are a
  specific, five-word closing phrase, the practical exposure is low, but
  it is not zero, and this plan does not pretend otherwise.
- **Blank path / blank content**: unchanged from today's standalone
  command — `_extract_create_input()` already returns `("", content)` or
  `(path, "")` when either piece is absent, and `FileCreateTool.run()`
  already rejects a blank path with a clear failure while accepting
  blank content (an intentionally empty file). No new validation is
  added at the router level, consistent with the established convention
  that the router extracts as literally as possible and the tool itself
  is the validation authority.
- **Unusual but already-supported path characters**: unchanged — the
  same `_clean_path()` (strip leading "the ", strip surrounding quotes)
  already applied to the standalone command applies identically here,
  since it is the same function.
- **Trailing whitespace**: normalized exactly as today — `_extract_create_input`
  and `_clean_path` already `.strip()` throughout; no new normalization
  rule is introduced.

**`update memory <id>: <content> and show it back`:**

- New matcher `CommandRouter.match_update_and_show_workflow(text) -> tuple[int | None, str] | None`:
  1. Return `None` immediately unless `text` (casefolded) starts with
     `"update memory"` **and** ends with the exact literal suffix
     `" and show it back"` (casefolded, `endswith`-checked against the
     fully stripped text).
  2. If both hold, remove exactly that trailing suffix (by length) to
     get the pre-suffix text.
  3. Apply the existing `_extract_memory_id(pre_suffix_text, "update memory")`
     classmethod (unchanged) to get the id, and the existing
     first-colon-split (`pre_suffix_text.split(":", 1)[1].strip()` when a
     colon is present — the identical logic already used in
     `_build_memory_update_input()`'s own `"update"` branch) to get the
     content.
- Placement: identical position to the file-workflow matcher, directly
  after it, before `_handle_request_core`.
- **Proof this does not swallow the standalone command**: `update memory <id>: <content>`
  with no trailing `" and show it back"` fails the `endswith` check and
  returns `None`, falling through to the ordinary, completely unmodified
  `_build_memory_update_input()` path — the standalone command's own
  behavior, including its `"move memory ... to ..."` sibling shape
  (never touched by either new matcher, since neither checks for a
  `"move memory"` prefix), is unaffected.
- **Disclosed, honest edge case**, identical in kind to the file
  workflow's own: content legitimately ending in the literal words "and
  show it back" cannot be expressed through this exact command shape —
  the trigger will always fire and strip it. Same disclosure discipline
  applies (§9, completion report).
- **Colon handling**: unchanged from today — only the *first* colon
  splits id-context from content, exactly as the existing standalone
  command already behaves; a colon appearing later, inside the content
  itself, is preserved as part of the content, identically to today.
- **Blank content**: unchanged — if no colon is present, or the content
  after the colon is empty after stripping, `content=""` is returned
  (mirroring today's exact behavior), and `MemoryUpdateTool.run()`
  already rejects an empty `content` for the `"update"` operation with a
  clear failure message.
- **Legitimate replacement content is not incorrectly truncated** in the
  general case: only a true trailing match of the exact fixed suffix is
  ever removed, and only once, by length — content containing the
  *words* "and show it back" anywhere except as the literal final
  characters of the message is preserved character-for-character.

**No general quoting or escaping syntax is introduced** — neither
existing convention (`_clean_path`'s quote-stripping, `_clean_content`)
requires one, and this plan does not invent one.

## 6. Security and Approval Authority

- `PlanStep.tier` remains exactly what it already is for both existing
  templates: hardcoded, display-only metadata, **never** read by
  `WorkflowEngine` for any execution decision (confirmed unchanged by
  direct inspection of `workflow/engine.py` — this plan touches none of
  its code).
- At execution, `ToolExecutor.execute()` calls
  `SecurityManager.classify_action(tool.action_for(request))` fresh,
  exactly as it already does for every other step of every other
  workflow — **the factory grants no authority, and the command router
  grants no authority**; both only ever produce a `Plan`/dispatch a
  request, never a security decision or a cached approval.
- Neither new workflow's YELLOW step (`file_create`, `memory_update`)
  changes its own classification, approval requirement, or run
  conditions in any way — both reuse the exact same tool, the exact same
  action string, and the exact same `ToolExecutor`/`ApprovalManager`
  path the standalone commands already use today.
- **No workflow-level, batch, implicit, or pre-approval mechanism is
  added.** Each workflow's YELLOW step independently pauses
  `WorkflowEngine` exactly as `build_remember_and_forget_plan`'s own
  step 2 already does, creates exactly one `ApprovalRequest` via the
  existing, unmodified `ApprovalManager.create_request()`, and resumes
  only through the existing, unmodified `execute_approved()` →
  `WorkflowEngine.resume()` path.

## 7. Trust Model / Input-Origin Table

| Workflow | Field | Origin | Trust classification |
|---|---|---|---|
| `create_and_read` | `path` (both steps) | Nathan's live current-turn text | `JARVIS_TRUSTED` (unchanged from today's standalone `file_create`/`file_read` commands) |
| `create_and_read` | `content` (step 1) | Nathan's live current-turn text | `JARVIS_TRUSTED` |
| `create_and_read` | `operation`/tool-name constants | Jarvis-authored, hardcoded | N/A — not user content |
| `update_and_show` | `memory_id`, `content` (step 1) | Nathan's live current-turn text | `JARVIS_TRUSTED` |
| `update_and_show` | `memory_id` (step 2) | Deterministic engine propagation from step 1's own `metadata["memory_id"]` | Not AI/user content at all — a runtime fact produced by Jarvis's own already-executed, already-approved step |
| `update_and_show` | `operation`/tool-name constants | Jarvis-authored, hardcoded | N/A |

**No stored memory content, file content, web content, tool-generated
freeform text, historical conversation text, or AI-generated content
becomes executable `PlanStep.tool_input` anywhere in either workflow** —
confirmed by the table above accounting for every field of both `Plan`s
with no residual "other" category.

## 8. Failure Semantics and Persistence

- **STOP-only, unchanged**: if step 1 does not succeed (denied approval,
  tool failure, or a RED block that cannot occur here — see below), step
  2 is never attempted, exactly as `WorkflowEngine._stop()` already
  guarantees for every workflow.
- **No RED collision**: `"create text file"` and `"update memory"` are
  both confirmed YELLOW against the current, unmodified `_RULES` table
  (§3); neither this plan nor any future maintenance turn should ever
  need to special-case a RED path here, since the allowlist is
  hand-authored specifically to exclude one.
- **Partial durable side effects are never presented as rolled back**:
  if step 1 succeeds and step 2 fails for any reason (for example, a
  concurrent deletion of the just-created file, or a concurrent forget
  of the just-updated memory), the `WorkflowResult` honestly reports a
  `FAILED` step outcome for step 2 while step 1's real side effect
  (the file on disk; the updated memory row) remains exactly as
  produced — identical in kind to the accepted, already-disclosed race
  class the two existing templates already carry.
- **Crash behavior**: unchanged from today. A crash mid-workflow leaves
  any already-completed step's durable side effect intact, records
  whatever lifecycle transitions occurred up to that point in the
  already-shipped `WorkflowHistoryStore` (Durable Workflow Lifecycle
  Foundation), and does not resume automatically — this plan introduces
  no checkpoint or resumption architecture of any kind.
- **Observability isolation**: both workflows emit exactly the same
  seven `workflow_*` audit events and the same durable history
  transitions every existing workflow already emits, through the
  completely unmodified `WorkflowEngine._emit`/`_emit_step_event`/`_record_history`
  methods — no new isolation code is needed or written.

## 9. Batch Plan

### Batch 1 — Factory Functions and Unit Tests

- **Purpose**: add the two new deterministic `Plan` builders and prove
  their exact shape in isolation, with zero command-routing or
  orchestrator involvement yet.
- **Production files**: `workflow/workflow_plan_factory.py` (extended).
- **Test files**: `tests/unit/test_workflow_plan_factory.py` (extended):
  exact `Plan.user_request` text; exactly two steps; consecutive step
  numbers (1, 2); exact `tool_name` per step; exact `tool_input` per
  step; exact `input_from_previous_step` per step (`False, False` for
  `create_and_read`; `False, True` for `update_and_show`); exact
  `tier`/`reason` values, explicitly re-asserted as **non-authoritative
  display metadata only** (mirroring the existing module's own such
  tests); confirmation neither function imports or calls
  `SecurityManager`/`ToolExecutor`/`ToolRegistry` (an AST-based
  structural test, mirroring the existing module-level guarantee already
  proven for the first two templates).
- **Invariants protected**: factory purity (no execution, no
  classification, no side effect at construction time); tier values
  match the real `SecurityManager` rule table (cross-checked, not just
  asserted).
- **Non-goals**: no command parsing, no orchestrator wiring, no
  `WorkflowEngine` execution in this batch.
- **Verification commands**: `poetry run pytest tests/unit/test_workflow_plan_factory.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, e.g. "Add create-and-read and
  update-and-show workflow plan factories (Phase 17 Batch 1)".

### Batch 2 — Command Parsing, Routing, and Orchestrator Dispatch

- **Purpose**: make both workflows reachable end-to-end through exact
  command text, reusing the existing `_handle_workflow_request` glue
  unchanged.
- **Production files**: `core/command_router.py` (two new matchers,
  §5), `core/orchestrator.py` (two new thin handler methods mirroring
  `_handle_remember_and_show_back_workflow_request`/`_handle_remember_and_forget_workflow_request`
  exactly, plus two new dispatch checks placed directly after the
  existing two, before `_handle_request_core`).
- **Test files**: `tests/unit/test_command_router.py` (extended): exact
  valid command recognition for both; path/content and
  memory-id/content extraction; exact suffix requirement (a text
  missing the suffix does not match); the standalone `file_create` and
  `update memory` commands remain byte-for-byte unchanged (regression);
  nearby non-matching variants (missing suffix, different suffix
  wording, suffix as a `move memory` command) correctly do not trigger
  either workflow; adversarial command-like path/content strings never
  change what is extracted (extraction is purely positional/textual,
  never content-aware). `tests/unit/test_orchestrator_workflow_commands.py`
  (extended): dispatch order confirmed via direct test (a workflow-shaped
  request never reaches `_handle_request_core`'s generic path); approval
  pause/resume coverage for both new workflows' YELLOW step, mirroring
  the existing `remember_and_forget` coverage exactly.
- **Invariants protected**: `SecurityManager` remains the sole
  classification authority (verified live, not assumed, via a real
  `ToolExecutor` in these tests); no approval bypass of any kind exists.
- **Non-goals**: no new tool, no engine change, no README yet.
- **Verification commands**: `poetry run pytest tests/unit/test_command_router.py tests/unit/test_orchestrator_workflow_commands.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, e.g. "Add command routing and
  orchestrator dispatch for create-and-read and update-and-show
  workflows (Phase 17 Batch 2)".

### Batch 3 — End-to-End Verification, Adversarial Tests, Documentation, Closure

- **Purpose**: prove the full real stack (real `SecurityManager`, real
  `ToolExecutor`, real `ApprovalManager`, real `CommandRouter`, real
  `WorkflowEngine`, a real temp-directory filesystem and a real
  in-memory SQLite `MemoryManager` — never a fake at this level) end to
  end, adversarially test the trust/security properties claimed in §6–§7,
  document, and close.
- **Production files**: none expected; any narrowly-justified correction
  found during this batch's own review will be disclosed, not silently
  applied.
- **Test files**: `tests/integration/test_create_and_read_workflow_end_to_end.py`
  (new) and `tests/integration/test_update_and_show_workflow_end_to_end.py`
  (new), covering every item in §15 below, including: YELLOW pause at
  step 1 for both; denial stops the workflow with no side effect; approval
  resumes and completes step 2; step 2 genuinely re-reads/re-fetches
  persisted state rather than echoing step 1's input (proven by
  asserting the *tool*, not the factory, produced the final displayed
  text); partial-failure honesty; durable workflow-history transitions
  recorded correctly; logger/history-store failure isolation (reusing
  the already-proven fakes from the Durable Workflow Lifecycle
  Foundation's own test suite); adversarial content (RED/YELLOW keyword
  strings, command-like text) never changes classification or escapes as
  anything other than inert data; no AI path is invoked at any point; no
  web-search participation exists anywhere in either workflow.
- **Documentation**: `README.md` (new "Phase 17" section, following the
  established per-phase style — command table, safety note, explicit
  non-goals, including the disclosed suffix-ambiguity edge case from
  §5); `docs/phase_17_implementation_plan.md` (this document, tracked at
  this point per the established convention); `docs/phase_17_completion_report.md`
  (new, at closure, covering every item in §19 below).
- **Invariants protected**: full-stack proof that neither workflow can
  ever grant AI authority (none exists to grant), bypass approval, or
  leak untrusted content into executable input.
- **Non-goals**: no scope beyond verification, adversarial testing, and
  documentation.
- **Verification commands**: `poetry run pytest tests/integration/test_create_and_read_workflow_end_to_end.py tests/integration/test_update_and_show_workflow_end_to_end.py -v`, then full `poetry run pytest -q`, `git diff --check`, `git status`.
- **Commit boundary**: one commit for closure documentation and any
  narrowly-justified correction, staging only the files this batch
  actually touches.

## 10. Testing Requirements (Consolidated)

Every item from the authorizing instructions' §15 is covered across
Batches 1–3 above; restated here as a checklist for closure verification:
exact `Plan` shape and step count/order/tool names/inputs/propagation
flags (Batch 1); routing exactness, suffix recognition, standalone
regression, non-collision with nearby variants, content-independence of
classification (Batch 2); full execution lifecycle including approval
pause/resume/denial, genuine re-verification (not echo), partial-failure
honesty, history correctness, and logger isolation (Batch 3); the full
adversarial security/trust set — RED/YELLOW keyword content, file-read
output never becoming later executable input, stored content never
choosing the next step, no AI path, no web-search participation, no
approval bypass (Batch 3).

## 11. Plan-vs-Master-Specification Reconciliation

Classified explicitly, per the authorizing instructions:

- This phase is **deterministic fixed workflow expansion** — two more
  hand-authored, fixed-shape `Plan` builders, structurally identical to
  the two Phase 15 already shipped.
- This phase is **not the full Planner** (Ch6) — no dependency
  resolution, no parallel execution, no resource estimation, no dynamic
  replanning, no retries are added or approximated.
- This phase is **not AI-assisted planning** — no AI call, no AI-facing
  context, no structured AI output, no allowlist exposed to any model.
- This phase is **not generalized workflow composition** — the
  `_PROPAGATED_FIELD` limitation (§12) is a real, disclosed architectural
  boundary, not silently worked around; no template/expression language
  of any kind is introduced.

No divergence from the Workflow Engine chapter, tool architecture,
security model, approval model, or AI-authority invariants exists — both
new workflows reuse already-classified, already-approved actions and the
already-shipped propagation mechanism, unchanged, exactly as Phase 15's
own two templates already do.

## 12. Known, Disclosed, Deliberately Deferred Architectural Pressure Point

**`WorkflowEngine` propagates only `metadata["memory_id"]` — a single,
hardcoded field name, not a generic output-to-input mapping
mechanism.** This is the direct reason `file_create`'s own `metadata["path"]`
cannot be engine-propagated into `file_read`'s step (worked around here
by the factory sharing the literal `path` value across both steps
instead — a solution that only works because Nathan already supplies
the path himself; it would not generalize to a case where the value is
only known after step 1 actually runs). This is documented here as a
known composition limitation for any future workflow-expansion turn to
read before assuming a new workflow "should just work" — **it is not
fixed in Phase 17**, and no future workflow requiring genuine
runtime-produced-value propagation beyond `memory_id` can be built
without first, separately, and deliberately deciding whether and how to
generalize this mechanism.

## 13. Adversarial Planning Review

- **Does the existing standalone command parser swallow the workflow
  suffix?** No — proven by the dispatch-order argument in §5: the new
  matchers are checked first and return `None` (falling through)
  whenever the exact suffix is absent, so the standalone parser only
  ever sees text the workflow matcher has already declined.
- **Can "and show it" inside legitimate file content cause truncation?**
  Only when it is the literal, exact trailing text of the whole command
  — a disclosed, narrow, honestly-documented edge case (§5), not a
  silent bug.
- **Can "and show it back" inside legitimate memory content cause
  truncation?** Same answer, same disclosure.
- **Are these workflows merely echoing Nathan's input instead of
  independently verifying persisted state?** No — `file_read` re-reads
  from the filesystem; `memory` `"get"` re-fetches via `MemoryManager.get()`
  from the database. Neither step's output is templated from the
  factory's own held values; both are proven, in Batch 3, to originate
  from the tool's own independent lookup.
- **Is `create_and_read` actually reading the created file after
  approval?** Yes — step 2 only runs after step 1's `ToolResult.success`
  is `True`, per `WorkflowEngine`'s own unmodified STOP-only loop;
  proven end-to-end in Batch 3 by asserting the read-back content
  matches what was actually written to disk, not merely what the
  factory was given.
- **Does `update_and_show` truly use runtime `memory_id` propagation?**
  Yes — `input_from_previous_step=True` on step 2, using the exact,
  unmodified mechanism `build_remember_and_show_plan` already relies on;
  proven in Batch 3 via a test asserting propagation still functions
  even if the factory were (hypothetically) given a different id than
  what step 1 ultimately confirms — not applicable in practice since
  the id doesn't change across the update, but the mechanism itself is
  exercised identically to the existing template's own test coverage.
- **Is any untrusted read content becoming executable input?** No —
  confirmed by the input-origin table (§7): `file_read`'s output is
  never read back into any `tool_input` anywhere in this plan.
- **Did we accidentally add a generic propagation mechanism?** No —
  `create_and_read` uses factory-level literal sharing (not engine
  propagation at all); `update_and_show` uses the exact, single,
  pre-existing `memory_id` mechanism, unchanged.
- **Did we weaken YELLOW approval semantics?** No — §6 confirms both
  YELLOW steps use the identical, unmodified `ToolExecutor`/`ApprovalManager`
  path as their standalone command counterparts.
- **Can partial side effects be misrepresented as rollback?** No — §8
  explicitly requires `WorkflowResult` to honestly report a partial
  outcome; no rollback claim is made or implied anywhere in this plan.
- **Are workflow history transitions still truthful?** Yes — both
  workflows emit the same, already-proven-correct seven-event family and
  durable history rows, unmodified.
- **Did we add these workflows merely to inflate the future AI
  allowlist?** No — the prior architectural/product review explicitly
  evaluated and scored these two on their own standalone merits, and
  explicitly declined to recommend AI-assisted planning as a
  consequence of this expansion.
- **Are the commands still fixed deterministic commands rather than a
  hidden workflow language?** Yes — exactly two new fixed phrases, each
  parsed by directly reusing existing, unmodified extraction functions;
  no new grammar rule, wildcard, or parameterized template syntax of any
  kind is introduced.

## 14. Final Summary

- **Final approved command grammar**: `create file <path> with <content> and show it`; `update memory <id>: <content> and show it back`.
- **Final factory signatures**: `build_create_and_read_plan(path: str, content: str) -> Plan`; `build_update_and_show_plan(memory_id: int, content: str) -> Plan`.
- **Exact `Plan`/`PlanStep` shapes**: as specified in full in §4.
- **Exact input-origin table**: as specified in full in §7.
- **Exact security/approval behavior**: unchanged `SecurityManager`/`ApprovalManager`/`ToolExecutor` paths, per-step, live, every time (§6).
- **Exact propagation behavior**: `create_and_read` uses factory-level literal sharing, no engine propagation; `update_and_show` uses the existing, sole `memory_id` engine mechanism, unchanged (§4, §12).
- **Final batch sequence**: Batch 1 (factories) → Batch 2 (routing/dispatch) → Batch 3 (end-to-end/adversarial/documentation/closure), per §9.
- **Explicit Phase 17 non-goals**: repeated in full in §2.
- **Likely architectural pressure points discovered but deliberately deferred**: the single-field (`memory_id`-only) propagation limitation (§12) — disclosed, not fixed.

## 15. Closure Expectations (For the Eventual Completion Report)

At closure, `docs/phase_17_completion_report.md` must verify and
reconcile, at minimum: plan versus implementation; Master Specification
reconciliation (§11); workflow factory authority (unchanged,
non-executing, non-classifying); `SecurityManager` authority (live,
per-step, unchanged); `ApprovalManager` authority (per-action, unchanged,
no new capability); the full input-origin/trust-boundary table (§7),
re-verified against the delivered code; confirmation `_PROPAGATED_FIELD`
remains exactly `"memory_id"` and untouched; confirmation no AI
involvement exists anywhere in the delivered code; confirmation no
web-search participation exists; confirmation no new tool was added or
modified; confirmation no engine generalization occurred; full backward
compatibility (every pre-existing test passes unmodified); and every
explicit non-goal from §2, checked individually, not merely asserted in
aggregate.
