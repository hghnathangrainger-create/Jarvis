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

from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import (
    JarvisCLI,
    format_response,
    is_exit_command,
    status_for,
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
    return JarvisOrchestrator(planner=planner, executor=executor, registry=registry)


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


def test_format_confirmation_response() -> None:
    response = JarvisResponse(
        success=False, message="needs your ok", requires_confirmation=True
    )
    assert status_for(response) == "NEEDS CONFIRMATION"
    assert "[NEEDS CONFIRMATION]" in format_response(response)


def test_format_blocked_response() -> None:
    response = JarvisResponse(success=False, message="too dangerous", blocked=True)
    assert status_for(response) == "BLOCKED"
    assert "[BLOCKED]" in format_response(response)


def test_format_not_handled_response() -> None:
    response = JarvisResponse(success=False, message="cannot do that yet")
    assert status_for(response) == "NOT HANDLED"
    assert "[NOT HANDLED]" in format_response(response)


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


# --- Entry point -------------------------------------------------------------


def test_main_entry_point_imports() -> None:
    """The main module imports and exposes a callable entry point."""
    import main

    assert callable(main.main)
    assert callable(main.build_orchestrator)