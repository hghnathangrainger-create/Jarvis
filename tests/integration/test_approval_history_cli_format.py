"""
test_approval_history_cli_format.py

CLI-level integration tests for durable approval history (Phase 6, Batch 2).

Batch 1's integration test called orchestrator.handle_request() directly.
This file goes one layer further: it drives the actual JarvisCLI interactive
loop (the same code path a real terminal session uses), with scripted input
and captured output, over a real SQLite database. This is the closest an
automated test can get to "confirm all five commands work cleanly in the live
CLI" without an actual terminal.

Covered here:
    - All five history commands, run through the real CLI, show the [OK]
      status label (via the real format_response function) and every
      required field.
    - The existing YELLOW approve/decline flow still works end-to-end through
      the CLI, unchanged, with history layered on top.
    - History - and only history - survives a simulated restart; a fresh
      CLI/orchestrator built on the same database still shows past entries,
      while a request left pending is not restorable as an action.
    - A YELLOW request whose approval window elapses (Phase 6, Batch 3) shows
      as EXPIRED in durable history, through the real orchestrator and
      database, and can no longer be approved or declined.

These tests use the real FileCreateTool to exercise real YELLOW write
actions, but every file it creates is pointed at pytest's per-test tmp_path
fixture (an isolated temporary directory), never at the repository working
directory - so running this suite never leaves stray files in the repo.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/integration/test_approval_history_cli_format.py
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


class _ScriptedIO:
    """Feeds canned input lines to a JarvisCLI and records every printed line.

    Once the scripted inputs are exhausted, further reads raise EOFError,
    matching how JarvisCLI.run() ends a real session at end-of-input.
    """

    def __init__(self, inputs: list[str]) -> None:
        self._inputs = list(inputs)
        self.output_lines: list[str] = []

    def input_fn(self, prompt: str) -> str:
        if not self._inputs:
            raise EOFError
        return self._inputs.pop(0)

    def output_fn(self, line: str) -> None:
        self.output_lines.append(line)

    @property
    def transcript(self) -> str:
        """The full session output, as one string, for substring assertions."""
        return "\n".join(self.output_lines)


class _System:
    """The real components wired together with a real SQLite database.

    Every _System instance built on the same `engine` shares the same
    underlying data, which is what makes the restart tests meaningful: a
    fresh _System still constructs a brand-new ApprovalManager (empty
    _pending), while the ApprovalHistoryStore reads and writes real,
    persisted rows.
    """

    def __init__(
        self,
        engine: object,
        *,
        timeout_seconds: int | None = None,
        clock: object | None = None,
    ) -> None:
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
            audit_logger=self.logger,
            history_store=self.history,
            timeout_seconds=timeout_seconds,
            clock=clock,
        )
        self.orchestrator = JarvisOrchestrator(
            planner=Planner(self.security),
            executor=self.executor,
            registry=self.registry,
            command_router=CommandRouter(self.registry),
            approval_manager=self.approvals,
        )

    def cli(self, inputs: list[str]) -> _ScriptedIO:
        """Build a JarvisCLI over this system's orchestrator and run it.

        Args:
            inputs: The scripted lines of input for the session.

        Returns:
            The _ScriptedIO used, with the full session transcript recorded.
        """
        from ui.cli import JarvisCLI

        io = _ScriptedIO(inputs)
        cli = JarvisCLI(
            self.orchestrator, input_fn=io.input_fn, output_fn=io.output_fn
        )
        cli.run()
        return io


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

    Using an absolute path inside pytest's per-test tmp_path fixture (rather
    than a bare filename) means these tests still exercise the real
    FileCreateTool end to end, but nothing they create ever lands in the
    repository working directory.

    Args:
        tmp_path: The per-test temporary directory fixture.
        filename: The bare filename to create inside tmp_path.
        content: The content to write into the file.

    Returns:
        The natural-language command string routed to file_create.
    """
    return f"create file {tmp_path / filename} with {content}"


# --- All five commands, run through the real CLI loop -----------------------


def test_show_approval_history_prints_ok_status(
    engine: object, tmp_path: Path
) -> None:
    """Phase 73, Batch 1 added a real, all-time status breakdown to this
    header - previously a bare "Approval history:", now "Approval
    history (pending: 0, approved: 1, declined: 0, expired: 0):" for
    this test's own single-approved-action scenario. Updated here as an
    intentional, approved consequence of that change, not a regression."""
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "a.txt", "x"), "y", "show approval history"]
    )
    assert "[OK] Approval history (pending: 0, approved: 1, declined: 0, expired: 0):" in io.transcript


def test_show_recent_approvals_prints_ok_status(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "a.txt", "x"), "y", "show recent approvals"]
    )
    assert "[OK] Recent approvals:" in io.transcript


def test_show_approved_actions_prints_ok_status(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "a.txt", "x"), "y", "show approved actions"]
    )
    assert "[OK] Approved actions:" in io.transcript


def test_show_declined_actions_prints_ok_status(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "a.txt", "x"), "n", "show declined actions"]
    )
    assert "[OK] Declined actions:" in io.transcript


def test_show_approval_by_id_prints_ok_status_and_detail(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    request_id = response.approval_request.request_id
    system.approvals.approve(request_id)

    io = system.cli([f"show approval {request_id}"])
    assert "[OK] Approval " + request_id in io.transcript
    assert "status: approved" in io.transcript


# --- Required fields visible through the real CLI formatting path ----------


def test_approved_entry_shows_all_required_fields_through_cli(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "a.txt", "x"), "y", "show approval history"]
    )
    transcript = io.transcript

    assert "APPROVED" in transcript
    assert "create file" in transcript  # the action text
    assert "tier: yellow" in transcript
    assert "created:" in transcript
    assert "decided:" in transcript
    assert "by user" in transcript


def test_pending_entry_omits_decision_fields_through_cli(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "a.txt", "x"), "y", "show approval history"]
    )
    # The approved entry from above should show decided fields...
    assert "decided:" in io.transcript

    # ...while a still-pending request shows none of them. Check this via a
    # second, independent system sharing the same database: leave one
    # request pending, then read history back and inspect that specific
    # entry's own detail line (the line directly after its summary line).
    second = _System(engine)
    pending_response = second.orchestrator.handle_request(
        _create_file_command(tmp_path, "pending.txt", "y")
    )
    pending_id = pending_response.approval_request.request_id

    history_output = second.orchestrator.handle_request("show approval history")
    lines = history_output.message.splitlines()
    summary_index = next(
        i for i, line in enumerate(lines) if pending_id in line
    )
    detail_line = lines[summary_index + 1]

    assert "PENDING" in lines[summary_index]
    assert "tier:" in detail_line
    assert "created:" in detail_line
    assert "decided" not in detail_line
    assert "reason" not in detail_line


# --- Existing approval flow, unchanged, through the CLI ---------------------


def test_existing_approve_flow_still_works_through_cli(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "report.txt", "numbers"), "y"]
    )
    assert "[NEEDS APPROVAL]" in io.transcript
    assert "[APPROVED]" in io.transcript


def test_existing_decline_flow_still_works_through_cli(
    engine: object, tmp_path: Path
) -> None:
    system = _System(engine)
    io = system.cli(
        [_create_file_command(tmp_path, "report.txt", "numbers"), "n"]
    )
    assert "[NEEDS APPROVAL]" in io.transcript
    assert "[DECLINED]" in io.transcript


# --- History survives a restart; pending state does not, through the CLI ---


def test_history_visible_through_cli_after_simulated_restart(
    engine: object, tmp_path: Path
) -> None:
    first_run = _System(engine)
    response = first_run.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    first_run.approvals.approve(response.approval_request.request_id)

    second_run = _System(engine)
    io = second_run.cli(["show approval history"])
    assert response.approval_request.request_id in io.transcript
    assert "APPROVED" in io.transcript


def test_pending_request_not_approvable_after_simulated_restart_via_cli(
    engine: object, tmp_path: Path
) -> None:
    first_run = _System(engine)
    first_run.orchestrator.handle_request(
        _create_file_command(tmp_path, "b.txt", "y")
    )
    # Deliberately left pending across the simulated restart below.

    second_run = _System(engine)
    assert second_run.approvals.list_pending() == []


# --- YELLOW approval timeout, through the real stack (Phase 6, Batch 3) ----


class _FakeClock:
    """A settable clock so this integration test can simulate elapsed time
    against the real orchestrator, ApprovalManager, and database - not just
    the in-memory unit tests in test_approval_manager_timeout.py."""

    def __init__(self, start: object) -> None:
        self.now = start

    def __call__(self) -> object:
        return self.now


def test_timed_out_request_shows_expired_in_history_through_cli(
    engine: object, tmp_path: Path
) -> None:
    from datetime import datetime, timedelta, timezone

    from approval.approval_models import ApprovalError

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = _FakeClock(start)
    system = _System(engine, timeout_seconds=60, clock=clock)

    # Created directly through the orchestrator (not system.cli(...)), so the
    # request becomes pending without the CLI immediately blocking on an
    # approval prompt - the same pattern already used above for a request
    # left deliberately pending across a simulated restart.
    response = system.orchestrator.handle_request(
        _create_file_command(tmp_path, "a.txt", "x")
    )
    request_id = response.approval_request.request_id

    clock.now = start + timedelta(seconds=60)  # exactly at the boundary

    # The sweep is lazy: it fires when ApprovalManager's own pending state is
    # next touched (get_pending/list_pending/has_pending, or approve/decline
    # via get_pending) - not merely by reading durable history, which the
    # read-only "show approval..." commands do directly against the store and
    # never touch the manager at all. Attempting to approve is what a real
    # late decision would do, and it is what triggers the sweep here.
    with pytest.raises(ApprovalError):
        system.approvals.approve(request_id)
    with pytest.raises(ApprovalError):
        system.approvals.decline(request_id)

    # Durable history now reflects the expiry, through the real CLI/tool path.
    io = system.cli(["show approval history"])
    assert f"[{request_id}] EXPIRED" in io.transcript

    # Never recorded as, or mistaken for, an approved or declined outcome.
    approved_io = system.cli(["show approved actions"])
    assert request_id not in approved_io.transcript
    declined_io = system.cli(["show declined actions"])
    assert request_id not in declined_io.transcript
