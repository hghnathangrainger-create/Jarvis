# Phase 22 Implementation Plan — Minimal Honest Notice of New Scheduled Inbox Activity

Status: **Planning only. No production code, tests, or README changes
accompany this document.**

Authoritative repository state this plan builds on, verified directly:
HEAD `0ec3c02` ("Close Phase 21: dashboard Schedules tab, end-to-end/
adversarial verification, and documentation (Batch 3)"), branch
`phase-4-ai-reasoning-and-write-actions`, working tree clean except one
untracked file, `dashboard_test.txt` — Nathan's own artifact, confirmed
present and untouched, not addressed by this plan. `poetry run pytest -q`
— **2438 passed, 0 failed**, re-run fresh for this planning turn.

---

## 1. Purpose

Let Nathan learn, without opening the dashboard, that scheduled runs have
added new `scheduled_web_search_summary` Inbox entries since he last used
the Jarvis CLI — closing the one concrete gap Phase 21 created (an
unattended write that nothing currently surfaces) — using the smallest
honest mechanism that requires no new dependency, no read/unread system,
and no dashboard mutation.

```text
Scheduled Inbox entries exist
↓
CLI startup shows Nathan a small honest notice
↓
Nathan knows to check the Inbox
```

## 2. Scope

**In scope:** one small, durable, single-row marker table and store
tracking the highest already-reported scheduled Inbox entry id; one new,
narrow, read-only `InboxStore` method to count/locate entries newer than
that marker; one small, pure, independently-testable function that
builds the notice text (or decides there is none); one new optional
`JarvisCLI` constructor parameter to print it once at startup; one small,
independent notice-composition step in `main.py`, mirroring
`dashboard.py`/`scheduler.py`'s own "separate engine over the same
SQLite file" pattern rather than changing `build_orchestrator()`'s
existing, widely-depended-on signature; optionally, one new, marker-
independent, real-data-only line on the dashboard Overview tab.

**Explicitly out of scope**, repeated here for closure-time reference:
desktop/OS toast notifications, system tray, email notifications, phone/
push notifications, any notification SDK or new runtime dependency, a
notification table with per-entry read/unread/dismiss state, any Inbox
read/unread mutation, a dismiss/acknowledge control anywhere, any
dashboard write action or notification control, any Core service, HTTP
server, or IPC bridge, any scheduler behavior change, any new schedule
action type, arbitrary command scheduling, webpage fetching, Research
Agent work, and voice/phone work.

## 3. Repository and Precedent Findings

Directly inspected this turn:

- **`inbox/inbox_store.py`** (re-read in full): exactly four methods
  (`append`, `list_recent`, `count`, `get`); no update/delete/read-unread
  method exists. `InboxRecord.id` is drawn from `InboxEntry.id`, an
  autoincrement primary key on an append-only table — ids are strictly
  monotonic with insertion order and never reused, since rows are never
  deleted (confirmed by `storage/models.py::InboxEntry`, re-read in
  full, having no delete anywhere in the codebase).
- **`scheduling/scheduled_summary_runner.py`** (re-read in full):
  `SCHEDULED_SOURCE_TYPE = "scheduled_web_search_summary"` is already an
  importable, public module constant — this plan reuses it directly
  rather than redefining a second string literal, exactly the precedent
  `scheduled_summary_runner.py` itself set by importing
  `_WEB_SEARCH_SUMMARY_LABEL` from `core/orchestrator.py` instead of
  duplicating it.
- **`scheduler.py`**: confirmed, again, to never import `CommandRouter`/
  `ToolExecutor`/`ApprovalManager`/`WorkflowEngine`, and to have no
  awareness of the CLI, the dashboard, or (after this phase) the notice
  marker at all. **This plan makes zero changes to `scheduler.py`** —
  the scheduler's own responsibility ends at writing an `InboxEntry`;
  it has no reason to know anything was "noticed."
- **`dashboard/read_model.py`/`ui/dashboard_app.py`** (re-read in full):
  `DashboardOverview` currently carries `total_memory_count` and
  `total_inbox_count` (both real, unfiltered totals) — no existing field
  is source-type-specific. Adding a scheduled-entries-specific count is a
  small, precedented extension of this same pattern, not a new concept.
- **`storage/models.py`** (re-read in full): three existing table
  *shapes* exist today — append-only (`InboxEntry`/`WorkflowHistoryEntry`),
  write-once-then-decided-once (`ApprovalHistoryEntry`), and per-row
  mutable (`ScheduleEntry`, Phase 21's own disclosed new precedent). A
  single-row, upsert-style marker table (§4) would be a **fourth**,
  genuinely new shape — disclosed explicitly here, exactly as Phase 21
  disclosed `ScheduleEntry`'s own departure from append-only.
- **`main.py`** (re-read in full): `build_orchestrator()` is called from
  26 existing test files (confirmed via direct repository search, not
  assumed) in addition to `main()` itself, and its own docstring states
  it is reused "by scripts and tests" specifically so that contract
  stays stable. **Changing its return type is avoidable and therefore
  not done** — see §7's rejected alternative.
- **`ui/cli.py`** (re-read in full): `JarvisCLI.__init__` already takes
  injectable `input_fn`/`output_fn` specifically for testability, and
  `run()` already prints a fixed startup banner via `self._output` before
  entering its loop. Every existing test constructs `JarvisCLI` with a
  mix of positional/keyword arguments (confirmed via direct grep of
  `tests/unit/test_cli.py`); adding one new **optional**, defaulted
  keyword argument cannot break any of them.
- **`config/constants.py`**: `APP_NAME`/`STARTUP_BANNER` are the existing
  precedent for short, fixed, non-parameterized user-facing strings;
  this plan's notice text is parameterized (count, timestamp) and
  therefore lives in code, not as a second constant here.
- **README Phase 20/21 sections, Phase 21 completion report**: both
  confirm the exact boundary this plan must not blur — Phase 20's Inbox
  is durable storage; nothing "transient attention"-shaped exists yet.
  The Phase 21 completion report's own "likely future pressure points"
  named this directly: "a notification layer now has a real first
  candidate to point to."
- **`pyproject.toml`** (re-read in full): dependencies remain exactly
  `anthropic`, `sqlalchemy`, `pydantic`, `python-dotenv`,
  `duckduckgo-search`. **No new dependency is required by this plan** —
  confirmed directly, not assumed, closing the "notification dependency"
  question the authorizing instructions raised.
- **Existing tests around Inbox/scheduler/dashboard/CLI/storage**:
  `tests/unit/test_inbox_store.py`, `tests/unit/test_cli.py`,
  `tests/unit/test_main_web_search_wiring.py`/`test_main_ai_wiring.py`
  (the precedent for a `main.build_orchestrator()`-level composition
  test, reused in shape for a new notice-wiring test), and the full
  Phase 21 test suite were all re-read to confirm no existing test
  constructs `InboxStore`/`JarvisCLI` in a way this plan's additive
  changes would break.

## 4. The Last-Seen Marker: Design and Storage-Option Evaluation

**Storage options evaluated** (per the authorizing instructions' own
list):

1. *New tiny table, one row* — **selected**. Matches this project's
   unbroken convention that every durable concept gets its own narrow
   table/store, never a shared bucket.
2. *Generic settings table (key/value)* — **rejected**. This project has
   never had, and does not need, a generic settings framework; building
   one now to serve a single value would be exactly the kind of
   premature, overbuilt abstraction the authorizing instructions warn
   against. If a second, unrelated durable setting is ever needed, *that*
   is the moment to evaluate a generic table — not preemptively now.
3. *Notice-specific table with per-entry rows* — **rejected**. This is
   precisely the "notification table with per-entry read/unread/dismiss
   state" the authorizing instructions explicitly forbid. A single
   marker row is sufficient; nothing here is a message, alert, or
   delivery record.
4. *Store the marker inside `InboxEntry`* — **rejected**. `InboxEntry`
   is deliberately append-only with no update method anywhere (confirmed
   §3); adding a mutable field to it, or writing a marker row into it,
   would break that guarantee for the one table this project has been
   most explicit about protecting.
5. *Store the marker inside `ScheduleEntry`* — **rejected**. A
   last-seen marker is not a property of any one schedule; it concerns
   the Inbox as a whole. Conflating them would misuse `ScheduleEntry`'s
   already-disclosed, deliberately narrow mutable surface for something
   it was never scoped to hold.
6. *File-based marker (e.g., a JSON file next to the database)* —
   **rejected**. Every other piece of durable Jarvis state lives in the
   configured SQLite database; a second, separate persistence mechanism
   for one integer would be an inconsistent, harder-to-reason-about
   precedent for no real benefit, and would not participate in the same
   WAL/`busy_timeout` concurrency story the database already provides.

**Marker field design — `last_seen_entry_id`, not `last_seen_at`:**

The authorizing instructions' own candidate field list led with
`last_seen_at` (a timestamp). Evaluated directly against the failure
semantics this same document asks to be addressed — "entries created
exactly at marker timestamp," "clock changes," "malformed timestamp" —
a **timestamp-based** marker requires a strict `>` comparison against
`InboxEntry.created_at`, which is theoretically vulnerable to two rows
sharing an identical microsecond-precision timestamp (extremely unlikely
but not impossible under rapid successive writes), and is directly
exposed to host clock changes in a way this project has already had to
reason carefully about once before (`ScheduleStore.claim_due`'s own
`'localtime'` semantics, Phase 21).

`InboxEntry.id` is an autoincrement primary key on a table that is
**never** deleted from (confirmed §3) — it is therefore strictly
monotonic with insertion order, immune to clock changes entirely, and
requires no timestamp-precision reasoning at all. **Recommendation:
track `last_seen_entry_id: int | None` instead of a timestamp.** The
"latest timestamp" shown in the notice text is still produced — it comes
from the *query result* (the counted entries' own `created_at` values),
never from the marker itself, so nothing about the user-visible wording
changes; only the internal comparison this plan makes more robust.

**Final model:**

```python
class ScheduledInboxNoticeState(Base):
    __tablename__ = "scheduled_inbox_notice_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    last_seen_entry_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, nullable=False
    )
```

**Model name:** `ScheduledInboxNoticeState` — of the three candidate
names offered, this is the most precise and least overclaiming: not
`NoticeState` (too generic — invites future unrelated notices to be
bolted on), not `InboxNoticeState` (ambiguous about whether interactive
Inbox entries are included — they are not, see §7), but explicitly
scoped to the one thing it tracks. "State," not "Notification," in the
name, so nothing about this table's name implies a delivery/read/unread
system exists.

**A genuinely new precedent, disclosed:** this is the project's first
*single-row, upsert-style* durable table — neither append-only, nor
write-once-then-decided-once, nor per-row-mutable-by-id like
`ScheduleEntry`. There is exactly one row, ever; the store (§5) creates
it lazily on first write and updates it in place thereafter. This is
disclosed explicitly, exactly as `ScheduleEntry`'s own departure from
append-only was disclosed in the Phase 21 plan.

## 5. Store API Design

```python
class ScheduledInboxNoticeStore:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None: ...

    def get_last_seen_entry_id(self) -> int | None: ...
    def set_last_seen_entry_id(self, entry_id: int) -> None: ...
```

Two methods, mirroring `ScheduleStore`'s own narrow-API discipline.
`get_last_seen_entry_id()` returns `None` when no row exists yet (never
checked before). `set_last_seen_entry_id()` is an upsert: it updates the
single existing row if one exists, or creates it if this is the very
first write — the only method on this store that writes anything, and
it never touches `InboxEntry` or `ScheduleEntry` in any way.

**Which store performs the counting query?** `InboxStore` — it is
already the sole persistence-facing layer for `InboxEntry` (exactly as
`dashboard/read_model.py`'s own docstring insists no caller reach into
`storage.models` directly), so a new, narrow, read-only method is added
there rather than having the notice module query `InboxEntry` on its
own:

```python
def count_since(
    self, *, source_type: str, after_id: int | None
) -> tuple[int, int | None, datetime | None]:
    """Return (count, latest_id, latest_created_at) for entries of
    source_type with id > after_id (or every such entry if after_id is
    None), ordered so the latest id/created_at pair is correctly
    identified. A pure, read-only count/lookup - no row is ever
    returned in full, and no update/delete method is added anywhere."""
```

This is the **only** change to `InboxStore` in this phase — it adds no
write method, no read/unread concept, and no per-entry mutation. The
`ScheduledInboxNoticeStore` never imports or queries `InboxEntry` at
all; the two stores are fully decoupled, composed only by the small
pure function in §6.

## 6. The Notice-Building Function

A new, small, pure(ish) function — no Tk, no CLI, no orchestrator
required to test it, following this project's established convention
(`format_timestamp`, `format_error_state`, `status_for`, `format_response`
are all tested as pure functions without constructing their surrounding
class):

```python
def build_scheduled_inbox_notice(
    inbox_store: InboxStore, notice_store: ScheduledInboxNoticeStore
) -> str | None:
    """Return one honest notice line, or None if there is nothing to
    report. Never raises - any failure anywhere is treated as "nothing
    to report this run", never as a reason to block CLI startup."""
```

**Algorithm:**

1. Read `last_seen_id = notice_store.get_last_seen_entry_id()`. If this
   raises, return `None` immediately (§9 — a marker read failure
   suppresses the notice for this run only; it never corrupts state and
   never blocks startup).
2. `is_first_run = last_seen_id is None`.
3. Query `count, latest_id, latest_created_at = inbox_store.count_since(source_type=SCHEDULED_SOURCE_TYPE, after_id=last_seen_id)`.
   If this raises, return `None` (same reasoning as step 1).
4. If `latest_id is not None`, advance the marker:
   `notice_store.set_last_seen_entry_id(latest_id)`. If this raises, the
   function still proceeds to return whatever notice text step 5 would
   produce for **this** run — a marker-write failure means the same
   notice may reappear once more next launch, which is honest and safe,
   never a crash and never data loss (§9).
5. If `is_first_run`, return `None` — **silent initialization** (§8):
   the very first launch after upgrading to Phase 22 never dumps a
   potentially large historical backlog; it only starts counting from
   this point forward.
6. If `count == 0`, return `None` — nothing to report.
7. Otherwise, format and return the notice text (§8).

**Correctness of the id-based comparison under concurrent writes:**
because step 3's query and step 4's marker advance both use the *same*
`latest_id` value read in that single call, any `InboxEntry` written by
the scheduler *during* this exact check (a real but narrow race) simply
has a higher `id` and is correctly picked up on the *next* check — it is
never skipped, never double-counted, and never causes the current
check to crash or block.

## 7. Where This Runs, and the Rejected `build_orchestrator()` Change

**Rejected alternative: extending `build_orchestrator()`'s return type**
(e.g., to `tuple[JarvisOrchestrator, str | None]`) so `main()` could get
the notice text "for free" from the same composition step. **Rejected**
because `build_orchestrator()` is called directly by 26 existing test
files (confirmed by direct repository search, not assumed) specifically
because its docstring promises reuse "by scripts and tests" — changing
its signature would ripple across every one of them for a small,
unrelated notice feature, which is exactly the kind of scope-broadening
this plan must avoid.

**Selected design:** the notice check becomes a small, independent
composition step in `main.py`, mirroring `dashboard.py`/`scheduler.py`'s
own established pattern of opening a *second*, independent
engine/session-factory over the same configured SQLite file — never
sharing engine or session-factory state with `build_orchestrator()`'s
own internal one, and adding no new IPC/socket/shared-object concept of
any kind (this is the exact same "shares only the file on disk" pattern
already proven safe three times over):

```python
def build_startup_notice() -> str | None:
    """Independently open the same configured database and build one
    honest startup notice, or None. Mirrors dashboard.py/scheduler.py's
    own composition-root pattern - a second engine over the same SQLite
    file, never sharing state with build_orchestrator()'s own engine."""
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    inbox_store = InboxStore(session_factory)
    notice_store = ScheduledInboxNoticeStore(session_factory)
    return build_scheduled_inbox_notice(inbox_store, notice_store)


def main() -> None:
    orchestrator = build_orchestrator()
    startup_notice = build_startup_notice()
    cli = JarvisCLI(orchestrator, startup_notice=startup_notice)
    cli.run()
```

`JarvisCLI.__init__` gains exactly one new, optional, defaulted keyword
parameter: `startup_notice: str | None = None`. Every existing
`JarvisCLI(orchestrator, ...)` construction in every existing test
continues to work unchanged (confirmed by direct inspection of every
call site — none passes a 3rd positional argument that this would
collide with). `run()` prints `startup_notice` via the existing
`self._output`, once, immediately after `_print_banner()` and before the
first prompt — the smallest possible change to the loop's own shape,
using the exact same output-injection mechanism the banner and every
response already use, so the new line is testable the same way
(`output_fn=list.append` capturing).

**Interactive Inbox entries never notify.** `build_scheduled_inbox_notice`
is hard-coded to `source_type=SCHEDULED_SOURCE_TYPE`
(`"scheduled_web_search_summary"`) only — the interactive
`"web_search_summary"` source type is never counted, matching the
authorizing instructions exactly (Nathan is already looking at the
screen when an interactive summary completes; notifying him of his own
just-typed command would be noise).

## 8. Notice Wording and First-Run Behavior

**Exact wording** (count-aware, singular/plural handled):

```
Jarvis notice: 3 scheduled inbox entries were added since your last check. Latest: 2026-07-11 08:00. Open the dashboard Inbox to review them.
```
```
Jarvis notice: 1 scheduled inbox entry was added since your last check. Latest: 2026-07-11 08:00. Open the dashboard Inbox to review them.
```

**"Added," never "new" or "unread."** "Unread" is deliberately avoided
throughout — no read/unread state exists anywhere in this design, so
using that word would misdescribe what is actually being tracked (a
plain count since a marker, not a per-entry read flag). "Added" is
factual and matches `InboxEntry`'s own nature as an append-only log.

**No real-time/push implication.** The wording names no delivery
mechanism at all — it is printed once, at CLI startup, and says nothing
that could be read as "this just happened" or "Jarvis is watching you
right now." "Since your last check" honestly frames this as a pull,
not a push.

**No claim of trust.** The notice never repeats or summarizes the
entries' own content — it carries no query text, no body text, no URL,
and therefore cannot itself misrepresent an AI-generated summary as a
verified fact; it is purely a count-and-pointer, directing Nathan to the
existing, already-reviewed Inbox display for any actual content.

**First-run behavior (no marker exists yet):** initializes **silently**.
On the very first call after this phase ships, `get_last_seen_entry_id()`
returns `None`; the function advances the marker to whatever the
current latest scheduled entry's id already is (if any exist) and
returns `None` — printing nothing. This deliberately avoids a
potentially large, confusing "47 entries added since your last check"
dump on upgrade day for anyone who had scheduled entries accumulate
before this phase existed, matching the "no notification spam" and
"honest, non-alarming" requirements directly. Every notice after the
first run reports only genuinely new activity.

## 9. Failure Semantics (Explicit Table)

| Scenario | Notice shown | Marker state | CLI startup |
|---|---|---|---|
| Marker table/row missing (first run) | No (silent init) | Initialized to current latest id | Unaffected |
| Marker read failure (DB error, corrupt row) | No | Unchanged | Unaffected — never raises |
| `InboxStore` read failure | No | Unchanged | Unaffected — never raises |
| Marker write failure after a successful count | Yes, this run | Unchanged (may re-report next run) | Unaffected |
| Database locked at startup | No (treated as a read failure) | Unchanged | Unaffected |
| Malformed/corrupt marker value (e.g., a stale/garbage integer) | Whatever the comparison honestly produces | Unchanged until next successful write | Unaffected — an integer comparison cannot raise |
| No scheduled entries at all | No | Unchanged | Unaffected |
| Only interactive (`web_search_summary`) entries exist | No | Unchanged | Unaffected |
| Multiple scheduled entries since last check | Yes, one line, one count | Advances to the highest id counted | Unaffected |
| Entry created exactly "at" the marker | Correctly excluded (`id`, not timestamp, so no boundary ambiguity exists) | N/A | Unaffected |
| Entry created *during* the notice check (race with the scheduler) | Not included this run; included next run | Advances only past what was actually counted | Unaffected |
| Host clock change / DST | No effect — the marker is an id, never a timestamp | Unaffected | Unaffected |

**Every failure path leaves Jarvis's actual startup completely
unaffected** — `build_startup_notice()` itself never raises out of
`build_scheduled_inbox_notice()` (which is designed to catch every
internal exception), and even if `build_startup_notice()`'s own engine
construction somehow failed, `main()` would need a bare `try/except`
around the call so a failing *second* database connection can never
prevent the *primary* one (already opened by `build_orchestrator()`)
from working — this is disclosed as a required defensive wrapper at the
`main()` level, not just inside the notice function itself.

## 10. Audit/Observability Decision

**No new audit event is added in this phase.** The notice check is a
passive, local, read-only startup step with no user-facing content risk
(it never carries query/body text) and no write of consequence (the
marker is a single internal integer, not user data). Adding audit events
here would not meaningfully extend the existing Inbox/scheduler audit
trail (a `scheduled_summary_succeeded` event already exists for the
write that matters) and risks exactly the kind of "notification system
pretending to need its own observability layer" over-build this plan
must avoid. If field experience later shows marker-write failures are
silently recurring in a way worth tracking, that is a small, separately
justified addition — not assumed necessary now.

## 11. Dashboard Overview Line — Decision

**Included, but deliberately decoupled from the CLI's marker.** Rather
than a "since you last checked" framing (which would require the
dashboard to read the *same* marker the CLI owns, creating a confusing
dependency on which process's "last check" is meant), the Overview line
shows a plain, marker-independent, real-data-only summary — reusing
`InboxStore.count_since(source_type=SCHEDULED_SOURCE_TYPE, after_id=None)`
for a true total and latest timestamp, exactly the same pattern
`DashboardOverview.total_inbox_count` already establishes:

```
Scheduled inbox entries: 5 (most recent: 2026-07-11 08:00)
```

No "unread," no "new," no dismiss, no mark-seen, no button, and no read
of — or write to — `ScheduledInboxNoticeStore` from the dashboard side
at all (structurally provable the same way every other dashboard
guarantee already is, via an AST import-absence test and a monkeypatch
spy on `ScheduledInboxNoticeStore` proving zero calls from the dashboard
side). This keeps the dashboard's read-only guarantee, and its complete
independence from the CLI's own state, fully intact.

## 12. Source-Type Scope

The notice counts **only** `source_type == "scheduled_web_search_summary"`
(imported as `SCHEDULED_SOURCE_TYPE` from
`scheduling.scheduled_summary_runner`, never a locally redefined string
literal, so the two can never silently drift apart). It never counts
`"web_search_summary"` (interactive) and never uses an unfiltered
`InboxStore.count()`. `InboxStore.count_since()` takes `source_type` as
a required keyword argument specifically so no caller can accidentally
omit it and count every source type by mistake — there is no
convenience overload that defaults to "all entries."

## 13. Security/Adversarial Review

- **Scheduled Inbox body contains fake commands / malicious URLs /
  prompt injection** → the notice text never includes body content at
  all — only a count and a timestamp, both produced by the count/lookup
  query itself, never read from `InboxEntry.body`. There is no code path
  by which adversarial body text could reach the notice string.
- **Scheduled Inbox query contains sensitive/fake-instruction text** →
  same reasoning; `source_query` is never read by the notice-building
  function.
- **Notice accidentally prints query/body** → structurally impossible
  given the function signature only returns a string built from
  `count`/`latest_created_at`, never from any `InboxRecord` field beyond
  what `count_since` itself returns (which excludes `body`/`source_query`
  entirely — proven by the tuple's own declared shape).
- **Notice line looks like a command / contains a clickable URL** → the
  fixed wording template contains no URL and no command-shaped text;
  this is verifiable by direct inspection of the one template string,
  and testable via a literal-content assertion.
- **Marker corruption causes repeated spam** → the worst case (a marker
  write failure) reports the *same* real entries once more next launch —
  never fabricated entries, never an escalating or unbounded count,
  since each check is a fresh, correct comparison against real data.
- **Marker corruption hides entries** → a garbage-but-valid integer
  marker only ever *widens* what's reported (a lower marker reports
  more, never fewer, real entries) — it cannot cause a real entry to be
  permanently invisible, since ids are monotonic and the "since" bound
  is inclusive of everything after it.
- **Notice failure breaks CLI startup or the scheduler** → `scheduler.py`
  has zero dependency on any file this phase touches (confirmed, no
  changes made to it at all); CLI startup is defended by the
  catch-everything design in §6/§9 plus the `main()`-level wrapper
  around the second engine's construction.
- **Dashboard Overview implies unread/dismiss semantics** → avoided by
  wording ("Scheduled inbox entries: N (most recent: ...)", never
  "unread"/"new"/a badge) and by having no dismiss/mark-seen control
  anywhere on the dashboard, structurally provable.
- **Future `source_type` accidentally counted** → `count_since` requires
  an explicit `source_type` argument; a future third producer would need
  its own explicit, reviewed decision to be included here — it is never
  swept in by a wildcard or an "all inbox entries" default.
- **Notification system becomes a command channel** → the notice string
  is printed via `self._output` exactly like every other CLI output
  line; nothing reads it back as input, parses it, or routes it anywhere
  — it is terminal output, not terminal input.
- **Last-seen marker becomes a generic settings framework too early** →
  explicitly rejected in §4 (option 2); the model and store are named
  and scoped to this one concern only, with no key/value generality
  anywhere in the schema.

## 14. Testing Plan

**Batch 1**: `ScheduledInboxNoticeState` table creation via
`initialize_database`; `get_last_seen_entry_id()`/`set_last_seen_entry_id()`
behavior including the upsert (first write creates the row, second write
updates the same row — never a second row); `InboxStore.count_since()`
correctness (zero entries, only-interactive entries excluded, only-
scheduled entries counted, `after_id=None` counts everything, `after_id`
correctly excludes entries at and below it); `build_scheduled_inbox_notice()`
unit tests covering every row of the §9 failure table via fake/raising
store doubles; first-run silent-initialization behavior; marker
advancement correctness (advances to the counted latest id, not
wall-clock time); a structural test proving `ScheduledInboxNoticeStore`
never imports or queries `InboxEntry`/`ScheduleEntry`; a structural test
proving its own public API is exactly the two approved methods; CLI-level
tests proving `JarvisCLI(orchestrator, startup_notice="...")` prints the
notice exactly once, immediately after the banner, and that
`JarvisCLI(orchestrator)` (no `startup_notice` argument, matching every
existing test) behaves byte-for-byte as it does today.

**Batch 2**: a real-SQLite end-to-end test proving a schedule created and
run through the real scheduler pipeline produces a scheduled Inbox entry
that a subsequent, independent call to `build_startup_notice()`/
`build_scheduled_inbox_notice()` correctly reports; a second such call
proving no re-report after the marker advances; a test with several
scheduled entries created in one batch proving exactly one summarizing
notice line (never one line per entry); a test proving a raising/locked
marker store does not prevent `main.build_startup_notice()` from
returning `None` cleanly; a test proving a raising `InboxStore` behaves
the same way; the optional dashboard Overview line's own tests (real
data, no marker dependency, structural proof the dashboard never touches
`ScheduledInboxNoticeStore`); an adversarial test seeding scheduled Inbox
entries with prompt-injection-shaped/URL-shaped/control-character body
and query text and proving the resulting notice text contains none of it
— only the count and a timestamp; README update; the Phase 22 completion
report; plan-vs-implementation reconciliation.

## 15. Batch Plan

### Batch 1 — Marker Model/Store, `InboxStore` Query, Notice Function, CLI Wiring

- **Purpose**: the durable marker, the narrow `InboxStore` addition, the
  pure notice-building function, and `JarvisCLI`'s new optional startup
  line — fully unit-tested in isolation.
- **Production files**: `storage/models.py` (extended —
  `ScheduledInboxNoticeState`), `notice/__init__.py` (new),
  `notice/scheduled_inbox_notice_store.py` (new), `inbox/inbox_store.py`
  (extended — `count_since()`), `notice/scheduled_inbox_notice.py` (new —
  `build_scheduled_inbox_notice()`), `ui/cli.py` (extended — the new
  optional `startup_notice` parameter and one new printed line),
  `main.py` (extended — `build_startup_notice()`, wired into `main()`
  only; `build_orchestrator()` itself untouched).
- **Test files**: `tests/unit/test_scheduled_inbox_notice_store.py` (new),
  `tests/unit/test_inbox_store.py` (extended — `count_since()`),
  `tests/unit/test_scheduled_inbox_notice.py` (new), `tests/unit/test_cli.py`
  (extended — `startup_notice` behavior), `tests/unit/test_main_notice_wiring.py`
  (new, mirroring `test_main_web_search_wiring.py`'s hermetic-env
  pattern).
- **Invariants protected**: no update/delete method exists on the new
  store beyond the single upsert; `InboxStore` gains no write method;
  `build_orchestrator()`'s signature is unchanged; every existing
  `JarvisCLI` construction continues to work unmodified.
- **Explicit non-goals**: no end-to-end scheduler-to-notice proof yet
  (unit-level correctness only, with fake stores); no dashboard changes;
  no README/completion-report changes.
- **Verification**: focused tests, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files above.

### Batch 2 — End-to-End, Optional Dashboard Line, Adversarial/Failure Verification, Closure

- **Purpose**: real-SQLite proof of the full scheduler-to-notice path,
  the optional dashboard Overview line, the adversarial content-leak
  sweep, documentation, and closure.
- **Production files**: `dashboard/read_model.py`, `ui/dashboard_app.py`
  (both extended — the one new Overview line only, if it survives its
  own low-risk review in Batch 2).
- **Test files**: `tests/integration/test_scheduled_inbox_notice_end_to_end.py`
  (new).
- **Documentation**: `README.md` (Phase 22 section), `docs/phase_22_implementation_plan.md`
  (tracked at closure, per established convention), `docs/phase_22_completion_report.md`
  (new).
- **Verification commands**: the new end-to-end file, then full
  `poetry run pytest -q`, `git diff --check`, `git status`.
- **Commit boundary**: one closure commit. `dashboard_test.txt` remains
  untouched and unstaged throughout.

Batch boundaries are unchanged from the authorizing instructions'
own expected sequence — no repository evidence surfaced during this
review that argues for a different split.

## 16. Plan-vs-Master-Spec Reconciliation

Phase 22 is honestly a **minimal local notice**: a CLI startup pull-check
producing one content-free heads-up line about scheduled Inbox activity,
backed by a single durable integer marker. It is **not** a desktop
notification, a push notification, an email notification, a phone
notification, a read/unread system, a notification center, a
notification delivery framework, a Core service, dashboard interactivity,
a scheduler extension, a task queue, or a messaging system of any kind.
The Master Specification's own "Notification Delivery" section (Dashboard
alert panel + Android push + voice, delivered simultaneously) describes
infrastructure this repository has none of and this phase does not
build any of — the Master Specification is **not** updated, since no
repository evidence proves it cannot be documented correctly without
that change (the README's own Phase 22 section fully captures the real,
narrow behavior).

## 17. Final Adversarial Planning Review

- **Are we solving the right gap after Phase 21?** Yes — this is the
  one concrete, named consequence of Phase 21 (an unattended write
  nothing surfaces), not a speculative feature.
- **Is CLI startup notice enough to call this a useful phase?** Yes —
  it is the one channel Nathan already uses that requires zero new
  infrastructure, and it directly closes the gap; a dashboard-only
  signal would under-deliver since the dashboard is a separate process
  he must choose to open.
- **Are we overbuilding a notification system?** No — one marker
  column, two store methods, one pure function, one printed line; no
  table of per-entry records, no delivery history, no channel
  abstraction.
- **Does the marker create unwanted mutation?** One narrow, disclosed
  mutation (a single integer, in a single-row table, written only by the
  CLI process) — smaller than `ScheduleEntry`'s own already-accepted
  mutable surface.
- **Can the dashboard remain read-only?** Yes — its optional line reads
  only `InboxStore`, never `ScheduledInboxNoticeStore`; structurally
  provable the same way every other dashboard guarantee already is.
- **Are we introducing fake unread semantics?** No — "unread" is never
  used; the wording says "added," and no per-entry state exists to make
  "unread" honestly claimable anyway.
- **Can sensitive query/body text leak?** No — proven by the notice
  function's own signature and the `count_since()` return shape, which
  excludes `body`/`source_query` entirely.
- **Can malicious Inbox text become executable?** No — the notice is
  printed output only, never re-parsed as input by anything.
- **Can notification failure break CLI startup or the scheduler?** No —
  every failure path in §9 leaves both unaffected; `scheduler.py` is not
  modified at all.
- **Are we counting only scheduled entries?** Yes — `count_since()`
  requires an explicit `source_type`, and the notice function hard-codes
  `SCHEDULED_SOURCE_TYPE` imported from `scheduled_summary_runner.py`.
- **Are we accidentally including future source types?** No — there is
  no wildcard/"all entries" path anywhere in this design.
- **Does this reduce Nathan's workload?** Yes, directly — he learns
  about unattended results without having to remember to check.
- **Is desktop notification actually needed now, or correctly deferred?**
  Correctly deferred — no dependency exists, no forcing function beyond
  "would be nice," and the CLI/dashboard channels already close the real
  gap without it.
- **Is this better than webpage-fetch safety as Phase 22?** Yes, for
  this specific boundary — it is smaller, lower-risk, requires no new
  dependency, and is a direct, evidence-backed consequence of the phase
  that just closed, whereas webpage fetch remains independently valuable
  but unrelated to what Phase 21 just created.

## 18. Final Summary

- **Final marker table/model**: `scheduled_inbox_notice_state` /
  `ScheduledInboxNoticeState` (`id`, `last_seen_entry_id`, `created_at`)
  — the project's first single-row, upsert-style durable table,
  explicitly disclosed as a new precedent.
- **Final store API**: `ScheduledInboxNoticeStore.get_last_seen_entry_id()`
  / `set_last_seen_entry_id()` — two methods, no delete, no arbitrary
  key/value generality.
- **Final `InboxStore` addition**: one new read-only method,
  `count_since(source_type, after_id)` — no new write method, no
  read/unread concept.
- **Final CLI startup behavior**: `main.build_startup_notice()` opens a
  second, independent engine over the same configured database
  (mirroring `dashboard.py`/`scheduler.py`), builds the notice via the
  pure `build_scheduled_inbox_notice()`, and passes the result into a new
  optional `JarvisCLI(..., startup_notice=...)` parameter, printed once
  after the banner. `build_orchestrator()` itself is completely
  unchanged.
- **Final notice wording**: "Jarvis notice: N scheduled inbox
  entr{y/ies} {was/were} added since your last check. Latest:
  `<timestamp>`. Open the dashboard Inbox to review them." — never
  "unread," never implying push/real-time delivery, never containing
  query/body/URL content.
- **Final marker advancement semantics**: advances to the highest
  `InboxEntry.id` actually counted this run, never to wall-clock "now" —
  chosen specifically to avoid every timestamp-boundary/clock-change
  edge case the authorizing instructions raised.
- **Final source_type scope**: `scheduled_web_search_summary` only,
  imported from `scheduling.scheduled_summary_runner.SCHEDULED_SOURCE_TYPE`
  — interactive `web_search_summary` entries are never counted.
- **Final dashboard Overview decision**: one new, optional, real-data-
  only, marker-independent line ("Scheduled inbox entries: N (most
  recent: ...)"), decoupled entirely from the CLI's own marker to avoid
  any "whose last-check" ambiguity.
- **Final failure semantics**: every failure (marker read/write,
  `InboxStore` read, corrupt marker value, first-run) leaves CLI
  startup, the scheduler, and the dashboard completely unaffected; the
  worst case is a notice reappearing once more or not appearing this run
  — never a crash, never fabricated content, never a permanently hidden
  entry.
- **Final audit/observability decision**: no new audit event in this
  phase — the check is passive, content-free, and low-stakes; revisit
  only if real-world evidence later justifies it.
- **Final batch sequence**: (1) marker model/store, `InboxStore` query,
  notice function, CLI wiring, unit tests; (2) end-to-end proof, optional
  dashboard line, adversarial/failure verification, documentation,
  closure.
- **Explicit Phase 22 non-goals**: every item listed in §2, restated in
  full at closure.
- **Likely future pressure points**: if Nathan later reports the CLI
  notice isn't enough (e.g., he rarely restarts the CLI), that is the
  concrete, evidence-backed moment to re-evaluate a desktop notification
  — not before; a second scheduled-source-type producer, if ever added,
  would need its own explicit decision about whether to also notify,
  never silently inherited from this phase's hard-coded scope.
