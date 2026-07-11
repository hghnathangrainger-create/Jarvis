"""
test_main_file_copy_wiring.py

Composition tests for FileCopyTool wiring in main.build_orchestrator()
(Phase 25).

These tests confirm FileCopyTool is registered and routed to correctly
- without ever needing a database, AI, or network call, matching the
existing test_main_web_search_wiring.py/test_main_file_search_wiring.py
pattern exactly.

Run with:
    pytest tests/unit/test_main_file_copy_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.builtin.file_copy_tool import FileCopyTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_file_copy_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("file_copy")


def test_file_copy_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("file_copy")
    assert isinstance(tool, FileCopyTool)


def test_command_router_routes_copy_file_to_file_copy() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("copy file a.txt to b.txt") == "file_copy"


def test_exactly_one_file_copy_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("file_copy") == 1
