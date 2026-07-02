"""
test_file_tool_routing.py

Unit tests for registering and routing the read-only file tools in the live
Core path (Phase 3 Step 7).

These tests confirm that FileListTool and FileReadTool are reachable through
the orchestrator: natural commands like "list files in ." and "read file
README.md" route to the right tool, extract the path, and run as GREEN actions
without approval. RED still blocks and the YELLOW approval flow still works.

Run with:
    pytest tests/unit/test_file_tool_routing.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import (
    EchoTool,
    FileListTool,
    FileReadTool,
    InfoTool,
    MemoryTool,
)
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


class _FakeMemory:
    def list_recent(self, limit: int = 10):
        return []

    def search(self, query: str, limit: int = 10):
        return []


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register_tool(EchoTool())
    reg.register_tool(InfoTool())
    reg.register_tool(MemoryTool(_FakeMemory()))  # type: ignore[arg-type]
    reg.register_tool(FileListTool())
    reg.register_tool(FileReadTool())
    return reg


@pytest.fixture()
def orchestrator(registry: ToolRegistry) -> JarvisOrchestrator:
    security = SecurityManager()
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=Planner(security), executor=executor, registry=registry
    )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a small workspace and switch into it as the current directory."""
    (tmp_path / "README.md").write_text("# Jarvis\nHello from README.\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("some notes here")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- Registration ------------------------------------------------------------


def test_file_list_is_registered(registry: ToolRegistry) -> None:
    assert registry.has_tool("file_list")


def test_file_read_is_registered(registry: ToolRegistry) -> None:
    assert registry.has_tool("file_read")


# --- Routing to file_list ----------------------------------------------------


def test_list_files_in_current_directory(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("list files in .")
    assert response.success is True
    assert response.approval_request is None
    assert "README.md" in response.message


def test_list_files_in_subdirectory(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("list files in docs")
    assert response.success is True
    assert "notes.txt" in response.message


def test_show_files_routes_to_file_list(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("show files in docs")
    assert response.success is True
    assert "notes.txt" in response.message


def test_list_files_defaults_to_current_directory(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("list files")
    assert response.success is True
    assert "README.md" in response.message


# --- Routing to file_read ----------------------------------------------------


def test_read_file_reads_content(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("read file README.md")
    assert response.success is True
    assert response.approval_request is None
    assert "Hello from README" in response.message


def test_open_file_is_read_only(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    before = (workspace / "docs" / "notes.txt").read_bytes()
    response = orchestrator.handle_request("open file docs/notes.txt")
    after = (workspace / "docs" / "notes.txt").read_bytes()
    assert response.success is True
    assert "some notes here" in response.message
    assert before == after  # nothing modified


def test_show_file_routes_to_file_read(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("show file README.md")
    assert response.success is True
    assert "Hello from README" in response.message


# --- File commands are GREEN -------------------------------------------------


def test_file_commands_run_without_approval(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    listing = orchestrator.handle_request("list files in .")
    reading = orchestrator.handle_request("read file README.md")
    for response in (listing, reading):
        assert response.requires_confirmation is False
        assert response.approval_request is None


def test_reading_missing_file_fails_without_blocking(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("read file does_not_exist.xyz")
    assert response.success is False
    assert response.blocked is False
    assert response.requires_confirmation is False
    assert response.tool_result is not None  # a tool actually ran


# --- Safety preserved --------------------------------------------------------


def test_red_still_blocks(orchestrator: JarvisOrchestrator, workspace: Path) -> None:
    response = orchestrator.handle_request("format drive C")
    assert response.blocked is True
    assert response.approval_request is None


def test_yellow_approval_flow_still_works(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("send email to Alex")
    assert response.requires_confirmation is True
    assert response.approval_request is not None