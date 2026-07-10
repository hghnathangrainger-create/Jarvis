# Durable Workflow Lifecycle Foundation — Implementation Plan

Status: **Authorized prerequisite foundation turn — not a numbered phase.**

**This is explicitly not Phase 16.** It adds no scheduling, no resumable
checkpoints, no workflow replay, no exactly-once execution, no AI planning
change, and no new user-facing workflow command grammar. It is a narrow,
Category-A-only (durable status/history) closure of a gap the
post-Phase-15 architectural review (previous turn) identified: a paused or
completed workflow's lifecycle is currently visible only in-memory and in
the generic, unstructured audit log — never in a structured, queryable,
workflow-scoped form. Naming this "Phase 16" would misrepresent it as the
next capability phase, which it deliberately is not — see
`docs/retrieval_workflow_maintenance_plan.md` for the established precedent
of naming a non-capability turn outside the phase-numbering convention.

Authoritative repository state this plan builds on, verified directly:
HEAD `da696cbf7edcb3c4f5b008ceecee524c5a7328d7` ("Close Phase 15: sequential
workflow execution documentation and review"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean. `poetry run
pytest -q` — **1815 passed, 0 failed** — re-run fresh for this planning
turn. No pre-existing failure exists.

---

## 1. Purpose

Make a workflow's lifecycle (started, each step's outcome, paused,
resumed, completed, or stopped) durable and honestly queryable across a
process restart, without making any of it resumable, replayable, or
schedulable. This closes exactly the gap named in the prior architectural
review (§4, §6, Category A): today, `WorkflowEngine._paused` is
in-memory-only, and a crash while a workflow is paused for approval leaves
no durable trace beyond an unstructured audit-log `detail` string — there
is no way to ask "what happened to that workflow?" after a restart.

## 2. Scope

**In scope:**
- A new durable, append-only `workflow_history` table recording each
  workflow lifecycle transition (the same seven transitions
  `WorkflowEngine` already emits as audit events), with `workflow_id` as a
  first-class, indexed, queryable column.
- A `WorkflowHistoryStore` data-access class, structurally mirroring
  `ApprovalHistoryStore`.
- `WorkflowEngine` writing to this store at the same points it already
  emits its existing `_emit`/`_emit_step_event` audit events — additively,
  never replacing them.
- Correlation with approvals: when a step pauses, the durable row records
  the `ApprovalRequest.request_id` that a human can cross-reference
  against `ApprovalHistoryStore`/`ApprovalHistoryTool`.
- A new `WorkflowHistoryTool` (GREEN, read-only), mirroring
  `ApprovalHistoryTool`.
- Two or three new exact `CommandRouter` phrases routing to it, mirroring
  `_APPROVAL_HISTORY_EXACT`/`_APPROVAL_DETAIL_PREFIXES`.
- `main.py` wiring: one new store instance, reused (not duplicated) by
  both `WorkflowEngine` and the new tool.

**Explicitly out of scope (Category B/C from the prior review, deliberately
not attempted here):**
- Resumable checkpoints (durably capturing enough state — resolved
  `tool_input`, remaining plan steps — to actually resume execution).
- Workflow replay of any kind.
- Any idempotency mechanism or exactly-once execution guarantee.
- Scheduling, background execution, or any trigger source.
- Notifications of any kind.
- Any AI planning change.
- Any new workflow command grammar, new propagated field, branching,
  retries, or parallel execution.
- Any change to `SecurityManager`, `ToolExecutor`'s classification
  behavior, `ApprovalManager`'s decision behavior, or either of the two
  existing Phase 15 workflow commands' behavior.

## 3. Verification That No Existing Architecture Already Provides This

Confirmed by direct inspection (this turn):
- `AuditLogEntry`/`AuditLog` (`storage/models.py`, `security/audit_log.py`)
  is a generic, source-agnostic, free-text-`detail` log with no
  `workflow_id` column and no per-workflow query method. It durably
  records that something happened but cannot be queried "show me
  everything about workflow X" without parsing free text.
- `ApprovalHistoryStore`/`ApprovalHistoryEntry` records only approval
  decisions (pending/approved/declined/expired), correlated by
  `request_id`, not by `workflow_id`, and has no concept of workflow steps,
  step count, or tool name.
- `WorkflowEngine._paused` (in-memory `dict[str, _PausedWorkflow]`) is
  transient by explicit design (Phase 15 §Batch 2/4) and is never written
  to storage anywhere.
- `WorkflowResult`/`WorkflowStepOutcome` (`workflow/workflow_models.py`)
  are plain in-memory dataclasses, constructed fresh per `run()`/`resume()`
  call, never persisted.
- No table, store, or tool anywhere in the repository has `workflow_id` as
  a column or query key. **Confirmed: this capability does not exist
  anywhere in the current architecture.**

## 4. Architectural Decisions

**4.1 — Append-only per-transition log, not an update-in-place row.**
Unlike `ApprovalHistoryEntry` (exactly two states: created once, decided
at most once), a workflow's lifecycle has a variable number of
transitions (a two-step workflow that pauses produces at least
`started → step_started → step_waiting`, then, on a later `resume()`
call, `step_started → step_completed → completed`). An append-only log
(one row per transition, mirroring `AuditLogEntry`'s own append-only
convention) is the natural fit; "current status" is derived as "the most
recent row for this `workflow_id`," exposed as a dedicated convenience
query rather than a separately-maintained mutable field (which would risk
drifting out of sync with the transition log itself).

**4.2 — Reuse the existing seven-event vocabulary verbatim.**
`WorkflowEngine` already defines exactly seven audit event names
(`workflow_started`, `workflow_step_started`, `workflow_step_completed`,
`workflow_step_waiting`, `workflow_step_failed`, `workflow_completed`,
`workflow_stopped`). The durable store's `status` column stores these
exact strings, rather than inventing a second, slightly different
vocabulary — directly avoiding the kind of duplicated-constant drift risk
the Phase 14 completion report disclosed for AI-reasoning message
constants.

**4.3 — Durable writes follow the same narrow observability-isolation
pattern as every other optional audit collaborator.** `WorkflowEngine`
gains one new optional constructor parameter, `history:
WorkflowHistoryStore | None = None` (default `None`, fully backward
compatible — mirrors how `logger: _AuditLogger | None = None` already
works). Every write to it is wrapped in the same narrow
`try/except Exception: pass` scoped only around the store call itself —
consistent with the standing invariant re-confirmed at Phase 15's own
closure: **a logger/observability failure must never alter an
authoritative workflow outcome.** This history store is itself
Category-A observability, not new execution authority, so it must obey
the identical invariant, not a weaker or stronger one.

**4.4 — No new `SecurityManager` rule needed.** `WorkflowHistoryTool`'s
action strings (e.g. `"show workflow history"`) already match the
existing, unmodified generic `_Rule("show", GREEN, ...)` rule — confirmed
by direct inspection of `security/security_manager.py`. This mirrors
exactly how `ApprovalHistoryTool`'s actions already resolve to GREEN with
no dedicated rule.

**4.5 — Tool-gated, not a CLI special-case.** The read command is
implemented as an ordinary registered `BaseTool`, routed through the
ordinary `CommandRouter.match()` → `ToolExecutor.execute()` path — the
exact same path every other command (including
`show approval history`) already takes. This means `SecurityManager`
still classifies it fresh on every call, exactly like every other action,
rather than adding any bypass or CLI-only special path.

**4.6 — No new SQLAlchemy migration helper needed.** `workflow_history` is
a brand-new table with no pre-existing rows anywhere to backfill (unlike
`episodic_memories.category`, which needed `_ensure_memory_category_column`
for pre-Phase-5 databases). `Base.metadata.create_all(bind=engine)`
(already called unconditionally on every startup by
`initialize_database()`) creates it automatically on first run against
either a fresh or an existing pre-this-turn database.

**4.7 — `workflow_id` is opaque and carries no restart-identity claim.**
Recording `workflow_id` durably does **not** change the fact (Phase 15,
confirmed again at closure) that `workflow_id` is a fresh `uuid.uuid4()`
per `run()` call with no cross-restart meaning for *resumption* — this
foundation only makes that same id durably *visible*, never durably
*resumable*. This distinction is stated explicitly in code comments and
tests to prevent a future reader from mistaking a history row for a
checkpoint.

## 5. Schema

New table `workflow_history` (SQLAlchemy model `WorkflowHistoryEntry` in
`storage/models.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | Integer PK | Auto-increment. |
| `workflow_id` | String(36) | Indexed, **not unique** — many rows per workflow over its lifetime. |
| `session_id` | Integer, nullable | Mirrors existing session-id convention elsewhere. |
| `status` | String(32) | One of the seven existing `WorkflowEngine` event-name strings. Indexed. |
| `step_number` | Integer, nullable | The step this transition concerns, when applicable (absent for workflow-level `workflow_started`/`workflow_completed`/`workflow_stopped`). |
| `step_total` | Integer, nullable | Total steps in the plan, for display context. |
| `tool_name` | String(128), nullable | The step's tool name only — never `tool_input`, never memory/file content. |
| `approval_request_id` | String(36), nullable | Set only on `workflow_step_waiting` rows; correlates with `ApprovalHistoryEntry.request_id`. |
| `detail` | Text, nullable | Short, content-free human-readable text (e.g. the stop reason) — never raw tool output or memory/file content. |
| `created_at` | DateTime(timezone=True) | UTC, `default=_utc_now`, indexed — mirrors every existing timestamped table. |

No `tool_input` column, no `resolved_tool_input` column, no plan
serialization column — by design, so this table structurally cannot become
a checkpoint by accident (mirroring `ApprovalHistoryEntry`'s own
deliberate omission of `tool_name`/`tool_input`, for the same reason).

## 6. New Modules and Integration Points

- **`storage/models.py`** — add `WorkflowHistoryEntry` (additive only).
- **`workflow/workflow_history_store.py`** (new) — `WorkflowHistoryStore`,
  structurally mirroring `approval/approval_history_store.py`: one
  `record_transition(...)` write method (covering all seven statuses via
  a `status` parameter, rather than seven near-duplicate methods, since
  every transition shares the same column set) plus `list_recent()`,
  `list_for_workflow()`, and `latest_status_for()` read methods.
- **`workflow/engine.py`** — add optional `history` constructor parameter;
  call `self._history.record_transition(...)` at the same seven points
  `_emit`/`_emit_step_event` are already called, wrapped in the same
  narrow isolation pattern. No change to any existing method's return
  value, signature, or control flow.
- **`tools/builtin/workflow_history_tool.py`** (new) —
  `WorkflowHistoryTool`, structurally mirroring
  `tools/builtin/approval_history_tool.py`.
- **`tools/builtin/__init__.py`** — export the new tool (additive).
- **`core/command_router.py`** — add `_WORKFLOW_HISTORY_EXACT` (distinct
  name from the pre-existing, unrelated `_WORKFLOW_ALIASES` dict, which
  is a Phase-7-era file-path convenience alias table and must not be
  confused with this turn's workflow-lifecycle history) and
  `_WORKFLOW_HISTORY_DETAIL_PREFIXES`, plus matching entries in `match()`
  and a new `_build_workflow_history_input()`, checked in the same
  position/style as the existing approval-history block.
- **`main.py`** — construct one `WorkflowHistoryStore` instance from the
  already-built `session_factory`; pass it into both `WorkflowEngine(...,
  history=...)` and `registry.register_tool(WorkflowHistoryTool(...))` —
  reusing the same instance, never constructing two.

## 7. Collision Check

- `"show workflow history"` / `"show recent workflows"` / `"show workflow
  <id>"` / `"view workflow <id>"` do not collide with any existing exact
  phrase or prefix in `core/command_router.py` (checked directly against
  `_WORKFLOW_ALIASES`, `_APPROVAL_HISTORY_EXACT`, `_APPROVAL_DETAIL_PREFIXES`,
  and every other prefix table in the module).
- Placed in `match()` immediately after the existing approval-history
  block, before file commands — pure narrative grouping, not
  load-bearing (mirrors how every prior phase's matcher placement has
  been proven order-independent).

## 8. Batch Plan

- **Batch 1** — `WorkflowHistoryEntry` model, `WorkflowHistoryStore`,
  focused unit tests against a real in-memory SQLite database (mirroring
  `test_approval_history_store.py`). No `WorkflowEngine` change yet.
- **Batch 2** — `WorkflowEngine` integration: optional `history`
  parameter, seven call sites, isolation-failure tests (a raising history
  store must never alter a `WorkflowResult`), full existing
  `test_workflow_engine.py` suite re-run to confirm zero regression.
- **Batch 3** — `WorkflowHistoryTool`, `CommandRouter` wiring, `main.py`
  wiring, end-to-end tests (a real two-step workflow's full lifecycle
  becomes queryable through the real command path).
- **Batch 4** — Full regression, closure documentation, commit.

After every batch: full suite, `git diff`/`git status` inspection,
formatting/whitespace check, architectural-consistency self-review before
proceeding to the next batch.

## 9. Non-Goal Guardrail

If, during implementation, any additional architectural need is
discovered (for example, a genuine need to store `resolved_tool_input`
for future resumption, or a need for a scheduler hook), this plan will
**stop, document the finding, and leave it for a future, separately-
authorized phase** — not fold it in here.
