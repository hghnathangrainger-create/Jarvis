# Jarvis — Phase 22 Completion Report

**Checkpoint:** complete for its defined scope; not yet tagged.
**Version:** Phase 22 — Minimal Honest Notice of New Scheduled Inbox Activity (Batches 1–2, complete)
**Date:** 2026-07-11

---

## Executive Summary

Phase 22 of the Jarvis AI Operating System is **complete** for the scope defined in `docs/phase_22_implementation_plan.md`: one single-row durable marker, one narrow read-only `InboxStore` query, one pure notice-building function, one optional `JarvisCLI` startup line, and one optional, marker-independent dashboard Overview line. This closes the one concrete gap Phase 21 created — a scheduled result can now be produced entirely unattended, and until this phase, nothing told Nathan it had happened.

Two batches delivered it:

- **Batch 1** (implemented, reviewed, approved) — `storage/models.py::ScheduledInboxNoticeState`, `notice/scheduled_inbox_notice_store.py::ScheduledInboxNoticeStore`, `inbox/inbox_store.py::InboxStore.count_since()`, `notice/scheduled_inbox_notice.py::build_scheduled_inbox_notice()`, `ui/cli.py`'s new optional `startup_notice` parameter, and `main.py`'s new `build_startup_notice()`.
- **Batch 2** (this closure) — real-scheduler-to-real-notice end-to-end tests, an adversarial content-leak sweep, failure verification, the optional dashboard Overview line, README documentation, and this closure review.

As with every prior phase, Jarvis runs and is tested **without any Anthropic API credits**, **without any real network call**, and — new to this phase's own claim — **without any new runtime dependency at all**.

---

## Batch-by-Batch Implementation Summary

### Batch 1 — Marker, Query, Notice Builder, CLI Wiring

`storage/models.py::ScheduledInboxNoticeState` (`scheduled_inbox_notice_state` table) is the project's fourth durable table *shape* — a single-row, upsert-style marker, neither append-only, write-once-then-decided-once, nor per-row mutable like `ScheduleEntry`. It holds exactly `id`, `last_seen_entry_id`, `created_at` — no key/value generality, no per-entry record, no read/unread column. `notice/scheduled_inbox_notice_store.py::ScheduledInboxNoticeStore` exposes exactly two methods, `get_last_seen_entry_id()`/`set_last_seen_entry_id()`, and never imports or queries `InboxEntry`/`ScheduleEntry`. `inbox/inbox_store.py` gained one new read-only method, `count_since(source_type, after_id)`, returning `(count, latest_id, latest_created_at)` — no new write method; `InboxStore`'s public API is now `{append, list_recent, count, get, count_since}`.

`notice/scheduled_inbox_notice.py::build_scheduled_inbox_notice()` is a small, pure function that reads the marker, counts new `scheduled_web_search_summary` entries via `count_since`, and returns one content-free notice line or `None`. `ui/cli.py::JarvisCLI` gained one new, optional, defaulted `startup_notice` parameter, printed once via the existing `self._output` immediately after the banner — every pre-existing `JarvisCLI(orchestrator, ...)` construction continues to work unchanged. `main.py` gained `build_startup_notice()`, which opens its own independent engine over the same configured SQLite file (mirroring `dashboard.py`/`scheduler.py`'s own composition-root pattern) rather than changing `build_orchestrator()`'s widely-depended-on return type (confirmed used by 26 other test files).

**One real bug was found and fixed during Batch 1's own testing**: the original implementation only advanced the marker when at least one matching entry existed. If the very first-ever check found zero scheduled entries, "first run" state would persist indefinitely across every subsequent CLI launch, and the eventual first real scheduled entry would have been silently absorbed as "still historical backfill" rather than ever reported. Fixed by always advancing the marker on the first run — to the sentinel `0` when no entries exist yet, or to the latest existing entry's id otherwise — closing the gap. A regression test locks this in.

### Batch 2 — End-to-End, Adversarial, Failure Verification, Dashboard Line, Closure (this report)

`tests/integration/test_scheduled_inbox_notice_end_to_end.py` (24 tests) uses a real, temporary, file-backed SQLite database, the real `scheduler.run_one_poll_cycle`/`scheduling.scheduled_summary_runner` pipeline (fake search/AI providers, no real network call), and `main.build_startup_notice()` itself — the actual CLI-startup composition step, not a stand-in. It proves: a schedule run through the real scheduler produces a real `scheduled_web_search_summary` entry that a later, independent call to `build_startup_notice()` correctly reports; a second call never re-reports it; four entries in one pass produce exactly one summarizing line, never four; interactive entries are never counted, alongside scheduled ones in the same database; entries at or below the marker are excluded and entries above it are included, both proven directly by manipulating the marker; the notice contains only count/timestamp content — never the query, the AI summary text, or any URL/snippet; a nine-payload adversarial sweep (fake commands, fake system/developer messages, fake tool-call JSON/XML, malicious URLs, sensitive-looking text, a message claiming to be Nathan, 4000-character bodies, and control characters) run through the real scheduler pipeline proves none of it ever reaches the notice text, while confirming it is still safely stored in the Inbox itself; a marker read failure, a marker write failure, an Inbox read failure, and a broken second-engine setup (empty `DATABASE_PATH`) each leave `build_startup_notice()` returning `None` (or, for the write-failure case, still returning the correct notice for that run) without ever raising; `scheduler.py` is confirmed, structurally, to import nothing from the new `notice` package; and a full, real, withdrawn-Tk `DashboardApp` proves the new Overview line shows the real scheduled-entry count while a direct spy on both `ScheduledInboxNoticeStore` methods confirms the dashboard never reads or writes the CLI's own marker.

The optional dashboard Overview line was evaluated per the plan's own §11 decision and implemented as approved: `DashboardOverview` gained `total_scheduled_inbox_count`/`latest_scheduled_inbox_created_at`, computed via `InboxStore.count_since(source_type=SCHEDULED_SOURCE_TYPE, after_id=None)` — deliberately **not** framed as "since you last checked," so the dashboard has no dependency on, or ambiguity about, the CLI's own marker ownership. The line reads `"Scheduled inbox entries: N (most recent: <timestamp>)"` — no unread badge, no dismiss control, no mark-seen action.

README updated with the Phase 22 section, the notice's exact wording and behavior, the dashboard addition, a safety note, and explicit non-goals — only after every test above passed.

---

## Final State

- Full suite: **2513 passed, 0 failed** (up from 2487 post-Batch-1; 2438 pre-Phase-22 baseline). Cumulative running totals: 2438 → 2487 (Batch 1, +49) → 2513 (Batch 2, +26).
- Production files changed: `storage/models.py` (extended), `notice/__init__.py` (new), `notice/scheduled_inbox_notice_store.py` (new), `notice/scheduled_inbox_notice.py` (new), `inbox/inbox_store.py` (extended), `ui/cli.py` (extended), `main.py` (extended), `dashboard/read_model.py` (extended), `ui/dashboard_app.py` (extended).
- Test files changed: `tests/unit/test_scheduled_inbox_notice_store.py` (new), `tests/unit/test_scheduled_inbox_notice.py` (new), `tests/unit/test_inbox_store.py` (extended), `tests/unit/test_cli.py` (extended), `tests/unit/test_main_notice_wiring.py` (new), `tests/unit/test_dashboard_read_model.py` (extended), `tests/unit/test_dashboard_app.py` (extended), `tests/integration/test_scheduled_inbox_notice_end_to_end.py` (new).
- Documentation: `README.md` (extended), `docs/phase_22_implementation_plan.md` (tracked at this closure, per established convention), `docs/phase_22_completion_report.md` (this report).
- `dashboard_test.txt` remains untracked, untouched, and unstaged throughout both batches and this closure commit.
- `pyproject.toml`: unchanged — confirmed directly, no new dependency of any kind.

---

## Plan-vs-Implementation Reconciliation

| Item | Classification | Notes |
|---|---|---|
| `last_seen_entry_id` marker instead of a timestamp | **A** | Implemented exactly as planned; the id-based comparison proved robust in every failure/boundary test. |
| Single-row/upsert-style `ScheduledInboxNoticeState` | **A** | Implemented exactly as planned — the project's fourth table shape, disclosed in its own docstring. |
| `ScheduledInboxNoticeStore` method names `get_last_seen_entry_id`/`set_last_seen_entry_id` | **A** | Implemented with the plan's exact names (the Batch 1 approval message's "get, set" phrasing was treated as descriptive shorthand for "two methods," not a literal rename, and this was flagged explicitly for confirmation at the time — no correction was requested). |
| `InboxStore.count_since()` returning `(count, latest_id, latest_created_at)` | **A** | Implemented exactly as planned. |
| First-run silent initialization | **A** | Implemented as planned — no historical backlog is ever dumped into a first notice. |
| Marker initialization to sentinel `0` when no entries exist yet | **C** | Corrective fix discovered during Batch 1's own testing: the plan's original description ("initialize the marker to the current latest scheduled entry's id, if any exist") did not address the zero-entries case explicitly, and the first implementation left the marker at `None` in that case — causing "first run" state to persist indefinitely and silently swallow the eventual first real entry. Fixed by always advancing to `0` (a value below every real `InboxEntry.id`, which starts at 1) when no entries exist yet, so the very next entry is correctly recognised as new. A regression test locks this in. |
| Optional dashboard Overview decision | **A** | Implemented exactly as planned: included, real-data-only, deliberately decoupled from the CLI's marker (no "since you last checked" framing), no unread/dismiss semantics. |
| No audit events | **A** | Implemented exactly as planned — no new audit event exists anywhere in this phase. |
| No scheduler changes | **A** | Confirmed structurally: `scheduler.py` imports nothing from the `notice` package, and no line of it was modified. |
| No notification dependencies | **A** | Confirmed directly: `pyproject.toml` is unchanged from before this phase. |
| `build_orchestrator()` signature unchanged | **A** | Confirmed by a dedicated test; `build_startup_notice()` is a wholly separate, independent composition step in `main.py`. |

**No unresolved (E) item exists anywhere in this implementation.**

---

## Master Specification Reconciliation

Unchanged from the plan's own §16: Phase 22 is a **minimal local notice** — a CLI startup pull-check producing one content-free heads-up line about scheduled Inbox activity, backed by a single durable integer marker. It is not a desktop notification, a push notification, an email notification, a phone notification, a read/unread system, a notification center, a notification delivery framework, a Core service, dashboard interactivity, a scheduler extension, a task queue, or a messaging system of any kind. The Master Specification was not modified — no repository evidence surfaced during implementation that required it.

---

## End-to-End Behavior Proven

A schedule run through the real `scheduler.py`/`scheduling.scheduled_summary_runner` pipeline produces a real `scheduled_web_search_summary` Inbox entry that a subsequent, independent call to `main.build_startup_notice()` correctly reports, using only a count and a timestamp. A second call never re-reports the same entry. Four entries created in one pass produce exactly one summarizing notice line, never four separate lines. Interactive `web_search_summary` entries are never counted, confirmed alongside real scheduled entries in the same database. Entries at or below the marker are excluded; entries above it are included — both proven by directly setting the marker and observing the resulting count. Repeated CLI startups never accumulate duplicate reports.

---

## Adversarial Content-Leak Findings

Nine adversarial query/body payloads (fake commands, fake system/developer messages, fake tool-call JSON/XML, malicious-looking URLs, sensitive-looking text, a message claiming to be Nathan, 4000-character bodies, and raw control characters) were run through the **real** scheduler-to-Inbox pipeline — not seeded directly, but genuinely produced via `run_one_poll_cycle` with a fake AI provider returning the adversarial summary text — and the resulting CLI startup notice was proven, in every case, to contain neither the adversarial query nor the adversarial summary text, while the same content remained correctly and safely stored, verbatim, in the Inbox itself (confirmed by a direct read immediately after each test). The notice's own content was independently confirmed to consist of only the fixed template wording, a count, and a timestamp.

---

## Failure Findings

A raising `ScheduledInboxNoticeStore.get_last_seen_entry_id()`, a raising `set_last_seen_entry_id()` (after a successful count), a raising `InboxStore.count_since()`, and an empty/broken `DATABASE_PATH` (simulating a failure in `build_startup_notice()`'s own second-engine construction) were each proven, via real monkeypatched failures against the actual `main.build_startup_notice()` call, to never raise and never block CLI startup — the worst observed outcome is a `None` result (no notice shown) or, in the write-failure case, the correct notice still being returned for that run (with the marker simply not advancing, meaning the same notice may honestly reappear next launch). No failure path was found to print any sensitive content, since every failure short-circuits before the string-formatting step is ever reached. `scheduler.py` and the dashboard were both confirmed unaffected: the former via a structural import-absence test, the latter via a full `DashboardApp` construction alongside real scheduler-produced entries with a direct spy proving zero calls to either `ScheduledInboxNoticeStore` method from the dashboard side.

---

## README Changes

Added the Phase 22 section (batch summary, the exact CLI notice wording and behavior, the dashboard Overview addition, a safety note, and explicit non-goals). Documented honestly: the CLI now shows a startup notice when scheduled Inbox entries exist since the marker's last value; the notice is content-free, showing only count/latest timestamp; it counts only `scheduled_web_search_summary` entries; the first run initializes silently to avoid historical backlog spam; the marker is id-based, not timestamp-based; a marker write failure may cause a notice to reappear but never blocks startup; the dashboard remains read-only; this is not desktop/phone/email notification, not a read/unread system, and not a notification center; no scheduler behavior changed; and no Core service exists. Also updated Phase 21's own non-goals line to note that Phase 22 is the first, deliberately minimal step in the notification direction it had explicitly deferred.

---

## Explicit Non-Goal Verification

Confirmed absent from the delivered code: any desktop/OS toast notification, system tray icon, email notification, phone/push notification, notification SDK, or new runtime dependency (`pyproject.toml` unchanged, confirmed directly); a notification table with per-entry read/unread/dismiss records (the only new table holds a single row and a single integer); any Inbox read/unread mutation or dismiss button (`InboxStore` gained no write method); any dashboard write action or notification control (the dashboard's only addition is one read-only summary line, structurally proven never to touch the marker); any Core service, HTTP server, or IPC bridge; any change to `scheduler.py` or scheduled-execution behavior (confirmed both by the file being untouched and by a structural import-absence test); any new schedule action type or arbitrary command scheduling; webpage fetching; and Research Agent or voice/phone work.

---

## Verification

```
poetry run pytest -q
2513 passed
```

Focused suites also run and passing: `tests/unit/test_scheduled_inbox_notice_store.py` (9), `tests/unit/test_scheduled_inbox_notice.py` (23), `tests/unit/test_inbox_store.py` (43, including the new `count_since` coverage), `tests/unit/test_cli.py` (39, including the new `startup_notice` coverage), `tests/unit/test_main_notice_wiring.py` (7), `tests/integration/test_scheduled_inbox_notice_end_to_end.py` (24), `tests/unit/test_dashboard_read_model.py` (36), `tests/unit/test_dashboard_app.py` (36).

`git diff --check`: exit 0 (only pre-existing LF/CRLF warnings, no new whitespace/line-ending errors). No new unrelated lint findings; one real `F401` (an unused import introduced during this batch's own test-writing) was found and fixed before commit. The pre-existing, unrelated `storage/database.py` unused-`Connection`-import finding (noted at Phase 19's own closure) remains untouched, as it is outside this phase's scope.

`git status --short` (immediately before this closure commit): `README.md`, `dashboard/read_model.py`, `inbox/inbox_store.py`, `main.py`, `storage/models.py`, `tests/unit/test_cli.py`, `tests/unit/test_dashboard_app.py`, `tests/unit/test_dashboard_read_model.py`, `tests/unit/test_inbox_store.py`, `ui/cli.py`, `ui/dashboard_app.py`, `notice/`, `tests/integration/test_scheduled_inbox_notice_end_to_end.py`, `tests/unit/test_main_notice_wiring.py`, `tests/unit/test_scheduled_inbox_notice.py`, `tests/unit/test_scheduled_inbox_notice_store.py`, `docs/phase_22_implementation_plan.md`, `docs/phase_22_completion_report.md` pending. `dashboard_test.txt` remains untracked and was not staged.

---

## Final Adversarial Self-Review

- **Did Phase 22 stay minimal?** Yes — one marker table (one row), two store methods, one read-only Inbox query, one pure function, one CLI parameter, one optional dashboard line.
- **Did it become a notification system?** No — no channel abstraction, no delivery history, no per-entry record; confirmed by direct inspection of every file this phase touched.
- **Did it add read/unread semantics?** No — "unread" appears nowhere in the wording, and no per-entry state exists to make it honestly claimable.
- **Did it add dashboard mutation?** No — a direct spy on both `ScheduledInboxNoticeStore` methods proves zero calls from the dashboard's construction/refresh lifecycle.
- **Did it add desktop/email/phone notification infrastructure?** No — `pyproject.toml` is unchanged, confirmed directly.
- **Did it leak query/body/URL content?** No — proven by a nine-payload adversarial sweep run through the real scheduler pipeline.
- **Did it count interactive Inbox entries incorrectly?** No — proven directly, both in isolation and alongside real scheduled entries in the same database.
- **Did it count future source types accidentally?** No — `count_since()` requires an explicit `source_type`; there is no "all entries" default anywhere.
- **Did marker failure block CLI startup?** No — proven for read failure, write failure, and Inbox read failure, all against the real `main.build_startup_notice()` call.
- **Did scheduler behavior remain unchanged?** Yes — `scheduler.py` was not modified, and a structural test confirms it imports nothing from the `notice` package.
- **Did dashboard behavior remain read-only?** Yes — the only addition is one real-data-only summary line; no control, button, or mutation of any kind was added.
- **Did `dashboard_test.txt` remain untouched?** Yes — confirmed present, untracked, and unstaged at every point in both batches and at this closure.
- **Did `docs/phase_22_implementation_plan.md` follow the established convention?** Yes — left untracked through Batch 1, tracked at this closure commit.
- **Are there any hidden Core-service, IPC, task queue, notification SDK, or scheduler changes?** No — confirmed by direct inspection of every file this phase touched and by the explicit non-goal verification above.

---

## Status Statement

**Phase 22 complete for its defined scope: one durable, single-row marker; one narrow, read-only Inbox query; one pure, content-free notice builder; one optional CLI startup line; and one optional, marker-independent dashboard summary line — with the scheduler completely untouched, the dashboard provably still read-only, every failure path provably non-blocking and content-free, and adversarial scheduled-entry content provably unable to reach the printed notice.**

Phase 22 is not, and must not be described as, a notification system, a desktop/email/phone delivery mechanism, a read/unread system, or a step toward a Core service — it is exactly one narrow, evidence-backed heads-up for the single concrete gap the previous phase created, built with the same batch discipline, security review, and honesty standard as every phase before it.
