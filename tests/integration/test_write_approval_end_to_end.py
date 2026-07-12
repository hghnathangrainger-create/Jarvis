"""
test_write_approval_end_to_end.py

End-to-end integration tests for the guarded write approval flow
(Phase 4, Batch 2; extended Phase 25 with FileCopyTool; extended
Phase 26 with FileMoveTool; extended Phase 35 with FileDeleteTool).

These wire the real Security Manager, Tool Registry, Tool Executor, Approval
Manager, and the write tools together, and trace a write action through its
full journey: request -> YELLOW approval -> approved-and-written or
declined-and-untouched. They prove the filesystem only changes when a write is
actually approved, that a RED action stays blocked even with an approval, and
that every decision is audited.

Run with:
    pytest tests/integration/test_write_approval_end_to_end.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import (
    EchoTool,
    FileAppendTool,
    FileCopyTool,
    FileCreateTool,
    FileDeleteTool,
    FileListTool,
    FileMoveTool,
    FileReadTool,
)
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.approval_prompt import format_approval_request

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


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

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        clock: object | None = None,
    ) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.red = _RedWriteTool()
        self.registry.register_tool(EchoTool())
        self.registry.register_tool(FileListTool())
        self.registry.register_tool(FileReadTool())
        self.registry.register_tool(FileCreateTool())
        self.registry.register_tool(FileAppendTool())
        self.registry.register_tool(FileCopyTool())
        self.registry.register_tool(FileMoveTool())
        self.registry.register_tool(FileDeleteTool())
        self.registry.register_tool(self.red)
        self.executor = ToolExecutor(
            registry=self.registry,
            security_manager=self.security,
            logger=self.logger,  # type: ignore[arg-type]
        )
        self.approvals = ApprovalManager(
            audit_logger=self.logger,  # type: ignore[arg-type]
            timeout_seconds=timeout_seconds,
            clock=clock,  # type: ignore[arg-type]
        )
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


# --- Copy: approved copies, declined does not, never overwrites (Phase 25) ------


def test_approved_copy_creates_the_destination(
    system: _System, workspace: Path
) -> None:
    source = workspace / "source.txt"
    source.write_text("original content")
    destination = workspace / "dest.txt"

    response = system.orchestrator.handle_request(
        "copy file source.txt to dest.txt"
    )
    assert response.requires_confirmation is True
    assert not destination.exists()  # not yet copied

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert destination.read_text() == "original content"
    assert source.read_text() == "original content"  # source untouched


def test_declined_copy_creates_nothing(system: _System, workspace: Path) -> None:
    source = workspace / "source.txt"
    source.write_text("original content")
    destination = workspace / "dest.txt"

    response = system.orchestrator.handle_request(
        "copy file source.txt to dest.txt"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert not destination.exists()


def test_approval_cannot_override_existing_destination_refusal(
    system: _System, workspace: Path
) -> None:
    """The no-overwrite rule is not something approval can waive - even a
    fully approved copy still refuses if the destination already exists."""
    source = workspace / "source.txt"
    source.write_text("new content")
    destination = workspace / "dest.txt"
    destination.write_text("pre-existing content, must survive")

    response = system.orchestrator.handle_request(
        "copy file source.txt to dest.txt"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert destination.read_text() == "pre-existing content, must survive"


def test_copy_requires_no_direct_bypass_around_approval_manager(
    system: _System, workspace: Path
) -> None:
    """A copy request that is never approved or declined at all must
    never write anything - there is no path from handle_request() to a
    written file that skips ApprovalManager entirely."""
    source = workspace / "source.txt"
    source.write_text("content")
    destination = workspace / "dest.txt"

    response = system.orchestrator.handle_request(
        "copy file source.txt to dest.txt"
    )
    assert response.requires_confirmation is True
    assert response.success is False  # nothing has run yet
    assert not destination.exists()


# --- Move: approved moves, declined does not, never overwrites (Phase 26) -------


def test_approved_move_relocates_the_file(system: _System, workspace: Path) -> None:
    source = workspace / "source.txt"
    source.write_text("original content")
    destination = workspace / "dest.txt"

    response = system.orchestrator.handle_request(
        "move file source.txt to dest.txt"
    )
    assert response.requires_confirmation is True
    assert source.exists()  # not yet moved
    assert not destination.exists()

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert destination.read_text() == "original content"
    assert not source.exists()  # source relocated, not just copied


def test_approved_rename_alias_relocates_the_file(
    system: _System, workspace: Path
) -> None:
    source = workspace / "source.txt"
    source.write_text("original content")
    destination = workspace / "renamed.txt"

    response = system.orchestrator.handle_request(
        "rename file source.txt to renamed.txt"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert destination.read_text() == "original content"
    assert not source.exists()


def test_declined_move_leaves_everything_unchanged(
    system: _System, workspace: Path
) -> None:
    source = workspace / "source.txt"
    source.write_text("original content")
    destination = workspace / "dest.txt"

    response = system.orchestrator.handle_request(
        "move file source.txt to dest.txt"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert source.exists()
    assert not destination.exists()


def test_move_approval_cannot_override_existing_destination_refusal(
    system: _System, workspace: Path
) -> None:
    """The no-overwrite rule is not something approval can waive - even a
    fully approved move still refuses if the destination already
    exists, and the source is correctly left in place (never
    half-consumed by a refused move)."""
    source = workspace / "source.txt"
    source.write_text("new content")
    destination = workspace / "dest.txt"
    destination.write_text("pre-existing content, must survive")

    response = system.orchestrator.handle_request(
        "move file source.txt to dest.txt"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert destination.read_text() == "pre-existing content, must survive"
    assert source.exists()  # never consumed by the refused move
    assert source.read_text() == "new content"


def test_move_requires_no_direct_bypass_around_approval_manager(
    system: _System, workspace: Path
) -> None:
    """A move request that is never approved or declined at all must
    never relocate anything - there is no path from handle_request() to
    a moved file that skips ApprovalManager entirely."""
    source = workspace / "source.txt"
    source.write_text("content")
    destination = workspace / "dest.txt"

    response = system.orchestrator.handle_request(
        "move file source.txt to dest.txt"
    )
    assert response.requires_confirmation is True
    assert response.success is False  # nothing has run yet
    assert source.exists()
    assert not destination.exists()


# --- Delete/Quarantine: approved moves to trash, declined/timed-out does not ---
# (Phase 35) ----------------------------------------------------------------


def test_delete_file_requires_yellow_approval_before_execution(
    system: _System, workspace: Path
) -> None:
    target = workspace / "notes.txt"
    target.write_text("content")

    response = system.orchestrator.handle_request("delete file notes.txt")

    assert response.requires_confirmation is True
    assert response.success is False
    assert target.exists()  # not yet moved


def test_delete_file_classification_is_fixed_and_not_path_dependent(
    system: _System, workspace: Path
) -> None:
    (workspace / "a.txt").write_text("a")
    (workspace / "b.txt").write_text("b")

    response_one = system.orchestrator.handle_request("delete file a.txt")
    response_two = system.orchestrator.handle_request(
        "delete file ../../../etc/passwd"
    )

    assert response_one.requires_confirmation is True
    assert response_two.requires_confirmation is True
    assert response_one.approval_request.security_tier == (
        response_two.approval_request.security_tier
    )
    assert response_one.tool_name == "file_delete"
    assert response_two.tool_name == "file_delete"


def test_approval_prompt_clearly_indicates_deletion_risk(
    system: _System, workspace: Path
) -> None:
    (workspace / "notes.txt").write_text("content")
    response = system.orchestrator.handle_request("delete file notes.txt")

    formatted = format_approval_request(response.approval_request)
    lowered = formatted.lower()
    assert "delete file" in lowered
    assert "delet" in lowered or "confirm" in lowered


def test_approved_delete_moves_the_file_into_quarantine(
    system: _System, workspace: Path
) -> None:
    source = workspace / "notes.txt"
    source.write_text("important content")

    response = system.orchestrator.handle_request("delete file notes.txt")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert not source.exists()  # removed from its original path only
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantined_files = list(quarantine_dir.iterdir())
    assert len(quarantined_files) == 1
    assert quarantined_files[0].read_text() == "important content"


def test_declined_delete_leaves_the_file_untouched(
    system: _System, workspace: Path
) -> None:
    source = workspace / "notes.txt"
    source.write_text("content")

    response = system.orchestrator.handle_request("delete file notes.txt")
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert source.exists()
    assert source.read_text() == "content"
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()


def test_timed_out_approval_leaves_the_file_untouched(workspace: Path) -> None:
    clock = _FakeClock(_START)
    system = _System(timeout_seconds=60, clock=clock)
    source = workspace / "notes.txt"
    source.write_text("content")

    response = system.orchestrator.handle_request("delete file notes.txt")
    clock.now = _START + timedelta(seconds=60)

    with pytest.raises(ApprovalError):
        system.approvals.approve(response.approval_request.request_id)

    assert source.exists()
    assert source.read_text() == "content"
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()


def test_delete_requires_no_direct_bypass_around_approval_manager(
    system: _System, workspace: Path
) -> None:
    """A delete request that is never approved or declined at all must
    never quarantine anything - there is no path from handle_request()
    to a moved file that skips ApprovalManager entirely."""
    source = workspace / "notes.txt"
    source.write_text("content")

    response = system.orchestrator.handle_request("delete file notes.txt")

    assert response.requires_confirmation is True
    assert response.success is False
    assert source.exists()
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()


def test_missing_file_delete_input_fails_cleanly(
    system: _System, workspace: Path
) -> None:
    response = system.orchestrator.handle_request(
        "delete file does_not_exist.txt"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()


def test_directory_delete_source_fails_cleanly(
    system: _System, workspace: Path
) -> None:
    a_directory = workspace / "a_folder"
    a_directory.mkdir()

    response = system.orchestrator.handle_request("delete file a_folder")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert a_directory.exists()


def test_already_quarantined_source_fails_cleanly(
    system: _System, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    already_quarantined = quarantine_dir / "already_here.txt"
    already_quarantined.write_text("already quarantined")

    response = system.orchestrator.handle_request(
        f"delete file {_QUARANTINE_DIR_NAME}/already_here.txt"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert already_quarantined.exists()


def test_delete_decisions_are_audited(system: _System, workspace: Path) -> None:
    (workspace / "notes.txt").write_text("content")
    response = system.orchestrator.handle_request("delete file notes.txt")
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    approval_events = system.logger.approval_events()
    assert len(approval_events) == 1
    assert "outcome=approved" in str(approval_events[0]["detail"])


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