"""
process_lock.py

OS-enforced execution-process exclusivity lock (Approval-to-Resume
Handoff Interlock, Batch 1 - docs/phase_98_approval_handoff_plan.md,
Section 3).

Responsibilities:
    - Derive one canonical, cross-process-stable identity for the
      configured SQLite database file (mirroring
      storage/database.py's own _build_sqlite_url() canonicalization,
      so the lock and the database it protects can never disagree
      about identity).
    - Derive the sidecar lock-file path from that canonical identity.
    - Acquire and release a real, OS-held, non-blocking exclusive lock
      on that sidecar file - fcntl.flock() on POSIX,
      msvcrt.locking() on Windows - never a database row, never an
      in-memory flag, never PID/token comparison.

Does NOT:
    - Wire this lock around cli.run(), build_orchestrator(), or any
      other live startup path. That integration is explicitly deferred
      to a later, separately-accepted interlock batch (Section 6 of
      the plan) - this module is a narrow, self-contained primitive
      only, exercised directly by its own tests in this batch.
    - Perform any approval, workflow, or handoff-state mutation of any
      kind. Acquisition failure here never touches the database.
    - Use PID liveness, a stored ownership token, or the sidecar
      file's mere existence as proof of ownership - only a live,
      kernel-held lock on an open file descriptor proves exclusivity;
      see the plan's Section 1 for why the previously-considered
      PID+token design was rejected.
    - Implement heartbeats, retries, distributed leases, or background
      workers of any kind. Acquisition is a single, immediate,
      non-blocking attempt that either succeeds or raises.

A stale sidecar file left behind by a crashed process contains no lock
by the time a new process inspects it: both fcntl.flock() and
msvcrt.locking() are released by the operating system the instant the
holding process's file descriptors close, for any reason, including
SIGKILL - so a new process's own non-blocking acquisition attempt
succeeds immediately, exactly as if the file had never existed. File
deletion is never how this lock is released.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

#: Suffix appended to the canonical database path to derive the sidecar
#: lock-file path: "<canonical_database_path>.jarvis.lock".
_LOCK_SUFFIX = ".jarvis.lock"

#: The literal SQLite in-memory database identifier. An in-memory
#: database has no file, is never durable across a restart, and never
#: represents the same shared database between two independent
#: processes - so it is never a valid target for this lock.
_IN_MEMORY_DATABASE = ":memory:"

#: Extra open flags applied only on Windows, to avoid the C runtime's
#: default text-mode newline translation from touching the single
#: control byte this module writes (Section 3 of the plan). A no-op
#: concept on POSIX, where os.O_BINARY does not exist.
_EXTRA_OPEN_FLAGS = getattr(os, "O_BINARY", 0)


class ExecutionLockError(Exception):
    """Raised when the execution-process lock cannot be acquired, or is
    used incorrectly (double acquisition by the same object).

    This is the single, bounded, honest error this module ever raises
    for a failed acquisition - it never distinguishes "some other
    Jarvis process holds it" from any other OS-level reason the lock
    call failed, since the kernel itself provides no more specific
    answer than "this cannot be acquired right now."
    """


class InMemoryDatabaseLockError(ExecutionLockError):
    """Raised when locking is requested for a non-durable ':memory:'
    database.

    An in-memory SQLite database is not durable across a restart and
    does not represent a real, shared database between two independent
    processes (each process that opens ':memory:' gets its own,
    private, empty database) - so execution-process locking is not a
    meaningful concept for it. This is deliberately a distinct,
    honestly-named error rather than silently mapping every in-memory
    database to one shared global lock.
    """


def canonical_database_path(database_path: Path) -> Path:
    """Derive the canonical, cross-process-stable identity of a
    configured SQLite database file.

    Mirrors storage/database.py's own _build_sqlite_url()
    canonicalization exactly (expanduser().resolve()), so the lock
    this module protects and the database file itself can never
    disagree about identity. On Windows, additionally applies
    os.path.normcase() (a no-op on POSIX) so that two configuration
    values differing only in case or slash style resolve to the
    identical canonical path, matching Windows' own
    case-insensitive-but-case-preserving filesystem semantics.

    Args:
        database_path: The configured SQLite database file path
            (settings.database_path), relative or absolute.

    Returns:
        The canonical, resolved (and, on Windows, case-normalized)
        Path.
    """
    resolved = database_path.expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.path.normcase(str(resolved)))
    return resolved


def lock_path_for(database_path: Path) -> Path:
    """Derive the sidecar lock-file path for a configured database path.

    Args:
        database_path: The configured SQLite database file path.

    Returns:
        The sidecar lock-file path, in the same directory as the
        canonical database path, named
        "<canonical_database_path>.jarvis.lock".

    Raises:
        InMemoryDatabaseLockError: If database_path is ':memory:'.
    """
    if str(database_path) == _IN_MEMORY_DATABASE:
        raise InMemoryDatabaseLockError(
            "An in-memory SQLite database (':memory:') is not durable "
            "across a restart and does not represent a real, shared "
            "database between processes - execution-process locking is "
            "not supported for it."
        )
    canonical = canonical_database_path(database_path)
    return canonical.with_name(canonical.name + _LOCK_SUFFIX)


def _platform_lock(fd: int) -> None:
    """Acquire a real, kernel-held, non-blocking exclusive lock on `fd`.

    Raises:
        OSError: If another process already holds the lock (or the
            byte-range lock, on Windows).
    """
    if sys.platform == "win32":
        os.write(fd, b"\0")  # msvcrt.locking() requires at least one byte.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _platform_unlock(fd: int) -> None:
    """Release the lock previously acquired on `fd` by _platform_lock().

    Uses the exact same byte range (offset 0, length 1) on Windows that
    _platform_lock() locked, since msvcrt.locking()'s unlock call must
    match the original lock's own range exactly.
    """
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


class ExecutionProcessLock:
    """A cross-platform, OS-enforced execution-process exclusivity lock,
    keyed to one canonical SQLite database path.

    Ownership is proven only by a live, kernel-held lock on an open
    file descriptor - never by the sidecar file's mere existence, a PID,
    or a stored token. The operating system itself releases the lock
    the instant every file descriptor referencing it closes, including
    on abnormal process termination (SIGKILL, a crash) - no cleanup
    code is required for that case.

    Not thread-safe for concurrent acquire()/release() calls on the
    same instance from multiple threads - this project's own processes
    are single-threaded with respect to lock acquisition (acquired once,
    at startup, by one process's main thread).

    Attributes:
        database_path: The configured database path this lock protects
            (as given at construction - not yet canonicalized).
        lock_path: The canonical sidecar lock-file path this instance
            locks.
    """

    def __init__(self, database_path: Path) -> None:
        """Initialise the lock for one configured database path.

        Does not acquire anything - construction alone has no side
        effect on the filesystem or any process-wide state. Call
        acquire() (or use this object as a context manager) to attempt
        acquisition.

        Args:
            database_path: The configured SQLite database file path
                (settings.database_path).

        Raises:
            InMemoryDatabaseLockError: If database_path is ':memory:'.
        """
        self.database_path = database_path
        self.lock_path = lock_path_for(database_path)
        self._fd: int | None = None

    @property
    def is_acquired(self) -> bool:
        """Whether this object currently holds the lock.

        Returns:
            True if acquire() has succeeded and release() has not yet
            been called; False otherwise. For test/inspection use only
            - never consulted by acquire()/release() themselves, which
            rely solely on the real OS lock state.
        """
        return self._fd is not None

    def acquire(self) -> None:
        """Acquire the OS-enforced exclusive lock, immediately and
        non-blockingly.

        Opens (creating if necessary) the sidecar lock file and
        attempts a real, kernel-held, non-blocking exclusive lock on
        it. The file descriptor remains open for as long as the lock
        is held - closing it (via release()) is what drops the lock.

        Raises:
            ExecutionLockError: If this object already holds the lock
                (double acquisition), or if the OS lock could not be
                acquired (another process already holds it, or another
                OS-level failure occurred). Acquisition failure never
                creates, initializes, or mutates any database or
                handoff state - nothing beyond opening the sidecar file
                itself has happened by the time this raises.
        """
        if self._fd is not None:
            raise ExecutionLockError(
                "This ExecutionProcessLock instance already holds the "
                f"lock for {self.lock_path}."
            )

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            str(self.lock_path),
            os.O_CREAT | os.O_RDWR | _EXTRA_OPEN_FLAGS,
        )
        try:
            _platform_lock(fd)
        except OSError as exc:
            os.close(fd)
            raise ExecutionLockError(
                "Jarvis appears to already be running against this "
                f"database ({self.database_path})."
            ) from exc

        self._fd = fd

    def release(self) -> None:
        """Release the lock, if currently held.

        A no-op if this object does not currently hold the lock - a
        caller never needs to check is_acquired first, mirroring this
        codebase's own established "repeated release is safe" store
        convention (e.g. PendingApprovalStore.delete()). Never deletes
        the sidecar file - only closing the file descriptor is what
        drops the OS lock.
        """
        if self._fd is None:
            return
        fd = self._fd
        self._fd = None
        try:
            _platform_unlock(fd)
        finally:
            os.close(fd)

    def __enter__(self) -> ExecutionProcessLock:
        """Acquire the lock and return this object.

        Returns:
            This ExecutionProcessLock, now holding the lock.
        """
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the lock unconditionally, including when the `with`
        block raised.

        Returns:
            None (never suppresses an exception raised in the block).
        """
        self.release()
