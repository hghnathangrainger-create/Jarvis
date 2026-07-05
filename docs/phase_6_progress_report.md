# Jarvis — Phase 6 Progress Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 6 — Durable Approvals and Approval-Lifecycle Timeout Enforcement (Batches 1–3, complete)
**Date:** 2026-07-06

---

## Executive Summary

Phase 6 of the Jarvis AI Operating System is **complete** for the scope it was defined to cover: durable approval history, and the full lifecycle of a pending approval (approved, declined, or now expired).

Through Phase 5, every approval decision lived only in memory for the life of one running process: once Jarvis stopped, the record of what had been asked and how it had been decided was gone, except for whatever reached the audit log. Phase 6 made approval decisions **durable**: every request and its outcome is written to SQLite and survives a restart. Batch 3 then closed a remaining gap in the approval *lifecycle* itself: a pending YELLOW request that nobody ever answers now expires automatically after a configurable window, rather than remaining pending forever.

This durability is deliberately **read-only**. Nothing built across Batches 1–3 makes a past decision resumable, replayable, or automatically executable. That boundary is enforced structurally (the history table has no columns for a tool name or its input, and an expired request produces no reusable decision), not just by convention, and it was a condition attached to the scope of every batch from the start.

- **Batch 1 — Durable approval history.** A new `approval_history` table, an `ApprovalHistoryStore`, optional history-recording wired into `ApprovalManager`, a read-only `ApprovalHistoryTool` with five commands, and a real gap fixed in `main.py`: the audit logger was never actually connected to the Approval Manager, so approval decisions were reaching neither the audit log nor any durable record.
- **Batch 2 — CLI polish and documentation.** The five commands' list-view output was enriched to show every required field (previously only the single-item `show approval <id>` view showed tier, decided time, decided by, and reason — the list views showed only id, status, action, and one ambiguous timestamp). This README and this report were added.
- **Batch 3 — YELLOW approval-window timeout enforcement.** A pending YELLOW approval that goes unanswered for a configurable timeout now expires automatically, is recorded durably as `expired` (never as declined), and can never afterward be approved or declined. RED remains structurally outside this lifecycle entirely.

As in every prior phase, Jarvis runs and is tested **without any Anthropic API credits**: AI reasoning is off by default, and all tests use a fake provider.

---

## What Phase 6 Added

### Batch 1 — Durable approval history

- A new `approval_history` table: request id, session id, action, reason, security tier, status (`pending` / `approved` / `declined`, now joined by `expired` — see Batch 3), created time, and — once decided — decided time, decided by, and decision reason.
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

### Batch 3 — YELLOW approval-window timeout enforcement

Through Batch 2, a pending YELLOW approval could sit unanswered indefinitely — nothing ever expired it. This gap was identified against `docs/JARVIS_PROJECT_MASTER_SPECIFICATION_V2_1.md`'s Security Manager chapter, which specifies a configurable YELLOW approval timeout (default 60 seconds) as a required control. Batch 3 closes it, entirely within Phase 6's existing approval-history machinery — no new subsystem, no Workflow Engine, no change to what gets classified GREEN/YELLOW/RED.

- **`ApprovalStatus.EXPIRED`** — a distinct third terminal outcome alongside `APPROVED`/`DECLINED`. It existed in the model as an unused enum member since before this batch; Batch 3 is the first thing that ever produces it. A timeout is never recorded or reported as a decline.
- **`EventOutcome.TIMEOUT`** — likewise existed as dormant scaffolding (`config/constants.py`, already mapped to a WARNING log level in `observability/logger.py`) before Batch 3 ever emitted one. Every expiry emits exactly one `EventOutcome.TIMEOUT` audit event — distinct from the `SUCCESS` (approved) and `BLOCKED` (declined) outcomes used elsewhere.
- **`Settings.approval_timeout_seconds`**, sourced from the `APPROVAL_TIMEOUT_SECONDS` environment variable, **defaults to 60 seconds**, and is validated positive at settings-load time. `main.py` wires this value into the real `ApprovalManager`; `ApprovalManager` also independently rejects a non-positive value if constructed directly, as defense in depth.
- **The exact boundary is `age >= timeout`, not `age > timeout`.** For the default 60-second window: a request that is **59.999 seconds old remains pending**; a request that is **exactly 60.000 seconds old has expired**. This exact boundary is locked in by a dedicated test (`test_expires_at_exactly_the_configured_timeout_not_before`).
- **Expiry is enforced by lazy sweeping, not a background timer or thread.** `ApprovalManager` evaluates every pending request's age only when its own pending-state methods are touched — `get_pending`, `list_pending`, or `has_pending` (including transitively, via `approve`/`decline`, which call `get_pending`). There is no polling loop and nothing runs on a schedule.
- **A pure read of durable history does not, by itself, trigger the sweep.** Commands like `show approval history` read `ApprovalHistoryStore` directly and never touch `ApprovalManager`, so a request that has technically aged past its timeout will still display as `PENDING` until something next touches the manager's pending state (an approval/decline attempt, or any other pending-state check). This is a deliberate consequence of the lazy design, not a defect, and is covered by an integration test that exercises the ordering explicitly.
- **A timeout never creates an `ApprovalDecision`.** `ApprovalDecision` can only represent `approved: bool`; an expiry is not a decision, so it is never forced through that type. Nobody approved or declined the request — its window simply passed.
- **`ApprovalHistoryStore.record_timeout()`** is a new method, structurally separate from `record_decision()`. It sets the durable row's `status="expired"` and `decided_by="timeout"` — a sentinel that can never be confused with a real human decider such as `"user"`.
- **RED cannot enter the pending-approval or timeout lifecycle at all.** `ApprovalRequest` rejects any non-YELLOW tier at construction (unchanged since before Phase 6), so a RED action can never become a pending request in the first place — there is nothing in `_pending` for the timeout sweep to find. This is a structural guarantee, not a policy choice, and is covered by a dedicated regression test.
- **No change to what gets approved, how it's audited, or how durable history is structured beyond the addition of the `expired` status value.** Every existing GREEN/YELLOW/RED rule from Phases 1–5 and Batches 1–2 is unchanged.

---

## Test-hygiene repairs made during Batch 3

Two pre-existing defects, unrelated to timeout behaviour itself, were found and fixed while implementing Batch 3:

- **`tests/integration/test_approval_history_end_to_end.py` previously contained a verbatim copy of `tools/builtin/approval_history_tool.py`'s source code**, dating back to the commit that created the file in Batch 1. It defined no `test_*` functions and silently collected **zero tests** in every "full suite passed" count reported for Phase 6 up to this point — including in this report's earlier drafts. It has now been repaired and contains **12 real integration tests** covering exactly the scenarios this report always intended for it: approved and declined actions appearing in durable history, all five approval-history commands running as GREEN through the real orchestrator, history surviving a simulated restart, a simulated restart not restoring pending approvals, and the existing YELLOW approve/run flow with its auditing.
- **Real `FileCreateTool` integration tests** (in `test_approval_history_cli_format.py` and the repaired `test_approval_history_end_to_end.py`) previously wrote to bare filenames such as `a.txt` and `report.txt`, which resolved against the repository's working directory — leaving untracked files in the repo root every time the suite ran. Both files now build their file-creation commands against pytest's per-test `tmp_path` fixture, so the real `FileCreateTool` is still exercised end to end, but nothing it creates lands anywhere in the repository.

## Maintenance fix made during Batch 3

**`ApprovalHistoryEntry.__repr__` (`storage/models.py`)** was found to be mis-indented at module scope — a stray, dead, module-level function rather than a method on the class, present since the commit that introduced the table. It has been corrected to a proper class method, with no change to its logic or output text, and a regression test now asserts `__repr__` is present in `ApprovalHistoryEntry.__dict__`. This is a debugging-representation fix only: no test or production code path ever depended on the broken behaviour, and there is no schema or database migration involved.

---

## Files Changed Across Batches

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

**Batch 3**
- `approval/approval_history_store.py` (changed) — new `record_timeout()` method.
- `approval/approval_manager.py` (changed) — optional `timeout_seconds` and `clock`, positivity validation, lazy expiry sweeping wired into `get_pending`/`list_pending`/`has_pending`, `create_request` now stamps `created_at` from the injected clock.
- `main.py` (changed) — wires `settings.approval_timeout_seconds` into the real `ApprovalManager`.
- `tests/unit/test_approval_manager_timeout.py` (new) — 12 tests, including the exact `age >= timeout` boundary test.
- `tests/unit/test_approval_history_store.py` (changed) — 5 new tests for `record_timeout`.
- `tests/unit/test_approval_manager_history.py` (changed) — fake history recorder extended with `record_timeout`.
- `tests/integration/test_approval_history_cli_format.py` (changed) — 1 new end-to-end timeout scenario through the real stack; every file-creation command now sandboxed under `tmp_path`.
- `tests/integration/test_approval_history_end_to_end.py` (repaired) — see "Test-hygiene repairs" above; now 12 real tests, also sandboxed under `tmp_path`.
- `storage/models.py` (changed) — unrelated maintenance fix, see above.
- `tests/unit/test_storage_models.py` (new) — 2 tests for the `__repr__` fix.

---

## The Safety Model

Safety is enforced by the **Security Manager** and applied at the **Tool Executor**, the single gate the rest of the system cannot bypass. Phase 6 changed none of this.

- **GREEN — runs automatically.** All five durable-history commands, via the Security Manager's existing, unchanged `"show"` rule. No new Security Manager rule was added or needed.
- **YELLOW — unchanged, plus a bounded wait.** What requires approval, and what running it requires, is unchanged. Batch 3 adds only that an unanswered YELLOW request does not wait forever: it expires after a configurable window instead of remaining pending indefinitely.
- **RED — unchanged, and untouched by timeout.** RED is still always blocked, an approval still can never unlock it, and — as of Batch 3 — RED still cannot even become a pending, timeable request in the first place.

### Durable approval history commands (all GREEN, all read-only)

| Command | Tier |
|---|---|
| `show approval history` | GREEN |
| `show recent approvals` | GREEN |
| `show approved actions` | GREEN |
| `show declined actions` | GREEN |
| `show approval <id>` | GREEN |

Guarantees checked directly against the code (and, where noted, executed):

- **No `tool_name`/`tool_input` anywhere.** Checked directly against `storage/models.py`, `approval_history_store.py`, and the `ApprovalHistoryTool` interface — none of them have a field, parameter, or return value for either.
- **No rehydration.** `ApprovalManager.__init__` never reads from `history_store`. Executed directly (see Tests, Batch 1): a manager creates a pending request, is discarded, and a fresh manager built on the same history store starts with empty pending state and cannot approve or decline the old request.
- **RED still can't reach history, and still can't time out.** `ApprovalRequest` continues to reject any non-YELLOW tier at construction, unchanged since before Phase 6.
- **Approval decisions are audited.** The `main.py` fix connects the existing audit logger to the Approval Manager, so both the audit log and durable history now receive every decision — and, since Batch 3, every timeout.
- **A timeout is never disguised as a decline.** It is written through `record_timeout` (`status="expired"`, `decided_by="timeout"`), never through `record_decision`, and audited as `EventOutcome.TIMEOUT`, never `EventOutcome.BLOCKED` (the outcome used for a real decline).

---

## Tests

- **Batch 1:** `test_approval_history_store.py` (real in-memory SQLite — record/decide/list/get, and a direct check that the returned record type has no `tool_name`/`tool_input` attributes at all), `test_approval_manager_history.py` (fake history recorder — create/approve/decline write correctly, a manager with no history store behaves exactly as before, and the critical no-rehydration guarantee), `test_approval_history_end_to_end.py` (real database, real orchestrator, called directly rather than through the CLI — approved/declined actions appear in history, all five commands are GREEN, history survives a simulated restart, a simulated restart does not restore pending approvals, the existing YELLOW flow and its auditing still work).
- **Batch 2:** `test_approval_history_tool.py` (fake store — every operation's action string, and every required field appearing in list-view output for pending, approved, and declined records, with decision fields cleanly absent for pending ones), `test_approval_history_cli_format.py` (real database, the actual `JarvisCLI` loop — the `[OK]` status label through the real formatting path for all five commands, required fields visible through that same path, the existing approve/decline flow still working through the CLI, and history surviving a simulated restart at the CLI level).
- **Batch 3:** `test_approval_manager_timeout.py` (fake injectable clock — the exact `age >= timeout` boundary, approve/decline after timeout both raising rather than succeeding, `list_pending` excluding expired requests, a request answered before its deadline being unaffected, `timeout_seconds=None` disabling the mechanism entirely, non-positive `timeout_seconds` rejected, the `EventOutcome.TIMEOUT` audit event, `record_timeout` — not `record_decision` — being called, and RED being structurally unable to become a pending, timeable request), `test_approval_history_store.py` (extended with `record_timeout` coverage), `test_approval_history_cli_format.py` (extended with one end-to-end timeout scenario through the real CLI/orchestrator/database stack), `test_storage_models.py` (the unrelated `__repr__` maintenance fix).
- The Phase 1–5 suites continue to pass unchanged (no code touched by any batch affects them).
- **No live Claude API call is made in any test.** A fake provider is used throughout, and database-backed tests use a real in-memory SQLite database.

### Test commands

```powershell
poetry run pytest -v

poetry run pytest tests/unit/test_approval_history_store.py -v
poetry run pytest tests/unit/test_approval_manager_history.py -v
poetry run pytest tests/unit/test_approval_history_tool.py -v
poetry run pytest tests/unit/test_approval_manager_timeout.py -v
poetry run pytest tests/unit/test_storage_models.py -v
poetry run pytest tests/integration/test_approval_history_end_to_end.py -v
poetry run pytest tests/integration/test_approval_history_cli_format.py -v
```

---

## Verification

The full suite has been run directly, repeatedly, in the development environment (`poetry run pytest -v`, Python 3.14.6, pytest 9.1.1). The authoritative, current result:

```
559 passed
0 failed
0 skipped
0 errored
```

This total includes every test from Phases 1–5 and all three Phase 6 batches, plus the test-hygiene repairs and the `__repr__` maintenance fix. No live Claude API call is made anywhere in the suite; AI reasoning is exercised only through a fake provider.

## Required Confirmations

- **No resumable approvals were added in Batch 1, 2, or 3.** No `tool_name`/`tool_input` in the schema, the store, or the tool. No rehydration of pending state on startup. No `approve <id>` path for a request that isn't currently in memory. No automatic execution of anything from history. An expired request produces a terminal `EXPIRED` outcome, not a reactivatable one.
- **No approval safety changed.** Classification, the approval gate, and what requires confirmation are all unchanged from Phase 5. Batch 3 adds a bounded wait to YELLOW; it changes no tier's classification and adds no new way for any action to run.
- **The `main.py` audit/history wiring fix changed only what gets recorded, not what gets approved.** Three additions (build the store, wire it and the existing logger into one `ApprovalManager`, pass that manager into the orchestrator) — no new trust, no new bypass.
- **RED was never touched by Batch 3.** It cannot be created as a pending request, so it was never a candidate for timeout in the first place; there was no RED-specific code to write or guard.

---

## Known Limitations

These are understood, and none affects the stability of what has shipped.

- **Resumable approvals remain explicitly deferred**, not merely unimplemented. Making a past pending request (or a past expired one) resumable is a separate decision, requiring its own safety review, its own reclassification analysis (since a stale `tool_input` could describe a world that no longer matches reality), and its own expiry-vs-resume interaction rules. Nothing across Batches 1–3 moves toward this by accident — the schema structurally cannot support it.
- **Durable history rows have no expiry or pruning of their own.** Batch 3 lets a *pending request* expire; it does not add any policy for deleting or archiving old *history rows* — those still accumulate indefinitely. Worth a policy before the table grows large, but a separate concern from approval-window timeouts.
- **`list_recent` and `list_by_status` cap at 50 entries.** Older entries remain in the database and are reachable via `show approval <id>`, just not via the list views past that cap.
- **The expiry sweep is lazy, not proactive.** A request that has aged past its timeout will still read as `PENDING` from a pure history query until something next touches `ApprovalManager`'s own pending-state methods. This is documented behaviour (see Batch 3 above), not a bug, but worth knowing if a future feature reads history without ever touching the manager.
- **AI reasoning is unaffected by Phase 6** — it remains advisory only, exactly as in Phase 5.

---

## Deferred / Future Candidates (Outside Phase 6)

With durable history and a bounded approval lifecycle now both in place, further work remains possible but is explicitly outside Phase 6's completed scope:

1. **Resumable approvals**, as its own future effort with its own safety review — staleness checks, explicit reclassification if the world has changed, and rules for how resumption interacts with the new `EXPIRED` outcome. This is the one item consistently named, since Batch 1, as requiring a separate architecture decision before it can be scoped at all.
2. **Deeper, still-advisory AI assistance** — richer summaries across memories and approval history, and better suggestions — with the gate always final.
3. **Optional smarter search** over memory, kept advisory and never able to change or remove memories on its own.

None of these is scheduled or designed here. Any future work in this direction will preserve the rule that has held since Phase 1: **no capability, and no AI suggestion, bypasses the Security Manager, and no sensitive action runs without approval.**

---

## Status Statement

**Phase 6 complete for its defined durable approval-history and approval-lifecycle scope.**

Resumable approvals remain explicitly deferred and are not part of Phase 6 completion because they require a separate safety review and architecture decision.
