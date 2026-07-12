"""
test_quarantine_list_tool.py

Unit tests for the Jarvis QuarantineListTool
(tools/builtin/quarantine_list_tool.py), Phase 36.

The tool is read-only: it lists whatever currently exists inside
.jarvis_trash/ (name, size, modified time), never reads file content,
never creates the quarantine directory, and never modifies, moves, or
deletes anything. These tests use real temporary directories (via
tmp_path and monkeypatch.chdir), so no database, AI, or network is
needed.

Run with:
    pytest tests/unit/test_quarantine_list_tool.py
"""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path

import pytest

from tools.base_tool import ToolRequest
from tools.builtin import QuarantineListTool
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME


@pytest.fixture()
def tool() -> QuarantineListTool:
    return QuarantineListTool()


def _run(tool: QuarantineListTool):
    return tool.run(ToolRequest(tool_name="quarantine_list", input_data={}))


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Missing / empty quarantine directory
# ---------------------------------------------------------------------------


def test_missing_quarantine_directory_reports_nothing_quarantined(
    tool: QuarantineListTool, workspace: Path
) -> None:
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()
    result = _run(tool)

    assert result.success is True
    assert "nothing has been quarantined" in result.output.lower()


def test_missing_quarantine_directory_is_not_created_by_listing(
    tool: QuarantineListTool, workspace: Path
) -> None:
    _run(tool)
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()


def test_existing_empty_quarantine_directory_reports_empty(
    tool: QuarantineListTool, workspace: Path
) -> None:
    (workspace / _QUARANTINE_DIR_NAME).mkdir()
    result = _run(tool)

    assert result.success is True
    assert "empty" in result.output.lower()


# ---------------------------------------------------------------------------
# Listing quarantined files
# ---------------------------------------------------------------------------


def test_one_quarantined_file_is_listed(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "notes__a1b2c3d4.txt").write_text(
        "quarantined content", encoding="utf-8"
    )

    result = _run(tool)

    assert result.success is True
    assert "notes__a1b2c3d4.txt" in result.output
    assert result.metadata["file_count"] == "1"


def test_multiple_quarantined_files_are_listed(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "a__11111111.txt").write_text("a", encoding="utf-8")
    (quarantine_dir / "b__22222222.txt").write_text("bb", encoding="utf-8")

    result = _run(tool)

    assert result.success is True
    assert "a__11111111.txt" in result.output
    assert "b__22222222.txt" in result.output
    assert result.metadata["file_count"] == "2"


def test_size_in_bytes_is_shown(tool: QuarantineListTool, workspace: Path) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "sized__aaaaaaaa.txt").write_text(
        "exactly-twenty-chars", encoding="utf-8"
    )

    result = _run(tool)

    assert "20 bytes" in result.output


def test_modified_time_is_shown(tool: QuarantineListTool, workspace: Path) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    quarantined = quarantine_dir / "timed__bbbbbbbb.txt"
    quarantined.write_text("content", encoding="utf-8")
    fixed_mtime = time.mktime((2026, 1, 1, 12, 0, 0, 0, 0, -1))
    os.utime(quarantined, (fixed_mtime, fixed_mtime))

    result = _run(tool)

    assert "2026-01-01" in result.output


def test_file_contents_are_never_read(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "secret__cccccccc.txt").write_text(
        "THIS SHOULD NEVER APPEAR IN OUTPUT", encoding="utf-8"
    )

    result = _run(tool)

    assert "THIS SHOULD NEVER APPEAR IN OUTPUT" not in result.output


# ---------------------------------------------------------------------------
# No side effects
# ---------------------------------------------------------------------------


def test_listing_does_not_modify_file_mtimes_or_content(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    quarantined = quarantine_dir / "untouched__dddddddd.txt"
    quarantined.write_text("original content", encoding="utf-8")
    original_mtime = quarantined.stat().st_mtime

    _run(tool)

    assert quarantined.read_text(encoding="utf-8") == "original content"
    assert quarantined.stat().st_mtime == original_mtime


def test_listing_does_not_move_or_delete_files(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    quarantined = quarantine_dir / "stays_put__eeeeeeee.txt"
    quarantined.write_text("content", encoding="utf-8")

    _run(tool)

    assert quarantined.exists()
    assert list(quarantine_dir.iterdir()) == [quarantined]


# ---------------------------------------------------------------------------
# Unexpected non-file entries inside quarantine
# ---------------------------------------------------------------------------


def test_unexpected_subdirectory_is_handled_safely_and_not_recursed_into(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    unexpected_dir = quarantine_dir / "unexpected_folder"
    unexpected_dir.mkdir()
    (unexpected_dir / "nested_file.txt").write_text("should not be listed")
    (quarantine_dir / "real_file__ffffffff.txt").write_text(
        "content", encoding="utf-8"
    )

    result = _run(tool)

    assert result.success is True
    assert "real_file__ffffffff.txt" in result.output
    assert "unexpected_folder" in result.output
    assert "nested_file.txt" not in result.output
    assert result.metadata["file_count"] == "1"
    assert result.metadata["unsupported_count"] == "1"


def test_quarantine_containing_only_an_unexpected_subdirectory(
    tool: QuarantineListTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "unexpected_folder").mkdir()

    result = _run(tool)

    assert result.success is True
    assert "unexpected_folder" in result.output
    assert result.metadata["file_count"] == "0"


# ---------------------------------------------------------------------------
# Structural: no permanent-delete/move/write APIs, no forbidden imports
# ---------------------------------------------------------------------------


def test_module_never_calls_permanent_delete_or_move_apis() -> None:
    source = Path("tools/builtin/quarantine_list_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_calls = {"remove", "unlink", "rmtree", "rmdir", "rename", "replace"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls, (
                f"forbidden call found: {node.func.attr}"
            )


def test_module_never_calls_open_or_write_text(tool: QuarantineListTool) -> None:
    source = Path("tools/builtin/quarantine_list_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_calls = {"open", "write_text", "write_bytes", "mkdir"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                raise AssertionError(f"forbidden call found: {node.func.id}")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_calls
            ):
                raise AssertionError(f"forbidden call found: {node.func.attr}")


def test_module_imports_no_forbidden_packages() -> None:
    source = Path("tools/builtin/quarantine_list_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

    forbidden = {
        "ai",
        "workflow",
        "scheduler",
        "dashboard",
        "ui",
        "inbox",
        "storage",
        "database",
    }
    assert not (imported_names & forbidden), imported_names


# ---------------------------------------------------------------------------
# action_for()
# ---------------------------------------------------------------------------


def test_action_for_returns_fixed_string(tool: QuarantineListTool) -> None:
    request = ToolRequest(tool_name="quarantine_list", input_data={})
    assert tool.action_for(request) == "list quarantine"
