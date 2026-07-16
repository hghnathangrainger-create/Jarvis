"""
test_main_prepare_prompt_wiring.py

Composition tests for PreparePromptTool wiring in
main.build_orchestrator() (Phase 86, Batch 2).

These confirm PreparePromptTool is registered, routed to correctly
(all five "prepare <mode> prompt for <goal>" grammar phrases), and
receives the real, already-built JarvisBrainStatusTool instance -
without ever needing a second real database connection beyond the one
build_orchestrator() itself already opens, matching the existing
test_main_jarvis_brain_wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_prepare_prompt_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin.prepare_prompt_tool import PreparePromptTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_prepare_prompt_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("prepare_prompt")


def test_prepare_prompt_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("prepare_prompt")
    assert isinstance(tool, PreparePromptTool)


@pytest.mark.parametrize(
    "mode", ["implementation", "review", "brainstorm", "critique", "compare"]
)
def test_command_router_routes_prepare_prompt_for_each_mode(mode: str) -> None:
    orchestrator = main.build_orchestrator()
    assert (
        orchestrator._command_router.match(f"prepare {mode} prompt for x")
        == "prepare_prompt"
    )


def test_exactly_one_prepare_prompt_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("prepare_prompt") == 1


def test_prepare_prompt_tool_output_is_non_empty_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("prepare_prompt")

    result = tool.run(
        ToolRequest(
            tool_name="prepare_prompt",
            input_data={"mode": "implementation", "goal": "improve memory search"},
        )
    )
    assert result.success is True
    assert "improve memory search" in result.output
    assert "## Jarvis Context" in result.output


def test_prepare_prompt_tool_reports_real_context_through_real_wiring() -> None:
    """Confirms PreparePromptTool receives the real, already-built
    JarvisBrainStatusTool through main.py's own wiring - not a fake or
    a disconnected copy - so its "Jarvis Context" section reflects
    reality (an empty, freshly initialised database)."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("prepare_prompt")

    result = tool.run(
        ToolRequest(
            tool_name="prepare_prompt",
            input_data={"mode": "review", "goal": "anything"},
        )
    )
    assert "Total memories stored: 0" in result.output
    assert "0 total (pending: 0, approved: 0, declined: 0, expired: 0)" in result.output
    assert "0 distinct workflow(s) recorded" in result.output


def test_prepare_prompt_tool_action_classifies_green_through_real_wiring() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("prepare_prompt")
    security = SecurityManager()
    decision = security.classify_action(
        tool.action_for(
            ToolRequest(
                tool_name="prepare_prompt",
                input_data={"mode": "implementation", "goal": "x"},
            )
        )
    )
    assert decision.is_allowed_automatically is True
    assert decision.tier.name == "GREEN"


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
