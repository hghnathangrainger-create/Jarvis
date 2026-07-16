"""
test_cli_end_to_end.py

End-to-end integration tests for the live Jarvis CLI (Phase 3, Step 9).

These drive the real CLI with scripted input and captured output - no real
terminal - and wire together the real Security Manager, Tool Registry, Tool
Executor, Approval Manager, and built-in tools. They prove the complete user
journeys work through the actual interface:

    - GREEN commands run and show [OK] with no approval prompt.
    - YELLOW commands show the approval prompt; approving runs the action (or
      clearly reports there is no runnable tool), declining cancels it.
    - RED commands show [BLOCKED] with no approval prompt.
    - Exit commands end the session cleanly.

Run with:
    pytest tests/integration/test_cli_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from approval.approval_manager import ApprovalManager
from config.constants import SecurityTier
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import (
    EchoTool,
    FileListTool,
    FileReadTool,
    InfoTool,
    MemoryTool,
)
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    """Captures emitted events, standing in for the real EventLogger."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeMemory:
    def list_recent(self, limit: int = 10):
        return []

    def search(self, query: str, limit: int = 10):
        return []


class _SendTool(BaseTool):
    """A registered tool whose action classifies YELLOW; records if it ran."""

    def __init__(self) -> None:
        self.ran = False

    @property
    def name(self) -> str:
        return "send"

    @property
    def description(self) -> str:
        return "A sensitive (YELLOW) tool that pretends to send a message."

    def action_for(self, request: ToolRequest) -> str:
        return "send email"

    def run(self, request: ToolRequest) -> ToolResult:
        self.ran = True
        return ToolResult(tool_name=self.name, success=True, output="Message sent!")


# --- Fixtures ----------------------------------------------------------------


class _System:
    """Bundles the real, wired-together components plus the YELLOW send tool."""

    def __init__(self) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.send = _SendTool()
        self.registry.register_tool(EchoTool())
        self.registry.register_tool(InfoTool())
        self.registry.register_tool(MemoryTool(_FakeMemory()))  # type: ignore[arg-type]
        self.registry.register_tool(FileListTool())
        self.registry.register_tool(FileReadTool())
        self.registry.register_tool(self.send)
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
    """Create a small project workspace and switch into it."""
    (tmp_path / "README.md").write_text("# Jarvis\nThe project README.\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("notes")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _drive(
    system: _System, inputs: list[str], *, force_send: bool = False
) -> str:
    """Run the real CLI with scripted input; return the joined output.

    When force_send is True, a request containing 'send' returns a crafted
    YELLOW response backed by the registered send tool, so the approve-and-run
    journey can be exercised (the built-in matcher does not route to it).
    """
    outputs: list[str] = []
    scripted = iter(inputs)

    cli = JarvisCLI(
        system.orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )

    if force_send:
        original = system.orchestrator.handle_request

        def _handle(text: str) -> JarvisResponse:
            if "send" in text.lower():
                request = system.approvals.create_request(
                    action="send email to Alex",
                    reason="Sending an email communicates on your behalf.",
                    security_tier=SecurityTier.YELLOW,
                )
                return JarvisResponse(
                    success=False,
                    message="This action requires your confirmation.",
                    requires_confirmation=True,
                    approval_request=request,
                    tool_name="send",
                    tool_input={},
                )
            return original(text)

        system.orchestrator.handle_request = _handle  # type: ignore[method-assign]

    cli.run()
    return "\n".join(outputs)


# --- Scenario 1: GREEN command journey ---------------------------------------


def test_green_command_journey(system: _System, workspace: Path) -> None:
    output = _drive(system, ["show project files", "exit"])
    assert "[OK]" in output
    assert "README.md" in output
    assert "approval required" not in output.lower()


def test_file_list_journey_respects_custom_limit(
    system: _System, workspace: Path
) -> None:
    """Phase 83, Batch 1: the CLI's "limit <N>" grammar must actually
    reach FileListTool through the real CommandRouter -> ToolExecutor
    path and change how many entries are shown - not just be parsed and
    dropped."""
    for i in range(5):
        (workspace / f"extra_{i}.txt").write_text("x")
    output = _drive(system, ["list files limit 2", "exit"])
    assert "[OK]" in output
    assert "showing 2 of 7 entries; more entries exist" in output


# --- Scenario 2: file read journey -------------------------------------------


def test_file_read_journey(system: _System, workspace: Path) -> None:
    output = _drive(system, ["read readme", "exit"])
    assert "[OK]" in output
    assert "The project README" in output
    assert "approval required" not in output.lower()


def test_file_read_journey_respects_custom_max_chars(
    system: _System, workspace: Path
) -> None:
    """Phase 82: the CLI's "up to <N> chars" grammar must actually reach
    FileReadTool through the real CommandRouter -> ToolExecutor path and
    change its truncation point - not just be parsed and dropped."""
    (workspace / "long.txt").write_text("0123456789abcdefghij")
    output = _drive(system, ["read file long.txt up to 10 chars", "exit"])
    assert "[OK]" in output
    assert "0123456789" in output
    assert "abcdefghij" not in output
    assert "showing the first 10 characters" in output


# --- Scenario 3: YELLOW approve journey (backed tool runs) -------------------


def test_yellow_approve_journey_executes(system: _System, workspace: Path) -> None:
    output = _drive(
        system, ["send a message", "yes", "exit"], force_send=True
    )
    assert "approval required" in output.lower()
    assert "[APPROVED]" in output
    assert "Message sent!" in output
    assert system.send.ran is True


def test_yellow_approve_journey_no_backed_tool(
    system: _System, workspace: Path
) -> None:
    # "send email to Alex" has no matching tool, so approval is recorded but
    # the CLI reports there is nothing to run.
    output = _drive(system, ["send email to Alex", "yes", "exit"])
    assert "approval required" in output.lower()
    assert "[APPROVED]" in output
    assert "no runnable tool" in output.lower()


# --- Scenario 4: YELLOW decline journey --------------------------------------


def test_yellow_decline_journey(system: _System, workspace: Path) -> None:
    output = _drive(
        system, ["send a message", "no", "exit"], force_send=True
    )
    assert "approval required" in output.lower()
    assert "[DECLINED]" in output
    assert "Message sent!" not in output
    assert system.send.ran is False


# --- Scenario 5: RED blocked journey -----------------------------------------


def test_red_blocked_journey(system: _System, workspace: Path) -> None:
    output = _drive(system, ["format drive C", "exit"])
    assert "[BLOCKED]" in output
    assert "approval required" not in output.lower()


# --- Scenario 6: exit journey ------------------------------------------------


@pytest.mark.parametrize("word", ["exit", "quit", "bye"])
def test_exit_journey(system: _System, workspace: Path, word: str) -> None:
    output = _drive(system, [word])
    assert "Goodbye" in output


# --- Output collection and input handling ------------------------------------


def test_output_is_collected_through_injected_output_fn(
    system: _System, workspace: Path
) -> None:
    outputs: list[str] = []
    scripted = iter(["show project files", "exit"])
    cli = JarvisCLI(
        system.orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    # The banner and at least one response line were collected.
    assert any("Jarvis Online." in line for line in outputs)
    assert any("[OK]" in line for line in outputs)


def test_eof_ends_cleanly(system: _System, workspace: Path) -> None:
    def _eof(_prompt: str) -> str:
        raise EOFError

    outputs: list[str] = []
    cli = JarvisCLI(
        system.orchestrator, input_fn=_eof, output_fn=outputs.append
    )
    cli.run()
    assert any("Goodbye" in line for line in outputs)


# --- Full journey consistency ------------------------------------------------


def test_full_approved_journey_is_recorded(
    system: _System, workspace: Path
) -> None:
    _drive(system, ["send a message", "yes", "exit"], force_send=True)
    decisions = system.approvals.list_decisions()
    assert len(decisions) == 1
    assert decisions[0].is_approved is True
    # The approval decision was written to the audit log.
    approval_events = [
        e for e in system.logger.events if e.get("action_type") == "approval_decision"
    ]
    assert len(approval_events) == 1


def test_full_declined_journey_is_recorded(
    system: _System, workspace: Path
) -> None:
    _drive(system, ["send a message", "no", "exit"], force_send=True)
    decisions = system.approvals.list_decisions()
    assert len(decisions) == 1
    assert decisions[0].is_declined is True
    assert system.send.ran is False