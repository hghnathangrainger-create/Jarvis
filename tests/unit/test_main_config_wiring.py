"""
test_main_config_wiring.py

Composition tests for ConfigTool wiring in main.build_orchestrator()
(Phase 31).

These confirm ConfigTool is registered, routed to correctly (both the
"show config" and "show settings" grammar aliases), reads the real
already-loaded Settings object, and never exposes the configured API
key's value - without ever needing a real database or AI call, matching
the existing test_main_file_move_wiring.py/test_main_pending_approval_
wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_config_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.builtin.config_tool import ConfigTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_config_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("config")


def test_config_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("config")
    assert isinstance(tool, ConfigTool)


def test_command_router_routes_show_config_to_config() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("show config") == "config"


def test_command_router_routes_show_settings_to_config() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("show settings") == "config"


def test_exactly_one_config_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("config") == 1


def test_config_tool_reflects_the_real_loaded_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_MODEL", "a-distinctive-test-model-name")
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("config")

    from tools.base_tool import ToolRequest

    result = tool.run(ToolRequest(tool_name="config", input_data={}))
    assert "a-distinctive-test-model-name" in result.output


def test_config_tool_never_exposes_the_configured_api_key_value() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("config")

    from tools.base_tool import ToolRequest

    result = tool.run(ToolRequest(tool_name="config", input_data={}))
    assert "test-key-not-real" not in result.output
    assert "Anthropic API key: set" in result.output


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
