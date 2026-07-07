"""
test_write_tool_routing.py

Unit tests for routing write commands to the guarded write tools
(Phase 4, Batch 2).

These confirm that natural create/append phrases route to file_create and
file_append with the path and content extracted correctly, that the responses
come back as YELLOW (requiring approval) rather than running immediately, that
read-only commands stay GREEN, and that RED stays blocked.

Run with:
    pytest tests/unit/test_write_tool_routing.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin import (
    EchoTool,
    FileAppendTool,
    FileCreateTool,
    FileListTool,
    FileReadTool,
    InfoTool,
)
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


@pytest.fixture()
def orchestrator() -> JarvisOrchestrator:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
    registry.register_tool(FileCreateTool())
    registry.register_tool(FileAppendTool())
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "existing.txt").write_text("start")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# --- Create routing ----------------------------------------------------------


def test_create_command_routes_to_file_create(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("create file hello.txt with hello there")
    assert response.tool_name == "file_create"
    assert response.tool_input == {"path": "hello.txt", "content": "hello there"}


def test_create_command_is_yellow_not_run(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("create file hello.txt with hi")
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    # The file must NOT exist yet: creation waits for approval.
    assert not (workspace / "hello.txt").exists()


def test_create_command_without_content(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("create file empty.txt")
    assert response.tool_name == "file_create"
    assert response.tool_input == {"path": "empty.txt", "content": ""}


# --- Append routing ----------------------------------------------------------


def test_append_command_routes_to_file_append(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request(
        "append more text to file existing.txt"
    )
    assert response.tool_name == "file_append"
    assert response.tool_input == {"path": "existing.txt", "content": "more text"}


def test_append_command_is_yellow_not_run(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("append hi to file existing.txt")
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    # The file must be unchanged: appending waits for approval.
    assert (workspace / "existing.txt").read_text() == "start"


# --- Read-only stays GREEN, RED stays blocked --------------------------------


def test_read_only_commands_stay_green(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    listing = orchestrator.handle_request("list files in .")
    reading = orchestrator.handle_request("read file existing.txt")
    for response in (listing, reading):
        assert response.success is True
        assert response.approval_request is None


def test_red_still_blocks(
    orchestrator: JarvisOrchestrator, workspace: Path
) -> None:
    response = orchestrator.handle_request("format drive C")
    assert response.blocked is True
    assert response.approval_request is None