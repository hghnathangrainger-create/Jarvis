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

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
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


# --- Approval prompt is triggered for YELLOW ---------------------------------


def test_yellow_response_triggers_prompt_and_approve() -> None:
    orchestrator, output = _run_cli(["send email to Alex", "yes", "exit"])
    assert "Approval required" in output
    assert "[APPROVED]" in output


def test_yellow_response_triggers_prompt_and_decline() -> None:
    orchestrator, output = _run_cli(["send email to Alex", "no", "exit"])
    assert "Approval required" in output
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
    assert "Approval required" not in output
    assert "[OK]" in output


def test_red_response_does_not_trigger_prompt() -> None:
    _orchestrator, output = _run_cli(["format drive C", "exit"])
    assert "Approval required" not in output
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