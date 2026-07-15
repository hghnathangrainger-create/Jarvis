"""
test_file_list_tool.py

Unit tests for the Jarvis FileListTool (tools/builtin/file_list_tool.py).

The tool is read-only and uses a real temporary directory, so these tests need
no database, AI, or network. They also confirm the tool never modifies the
directory it lists.

Run with:
    pytest tests/unit/test_file_list_tool.py
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileListTool


@pytest.fixture()
def tool() -> FileListTool:
    return FileListTool()


@pytest.fixture()
def sample_dir(tmp_path: Path) -> Path:
    """Create a directory with two files and two folders."""
    (tmp_path / "banana.txt").touch()
    (tmp_path / "apple.txt").touch()
    (tmp_path / "zebra_folder").mkdir()
    (tmp_path / "alpha_folder").mkdir()
    return tmp_path


def _run(tool: FileListTool, **input_data: object):
    return tool.run(ToolRequest(tool_name="file_list", input_data=dict(input_data)))


def _snapshot(directory: Path) -> list[str]:
    """Return a sorted list of every path under a directory, for comparison."""
    return sorted(str(p) for p in directory.rglob("*"))


# --- Listing -----------------------------------------------------------------


def test_lists_files(tool: FileListTool, sample_dir: Path) -> None:
    result = _run(tool, path=str(sample_dir))
    assert result.success is True
    assert "apple.txt" in result.output
    assert "banana.txt" in result.output


def test_lists_folders(tool: FileListTool, sample_dir: Path) -> None:
    result = _run(tool, path=str(sample_dir))
    assert "[DIR] alpha_folder" in result.output
    assert "[DIR] zebra_folder" in result.output


def test_entries_are_sorted(tool: FileListTool, sample_dir: Path) -> None:
    result = _run(tool, path=str(sample_dir))
    names = [
        line.replace("[DIR]", "").strip()
        for line in result.output.splitlines()[1:]
    ]
    assert names == sorted(names, key=str.casefold)


def test_empty_directory(tool: FileListTool, tmp_path: Path) -> None:
    result = _run(tool, path=str(tmp_path))
    assert result.success is True
    assert "empty" in result.output.lower()


def test_does_not_recurse(tool: FileListTool, sample_dir: Path) -> None:
    (sample_dir / "alpha_folder" / "secret.txt").touch()
    result = _run(tool, path=str(sample_dir))
    assert "secret.txt" not in result.output


# --- Error cases -------------------------------------------------------------


def test_missing_path_fails(tool: FileListTool) -> None:
    result = _run(tool)
    assert result.success is False
    assert result.error is not None


def test_nonexistent_path_fails(tool: FileListTool) -> None:
    result = _run(tool, path="/no/such/directory/xyz123")
    assert result.success is False
    assert "does not exist" in result.error


def test_file_path_instead_of_folder_fails(
    tool: FileListTool, sample_dir: Path
) -> None:
    result = _run(tool, path=str(sample_dir / "apple.txt"))
    assert result.success is False
    assert "not a directory" in result.error


# --- Limit -------------------------------------------------------------------


def test_limit_is_respected(tool: FileListTool, sample_dir: Path) -> None:
    """Phase 74 added an honest truncation notice line when more entries
    exist than are shown - sample_dir has 4 entries and limit=2 here, so
    exactly one extra, non-entry notice line is now expected alongside
    the 2 shown entries. This assertion is updated intentionally to
    account for it, not a regression."""
    result = _run(tool, path=str(sample_dir), limit=2)
    body = [
        line
        for line in result.output.splitlines()
        if line.strip()
        and not line.startswith("Contents")
        and not line.startswith("[showing")
    ]
    assert len(body) == 2


# --- Truncation notice (Phase 74) ---------------------------------------------


def test_more_entries_than_limit_shows_exact_notice(
    tool: FileListTool, sample_dir: Path
) -> None:
    result = _run(tool, path=str(sample_dir), limit=2)
    assert "[showing 2 of 4 entries; increase 'limit' to see more]" in result.output


def test_exactly_limit_entries_shows_no_notice(
    tool: FileListTool, sample_dir: Path
) -> None:
    result = _run(tool, path=str(sample_dir), limit=4)
    assert "showing" not in result.output.lower()


def test_fewer_entries_than_limit_shows_no_notice(
    tool: FileListTool, sample_dir: Path
) -> None:
    result = _run(tool, path=str(sample_dir), limit=50)
    assert "showing" not in result.output.lower()


def test_empty_directory_unaffected_by_truncation_notice(
    tool: FileListTool, tmp_path: Path
) -> None:
    result = _run(tool, path=str(tmp_path))
    assert result.output == f"{tmp_path} is empty."
    assert "showing" not in result.output.lower()


def test_truncation_notice_does_not_change_entry_order_or_labels(
    tool: FileListTool, sample_dir: Path
) -> None:
    result = _run(tool, path=str(sample_dir), limit=2)
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines[0] == f"Contents of {sample_dir}:"
    assert lines[1] == "  [DIR] alpha_folder"
    assert lines[2] == "        apple.txt"
    assert lines[3] == "[showing 2 of 4 entries; increase 'limit' to see more]"


# --- Security ----------------------------------------------------------------


def test_action_for_classifies_green(tool: FileListTool) -> None:
    action = tool.action_for(
        ToolRequest(tool_name="file_list", input_data={"path": "."})
    )
    decision = SecurityManager().classify_action(action)
    assert decision.tier is SecurityTier.GREEN


# --- Read-only guarantee -----------------------------------------------------


def test_tool_is_read_only(tool: FileListTool, sample_dir: Path) -> None:
    before = _snapshot(sample_dir)
    _run(tool, path=str(sample_dir))
    _run(tool, path=str(sample_dir), limit=1)
    after = _snapshot(sample_dir)
    assert before == after


def test_tool_exposes_no_mutating_methods(tool: FileListTool) -> None:
    public = [name for name in dir(tool) if not name.startswith("_")]
    forbidden = [
        name
        for name in public
        if any(
            word in name.lower()
            for word in ("write", "delete", "remove", "move", "rename", "modify")
        )
    ]
    assert forbidden == []


# --- Export ------------------------------------------------------------------


def test_exported_from_builtin() -> None:
    from tools.builtin import FileListTool as Exported

    assert Exported is FileListTool