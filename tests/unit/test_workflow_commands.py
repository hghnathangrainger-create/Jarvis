"""
test_workflow_commands.py

Unit tests for the practical read-only workflow commands (Phase 3 Step 8).

These are convenience aliases that map a friendly phrase to an existing
read-only file tool with a fixed path: for example, "show project files" ->
file_list "." and "read readme" -> file_read "README.md". No new tools are
added; the aliases route to file_list and file_read only.

Run with:
    pytest tests/unit/test_workflow_commands.py
"""

from __future__ import annotations

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
def orchestrator() -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(_FakeMemory()))  # type: ignore[arg-type]
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
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
    """Create a realistic project workspace and switch into it."""
    (tmp_path / "README.md").write_text("# Jarvis\nThe project README.\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "notes.txt").write_text("notes")
    (docs / "phase_3_implementation_plan.md").write_text(
        "# Phase 3 Plan\nLive CLI approval execution.\n"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- Routing -----------------------------------------------------------------


def test_show_project_files_lists_root(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("show project files")
    assert response.success is True
    assert response.approval_request is None
    assert "README.md" in response.message
    assert "docs" in response.message


def test_show_docs_lists_docs(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("show docs")
    assert response.success is True
    assert "notes.txt" in response.message


def test_read_readme_reads_readme(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("read readme")
    assert response.success is True
    assert "The project README" in response.message


def test_show_phase_3_plan_reads_markdown(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("show phase 3 plan")
    assert response.success is True
    assert "Live CLI approval execution" in response.message


def test_aliases_are_case_insensitive_and_trimmed(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("  SHOW PROJECT FILES  ")
    assert response.success is True
    assert "README.md" in response.message


# --- GREEN and read-only -----------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "show project files",
        "list project files",
        "show docs",
        "list docs",
        "read readme",
        "show readme",
        "show phase 3 plan",
        "read phase 3 plan",
    ],
)
def test_aliases_run_green_without_approval(
    orchestrator: JarvisOrchestrator, workspace: Path, command: str
) -> None:
    response = orchestrator.handle_request(command)
    assert response.requires_confirmation is False
    assert response.approval_request is None


def test_aliases_are_read_only(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    def snapshot() -> list[str]:
        return sorted(str(p) for p in workspace.rglob("*"))

    before = snapshot()
    for command in ("show project files", "read readme", "show phase 3 plan"):
        orchestrator.handle_request(command)
    assert snapshot() == before


def test_missing_plan_file_fails_cleanly(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    (workspace / "docs" / "phase_3_implementation_plan.md").unlink()
    response = orchestrator.handle_request("show phase 3 plan")
    assert response.success is False
    assert response.blocked is False
    assert response.requires_confirmation is False
    assert response.tool_result is not None


# --- Existing behaviour preserved --------------------------------------------


def test_direct_file_commands_still_work(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    assert orchestrator.handle_request("list files in docs").success is True
    assert orchestrator.handle_request("read file README.md").success is True


def test_non_alias_phrases_route_normally(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    assert orchestrator.handle_request("show me system info").success is True


def test_red_still_blocks(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    assert orchestrator.handle_request("format drive C").blocked is True


def test_yellow_approval_flow_still_works(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("send email to Alex")
    assert response.requires_confirmation is True
    assert response.approval_request is not None