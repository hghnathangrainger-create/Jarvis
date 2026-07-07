"""
test_cli.py

Unit tests for the Jarvis CLI (ui/cli.py) and the main entry point.

The CLI's formatting and exit-detection logic are pure functions and are
tested directly. The interactive loop is tested with injected input and output
callables, so no real terminal is needed. The main module is imported to
confirm the entry point is intact.

Run with:
    pytest tests/unit/test_cli.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import (
    JarvisCLI,
    format_response,
    is_exit_command,
    status_for,
    strip_prompt_prefix,
)


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeMemory:
    def __init__(self) -> None:
        self._data: list[MemoryRecord] = []

    def add(self, content: str) -> None:
        self._data.append(
            MemoryRecord(
                id=len(self._data) + 1,
                content=content,
                source="test",
                session_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )

    def list_recent(self, limit: int = 10) -> list[MemoryRecord]:
        return list(reversed(self._data))[:limit]

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        term = query.lower()
        return [r for r in reversed(self._data) if term in r.content.lower()][:limit]


@pytest.fixture()
def orchestrator() -> JarvisOrchestrator:
    memory = _FakeMemory()
    memory.add("Nathan likes Python.")
    security = SecurityManager()
    planner = Planner(security)
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))  # type: ignore[arg-type]
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=planner,
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )


# --- Exit command detection --------------------------------------------------


@pytest.mark.parametrize("command", ["exit", "quit", "bye", "EXIT", "  Quit  ", "BYE"])
def test_exit_commands_are_detected(command: str) -> None:
    assert is_exit_command(command) is True


@pytest.mark.parametrize("command", ["hello", "exits", "goodbye", "quitter", ""])
def test_non_exit_commands_are_not_detected(command: str) -> None:
    assert is_exit_command(command) is False


# --- Response formatting ------------------------------------------------------


def test_format_ok_response() -> None:
    response = JarvisResponse(success=True, message="Here is the info")
    assert status_for(response) == "OK"
    rendered = format_response(response)
    assert "[OK]" in rendered
    assert "Here is the info" in rendered


def test_format_approval_response() -> None:
    response = JarvisResponse(
        success=False, message="needs your ok", requires_confirmation=True
    )
    assert status_for(response) == "NEEDS APPROVAL"
    assert "[NEEDS APPROVAL]" in format_response(response)


def test_format_blocked_response() -> None:
    response = JarvisResponse(success=False, message="too dangerous", blocked=True)
    assert status_for(response) == "BLOCKED"
    assert "[BLOCKED]" in format_response(response)


def test_format_not_handled_response() -> None:
    response = JarvisResponse(success=False, message="cannot do that yet")
    assert status_for(response) == "NOT HANDLED"
    assert "[NOT HANDLED]" in format_response(response)


def test_format_failed_response() -> None:
    """A tool that ran but errored is reported as FAILED, not NOT HANDLED."""
    result = ToolResult(
        tool_name="file_read", success=False, error="Path does not exist"
    )
    response = JarvisResponse(
        success=False, message="Path does not exist", tool_result=result
    )
    assert status_for(response) == "FAILED"
    assert "[FAILED]" in format_response(response)


def test_blocked_wins_over_failed() -> None:
    """A blocked response stays BLOCKED even if it carries a tool result."""
    result = ToolResult(
        tool_name="danger", success=False, error="blocked", blocked=True
    )
    response = JarvisResponse(
        success=False, message="blocked", blocked=True, tool_result=result
    )
    assert status_for(response) == "BLOCKED"


def test_needs_approval_wins_over_failed() -> None:
    """A needs-approval response stays NEEDS APPROVAL even with a tool result."""
    result = ToolResult(
        tool_name="send",
        success=False,
        error="confirm",
        requires_confirmation=True,
    )
    response = JarvisResponse(
        success=False,
        message="confirm",
        requires_confirmation=True,
        tool_result=result,
    )
    assert status_for(response) == "NEEDS APPROVAL"


def test_all_five_status_labels_are_distinct() -> None:
    """The five outcome labels are all different, so they are unambiguous."""
    labels = {
        status_for(JarvisResponse(success=True, message="x")),
        status_for(
            JarvisResponse(success=False, message="x", requires_confirmation=True)
        ),
        status_for(JarvisResponse(success=False, message="x", blocked=True)),
        status_for(
            JarvisResponse(
                success=False,
                message="x",
                tool_result=ToolResult(tool_name="t", success=False, error="e"),
            )
        ),
        status_for(JarvisResponse(success=False, message="x")),
    }
    assert labels == {"OK", "NEEDS APPROVAL", "BLOCKED", "FAILED", "NOT HANDLED"}


# --- Interactive loop with injected I/O --------------------------------------


def test_cli_prints_banner_and_handles_requests(
    orchestrator: JarvisOrchestrator,
) -> None:
    scripted = iter(["echo hello", "format drive C", "exit"])
    outputs: list[str] = []

    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()

    joined = "\n".join(outputs)
    assert "Jarvis Online." in joined
    assert "[OK] echo hello" in joined
    assert "[BLOCKED]" in joined
    assert "Goodbye" in joined


def test_cli_exits_on_exit_command(orchestrator: JarvisOrchestrator) -> None:
    scripted = iter(["bye"])
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    assert any("Goodbye" in line for line in outputs)


def test_cli_handles_eof_cleanly(orchestrator: JarvisOrchestrator) -> None:
    def _eof(_prompt: str) -> str:
        raise EOFError

    outputs: list[str] = []
    cli = JarvisCLI(orchestrator, input_fn=_eof, output_fn=outputs.append)
    cli.run()
    assert any("Goodbye" in line for line in outputs)


def test_cli_ignores_blank_lines(orchestrator: JarvisOrchestrator) -> None:
    scripted = iter(["", "   ", "exit"])
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    # Blank lines produce no jarvis> output; only banner + goodbye appear.
    assert not any(line.startswith("jarvis>") for line in outputs)


# --- Prompt-prefix stripping (pasted "you>" handling) ------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("you> exit", "exit"),
        ("you> show me system info", "show me system info"),
        ("you>exit", "exit"),
        ("YOU> exit", "exit"),
        ("  you>  echo hi  ", "echo hi"),
        ("jarvis> hello", "hello"),
        ("exit", "exit"),
        ("you are great", "you are great"),
        ("tell me about you> stuff", "tell me about you> stuff"),
    ],
)
def test_strip_prompt_prefix(raw: str, expected: str) -> None:
    assert strip_prompt_prefix(raw) == expected


def test_pasted_prompt_exit_still_exits(orchestrator: JarvisOrchestrator) -> None:
    """'you> exit' should exit, not be processed as a request."""
    scripted = iter(["you> exit"])
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    assert any("Goodbye" in line for line in outputs)
    assert not any(line.startswith("jarvis>") for line in outputs)


def test_pasted_prompt_request_is_processed(
    orchestrator: JarvisOrchestrator,
) -> None:
    """'you> echo hi' should behave exactly like 'echo hi'."""
    scripted = iter(["you> echo hi", "exit"])
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    assert any("[OK] echo hi" in line for line in outputs)


def test_banner_warns_against_typing_prompt(
    orchestrator: JarvisOrchestrator,
) -> None:
    """The startup banner tells the user not to type the prompt text."""
    scripted = iter(["exit"])
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    banner = "\n".join(outputs)
    assert "Do not type" in banner
    assert "you>" in banner


# --- Entry point -------------------------------------------------------------


def test_main_entry_point_imports() -> None:
    """The main module imports and exposes a callable entry point."""
    import main

    assert callable(main.main)
    assert callable(main.build_orchestrator)   