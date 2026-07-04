# Jarvis — Phase 6 Progress Report

**Checkpoint:** none yet — Phase 6 is in progress and not yet tagged.
**Version:** Phase 6 — Durable Approvals (Batches 1–2 of an unknown total complete)
**Date:** 2026-07-04

---

## Executive Summary

Phase 6 of the Jarvis AI Operating System is **in progress**. This report covers what has been built and verified so far — Batches 1 and 2 — and is written to be extended or superseded by a full Phase 6 completion report once the phase is finished and tagged, the same way Phase 5's report only became final at its own Batch 4.

Through Phase 5, every approval decision lived only in memory for the life of one running process: once Jarvis stopped, the record of what had been asked and how it had been decided was gone, except for whatever reached the audit log. Phase 6 so far has made approval decisions **durable**: every request and its outcome is written to SQLite and survives a restart.

This durability is deliberately **read-only**. Nothing built in Batches 1–2 makes a past decision resumable, replayable, or automatically executable. That boundary is enforced structurally (the history table has no columns for a tool name or its input), not just by convention, and it was a condition attached to the scope of both batches from the start.

- **Batch 1 — Durable approval history.** A new `approval_history` table, an `ApprovalHistoryStore`, optional history-recording wired into `ApprovalManager`, a read-only `ApprovalHistoryTool` with five commands, and a real gap fixed in `main.py`: the audit logger was never actually connected to the Approval Manager, so approval decisions were reaching neither the audit log nor any durable record.
- **Batch 2 — CLI polish and documentation.** The five commands' list-view output was enriched to show every required field (previously only the single-item `show approval <id>` view showed tier, decided time, decided by, and reason — the list views showed only id, status, action, and one ambiguous timestamp). This README and this report were added.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and all tests use a fake provider.

---

## What Phase 6 Added So Far

### Batch 1 — Durable approval history

- A new `approval_history` table: request id, session id, action, reason, security tier, status (`pending` / `approved` / `declined`), created time, and — once decided — decided time, decided by, and decision reason.
- **No `tool_name` or `tool_input` column exists in this table.** This is the central safety property of the batch: a history row can never be replayed, because the data needed to execute anything was never captured.
- `ApprovalHistoryStore`, a read/write data-access layer for that table.
- `ApprovalManager` gained an optional `history_store` parameter. When supplied, every `create_request` writes a pending row, and every `approve`/`decline` updates it. `ApprovalManager.__init__` never reads from the store — a freshly constructed manager always starts with empty pending state, exactly as before, restart or not.
- A new, read-only `ApprovalHistoryTool` with five GREEN operations (see the command table below), registered like any other tool, going through the same Security Manager and Tool Executor as everything else.
- **`main.py` fix:** previously, `main.py` built no `ApprovalManager` at all, and `JarvisOrchestrator` silently constructed its own disconnected default — so approve/decline decisions were reaching neither the audit log nor (once it existed) durable history. `main.py` now builds the `ApprovalHistoryStore`, wires it and the existing audit logger into one `ApprovalManager`, and actually passes that manager into `JarvisOrchestrator`. Nothing about what gets approved, or how, changed — only what gets remembered about decisions that already happen.

### Batch 2 — CLI polish and documentation

- The list-view formatting in `ApprovalHistoryTool` was enriched. Each entry is now a two-line block: a summary line (id, status, action — unchanged from Batch 1) and a detail line carrying tier and created time always, with decided time, decided by, and decision reason appended only when the record actually has them.
- A pending record's detail line shows only tier and created time — decision fields are omitted entirely, never shown blank or as `None`.
- No change to the five operations, their action strings, or their GREEN classification.
- This README and this progress report.

---

## Files Changed Across Batches So Far

**Batch 1**
- `storage/models.py` (changed) — the `ApprovalHistoryEntry` table.
- `approval/approval_manager.py` (changed) — optional `history_store`, write-only recording, no rehydration.
- `core/orchestrator.py` (changed) — routing for the five commands.
- `main.py` (changed) — the audit/history wiring fix.
- `approval/approval_history_store.py` (new).
- `tools/builtin/approval_history_tool.py`, `tools/builtin/__init__.py` (new / changed) — added to keep the five commands going through the Security Manager and Tool Executor like every other command, rather than special-casing them in the orchestrator.
- `tests/unit/test_approval_history_store.py`, `tests/unit/test_approval_manager_history.py`, `tests/integration/test_approval_history_end_to_end.py` (new).

**Batch 2**
- `tools/builtin/approval_history_tool.py` (changed) — enriched list-view formatting only; no change to operations, routing, or classification.
- `README.md` (changed) — the Phase 6 section.
- `docs/phase_6_progress_report.md` (new) — this report.
- `tests/unit/test_approval_history_tool.py` (new) — direct formatting and operation-mapping tests that Batch 1 did not have (Batch 1 only checked this tool indirectly, via substrings in its integration test).
- `tests/integration/test_approval_history_cli_format.py` (new) — drives the real `JarvisCLI` loop, not just the orchestrator, over a real database.

---

## The Safety Model

Safety is enforced by the **Security Manager** and applied at the **Tool Executor**, the single gate the rest of the system cannot bypass. Phase 6 changed none of this.

- **GREEN — runs automatically.** All five durable-history commands, via the Security Manager's existing, unchanged `"show"` rule. No new Security Manager rule was added or needed.
- **YELLOW / RED — unchanged.** Nothing about what requires approval, or what is blocked outright, changed in Phase 6 so far.

### Durable approval history commands (all GREEN, all read-only)

| Command | Tier |
|---|---|
| `show approval history` | GREEN |
| `show recent approvals` | GREEN |
| `show approved actions` | GREEN |
| `show declined actions` | GREEN |
| `show approval <id>` | GREEN |

Guarantees specific to Phase 6 so far, checked directly against the code (and, where noted, executed):

- **No `tool_name`/`tool_input` anywhere.** Checked directly against `storage/models.py`, `approval_history_store.py`, and the `ApprovalHistoryTool` interface — none of them have a field, parameter, or return value for either.
- **No rehydration.** `ApprovalManager.__init__` never reads from `history_store`. Executed directly (see Tests Added, Batch 1): a manager creates a pending request, is discarded, and a fresh manager built on the same history store starts with empty pending state and cannot approve or decline the old request.
- **RED still can't reach history.** `ApprovalRequest` continues to reject any non-YELLOW tier at construction, unchanged since before Phase 6.
- **Approval decisions are audited.** The `main.py` fix connects the existing audit logger to the Approval Manager, so both the audit log and durable history now receive every decision.

---

## Tests Added

- **Batch 1:** `test_approval_history_store.py` (real in-memory SQLite — record/decide/list/get, and a direct check that the returned record type has no `tool_name`/`tool_input` attributes at all), `test_approval_manager_history.py` (fake history recorder — create/approve/decline write correctly, a manager with no history store behaves exactly as before, and the critical no-rehydration guarantee), `test_approval_history_end_to_end.py` (real database, real orchestrator — approved/declined actions appear in history, all five commands are GREEN, history survives a simulated restart, a simulated restart does not restore pending approvals, the existing YELLOW flow and its auditing still work).
- **Batch 2:** `test_approval_history_tool.py` (fake store — every operation's action string, and every required field appearing in list-view output for pending, approved, and declined records, with decision fields cleanly absent for pending ones), `test_approval_history_cli_format.py` (real database, the actual `JarvisCLI` loop — the `[OK]` status label through the real formatting path for all five commands, required fields visible through that same path, the existing approve/decline flow still working through the CLI, and history surviving a simulated restart at the CLI level).
- The Phase 1–5 suites continue to pass unchanged (no code touched by either batch affects them).
- **No live Claude API call is made in any test.** A fake provider is used throughout, and database-backed tests use a real in-memory SQLite database.

### Test commands

```powershell
poetry run pytest -v

poetry run pytest tests/unit/test_approval_history_store.py -v
poetry run pytest tests/unit/test_approval_manager_history.py -v
poetry run pytest tests/unit/test_approval_history_tool.py -v
poetry run pytest tests/integration/test_approval_history_end_to_end.py -v
poetry run pytest tests/integration/test_approval_history_cli_format.py -v
```

---

## Verification

Batch 1 was confirmed passing by Nathan after implementation. For Batch 2, the following was actually executed directly against the real code in the development environment (not a real `poetry run pytest`, since that environment has no network access to install SQLAlchemy or pytest):

- All 17 tests in `test_approval_history_tool.py` were run directly (via a plain Python harness calling each `test_*` function) against the real `ApprovalHistoryTool` and `ApprovalHistoryRecord` — **17 passed, 0 failed.**
- The eight scenarios in Batch 1's `test_approval_manager_history.py`, including the critical no-rehydration guarantee, were likewise executed directly against the real `ApprovalManager` — **8 passed, 0 failed.**
- `SecurityManager.classify_action()` was called directly for all five action strings — all five returned GREEN via the existing `"show"` rule, with no changes made to `security_manager.py`.
- A full syntax-compile check (`py_compile`) was run across every `.py` file in the project after both batches — all files compile cleanly.

The database-backed tests (`test_approval_history_store.py`, `test_approval_history_end_to_end.py`, `test_approval_history_cli_format.py`) still need a real `poetry run pytest -v` to produce an authoritative pass count for this report, the same as every previous phase's completion report. Recommend running the full suite and sharing the output so this section can be finalised with real numbers.

## Required Confirmations

- **No resumable approvals were added in Batch 1 or Batch 2.** No `tool_name`/`tool_input` in the schema, the store, or the tool. No rehydration of pending state on startup. No `approve <id>` path for a request that isn't currently in memory. No automatic execution of anything from history.
- **No approval safety changed.** Classification, the approval gate, and what requires confirmation are all unchanged from Phase 5.
- **The `main.py` audit/history wiring fix changed only what gets recorded, not what gets approved.** Three additions (build the store, wire it and the existing logger into one `ApprovalManager`, pass that manager into the orchestrator) — no new trust, no new bypass.

---

## Known Limitations

These are understood, and they shape what a future batch could responsibly add. None affects the stability of what has shipped so far.

- **Resumable approvals are explicitly deferred**, not merely unimplemented. Making a past pending request resumable after a restart is a separate decision, requiring its own safety review, its own reclassification analysis (since a stale `tool_input` could describe a world that no longer matches reality), and its own expiry rules. Nothing in Batches 1–2 moves toward this by accident — the schema structurally cannot support it yet.
- **History has no expiry or pruning.** Every request and decision accumulates indefinitely. Not a problem yet, but worth a policy before the table grows large.
- **`list_recent` and `list_by_status` cap at 50 entries.** Older entries remain in the database and are reachable via `show approval <id>`, just not via the list views past that cap.
- **AI reasoning is unaffected by Phase 6 so far** — it remains advisory only, exactly as in Phase 5.

---

## Recommended Next Batch

With durable, read-only history in place and polished, reasonable next steps for Phase 6 include:

1. **Resumable approvals**, as its own batch with its own safety review — staleness checks, explicit reclassification if the world has changed, and expiry rules, exactly as flagged when this scope was deliberately excluded from Batches 1–2.
2. **Deeper, still-advisory AI assistance** — richer summaries across memories and approval history, and better suggestions — with the gate always final.
3. **Optional smarter search** over memory, kept advisory and never able to change or remove memories on its own.

Each will preserve the rule that has held since Phase 1: **no capability, and no AI suggestion, bypasses the Security Manager, and no sensitive action runs without approval.**

---

## Status Statement

**Phase 6 is in progress, not complete.** Batches 1 and 2 have delivered durable, read-only approval history with a polished CLI experience, without introducing any resumable, automatic, or trusted action. This is a mid-phase checkpoint, not a tagged milestone — the `phase-6-...` tag will follow once the phase's remaining scope is decided and delivered, the same way `phase-5-better-memory` was only tagged at Phase 5's own Batch 4.
