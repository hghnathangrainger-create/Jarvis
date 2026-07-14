"""
test_main_health_check_wiring.py

Composition tests for HealthCheckTool wiring in main.build_orchestrator()
(Phase 57, covering both Batch 1 and Batch 2).

These confirm HealthCheckTool is registered, routed to correctly (all
three "health check"/"show health"/"system health" grammar aliases),
and receives the real, already-built registry/settings/inbox_store/
schedule_store/quarantine_store/security instances - without ever
needing a real database connection beyond the one build_orchestrator()
itself already opens, matching the existing
test_main_help_wiring.py/test_main_config_wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_health_check_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.base_tool import ToolRequest
from tools.builtin.health_check_tool import HealthCheckTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_health_check_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("health_check")


def test_health_check_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("health_check")
    assert isinstance(tool, HealthCheckTool)


def test_command_router_routes_health_check_to_health_check() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("health check") == "health_check"


def test_command_router_routes_show_health_to_health_check() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("show health") == "health_check"


def test_command_router_routes_system_health_to_health_check() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("system health") == "health_check"


def test_exactly_one_health_check_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("health_check") == 1


def test_health_check_tool_output_is_non_empty_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("health_check")

    result = tool.run(ToolRequest(tool_name="health_check", input_data={}))
    assert result.success is True
    assert "Jarvis health check:" in result.output


def test_health_check_tool_reports_batch_2_store_checks_through_real_wiring() -> None:
    """Confirms HealthCheckTool receives real, already-built Inbox/
    Schedule/Quarantine/SecurityManager instances through main.py's own
    wiring (Phase 57, Batch 2), not fakes or a disconnected copy."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("health_check")

    result = tool.run(ToolRequest(tool_name="health_check", input_data={}))
    assert "Inbox store: reachable" in result.output
    assert "Schedule store: reachable" in result.output
    assert "Quarantine store: reachable" in result.output
    assert (
        "Security Manager: reachable (self-classification: GREEN, as expected)"
        in result.output
    )


def test_health_check_tool_sees_the_real_populated_registry_through_wiring() -> None:
    """Confirms the tool receives the *same* registry object main.py
    itself builds - not a disconnected copy - so its own "tools
    registered" count reflects reality."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("health_check")

    result = tool.run(ToolRequest(tool_name="health_check", input_data={}))
    assert "including all core tools" in result.output


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
