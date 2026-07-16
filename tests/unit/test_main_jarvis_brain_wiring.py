"""
test_main_jarvis_brain_wiring.py

Composition tests for JarvisBrainStatusTool wiring in
main.build_orchestrator() (Phase 86, Batch 1).

These confirm JarvisBrainStatusTool is registered, routed to correctly
(both "jarvis brain status"/"show jarvis brain" grammar aliases), and
receives the real, already-built registry/settings/memory/
approval_history/workflow_history instances - without ever needing a
second real database connection beyond the one build_orchestrator()
itself already opens, matching the existing
test_main_health_check_wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_jarvis_brain_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin.jarvis_brain_tool import JarvisBrainStatusTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_jarvis_brain_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("jarvis_brain")


def test_jarvis_brain_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("jarvis_brain")
    assert isinstance(tool, JarvisBrainStatusTool)


def test_command_router_routes_jarvis_brain_status_to_jarvis_brain() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("jarvis brain status") == "jarvis_brain"


def test_command_router_routes_show_jarvis_brain_to_jarvis_brain() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("show jarvis brain") == "jarvis_brain"


def test_exactly_one_jarvis_brain_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("jarvis_brain") == 1


def test_jarvis_brain_tool_output_is_non_empty_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("jarvis_brain")

    result = tool.run(ToolRequest(tool_name="jarvis_brain", input_data={}))
    assert result.success is True
    assert "Jarvis Brain Status:" in result.output


def test_jarvis_brain_tool_reports_real_config_through_real_wiring() -> None:
    """Confirms JarvisBrainStatusTool receives the real, already-built
    Settings/MemoryManager/ApprovalHistoryStore/WorkflowHistoryStore
    instances through main.py's own wiring, not fakes or a
    disconnected copy."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("jarvis_brain")

    result = tool.run(ToolRequest(tool_name="jarvis_brain", input_data={}))
    assert "AI reasoning enabled: False" in result.output
    assert "Anthropic API key: set" in result.output
    assert "Total memories stored: 0" in result.output
    assert "0 total (pending: 0, approved: 0, declined: 0, expired: 0)" in result.output
    assert "0 distinct workflows recorded" in result.output


def test_jarvis_brain_tool_sees_the_real_populated_registry_through_wiring() -> None:
    """Confirms the tool receives the *same* registry object main.py
    itself builds - not a disconnected copy - so its own "tools
    registered" count reflects reality."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("jarvis_brain")

    result = tool.run(ToolRequest(tool_name="jarvis_brain", input_data={}))
    expected_count = len(orchestrator._registry.list_tool_names())
    assert f"{expected_count} tools registered" in result.output


def test_jarvis_brain_tool_action_classifies_green_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("jarvis_brain")
    security = SecurityManager()
    decision = security.classify_action(
        tool.action_for(ToolRequest(tool_name="jarvis_brain"))
    )
    assert decision.is_allowed_automatically is True
    assert decision.tier.name == "GREEN"


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
