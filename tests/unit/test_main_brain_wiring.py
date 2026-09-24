"""
test_main_brain_wiring.py

Composition tests for the Markdown Brain Integration's wiring in
main.build_orchestrator(): both brain tools are registered against the
one shared BrainService built from the real Settings, the CommandRouter
routes all five commands to them, the optional ContextAssembler brain
source is wired, and classification through the real stack is GREEN for
reads and YELLOW for writes.

Hermetic: PYTHON_DOTENV_DISABLED=1 plus explicit monkeypatched values
mean the developer's real .env is never read, the database is a temp
file, and BRAIN_PATH points at a temporary directory - never at Nathan's
real brain.

Run with:
    pytest tests/unit/test_main_brain_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin.brain_read_tool import BrainReadTool
from tools.builtin.brain_write_tool import BrainWriteTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate every setting so build_orchestrator() touches nothing real."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    brain_root = tmp_path / "brain"
    (brain_root / "context").mkdir(parents=True)
    (brain_root / "context" / "note.md").write_text(
        "# Note\nhello wiring\n", encoding="utf-8"
    )
    monkeypatch.setenv("BRAIN_ENABLED", "true")
    monkeypatch.setenv("BRAIN_PATH", str(brain_root))


def test_both_brain_tools_are_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("brain_read")
    assert orchestrator._registry.has_tool("brain_write")


def test_brain_tools_are_the_correct_types() -> None:
    orchestrator = main.build_orchestrator()
    assert isinstance(orchestrator._registry.get_tool("brain_read"), BrainReadTool)
    assert isinstance(orchestrator._registry.get_tool("brain_write"), BrainWriteTool)


def test_exactly_one_instance_of_each_brain_tool() -> None:
    orchestrator = main.build_orchestrator()
    names = orchestrator._registry.list_tool_names()
    assert names.count("brain_read") == 1
    assert names.count("brain_write") == 1


def test_router_routes_all_five_commands() -> None:
    orchestrator = main.build_orchestrator()
    router = orchestrator._command_router
    assert router.match("brain status") == "brain_read"
    assert router.match("brain search hello") == "brain_read"
    assert router.match("brain read context/note") == "brain_read"
    assert router.match("brain remember context/x hi") == "brain_write"
    assert router.match("brain update context/x hi") == "brain_write"


def test_real_settings_reach_the_shared_service() -> None:
    """The registered read tool's service reflects the real, already-
    loaded Settings - not a default-constructed copy."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("brain_read")
    result = tool.run(ToolRequest(tool_name="brain_read", input_data={"op": "status"}))
    assert result.success is True
    assert "enabled and configured" in result.output
    assert "Allowed folder 'context': exists" in result.output


def test_context_assembler_receives_the_same_shared_service() -> None:
    orchestrator = main.build_orchestrator()
    assembler = orchestrator._context_assembler
    assert assembler is not None
    assert assembler._brain_service is not None
    # The same instance the tools were registered with (one service,
    # never two).
    read_tool = orchestrator._registry.get_tool("brain_read")
    assert assembler._brain_service is read_tool._service


def test_read_action_classifies_green_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("brain_read")
    security = SecurityManager()
    decision = security.classify_action(
        tool.action_for(
            ToolRequest(tool_name="brain_read", input_data={"op": "search"})
        )
    )
    assert decision.tier is SecurityTier.GREEN


def test_write_action_classifies_yellow_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("brain_write")
    security = SecurityManager()
    decision = security.classify_action(
        tool.action_for(
            ToolRequest(
                tool_name="brain_write",
                input_data={"op": "remember", "title": "x", "content": "y"},
            )
        )
    )
    assert decision.tier is SecurityTier.YELLOW
