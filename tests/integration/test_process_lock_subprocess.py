"""
test_process_lock_subprocess.py

Real-subprocess proof that runtime.process_lock.ExecutionProcessLock
enforces genuine, OS-level, cross-process exclusivity (Approval-to-
Resume Handoff Interlock, Batch 1 -
docs/phase_98_approval_handoff_plan.md, Section 14: "New tests
targeting the lock mechanism itself must use real subprocesses ...
not a mocked lock API - this is a hard requirement, since only a real
OS call can prove real OS-enforced exclusivity.").

Each test spawns _process_lock_subprocess_helper.py as a genuine,
independent Python process (subprocess.Popen), never imports it, and
never mocks fcntl/msvcrt.

Run with:
    pytest tests/integration/test_process_lock_subprocess.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from runtime.process_lock import ExecutionProcessLock

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER = Path(__file__).resolve().parent / "_process_lock_subprocess_helper.py"

_STARTUP_TIMEOUT_SECONDS = 5.0
_POLL_INTERVAL_SECONDS = 0.05


def _spawn(database_path: Path | str, hold_seconds: float) -> subprocess.Popen[str]:
    """Launch the helper as a real, independent subprocess.

    cwd is fixed to the repository root so a relative database_path
    argument resolves identically to how canonical_database_path()
    would resolve it for a real Jarvis process started from the repo
    root.
    """
    return subprocess.Popen(
        [sys.executable, str(_HELPER), str(database_path), str(hold_seconds)],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_line(
    proc: subprocess.Popen[str], expected: str, *, timeout: float = _STARTUP_TIMEOUT_SECONDS
) -> None:
    """Block until `expected` is read from the subprocess's stdout."""
    deadline = time.monotonic() + timeout
    last_line = ""
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(_POLL_INTERVAL_SECONDS)
            continue
        last_line = line.strip()
        if last_line == expected:
            return
    raise AssertionError(
        f"Timed out waiting for subprocess to print {expected!r}; "
        f"last line seen: {last_line!r}"
    )


# 1. Process A acquires the lock for database A.
def test_process_a_acquires_lock_for_database_a(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    proc = _spawn(db, hold_seconds=0.5)
    try:
        _wait_for_line(proc, "ACQUIRED")
    finally:
        assert proc.wait(timeout=10) == 0


# 2. Process B using the same database A is rejected.
# 10. Lock remains held while the owner process is alive.
def test_process_b_same_database_is_rejected_while_a_holds_it(tmp_path: Path) -> None:
    db = tmp_path / "shared.db"
    proc_a = _spawn(db, hold_seconds=2.0)
    try:
        _wait_for_line(proc_a, "ACQUIRED")

        proc_b = _spawn(db, hold_seconds=0.1)
        proc_b.communicate(timeout=10)
        assert proc_b.returncode == 1
    finally:
        assert proc_a.wait(timeout=10) == 0


# 3. A process using database B succeeds concurrently.
# 12. Distinct temporary test databases do not interfere.
def test_process_using_a_different_database_succeeds_concurrently(
    tmp_path: Path,
) -> None:
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"
    proc_a = _spawn(db_a, hold_seconds=2.0)
    try:
        _wait_for_line(proc_a, "ACQUIRED")

        proc_b = _spawn(db_b, hold_seconds=0.1)
        stdout_b, _ = proc_b.communicate(timeout=10)
        assert proc_b.returncode == 0
        assert "ACQUIRED" in stdout_b
    finally:
        assert proc_a.wait(timeout=10) == 0


# 4. Clean release permits later acquisition.
def test_clean_release_permits_later_acquisition(tmp_path: Path) -> None:
    db = tmp_path / "release_check.db"
    proc = _spawn(db, hold_seconds=0.2)
    stdout, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0
    assert "RELEASED" in stdout

    lock = ExecutionProcessLock(db)
    lock.acquire()
    try:
        assert lock.is_acquired is True
    finally:
        lock.release()


# 5. Abrupt process termination permits later acquisition.
def test_abrupt_termination_permits_later_acquisition(tmp_path: Path) -> None:
    db = tmp_path / "kill_check.db"
    proc = _spawn(db, hold_seconds=30.0)
    try:
        _wait_for_line(proc, "ACQUIRED")
        proc.kill()
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)

    lock = ExecutionProcessLock(db)
    deadline = time.monotonic() + 5.0
    acquired = False
    last_error: Exception | None = None
    while time.monotonic() < deadline and not acquired:
        try:
            lock.acquire()
            acquired = True
        except Exception as exc:  # noqa: BLE001 - retry loop; asserted below
            last_error = exc
            time.sleep(_POLL_INTERVAL_SECONDS)

    try:
        assert acquired, (
            "Lock was not acquirable after abrupt termination of its "
            f"holder: {last_error}"
        )
    finally:
        if acquired:
            lock.release()


# 7. Equivalent relative and absolute database paths collide.
# 8. Canonicalized paths map to one sidecar.
def test_equivalent_relative_and_absolute_paths_collide(tmp_path: Path) -> None:
    db_abs = tmp_path / "equiv.db"
    proc_a = _spawn(db_abs, hold_seconds=2.0)
    try:
        _wait_for_line(proc_a, "ACQUIRED")

        relative_equivalent = os.path.relpath(str(db_abs), start=str(_REPO_ROOT))
        proc_b = _spawn(relative_equivalent, hold_seconds=0.1)
        proc_b.communicate(timeout=10)
        assert proc_b.returncode == 1
    finally:
        assert proc_a.wait(timeout=10) == 0
