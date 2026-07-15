"""
test_tools.py

Unit tests for the Jarvis Tool Manager:
    tools/base_tool.py
    tools/registry.py
    tools/executor.py
    tools/builtin/echo_tool.py
    tools/builtin/info_tool.py
    tools/builtin/memory_tool.py

The executor is exercised with the real Security Manager and a spy logger, so
the GREEN/YELLOW/RED safety gate is tested end to end. No database, AI, or
network is required.

Run with:
    pytest tests/unit/test_tools.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from memory.episodic_memory import MemoryRecord
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    """Captures emitted events instead of writing to the audit log."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeMemory:
    """In-memory stand-in for the Memory Manager (read-only methods)."""

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

    def count(self) -> int:
        return len(self._data)


class _RedTool(BaseTool):
    """A tool whose action classifies RED; its run must never be reached."""

    @property
    def name(self) -> str:
        return "danger"

    @property
    def description(self) -> str:
        return "Test tool with a dangerous action."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("A RED tool must never run.")


class _YellowTool(BaseTool):
    """A tool whose action classifies YELLOW; its run must not be reached."""

    @property
    def name(self) -> str:
        return "writer"

    @property
    def description(self) -> str:
        return "Test tool with a sensitive action."

    def action_for(self, request: ToolRequest) -> str:
        return "write file"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("A YELLOW tool must not run without confirmation.")


# --- Fixtures ----------------------------------------------------------------


@pytest.fixture()
def memory() -> _FakeMemory:
    mem = _FakeMemory()
    mem.add("Nathan likes Python.")
    mem.add("Nathan is learning trading.")
    return mem


@pytest.fixture()
def registry(memory: _FakeMemory) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_tool(EchoTool())
    reg.register_tool(InfoTool())
    reg.register_tool(MemoryTool(memory))  # type: ignore[arg-type]
    reg.register_tool(_RedTool())
    reg.register_tool(_YellowTool())
    return reg


@pytest.fixture()
def logger() -> _SpyLogger:
    return _SpyLogger()


@pytest.fixture()
def executor(registry: ToolRegistry, logger: _SpyLogger) -> ToolExecutor:
    return ToolExecutor(
        registry=registry,
        security_manager=SecurityManager(),
        logger=logger,  # type: ignore[arg-type]
    )


# --- Registry ----------------------------------------------------------------


def test_tools_are_registered(registry: ToolRegistry) -> None:
    assert registry.list_tool_names() == sorted(
        ["echo", "info", "memory", "danger", "writer"]
    )


def test_duplicate_registration_rejected() -> None:
    reg = ToolRegistry()
    reg.register_tool(EchoTool())
    with pytest.raises(ValueError):
        reg.register_tool(EchoTool())


def test_get_unknown_tool_returns_none() -> None:
    reg = ToolRegistry()
    assert reg.get_tool("missing") is None


# --- Executor: unknown tool --------------------------------------------------


def test_unknown_tool_returns_failed_result(executor: ToolExecutor) -> None:
    result = executor.execute("nonexistent")
    assert result.success is False
    assert result.error is not None


# --- Executor: GREEN ---------------------------------------------------------


def test_green_echo_runs(executor: ToolExecutor) -> None:
    result = executor.execute("echo", {"text": "hello"})
    assert result.success is True
    assert result.output == "hello"


def test_green_info_runs(executor: ToolExecutor) -> None:
    result = executor.execute("info")
    assert result.success is True
    assert "Jarvis" in result.output


# --- Executor: YELLOW --------------------------------------------------------


def test_yellow_action_requires_confirmation(executor: ToolExecutor) -> None:
    result = executor.execute("writer")
    assert result.success is False
    assert result.requires_confirmation is True
    assert result.blocked is False


# --- Executor: RED -----------------------------------------------------------


def test_red_action_is_blocked(executor: ToolExecutor) -> None:
    result = executor.execute("danger")
    assert result.success is False
    assert result.blocked is True
    assert result.requires_confirmation is False


# --- Memory tool -------------------------------------------------------------


def test_memory_tool_list(executor: ToolExecutor) -> None:
    result = executor.execute("memory", {"operation": "list"})
    assert result.success is True
    assert "Nathan" in result.output


def test_memory_tool_search(executor: ToolExecutor) -> None:
    result = executor.execute("memory", {"operation": "search", "query": "trading"})
    assert result.success is True
    assert "trading" in result.output.lower()


def test_memory_tool_search_without_query_fails(executor: ToolExecutor) -> None:
    result = executor.execute("memory", {"operation": "search"})
    assert result.success is False
    assert result.error is not None


# --- Logging -----------------------------------------------------------------


def test_every_execution_is_logged(
    executor: ToolExecutor, logger: _SpyLogger
) -> None:
    executor.execute("echo", {"text": "a"})
    executor.execute("danger")
    executor.execute("writer")
    assert len(logger.events) == 3


# --- Tool isolation ----------------------------------------------------------


def test_misbehaving_tool_does_not_crash_executor(executor: ToolExecutor) -> None:
    """A tool that raises is caught and reported as a failed result."""
    result = executor.execute("echo", {})  # missing 'text' -> graceful failure
    assert result.success is False
    assert result.error is not None