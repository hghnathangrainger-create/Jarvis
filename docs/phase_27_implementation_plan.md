# Jarvis — Phase 27 Implementation Plan

**Phase 27 title:** Durable Pending-Approval / Resumable Workflow State
**Classification (Nathan's shortcut rule):** Large/risky — 3 batches
**Status:** Planning only. No production code, tests, README, user guide, or Master Specification changes made. Nothing staged or committed.

---

## 1. Baseline

```
Branch:        phase-4-ai-reasoning-and-write-actions
HEAD:          b025aec  "Add File Move/Rename Tool (Phase 26)"
Full suite:    2656 passed, 0 failed
git status:    ?? dashboard_test.txt (only entry — untouched, untracked, unstaged)
```

`dashboard_test.txt` was not touched, staged, or referenced by anything in this planning pass.

## 2. Files Inspected For This Plan

`approval/approval_manager.py` (full), `approval/approval_models.py` (full), `workflow/engine.py` (full), `tools/executor.py` (full), `core/orchestrator.py` (composition, `_handle_request_core`, `_confirmation_response`, `_tool_response`, `execute_approved`, `_paused_workflow_id_for` — full read of every approval/workflow-creation call site), `ui/cli.py` (`run`, `_handle_approval`, `_print_banner`), `storage/models.py` (full — all 8 tables), `approval/approval_history_store.py` (full), `scheduling/schedule_store.py` (full, as the project's own precedent for a *mutable* durable table with a narrow API), `main.py` (composition-root wiring for `ApprovalManager`/`WorkflowEngine`/`InboxStore`/`ScheduleStore`/`ScheduledInboxNoticeStore`), `pyproject.toml`, `docs/phase_26_completion_report.md`. Store-pattern conventions (`ApprovalHistoryStore`, `ScheduleStore`) were read in full to match this project's established dataclass-record + session-scope-store shape exactly, rather than inventing a new one.

## 3. Current Exact In-Memory Gap (confirmed by direct inspection)

Two related but structurally different gaps exist, not one:

### 3a. Plain (non-workflow) pending YELLOW approval

`core/orchestrator.py::_tool_response()` (line 3598) creates the `ApprovalRequest` via `self._approvals.create_request(action=..., reason=..., security_tier=..., session_id=...)` — **`ApprovalRequest` itself has no `tool_name`/`tool_input` field** (confirmed: `approval/approval_models.py`, full dataclass definition, lines 74-101 — only `action`, `reason`, `security_tier`, `session_id`, `metadata: dict[str, str]`, `request_id`, `created_at`). The `tool_name`/`tool_input` needed to actually run the tool once approved are carried **only** on the `JarvisResponse` object returned to the caller (`orchestrator.py:3611-3612`), which in the CLI (`ui/cli.py:254-258, 273-307`) is a **local Python variable held on the CLI's own call stack** between printing the prompt and reading the answer — entirely synchronous, entirely in-process, and **never passed to `ApprovalManager` at all**.

**This means the tool_name/tool_input for a plain pending approval do not exist in any Core-owned object today, in memory or otherwise** — only in the interactive loop's local stack frame. A crash between "prompt shown" and "answer given" loses both the CLI process and this local state together; nothing exists yet for Phase 27 to "persist" for this path without first giving `ApprovalManager` (or a new sibling structure) a place to hold `tool_name`/`tool_input` at all.

### 3b. Workflow-paused approval

`workflow/engine.py::_PausedWorkflow` (lines 126-140) **does** hold real executable state in a Core-owned, long-lived object (`WorkflowEngine._paused: dict[str, _PausedWorkflow]`, line 197): `plan: Plan` (the full step list, each with its own `tool_name`/`tool_input`/`action`/`tier`), `session_id`, `completed_outcomes`, `waiting_step_index`, `resolved_tool_input: dict[str, object]` (the actual input the paused step would run with), and `request_id` (correlating to the matching `ApprovalRequest` in `ApprovalManager._pending`, linked via `ApprovalRequest.metadata["workflow_id"]`).

Both `ApprovalManager._pending` (`approval/approval_manager.py:222`) and `WorkflowEngine._paused` (`workflow/engine.py:197`) are confirmed, by direct inspection this session (repeated identically across five prior reviews), to be plain in-memory `dict`s with no persistence path anywhere in either class.

### Conclusion this plan is built on

Making the **workflow-paused** case durable is a comparatively natural extension: the executable state already lives in one place, owned by a long-lived Core object. Making the **plain pending-approval** case durable requires a real, new piece of state that doesn't exist today: `ApprovalManager` must be extended to optionally hold `tool_name`/`tool_input` alongside a pending request (mirroring, in spirit, what `_PausedWorkflow` already does for the workflow case) before there is anything to persist for it. This is disclosed here as a genuine finding, not assumed going in — it directly shapes Batch 1's scope below.

## 4. Trust-Boundary Analysis (answered before proposing any schema, as required)

**What must be persisted for a pending approval to survive restart?**
`request_id`, `action` (string), `reason` (string), `security_tier` (always `"yellow"` — `ApprovalRequest` rejects any other tier at construction), `session_id`, `created_at`, `metadata` (the existing `dict[str, str]` — `workflow_id`/`step_number` when workflow-linked), and — new, per finding 3a — `tool_name` (a plain registered-tool identifier string) and `tool_input` (a JSON-serializable `dict[str, object]`, the exact same shape `ToolRequest.input_data` already is) **when a runnable tool exists for this request** (it does not for the plan-only `_confirmation_response` path at `orchestrator.py:3519`, which today has no tool to re-run even in-process — that path's approvals remain not-runnable after reload too, exactly as they are not-runnable today; see `execute_approved`'s own existing "no runnable tool for this action yet" branch).

**What must not be persisted because it would violate trust boundaries?**
Nothing about the *stored tier* is ever trusted on reload — the tier is always re-derived fresh via a live `SecurityManager.classify_action()` call at the moment of (re-)execution, exactly as it is for every ordinary request today; the persisted `security_tier` string is descriptive/audit metadata only, never a bypass of the classification gate. No pre-computed "already classified, just run it" flag is ever stored or honored. No raw file content, memory content, or other payload is stored beyond the same plain, already-validated-shape `tool_input` dict a live request already carries (e.g. `{"source": "a.txt", "destination": "b.txt"}` for `file_move` — identifiers and paths, not code). This mirrors, rather than contradicts, the project's existing discipline: `ApprovalHistoryEntry`'s own docstring explicitly names this exact scenario as a *deferred, separately-authorized* future decision ("Making approvals resumable is an explicit, separate decision deferred to a later phase, with its own safety review") — Phase 27 is that later phase, and the discipline is preserved by keeping this new state in its **own new table(s)**, never mixed into `approval_history`/`workflow_history`, so those tables' existing, permanent non-executable guarantee is completely unchanged.

**What must be persisted for a paused workflow to survive restart?**
`workflow_id`, `session_id`, the `Plan` (its steps: `number`, `tool_name`, `tool_input`, `action`, `tier`, `description`, `input_from_previous_step` — all plain, already-validated data, no different in kind from a single tool's `tool_input`), `completed_outcomes` (reduced to the minimum needed to resume: which step numbers already completed and their tool results' `success`/`output`/`metadata`, not re-derived from history), `waiting_step_index`, `resolved_tool_input`, and the linked `request_id`.

**What must not be persisted because it would recreate executable authority unsafely?**
No serialized Python callable, no pickled object of any kind (JSON only — see Batch 2 design constraint below), no `ToolExecutor`/`SecurityManager`/registry reference, no assumption that the *same tool implementation* still exists or behaves identically — reload always re-resolves `tool_name` against the **live** `ToolRegistry` and re-classifies via the **live** `SecurityManager`, never trusting anything stored about either. `WorkflowStepOutcome.tool_result` is stored only as plain output/metadata for already-completed steps (display/resume-context only) — never re-executed; only the *waiting* step is ever a candidate for execution, and only after a fresh approval decision.

**Can the original request/tool action be reconstructed safely?**
Yes, for the two cases where the necessary data is captured at creation time (a plain approval whose creating call site is extended to pass `tool_name`/`tool_input` into the new persisted state, and a workflow pause, which already computes `resolved_tool_input` today) — reconstruction means re-resolving `tool_name` against the live registry and re-classifying the action fresh, not replaying a trusted blob. It is **not** safely reconstructable for a plan-only confirmation with no backing tool (`_confirmation_response`), and this plan does not attempt to change that — it remains exactly as unresumable after reload as it already is today, mid-session.

**If not, should the system fail closed?**
Yes. Every row loaded at startup is independently re-validated before being treated as genuinely pending/resumable. A row fails closed — is marked `invalid`/`expired` and is never executable — if any of the following hold: the named tool is no longer registered; `SecurityManager.classify_action()` no longer returns YELLOW for this action (e.g., code changed and it's now RED, or now GREEN and therefore no longer needs approval at all — in the GREEN case reload reports this honestly rather than treating it as still-pending); the stored JSON is missing a required field or fails schema validation; the row's linked workflow (for a workflow-paused approval) is itself invalid or the referenced step index is out of range for the reloaded plan; or the row is older than a configured staleness ceiling (see below).

**Should some reloaded states be marked expired/unresumable instead of resumed?**
Yes — see above. "Fail closed" for Phase 27 concretely means: a row that cannot be independently re-validated against the live registry/`SecurityManager` is transitioned to a terminal `invalid` (or `expired`) status, written once to `approval_history`/`workflow_history` as such (so the user has the same durable visibility into "this could not be resumed" as into any other outcome), and is then removed from the pending/paused table — it can never be approved, declined, or executed. Only rows that pass every check are reloaded as genuinely pending, in the exact same state (awaiting the same, unmodified approve/decline path) as if the process had never restarted.

**How are stale pending approvals handled?**
A configurable staleness ceiling (reusing the existing `ApprovalManager(timeout_seconds=...)` concept, applied at reload time using `created_at`) expires anything older than the ceiling immediately on load, before it is ever exposed via `list_pending()` — recorded via the existing `record_timeout()` path on `approval_history`, exactly matching the live in-process timeout behavior already implemented (`ApprovalManager._sweep_expired()`), so a reloaded stale approval is indistinguishable in the history record from one that expired without ever restarting.

**How are stale paused workflows handled?**
Same ceiling, applied to the paused workflow's own creation time (the time its waiting step first paused). A workflow whose approval has separately expired (per the rule above) is reaped using the exact same logic `WorkflowEngine._reap_stale_paused()` already implements in-memory today — extended to run once at startup against the reloaded set, not only against live pauses.

**How does this interact with approval history?**
Additively only. `ApprovalHistoryStore`/`ApprovalHistoryEntry` are completely unchanged — no new column, no new method. The new pending-approval table is a separate table; a row's terminal outcome (approved/declined/expired/invalidated-on-reload) is still recorded through the existing `record_decision()`/`record_timeout()` calls exactly as today. A new, narrow terminal outcome — "could not be resumed after restart" — is recorded via the existing `record_timeout()` shape (reason text distinguishes it, no new `ApprovalHistoryEntry` column needed) rather than inventing a fourth status value in a table this plan does not touch.

**How does this interact with workflow history?**
Same principle. `WorkflowHistoryStore`/`WorkflowHistoryEntry` are unchanged. A workflow that fails closed on reload gets one additional `workflow_stopped`-shaped history row (reusing the existing status vocabulary, `detail="stopped_at_step=N (could not be resumed after restart)"`) via the existing `record_transition()` method — no new status string invented, no new column.

**How does this interact with audit logging?**
Additively only, following the exact isolation pattern already used everywhere else in this codebase (`_emit_audit_event`/`_emit`/`_record_history`'s own try/except-and-swallow convention): a reload-time audit event uses the existing `EventLogger.emit()` shape, a new `action_type` value (e.g. `"pending_approval_reload"` / `"paused_workflow_reload"`), and never lets a logging failure change whether a row is treated as resumable or invalidated.

**How does this interact with the dashboard's read-only history views?**
Not directly. The dashboard's Approval History and Workflow History tabs already read `ApprovalHistoryStore`/`WorkflowHistoryStore`, both unchanged by this phase — a reload-invalidated row shows up there exactly like any other expired/stopped entry already does, with no new tab code required.

**Does dashboard need to display pending state now, or is that out of scope?**
Out of scope, per the approved non-goals ("preserve dashboard read-only status," no dashboard write actions). The dashboard is not wired to `ApprovalManager`/`WorkflowEngine` at all today (it reads only through the durable history stores) and this phase does not change that. If Nathan later wants to *see* currently-pending/paused state on the dashboard, that is a small, separate, future addition once this phase's durable store exists to read from — not part of Phase 27's approved scope.

## 5. Proposed Schema

### Table: `pending_approval_state`

- **Purpose:** Durably hold a currently-pending YELLOW approval request (plain tool call or workflow-linked) so it can be independently re-validated and, if safe, genuinely resumed after a restart. A **new, narrowly-scoped table**, never merged with `approval_history`.
- **Fields:**
  - `id` — Integer, primary key, autoincrement, non-null.
  - `request_id` — String(36), non-null, unique, indexed. Matches `ApprovalRequest.request_id`.
  - `session_id` — Integer, nullable, indexed (matches every other newer table's plain-Integer convention, not a ForeignKey).
  - `action` — Text, non-null.
  - `reason` — Text, non-null.
  - `security_tier` — String(16), non-null. Always `"yellow"` at write time; never trusted alone on reload (see Trust-Boundary Analysis).
  - `metadata_json` — Text, nullable. JSON-serialized `dict[str, str]` (the existing `ApprovalRequest.metadata` shape — `workflow_id`/`step_number` when present). Plain string-to-string data only, matching the existing type already enforced by `ApprovalRequest`.
  - `tool_name` — String(128), nullable. Null only for a plan-only confirmation with no backing tool (`_confirmation_response`'s path) — such a row is never resumable and is always treated as reload-invalid.
  - `tool_input_json` — Text, nullable. JSON-serialized `dict[str, object]`, the plain, already-validated shape every live `ToolRequest.input_data` already is. Null exactly when `tool_name` is null.
  - `created_at` — DateTime(timezone=True), non-null, indexed, default `_utc_now`.
  - `status` — String(16), non-null, default `"pending"`. One of `"pending"`, `"resumed"`, `"invalidated"` (removed from this table once resolved either way — see lifecycle).
- **Indexes:** unique index on `request_id` (lookup and prevents duplicate rows for one request); index on `created_at` (staleness sweep); index on `session_id` (matches convention).
- **Lifecycle:** a row is inserted when `ApprovalManager.create_request()` creates a pending request (mirroring `_record_history_request`'s existing additive-write pattern) and deleted the moment that request is decided, expires, or is invalidated on reload — this table only ever holds **currently, genuinely pending** rows, never a history. Exactly parallel to how `_pending` itself only ever holds currently-pending requests in memory today; this table is its durable mirror, not a second history log.
- **What is intentionally not stored:** no decision, no `decided_by`, no `decided_at` — those belong solely to `approval_history`, which already records them; duplicating them here would create two sources of truth for the same fact.
- **Why storing `tool_input_json` here is safe:** it is written only from data the live `CommandRouter`/`WorkflowEngine` already produced for a request already independently classified YELLOW at creation time; on reload it is never trusted blindly — the action is reclassified fresh, the tool is re-resolved fresh against the live registry, and the tool's own `run()` validates the input exactly as it would for a brand-new live request (e.g. `FileMoveTool` still re-checks `destination.exists()` etc. even for a reloaded input).
- **How stale/corrupt rows are handled:** a row whose `tool_input_json`/`metadata_json` fails to parse as valid JSON, whose `tool_name` is no longer registered, whose reclassified tier is not YELLOW, or whose age exceeds the staleness ceiling is deleted from this table and recorded as invalidated/expired in `approval_history` — never executed.
- **How rows are cleaned up:** deleted on decision (approve/decline), deleted on staleness sweep (startup and/or the existing periodic `_sweep_expired()` path, extended to also delete the durable row), deleted on reload-invalidation.

### Table: `paused_workflow_state`

- **Purpose:** Durably hold a currently-paused workflow (at most one at a time, per Phase 15's own one-workflow-at-a-time contract, `WorkflowEngine.run()` line 279-284) so it can be independently re-validated and, if safe, genuinely resumed.
- **Fields:**
  - `id` — Integer, primary key, autoincrement, non-null.
  - `workflow_id` — String(36), non-null, unique, indexed.
  - `session_id` — Integer, nullable, indexed.
  - `request_id` — String(36), non-null, indexed. The linked `pending_approval_state.request_id` for this workflow's waiting step.
  - `plan_json` — Text, non-null. JSON-serialized list of steps (`number`, `tool_name`, `tool_input`, `action`, `tier.value`, `description`, `input_from_previous_step`) — a plain, flat, already-validated structure; never a pickle, never a class reference.
  - `completed_outcomes_json` — Text, non-null. JSON-serialized list of `{step_number, status, tool_result: {success, output, error, metadata}}` for every step already completed before the pause — enough to display/resume context, never re-executed.
  - `waiting_step_index` — Integer, non-null.
  - `resolved_tool_input_json` — Text, non-null. JSON-serialized `dict[str, object]` for the specific waiting step.
  - `created_at` — DateTime(timezone=True), non-null, indexed, default `_utc_now`. Set once, when the workflow first pauses (not updated on any later inspection).
  - `status` — String(16), non-null, default `"paused"`. One of `"paused"`, `"resumed"`, `"invalidated"`.
- **Indexes:** unique index on `workflow_id`; index on `request_id` (cross-reference to the pending approval row); index on `created_at`.
- **Lifecycle:** inserted the moment `_run_from()` pauses a step (mirroring the existing `self._paused[workflow_id] = _PausedWorkflow(...)` assignment at `engine.py:541`), deleted the moment `resume()` successfully continues or terminally stops the workflow, or invalidated on reload.
- **What is intentionally not stored:** no `ToolResult` for the *waiting* step itself (it hasn't run yet — nothing to store); no reference to `ApprovalManager`/`ToolExecutor`/`ToolRegistry` instances; no assumption about which process/instance will reload it.
- **Why storing `plan_json`/`resolved_tool_input_json` here is safe:** identical reasoning to `pending_approval_state.tool_input_json` above — this is a **new**, narrowly-scoped, explicitly-authorized-for-resumption table, structurally separate from `workflow_history`, whose own non-executable guarantee is completely unchanged.
- **How stale/corrupt rows are handled:** invalid JSON, an out-of-range `waiting_step_index` for the deserialized plan, a step whose `tool_name` is no longer registered, or a step whose action no longer reclassifies to YELLOW all invalidate the row — reload deletes it and records a `workflow_stopped`-shaped entry in `workflow_history` explaining why.
- **How rows are cleaned up:** deleted on resume (success or stop), deleted on reload-invalidation, deleted by the same staleness sweep as pending approvals (a paused workflow's linked approval going stale independently reaps the workflow row too, mirroring `_reap_stale_paused()`'s existing logic).

## 6. Proposed Stores

### `PendingApprovalStore` (new, `approval/pending_approval_store.py`)

- **Class name:** `PendingApprovalStore`
- **Methods:**
  - `save(request: ApprovalRequest, *, tool_name: str | None, tool_input: dict[str, object] | None) -> None` — insert-or-replace-by-`request_id`. Called from `ApprovalManager.create_request()`.
  - `delete(request_id: str) -> None` — called on decide/expire/invalidate. No-op if the row is already gone (idempotent).
  - `list_all() -> list[PendingApprovalRecord]` — returns detached dataclass records (mirroring `ApprovalHistoryRecord`'s own shape), used only at startup reload.
  - `get(request_id: str) -> PendingApprovalRecord | None` — used by `WorkflowEngine`'s reload path to cross-reference a paused workflow's linked approval row.
- **Method inputs/outputs:** all inputs are plain values already validated by `ApprovalRequest`/`ToolRequest`; `tool_input`/`metadata` are serialized to JSON text inside the store (never left to the caller), matching `ScheduleStore`'s own "validate and normalize inside the store" convention.
- **Transaction behavior:** every method uses `storage.database.session_scope`, exactly like every existing store — one commit per call, no cross-call transactions.
- **Error behavior:** malformed JSON on read (`list_all`/`get`) is caught per-row; a single corrupt row is skipped and reported (never raised, never allowed to abort loading every other valid row) — mirrors the project's existing "one failing collaborator must never break an already-authoritative outcome" isolation pattern used throughout `ApprovalManager`/`WorkflowEngine`.
- **Concurrency assumptions:** identical to every existing store — SQLite WAL mode (already enabled since Phase 19), single-writer-at-a-time via `session_scope`, no additional locking needed since Phase 15's own one-workflow-at-a-time / this project's single-process model is unchanged.
- **Test coverage:** round-trip save/list/get/delete; JSON round-trip fidelity for nested dict values; corrupt-row isolation; empty-table behavior.

### `PausedWorkflowStore` (new, `workflow/paused_workflow_store.py`)

- **Class name:** `PausedWorkflowStore`
- **Methods:**
  - `save(workflow_id: str, paused: _PausedWorkflow_shape, *, request_id: str) -> None`
  - `delete(workflow_id: str) -> None`
  - `list_all() -> list[PausedWorkflowRecord]`
  - `get(workflow_id: str) -> PausedWorkflowRecord | None`
- **Transaction/error/concurrency behavior:** identical pattern to `PendingApprovalStore` above.
- **Test coverage:** round-trip save/list/get/delete for a multi-step plan; JSON round-trip fidelity for `Plan`/`PlanStep`/`WorkflowStepOutcome` shapes; corrupt-row isolation; out-of-range `waiting_step_index` detection.

Both stores follow the exact `session_factory`-constructor, dataclass-record, `_to_record`/`_clamp_limit`-style-helper conventions already used by `ApprovalHistoryStore`/`ScheduleStore` — no new architectural pattern is introduced.

## 7. Proposed Integration Points

### `ApprovalManager`

- **Where pending approval is created:** `create_request()` (line 229) — after building `request`, and after the existing `self._pending[request.request_id] = request` / `self._record_history_request(request)` lines, add `self._record_pending_state(request, tool_name=..., tool_input=...)`. `create_request()`'s signature grows two new optional keyword arguments, `tool_name: str | None = None` and `tool_input: dict[str, object] | None = None`, both defaulting to `None` so every existing call site (including `_confirmation_response`'s plan-only path) is unaffected unless updated.
- **Where approval is decided:** `_decide()` (line 392) — after `del self._pending[request_id]`, add `self._pending_store.delete(request_id)` if a store is configured.
- **Where pending approval is removed:** `_decide()` (decision) and `_sweep_expired()` (line 527, timeout) — both already remove from `self._pending`; both gain the matching durable delete.
- **Where reload should happen:** a new method, `ApprovalManager.reload_pending(*, registry, security_manager) -> ReloadReport` — called once by `main.py` composition, **not** from `__init__` (keeping `__init__`'s existing "always starts empty" contract intact for every test that constructs a bare `ApprovalManager()` today, per the class's own existing docstring promise). `reload_pending()` reads every row via `PendingApprovalStore.list_all()`, independently re-validates each (registry lookup, fresh `classify_action()`, JSON validity, staleness), and either repopulates `self._pending` with a reconstructed `ApprovalRequest` (preserving the original `request_id`/`created_at`) or invalidates the row (deletes it, writes to `approval_history` via the existing `record_timeout`-shaped call).
- **How loaded state is validated:** exactly as described in the Trust-Boundary Analysis — never a blind rehydrate.
- **How loaded state avoids changing current behavior unexpectedly:** `reload_pending()` is opt-in (only called where a store is wired) and additive — it only ever populates `_pending` with rows that would already be valid to create fresh via `create_request()` today; nothing about `approve()`/`decline()`/`list_pending()`/`has_pending()` changes shape or behavior for a caller that never restarts.

### `WorkflowEngine`

- **Where workflow pauses:** `_run_from()` (line 541, `self._paused[workflow_id] = _PausedWorkflow(...)`) — immediately after, add `self._paused_store.save(workflow_id, paused, request_id=approval_request.request_id)` if configured.
- **Where workflow resumes:** `resume()` (line 342, `self._paused.pop(workflow_id, None)`) — immediately after a successful pop (whether the outcome is a further pause, completion, or stop), add `self._paused_store.delete(workflow_id)`.
- **Where paused state is removed:** same two sites above, plus `_reap_stale_paused()` (line 216) gains the matching durable delete for each reaped id.
- **Where reload should happen:** a new method, `WorkflowEngine.reload_paused(*, registry, security_manager, pending_approval_store) -> ReloadReport`, called once from `main.py` composition, never from `__init__` (same rationale as `ApprovalManager`). Cross-references each `paused_workflow_state` row against its linked `pending_approval_state` row (via `request_id`) — a paused workflow whose linked approval was itself invalidated is automatically invalidated too, never left as an orphaned paused-without-approval state.
- **How loaded state is validated:** deserializes `plan_json` into real `Plan`/`PlanStep` objects, checks `waiting_step_index` is in range, re-resolves every step's `tool_name` against the live registry, reclassifies the waiting step's action fresh — any failure invalidates the row (deleted, `workflow_history` gets a `workflow_stopped`-shaped closing entry).
- **How loaded state avoids changing current behavior unexpectedly:** `reload_paused()` only ever repopulates `self._paused`, which is otherwise untouched — `run()`'s existing "only one workflow may be active at a time" check (line 280-284) applies identically to a reloaded paused workflow as to a freshly-paused one, so behavior for every non-restart scenario is unchanged.

### Startup / Composition

- **`main.py`:** `build_orchestrator()` gains, after constructing `approval_history`/`workflow_history`/the `ApprovalManager`/`WorkflowEngine` instances (lines 117-118, 149, 203): construction of `pending_approval_store = PendingApprovalStore(session_factory)` and `paused_workflow_store = PausedWorkflowStore(session_factory)`, passed into `ApprovalManager(..., pending_store=pending_approval_store)` and `WorkflowEngine(..., paused_store=paused_workflow_store)` (both new optional keyword args, default `None`, so every existing caller that constructs either class directly — and there are many across the test suite — is unaffected). Immediately after both are constructed, `build_orchestrator()` calls `approvals.reload_pending(...)` then `workflow_engine.reload_paused(...)` before returning the orchestrator. **`build_orchestrator()`'s own signature does not change** — this is purely additive internal wiring, consistent with the standing "26+ callers depend on this signature" discipline already honored through Phases 20-26.
- **`dashboard.py`:** no changes. It never constructs `ApprovalManager`/`WorkflowEngine` today (dashboard is read-only and only reads through the durable history/inbox/schedule stores) and this phase does not change that.
- **`scheduler.py`:** no changes. It never touches approvals or workflows.
- **Composition blast radius:** contained entirely within `build_orchestrator()`'s own body plus the two touched classes' constructors (both gaining one new optional parameter each, defaulting to `None`) — no other module's construction call sites need updating unless a test explicitly wants to exercise persistence, in which case it opts in by passing the new parameter.

## 8. Proposed 3-Batch Sequence

### Batch 1 — Durable Pending Approval Store

- Add `PendingApprovalState` model to `storage/models.py`.
- Add `approval/pending_approval_store.py` (`PendingApprovalStore`, `PendingApprovalRecord`).
- Extend `ApprovalManager`: `create_request()` gains `tool_name`/`tool_input` optional params and writes through; `_decide()`/`_sweep_expired()` gain durable deletes; new `reload_pending()` method with full re-validation logic described above.
- Extend the two orchestrator call sites that create approvals (`_tool_response` at `orchestrator.py:3598`, and the workflow-pause call inside `engine.py:_run_from` — this second one is prepared here but only fully wired in Batch 2) to pass `tool_name`/`tool_input` through to `create_request()`. `_confirmation_response` (`orchestrator.py:3519`, plan-only, no tool) is left passing `tool_name=None, tool_input=None` explicitly, documented as permanently non-resumable.
- Wire `main.py` to construct `PendingApprovalStore` and pass it to `ApprovalManager`, call `reload_pending()`.
- **Tests:** persistence round-trip (save/list/get/delete); reload into a **new** `ApprovalManager` instance repopulates `_pending` correctly; approve/decline after reload behaves identically to a same-process approve/decline; a reloaded row whose tool is no longer registered is invalidated, not resumed; a reloaded row whose action no longer classifies YELLOW is invalidated; corrupt JSON in a row is isolated and invalidated without crashing reload; a stale (past staleness ceiling) row is expired on reload via the existing `record_timeout` path; a plan-only (`tool_name=None`) approval reloads as permanently non-resumable, matching its current in-process behavior; existing approval-flow tests (`tests/integration/test_write_approval_end_to_end.py`) still pass unmodified, proving no regression when no store is configured.

### Batch 2 — Durable Paused Workflow Store

- Add `PausedWorkflowState` model to `storage/models.py`.
- Add `workflow/paused_workflow_store.py` (`PausedWorkflowStore`, `PausedWorkflowRecord`), including the `Plan`/`PlanStep`/`WorkflowStepOutcome` ↔ JSON (de)serialization helpers (plain dict/list only — no pickling, no `eval`, no dynamic class loading; every field is a primitive, a string enum value, or a nested plain dict, matching every other JSON-shaped column already in this codebase, e.g. `ApprovalRequest.metadata`).
- Extend `WorkflowEngine`: pause site (`engine.py:541`) writes through; `resume()`/`_reap_stale_paused()` delete through; new `reload_paused()` method with full re-validation, including cross-referencing the linked `pending_approval_state` row.
- Fully wire the workflow-pause call site's `tool_name`/`tool_input` passthrough into `ApprovalManager.create_request()` (prepared in Batch 1).
- Wire `main.py` to construct `PausedWorkflowStore`, pass it to `WorkflowEngine`, call `reload_paused()` after `reload_pending()`.
- **Tests:** persistence round-trip for a multi-step plan, including a step already completed before the pause; reload into a **new** `WorkflowEngine` instance repopulates `_paused` correctly; resume-after-reload for a safely-revalidated workflow behaves identically to a same-process resume (same tool executes, same `ToolExecutor` gate, same STOP-only failure policy); a reloaded workflow whose waiting step's tool is no longer registered is invalidated; a reloaded workflow whose linked approval row is itself missing/invalidated is invalidated too (orphan case); an out-of-range `waiting_step_index` after deserialization is detected and invalidates the row; corrupt `plan_json`/`completed_outcomes_json` is isolated; existing Phase 15 workflow tests still pass unmodified with no store configured.

### Batch 3 — End-to-End Crash/Restart Proof, Adversarial Sweep, Docs, Closure

- Real "process restart" integration tests: construct one full `main.build_orchestrator()`-equivalent stack, create a pending approval (and separately, a paused workflow) against a real temp-file SQLite database, **discard every in-memory Python object**, construct a fresh stack against the same database file, and prove the approval/workflow reloads and can be safely decided/resumed.
- Crash-simulation tests: simulate a crash *mid-persist* (e.g., a write that raises partway) and prove no row is left in a state that could later execute anything unsafely.
- Adversarial persistence tests: hand-craft a `pending_approval_state`/`paused_workflow_state` row with corrupt JSON, an unregistered `tool_name`, a tampered `security_tier`, injection-shaped text inside `tool_input_json` values (proving it is never treated as instructions — the tool's own existing input handling already treats all input as untrusted data, unchanged by this phase), and an out-of-range `waiting_step_index` — each must invalidate cleanly, never execute, never raise out of `reload_pending()`/`reload_paused()`.
- Regression proof: the full pre-existing approval/workflow test suites pass byte-for-byte unmodified when no store is configured (default `None`), proving zero behavior change for every caller that doesn't opt in.
- Proofs required (explicitly, matching the approved list): pending approval survives restart if safe; paused workflow survives restart if safe; corrupted persisted state does not execute; stale persisted state does not execute unsafely; untrusted text in persisted state does not become instructions; no tool executes merely because state was reloaded (reload only repopulates `_pending`/`_paused` — execution still requires an explicit, later `approve()` call exactly as today); no approval is auto-approved; no workflow is auto-resumed without the same approval/resume path (`resume()` still requires an explicit `ApprovalDecision`, never synthesized during reload); normal non-restart approval/workflow behavior unchanged; dashboard remains read-only; scheduler behavior unchanged; file tools unchanged; full suite green.
- `docs/user_guide.md` update **only if** any user-visible behavior actually changes — per the trust-boundary analysis, the only user-visible change is that a restart during a pending approval or paused workflow now either (a) genuinely resumes it, or (b) honestly reports it could not be resumed (previously: silent loss, no message at all) — this is worth one short addition to the guide's existing "Safety Model" section.
- `README.md` — new `## Phase 27` section, matching the existing per-phase format.
- `docs/phase_27_completion_report.md` — full reconciliation against this plan.
- Final full-suite verification, `git status` check (`dashboard_test.txt` still untouched), commit only if everything is clean and the user has approved closure.

## 9. Explicit Non-Goals (restated, unchanged from the approved scope)

No new tools. No file delete. No dashboard command box or write actions. No Core service or multi-client/HTTP/IPC architecture. No approval scheduling. No auto-approval or auto-denial. No auto-resume policy beyond re-presenting the exact same approval the user would have seen anyway (resume always still requires an explicit decision). No arbitrary command scheduling. No changes to GREEN/YELLOW/RED classification rules. No changes to existing file-tool behavior. No webpage fetching. No Research Agent. No voice/phone work. No notification work. No goals/projects/tasks work. No new workflow templates.

## 10. Risk Analysis

- **Schema-design risk:** once real pending/paused rows exist in the field, changing `pending_approval_state`/`paused_workflow_state`'s shape later is harder than getting it right now — mitigated by keeping both tables' JSON payloads as plain, versionless dict/list structures (no nested custom classes) and by both tables being entirely disposable/regenerable (unlike `approval_history`, nothing here is meant to accumulate — a corrupt or outdated row is simply invalidated, never migrated).
- **Partial-write risk:** a crash mid-persist (e.g., between `self._pending[id] = request` and the durable write, or vice versa) must never leave a row that looks valid but isn't, or a row that's missing entirely when the in-memory side thinks it succeeded — mitigated by writing the durable row **before** returning from `create_request()`/the pause site (durable-first, matching `_record_history_request`'s own existing ordering), and by Batch 3's dedicated crash-simulation tests.
- **Reclassification drift risk:** if `SecurityManager`'s rules change between when a request was created and when it's reloaded, an action that was YELLOW may now be GREEN (safe to just note and invalidate — never silently auto-run something now-GREEN without going through a live, fresh classification) or RED (must be blocked, never resumed) — mitigated by always reclassifying fresh on reload, never trusting the stored tier, exactly as designed above.
- **Orphan risk:** a paused workflow row whose linked pending-approval row is missing (deleted, decided, or invalidated independently) must never be treated as still-resumable — mitigated by the explicit cross-reference check in `reload_paused()`.
- **Test-suite size risk:** this phase touches two of the most heavily depended-upon classes in the codebase (`ApprovalManager`, `WorkflowEngine`) — mitigated by making every new parameter optional and defaulting to `None`/current behavior, and by running the full suite after each batch, not only at the end.

## 11. Fail-Closed Design (summary)

A persisted pending approval or paused workflow is only ever treated as live/resumable after independently re-passing, on every reload, the same checks a brand-new live request already has to pass: the named tool must still be registered; the action must still classify as YELLOW under the live `SecurityManager`; the stored JSON must parse and satisfy basic shape checks; the row must not have exceeded the staleness ceiling; and (for a workflow) its linked approval row must itself be valid and its waiting step index must be in range for the deserialized plan. Failing any check invalidates the row — it is deleted from the pending/paused table, and a single terminal entry is written to the existing, unchanged `approval_history`/`workflow_history` tables explaining that it could not be resumed. Nothing is ever auto-approved, auto-declined, or auto-executed as a side effect of reload; reload only ever changes whether a row is available for the user to explicitly approve/decline through the existing, unmodified path.

## 12. Final Recommendation

**Proceed to Batch 1** as scoped above. The trust-boundary analysis resolves the plan's central open question (whether persisting enough state to resume conflicts with the project's established "no executable authority in history tables" discipline) by keeping the new durable state in its own tables, separate from `approval_history`/`workflow_history`, whose non-executable guarantee is completely unchanged — and by requiring every reloaded row to be independently re-validated against live code, never trusted as a replay blob. This satisfies the approved goal (pending approvals and paused workflows genuinely survive a restart when it is safe to resume them, and are honestly, visibly invalidated when it is not) without overbuilding: no new tools, no Core service, no generic resumption framework beyond these two specific, already-existing state shapes.

## 13. Confirmation

No production code, tests, README, user guide, or Master Specification file was modified during this planning pass. This document (`docs/phase_27_implementation_plan.md`) is the only file written. Nothing was staged or committed. `dashboard_test.txt` remains untouched, untracked, and unstaged.
