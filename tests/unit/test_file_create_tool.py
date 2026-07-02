"""
test_file_create_tool.py

Unit tests for FileCreateTool (Phase 4, Batch 2).

FileCreateTool is a guarded YELLOW write tool. These tests exercise it in
isolation in a temporary directory: it creates a new file, refuses to overwrite,
refuses to create folders, rejects bad input, and classifies YELLOW.

Run with:
    pytest tests/unit/test_file_create_tool.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileCreateTool


@pytest.fixture()
def tool() -> FileCreateTool:
    return FileCreateTool()


def _request(**input_data: object) -> ToolRequest:
    return ToolRequest(tool_name="file_create", input_data=input_data)


# --- Classification ----------------------------------------------------------


def test_action_classifies_yellow(tool: FileCreateTool) -> None:
    security = SecurityManager()
    action = tool.action_for(_request())
    assert security.classify_action(action).tier.name == "YELLOW"


def test_tool_name_and_description(tool: FileCreateTool) -> None:
    assert tool.name == "file_create"
    assert "creat" in tool.description.lower()


# --- Successful create -------------------------------------------------------


def test_creates_new_file_with_content(
    tool: FileCreateTool, tmp_path: Path
) -> None:
    target = tmp_path / "notes.txt"
    result = tool.run(_request(path=str(target), content="hello world"))
    assert result.success is True
    assert target.read_text() == "hello world"
    assert result.metadata["operation"] == "create"
    assert result.metadata["chars_written"] == "11"


def test_creates_empty_file_when_no_content(
    tool: FileCreateTool, tmp_path: Path
) -> None:
    target = tmp_path / "empty.txt"
    result = tool.run(_request(path=str(target)))
    assert result.success is True
    assert target.read_text() == ""


# --- Refusals ----------------------------------------------------------------


def test_refuses_to_overwrite_existing_file(
    tool: FileCreateTool, tmp_path: Path
) -> None:
    target = tmp_path / "exists.txt"
    target.write_text("original")
    result = tool.run(_request(path=str(target), content="new"))
    assert result.success is False
    assert "already exists" in result.error.lower()
    assert target.read_text() == "original"  # unchanged


def test_refuses_missing_parent_folder(
    tool: FileCreateTool, tmp_path: Path
) -> None:
    target = tmp_path / "no_such_dir" / "sub" / "file.txt"
    result = tool.run(_request(path=str(target), content="x"))
    assert result.success is False
    assert "does not exist" in result.error.lower()
    assert not (tmp_path / "no_such_dir").exists()  # no folders created


def test_rejects_missing_path(tool: FileCreateTool) -> None:
    result = tool.run(_request(content="x"))
    assert result.success is False
    assert "path" in result.error.lower()


def test_rejects_empty_path(tool: FileCreateTool) -> None:
    result = tool.run(_request(path="   ", content="x"))
    assert result.success is False


def test_rejects_non_string_content(
    tool: FileCreateTool, tmp_path: Path
) -> None:
    target = tmp_path / "bad.txt"
    result = tool.run(_request(path=str(target), content=123))
    assert result.success is False
    assert not target.exists()