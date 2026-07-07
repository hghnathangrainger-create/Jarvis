"""
test_write_approval_end_to_end.py

End-to-end integration tests for the guarded write approval flow
(Phase 4, Batch 2).

These wire the real Security Manager, Tool Registry, Tool Executor, Approval
Manager, and the two write tools together, and trace a write action through its
full journey: request -> YELLOW approval -> approved-and-written or
declined-and-untouched. They prove the filesystem only changes when a write is
actually approved, that a RED action stays blocked even with an approval, and
that every decision is audited.

Run with:
    pytest tests/integration/test_write_approval_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from approval.approval_manager import ApprovalManager
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import (
    EchoTool,
    FileAppendTool,
    FileCreateTool,
    FileListTool,
    FileReadTool,
)
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))

    def approval_events(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action_type") == "approval_decision"]


class _RedWriteTool(BaseTool):
    """A tool whose action classifies RED; its run must never be reached."""

    def __init__(self) -> None:
        self.ran = False

    @property
    def name(self) -> str:
        return "danger_write"

    @property
    def description(self) -> str:
        return "A dangerous tool that must never run."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        self.ran = True
        raise AssertionError("A RED action must never run.")


class _System:
    """The real components wired together, plus a RED tool for safety tests."""

    def __init__(self) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.red = _RedWriteTool()
        self.registry.register_tool(EchoTool())
        self.registry.register_tool(FileListTool())
        self.registry.register_tool(FileReadTool())
        self.registry.register_tool(FileCreateTool())
        self.registry.register_tool(FileAppendTool())
        self.registry.register_tool(self.red)
        self.executor = ToolExecutor(
            registry=self.registry,
            security_manager=self.security,
            logger=self.logger,  # type: ignore[arg-type]
        )
        self.approvals = ApprovalManager(audit_logger=self.logger)  # type: ignore[arg-type]
        self.orchestrator = JarvisOrchestrator(
            planner=Planner(self.security),
            executor=self.executor,
            registry=self.registry,
            command_router=CommandRouter(self.registry),
            approval_manager=self.approvals,
        )


@pytest.fixture()
def system() -> _System:
    return _System()


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- Create: approved writes, declined does not ------------------------------


def test_approved_create_writes_the_file(
    system: _System, workspace: Path
) -> None:
    response = system.orchestrator.handle_request(
        "create file made.txt with APPROVED"
    )
    assert response.requires_confirmation is True
    assert not (workspace / "made.txt").exists()

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert (workspace / "made.txt").read_text() == "APPROVED"


def test_declined_create_writes_nothing(
    system: _System, workspace: Path
) -> None:
    response = system.orchestrator.handle_request(
        "create file nope.txt with SHOULD NOT EXIST"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert not (workspace / "nope.txt").exists()


# --- Append: approved writes, declined does not ------------------------------


def test_approved_append_modifies_the_file(
    system: _System, workspace: Path
) -> None:
    target = workspace / "log.txt"
    target.write_text("base")
    response = system.orchestrator.handle_request(
        "append -added to file log.txt"
    )
    assert response.requires_confirmation is True
    assert target.read_text() == "base"  # not yet appended

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert target.read_text() == "base-added"


def test_declined_append_leaves_file_unchanged(
    system: _System, workspace: Path
) -> None:
    target = workspace / "keep.txt"
    target.write_text("original")
    response = system.orchestrator.handle_request("append XXX to file keep.txt")
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert target.read_text() == "original"


# --- RED stays blocked, writes are audited -----------------------------------


def test_red_write_stays_blocked_even_when_approved(
    system: _System, workspace: Path
) -> None:
    # Fabricate an approval and point it at the RED tool via the executor.
    from config.constants import SecurityTier

    request = system.approvals.create_request(
        action="format drive",
        reason="A mistaken approval attempt.",
        security_tier=SecurityTier.YELLOW,
    )
    decision = system.approvals.approve(request.request_id)
    result = system.executor.execute(
        "danger_write", approval_decision=decision
    )
    assert result.blocked is True
    assert system.red.ran is False


def test_write_decisions_are_audited(
    system: _System, workspace: Path
) -> None:
    response = system.orchestrator.handle_request(
        "create file audited.txt with x"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    approval_events = system.logger.approval_events()
    assert len(approval_events) == 1
    assert "outcome=approved" in str(approval_events[0]["detail"])


def test_full_create_then_append_journey(
    system: _System, workspace: Path
) -> None:
    """Create a file (approved), then append to it (approved)."""
    create = system.orchestrator.handle_request(
        "create file story.txt with Chapter 1"
    )
    system.orchestrator.execute_approved(
        create, system.approvals.approve(create.approval_request.request_id)
    )
    assert (workspace / "story.txt").read_text() == "Chapter 1"

    append = system.orchestrator.handle_request(
        "append the end to file story.txt"
    )
    system.orchestrator.execute_approved(
        append, system.approvals.approve(append.approval_request.request_id)
    )
    assert (workspace / "story.txt").read_text() == "Chapter 1the end"