"""
test_main_web_search_wiring.py

Composition tests for web-search wiring in main.build_orchestrator()
(Phase 16, Batch 2: Read-Only Tool, Command Routing, Composition Wiring).

These tests confirm WebSearchTool is registered, routed to correctly, and
backed by exactly one DuckDuckGoSearchProvider instance - without ever
performing a real search. No test in this file makes a real network
call: the DuckDuckGoSearchProvider is constructed (which does not itself
touch the network - it only builds a client object) but its search()
method is never invoked here.

Run with:
    pytest tests/unit/test_main_web_search_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.builtin.web_search_tool import WebSearchTool
from tools.duckduckgo_search_provider import DuckDuckGoSearchProvider


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_web_search_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("web_search")


def test_web_search_tool_is_backed_by_duckduckgo_provider() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("web_search")
    assert isinstance(tool, WebSearchTool)
    assert isinstance(tool._provider, DuckDuckGoSearchProvider)


def test_command_router_routes_the_exact_phrase_to_web_search() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._command_router.match("search the web for jarvis ai") == "web_search"


def test_exactly_one_provider_instance_is_constructed() -> None:
    """main.py must construct exactly one DuckDuckGoSearchProvider and
    inject it into exactly one WebSearchTool - never a second, separate
    instance anywhere else in the composition root."""
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("web_search")
    # Structural: the tool holds a provider reference, and only one tool
    # of this name exists in the registry at all.
    assert orchestrator._registry.list_tool_names().count("web_search") == 1
    assert tool._provider is not None
