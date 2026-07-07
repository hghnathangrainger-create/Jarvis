"""
test_cli_write_end_to_end.py

End-to-end integration tests for the guarded write approval flow through the
live CLI (Phase 4, Batch 3).

These drive the real CLI with scripted input and captured output - no real
terminal - wiring together the real Security Manager, Tool Registry, Tool
Executor, Approval Manager, and the two write tools. They prove the full write
journeys through the actual interface:

    - An approved "create file" writes the file to disk.
    - A declined "create file" writes nothing.
    - An approved "append" changes the file.
    - A declined "append" leaves the file unchanged.
    - A RED command stays blocked and never prompts for approval.
    - An advisory AI suggestion, when enabled, is displayed but changes nothing.

Run with:
    pytest tests/integration/test_cli_write_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIRequest, AIResponse
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from approval.approval_manager import ApprovalManager
from config.settings import Settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import (
    EchoTool,
    FileAppendTool,
    FileCreateTool,
    FileListTool,
    FileReadTool,
)
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeProvider(AIProvider):
    """A fake provider so AI tests need no API key or credits."""

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            text="You want to work with a file.\nStep 1: create it",
            model="fake-model",
            provider="fake",
        )

    def is_available(self) -> bool:
        return True


class _System:
    """The real components wired together, with the write tools registered."""

    def __init__(self, reasoning: AIReasoningEngine | None = None) -> None:
        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.registry.register_tool(EchoTool())
        self.registry.register_tool(FileListTool())
        self.registry.register_tool(FileReadTool())
        self.registry.register_tool(FileCreateTool())
        self.registry.register_tool(FileAppendTool())
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
            reasoning_engine=reasoning,
        )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _enabled_reasoning_engine() -> AIReasoningEngine:
    """Build an AIReasoningEngine wired to a fake provider via a real
    AIRouter - no live Claude API call is ever made."""
    router = AIRouter(
        provider=_FakeProvider(),
        prompt_builder=PromptBuilder(),
        validator=ResponseValidator(),
        logger=_SpyLogger(),  # type: ignore[arg-type]
        settings=Settings(
            anthropic_api_key="test-key",
            ai_model="test-model",
            ai_max_tokens=1024,
            database_path=Path("unused.db"),
            log_level="INFO",
            approval_timeout_seconds=60,
            debug=False,
            ai_reasoning_enabled=True,
        ),
    )
    return AIReasoningEngine(router=router, enabled=True)


def _drive(system: _System, inputs: list[str]) -> str:
    """Run the real CLI with scripted input; return the joined output."""
    outputs: list[str] = []
    scripted = iter(inputs)
    cli = JarvisCLI(
        system.orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    return "\n".join(outputs)


# --- Create through the CLI --------------------------------------------------


def test_cli_approved_create_writes_the_file(workspace: Path) -> None:
    system = _System()
    output = _drive(
        system,
        ["create file made.txt with HELLO FROM CLI", "yes", "exit"],
    )
    assert "approval required" in output.lower()
    assert "[APPROVED]" in output
    assert (workspace / "made.txt").read_text() == "HELLO FROM CLI"


def test_cli_declined_create_writes_nothing(workspace: Path) -> None:
    system = _System()
    output = _drive(
        system,
        ["create file nope.txt with SHOULD NOT EXIST", "no", "exit"],
    )
    assert "[DECLINED]" in output
    assert not (workspace / "nope.txt").exists()


# --- Append through the CLI --------------------------------------------------


def test_cli_approved_append_changes_the_file(workspace: Path) -> None:
    target = workspace / "log.txt"
    target.write_text("base")
    system = _System()
    output = _drive(
        system,
        ["append -more to file log.txt", "yes", "exit"],
    )
    assert "[APPROVED]" in output
    assert target.read_text() == "base-more"


def test_cli_declined_append_leaves_file_unchanged(workspace: Path) -> None:
    target = workspace / "keep.txt"
    target.write_text("original")
    system = _System()
    output = _drive(
        system,
        ["append XXX to file keep.txt", "no", "exit"],
    )
    assert "[DECLINED]" in output
    assert target.read_text() == "original"


# --- RED stays blocked, no prompt --------------------------------------------


def test_cli_red_command_stays_blocked_without_prompt(workspace: Path) -> None:
    system = _System()
    output = _drive(system, ["format drive C", "exit"])
    assert "[BLOCKED]" in output
    assert "approval required" not in output.lower()


# --- Read-only stays GREEN ---------------------------------------------------


def test_cli_read_only_stays_green(workspace: Path) -> None:
    (workspace / "readme.txt").write_text("hi")
    system = _System()
    output = _drive(system, ["read file readme.txt", "exit"])
    assert "[OK]" in output
    assert "approval required" not in output.lower()


# --- Advisory AI suggestion is displayed, changes nothing --------------------


def test_cli_shows_advisory_ai_suggestion_when_enabled(workspace: Path) -> None:
    system = _System(reasoning=_enabled_reasoning_engine())
    # A RED command: the AI suggestion is shown, but the action stays blocked.
    output = _drive(system, ["format drive C", "exit"])
    assert "advisory only" in output.lower()
    assert "[BLOCKED]" in output


def test_cli_advisory_suggestion_does_not_change_write_gate(
    workspace: Path,
) -> None:
    system = _System(reasoning=_enabled_reasoning_engine())
    # Even with the AI advising, a create still needs approval and, if declined,
    # writes nothing.
    output = _drive(
        system, ["create file ai.txt with x", "no", "exit"]
    )
    assert "advisory only" in output.lower()
    assert "[DECLINED]" in output
    assert not (workspace / "ai.txt").exists()