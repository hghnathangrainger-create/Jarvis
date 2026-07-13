"""
test_main_quarantine_list_wiring.py

Composition tests for QuarantineListTool wiring in
main.build_orchestrator() (Phase 36; extended Phase 37, Batch 2 to
confirm it shares the same QuarantineStore instance as FileDeleteTool).

These tests confirm QuarantineListTool is registered and routed to
correctly via both "list quarantine" and "show quarantine" - without
ever needing a database, AI, or network call, matching the existing
test_main_file_delete_wiring.py pattern exactly.

Run with:
    pytest tests/unit/test_main_quarantine_list_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from quarantine.quarantine_store import QuarantineStore
from tools.builtin import QuarantineListTool


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_quarantine_list_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("quarantine_list")


def test_quarantine_list_tool_is_the_correct_type() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("quarantine_list")
    assert isinstance(tool, QuarantineListTool)


def test_command_router_routes_list_quarantine() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("list quarantine") == "quarantine_list"


def test_command_router_routes_show_quarantine() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("show quarantine") == "quarantine_list"


def test_exactly_one_quarantine_list_tool_instance_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("quarantine_list") == 1


def test_quarantine_list_tool_is_backed_by_a_real_quarantine_store() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("quarantine_list")
    assert isinstance(tool._store, QuarantineStore)


def test_quarantine_list_tool_and_file_delete_tool_share_one_quarantine_store() -> (
    None
):
    """main.py must construct QuarantineStore exactly once and inject
    the same instance into both tools - never a second, redundant
    store/database connection."""
    orchestrator = main.build_orchestrator()
    list_tool = orchestrator._registry.get_tool("quarantine_list")
    delete_tool = orchestrator._registry.get_tool("file_delete")
    assert list_tool._store is delete_tool._store


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
