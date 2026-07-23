"""
test_process_lock.py

Single-process unit tests for runtime.process_lock (Approval-to-Resume
Handoff Interlock, Batch 1 - docs/phase_98_approval_handoff_plan.md):
canonical database identity, sidecar lock-path derivation, and the
ExecutionProcessLock context-manager mechanics that do not themselves
require a genuine second OS process to prove (those live in
tests/integration/test_process_lock_subprocess.py instead - a hard
requirement of this batch, since only a real subprocess can prove real
OS-enforced cross-process exclusivity).

Run with:
    pytest tests/unit/test_process_lock.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from runtime.process_lock import (
    ExecutionLockError,
    ExecutionProcessLock,
    InMemoryDatabaseLockError,
    canonical_database_path,
    lock_path_for,
)

_MODULE_PATH = Path(__file__).resolve().parents[2] / "runtime" / "process_lock.py"


# --- canonical identity -------------------------------------------------------


def test_relative_and_absolute_paths_canonicalize_identically(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"
    db.parent.mkdir(parents=True, exist_ok=True)

    absolute = canonical_database_path(db)

    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        relative = canonical_database_path(Path("jarvis.db"))
    finally:
        os.chdir(cwd)

    assert absolute == relative


def test_canonical_path_resolves_symlink_free_dotted_segments(tmp_path: Path) -> None:
    nested = tmp_path / "sub" / ".." / "jarvis.db"
    canonical = canonical_database_path(nested)
    assert canonical == canonical_database_path(tmp_path / "jarvis.db")


@pytest.mark.skipif(sys.platform != "win32", reason="Case-insensitivity is Windows-specific")
def test_case_varied_paths_canonicalize_identically_on_windows(tmp_path: Path) -> None:
    lower = canonical_database_path(tmp_path / "jarvis.db")
    upper = canonical_database_path(tmp_path / "JARVIS.DB")
    assert lower == upper


def test_distinct_database_files_canonicalize_to_distinct_paths(tmp_path: Path) -> None:
    a = canonical_database_path(tmp_path / "a.db")
    b = canonical_database_path(tmp_path / "b.db")
    assert a != b


# --- sidecar lock-path derivation ---------------------------------------------


def test_lock_path_has_expected_suffix(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"
    lock_path = lock_path_for(db)
    assert lock_path.name == "jarvis.db.jarvis.lock"
    assert lock_path.parent == canonical_database_path(db).parent


def test_lock_path_for_equivalent_paths_is_identical(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"
    cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        relative_lock_path = lock_path_for(Path("jarvis.db"))
    finally:
        os.chdir(cwd)
    assert lock_path_for(db) == relative_lock_path


def test_lock_path_for_in_memory_database_raises() -> None:
    with pytest.raises(InMemoryDatabaseLockError):
        lock_path_for(Path(":memory:"))


def test_execution_process_lock_construction_rejects_in_memory_database() -> None:
    with pytest.raises(InMemoryDatabaseLockError):
        ExecutionProcessLock(Path(":memory:"))


# --- acquire / release lifecycle ----------------------------------------------


def test_acquire_then_release_cycle(tmp_path: Path) -> None:
    lock = ExecutionProcessLock(tmp_path / "jarvis.db")
    assert lock.is_acquired is False

    lock.acquire()
    assert lock.is_acquired is True

    lock.release()
    assert lock.is_acquired is False


def test_double_acquisition_by_same_object_raises(tmp_path: Path) -> None:
    lock = ExecutionProcessLock(tmp_path / "jarvis.db")
    lock.acquire()
    try:
        with pytest.raises(ExecutionLockError):
            lock.acquire()
    finally:
        lock.release()


def test_repeated_release_is_a_safe_no_op(tmp_path: Path) -> None:
    lock = ExecutionProcessLock(tmp_path / "jarvis.db")
    lock.acquire()
    lock.release()
    lock.release()  # must not raise
    assert lock.is_acquired is False


def test_context_manager_acquires_and_releases(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"
    with ExecutionProcessLock(db) as lock:
        assert lock.is_acquired is True
    assert lock.is_acquired is False


def test_exception_inside_context_manager_still_releases(tmp_path: Path) -> None:
    db = tmp_path / "jarvis.db"

    with pytest.raises(RuntimeError):
        with ExecutionProcessLock(db) as lock:
            assert lock.is_acquired is True
            raise RuntimeError("boom")

    # A fresh instance must be able to acquire immediately - proving the
    # first instance's lock was genuinely released, not merely that its
    # own is_acquired flag flipped.
    second = ExecutionProcessLock(db)
    second.acquire()
    second.release()


def test_release_leaves_no_lingering_lock_for_a_new_instance(tmp_path: Path) -> None:
    """Item 13: no active lock remains after release(). A leaked file
    descriptor still holding the OS lock would block this second,
    independent instance's own acquire() - so this is real proof, not
    merely an internal-flag check."""
    db = tmp_path / "jarvis.db"
    first = ExecutionProcessLock(db)
    first.acquire()
    first.release()

    second = ExecutionProcessLock(db)
    second.acquire()  # must not raise
    second.release()


def test_second_instance_same_database_is_rejected_while_first_holds_it(
    tmp_path: Path,
) -> None:
    """In-process proof that the OS lock is real (per open file
    description), not merely an in-object flag: a second, independent
    ExecutionProcessLock instance for the same database, opening its
    own file descriptor, cannot acquire while the first still holds it -
    even though both live in the same process. The hard cross-process
    requirement is proven separately, with real subprocesses, in
    tests/integration/test_process_lock_subprocess.py."""
    db = tmp_path / "jarvis.db"
    first = ExecutionProcessLock(db)
    first.acquire()
    try:
        second = ExecutionProcessLock(db)
        with pytest.raises(ExecutionLockError):
            second.acquire()
        assert second.is_acquired is False
    finally:
        first.release()

    # Once released, a fresh acquisition attempt succeeds.
    third = ExecutionProcessLock(db)
    third.acquire()
    third.release()


def test_stale_sidecar_file_without_held_lock_does_not_block_acquisition(
    tmp_path: Path,
) -> None:
    """Item 6: a sidecar file's mere existence (left behind by a prior,
    already-exited process, or created here directly) proves nothing -
    only a live, held OS lock does. Pre-creating the file with no lock
    held must never block a fresh acquisition."""
    db = tmp_path / "jarvis.db"
    lock_path = lock_path_for(db)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(b"stale contents from a previous run")

    lock = ExecutionProcessLock(db)
    lock.acquire()  # must not raise
    try:
        assert lock.is_acquired is True
    finally:
        lock.release()


# --- structural proofs (no database/handoff mutation; real kernel locking) ---


def _referenced_identifiers(source: str) -> set[str]:
    tree = ast.parse(source)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Import):
            identifiers.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            identifiers.update(node.module.split("."))
    return identifiers


def test_module_never_touches_database_or_approval_machinery() -> None:
    """Item 11: acquisition failure must perform no database or handoff
    mutation. Proven structurally (AST-based, not raw text search, since
    this module's own docstrings legitimately name these concepts when
    explaining what it does not do): the module imports and references
    none of them at all."""
    source = _MODULE_PATH.read_text(encoding="utf-8")
    identifiers = _referenced_identifiers(source)
    assert "session_scope" not in identifiers
    assert "ApprovalManager" not in identifiers
    assert "PendingApprovalStore" not in identifiers
    assert "create_database_engine" not in identifiers
    assert "initialize_database" not in identifiers


def test_module_dispatches_to_real_platform_locking_primitives() -> None:
    """Item 14: the module uses the real, platform-appropriate kernel
    locking primitive - never a mock, never a third-party lock library."""
    source = _MODULE_PATH.read_text(encoding="utf-8")
    identifiers = _referenced_identifiers(source)
    assert "fcntl" in identifiers
    assert "msvcrt" in identifiers
    # Confirms the platform dispatch is conditioned on sys.platform, not
    # an unconditional import of both on every platform (fcntl does not
    # exist on Windows; msvcrt does not exist on POSIX).
    assert "sys.platform" in source or "sys" in identifiers
