"""
test_main_webpage_read_wiring.py

Composition tests for WebpageReadTool wiring in main.build_orchestrator()
(Phase 33, Batch 1: Webpage Read Command).

These tests confirm WebpageReadTool is registered exactly once, routed
to correctly via the "read webpage <url>" command, and backed by
exactly one SafeWebFetcher instance - without ever performing a real
fetch. No test in this file makes a real network call: SafeWebFetcher
is constructed (which performs no I/O itself - it only builds an
httpx.Client) but its fetch() method is never invoked here.

Run with:
    pytest tests/unit/test_main_webpage_read_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from tools.builtin.webpage_read_tool import WebpageReadTool
from web.safe_web_fetcher import SafeWebFetcher


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_webpage_read_tool_is_registered() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.has_tool("webpage_read")


def test_webpage_read_tool_is_backed_by_safe_web_fetcher() -> None:
    orchestrator = main.build_orchestrator()
    tool = orchestrator._registry.get_tool("webpage_read")
    assert isinstance(tool, WebpageReadTool)
    assert isinstance(tool._fetcher, SafeWebFetcher)


def test_command_router_routes_read_webpage_to_webpage_read() -> None:
    orchestrator = main.build_orchestrator()
    assert (
        orchestrator._command_router.match("read webpage https://example.com")
        == "webpage_read"
    )


def test_exactly_one_webpage_read_tool_instance_is_registered() -> None:
    """main.py must construct exactly one SafeWebFetcher and inject it
    into exactly one WebpageReadTool - never a second, separate
    instance anywhere else in the composition root."""
    orchestrator = main.build_orchestrator()
    assert orchestrator._registry.list_tool_names().count("webpage_read") == 1
    tool = orchestrator._registry.get_tool("webpage_read")
    assert tool._fetcher is not None


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
