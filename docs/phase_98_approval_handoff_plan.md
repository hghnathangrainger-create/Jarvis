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
