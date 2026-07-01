"""
test_approval_end_to_end.py

End-to-end integration tests for the Jarvis approval flow (Phase 2, Step 9).

Unlike the unit tests, these wire the real components together - Security
Manager, Tool Registry, Tool Executor, Approval Manager, and the real event
logging interface (via a spy) - and trace a complete YELLOW action through its
full journey: request -> decision -> execution or cancellation.

They prove the whole flow works as one system:
    - GREEN runs automatically.
    - YELLOW creates a request and does not run until approved.
    - An approved decision lets the tool run through the executor gate.
    - A declined decision prevents execution.
    - RED is never unlocked by an approval.
    - Every decision is recorded in the audit log.

Run with:
    pytest tests/integration/test_approval_end_to_end.py
"""

from __future__ import annotations

import pytest

from approval.approval_manager import ApprovalManager
from config.constants import EventOutcome, SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Spy logger --------------------------------------------------------------


class _SpyLogger:
    """Captures emitted events, standing in for the real EventLogger."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))

    def approval_events(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action_type") == "approval_decision"]

    def tool_events(self) -> list[dict[str, object]]:
        return [e for e in self.events if e.get("action_type") == "tool_call"]


# --- Tools used in the scenarios ---------------------------------------------


class _YellowSendTool(BaseTool):
    """A tool whose action classifies YELLOW; records whether it ran."""

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
        return ToolResult(tool_name=self.name, success=True, output="message sent")


class _RedDeleteTool(BaseTool):
    """A tool whose action classifies RED; its run must never be reached."""

    def __init__(self) -> None:
        self.ran = False

    @property
    def name(self) -> str:
        return "wipe"

    @property
    def description(self) -> str:
        return "A dangerous (RED) tool that must never run."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        self.ran = True
        raise AssertionError("A RED action must never run.")


# --- Fixtures ----------------------------------------------------------------


class _System:
    """A small container bundling the wired-together components for a test."""

    def __init__(self) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.send = _YellowSendTool()
        self.wipe = _RedDeleteTool()
        self.registry.register_tool(EchoTool())
        self.registry.register_tool(self.send)
        self.registry.register_tool(self.wipe)
        self.executor = ToolExecutor(
            registry=self.registry,
            security_manager=self.security,
            logger=self.logger,  # type: ignore[arg-type]
        )
        self.approvals = ApprovalManager(audit_logger=self.logger)  # type: ignore[arg-type]


@pytest.fixture()
def system() -> _System:
    return _System()


# --- Scenario 1: GREEN runs automatically ------------------------------------


def test_green_runs_without_approval(system: _System) -> None:
    result = system.executor.execute("echo", {"text": "hi"})
    assert result.success is True
    assert result.output == "hi"


# --- Scenario 2 + 3: YELLOW creates a request and does not run yet ------------


def test_yellow_creates_request_and_does_not_run(system: _System) -> None:
    # The Core would create the approval request when it sees a YELLOW action.
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )
    # It is pending, and the tool has not run.
    assert system.approvals.has_pending(request.request_id)
    assert system.send.ran is False

    # Executing without an approval decision withholds the action.
    result = system.executor.execute("send")
    assert result.requires_confirmation is True
    assert system.send.ran is False


# --- Scenario 4: approved decision lets the tool run -------------------------


def test_approved_decision_runs_the_tool(system: _System) -> None:
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )
    decision = system.approvals.approve(request.request_id, decided_by="user")

    result = system.executor.execute("send", approval_decision=decision)

    assert result.success is True
    assert result.output == "message sent"
    assert system.send.ran is True


# --- Scenario 5: declined decision prevents execution ------------------------


def test_declined_decision_prevents_execution(system: _System) -> None:
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )
    decision = system.approvals.decline(request.request_id, decided_by="user")

    result = system.executor.execute("send", approval_decision=decision)

    assert result.success is False
    assert result.requires_confirmation is True
    assert system.send.ran is False


# --- Scenario 6: RED stays blocked even with an approved decision ------------


def test_red_stays_blocked_even_when_approved(system: _System) -> None:
    # A YELLOW approval is fabricated and pointed at a RED tool. The executor
    # must still block it, because the Security Manager classifies it RED.
    request = system.approvals.create_request(
        action="format drive",
        reason="A mistaken approval attempt.",
        security_tier=SecurityTier.YELLOW,
    )
    decision = system.approvals.approve(request.request_id, decided_by="user")

    result = system.executor.execute("wipe", approval_decision=decision)

    assert result.blocked is True
    assert result.success is False
    assert system.wipe.ran is False


# --- Scenario 7 + 8: audit logging records decisions -------------------------


def test_audit_records_approved_decision(system: _System) -> None:
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="communicates on your behalf",
        security_tier=SecurityTier.YELLOW,
    )
    system.approvals.approve(request.request_id, decided_by="user", reason="ok")

    approvals = system.logger.approval_events()
    assert len(approvals) == 1
    assert approvals[0]["outcome"] is EventOutcome.SUCCESS
    assert "outcome=approved" in str(approvals[0]["detail"])


def test_audit_records_declined_decision(system: _System) -> None:
    request = system.approvals.create_request(
        action="install a package",
        reason="changes the system",
        security_tier=SecurityTier.YELLOW,
    )
    system.approvals.decline(request.request_id, decided_by="user")

    approvals = system.logger.approval_events()
    assert len(approvals) == 1
    assert approvals[0]["outcome"] is EventOutcome.BLOCKED
    assert "outcome=declined" in str(approvals[0]["detail"])


# --- Scenario 9: request_id preserved in ToolResult metadata -----------------


def test_approval_request_id_in_result_metadata(system: _System) -> None:
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="communicates on your behalf",
        security_tier=SecurityTier.YELLOW,
    )
    decision = system.approvals.approve(request.request_id, decided_by="user")

    result = system.executor.execute("send", approval_decision=decision)

    assert result.metadata.get("approval_request_id") == decision.request_id


# --- Full journey: request -> approve -> run, all recorded -------------------


def test_full_approved_journey_is_consistent(system: _System) -> None:
    """One coherent walk through the whole approved path."""
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="communicates on your behalf",
        security_tier=SecurityTier.YELLOW,
        session_id=7,
    )
    assert system.approvals.has_pending(request.request_id)
    assert system.send.ran is False

    decision = system.approvals.approve(request.request_id, decided_by="user")
    assert decision.is_approved is True
    assert not system.approvals.has_pending(request.request_id)
    assert system.approvals.get_decision(request.request_id).is_approved is True

    result = system.executor.execute(
        "send", approval_decision=decision, session_id=7
    )
    assert result.success is True
    assert system.send.ran is True
    assert result.metadata.get("approval_request_id") == request.request_id

    # Both an approval event and a successful tool event were logged.
    assert len(system.logger.approval_events()) == 1
    success_tool_events = [
        e
        for e in system.logger.tool_events()
        if "success=True" in str(e.get("detail", ""))
    ]
    assert len(success_tool_events) == 1


def test_full_declined_journey_is_consistent(system: _System) -> None:
    """One coherent walk through the whole declined path."""
    request = system.approvals.create_request(
        action="send email to Alex",
        reason="communicates on your behalf",
        security_tier=SecurityTier.YELLOW,
    )
    decision = system.approvals.decline(request.request_id, decided_by="user")
    assert decision.is_declined is True

    result = system.executor.execute("send", approval_decision=decision)
    assert result.success is False
    assert system.send.ran is False

    # The decline was recorded; no successful tool execution was logged.
    assert len(system.logger.approval_events()) == 1
    success_tool_events = [
        e
        for e in system.logger.tool_events()
        if "success=True" in str(e.get("detail", ""))
    ]
    assert success_tool_events == []