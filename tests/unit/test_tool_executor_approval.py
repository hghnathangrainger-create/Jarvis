"""
test_tool_executor_approval.py

Unit tests for the Jarvis ToolExecutor approved-YELLOW path (Phase 2, Step 5).

These tests confirm that a YELLOW action runs only when an approved
ApprovalDecision is supplied, that a declined or missing decision withholds it,
and that no approval can ever run a RED action. The executor is exercised with
the real Security Manager and a spy logger.

Run with:
    pytest tests/unit/test_tool_executor_approval.py
"""

from __future__ import annotations

import pytest

from approval.approval_models import ApprovalDecision, ApprovalRequest
from config.constants import SecurityTier
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from security.security_manager import SecurityManager


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _YellowTool(BaseTool):
    """A tool whose action classifies YELLOW and records whether it ran."""

    def __init__(self) -> None:
        self.ran = False

    @property
    def name(self) -> str:
        return "send"

    @property
    def description(self) -> str:
        return "A tool with a sensitive (YELLOW) action."

    def action_for(self, request: ToolRequest) -> str:
        return "send email"

    def run(self, request: ToolRequest) -> ToolResult:
        self.ran = True
        return ToolResult(tool_name=self.name, success=True, output="sent!")


class _RedTool(BaseTool):
    """A tool whose action classifies RED; its run must never be reached."""

    def __init__(self) -> None:
        self.ran = False

    @property
    def name(self) -> str:
        return "danger"

    @property
    def description(self) -> str:
        return "A tool with a dangerous (RED) action."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        self.ran = True
        raise AssertionError("A RED action must never run.")


# --- Helpers -----------------------------------------------------------------


def _approved(action: str = "send email") -> ApprovalDecision:
    request = ApprovalRequest(
        action=action, reason="approved", security_tier=SecurityTier.YELLOW
    )
    return request.decide(approved=True, decided_by="user")


def _declined(action: str = "send email") -> ApprovalDecision:
    request = ApprovalRequest(
        action=action, reason="declined", security_tier=SecurityTier.YELLOW
    )
    return request.decide(approved=False, decided_by="user")


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_tool(EchoTool())
    reg.register_tool(_YellowTool())
    reg.register_tool(_RedTool())
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


def _tool(registry: ToolRegistry, name: str):
    return registry.get_tool(name)


# --- GREEN -------------------------------------------------------------------


def test_green_runs_without_approval(executor: ToolExecutor) -> None:
    result = executor.execute("echo", {"text": "hi"})
    assert result.success is True
    assert result.output == "hi"


def test_green_runs_even_if_approval_supplied(executor: ToolExecutor) -> None:
    result = executor.execute("echo", {"text": "hi"}, approval_decision=_approved())
    assert result.success is True


# --- YELLOW ------------------------------------------------------------------


def test_yellow_without_approval_does_not_run(
    executor: ToolExecutor, registry: ToolRegistry
) -> None:
    result = executor.execute("send")
    assert result.success is False
    assert result.requires_confirmation is True
    assert _tool(registry, "send").ran is False


def test_yellow_with_approved_decision_runs(
    executor: ToolExecutor, registry: ToolRegistry
) -> None:
    result = executor.execute("send", approval_decision=_approved())
    assert result.success is True
    assert result.output == "sent!"
    assert _tool(registry, "send").ran is True


def test_yellow_with_declined_decision_does_not_run(
    executor: ToolExecutor, registry: ToolRegistry
) -> None:
    result = executor.execute("send", approval_decision=_declined())
    assert result.success is False
    assert result.requires_confirmation is True
    assert _tool(registry, "send").ran is False


# --- RED ---------------------------------------------------------------------


def test_red_with_approved_decision_stays_blocked(
    executor: ToolExecutor, registry: ToolRegistry
) -> None:
    result = executor.execute("danger", approval_decision=_approved("format drive"))
    assert result.success is False
    assert result.blocked is True
    assert _tool(registry, "danger").ran is False


# --- Unchanged behaviours ----------------------------------------------------


def test_unknown_tool_unchanged(executor: ToolExecutor) -> None:
    result = executor.execute("nonexistent")
    assert result.success is False
    assert result.error is not None


def test_misbehaving_tool_unchanged(executor: ToolExecutor) -> None:
    result = executor.execute("echo", {})  # missing 'text' -> graceful failure
    assert result.success is False
    assert result.error is not None


# --- Logging and metadata ----------------------------------------------------


def test_approved_yellow_execution_is_logged(
    executor: ToolExecutor, logger: _SpyLogger
) -> None:
    executor.execute("send", approval_decision=_approved())
    success_events = [
        event
        for event in logger.events
        if "tool=send" in str(event.get("detail", ""))
        and "success=True" in str(event.get("detail", ""))
    ]
    assert len(success_events) == 1
    assert "approved_by=user" in str(success_events[0]["detail"])


def test_approval_request_id_recorded_in_metadata(executor: ToolExecutor) -> None:
    decision = _approved()
    result = executor.execute("send", approval_decision=decision)
    assert result.metadata.get("approval_request_id") == decision.request_id