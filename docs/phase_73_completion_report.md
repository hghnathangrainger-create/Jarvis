# Jarvis — Phase 73 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 73 — Approval & Workflow History CLI Status Breakdown (medium: 2 batches, complete)
**Date:** 2026-07-15

---

## Executive Summary

The dashboard's Approval History and Workflow History tabs have shown real Status Breakdown panels since Phase 64, but the CLI's own `show approval history`/`show workflow history` commands never surfaced the equivalent. Phase 73 closes both gaps, completing the "CLI breakdown honesty" arc started in Phase 71 (memory) and continued in Phase 72 (schedule/quarantine) across every domain that has a CLI display command. Batch 1 added a true, all-time status breakdown to Approval History's default `"history"` operation. This closing batch (Batch 2) adds a real, honestly-scoped status breakdown to Workflow History's `"history"`/`"recent"` operations — carefully tallying distinct workflows by their latest status, never raw transition rows — confirms no documentation needed correcting, and closes the phase.

## Baseline

```
Branch:                       phase-4-ai-reasoning-and-write-actions
Phase 73 Batch 1 commit:      f5dee28
Full suite before Batch 2:    3881 passed, 3 skipped, 0 failed
```

## Files Changed (Batch 2)

- **`tools/builtin/workflow_history_tool.py`** — `"history"`/`"recent"` operations' headers now include a real, recent-activity-scoped status breakdown, built by two new methods: `_workflow_status_breakdown_text()` (tallies distinct workflows' latest status via `list_recent_workflow_ids()` + `latest_status_for()`, never the flat transition list) and `_list_header()` (enriches the plain header only when results exist, leaving `_format_many()` itself completely unchanged). The `"get"` single-workflow detail operation is untouched.
- **`tests/unit/test_workflow_history_tool.py`** — `_FakeHistoryStore` gained `list_recent_workflow_ids()`/`latest_status_for()`; nine new tests added, most notably `test_history_header_counts_distinct_workflows_not_raw_transitions`, which seeds one workflow with three transitions and proves it is tallied exactly once, under its latest status.
- **`docs/phase_73_completion_report.md`** (this file, new).

No other file was touched. `README.md` and `docs/user_guide.md` were both checked for an exact quote of the old `"Workflow history:"`/`"Recent workflows:"` headers — neither was found, so neither doc was changed. `tools/builtin/approval_history_tool.py` (Batch 1's own change) was re-confirmed correct during Batch 2 review and was not modified further.

## Exact Workflow History Output Behavior Change

Before:
```
Workflow history:
```

After (using the real `KNOWN_WORKFLOW_STATUSES` values, not the illustrative-only names in the approval prompt):
```
Workflow history (recent activity: workflow_started: 1, workflow_step_started: 0, workflow_step_completed: 0, workflow_step_waiting: 0, workflow_step_failed: 0, workflow_completed: 2, workflow_stopped: 0):
```

`"show recent workflows"` gets the identical treatment on its own `"Recent workflows"` header. The empty-state message (`"Workflow history: none found."`) is unchanged, confirmed by a dedicated regression test. `"show workflow <id>"` (single-workflow detail) is completely unaffected, confirmed by a dedicated test asserting no `"("` appears in its header line.

## Exact Methodology Used for Workflow Status Counts

`_workflow_status_breakdown_text(limit)` calls `WorkflowHistoryStore.list_recent_workflow_ids(limit)` to get distinct, most-recently-active workflow ids, then calls `latest_status_for(workflow_id)` once per id to get each workflow's own current status — the exact same methodology `dashboard/read_model.py`'s own `get_workflow_status_breakdown()` already established and proved in Phase 64. The tally uses `collections.Counter` over these latest-status values only, **never** the flat list of transition rows `"history"`/`"recent"` already fetch for display — a workflow with many transitions is counted exactly once, by its current status. Every status in `KNOWN_WORKFLOW_STATUSES` is included, honest zeros included, in that tuple's own fixed order — never sorted by count. The header explicitly reads `"recent activity: ..."`, never claiming an all-time total, since no all-time per-status aggregation exists for workflows (a workflow's "status" is its own latest transition, not a fixed column).

## Doc Check Result

Both `README.md` and `docs/user_guide.md` were grepped for `"Workflow history:"`, `"Recent workflows:"`, and related exact-output phrasing. **Neither file quotes the tool's literal output at all** (both mention the commands only by name in prose/tables) — no exact stale quote was found, so **neither file was changed**.

## Focused Workflow-History Test Result

```
poetry run pytest tests/unit/test_workflow_history_tool.py -q
23 passed (14 pre-existing, unmodified + 9 new)
```

## Directly Relevant Workflow Routing/End-to-End Test Results

Searched the repo for every other test file referencing `WorkflowHistoryTool`/`workflow_history`, including `tests/unit/test_cli_workflow_history.py` (a CLI-level integration test analogous to Batch 1's `test_approval_history_cli_format.py`) — confirmed it uses only loose `"[OK]" in output` checks, never an exact quote of either header. Ran the workflow-specific cases directly:

```
poetry run pytest tests/unit/test_cli_workflow_history.py tests/unit/test_command_router.py tests/unit/test_dashboard_read_model.py tests/unit/test_dashboard_app.py -q -k "workflow"
130 passed, 466 deselected
```

## Batch 1 Approval Regression Test Results

```
poetry run pytest tests/unit/test_approval_history_tool.py -q
26 passed (unchanged from Batch 1's own closing count)

poetry run pytest tests/integration/test_approval_history_cli_format.py -q
12 passed (unchanged)
```

## Full Suite Result

```
poetry run pytest -q
3890 passed, 3 skipped, 0 failed
(3881 Batch-1 baseline + 9 net-new, exact)
```

## Ruff Result

```
poetry run ruff check tools/builtin/workflow_history_tool.py tests/unit/test_workflow_history_tool.py
```
3 pre-existing `E402` warnings in `tests/unit/test_workflow_history_tool.py` (the established `pytest.importorskip("sqlalchemy")`-before-imports pattern) — confirmed via `git stash` identical before and after this batch's changes. With `--ignore E402`: **All checks passed!**

## git diff --check Result

Clean.

## Final Git Status

```
 M tools/builtin/workflow_history_tool.py
 M tests/unit/test_workflow_history_tool.py
?? dashboard_test.txt
?? docs/phase_73_completion_report.md
```

## Confirmations

- **`dashboard_test.txt`** remained untouched, untracked, and uncommitted throughout both batches.
- No `ApprovalHistoryStore`, `WorkflowHistoryStore`, dashboard, `SecurityManager`, database schema, approval lifecycle behavior, workflow execution/lifecycle behavior, scheduler, quarantine, inbox, memory, AI, or write-action behavior changed anywhere in this phase — the only changes are two list-command header strings, each built entirely from already-existing, already-proven store methods.
- Workflow status counts are confirmed based on **distinct workflow IDs' latest statuses only** — never raw transition rows — proven directly by `test_history_header_counts_distinct_workflows_not_raw_transitions`, which seeds a single workflow with three transitions and asserts it is tallied exactly once.

---

## Status Statement

**Phase 73 complete across both batches: `show approval history` now shows a true, all-time status breakdown, and `show workflow history`/`show recent workflows` now show a real, honestly recent-activity-scoped status breakdown tallied by distinct workflow — both built entirely on already-existing, already-proven store methods, with zero new store method, zero schema change, and zero `SecurityManager` change.**

Phase 73 is now complete and closed.
