"""
test_cli_approval.py

Unit tests for the live CLI approval integration (ui/cli.py, Phase 3 Step 2).

These tests drive the interactive CLI with scripted input and capture its
output, so no real terminal is needed. They confirm that a YELLOW response
triggers the approval prompt, that approving and declining show clear feedback
and are recorded, and that GREEN and RED responses do not trigger the prompt.

Run with:
    pytest tests/unit/test_cli_approval.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier
from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI, format_decision


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


def _build() -> JarvisOrchestrator:
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


def _run_cli(inputs: list[str]) -> tuple[JarvisOrchestrator, str]:
    """Run the CLI with scripted inputs; return the orchestrator and output."""
    orchestrator = _build()
    scripted = iter(inputs)
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    return orchestrator, "\n".join(outputs)


# --- A YELLOW tool used to test approved execution ---------------------------


class _SendTool(BaseTool):
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
        return ToolResult(tool_name=self.name, success=True, output="Message sent!")


class _WipeTool(BaseTool):
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


def _build_with_tool(tool: BaseTool) -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(tool)
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=Planner(security), executor=executor, registry=registry
    )


def _yellow_tool_response(
    orchestrator: JarvisOrchestrator, tool_name: str
) -> JarvisResponse:
    """Build the kind of response the Core returns for a YELLOW tool action."""
    request = orchestrator.approvals.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )
    return JarvisResponse(
        success=False,
        message="This action requires your confirmation.",
        requires_confirmation=True,
        approval_request=request,
        tool_name=tool_name,
        tool_input={},
    )


# --- Approval prompt is triggered for YELLOW ---------------------------------


def test_yellow_response_triggers_prompt_and_approve() -> None:
    orchestrator, output = _run_cli(["send email to Alex", "yes", "exit"])
    assert "approval required" in output.lower()
    assert "[APPROVED]" in output


def test_yellow_response_triggers_prompt_and_decline() -> None:
    orchestrator, output = _run_cli(["send email to Alex", "no", "exit"])
    assert "approval required" in output.lower()
    assert "[DECLINED]" in output
    assert "cancelled" in output.lower()


def test_invalid_then_valid_approval_input_reprompts() -> None:
    _orchestrator, output = _run_cli(
        ["send email to Alex", "maybe", "huh", "yes", "exit"]
    )
    assert "[APPROVED]" in output


# --- GREEN and RED do not trigger the prompt ---------------------------------


def test_green_response_does_not_trigger_prompt() -> None:
    _orchestrator, output = _run_cli(["show me system info", "exit"])
    assert "approval required" not in output.lower()
    assert "[OK]" in output


def test_red_response_does_not_trigger_prompt() -> None:
    _orchestrator, output = _run_cli(["format drive C", "exit"])
    assert "approval required" not in output.lower()
    assert "[BLOCKED]" in output


# --- Decisions are recorded --------------------------------------------------


def test_approval_is_recorded_in_manager() -> None:
    orchestrator, _output = _run_cli(["send email to Alex", "yes", "exit"])
    decisions = orchestrator.approvals.list_decisions()
    assert len(decisions) == 1
    assert decisions[0].is_approved is True


def test_decline_is_recorded_in_manager() -> None:
    orchestrator, _output = _run_cli(["send email to Alex", "no", "exit"])
    decisions = orchestrator.approvals.list_decisions()
    assert len(decisions) == 1
    assert decisions[0].is_declined is True


# --- Exit commands still work ------------------------------------------------


@pytest.mark.parametrize("word", ["exit", "quit", "bye"])
def test_exit_commands_still_work(word: str) -> None:
    _orchestrator, output = _run_cli([word])
    assert "Goodbye" in output


# --- format_decision pure function -------------------------------------------


def test_format_decision_approved() -> None:
    request = ApprovalRequest(
        action="send email", reason="x", security_tier=SecurityTier.YELLOW
    )
    decision = request.decide(approved=True, decided_by="user")
    assert "[APPROVED]" in format_decision(decision)


def test_format_decision_declined() -> None:
    request = ApprovalRequest(
        action="send email", reason="x", security_tier=SecurityTier.YELLOW
    )
    decision = request.decide(approved=False, decided_by="user")
    text = format_decision(decision)
    assert "[DECLINED]" in text
    assert "cancelled" in text.lower()
    assert "will not run" in text.lower()


def test_format_decision_names_the_action() -> None:
    request = ApprovalRequest(
        action="send email to Alex", reason="x", security_tier=SecurityTier.YELLOW
    )
    approved = request.decide(approved=True, decided_by="user")
    declined = request.decide(approved=False, decided_by="user")
    assert "send email to Alex" in format_decision(approved, request.action)
    assert "send email to Alex" in format_decision(declined, request.action)


# --- Approved execution (Step 3) ---------------------------------------------


def test_execute_approved_runs_the_tool() -> None:
    tool = _SendTool()
    orchestrator = _build_with_tool(tool)
    response = _yellow_tool_response(orchestrator, "send")
    decision = orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )

    executed = orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert executed.message == "Message sent!"
    assert tool.ran is True


def test_declined_decision_does_not_execute() -> None:
    tool = _SendTool()
    orchestrator = _build_with_tool(tool)
    response = _yellow_tool_response(orchestrator, "send")
    decision = orchestrator.approvals.decline(
        response.approval_request.request_id, decided_by="user"
    )

    executed = orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert tool.ran is False


def test_declined_request_is_no_longer_pending() -> None:
    tool = _SendTool()
    orchestrator = _build_with_tool(tool)
    response = _yellow_tool_response(orchestrator, "send")
    request_id = response.approval_request.request_id

    orchestrator.approvals.decline(request_id, decided_by="user")

    assert not orchestrator.approvals.has_pending(request_id)
    assert orchestrator.approvals.list_pending() == []


def test_declined_decision_is_recorded() -> None:
    tool = _SendTool()
    orchestrator = _build_with_tool(tool)
    response = _yellow_tool_response(orchestrator, "send")
    request_id = response.approval_request.request_id

    orchestrator.approvals.decline(request_id, decided_by="user")

    decisions = orchestrator.approvals.list_decisions()
    assert len(decisions) == 1
    assert decisions[0].is_declined is True


def test_red_tool_stays_blocked_even_when_approved() -> None:
    tool = _WipeTool()
    orchestrator = _build_with_tool(tool)
    response = _yellow_tool_response(orchestrator, "wipe")
    decision = orchestrator.approvals.approve(
        response.approval_request.request_id, decided_by="user"
    )

    executed = orchestrator.execute_approved(response, decision)

    assert executed.blocked is True
    assert tool.ran is False


# --- Full CLI journey with execution -----------------------------------------


def _run_cli_with_crafted_yellow(
    orchestrator: JarvisOrchestrator, crafted: JarvisResponse, inputs: list[str]
) -> str:
    """Drive the CLI so a 'send' request returns a crafted YELLOW response.

    The built-in tool matcher does not route to the test's YELLOW tool, so the
    orchestrator's handle_request is wrapped to return the crafted response for
    a 'send' request while leaving everything else unchanged.
    """
    original = orchestrator.handle_request

    def _handle(text: str) -> JarvisResponse:
        if "send" in text.lower():
            return crafted
        return original(text)

    orchestrator.handle_request = _handle  # type: ignore[method-assign]

    scripted = iter(inputs)
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    return "\n".join(outputs)


def test_cli_approve_executes_and_displays_result() -> None:
    tool = _SendTool()
    orchestrator = _build_with_tool(tool)
    crafted = _yellow_tool_response(orchestrator, "send")

    output = _run_cli_with_crafted_yellow(
        orchestrator, crafted, ["send a message", "yes", "exit"]
    )

    assert "approval required" in output.lower()
    assert "[APPROVED]" in output
    assert "Message sent!" in output
    assert tool.ran is True


def test_cli_decline_does_not_execute() -> None:
    tool = _SendTool()
    orchestrator = _build_with_tool(tool)
    crafted = _yellow_tool_response(orchestrator, "send")

    output = _run_cli_with_crafted_yellow(
        orchestrator, crafted, ["send a message", "no", "exit"]
    )

    assert "[DECLINED]" in output
    assert "Message sent!" not in output
    assert tool.ran is False


def test_cli_decline_is_clean_and_audited() -> None:
    """A full CLI decline: nothing runs, it is recorded, audited, and cleared."""
    logger = _SpyLogger()
    security = SecurityManager()
    registry = ToolRegistry()
    tool = _SendTool()
    registry.register_tool(EchoTool())
    registry.register_tool(tool)
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,  # type: ignore[arg-type]
    )
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        approval_manager=approvals,
    )
    crafted = _yellow_tool_response(orchestrator, "send")
    request_id = crafted.approval_request.request_id

    output = _run_cli_with_crafted_yellow(
        orchestrator, crafted, ["send a message", "no", "exit"]
    )

    # Nothing ran.
    assert tool.ran is False
    # Clear cancellation feedback that says it will not run.
    assert "[DECLINED]" in output
    assert "will not run" in output.lower()
    # Recorded and no longer pending.
    assert orchestrator.approvals.list_decisions()[0].is_declined is True
    assert not orchestrator.approvals.has_pending(request_id)
    # The decline was written to the audit log.
    approval_events = [
        e for e in logger.events if e.get("action_type") == "approval_decision"
    ]
    assert len(approval_events) == 1
    assert "outcome=declined" in str(approval_events[0]["detail"])
    # No successful tool execution was logged.
    success_tool_events = [
        e for e in logger.events if "success=True" in str(e.get("detail", ""))
    ]
    assert success_tool_events == []