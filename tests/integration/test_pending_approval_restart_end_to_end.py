"""
test_pending_approval_restart_end_to_end.py

End-to-end integration tests for durable pending-approval state surviving
a simulated process restart (Phase 27, Batch 1).

Unlike the unit-level ApprovalManager tests, these wire the real
SecurityManager, ToolRegistry, ToolExecutor, ApprovalManager, and a real
write tool (FileCopyTool) together, exactly as tests/integration/
test_write_approval_end_to_end.py already does for the live (non-restart)
flow. Each test here deliberately throws away every in-memory Python
object between "create a pending approval" and "reload it," constructing
a completely fresh ApprovalManager/ToolExecutor/ToolRegistry bound only to
the same on-disk SQLite database file - the closest a test can come to
proving a real process restart without literally spawning a subprocess.

Run with:
    pytest tests/integration/test_pending_approval_restart_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager, ApprovalReloadReport
from approval.pending_approval_store import PendingApprovalStore
from config.constants import SecurityTier
from security.security_manager import SecurityManager
from storage.database import create_session_factory, initialize_database
from tools.builtin import FileCopyTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


def _build_stack(session_factory, logger: _SpyLogger):
    """Build one full, independent registry/executor/manager stack bound
    to the given session_factory - simulating one process's worth of
    composition (mirrors main.py::build_orchestrator()'s own wiring, at
    the scale this test needs)."""
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCopyTool())
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    pending_store = PendingApprovalStore(session_factory)
    approvals = ApprovalManager(audit_logger=logger, pending_store=pending_store)
    return registry, executor, approvals


@pytest.fixture()
def session_factory(tmp_path: Path):
    from sqlalchemy import create_engine

    db_path = tmp_path / "jarvis_test.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def test_pending_approval_survives_restart_and_can_be_approved_and_executed(
    session_factory, workspace: Path
) -> None:
    (workspace / "source.txt").write_text("original content")

    # --- "process one": create a pending approval, then vanish. ---------
    registry_one, executor_one, approvals_one = _build_stack(
        session_factory, _SpyLogger()
    )
    tool_input = {
        "source": str(workspace / "source.txt"),
        "destination": str(workspace / "copied.txt"),
    }
    result = executor_one.execute("file_copy", tool_input)
    assert result.requires_confirmation is True
    request = approvals_one.create_request(
        "copy file",
        result.error or "Copying a file creates new state.",
        SecurityTier.YELLOW,
        tool_name="file_copy",
        tool_input=tool_input,
    )
    request_id = request.request_id
    del registry_one, executor_one, approvals_one, result, request  # simulate crash

    assert not (workspace / "copied.txt").exists()

    # --- "process two": fresh stack, same database file. -----------------
    registry_two, executor_two, approvals_two = _build_stack(
        session_factory, _SpyLogger()
    )
    report = approvals_two.reload_pending(registry=registry_two)
    assert report == ApprovalReloadReport(resumed=1, invalidated=0)
    assert approvals_two.has_pending(request_id)

    # Nothing executed merely from reloading.
    assert not (workspace / "copied.txt").exists()

    decision = approvals_two.approve(request_id)
    state = approvals_two.get_pending_tool_state(request_id)
    assert state is not None

    executed = executor_two.execute(
        state.tool_name,
        state.tool_input,
        approval_decision=decision,
    )
    assert executed.success is True
    assert (workspace / "copied.txt").read_text() == "original content"


def test_declined_after_restart_writes_nothing(
    session_factory, workspace: Path
) -> None:
    (workspace / "source.txt").write_text("original content")

    registry_one, executor_one, approvals_one = _build_stack(
        session_factory, _SpyLogger()
    )
    tool_input = {
        "source": str(workspace / "source.txt"),
        "destination": str(workspace / "copied.txt"),
    }

    executor_one.execute("file_copy", tool_input)
    request = approvals_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="file_copy", tool_input=tool_input,
    )
    request_id = request.request_id
    del registry_one, executor_one, approvals_one, request

    registry_two, executor_two, approvals_two = _build_stack(
        session_factory, _SpyLogger()
    )
    approvals_two.reload_pending(registry=registry_two)
    decision = approvals_two.decline(request_id)
    assert decision.is_declined is True
    assert not (workspace / "copied.txt").exists()


def test_no_bypass_around_approval_manager_after_restart(
    session_factory, workspace: Path
) -> None:
    """Reloading pending state must never let a tool run without a real,
    explicit approval decision - the executor's own gate is untouched."""
    (workspace / "source.txt").write_text("x")

    registry_one, executor_one, approvals_one = _build_stack(
        session_factory, _SpyLogger()
    )
    tool_input = {
        "source": str(workspace / "source.txt"),
        "destination": str(workspace / "copied.txt"),
    }

    executor_one.execute("file_copy", tool_input)
    approvals_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="file_copy", tool_input=tool_input,
    )
    del registry_one, executor_one, approvals_one

    registry_two, executor_two, approvals_two = _build_stack(
        session_factory, _SpyLogger()
    )
    approvals_two.reload_pending(registry=registry_two)

    # Attempt to run the tool directly with no approval decision at all.
    result = executor_two.execute("file_copy", tool_input)
    assert result.requires_confirmation is True
    assert not (workspace / "copied.txt").exists()


def test_reload_invalidation_leaves_nothing_executable(
    session_factory, workspace: Path
) -> None:
    """A row whose tool is no longer registered after restart is
    invalidated, not executed, and the source file is never touched."""
    (workspace / "source.txt").write_text("x")

    registry_one, executor_one, approvals_one = _build_stack(
        session_factory, _SpyLogger()
    )
    tool_input = {
        "source": str(workspace / "source.txt"),
        "destination": str(workspace / "copied.txt"),
    }

    executor_one.execute("file_copy", tool_input)
    request = approvals_one.create_request(
        "copy file", "reason", SecurityTier.YELLOW,
        tool_name="file_copy", tool_input=tool_input,
    )
    request_id = request.request_id
    del registry_one, executor_one, approvals_one, request

    # "process two" never registers file_copy at all.
    empty_registry = ToolRegistry()
    pending_store = PendingApprovalStore(session_factory)
    approvals_two = ApprovalManager(pending_store=pending_store)
    report = approvals_two.reload_pending(registry=empty_registry)

    assert report == ApprovalReloadReport(resumed=0, invalidated=1)
    assert approvals_two.has_pending(request_id) is False
    assert not (workspace / "copied.txt").exists()
    assert (workspace / "source.txt").read_text() == "x"
