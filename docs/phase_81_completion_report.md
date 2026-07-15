# Jarvis — Phase 81 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 81 — Schedule Naming CLI Grammar (small: 1 batch, complete)
**Date:** 2026-07-15

---

## Executive Summary

`ScheduleCreateTool` and `ScheduleStore` already fully supported an optional schedule `name`, but `CommandRouter.build_input()`'s `"schedule_create"` branch never set a `"name"` input key for any phrasing - a fully-built, already-tested tool capability that was completely unreachable from the interactive CLI. This phase closes that gap with a purely additive CLI grammar/routing change: an optional trailing `" as <name>"` clause is now parsed and passed through, while the existing unnamed grammar remains byte-for-byte unchanged. No tool, store, security, or approval behavior was touched.

## Baseline

```
Branch:                       phase-4-ai-reasoning-and-write-actions
Previous commit:              170de28
Full suite before this phase: 3972 passed, 3 skipped, 0 failed
```

## Files Changed

- **`core/command_router.py`** — `_extract_schedule_create_input()` now returns `(query, time_of_day, name)` instead of `(query, time_of_day)`. The existing last-`" at "` query/time split is completely unchanged; a new, separate split then looks for the first `" as "` (or a bare trailing `" as"` with no name, for the blank-name case) only within the already-isolated post-`" at "` segment - never touching the query. `build_input()`'s `"schedule_create"` branch now includes a `"name"` key only when a non-empty name was parsed.
- **`tests/unit/test_command_router.py`** — 5 new tests: named schedule parses correctly; unnamed schedule is completely unaffected (no `"name"` key at all); a query containing "as" before the final time is not mis-split; a query containing "at" before the final time still uses the last occurrence (regression, now combined with a name suffix); a blank/whitespace-only `" as    "` clause is treated as absent.
- **`tests/integration/test_scheduled_summary_end_to_end.py`** — 1 new end-to-end test, `test_named_schedule_created_via_cli_reaches_schedule_create_tool`, proving the parsed name travels through the real `CommandRouter` → `ToolExecutor` → `ApprovalManager` → `ScheduleCreateTool` → `ScheduleStore` path: the approved confirmation output contains the name, and the stored `ScheduleRecord.name` matches.
- **`docs/user_guide.md`** — added a new schedule-commands table row documenting the optional `as <name>` suffix.
- **`docs/phase_81_completion_report.md`** (this file, new).

No other file was touched. `ScheduleCreateTool`, `ScheduleStore`, `ScheduleEnableTool`, `ScheduleDisableTool`, and `ScheduleListTool` were not modified.

## Exact Schedule Naming Grammar Added

```
schedule web search summary for jarvis news at 08:00 as morning news
```
parses to `{"query": "jarvis news", "time_of_day": "08:00", "name": "morning news"}`, producing:
```
Created schedule 1 (morning news): 'jarvis news' at 08:00 daily.
```

## Exact Unnamed Schedule Behavior Preserved

```
schedule web search summary for jarvis news at 08:00
```
still parses to exactly `{"query": "jarvis news", "time_of_day": "08:00"}` - no `"name"` key present at all (not an empty string) - producing the unchanged:
```
Created schedule 1: 'jarvis news' at 08:00 daily.
```

## Exact Parsing Edge Cases Covered

- **Query containing "as" before the final time** (`"...for cafes known as bistros at 08:00"`): the query's own "as" is never touched, since the name split only ever operates on the segment after the last `" at "` - result: `query = "cafes known as bistros"`, no name.
- **Query containing "at" before the final time, combined with a name** (`"...restaurants open late at night at 22:00 as dinner spots"`): the existing last-`" at "`-wins behavior is fully preserved even with a trailing name clause - result: `query = "restaurants open late at night"`, `time_of_day = "22:00"`, `name = "dinner spots"`.
- **Blank/whitespace-only name** (`"...at 08:00 as    "`): treated identically to no name at all - `time_of_day = "08:00"`, no `"name"` key. (This required a small additional case beyond the initial implementation: `_strip_write_prefix` right-strips the whole command before the name split runs, so a blank `" as    "` clause survives internally only as a bare trailing `" as"` with nothing after it - handled as its own explicit case, verified directly against the failing test before being fixed.)
- **No `" at "` at all** (existing behavior, unchanged): returns `(query, "", "")`.

## User-Guide/README Stale Grammar Update Result

`docs/user_guide.md`'s schedule-commands table (the living, always-current command reference) was updated with a new row documenting the optional `as <name>` suffix. `README.md`'s matching quote (line 631) sits inside the Phase 21 historical build-log section, accurately describing what Phase 21 itself shipped at the time - not a "this is the only grammar today" claim - so it was left unchanged, consistent with README's append-only phase-log convention (confirmed by checking the surrounding context directly).

## Focused Command-Router Test Result

```
poetry run pytest tests/unit/test_command_router.py -q -k "schedule"
26 passed
```

## Schedule-Create Integration/Routing Test Result

```
poetry run pytest tests/integration/test_scheduled_summary_end_to_end.py -q
24 passed
```

## Full Suite Result

```
poetry run pytest -q
3978 passed, 3 skipped, 0 failed
(3972 baseline + 6 net-new, exact)
```

## Ruff Result

```
poetry run ruff check core/command_router.py tests/unit/test_command_router.py tests/integration/test_scheduled_summary_end_to_end.py
```
`command_router.py`, `test_command_router.py`: clean, no warnings.
`test_scheduled_summary_end_to_end.py`: 32 `E402` warnings (a large module-level import block after `pytest.importorskip("sqlalchemy")`). Confirmed via `git stash` before/after comparison to be identical, pre-existing warnings, unrelated to this phase's changes - not introduced by this batch.

## git diff --check Result

Clean.

## Final Git Status

```
 M core/command_router.py
 M docs/user_guide.md
 M tests/integration/test_scheduled_summary_end_to_end.py
 M tests/unit/test_command_router.py
?? dashboard_test.txt
```

## Confirmations

- **`dashboard_test.txt`** remained untouched, untracked, and uncommitted throughout.
- **`ScheduleCreateTool`**, **`ScheduleStore`**, **`ScheduleEnableTool`**, **`ScheduleDisableTool`**, **`ScheduleListTool`**, **`SecurityManager`**, database schema, approval lifecycle behavior, scheduler-runner, dashboard, memory, quarantine, inbox, file, web, workflow, AI, and write-action behavior beyond routing the already-supported `name` field were **not** changed anywhere in this phase - the only change is CLI grammar parsing/routing in `CommandRouter`, making an already-built, already-tested tool capability reachable.

---

## Status Statement

**Phase 81 complete: the interactive CLI can now name a schedule at creation time via an optional trailing `as <name>` clause, reaching `ScheduleCreateTool`'s and `ScheduleStore`'s already-existing `name` support end to end. The unnamed grammar is completely unaffected. Zero new store/tool code, zero security/approval behavior change, zero AI involvement - a pure CLI grammar/reachability fix.**

Phase 81 is now complete and closed.
