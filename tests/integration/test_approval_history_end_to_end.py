"""
test_approval_history_end_to_end.py

End-to-end integration tests for durable approval history (Phase 6, Batch 1).

These wire the real components together - Planner, Security Manager, Tool
Registry, Tool Executor, ApprovalManager, ApprovalHistoryStore, and the real
JarvisOrchestrator - over a real SQLite database, and call
orchestrator.handle_request() directly (unlike
test_approval_history_cli_format.py, which goes one layer further and drives
the actual JarvisCLI loop on top of this same stack).

Per docs/phase_6_progress_report.md, this file is the intended home for:
    - Approved actions appear in durable history.
    - Declined actions appear in durable history.
    - All five approval-history commands are GREEN (they run automatically,
      through the real orchestrator, with no approval required).
    - History survives a simulated restart (a fresh _System built on the same
      database still shows past entries).
    - A simulated restart does not restore pending approvals (in-memory
      pending state is never rehydrated from history).
    - The existing YELLOW flow and its auditing still work, unchanged.

These tests use the real FileCreateTool to exercise a genuine YELLOW write
action, but every file it creates is pointed at pytest's per-test tmp_path
fixture (an isolated temporary directory), never at the repository working
directory.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/integration/test_approval_history_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")


class _SpyLogger:
    """A minimal stand-in for EventLogger that records every emitted event."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _System:
    """The real components wired together with a real SQLite database.

    Every _System instance built on the same `engine` shares the same
    underlying data, which is what makes the restart scenarios meaningful: a
    fresh _System still constructs a brand-new ApprovalManager (empty
    _pending), while the ApprovalHistoryStore reads and writes real,
    persisted rows. Unlike test_approval_history_cli_format.py's _System,
    there is no CLI layer here - tests call orchestrator.handle_request()
    directly, matching this file's documented Batch 1 scope.
    """

    def __init__(self, engine: object) -> None:
        from approval.approval_history_store import ApprovalHistoryStore
        from approval.approval_manager import ApprovalManager
        from core.command_router import CommandRouter
        from core.orchestrator import JarvisOrchestrator
        from memory.episodic_memory import EpisodicMemoryStore
        from memory.memory_manager import MemoryManager
        from planner.planner import Planner
        from security.security_manager import SecurityManager
        from storage.database import create_session_factory
        from tools.builtin import ApprovalHistoryTool, FileCreateTool, MemoryTool
        from tools.executor import ToolExecutor
        from tools.registry import ToolRegistry

        factory = create_session_factory(engine)
        self.memory = MemoryManager(EpisodicMemoryStore(factory))
        self.history = ApprovalHistoryStore(factory)

        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.registry.register_tool(MemoryTool(self.memory))
        self.registry.register_tool(FileCreateTool())
        self.registry.register_tool(ApprovalHistoryTool(self.history))
        self.executor = ToolExecutor(
            registry=self.registry,
            security_manager=self.security,
            logger=self.logger,
        )
        self.approvals = ApprovalManager(
            audit_logger=self.logger, history_store=self.history
        )
        self.orchestrator = JarvisOrchestrator(
            planner=Planner(self.security),
            executor=self.executor,
            registry=self.registry,
            command_router=CommandRouter(self.registry),
            approval_manager=self.approvals,
        )


@pytest.fixture()
def engine() -> object:
    """A shared, connection-pooled in-memory SQLite engine (see Batch 1)."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from storage.database import initialize_database

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    initialize_database(eng)
    return eng


def _create_file_command(tmp_path: Path, filename: str, content: str) -> str:
    """Build a "create file <path> with <content>" command under tmp_path.

    Args:
        tmp_path: The per-test temporary directory fixture.
        filename: The bare filename to create inside tmp_path.
        content: The content to write into the file.

    Returns:
        The natural-language command string routed to file_create.
    """
    return f"create file {tmp_path / filename} with {content}"


# --- Approved and declined actions appear in durable history -----------------


def test_approved_action_appears_in_history(engine: object, tmp_path: Path) -> None:
    system = _System(engine)
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    request_id = response.approval_request.request_id
    system.approvals.approve(request_id, decided_by="user")

    record = system.history.get(request_id)
    assert record is not None
    assert record.status == "approved"
    assert record.decided_by == "user"


def test_declined_action_appears_in_history(engine: object, tmp_path: Path) -> None:
    system = _System(engine)
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    request_id = response.approval_request.request_id
    system.approvals.decline(request_id, decided_by="user")

    record = system.history.get(request_id)
    assert record is not None
    assert record.status == "declined"


# --- All five approval-history commands are GREEN ----------------------------


@pytest.mark.parametrize(
    "command",
    [
        "show approval history",
        "show recent approvals",
        "show approved actions",
        "show declined actions",
    ],
)
def test_history_list_commands_are_green(
    engine: object, command: str
) -> None:
    """Each list command runs automatically: no approval, nothing blocked."""
    system = _System(engine)
    response = system.orchestrator.handle_request(command)
    assert response.blocked is False
    assert response.requires_confirmation is False
    assert response.approval_request is None


def test_show_approval_by_id_is_green(engine: object, tmp_path: Path) -> None:
    system = _System(engine)
    created = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    request_id = created.approval_request.request_id
    system.approvals.approve(request_id, decided_by="user")

    response = system.orchestrator.handle_request(f"show approval {request_id}")
    assert response.blocked is False
    assert response.requires_confirmation is False
    assert response.success is True


# --- History survives a simulated restart ------------------------------------


def test_history_survives_simulated_restart(engine: object, tmp_path: Path) -> None:
    first_run = _System(engine)
    response = first_run.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    request_id = response.approval_request.request_id
    first_run.approvals.approve(request_id, decided_by="user")

    # A fresh _System over the same engine simulates a process restart: a new
    # ApprovalManager, a new ApprovalHistoryStore instance, same database.
    second_run = _System(engine)
    record = second_run.history.get(request_id)
    assert record is not None
    assert record.status == "approved"


def test_simulated_restart_does_not_restore_pending_approvals(
    engine: object, tmp_path: Path
) -> None:
    first_run = _System(engine)
    first_run.orchestrator.handle_request(
        _create_file_command(tmp_path, "b.txt", "y")
    )
    # Deliberately left pending across the simulated restart below - never
    # approved or declined in this process "lifetime".

    second_run = _System(engine)
    assert second_run.approvals.list_pending() == []


# --- The existing YELLOW flow and its auditing still work --------------------


def test_yellow_action_still_requires_approval_before_running(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    path = tmp_path / "c.txt"
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "c.txt", "z")
    )
    assert response.requires_confirmation is True
    assert not path.exists()  # the file is not created until approved


def test_yellow_action_runs_after_approval(engine: object, tmp_path: Path) -> None:
    system = _System(engine)
    path = tmp_path / "d.txt"
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "d.txt", "w")
    )
    decision = system.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )
    executed = system.orchestrator.execute_approved(response, decision)
    assert executed.success is True
    assert path.exists()


def test_approval_decision_is_audited(engine: object, tmp_path: Path) -> None:
    system = _System(engine)
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    system.approvals.approve(response.approval_request.request_id, decided_by="user")

    approval_events = [
        e for e in system.logger.events if e.get("action_type") == "approval_decision"
    ]
    assert len(approval_events) == 1
