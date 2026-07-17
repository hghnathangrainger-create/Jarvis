"""
test_main_project_state_wiring.py

Composition tests for ProjectStateShowTool/ProjectStateUpdateTool
wiring in main.build_orchestrator() (Phase 89, Batch 1).

These confirm both tools are registered, routed to correctly, backed
by the same real ProjectStateStore instance (never two separately
constructed stores), and classify GREEN/YELLOW respectively through
the real SecurityManager - matching the existing
test_main_jarvis_brain_wiring.py pattern.

Run with:
    pytest tests/unit/test_main_project_state_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from project_state.project_state_store import ProjectStateStore
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin.project_state_show_tool import ProjectStateShowTool
from tools.builtin.project_state_update_tool import ProjectStateUpdateTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


# --- registration --------------------------------------------------------------


def test_project_state_show_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("project_state_show")


def test_project_state_update_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("project_state_update")


def test_project_state_show_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("project_state_show")
    assert isinstance(tool, ProjectStateShowTool)


def test_project_state_update_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("project_state_update")
    assert isinstance(tool, ProjectStateUpdateTool)


def test_exactly_one_instance_of_each_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    names = orchestrator._registry.list_tool_names()
    assert names.count("project_state_show") == 1
    assert names.count("project_state_update") == 1


# --- routing ---------------------------------------------------------------------


def test_command_router_routes_show_jarvis_project_state() -> None:
    orchestrator = main.build_orchestrator()
    assert (
        orchestrator._command_router.match("show jarvis project state")
        == "project_state_show"
    )


def test_command_router_routes_update_jarvis_project_state() -> None:
    orchestrator = main.build_orchestrator()
    assert (
        orchestrator._command_router.match(
            "update jarvis project state: branch=main"
        )
        == "project_state_update"
    )


# --- both tools share one real store instance ---------------------------------


def test_both_tools_are_backed_by_a_real_project_state_store() -> None:
    orchestrator = main.build_orchestrator()
    show_tool = orchestrator._registry.get_tool("project_state_show")
    update_tool = orchestrator._registry.get_tool("project_state_update")
    assert isinstance(show_tool._project_state_store, ProjectStateStore)
    assert isinstance(update_tool._project_state_store, ProjectStateStore)


def test_both_tools_share_the_exact_same_store_instance() -> None:
    orchestrator = main.build_orchestrator()
    show_tool = orchestrator._registry.get_tool("project_state_show")
    update_tool = orchestrator._registry.get_tool("project_state_update")
    assert show_tool._project_state_store is update_tool._project_state_store


def test_an_update_through_one_tool_is_visible_through_the_other() -> None:
    orchestrator = main.build_orchestrator()
    show_tool = orchestrator._registry.get_tool("project_state_show")
    update_tool = orchestrator._registry.get_tool("project_state_update")

    update_tool.run(
        ToolRequest(
            tool_name="project_state_update",
            input_data={"field": "branch", "value": "main"},
        )
    )
    result = show_tool.run(
        ToolRequest(tool_name="project_state_show", input_data={})
    )
    assert "main" in result.output


# --- security classification through real wiring -------------------------------


def test_project_state_show_action_classifies_green_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("project_state_show")
    security = SecurityManager()
    decision = security.classify_action(
        tool.action_for(ToolRequest(tool_name="project_state_show"))
    )
    assert decision.is_allowed_automatically is True


def test_project_state_update_action_classifies_yellow_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("project_state_update")
    security = SecurityManager()
    decision = security.classify_action(
        tool.action_for(ToolRequest(tool_name="project_state_update"))
    )
    assert decision.requires_confirmation is True


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
