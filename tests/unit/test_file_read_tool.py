"""
test_file_read_tool.py

Unit tests for the Jarvis FileReadTool (tools/builtin/file_read_tool.py).

The tool is read-only and uses real temporary files, so these tests need no
database, AI, or network. They also confirm the tool never modifies the file
it reads, respects the character limit, and refuses binary files.

Run with:
    pytest tests/unit/test_file_read_tool.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileReadTool


@pytest.fixture()
def tool() -> FileReadTool:
    return FileReadTool()


@pytest.fixture()
def text_file(tmp_path: Path) -> Path:
    """Create a small UTF-8 text file."""
    path = tmp_path / "note.txt"
    path.write_text("Hello Jarvis!\nThis is a small text file.\n", encoding="utf-8")
    return path


def _run(tool: FileReadTool, **input_data: object):
    return tool.run(ToolRequest(tool_name="file_read", input_data=dict(input_data)))


# --- Reading -----------------------------------------------------------------


def test_reads_small_text_file(tool: FileReadTool, text_file: Path) -> None:
    result = _run(tool, path=str(text_file))
    assert result.success is True
    assert "Hello Jarvis!" in result.output
    assert "small text file" in result.output


def test_empty_file(tool: FileReadTool, tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.touch()
    result = _run(tool, path=str(path))
    assert result.success is True


# --- Error cases -------------------------------------------------------------


def test_missing_path_fails(tool: FileReadTool) -> None:
    result = _run(tool)
    assert result.success is False
    assert result.error is not None


def test_nonexistent_path_fails(tool: FileReadTool) -> None:
    result = _run(tool, path="/no/such/file.txt")
    assert result.success is False
    assert "does not exist" in result.error


def test_directory_path_fails(tool: FileReadTool, tmp_path: Path) -> None:
    result = _run(tool, path=str(tmp_path))
    assert result.success is False
    assert "directory" in result.error.lower()


# --- Character limit ---------------------------------------------------------


def test_max_chars_is_respected(tool: FileReadTool, tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    path.write_text("A" * 10_000, encoding="utf-8")
    result = _run(tool, path=str(path), max_chars=100)
    body = result.output.split("\n", 1)[1]
    assert body.count("A") == 100


def test_truncation_is_marked(tool: FileReadTool, tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    path.write_text("A" * 10_000, encoding="utf-8")
    result = _run(tool, path=str(path), max_chars=100)
    assert "truncated" in result.output.lower()


def test_no_truncation_notice_when_file_fits(
    tool: FileReadTool, text_file: Path
) -> None:
    result = _run(tool, path=str(text_file), max_chars=4000)
    assert "truncated" not in result.output.lower()


# --- Binary refusal ----------------------------------------------------------


def test_binary_file_is_refused(tool: FileReadTool, tmp_path: Path) -> None:
    path = tmp_path / "image.bin"
    path.write_bytes(b"\x89PNG\r\n\x00\x00\x00binary\x00stuff")
    result = _run(tool, path=str(path))
    assert result.success is False
    assert "binary" in result.error.lower()


# --- UTF-8 safety ------------------------------------------------------------


def test_invalid_utf8_is_handled_safely(tool: FileReadTool, tmp_path: Path) -> None:
    path = tmp_path / "bad.txt"
    # Invalid UTF-8 bytes but no NUL, so it is treated as text and read safely.
    path.write_bytes("café \x80\x81 text".encode("latin-1"))
    result = _run(tool, path=str(path))
    assert result.success is True


# --- Security ----------------------------------------------------------------


def test_action_for_classifies_green(tool: FileReadTool) -> None:
    action = tool.action_for(
        ToolRequest(tool_name="file_read", input_data={"path": "x.txt"})
    )
    decision = SecurityManager().classify_action(action)
    assert decision.tier is SecurityTier.GREEN


# --- Read-only guarantee -----------------------------------------------------


def test_tool_is_read_only(tool: FileReadTool, text_file: Path) -> None:
    before = (text_file.read_bytes(), text_file.stat().st_mtime)
    _run(tool, path=str(text_file))
    _run(tool, path=str(text_file), max_chars=5)
    after = (text_file.read_bytes(), text_file.stat().st_mtime)
    assert before == after


def test_tool_exposes_no_mutating_methods(tool: FileReadTool) -> None:
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
    from tools.builtin import FileReadTool as Exported

    assert Exported is FileReadTool