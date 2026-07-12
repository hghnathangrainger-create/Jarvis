"""
test_main_file_delete_wiring.py

Composition tests for FileDeleteTool wiring in main.build_orchestrator()
(Phase 35, Batch 1).

These tests confirm FileDeleteTool is registered and routed to
correctly via "delete file <path>" - without ever needing a database,
AI, or network call, matching the existing
test_main_file_move_wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_file_delete_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.builtin.file_delete_tool import FileDeleteTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_file_delete_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("file_delete")


def test_file_delete_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("file_delete")
    assert isinstance(tool, FileDeleteTool)


def test_command_router_routes_delete_file_to_file_delete() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("delete file a.txt") == "file_delete"


def test_exactly_one_file_delete_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("file_delete") == 1


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
