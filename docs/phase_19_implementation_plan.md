# Phase 19 Implementation Plan — Local Read-Only Dashboard for Existing Jarvis State

Status: **Planning only. No production code, tests, or README changes
accompany this document.**

Authoritative repository state this plan builds on, verified directly:
HEAD `86c3440` ("Close Phase 18: web-search summary end-to-end verification
and documentation (Batch 3)"), branch `phase-4-ai-reasoning-and-write-actions`,
working tree clean. `poetry run pytest -q` — **2112 passed, 0 failed**,
re-run fresh for this planning turn. No pre-existing failure exists.

---

## 1. Purpose

Give Nathan a local, visual, read-only interface for inspecting real durable
Jarvis state — memory, approval history, and workflow lifecycle history —
without reading CLI scrollback or manually issuing multiple `show`/`list`
commands. This is explicitly **not** the Master Specification's full Chapter
21 Dashboard; it is a narrow local viewer over exactly the state that already
exists and is durably queryable today.

## 2. Scope

**In scope:** a new, independent local process (`dashboard.py`) presenting
three views — Memories, Approval History, Workflow History — plus a small
Overview panel, all backed by a new read-model composition layer over the
three existing durable stores. One narrow new read-only method on
`WorkflowHistoryStore`. One narrow, justified SQLite concurrency setting in
`storage/database.py`. Full test/documentation coverage.

**Explicitly out of scope**, repeated here for closure-time reference: any
HTTP server, listener, or served frontend; any remote/LAN/phone reachability;
any authentication, session, or account system; any write, execute, approve,
decline, cancel, resume, or schedule action originating from the dashboard;
any change to `SecurityManager`, `ToolExecutor`, `ApprovalManager`,
`WorkflowEngine`, `CommandRouter`, or any AI-facing module; any new tool; any
goals/projects/knowledge-library data (none exist); any generic `AuditLog`
surfacing (a real, durable 4th data domain, deliberately not approved for
this phase); any durable inbox/notification schema; any fake or invented
metric not backed by real persisted state.

## 3. Repository and Precedent Findings

Directly inspected this turn:

- **`memory/memory_manager.py` / `memory/episodic_memory.py`**: `MemoryManager`
  already exposes `list_recent(limit, category=None)`, `list_by_category`,
  `search`, `count()`, `count_by_category(category)`, and `get(memory_id)`.
  `count()` is a real `SELECT COUNT(*)` — the total memory count is available
  **without loading all records**. `list_recent`/`search` return detached
  `MemoryRecord` dataclasses (no open-session dependency), ordered
  `created_at.desc(), id.desc()` — a stable, deterministic default order.
  `MemoryRecord` has `id`, `content`, `source`, `session_id`, `category`,
  `created_at` — **no `updated_at` field exists**, so there is nothing to
  honestly display for "last modified." Categories are exactly
  `general, personal, project, preference, note` (`memory/memory_models.py`).
- **`approval/approval_history_store.py`**: `list_recent(limit)` (clamped to
  `[1, 50]`), `list_by_status(status, limit)`, `get(request_id)`. Fields:
  `request_id`, `session_id`, `action`, `reason`, `security_tier`, `status`
  (`"pending" | "approved" | "declined" | "expired"`), `created_at`,
  `decided_at`, `decided_by`, `decision_reason`. No `tool_name`/`tool_input`
  column exists anywhere (by design). Ordering is `created_at.desc(),
  id.desc()`.
- **`workflow/workflow_history_store.py`**: `list_recent(limit)`,
  `list_for_workflow(workflow_id, limit)` (oldest-first, the chronological
  story of one workflow), `latest_status_for(workflow_id)`. Fields:
  `workflow_id`, `session_id`, `status` (one of `WorkflowEngine`'s seven
  lifecycle event names), `step_number`, `step_total`, `tool_name`,
  `approval_request_id`, `detail`, `created_at`. **No method returns the set
  of distinct workflow ids** — `list_recent` returns individual transitions
  across every workflow mixed together, which is insufficient on its own to
  build a "recent workflows" overview without risking a chatty workflow's
  many step-transitions crowding a quieter, older workflow out of a fixed
  transition-count window. This is a real gap in the existing API surface,
  addressed in §5 below.
- **`storage/database.py`**: `create_database_engine` builds a plain
  `sqlite:///<path>` engine with `future=True`, no journal-mode or
  busy-timeout pragma configured beyond the existing
  `PRAGMA foreign_keys=ON` connect listener. **No WAL mode is enabled.**
  `session_scope` commits/rolls back/closes deterministically; sessions are
  never leaked across calls. Confirmed empirically this turn (see §9): a
  `DateTime(timezone=True)` column's default (`datetime.now(timezone.utc)`)
  retains `tzinfo` on the same in-process object immediately after flush, but
  **comes back naive (`tzinfo=None`) once reloaded from SQLite** in a fresh
  query — SQLite has no native timezone-aware storage type, and SQLAlchemy's
  SQLite dialect does not restore it. This is the "known naive-timestamp
  debt" the authorizing instructions referred to; addressed honestly in §13.
- **`main.py`**: the existing composition-root pattern
  (`create_database_engine` → `initialize_database` → `create_session_factory`
  → construct stores) is directly reusable by a second, independent
  entry point with zero changes to `main.py` itself.
- **UI dependencies**: `tkinter` (with `ttk`) is available in this
  environment (`Tk 8.6`, verified by direct import) as part of the Python
  standard library — **zero new dependency**. Neither `rich` nor `textual`
  is present in `poetry.lock`. No `fastapi`/`uvicorn`/`flask` is present, and
  none will be added.
- **Launch convention**: Jarvis is launched via `poetry run python main.py`
  (README "How to Run"). No `[tool.poetry.scripts]` entries exist. A parallel
  top-level `dashboard.py`, launched via `poetry run python dashboard.py`,
  is the natural, consistent extension of this convention.

## 4. Read-Model Boundary — Architecture Comparison

| Option | Coupling | Testability | UI/persistence separation | Scope | Reuse by a future inbox/dashboard extension | Premature-abstraction risk |
|---|---|---|---|---|---|---|
| A. UI calls all three stores directly | High — UI imports `MemoryManager`, `ApprovalHistoryStore`, `WorkflowHistoryStore` individually | Requires a real UI harness to test any composition logic | Poor — view code decides ordering/derivation | Smallest short-term | None — logic is trapped inside UI code | Low, but pays for it in coupling |
| **B. A narrow `DashboardReadModel` composes read-only queries across the three stores** | Low — UI depends on one small, typed interface; the read model depends on the three existing stores' existing public methods only | High — pure Python, testable with zero UI/Tk involvement | Clean — persistence composition lives entirely below the UI | Small, one new module | High — the exact shape a future durable-inbox or second UI would want to reuse | Low — this is a single-purpose composition module, not a framework |
| C. Dashboard invokes existing read-only tools and parses outputs | High — couples the dashboard to CLI-formatted display strings | Very low — parsing display strings is brittle by construction | None — presentation formatting becomes a hidden dependency | Deceptively small, expensive later | None — CLI-formatted strings are not a reusable shape | High — this is exactly the anti-pattern `ai/memory_ingestion.py`'s own docstring already rejected for a different reason (coupling ingestion to `MemoryTool`'s CLI formatting) |
| D. Dashboard reads SQLAlchemy models/session directly | High — duplicates query logic (ordering, category normalization, limit clamping) already written once in the stores | Medium — testable, but re-implements existing, already-tested logic | Poor — the UI layer would need to know column names and SQLAlchemy query syntax | Larger than necessary | Low — duplicated logic doesn't generalize | Medium — not a "framework," but a needless duplication of working code |

**Decision: Option B.** A new `dashboard/read_model.py` module defines small,
frozen view-model dataclasses and a `DashboardReadModel` class whose
constructor takes the three existing store instances (`MemoryManager`,
`ApprovalHistoryStore`, `WorkflowHistoryStore`) and whose methods call only
their existing public read methods — never a raw session, never a CLI tool,
never parsed text. This is not a generic CQRS or event-sourcing framework:
it is one small, dashboard-specific composition module, exactly as narrow as
`ai/web_search_ingestion.py` was for its own single purpose.

One new store-level method is justified by direct evidence (§3): a distinct
"most recently active workflows" query is a real gap in
`WorkflowHistoryStore`'s existing surface, not something `DashboardReadModel`
should paper over by re-deriving it unreliably from `list_recent`. It belongs
on the store itself (mirroring how `count()`/`count_by_category()` already
live on `EpisodicMemoryStore`, not in a higher-layer composition module),
because it is a generically useful workflow-history capability, not a
dashboard-only concern:

```python
def list_recent_workflow_ids(self, limit: int = 10) -> list[str]:
    """Return the ids of the most recently active workflows, newest first.

    Distinct workflow_ids ordered by each workflow's own most recent
    transition, not by individual transition rows — so a workflow with
    many steps cannot crowd an older, distinct workflow out of the
    result window.
    """
```

Implemented as a `GROUP BY workflow_id ORDER BY MAX(created_at) DESC LIMIT
:limit` query — read-only, adds no column, no table, no write path.
`DashboardReadModel` then calls `latest_status_for(workflow_id)` (already
existing) for each returned id to build the full row — no duplicated
"latest transition" logic.

## 5. Exact Read-Model Shape

New module: `dashboard/read_model.py`.

```python
@dataclass(frozen=True, slots=True)
class MemoryRow:
    id: int
    category: str
    preview: str        # content truncated to a fixed display length
    full_content: str    # untruncated, for a detail view only
    created_at: datetime  # naive-but-UTC; see §13 for display rules

@dataclass(frozen=True, slots=True)
class ApprovalRow:
    request_id: str
    action: str
    security_tier: str
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None

@dataclass(frozen=True, slots=True)
class WorkflowTransitionRow:
    status: str
    step_number: int | None
    step_total: int | None
    tool_name: str | None
    detail: str | None
    created_at: datetime

@dataclass(frozen=True, slots=True)
class WorkflowRow:
    workflow_id: str
    latest_status: str
    latest_step_number: int | None
    latest_step_total: int | None
    latest_created_at: datetime

@dataclass(frozen=True, slots=True)
class DashboardOverview:
    total_memory_count: int
    recent_approvals: tuple[ApprovalRow, ...]
    recent_workflows: tuple[WorkflowRow, ...]

class DashboardReadModel:
    def __init__(
        self,
        memory: MemoryManager,
        approvals: ApprovalHistoryStore,
        workflows: WorkflowHistoryStore,
    ) -> None: ...

    def get_overview(self) -> DashboardOverview: ...
    def get_recent_memories(
        self, limit: int = 20, *, category: str | None = None
    ) -> list[MemoryRow]: ...
    def get_recent_approvals(self, limit: int = 20) -> list[ApprovalRow]: ...
    def get_recent_workflows(self, limit: int = 10) -> list[WorkflowRow]: ...
    def get_workflow_transitions(
        self, workflow_id: str, limit: int = 50
    ) -> list[WorkflowTransitionRow]: ...
```

Every field above maps to a real, already-persisted column. Nothing is
invented. `MemoryRow.preview` truncates `MemoryRecord.content` to a fixed
length (see §12); `full_content` carries the untruncated value for an
explicit detail view only — the read model computes both once, so the UI
layer never re-truncates or re-derives anything.

## 6. Dashboard v1 Information Architecture

- **Overview**: total memory count (`MemoryManager.count()`); the 5 most
  recent approval decisions (action, tier, status, timestamp); the 5 most
  recently active workflows (id, latest status, latest step/of-total).
- **Memories view**: recent memories, optionally filtered by category
  (reusing `list_recent(category=...)` — the same optional filter the CLI
  already exposes); id, category, preview; full content on row
  selection/detail view; created timestamp.
- **Approval History view**: recent decisions; action/reason context;
  security tier; status; created/decided timestamps; decided-by.
- **Workflow History view**: recent distinct workflows with latest status;
  selecting one shows its full, oldest-first transition list (status, step
  number/of-total, tool name, detail, timestamp) via
  `get_workflow_transitions`.

**Explicitly not displayed**, per the authorizing instructions and confirmed
by direct inspection that no real, durable source exists for any of them:
fake system health, fake AI activity, fake agents, fake plugins, fake cost
tracking, fake scheduled tasks, goals/projects, ephemeral (non-durable)
live web-search or AI-summary results, and any AI-provider status panel.

## 7. Refresh Model

Compared: (A) manual refresh only, (B) fixed periodic polling/requery, (C)
file/database change watching, (D) event bus/IPC.

**Decision: a fixed periodic requery (B), implemented via Tk's own
`.after()` scheduler calling the exact same function a manual "Refresh now"
button invokes** — not a background thread, not a file watcher, not an
event bus. `.after()` callbacks run on the Tk main loop itself, so there is
no cross-thread SQLAlchemy session sharing and no new concurrency class to
reason about. Default interval: **5000 ms**. A manual "Refresh now" control
is also provided for on-demand use. The dashboard is described in the UI
and documentation as **"current as of last refresh,"** never as "real-time"
or "live" in the networked sense — it is honest, periodic polling of a local
file. A query that raises `OperationalError` (including a transient SQLite
lock) is caught per-panel and renders that panel's error state without
crashing the dashboard or affecting the Jarvis CLI process in any way (§14).

## 8. Process Architecture and Concurrency

**Direct empirical verification this turn** (temporary script, discarded):
a `DateTime(timezone=True)` value written via the existing `_utc_now`
default retains `tzinfo` on the same Python object post-flush, but reloads
**naive** from a fresh query — confirming the naive-timestamp debt is real
and must be handled honestly in display (§13), not silently "fixed" by
reinterpreting a naive value as anything other than UTC-in-substance.

**SQLite concurrency finding:** the current engine configuration has no WAL
mode and no `busy_timeout` pragma. Under SQLite's default rollback-journal
mode, a second process opening the same file for reads can receive a
`database is locked` (`OperationalError`) if its read happens to overlap a
writer's commit window, with no automatic wait. This is a real,
previously-undocumented risk specifically introduced by this phase (Jarvis
has never before had a second process reading its database file
concurrently).

**Decision:** add two connect-time pragmas to `storage/database.py`'s
existing `Engine, "connect"` event-listener pattern — `PRAGMA
journal_mode=WAL` and `PRAGMA busy_timeout=2000` (2 seconds) — as a small,
narrowly-justified, evidence-backed addition, not a redesign. WAL mode is
SQLite's own standard, well-documented mechanism for exactly this
reader/writer pattern (one writer and any number of concurrent readers
without blocking each other); `busy_timeout` gives any remaining edge case
(e.g. two writers) a short, bounded wait instead of an immediate error. This
is not "infrastructure ahead of a second use case" — the second use case
(a second, independent reader process) is precisely what this phase builds,
so the prerequisite is directly, immediately consumed, not spec-built ahead
of need. This changes no existing single-process behavior at all.

**Process architecture:** a wholly separate local entry point,
`dashboard.py` at the repository root, mirroring `main.py`'s own shape. It
independently calls `create_database_engine()` → `initialize_database()` →
`create_session_factory()`, constructs its own `MemoryManager`,
`ApprovalHistoryStore`, `WorkflowHistoryStore`, and `DashboardReadModel`, and
launches the Tk application. **No IPC, no shared Python objects, and no
control relationship with `main.py`/the CLI in either direction** — the two
processes only ever share the same SQLite file on disk. `main.py` is not
modified to launch, monitor, or depend on the dashboard in any way (§14).
Launch command: **`poetry run python dashboard.py`**.

**Session lifecycle:** every read-model call opens and closes its own
session via the existing `session_scope` context manager (exactly like every
store method already does) — no session is held open across UI refresh
cycles, no session is shared across `.after()` ticks, and nothing new is
introduced here beyond calling already-existing, already-tested store
methods.

## 9. UI Technology Selection

| Option | Dependency impact | Windows compatibility | Packaging | Testing | Visual quality | Refresh support | Table/list rendering | Maintainability |
|---|---|---|---|---|---|---|---|---|
| **A. `tkinter`/`ttk` (standard library)** | **Zero new dependency** — verified present and working (Tk 8.6) | Native, first-class on Windows | None — ships with Python | `ttk.Treeview`/labels are inspectable via their own API; a hidden (`withdraw()`-ed) root is a standard, accepted test pattern | Plain but can look intentional with `ttk` styling (restrained dark/system theme where the platform theme supports it) | `.after()` built in, no extra library | `ttk.Treeview` is a genuine multi-column sortable table widget | High — no external release cycle to track |
| B. Rich/Textual terminal UI | New direct dependency (`textual`, not currently installed) | Good, but a *second* kind of UI surface alongside the existing CLI, some overlap in purpose | Adds a dependency and its own transitive tree | Textual has its own test harness, added learning cost | Can look very polished | Built-in reactive refresh | Good list/table widgets | Medium — newer, faster-moving library |
| C. Another lightweight desktop toolkit (e.g. PySimpleGUI, PyQt/PySide) | New dependency, in some cases a large one (Qt) | Good, but heavier install | Non-trivial (Qt packaging is not small) | Varies, generally more setup | Can be the most polished | Built-in | Good | Lower — larger surface to maintain for a single-purpose viewer |

**Decision: Option A, `tkinter`/`ttk`.** It is the only option with zero new
dependency, is already verified functional in this exact environment, needs
no packaging story beyond what Jarvis already has, and its `ttk.Treeview`
widget directly satisfies the table/list rendering need for all three views.
It is not the most visually striking option, but a "restrained,
system-styled, intentional" viewer (§11) is exactly what a `ttk`-based
interface can honestly deliver without overclaiming. Rich/Textual (Option B)
is a reasonable option for a *future* richer-terminal-UI direction if ever
revisited, but introduces a new dependency for a capability `tkinter`
already covers today — rejected for that reason, not for any technical
flaw.

## 10. Visual Design

Window title: **"Jarvis — Dashboard (read-only)"** — the "(read-only)" is
part of the title itself, not just documentation, so the authority boundary
is visible at a glance. Navigation: a `ttk.Notebook` with four tabs
(Overview, Memories, Approval History, Workflow History). Layout: a
`ttk.Treeview` per list view, a small detail/status pane below it, a
"Refresh now" button and a small "Last refreshed: <timestamp>" label in a
consistent location across all tabs. Empty states render an explicit,
honest message ("No memories stored yet." / "No approval decisions
recorded yet." / "No workflow activity recorded yet.") rather than a blank
pane. A query failure renders a small inline error banner in that tab only
("Could not read workflow history: <short reason>") without affecting other
tabs or the Jarvis CLI process. A restrained dark/system-style theme is
used only insofar as `ttk`'s theme support allows cleanly (no custom-drawn
chrome, no attempt to fight the toolkit). Explicitly excluded, per the
authorizing instructions: any 3D globe, animated hologram, camera feed,
voice waveform, fake CPU visualization, fake "AI thinking" animation, or
agent-swarm visualization — none of these have real data behind them in
this repository, and none are approved for this phase.

## 11. Memory Privacy/Readability Review

The Memories tab shows only `id`, `category`, and a **fixed-length preview**
(120 characters, mirroring the general order of magnitude already used by
`ai/*_ingestion.py`'s own per-item truncation conventions, though this is a
display truncation, not an AI-context budget) by default — not full content.
Full content is revealed only when a row is explicitly selected, in a
separate detail pane. This is a deliberate, if modest, shoulder-surfing
consideration for a locally-visible window: opening the dashboard does not
immediately dump every stored memory's full text onto the screen. This is
explicitly **not** a security boundary and no authentication is introduced
for the local dashboard in Phase 19 (per the authorizing instructions) — it
is a presentation choice only.

## 12. Timestamp Honesty Review

Confirmed empirically (§8): every `created_at`/`decided_at` value is
UTC-in-substance (produced by `_utc_now()`) but reloads from SQLite as a
**naive** `datetime` (no `tzinfo`). The dashboard must not call
`.astimezone()` or otherwise treat these values as local time — doing so
would silently misinterpret a naive-but-UTC value as naive-but-local and
shift it incorrectly. **Decision:** format every displayed timestamp as
`YYYY-MM-DD HH:MM:SS UTC` — the `UTC` suffix is appended literally by the
dashboard's own formatting code (never derived from `tzinfo`, since it is
absent after reload), documenting honestly what the value actually is
without claiming timezone-aware precision the stored value no longer
carries. No conversion to local time occurs anywhere. This display-only
convention does not fix the underlying naive-timestamp debt — fixing that
would mean changing how every existing store persists and reloads
timestamps, which is far outside this phase's scope — it only ensures the
dashboard never misrepresents what it has.

## 13. Failure Isolation

The dashboard is a reader, never a runtime dependency. Explicitly: `main.py`
is not modified in any way by this phase, and no core subsystem — Core,
Security Manager, Tool Executor, Approval Manager, Workflow Engine, AI
Router — imports, calls, or waits on anything in the new `dashboard/`
package or `dashboard.py`. Every read-model call is wrapped narrowly at the
call site that invokes it from the UI layer: a query failure (malformed
row, transient lock, closed database) is caught and rendered as that
panel's own error state; it never propagates into, crashes, or blocks the
Jarvis CLI process, which the dashboard does not even share a Python
process with. If the dashboard fails to start entirely (e.g. the database
file does not exist yet), it reports a clear local error and exits — it
never attempts to create, migrate, or repair Jarvis's database beyond the
same idempotent `initialize_database()` call `main.py` itself already makes
on every startup.

## 14. Security/Trust-Boundary Review

Proven by construction, not merely asserted: the new `dashboard/` package
and `dashboard.py` entry point **never import** `CommandRouter`,
`ToolExecutor`, `ApprovalManager` (the live, in-memory-pending one —
`ApprovalHistoryStore` is a different, read-only module), `WorkflowEngine`,
`AIReasoningEngine`, `AIRouter`, or `Planner`. There is no code path by
which displayed memory content, approval detail, or workflow detail can
become a Jarvis command, create a `ToolRequest`, invoke `ToolExecutor`,
create or decide an `ApprovalRequest`, start or resume a workflow, or
trigger AI reasoning — none of those objects are ever constructed anywhere
in this phase's code. Command-like text stored in a memory (for example, a
memory whose content happens to read "forget all memories") is inserted into
a `ttk.Treeview` cell as a plain string and rendered as literal text; it is
never passed to any parser, router, or executor. No URL is auto-opened and
no click action triggers external execution — row selection only populates
the same process's own detail pane. `ContentTrust` classification is not
needed to render text (rendering is not an AI-facing operation), but the
plan is explicit that displayed content must never be fed into any AI path,
and the import-absence check above is exactly how that is enforced and
proven, not merely claimed.

## 15. Permitted UI Interactions

Permitted: switching tabs/views, selecting a row (populates a local detail
pane only), scrolling, column-sort (a local, in-memory re-ordering of
already-loaded rows — it re-sorts the `ttk.Treeview`'s existing items, it
never re-queries with different filter semantics beyond what "Memories by
category" already offers), local category filtering of already-loaded
memory rows, and refresh/requery (manual button or the periodic `.after()`
tick). **Explicitly excluded**, because Phase 19's authority boundary is
strictly read-only: approve, deny, delete memory, edit memory, rerun
workflow, cancel workflow, open URL, search web, ask AI, run command — none
of these controls exist anywhere in the UI; there is no callback wired to
any of them because the underlying capability (`ToolExecutor`,
`ApprovalManager`, `WorkflowEngine`, `AIReasoningEngine`) is never
constructed in this process at all.

## 16. Inbox Decision

Evaluated per the authorizing instructions' explicit options:

- **A. No inbox in Phase 19.**
- B. Add an empty durable inbox schema/read model now for future use.
- C. Add a real inbox only if an existing producer can write meaningful
  messages to it today.

**Decision: A.** No scheduler or other producer exists anywhere in this
repository today (confirmed directly — no timer/wake loop, no schedule
table, no notification-delivery code), so Option C does not apply (there is
nothing to produce a meaningful message), and Option B would be exactly the
"infrastructure ahead of a second real use case" pattern this project has
repeatedly and explicitly rejected. An empty inbox table would sit unused
and untested-by-real-use until a scheduler exists, at which point its exact
shape would be designed against that scheduler's real requirements anyway —
building it now would not save real work later, only add speculative,
unverified schema. No inbox of any kind is added in Phase 19.

## 17. Master Specification Reconciliation

Phase 19 is honestly described as **Local Read-Only Dashboard for Existing
Jarvis State** — not the full Chapter 21 Dashboard, not the "Web Dashboard
chat interface" named in Chapter 26's roadmap, not the FastAPI server named
in Chapter 29's startup sequence, not the Android Client, not a remote
client, not a command center, not an approval UI, and not an AI chat UI.

Chapter 21 concepts **partially realized**: "Memory" (browse/filter by
category — but not edit/delete/export, and not multiple memory *types*,
since only episodic memory exists); "Tasks" (workflow status is visible —
but no pause/cancel/resume controls, and no "live progress" beyond the
durable transition log); "Today" (approvals and workflow activity are
visible in Overview — but with no goal-aligned recommendations, since goals
don't exist, and with the known "ghost pending" caveat below); "Audit Log"
(a structurally similar concept is realized narrowly for approval and
workflow history specifically — but the actual generic `AuditLogEntry`
table is a real, durable 4th source **not** surfaced in this phase, by
explicit scope decision, not oversight).

Chapter 21 concepts **entirely absent**: Knowledge Library, AI Providers
(status/cost/enable-disable), Goals, Settings (configuration, plugin
management, API keys) — none of these have any real, durable backing data
or subsystem in this repository today.

**One honest caveat surfaced during this review, worth carrying forward:**
`ApprovalManager._pending` is in-memory only, while
`ApprovalHistoryEntry.status` durably persists `"pending"` until a decision
or timeout updates it. If Jarvis restarts while an approval is genuinely
pending, that in-memory request is lost, but its durable history row will
show `"pending"` forever — a "ghost pending" row the dashboard would
honestly (and correctly, given what the table actually says) display, even
though it can never actually be decided anymore through the running CLI.
This is a pre-existing repository characteristic, not something this phase
introduces or should fix; it is disclosed here so the Overview panel's
"recent approval decisions" wording is written to describe *history*, not
to imply every "pending" row shown is currently actionable.

## 18. Batch Plan

### Batch 1 — Read-Model/Query Layer

- **Purpose**: a narrow, fully-tested composition layer over the three
  existing durable stores, with zero UI code.
- **Production files**: `dashboard/__init__.py` (new), `dashboard/read_model.py`
  (new); `workflow/workflow_history_store.py` (extended — one new method,
  `list_recent_workflow_ids`); `storage/database.py` (extended — WAL +
  busy_timeout connect-event pragmas).
- **Test files**: `tests/unit/test_dashboard_read_model.py` (new),
  `tests/unit/test_workflow_history_store.py` (extended, for the new
  method).
- **Invariants protected**: no store's write/record/update/delete method is
  ever called by `dashboard/read_model.py` (structurally verified); every
  returned row maps to a real persisted column (no invented field); ordering
  matches each store's own documented order; the new
  `list_recent_workflow_ids` method is read-only, adds no schema, and is
  usable independently of the dashboard.
- **Explicit non-goals**: no UI, no Tk import anywhere in this batch, no new
  security-tier logic, no change to any store's existing write-path
  behaviour.
- **Verification**: `poetry run pytest tests/unit/test_dashboard_read_model.py tests/unit/test_workflow_history_store.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files listed above.

### Batch 2 — UI/Rendering Layer

- **Purpose**: the `tkinter`/`ttk` application itself — navigation, the four
  views, refresh behaviour, empty/error/privacy/timestamp presentation.
- **Production files**: `dashboard.py` (new, repo-root entry point),
  `ui/dashboard_app.py` (new — mirrors `ui/cli.py`'s placement for the
  existing CLI).
- **Test files**: `tests/unit/test_dashboard_app.py` (new) — pure
  view-model/row-construction assertions wherever possible (no Tk
  instantiation needed), plus a smaller set of true-Tk tests using a
  `root.withdraw()`-ed instance to confirm wiring (tabs exist, no
  execute/approve/write callback is bound to any widget, refresh replaces
  displayed rows, error state renders without raising).
- **Invariants protected**: no widget is wired to any callback that
  constructs a `ToolRequest`, calls `ToolExecutor`, `ApprovalManager`,
  `WorkflowEngine`, or `AIReasoningEngine` (structurally verified — none of
  those names are ever imported in this batch's files); timestamps are
  always rendered with the literal `UTC` suffix, never `.astimezone()`;
  memory previews are truncated by default, full content shown only on
  selection.
- **Explicit non-goals**: no new store methods in this batch (Batch 1 is
  already complete and sufficient); no approve/deny/delete/edit/rerun/cancel
  control of any kind; no networking of any kind.
- **Verification**: `poetry run pytest tests/unit/test_dashboard_app.py -v`, then full `poetry run pytest -q`.
- **Commit boundary**: one commit, staging only the files listed above.

### Batch 3 — End-to-End Verification, Concurrency, Adversarial Tests, Documentation, Closure

- **Purpose**: real temporary file-backed SQLite database, real store
  implementations, real read-model, real (withdrawn) Tk app — proving the
  full pipeline; concurrency verification against the WAL/busy-timeout
  configuration; adversarial read-only-boundary proofs; documentation;
  closure.
- **Production files**: none expected.
- **Test files**: `tests/integration/test_dashboard_end_to_end.py` (new).
- **Documentation**: `README.md` (new Phase 19 section, launch command,
  safety note, non-goals), `docs/phase_19_implementation_plan.md` (tracked
  at closure, per established convention), `docs/phase_19_completion_report.md`
  (new).
- **Verification commands**: `poetry run pytest tests/integration/test_dashboard_end_to_end.py -v`, then full `poetry run pytest -q`, `git diff --check`, `git status`.
- **Commit boundary**: one closure commit, staging only the files this
  batch touches.

## 19. Testing Requirements (Consolidated Checklist)

**Read-model tests (Batch 1)**: structured memory/approval/workflow records
returned correctly; stable default ordering preserved; memory previews
deterministic and truncated at the fixed length; approval outcome/status
values passed through literally (never re-interpreted or normalized);
workflow latest status derived via `latest_status_for` semantics, never
re-implemented; workflow transitions remain ordered oldest-first for a
single workflow; empty database returns valid, empty (not `None`, not an
exception) view-model collections; an unrecognised/unexpected `status`
string is rendered literally, never causing a crash or a silent
substitution; a structural (AST-based, consistent with this repository's
established convention) test proves `dashboard/read_model.py` calls no
store method whose name implies a write (`save`, `update_*`, `delete`,
`forget`, `record_*`, `move_category`).

**UI/view-model tests (Batch 2)**: overview values map from real read-model
data; memory/approval/workflow rows show only real stored fields; empty
states render their honest, specific message; refresh replaces stale
displayed state with newly queried state; a simulated query failure renders
an inline error state without raising out of the UI layer; long memory
content is truncated in the list view and shown in full only in the detail
pane; command-like memory content is displayed as literal text; a
structural test proves no widget callback references `ToolExecutor`,
`ApprovalManager`, `WorkflowEngine`, `AIReasoningEngine`, or
`CommandRouter`.

**End-to-end tests (Batch 3)**: real stored memories, real approval history
rows, real workflow history transitions → `DashboardReadModel` →
`ui/dashboard_app.py`'s view construction → rendered `ttk.Treeview` state,
using a real temporary file-backed SQLite database and real store
instances. No real AI provider, no real web search, no `ToolExecutor`
invocation, and no `WorkflowEngine` execution anywhere in this test file —
history rows are inserted directly via the real stores' own write methods
to set up fixture state, exactly as `WorkflowHistoryStore`'s and
`ApprovalHistoryStore`'s own existing unit tests already do. The dashboard
reads updated durable state correctly after a simulated refresh tick
(calling the same refresh function `.after()` would call).

**Concurrency tests (Batch 3)**: two independent `sessionmaker`/engine pairs
opened against the same temporary file-backed database (simulating the CLI
process and the dashboard process); a write via one followed by a read via
the other succeeds and reflects the write; repeated open/read/close cycles
leave no leaked session or connection (verified via the engine's own pool,
or simply by repeating the cycle many times without error/resource
exhaustion). Where true simultaneous (not merely sequential) write-during-
read contention cannot be deterministically and portably forced in a test,
this is disclosed honestly rather than mocked: the test proves the
sequential-interleaved case deterministically, and the plan documents (as
established fact, not re-derived from a flaky test) that WAL mode's actual
non-blocking concurrent reader/writer behaviour is SQLite's own
externally-documented guarantee, not something this suite re-verifies from
first principles.

## 20. Adversarial Planning Review

- **Are we building a dashboard over data that isn't actually durable?** No
  — all three domains are backed by real SQLAlchemy tables already used in
  production; nothing ephemeral (live web search, live AI reasoning) is
  displayed.
- **Are we parsing CLI/tool output instead of structured stores?** No —
  Option C was explicitly rejected in §4; every field traces to a typed
  store method's return value.
- **Does the UI accidentally gain a write path?** No — no widget callback
  constructs a `ToolRequest` or calls any write-capable manager; proven
  structurally, not just by convention (§14, §19).
- **Can a memory containing command text cause execution?** No — it is
  inserted as a `Treeview` cell string; no parser or router ever sees it.
- **Can selecting a row trigger anything external?** No — selection only
  populates a local detail pane in the same process.
- **Are we adding HTTP/server infrastructure indirectly through the
  toolkit?** No — `tkinter` opens no socket of any kind.
- **Is "live" wording dishonest if refresh is polling?** No — the plan
  commits to "current as of last refresh" wording and a visible "Last
  refreshed" timestamp; "live"/"real-time" language is avoided throughout.
- **Will SQLite reads interfere with Jarvis writes?** Mitigated, not
  eliminated by magic: WAL mode plus a 2-second busy timeout make the
  common case non-blocking and the rare remaining case a short wait rather
  than an immediate failure; a residual failure still renders as an honest,
  isolated per-panel error (§13), never a crash.
- **Are sessions/connections leaked?** No — every read-model call uses the
  existing `session_scope` context manager, exactly like every other store
  caller in this repository; a dedicated repeated-cycle test proves this in
  Batch 3.
- **Are timestamps displayed misleadingly?** No — the naive-on-reload debt
  is disclosed and handled with an explicit, literal `UTC` suffix, never a
  false-precision timezone conversion (§12).
- **Are full memory contents exposed unnecessarily on launch?** No —
  previews are truncated by default; full content requires an explicit row
  selection (§11).
- **Are we inventing fake metrics to make the UI look impressive?** No —
  every Overview number traces to a real query (§6); no cost, health, agent,
  or plugin metric is fabricated.
- **Is the selected toolkit too heavy?** No — `tkinter` is the lightest
  possible choice, already present, zero new dependency (§9).
- **Is this actually better than a richer CLI?** Yes, specifically because
  it is glanceable and visual rather than another set of commands to
  remember and type — the entire premise the prior architectural review
  established (§20 of that review) for choosing this candidate at all.
- **Are we creating an empty inbox/table ahead of a producer?** No — §16
  explicitly rejects this (Option A chosen).
- **Does the dashboard make Jarvis feel more real while remaining genuinely
  useful?** Yes for the "feel more real" half by direct design intent; the
  "genuinely useful" half rests on it actually surfacing state Nathan
  currently has to reconstruct from scrollback — which this plan's exact
  three views (memory, approvals, workflow history) are chosen specifically
  to replace.
- **Did the phase accidentally become the full Master Specification
  dashboard?** No — §17 enumerates precisely what is realized, partially
  realized, and entirely absent; Settings, Goals, Knowledge Library, and AI
  Provider status are all explicitly out of scope and structurally absent.

No finding in this adversarial pass requires a design change.

## 21. Final Summary

- **Final UI technology choice**: `tkinter`/`ttk` (Python standard library,
  zero new dependency).
- **Exact dashboard launch command/entry point**: `poetry run python
  dashboard.py`.
- **Final process architecture**: a wholly separate local process, sharing
  only the SQLite file on disk with the Jarvis CLI process; no IPC, no
  shared Python objects, no control relationship in either direction.
- **Final read-model/query architecture**: a new `dashboard/read_model.py`
  module (`DashboardReadModel`) composing the three existing stores'
  existing public methods, plus one new, narrowly-justified
  `WorkflowHistoryStore.list_recent_workflow_ids` method.
- **Exact approved data domains**: memory state, approval history, workflow
  lifecycle/history — exactly the three approved, nothing more.
- **Exact overview metrics**: total memory count; 5 most recent approval
  decisions; 5 most recently active workflows with latest status.
- **Exact views/panels**: Overview, Memories (with category filter),
  Approval History, Workflow History (with per-workflow transition
  drill-down).
- **Refresh model and interval**: periodic requery via Tk's own `.after()`
  scheduler at a 5000 ms default interval, plus a manual "Refresh now"
  control; described honestly as "current as of last refresh," never
  "live"/"real-time."
- **Privacy/content-preview behaviour**: memory previews truncated to 120
  characters by default; full content shown only on explicit row selection.
- **Timestamp display behaviour**: `YYYY-MM-DD HH:MM:SS UTC`, the `UTC`
  suffix appended literally by dashboard code, never derived from (absent)
  `tzinfo`; no local-time conversion anywhere.
- **Exact permitted UI interactions**: switch tabs, select a row, scroll,
  sort already-loaded rows, filter already-loaded memory rows by category,
  refresh/requery.
- **Exact read-only authority guarantee**: no `ToolRequest` is ever
  constructed; `ToolExecutor`, the live `ApprovalManager`, `WorkflowEngine`,
  `AIReasoningEngine`, and `CommandRouter` are never imported by any file
  this phase adds — proven structurally, not merely asserted.
- **Exact failure-isolation behaviour**: any dashboard failure (database
  open, query, transient lock, malformed row, full crash) is contained to
  the dashboard's own process/panel and never affects the Jarvis CLI
  process, which does not import, launch, or depend on the dashboard in any
  way.
- **Inbox decision**: **A — no inbox in Phase 19.** No producer exists;
  building an empty schema now would be infrastructure ahead of a second
  real use case.
- **Final batch sequence**: (1) read-model/query layer; (2) UI/rendering
  layer; (3) end-to-end/concurrency/adversarial verification, documentation,
  closure.
- **Explicit Phase 19 non-goals**: HTTP server or listener of any kind;
  remote/LAN/phone reachability; authentication/sessions/accounts; any
  write, execute, approve, decline, cancel, resume, or schedule action from
  the dashboard; any change to `SecurityManager`, `ToolExecutor`,
  `ApprovalManager`, `WorkflowEngine`, `CommandRouter`, or any AI-facing
  module; any new tool; goals/projects/knowledge-library data; generic
  `AuditLog` surfacing; any durable inbox/notification schema; any fabricated
  metric.
- **Likely future pressure points**: the generic `AuditLog` table is a real,
  durable 4th data domain not included here, and is the most obvious
  candidate for a future dashboard extension; a durable inbox becomes
  genuinely justified the moment a real scheduler/producer exists, at which
  point this dashboard is the natural place to surface it; the "ghost
  pending" approval-history caveat (§17) may eventually warrant its own
  small, separately-reviewed fix if it proves confusing in practice; and the
  shared local-server-foundation question remains completely untouched and
  undecided by this phase, exactly as intended.
