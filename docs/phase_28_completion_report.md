# Jarvis — Phase 28 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 28 — Workflow Resume Request-ID Invariant (small whole-phase, complete)
**Date:** 2026-07-17

---

## Executive Summary

Phase 28 closes a real, previously-disclosed-but-unfixed gap: `WorkflowEngine.resume()` never verified that the `ApprovalDecision` it was handed actually belonged to the specific paused workflow being resumed. Phase 27's own completion report documented this honestly rather than silently, confirming by direct inspection that the gap was never live-exploitable — the one real production caller, `core/orchestrator.py::execute_approved()`, always supplies a matching pair by construction. Phase 28 closes it anyway, narrowly: one additive guard clause, no new subsystem, no new table, no behavior change for any legitimate caller.

## Baseline

```
Branch:        phase-4-ai-reasoning-and-write-actions
Phase 27 final commit: e65e4fe
Full suite before Phase 28: 2774 passed, 0 failed
```

## Files Changed

- `workflow/engine.py` — `resume()` gains the request-id guard; `WorkflowError`'s own class docstring updated to disclose the new raise condition.
- `tests/integration/test_phase27_invalid_state_fails_closed.py` — the existing disclosure test (`test_mismatched_request_id_pointing_at_an_unrelated_pending_approval`) renamed and reframed to honestly document a *different*, deeper, deliberately out-of-scope residual boundary (see "Residual, Disclosed Boundary" below) rather than exercising the fix itself, since the DB-row-tampering scenario it constructs cannot actually trigger the new invariant (explained below).
- `tests/unit/test_workflow_resume_invariant.py` (new, 8 tests) — the actual proof of the Phase 28 fix.
- `README.md` — new `## Phase 28` section.
- `docs/phase_28_completion_report.md` — this report, new.

`docs/user_guide.md` was **not** updated — this is pure internal hardening with no observable day-to-day behavior change for any legitimate use; the one guide passage that already discusses restart/fail-closed behavior (added in Phase 27) remains accurate without amendment.

---

## Exact Invariant Fixed

`WorkflowEngine.resume(workflow_id, decision, ...)` now requires `decision.request_id == paused.request_id` (the request id the paused workflow itself recorded when it originally paused, in `_run_from()`, as `request_id=approval_request.request_id`) before doing anything else. This check runs immediately after the workflow is popped from `self._paused` and its durable row is removed, and strictly before any `ToolExecutor.execute()` call.

## Implementation Summary

```python
if decision.request_id != paused.request_id:
    self._emit(_EVENT_WORKFLOW_STOPPED, EventOutcome.FAILURE, detail=..., session_id=paused.session_id)
    self._record_history(_EVENT_WORKFLOW_STOPPED, workflow_id=workflow_id, session_id=paused.session_id, detail=...)
    raise WorkflowError(...)
```

This reuses the exact same audit-log event (`_emit`) and durable-history event (`_record_history`, the existing `workflow_stopped` status string — no new event name, no new table) that `_stop()` already uses for an ordinary step failure, so no new observability plumbing was introduced. `WorkflowError` was chosen over returning a `FAILED WorkflowResult`, matching this class's own pre-existing convention (documented directly in `WorkflowError`'s own docstring): usage-contract violations (unknown workflow_id, already-resumed workflow_id) are raised, not returned as data, because they represent a caller mistake rather than an outcome the workflow itself produced.

**Terminal, not retryable**: the paused workflow is popped from `self._paused` before the check runs and is never put back on mismatch — a caller cannot retry the same `workflow_id` with a different decision after a rejected one, which would otherwise allow probing for a matching id.

## Fail-Closed Behavior

- No tool executes: the guard runs before `self._executor.execute(...)` is ever reached.
- No filesystem/memory/tool state mutation: proven directly (`test_no_tool_executes_on_mismatch`) — only the plan's own legitimate prior GREEN step ran; the waiting YELLOW step's tool was never called.
- The workflow is permanently closed, not left pending (`test_mismatch_is_terminal_not_retryable`) — even the *correct* decision cannot resume it after a mismatch was already rejected once.
- An honest `workflow_stopped` entry is recorded in the existing, unchanged `workflow_history` table (`test_workflow_history_records_an_honest_mismatch_entry`).

## Proof Valid Resume Behavior Is Unchanged

- `test_valid_matching_resume_still_works` — an ordinary, live, non-restart approve-then-resume cycle completes exactly as before.
- `test_valid_matching_resume_after_reload_still_works` — the entire Phase 27 restart/resume path (fresh engine/registry against the same database, `reload_pending()` then `reload_paused()`, approve, resume) still completes correctly.
- `test_declined_matching_resume_still_works` — a correctly-matched *decline* decision is not itself a mismatch and is still honoured as an ordinary decline.
- `test_production_orchestrator_path_always_supplies_matching_ids` — drives the real `JarvisOrchestrator`/`execute_approved()`/`_paused_workflow_id_for()` path end-to-end through the real `"remember this and forget it: <text>"` command, proving the one real production caller in this codebase continues to work completely unaffected.
- Every pre-existing Phase 15/27 workflow test (`test_workflow_engine.py`, `test_workflow_engine_paused_state.py`, both restart-end-to-end integration files, the adversarial and regression sweeps) passes unmodified.

## Residual, Disclosed Boundary (not fixed, out of scope)

The renamed test `test_row_level_request_id_tampering_is_a_disclosed_database_integrity_boundary` documents a distinct, deeper scenario this fix does *not* and cannot address: if `paused_workflow_state.request_id` is corrupted directly in the database (not merely mismatched by a careless caller), the reloaded in-memory paused workflow's own `request_id` field *is* the tampered value — so Phase 28's invariant (`decision.request_id == paused.request_id`) is satisfied trivially, because both sides now agree on the tampered id. Defending against this would require cryptographic row-signing or similar, wildly disproportionate to what this project defends against anywhere else (the SQLite file itself is already a trusted boundary — see every other store's own "plain data, no encryption" convention). This is disclosed explicitly, exactly as Phase 27 disclosed the original gap, rather than silently assumed.

## Tests Added/Updated

- **Added**: `tests/unit/test_workflow_resume_invariant.py` — 8 new tests (the core invariant, no-execution proof, terminal-not-retryable proof, honest history entry, valid-resume-unchanged ×3, and the real production-path proof).
- **Updated**: `tests/integration/test_phase27_invalid_state_fails_closed.py` — one test renamed and its docstring/assertions reframed to accurately describe the residual boundary above, rather than exercising the fix (which it structurally cannot, per the explanation above).

## Final Verification

```
Focused (12 files): 208 passed
poetry run pytest -q: 2782 passed, 0 failed (run 3x, stable; 2774 → 2782, +8 net)
poetry run ruff check: zero new findings (only the project's pre-existing E402-after-importorskip
  pattern, and the one pre-existing, unrelated F401 in workflow/engine.py that predates this session)
git diff --check: clean
```

## Non-Goals Confirmed

Confirmed absent, by direct inspection: no new workflow templates; no new tools; no file delete; no dashboard changes of any kind (`dashboard.py`/`ui/dashboard_app.py` untouched); no scheduler changes (`scheduler.py` untouched); no Core service or multi-client architecture; no webpage fetching; no notifications; no goals/projects/tasks; no `SecurityManager` rule changes; no `ApprovalManager` behavior changes (`approval/approval_manager.py` untouched — the fix lives entirely in `WorkflowEngine`); no new approval-correlation subsystem; no new durable table; no change to normal, legitimate approval/resume UX (proven directly, not merely assumed).

---

## Status Statement

**Phase 28 complete for its defined scope: `WorkflowEngine.resume()` now fails closed on a request-id mismatch between the supplied decision and the paused workflow being resumed, with zero behavior change for any legitimate caller, live or reloaded.** Implemented in a single pass, exactly matching its approved "small whole-phase" classification. The one deeper, disclosed residual boundary (direct database-row tampering) is explicitly out of scope and disclosed rather than silently assumed, mirroring the same honesty discipline Phase 27 itself established.
