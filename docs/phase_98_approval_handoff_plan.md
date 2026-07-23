# Phase 98 Safety Interlock Planning Gate — Durable Approved-to-Resume Handoff (Final Correction: OS-Enforced Exclusivity)

Status: **planning gate only**. No production or test code changed.
This correction replaces the database-row `ProcessInstanceLock` +
PID-liveness design (committed at `b59a3f6`) with a genuinely
OS-enforced file lock, and resolves a second, independently discovered
defect: placing lock acquisition inside `build_orchestrator()` would
have broken a real, established test pattern that calls it twice, in
one process, to simulate a restart.

## 1. Why PID plus token was rejected

A database-stored UUID token is only ever checked *from the database
side*, by a *new* process reading an *old* row - it is never presented
to, or verifiable against, the *actual, live* process holding a reused
PID. An unrelated process that later reuses the same PID has no
knowledge of, and makes no use of, the stored token; nothing forces
it to. PID-liveness alone answers "is *some* process running with this
number," never "is it *this* Jarvis instance." Neither the PID nor the
token is externally verifiable against the live process's own
identity, so their combination cannot prove ownership - only an
OS-held lock, which the kernel itself ties to a specific open file
handle for the lifetime of the holding process, can.

## 2. Repository inspection

- `pyproject.toml`: `requires-python = ">=3.14"`; dependencies are
  `anthropic`, `sqlalchemy`, `pydantic`, `python-dotenv`,
  `duckduckgo-search`, `httpx` - **no existing locking library**
  (`filelock`, `portalocker`, `fasteners`, etc.) is present. No new
  dependency is introduced (per the task's own constraint); the
  correction uses only the standard library.
- `config/settings.py`: `database_path: Path`, defaulting to the
  **relative** path `Path("data/jarvis.db")` - confirming relative-vs-
  absolute normalization is a genuine, live concern, not a theoretical
  one.
- `storage/database.py`'s own `_build_sqlite_url()` **already**
  canonicalizes via `database_path.expanduser().resolve()` for the
  database URL itself - the identical technique is reused for the lock
  identity, so the two can never disagree.
- `main.py`: `build_orchestrator()` is the composition root (loads
  settings, creates the engine, initializes the database, builds every
  manager, calls `reload_pending()`/`reload_paused()`); `main()` is a
  short wrapper calling `build_orchestrator()`, then constructing and
  running `JarvisCLI`. `main()` already has an established precedent
  (Phase 54, Batch 1) for keeping process-entry-point-only concerns
  *out* of `build_orchestrator()`, specifically so its many test
  callers are unaffected - `configure_console_logging()` is called only
  in `main()`, never inside `build_orchestrator()`, by explicit design.
- **Critical finding**: `build_orchestrator()` is called directly by
  over 100 existing tests (confirmed:
  `grep -rl build_orchestrator tests/` matches 15+ real test files).
  Several - most importantly
  `tests/integration/test_paused_workflow_restart_end_to_end.py` and
  `tests/integration/test_pending_approval_restart_end_to_end.py` -
  call `main.build_orchestrator()` **twice in one test function**,
  against the **same** temp database file, with a bare Python `del` of
  the first orchestrator in between, deliberately simulating "process
  one crashes; process two starts" **without any real process
  boundary**. A `del` does not deterministically close file handles or
  release an OS-level lock. Placing lock acquisition inside
  `build_orchestrator()` itself would make the *second* call in every
  such test fail to acquire the lock the *first* call never released,
  breaking this entire, real, already-established restart-simulation
  test pattern.
- `dashboard.py`/`scheduler.py`: confirmed unchanged from the prior
  audit (Section "Read-only components," below).
- Windows/POSIX: the target platform (this repository's own
  development environment) is Windows; the standard library provides
  `msvcrt.locking()` there and `fcntl.flock()` on POSIX - both already
  available with no new dependency, in every supported Python 3.14
  environment.

## 3. Exact OS-lock mechanism (selected: preferred option)

A new, narrow module (e.g. `runtime/process_lock.py`) providing one
small, platform-dispatching class/context-manager,
`ExecutionProcessLock`, wrapping a sidecar file opened and
OS-locked for the caller's lifetime - never a database row, never an
in-memory flag.

### POSIX

```python
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
```

`fcntl.flock()` raises `OSError`/`BlockingIOError` immediately
(non-blocking) if another process already holds the lock. The lock is
tied by the kernel to the open file description and is **automatically
released when the process exits, for any reason**, including `SIGKILL`
- no cleanup code required for the crash case.

### Windows

```python
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
os.write(fd, b"\0")  # msvcrt.locking() requires at least one byte
os.lseek(fd, 0, os.SEEK_SET)
msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
```

`msvcrt.locking()` with `LK_NBLCK` raises `OSError` immediately if
another process already holds the byte-range lock. Like POSIX
`flock()`, this lock is tied to the process/handle and is released by
the operating system when the process terminates, including abnormal
termination - no cleanup code required.

Both branches are dispatched by a single, small,
`sys.platform`-conditional import at the top of the new module (`fcntl`
does not exist on Windows; `msvcrt` does not exist on POSIX) - a
narrow, bounded, fully standard-library implementation, never a new
dependency, never a distributed lock platform.

### Rejected: an existing third-party library

None is present in this repository's dependencies (Section 2); adding
one is explicitly excluded by the task's own constraint. The standard-
library mechanism above is sufficient and narrower.

## 4. Canonical database identity

`Path(settings.database_path).expanduser().resolve()` - identical to
`storage/database.py`'s own existing canonicalization for the database
URL itself, so the lock and the database file it protects can never
disagree about identity. On Windows, additionally apply
`os.path.normcase()` (the standard-library, platform-aware
normalization function - a no-op on POSIX, lowercasing and
slash-normalizing on Windows) so that two configuration values
differing only in case or slash style resolve to the identical lock
identity, matching Windows' own case-insensitive-but-case-preserving
filesystem semantics. Symbolic links are resolved by `.resolve()`
itself (standard `pathlib` behavior). Multiple, genuinely distinct
database files each canonicalize to their own distinct path and
therefore their own distinct, independent lock file - no shared state
between them. An in-memory database
(`sqlite:///:memory:`, used throughout the test suite via direct
`create_engine()` calls that bypass `Settings`/`create_database_engine()`
entirely) never goes through this canonicalization at all, since the
lock is only ever acquired via the real, settings-driven startup path
(Section 6) - no special-casing is needed.

## 5. Lock-file location

`<canonical_database_path>.jarvis.lock` - a sidecar file in the exact
same directory as the database file itself (whose existence is already
guaranteed by `storage/database.py`'s own `_ensure_parent_directory()`,
requiring no new directory-creation logic). The file's own contents are
never authoritative and are not required to contain anything - an
empty file (or, optionally, a single byte written for the Windows
locking call, Section 3) is sufficient; **existence of this file proves
nothing** - only a live, OS-held lock on an open handle to it does.
File deletion is never how the lock is released (Section 7).

## 6. Exact acquisition ordering

A new, small wrapper function (e.g. `main.start_execution_session()`),
called only by `main()` - **never inside `build_orchestrator()`
itself**, preserving that function, and every one of its 100+ existing
test callers, completely unchanged (Section 2's critical finding):

1. Resolve the canonical database identity (Section 4).
2. Acquire the OS-enforced execution-process lock (Section 3). If
   acquisition fails, return a bounded, honest "Jarvis appears to
   already be running against this database" error - `build_orchestrator()`
   is never called, nothing is initialized, no approval/workflow state
   is touched, no tool executes.
3. Call the existing, unchanged `build_orchestrator()` - database
   initialization/migration, existing `reload_pending()`/`reload_paused()`
   (unchanged, still callable independently by every existing test with
   no lock involved).
4. Call a new, small function, e.g. `reconcile_claimed_handoffs(lock, ...)`,
   whose signature **structurally requires** the already-acquired lock
   object as a parameter - it is impossible to call without one, making
   "recovery cannot run before lock acquisition" a structural, not
   conventional, guarantee. This function performs, in order: approval/
   history consistency repair; inherited-`CLAIMED` reconciliation;
   missing interruption/terminal audit-event backfill (Sections
   inherited unchanged from the prior draft).
5. Rebuild the in-memory pending/approved-unconsumed views (unchanged).
6. Only then does `main()` construct `JarvisCLI` and call `cli.run()`,
   accepting approval or execution input.

This resolves the ordering requirement precisely while keeping
`build_orchestrator()` itself - and therefore the restart-simulation
tests identified in Section 2 - completely untouched: those tests
exercise `reload_pending()`/`reload_paused()`'s own existing,
already-proven restart-safety directly, never the new lock or the new
`CLAIMED`-reconciliation pass, which is correctly scoped to the one,
real production entry point only.

## 7. Lifetime and release

`ExecutionProcessLock` is a context manager; `main()` acquires it (via
`start_execution_session()`) and holds it, via a `try/finally` (or the
context manager's own `__exit__`), across the complete interactive CLI
lifetime - through every approval decision, claim, and
`WorkflowEngine` execution, released only when `main()` itself exits,
by any path (normal completion, a handled `KeyboardInterrupt`, or an
unhandled exception propagating out of `cli.run()`). Release simply
closes the file descriptor, which the operating system uses to drop
the lock - the sidecar file itself is never deleted as part of release
(Section 5).

## 8. Abnormal termination

No custom cleanup script or code path is required: both `fcntl.flock()`
and `msvcrt.locking()` locks are released by the operating system the
moment the holding process's file descriptors are closed, which the OS
itself guarantees on process termination for any reason, including
`SIGKILL`/a crash/a forced shutdown. A stale sidecar file left behind
by a crashed process contains no lock by the time a new process
inspects it - the new process's own non-blocking acquisition attempt
succeeds immediately, exactly as if the file had never existed.

## 9. Second-instance behavior

A second Jarvis CLI process attempting to start against the same
(canonicalized) database path fails at Section 6, step 2, before any
database initialization, recovery, or state mutation of any kind - it
receives a bounded, honest "already running" message and exits.

## 10. Dashboard and scheduler boundaries

- **Dashboard**: confirmed, unchanged from the prior audit, to be
  100% read-only - it never calls `start_execution_session()` or the
  new lock module at all, and is structurally incapable of mutating
  approval, workflow, or handoff state (no write-method call site
  exists anywhere in `dashboard.py`/`ui/dashboard_app.py`/
  `dashboard/read_model.py`). Because the new lock is a **separate
  file** from the SQLite database itself, the dashboard's own read
  access to the database is entirely unaffected by, and independent
  of, this lock - the two files are never in contention.
- **Scheduler**: `scheduler.py` writes only to `ScheduleStore`/
  `InboxStore` - it never touches `pending_approval_state`,
  `paused_workflow_state`, or any code this interlock protects, so it
  introduces no risk to the handoff state machine specifically.
  However, per the task's own instruction, it is **not** exempted
  merely on that basis: `scheduler.py` is a genuinely separate,
  execution-capable process (it does perform real, scheduled actions).
  This correction does **not** make it acquire the same lock - doing so
  would prevent scheduled actions from ever running while the
  interactive CLI is open, defeating `scheduler.py`'s own purpose.
  Instead, this is stated **honestly as an explicit, acknowledged,
  out-of-scope limitation**: `scheduler.py` running concurrently with
  the interactive CLI remains unsupported *with respect to any future,
  broader single-writer guarantee*, though it introduces zero new risk
  to *this specific* approval-handoff correction. Designing
  `scheduler.py`'s own participation in a shared exclusivity model is
  explicitly deferred to a future, separately-scoped phase - never
  silently assumed safe.

## 11. `ProcessInstanceLock` table decision

**Removed from the plan entirely.** The OS-level lock is fully
authoritative and self-sufficient (Sections 3, 8); a parallel database
row would be redundant, would risk the two authorities disagreeing, and
serves no concrete, currently-justified diagnostic need. This also
simplifies Batch 1's own schema scope: the only remaining schema change
across the whole handoff correction is the previously-planned
`pending_approval_state.handoff_status` column.

## 12. Workflow-history relationship (reaffirmed, responsibilities separated)

Unchanged from the prior draft's own twelve-point audit
(`WorkflowHistoryStore.latest_status_for()` remains the positive-only
reconciliation signal), with the two responsibilities now explicitly,
permanently separated: **the OS lock proves startup exclusivity** (no
other execution-capable process is live for this database, so any
inherited `CLAIMED` row is genuinely orphaned, never actively owned);
**workflow history only ever distinguishes a known terminal outcome
from an uncertain one**, for a row already known, via the lock, to be
orphaned. Neither responsibility substitutes for the other; they are
never combined into one claim.

## 13. `CLAIM_INTERRUPTED` relationship (unchanged)

Unchanged from the prior draft: `record_interruption()` on
`ApprovalHistoryStore`, one bounded, idempotent, `request_id`-keyed
event, fixed trusted reason text, no unrestricted output, old approval
non-reusable, paused workflow retained, no automatic retry. No further
visibility redesign is required by this correction.

## 14. Test isolation and subprocess tests

Tests using distinct temporary database files (the overwhelming
majority of this repository's existing tests, via `tmp_path`/`:memory:`)
are unaffected and remain fully independent - each canonicalizes to its
own lock file. `build_orchestrator()`'s own existing test callers
(Section 2) are unaffected, since neither the lock nor the new
reconciliation pass lives inside it. New tests targeting the lock
mechanism itself must use **real subprocesses** (`subprocess.Popen`
running a small, dedicated helper script), not a mocked lock API -
this is a hard requirement, since only a real OS call can prove real
OS-enforced exclusivity.

## 15. Final batch structure

- **Batch 1 - OS execution lock and CAS primitives**: `runtime/process_lock.py`
  (cross-platform `ExecutionProcessLock`, canonical-path helper);
  `pending_approval_state.handoff_status` column + migration;
  `PendingApprovalHandoffStatus` enum; `PendingApprovalStore` CAS
  transition/claim methods. No `ApprovalManager`/orchestrator change
  yet; no `main.py` wiring yet - the lock module and CAS primitives are
  each fully, independently unit- and subprocess-tested in isolation.
- **Batch 2 - Approval lifecycle, history consistency, and startup
  recovery**: `approve()`'s new transition; `claim_for_resume()`;
  `reconcile_claimed_handoffs()`; `record_interruption()` +
  `KNOWN_APPROVAL_STATUSES` update; `WorkflowEngine._try_reconstruct_paused_workflow()`'s
  three-way retention refinement; confirmation (or a small fix) that
  `ApprovalHistoryTool`'s display path shows `"interrupted"` truthfully.
  Complete regression for every existing YELLOW capability.
- **Batch 3 - `main.py`/orchestrator integration and closure**:
  `main.start_execution_session()` wiring `main()`'s own call to
  `build_orchestrator()` plus the lock and reconciliation pass;
  `execute_approved()` calling `claim_for_resume()` first; full
  end-to-end crash-window and second-instance subprocess tests; full
  three-environment regression; closure.

The OS lock does not require its own, separately-scoped foundation
phase - it is narrow enough to be Batch 1's own first deliverable,
alongside the already-planned schema/CAS primitives.

## 16. Updated required tests

All 14 subprocess-test items the task requires, plus the previously
specified 49 items (largely unchanged in substance, now referencing
the OS lock instead of PID/token), map onto the three batches: lock
mechanism and canonical-identity tests (Batch 1, using real
subprocesses per Section 14); approval lifecycle, history-consistency,
and startup-recovery tests (Batch 2); full `main.py` integration,
existing-YELLOW-workflow, and full-suite/Ruff verification (Batch 3).
No PID-reuse simulation is required anywhere, since PID is never
authoritative.

## 17. Updated acceptance criteria

All required tests pass, including real-subprocess proof that: a
second process against the same database is rejected; a process against
a different database succeeds independently; clean shutdown and abrupt
termination both permit a later acquisition; a stale lock file with no
held OS lock never blocks acquisition; equivalent relative/absolute/
case-varied paths collide correctly. `build_orchestrator()`'s own 100+
existing test callers, including both restart-simulation tests
identified in Section 2, pass completely unmodified. Fresh and migrated
databases behave identically. Ruff and `git diff --check` clean.

## 18. Updated risks and mitigations

- **Risk**: Windows `msvcrt.locking()` has subtle, under-documented
  edge cases. **Mitigation**: dedicated, real-subprocess tests specific
  to this platform, proven before Batch 1 closes - never assumed
  correct from documentation alone.
- **Risk**: a future contributor re-adds lock acquisition inside
  `build_orchestrator()`, reintroducing the restart-test regression
  found in Section 2. **Mitigation**: this plan documents the reason
  explicitly, and Batch 3's own test suite includes the two
  restart-simulation tests as an explicit, permanent regression guard.
- **Risk**: `scheduler.py`'s own exemption is later mistaken for "safe
  in all respects." **Mitigation**: Section 10 states the boundary
  honestly, as a named, acknowledged, deferred gap - never as a closed
  question.

## 19. Updated stop conditions

Stop before implementation if: ownership still depends on PID liveness
or an unverifiable stored token; locking is implemented as file
existence rather than a real, held OS lock; Windows locking cannot be
implemented and proven with real subprocess tests; equivalent database
paths (relative/absolute/case-varied) can acquire separate locks; a
second execution-capable process can run the `CLAIMED`-reconciliation
pass while another is live; abnormal process death does not
automatically release ownership; the lock is acquired inside
`build_orchestrator()` in a way that breaks its existing test callers;
dashboard read-only behavior would be blocked; two independent
ownership authorities (e.g. a reintroduced database row alongside the
OS lock) could disagree; startup recovery can run before lock
acquisition; or any test relies only on a mocked lock API rather than a
real subprocess.

## 20. Formal correction conclusion

The process-exclusivity mechanism is corrected from an unverifiable
database convention to a genuinely OS-enforced file lock, using only
the standard library, with no new dependency. A second, independently
discovered defect - that acquiring the lock inside `build_orchestrator()`
would have broken an established, real restart-simulation test
pattern used by over 100 existing tests - is resolved by acquiring the
lock only in `main()`'s own new, narrow wrapper, leaving
`build_orchestrator()` itself, and every test that calls it, completely
unaffected. The `ProcessInstanceLock` database table is removed as
redundant. The handoff correction remains a three-batch, large/risky
future phase - not implemented in this planning gate.

## 21. Interlock Batch 1 — Implementation Evidence

Batch 1 (the OS execution lock, the additive handoff-status schema, and
store-level CAS primitives - Sections 3-15 above) is implemented,
adding zero live wiring: no startup lock acquisition, no
`ApprovalManager`/orchestrator lifecycle change, no startup recovery,
and no `CLAIMED` reconciliation.

### 21.1 Scheduler-boundary audit — re-confirmed by direct re-inspection

`scheduler.py` was re-read in full for this batch. It remains a wholly
separate, execution-capable process (`run_one_poll_cycle()` really does
call `run_scheduled_web_search_summary()`, which mutates
`ScheduleStore` via `claim_due()`'s own atomic claim and writes a real
`InboxEntry` on success) that shares only the SQLite file with the CLI
process - no IPC, no shared Python objects, no import of `main.py`/
`JarvisOrchestrator`/`ApprovalManager`/`WorkflowEngine` at all
(confirmed directly: `scheduler.py`'s own imports touch only
`ScheduleStore`/`InboxStore`/`AIRouter`/`DuckDuckGoSearchProvider`).
Critically, it never touches `pending_approval_state`,
`paused_workflow_state`, `approval_history`, or `workflow_history` -
the four tables this interlock protects - so it introduces no risk to
*this specific* correction. Per the task's own instruction, this is
**not** treated as a closed question merely because it avoids
`ApprovalManager`: `scheduler.py` running concurrently with a
lock-holding interactive CLI remains an explicit, acknowledged,
deferred gap with respect to any *future*, broader single-writer
guarantee - recorded here again, unchanged from Section 10, as the
result of a fresh, direct re-audit rather than an assumption carried
forward.

`dashboard.py` was re-confirmed structurally read-only for this batch
via `grep -rln "write\|update\|save\|delete\|approve\|resume\|execute" dashboard.py`,
which returns only the filename match itself (the search pattern
matching its own docstring prose), no call site - unchanged from the
prior audit.

### 21.2 OS execution lock — exact implementation

- New module `runtime/process_lock.py` (package `runtime/__init__.py`
  added alongside it): `ExecutionProcessLock` (a context manager),
  `ExecutionLockError`, `InMemoryDatabaseLockError`,
  `canonical_database_path()`, `lock_path_for()`. Zero third-party or
  cross-project dependency - only `os`, `sys`, `pathlib`, and the
  platform-conditional `fcntl` (POSIX) / `msvcrt` (Windows).
- **Canonical identity**: `canonical_database_path()` performs
  `database_path.expanduser().resolve()`, identical to
  `storage/database.py`'s own `_build_sqlite_url()`, plus
  `os.path.normcase()` on Windows (a no-op on POSIX) - proven, by direct
  test, to make a relative and an absolute reference to the same file
  resolve identically, and (Windows-only, platform-guarded) a
  case-varied reference too.
- **Sidecar location**: `lock_path_for()` derives
  `<canonical_database_path>.jarvis.lock`, in the same directory as the
  database file. Raises `InMemoryDatabaseLockError` for the literal
  `":memory:"` database path - locking is honestly unsupported for a
  non-durable, non-shared in-memory database, never silently mapped to
  one global lock.
- **POSIX**: `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)` on an
  `os.open()`'d sidecar file descriptor.
- **Windows**: writes one control byte, seeks to offset 0, then
  `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)`; release seeks to the same
  offset and calls `msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)` - the exact
  same one-byte range for both lock and unlock, as required.
- **API**: `acquire()`/`release()`/`__enter__`/`__exit__`/
  `is_acquired`. Double acquisition by the same object raises
  `ExecutionLockError`; repeated `release()` is a safe no-op (mirroring
  `PendingApprovalStore.delete()`'s own established "no-op if already
  gone" convention); `__exit__` always releases, including when the
  `with` block raised. No heartbeats, PID checks, UUID rows, leases, or
  retry loops exist anywhere in this module.
- **Real subprocess evidence** (this repository's own development and
  target platform is Windows; `tests/integration/
  test_process_lock_subprocess.py` spawns
  `_process_lock_subprocess_helper.py` as a genuine, independent
  `subprocess.Popen` - never a mock): a second process against the
  same database is rejected while the first holds it; a process
  against a different database succeeds concurrently; a cleanly-released
  lock permits immediate later acquisition; **abrupt termination**
  (`proc.kill()`, simulating a crash) permits later acquisition,
  proving the OS - not this module's own code - is what releases the
  lock; equivalent relative/absolute paths (resolved against the same
  working directory a real Jarvis process would use) collide onto one
  sidecar. All 6 subprocess tests pass, using real `msvcrt` kernel
  locking, not a mock.
- **Stale-sidecar and no-leaked-descriptor evidence** (unit-level,
  `tests/unit/test_process_lock.py`): a pre-existing, empty sidecar
  file with no held lock never blocks acquisition; after `release()`, a
  second, independent `ExecutionProcessLock` instance (a distinct open
  file description, even within the same process) can acquire
  immediately - proof no descriptor or lock is left behind, since a
  genuinely leaked lock would have blocked this second instance too.
- **No database/handoff mutation on acquisition failure**: proven
  structurally, via AST-based real-identifier detection (not raw text
  search, since this module's own docstrings legitimately name
  `ApprovalManager`/`session_scope` when explaining what it does not
  do) - the module's source contains no reference to
  `session_scope`/`ApprovalManager`/`PendingApprovalStore`/
  `create_database_engine`/`initialize_database` at all.

### 21.3 Handoff-status schema — exact implementation

- New `PendingApprovalHandoffStatus` enum (`approval/approval_models.py`,
  alongside the pre-existing, untouched `ApprovalStatus`): `PENDING`,
  `APPROVED_UNCONSUMED`, `CLAIMED`, `CONSUMED`, `CLAIM_INTERRUPTED`,
  `DECLINED`, `EXPIRED` - a wholly separate concept from
  `ApprovalStatus`, which keeps its exact original four values
  (`pending`/`approved`/`declined`/`expired`), proven unchanged by a
  dedicated regression test.
- One additive column, `PendingApprovalState.handoff_status`
  (`storage/models.py`): `String(24)`, `nullable=False`,
  `default="pending"`, `server_default="pending"` - the only schema
  change in this batch; no `ProcessInstanceLock` table and no generic
  job/queue table were added.
- New guarded migration `_ensure_pending_approval_handoff_status_column()`
  (`storage/database.py`), called from `initialize_database()`
  immediately after the pre-existing `_ensure_memory_category_column()`
  - identical shape: inspect for the column, no-op if present, a single
  `ALTER TABLE ... ADD COLUMN ... DEFAULT 'pending'` if not.
- **Proof** (`tests/unit/test_pending_approval_handoff_schema.py`,
  against a hand-built pre-Batch-1 table, not a fixture that already
  has the column): a fresh database contains the column via
  `create_all()` alone; migration adds it to a pre-existing database;
  existing rows default to `"pending"` with every other column (action/
  reason/security_tier/schema_version) untouched; migration is
  idempotent (run three times); fresh and migrated schemas expose an
  identical column set and identical runtime behavior; pre-existing
  `pending_approval_state`/`paused_workflow_state`/`approval_history`
  rows all remain independently readable after migration; no
  `process_instance_lock` table exists.

### 21.4 Store-level CAS primitives — exact implementation

- `PendingApprovalStore` (`approval/pending_approval_store.py`) gains
  exactly six named transition methods -
  `mark_approved_unconsumed()`, `claim_for_resume()`,
  `mark_consumed()`, `mark_claim_interrupted()`, `mark_declined()`,
  `mark_expired()` - plus `get_handoff_status()` and
  `list_by_handoff_status()`. Every transition routes through one
  shared `_compare_and_set()` helper issuing a single, atomic SQL
  `UPDATE ... WHERE request_id = ? AND handoff_status = <expected>`
  and checking `result.rowcount == 1` - never a read-then-write pair,
  never an in-memory lock, never a blind update.
- **Allowed transitions** (exactly the plan's own matrix, and no
  others - there is no generic `transition(from, to)` API, so an
  unlisted combination is structurally unreachable, not merely
  runtime-rejected): `PENDING -> APPROVED_UNCONSUMED`,
  `PENDING -> DECLINED`, `PENDING -> EXPIRED`,
  `APPROVED_UNCONSUMED -> CLAIMED`, `CLAIMED -> CONSUMED`,
  `CLAIMED -> CLAIM_INTERRUPTED`.
- **Rejected transitions, proven directly**
  (`tests/unit/test_pending_approval_store_cas.py`):
  `APPROVED_UNCONSUMED -> PENDING`, `CLAIMED -> APPROVED_UNCONSUMED`,
  `CLAIM_INTERRUPTED -> CLAIMED`, `CONSUMED -> CLAIMED`,
  `DECLINED -> APPROVED_UNCONSUMED`, `EXPIRED -> APPROVED_UNCONSUMED`,
  and a same-state repeated call (e.g. a second `claim_for_resume()`)
  all correctly return `False` with the row's own `handoff_status`
  unchanged.
- **Concurrency/second-claim evidence**: a second `claim_for_resume()`
  call for the same `request_id` after a first, successful claim
  returns `False` (`test_concurrent_or_repeated_second_claim_fails`);
  a dedicated test manually advances a row's state between a caller's
  `save()`/read and its CAS call, proving the CAS only ever inspects
  the database's *current* state at the moment of its own atomic
  `UPDATE`, never a value read earlier.
- **Immutability**: `request_id`, `action`, `reason`, `security_tier`,
  `tool_name`, `tool_input`, `schema_version`, and any workflow-linking
  metadata (e.g. `workflow_id` inside `metadata_json`) are proven
  unchanged across a full `PENDING -> APPROVED_UNCONSUMED -> CLAIMED ->
  CONSUMED` transition sequence.
- **No arbitrary state string accepted**:
  `PendingApprovalHandoffStatus("not_a_real_state")` raises
  `ValueError`, proven directly; the enum's own member set is proven
  to be exactly the seven approved values, no more.
- Existing store behavior: `save()`/`delete()`/`get()`/`list_all()`
  remain present with their original signatures and behavior; `save()`
  now explicitly writes `handoff_status="pending"` for every new row
  (the one narrow, compatible adaptation the new column requires),
  mirroring how `save()` already explicitly writes `schema_version=
  SCHEMA_VERSION` rather than relying on the ORM column default alone.

### 21.5 Isolation evidence — zero live wiring

`tests/unit/test_interlock_batch1_isolation.py` proves, via AST-based
identifier detection and a full repository sweep (excluding `tests/`):
no reference to any new identifier (`ExecutionProcessLock`,
`PendingApprovalHandoffStatus`, any of the six CAS methods, etc.)
exists anywhere in production code outside the six files this batch
itself adds or modifies (`runtime/__init__.py`, `runtime/process_lock.py`,
`approval/approval_models.py`, `approval/pending_approval_store.py`,
`storage/models.py`, `storage/database.py`); `main.py`/`ui/cli.py`
import nothing from `runtime.process_lock`; `approval/approval_manager.py`/
`core/orchestrator.py`/`workflow/engine.py` reference none of the new
identifiers; `start_execution_session`/`reconcile_claimed_handoffs` (the
Batch 2/3 deliverables) are not yet defined as callables anywhere in the
repository; the Phase 97/98 compound-isolation boundary
(`intelligence/compound_grounding.py`, `compound_structured_output.py`,
`intelligence/planning.py`, `planner/plan_models.py`,
`workflow/compound_workflow_progress_store.py`) is untouched by this
batch.

### 21.6 Focused and regression evidence

- New tests: 18 (`test_process_lock.py`) + 6
  (`test_process_lock_subprocess.py`, real subprocesses) + 9
  (`test_pending_approval_handoff_schema.py`) + 25
  (`test_pending_approval_store_cas.py`) + 14
  (`test_interlock_batch1_isolation.py`) = **72 passed**.
- Targeted regression re-run (existing approval manager/models/store,
  workflow commands, verification gate, compound-workflow-progress
  store, Phase 98 Batch 1 isolation, plan models, storage models,
  database, restart end-to-end, Phase 27 adversarial/invalid-state/
  no-restart, approval/approval-history end-to-end, dashboard end-to-end,
  schedule enable/disable orchestrator workflows, project-state
  update-phase orchestrator workflow, trusted-workflow foundation,
  capability catalogue, grounding, planning, structured output,
  Phase 97 compound isolation/grounding/structured-output): **867
  passed**, all unmodified except the new files themselves.
- Full suite: **5432 passed, 3 skipped, 0 failed**, identical in all
  three required environments - exactly 72 more than the Phase 98
  Batch 1 baseline of 5360.
- Ruff: clean (0 findings) across every one of the 8 Python files this
  batch touches (2 new production files, 2 modified production files,
  1 modified production file with a guarded-migration addition, and 5
  new test files - see the implementation commit's own Ruff evidence
  for the exact file list and command).
- `git diff --check`: clean.

Interlock Batch 1 is closed. Batch 2 (`ApprovalManager` lifecycle,
history consistency, claim API, startup recovery) and Batch 3
(`main.py`/orchestrator integration, full YELLOW-workflow regression,
closure) were not started. Phase 98 live compound Batch 2/3 remain
blocked pending the full interlock's acceptance.
