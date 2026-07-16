"""
test_file_append_tool.py

Unit tests for FileAppendTool (Phase 4, Batch 2).

FileAppendTool is a guarded YELLOW write tool. These tests exercise it in
isolation in a temporary directory: it appends to an existing file, refuses
missing files, folders, and binary files, rejects bad input, and classifies
YELLOW.

Run with:
    pytest tests/unit/test_file_append_tool.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileAppendTool


@pytest.fixture()
def tool() -> FileAppendTool:
    return FileAppendTool()


def _request(**input_data: object) -> ToolRequest:
    return ToolRequest(tool_name="file_append", input_data=input_data)


# --- Classification ----------------------------------------------------------


def test_action_classifies_yellow(tool: FileAppendTool) -> None:
    security = SecurityManager()
    action = tool.action_for(_request())
    assert security.classify_action(action).tier.name == "YELLOW"


def test_tool_name_and_description(tool: FileAppendTool) -> None:
    assert tool.name == "file_append"
    assert "append" in tool.description.lower()


# --- Successful append -------------------------------------------------------


def test_appends_to_existing_file(tool: FileAppendTool, tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("start")
    result = tool.run(_request(path=str(target), content=" more"))
    assert result.success is True
    assert target.read_text() == "start more"
    assert result.metadata["operation"] == "append"
    assert result.metadata["chars_appended"] == "5"


def test_append_preserves_existing_content(
    tool: FileAppendTool, tmp_path: Path
) -> None:
    target = tmp_path / "log.txt"
    target.write_text("line1\n")
    tool.run(_request(path=str(target), content="line2\n"))
    tool.run(_request(path=str(target), content="line3\n"))
    assert target.read_text() == "line1\nline2\nline3\n"


# --- resulting total size disclosure (Phase 85, Batch 2) ----------------------


def test_success_message_includes_resulting_total_byte_size(
    tool: FileAppendTool, tmp_path: Path
) -> None:
    """The confirmation must keep disclosing characters added (unchanged
    since Phase 4) and now also disclose the file's real, resulting
    total byte size."""
    target = tmp_path / "notes.txt"
    target.write_text("start")
    result = tool.run(_request(path=str(target), content=" more"))
    expected_total = len(target.read_bytes())
    assert "5 characters added" in result.output
    assert f"{expected_total} bytes total" in result.output


def test_metadata_includes_size_bytes_key_matching_real_file_size(
    tool: FileAppendTool, tmp_path: Path
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("start")
    result = tool.run(_request(path=str(target), content=" more"))
    assert result.metadata["size_bytes"] == str(len(target.read_bytes()))


def test_append_to_nonempty_file_reports_total_not_just_appended_length(
    tool: FileAppendTool, tmp_path: Path
) -> None:
    """Critical honesty check: the disclosed size must be the file's
    real, resulting total - not merely len(content) of the text just
    appended - proven by appending a short string to a file with
    substantial pre-existing content and confirming the total reflects
    both."""
    target = tmp_path / "log.txt"
    target.write_text("existing content that is much longer than the append")
    result = tool.run(_request(path=str(target), content=" - x"))
    expected_total = len(target.read_bytes())

    assert "4 characters added" in result.output
    assert f"{expected_total} bytes total" in result.output
    assert expected_total > 4
    assert result.metadata["chars_appended"] == "4"
    assert result.metadata["size_bytes"] == str(expected_total)


def test_repeated_appends_report_growing_total_each_time(
    tool: FileAppendTool, tmp_path: Path
) -> None:
    target = tmp_path / "log.txt"
    target.write_text("line1\n")

    first = tool.run(_request(path=str(target), content="line2\n"))
    first_total = len(target.read_bytes())
    assert f"{first_total} bytes total" in first.output

    second = tool.run(_request(path=str(target), content="line3\n"))
    second_total = len(target.read_bytes())
    assert f"{second_total} bytes total" in second.output
    assert second_total > first_total


# --- Refusals ----------------------------------------------------------------


def test_refuses_missing_file(tool: FileAppendTool, tmp_path: Path) -> None:
    target = tmp_path / "ghost.txt"
    result = tool.run(_request(path=str(target), content="x"))
    assert result.success is False
    assert "does not exist" in result.error.lower()


def test_refuses_directory_target(tool: FileAppendTool, tmp_path: Path) -> None:
    directory = tmp_path / "adir"
    directory.mkdir()
    result = tool.run(_request(path=str(directory), content="x"))
    assert result.success is False
    assert "directory" in result.error.lower()


def test_refuses_binary_file(tool: FileAppendTool, tmp_path: Path) -> None:
    target = tmp_path / "data.bin"
    target.write_bytes(b"\x00\x01\x02binary")
    result = tool.run(_request(path=str(target), content="x"))
    assert result.success is False
    assert "binary" in result.error.lower()
    # The file was not modified.
    assert target.read_bytes() == b"\x00\x01\x02binary"


def test_rejects_missing_path(tool: FileAppendTool) -> None:
    result = tool.run(_request(content="x"))
    assert result.success is False
    assert "path" in result.error.lower()


def test_rejects_missing_content(tool: FileAppendTool, tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("start")
    result = tool.run(_request(path=str(target)))
    assert result.success is False
    assert "content" in result.error.lower()
    assert target.read_text() == "start"  # unchanged


def test_rejects_empty_content(tool: FileAppendTool, tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("start")
    result = tool.run(_request(path=str(target), content=""))
    assert result.success is False
    assert target.read_text() == "start"  # unchanged