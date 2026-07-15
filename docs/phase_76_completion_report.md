# Jarvis — Phase 76 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 76 — Approval History Filtered-View Truncation Honesty (small: 1 batch, complete)
**Date:** 2026-07-15

---

## Executive Summary

Phase 73 Batch 1 gave the default `"history"` operation a real, all-time, all-status breakdown header. Its filtered siblings, `"approved"` and `"declined"`, were deliberately left unchanged at the time (with tests locking that in), but they carry a separate, genuine gap: `list_by_status(status, limit=20)` silently truncates once more than 20 entries of that status exist all-time, with no disclosure at all. This phase closes that gap with a narrow, single-status truncation footer - never a cross-status breakdown - using the store's already-existing `count_by_status(status)` method. `"recent"`, `"history"`, and `"get"` are completely untouched.

An earlier draft of this phase proposed adding the Phase 73 all-status breakdown to `"approved"`/`"declined"` as well; that was rejected because it would print counts for statuses not present in a filtered view (e.g. showing a "declined: 1" count inside `Approved actions`), which reads as though the filtered view contains rows it does not. This revised, approved scope avoids that entirely - only the one status already being displayed is ever counted.

## Baseline

```
Branch:                       phase-4-ai-reasoning-and-write-actions
Previous commit:              b9e929a
Full suite before this phase: 3919 passed, 3 skipped, 0 failed
```

## Files Changed

- **`tools/builtin/approval_history_tool.py`** — new `_format_filtered(records, header, status)` method, used only by the `"approved"` and `"declined"` branches of `run()`. Appends `"\n[showing {shown} of {total} {label}; more {label} exist]"` only when `total > shown`, where `total` comes from one call to `self._history.count_by_status(status)` (that operation's own status only) and `label` is the lowercased header (`"approved actions"` / `"declined actions"`). Empty-state messages are unchanged. `_format_many`, `_format_history`, `_format_entry`, `_format_one`, and the `"recent"`/`"history"`/`"get"` branches are completely untouched.
- **`tests/unit/test_approval_history_tool.py`** — 14 new tests covering: exact footer counts when truncated (approved and declined), no footer when all results fit, no footer when `total == shown`, empty-result message with no footer, each view's total coming from its own status only (a large opposite-status count never leaks in), neutral wording (no "limit"/"increase"), no mutation/extra query beyond the one count call, row order/detail preservation, and explicit regression checks that `"recent"` and `"history"` outputs are unaffected.

No other file was touched. No `ApprovalHistoryStore`, `WorkflowHistoryStore`, `CommandRouter`, `SecurityManager`, dashboard, schema, approval lifecycle, or workflow file was changed.

## Exact Approved/Declined Output Behavior Change

Before (34 approved entries exist, 20 shown):
```
Approved actions:
  [a1] APPROVED - send email
  ... (20 rows)
```

After:
```
Approved actions:
  [a1] APPROVED - send email
  ... (20 rows)

[showing 20 of 34 approved actions; more approved actions exist]
```

Same shape for declined: `[showing 20 of 27 declined actions; more declined actions exist]`.

## Exact Truncation Boundary Behavior

- **All results fit / fewer than limit**: unchanged, no footer (`total == shown`, e.g. 3 of 3).
- **Exactly limit**: unchanged, no footer (20 of 20 - both the real total and the shown count agree).
- **More than limit**: exact footer with real, single-status counts.
- **Empty approved/declined result**: unchanged - `"Approved actions: none found."` / `"Declined actions: none found."`, no footer possible.

## Exact Wording Used

`"[showing {shown} of {total} {label}; more {label} exist]"`, e.g. `"[showing 20 of 34 approved actions; more approved actions exist]"`. Confirmed via test (`test_filtered_footer_wording_never_mentions_a_limit_flag`) that neither `"limit"` nor `"increase"` appears anywhere in the output - this wording does not imply any user-facing CLI limit-adjustment feature, since none exists.

## README/User-Guide Stale Quote Check Result

Grepped both `README.md` and `docs/user_guide.md` for `"Approved actions"` and `"Declined actions"` - **no matches in either file**. Neither doc was changed.

## Focused Approval-History Test Result

```
poetry run pytest tests/unit/test_approval_history_tool.py -q
40 passed
```

## Approval CLI Format Integration Test Result

```
poetry run pytest tests/integration/test_approval_history_cli_format.py -q
12 passed
```
The file's `test_show_approved_actions_prints_ok_status` / `test_show_declined_actions_prints_ok_status` scenarios each use a single approved/declined action (shown == total == 1), so no footer applies - both pass unchanged.

## Full Suite Result

```
poetry run pytest -q
3933 passed, 3 skipped, 0 failed
(3919 baseline + 14 net-new, exact)
```

## Ruff Result

```
poetry run ruff check tools/builtin/approval_history_tool.py tests/unit/test_approval_history_tool.py
```
`approval_history_tool.py`: clean, no warnings.
`test_approval_history_tool.py`: 3 `E402` warnings (module-level imports after `pytest.importorskip("sqlalchemy")`). Confirmed via `git stash` before/after comparison to be identical, pre-existing warnings, unrelated to this phase's changes - not introduced by this batch.

## git diff --check Result

Clean.

## Final Git Status

```
 M tests/unit/test_approval_history_tool.py
 M tools/builtin/approval_history_tool.py
?? dashboard_test.txt
```

## Confirmations

- **`dashboard_test.txt`** remained untouched, untracked, and uncommitted throughout.
- **Recent approvals**, **default approval history**, and **single approval/get** output are byte-for-byte unchanged (explicitly re-verified by dedicated regression tests in this batch).
- **`ApprovalHistoryStore`**, **`WorkflowHistoryStore`**, **`CommandRouter`**, **`SecurityManager`**, dashboard, database schema, approval lifecycle (request/decision/timeout), workflow behavior, scheduler, quarantine, inbox, memory, file, web, AI, and write-action behavior were **not** changed anywhere in this phase - the only change is one new, narrow, read-only formatting method reusing an already-existing store method.

---

## Status Statement

**Phase 76 complete: `show approved actions` and `show declined actions` now disclose an honest, exact truncation footer - using only that status's own real total - when more of that exact status exist than are shown. `"recent"`, `"history"`, and `"get"` are completely unaffected, preserving Phase 73's deliberate decision not to add a cross-status breakdown to filtered views. Zero new store/manager code, zero estimation, zero AI involvement.**

Phase 76 is now complete and closed.
