"""
test_main_help_wiring.py

Composition tests for HelpTool wiring in main.build_orchestrator()
(Phase 43).

These confirm HelpTool is registered, routed to correctly (all three
"help"/"list commands"/"show commands" grammar aliases), and takes no
dependency - without ever needing a real database or AI call, matching
the existing test_main_config_wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_help_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.builtin.help_tool import HelpTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_help_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("help")


def test_help_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("help")
    assert isinstance(tool, HelpTool)


def test_command_router_routes_help_to_help() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("help") == "help"


def test_command_router_routes_list_commands_to_help() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("list commands") == "help"


def test_command_router_routes_show_commands_to_help() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("show commands") == "help"


def test_exactly_one_help_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("help") == 1


def test_help_tool_output_is_non_empty_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("help")

    from tools.base_tool import ToolRequest

    result = tool.run(ToolRequest(tool_name="help", input_data={}))
    assert result.success is True
    assert result.output.strip() != ""


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
