# Durable Workflow Lifecycle Foundation — Completion Report

**Status: prerequisite foundation turn — not a numbered phase, and has not
become one.**

**Scope delivered:** Category-A durable workflow status/history only. No
resumable checkpoints, no workflow replay, no exactly-once execution, no
scheduling, no notifications, no AI planning change.

**Date:** 2026-07-10

---

## 1. Implementation Summary

Three batches, exactly as planned in `docs/durable_workflow_lifecycle_foundation_plan.md`:

- **Batch 1** (commit `ed2b9fd`) — a new, append-only `workflow_history`
  table (`storage/models.py::WorkflowHistoryEntry`) and a new
  `WorkflowHistoryStore` (`workflow/workflow_history_store.py`),
  structurally mirroring the existing `ApprovalHistoryStore`. 17 new unit
  tests against a real in-memory SQLite database.
- **Batch 2** (commit `b0ae539`) — `WorkflowEngine` gains one new,
  optional constructor parameter, `history: WorkflowHistoryStore | None =
  None`, defaulting to `None` for full backward compatibility. Every one
  of the seven existing `workflow_*` lifecycle transitions is now
  additionally recorded durably at the same point the corresponding audit
  event is already emitted, using the identical narrow
  observability-isolation pattern (`try/except Exception: pass`, scoped
  only around the store call). A pre-existing structural invariant test
  (`test_every_except_exception_wraps_only_emit`) was updated, not
  weakened, to assert the same property now holds for both isolation
  blocks. 15 new unit tests, including four proving a raising history
  store can never alter a `COMPLETED`/`WAITING`/`FAILED`/resumed
  `WorkflowResult`.
- **Batch 3** (commit `8743762`) — a new, read-only, GREEN
  `WorkflowHistoryTool` (`tools/builtin/workflow_history_tool.py`),
  mirroring `ApprovalHistoryTool`; two new `CommandRouter` exact phrases
  (`show workflow history`, `show recent workflows`) and one new prefix
  pair (`show workflow <id>` / `view workflow <id>`); `main.py` wiring
  reusing one `WorkflowHistoryStore` instance for both `WorkflowEngine`
  (writer) and the new tool (reader). 33 new tests: 18 tool-level, 10
  router-level, 7 real end-to-end tests (real `SecurityManager`, real
  `ToolExecutor`, real `ApprovalManager`, real `WorkflowEngine`, real
  in-memory SQLite `WorkflowHistoryStore`) proving a real two-step
  workflow's full lifecycle — including a YELLOW pause, approval, and
  resume — becomes queryable through the exact command a user would type.

**Total new tests: 65** (17 + 15 + 33). Full-suite total: **1815 → 1878**
(all passing at every batch boundary; 0 failed throughout).

---

## 2. Architectural Review

**No existing architecture already provided this capability**, confirmed
by direct inspection before any code was written (plan §3): the generic
audit log has no `workflow_id` column; `ApprovalHistoryStore` correlates
only by `request_id` and has no step/tool-name concept;
`WorkflowEngine._paused` is transient by explicit Phase 15 design; no
table anywhere in the repository had `workflow_id` as a column before this
turn.

**Design decisions** (plan §4, re-verified against the delivered code):
append-only per-transition rows (not update-in-place, since a workflow's
transition count is variable, unlike an approval's fixed two-state
shape); the durable `status` column reuses `WorkflowEngine`'s own seven
existing event-name strings verbatim, rather than a second vocabulary
that could drift; durable writes follow the identical narrow
observability-isolation pattern as the audit logger; no new
`SecurityManager` rule was needed (`"show"` already resolves GREEN); the
read surface is an ordinary registered `BaseTool` routed through the
ordinary `CommandRouter` → `ToolExecutor` path, not a CLI-only special
case; no new SQLAlchemy migration helper was needed, since
`workflow_history` is a brand-new table with nothing to backfill.

All of these decisions were followed exactly as planned; no deviation
was found during implementation that required stopping and reporting
(plan §9's guardrail was never triggered).

---

## 3. Specification Compliance

Re-checked against the Master Specification chapters most relevant to
this turn (Ch10 Workflow Engine, Ch29 System Lifecycle, Ch13
Observability):

- Ch10's own checkpoint description ("workflow ID, last completed step
  ID, step outputs, and timestamp") is **partially** realized: this turn
  records workflow ID, step number/total, tool name, and timestamp for
  every transition — a strict superset of per-transition granularity —
  but deliberately omits "step outputs" (i.e., resolved tool_input or
  result payloads) and does not implement the restart-resumption behavior
  Ch10 and Ch29 both describe. This is an intentional, disclosed partial
  realization (Category A only), not a claim of full Ch10/Ch29
  compliance.
- Ch13 Observability's general principle ("every significant action,
  decision, workflow, and system event should be traceable through
  comprehensive logging") is now more fully honored for workflows
  specifically: a workflow's lifecycle is traceable structurally
  (queryable by `workflow_id`), not only through free-text audit `detail`
  strings.
- No change was made to Ch12's Security Manager (GREEN/YELLOW/RED model,
  approval timeouts, prompt-injection defence) or Ch6's Planner chapter
  — neither chapter's behavior is touched by this turn.

---

## 4. Invariants Verification

Every standing invariant named in the authorizing instructions was
re-verified directly against the delivered code, not merely asserted:

- **Deterministic execution**: `WorkflowEngine`'s step sequencing,
  propagation rule, and STOP-only failure policy are byte-for-byte
  unchanged; the only new code path is an additive, side-effect-free
  (from execution's perspective) durable write.
- **Approval model unchanged**: `ApprovalManager` was not modified in
  this turn at all — zero lines changed in `approval/approval_manager.py`.
  `WorkflowEngine`'s pause/resume logic, `_reap_stale_paused()`, and its
  use of `ApprovalRequest.metadata["workflow_id"]` are unchanged; the
  history store only *reads* the already-created `approval_request.request_id`
  to record it for correlation.
- **SecurityManager remains authoritative**: zero lines changed in
  `security/security_manager.py`. `WorkflowHistoryTool`'s action strings
  resolve to GREEN via the pre-existing, unmodified generic `"show"`
  rule — confirmed by direct inspection, not assumed, before writing the
  tool (plan §4.4).
- **No new execution authority granted to AI**: this turn touches no AI
  module (`ai/`) at all — confirmed by `git diff --stat` showing zero
  changes under `ai/`.
- **Auditability preserved**: the pre-existing `workflow_*` audit-event
  family (`WorkflowEngine._emit`/`_emit_step_event`) is emitted exactly as
  before, at every one of the same seven points, with byte-identical
  arguments; the durable history write is additive, never a replacement.
- **Backward compatibility maintained**: `WorkflowEngine.__init__`'s new
  `history` parameter defaults to `None`; every pre-existing Phase 15 test
  (all ~120 of them across `test_workflow_engine.py`,
  `test_cli_workflow_commands.py`, etc.) passes unmodified, proving no
  existing caller's behavior changed. `main.py`'s `build_orchestrator()`
  signature is unchanged; only its internal wiring gained two new lines.

**A raising `WorkflowHistoryStore` can never alter an authoritative
`WorkflowResult`** — the central new invariant this turn introduces —
proven directly by five dedicated tests
(`test_failing_history_store_does_not_alter_*`) covering the
`COMPLETED`, `WAITING`, `FAILED`, and resumed-`COMPLETED` outcomes, plus a
test proving the failure of one isolation boundary (history) does not
suppress the other (the audit logger).

---

## 5. Dependency Analysis

**New dependencies introduced:** none. `WorkflowHistoryStore` reuses the
existing SQLAlchemy/SQLite storage layer (`storage/database.py`,
`storage/models.py`) already used by every other durable store in this
repository (`EpisodicMemoryStore`, `AuditLog`, `ApprovalHistoryStore`).

**New internal dependencies:**
`workflow/engine.py` → `workflow/workflow_history_store.py` (one new
import, the optional `history` collaborator); `tools/builtin/workflow_history_tool.py`
→ `workflow/workflow_history_store.py` (read-only); `core/command_router.py`
gains no new imports (only new string constants and a dispatch branch);
`main.py` gains two new imports (`WorkflowHistoryStore`,
`WorkflowHistoryTool`) and constructs one new instance, reused by both
collaborators — never two separately constructed stores, confirmed by
direct inspection of the final `build_orchestrator()` body.

**No circular dependency risk**: `WorkflowHistoryStore` depends only on
`storage.database`/`storage.models`; it is not depended on by either of
those modules, `ApprovalManager`, or `ToolExecutor`.

---

## 6. Trust-Boundary Verification

No new trust boundary was crossed or created:

- `WorkflowHistoryTool` is fully trusted, first-party code, registered
  exactly like every other built-in tool — no plugin, manifest, or
  external-input surface was introduced.
- The durable history schema has **no column capable of holding
  `tool_input`, resolved step input, or a serialised `Plan`** — verified
  directly in `storage/models.py::WorkflowHistoryEntry` and locked in by
  a dedicated structural test
  (`test_history_row_has_no_replay_fields`) and a call-site-level test
  (`test_history_never_receives_tool_input_or_plan`) proving
  `WorkflowEngine` itself never even attempts to pass such data to the
  store. This means a row in this table cannot become an accidental
  resumption/replay vector no matter how a future feature might try to
  read it — the same deliberate boundary `ApprovalHistoryEntry` already
  established for approvals.
- User-supplied content (memory text) is never written to this table —
  only `tool_name` (a plain identifier), step numbers, statuses, and a
  short, content-free `detail` string, mirroring the existing audit-log
  convention. Confirmed by direct inspection of every `record_transition()`
  call site in `workflow/engine.py`.

---

## 7. Git Verification

- Commits: `ed2b9fd` (Batch 1), `b0ae539` (Batch 2), `8743762` (Batch 3),
  plus this closure commit.
- `git diff --stat da696cb HEAD` (pre-foundation-turn baseline → final):
  13 files changed, 2,079 insertions, 8 deletions (before this closure
  commit's README/report additions) — every changed file classifies as
  required for this turn's own narrow scope (storage model, history
  store, engine wiring, tool, router, `main.py` wiring, tests) or as this
  turn's own documentation. No unrelated file was touched.
- `git diff --check`: exit 0 at every batch boundary (only pre-existing
  LF/CRLF warnings, not new errors).
- Full suite: **1878 passed, 0 failed** at final verification, matching
  the running total after Batch 3.
- Working tree: clean immediately before this closure commit, containing
  only `README.md`, this completion report, and (already committed) the
  plan document's own tracking.

---

## 8. Final Adversarial Self-Review

- **Did this silently broaden scope?** No — the plan's §9 guardrail was
  never triggered; no resumption, replay, idempotency, scheduling, or AI
  change was attempted at any point. The one place a broader design was
  briefly possible (recording *every* step event, not just workflow-level
  start/end) was deliberately kept, since it is still pure Category-A
  observability (no `tool_input`, no resumption capability) and was
  already disclosed in the plan (§4.1) before implementation began.
- **Does the new isolation pattern actually work, or was it merely
  asserted?** Directly tested: five dedicated tests force the failure
  path via a real raising fake store and assert the `WorkflowResult` is
  unchanged; a sixth test proves the two isolation boundaries (logger,
  history) are independent of each other.
- **Could this be mistaken for checkpointing?** Guarded against
  explicitly: the schema has no `tool_input`/plan column (§6), the module
  docstrings and the plan document both state the distinction in the same
  paragraph as the feature description, and a dedicated test
  (`test_history_never_receives_tool_input_or_plan`) makes the boundary
  mechanically checkable, not just documented in prose.
- **Is this genuinely useful, or infrastructure for its own sake?** It
  ships one real, user-typeable command (`show workflow history`) that
  produces a genuinely new, previously-impossible answer ("what happened
  to that workflow, even after a restart") — not a purely internal,
  invisible change.
- **Did any test get weakened to make this pass, rather than the code
  fixed?** No — the one pre-existing test that needed updating
  (`test_every_except_exception_wraps_only_emit`, now
  `..._wraps_only_emit_or_history`) was updated to assert a *stronger*
  property (two narrow isolation blocks, each still exactly one `Pass`
  statement) — not loosened or deleted.
- **Has this become Phase 16?** No. It adds exactly one new read-only
  command family and zero new write authority, zero new AI capability,
  zero scheduling, and zero resumption. It is sized and scoped as a
  maintenance/foundation turn (3 batches, 2,079 lines including tests and
  documentation), consistent with the established
  `docs/retrieval_workflow_maintenance_*` precedent for a non-phase turn,
  not with the 5,883-line, 6-batch scale of Phase 15 itself.

---

## 9. Confirmation

**This work remains only a prerequisite foundation turn. It has not
become, and does not claim to be, Phase 16.** No scheduling, no resumable
checkpoints, no workflow replay, no exactly-once execution, no
notifications, and no AI planning change were implemented. The next
numbered phase remains an open, separately-scoped decision, per
`README.md`'s own "Next Phase" section.
