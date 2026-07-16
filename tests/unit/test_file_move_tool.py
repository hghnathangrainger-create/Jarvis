"""
test_file_move_tool.py

Unit tests for the Jarvis FileMoveTool (tools/builtin/file_move_tool.py),
Phase 26.

The tool is write-capable but narrow: it moves/renames one existing file
to one new destination path, never overwriting an existing destination.
These tests use real temporary files, so no database, AI, or network is
needed.

Run with:
    pytest tests/unit/test_file_move_tool.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileMoveTool


@pytest.fixture()
def tool() -> FileMoveTool:
    return FileMoveTool()


def _run(tool: FileMoveTool, **input_data: object):
    return tool.run(ToolRequest(tool_name="file_move", input_data=dict(input_data)))


@pytest.fixture()
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.txt"
    path.write_text("Hello Jarvis! This is source content.", encoding="utf-8")
    return path


# --- successful move/rename -----------------------------------------------------


def test_same_directory_rename_succeeds(tool: FileMoveTool, tmp_path: Path, source_file: Path) -> None:
    destination = tmp_path / "renamed.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is True
    assert destination.exists()
    assert not source_file.exists()
    assert destination.read_text(encoding="utf-8") == "Hello Jarvis! This is source content."


def test_cross_directory_move_succeeds(tool: FileMoveTool, tmp_path: Path, source_file: Path) -> None:
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    destination = subdir / "moved.txt"

    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is True
    assert destination.exists()
    assert not source_file.exists()


def test_binary_file_move_succeeds(tool: FileMoveTool, tmp_path: Path) -> None:
    source = tmp_path / "image.bin"
    original_bytes = bytes(range(256)) * 4
    source.write_bytes(original_bytes)
    destination = tmp_path / "image_moved.bin"

    result = _run(tool, source=str(source), destination=str(destination))
    assert result.success is True
    assert destination.read_bytes() == original_bytes
    assert not source.exists()


def test_empty_file_move_succeeds(tool: FileMoveTool, tmp_path: Path) -> None:
    source = tmp_path / "empty.txt"
    source.touch()
    destination = tmp_path / "empty_moved.txt"

    result = _run(tool, source=str(source), destination=str(destination))
    assert result.success is True
    assert destination.exists()
    assert destination.read_bytes() == b""


def test_success_message_mentions_both_paths(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert str(source_file) in result.output
    assert str(destination) in result.output


def test_metadata_reports_operation_and_paths(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.metadata["operation"] == "move"
    assert result.metadata["source"] == str(source_file)
    assert result.metadata["destination"] == str(destination)


# --- byte-size disclosure (Phase 85, Batch 1) ------------------------------------


def test_success_message_includes_moved_file_byte_size(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    """The confirmation must disclose the moved file's real byte size,
    matching FileCopyTool's own established "(<size> bytes)" wording."""
    expected_size = len(source_file.read_bytes())
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert f"({expected_size} bytes)" in result.output


def test_empty_file_move_reports_zero_bytes_honestly(
    tool: FileMoveTool, tmp_path: Path
) -> None:
    source = tmp_path / "empty.txt"
    source.touch()
    destination = tmp_path / "empty_moved.txt"

    result = _run(tool, source=str(source), destination=str(destination))
    assert result.success is True
    assert "(0 bytes)" in result.output


def test_metadata_includes_size_bytes_key_matching_real_file_size(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    expected_size = len(source_file.read_bytes())
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.metadata["size_bytes"] == str(expected_size)


def test_binary_file_move_reports_correct_byte_size(
    tool: FileMoveTool, tmp_path: Path
) -> None:
    """Proves the size is read from the real, moved binary file - not
    derived from any text-based length calculation."""
    source = tmp_path / "image.bin"
    original_bytes = bytes(range(256)) * 4
    source.write_bytes(original_bytes)
    destination = tmp_path / "image_moved.bin"

    result = _run(tool, source=str(source), destination=str(destination))
    assert f"({len(original_bytes)} bytes)" in result.output
    assert result.metadata["size_bytes"] == str(len(original_bytes))


# --- no-overwrite rule ----------------------------------------------------------


def test_refuses_to_overwrite_existing_destination(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    destination.write_text("already here")

    result = _run(tool, source=str(source_file), destination=str(destination))

    assert result.success is False
    assert "already exists" in result.error
    assert destination.read_text() == "already here"  # untouched
    assert source_file.exists()  # source not consumed by the failed attempt


def test_destination_exists_check_is_not_bypassed_by_content_similarity(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    destination.write_text(source_file.read_text())

    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is False
    assert source_file.exists()


# --- source validation ------------------------------------------------------------


def test_missing_source_fails_safely(tool: FileMoveTool, tmp_path: Path) -> None:
    result = _run(
        tool,
        source=str(tmp_path / "ghost.txt"),
        destination=str(tmp_path / "dest.txt"),
    )
    assert result.success is False
    assert "does not exist" in result.error


def test_source_directory_fails_safely(tool: FileMoveTool, tmp_path: Path) -> None:
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()
    result = _run(
        tool, source=str(a_dir), destination=str(tmp_path / "dest.txt")
    )
    assert result.success is False
    assert "directory" in result.error.lower()
    assert a_dir.exists()  # untouched


def test_same_source_and_destination_fails_safely(
    tool: FileMoveTool, source_file: Path
) -> None:
    result = _run(tool, source=str(source_file), destination=str(source_file))
    assert result.success is False
    assert "same" in result.error.lower() or "different" in result.error.lower()
    assert source_file.exists()


def test_same_source_and_destination_via_different_spelling_fails_safely(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    differently_spelled = tmp_path / "." / source_file.name
    result = _run(tool, source=str(source_file), destination=str(differently_spelled))
    assert result.success is False
    assert source_file.exists()


# --- destination parent-directory behavior ----------------------------------------


def test_missing_destination_parent_fails_safely(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "no_such_folder" / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is False
    assert "parent" in result.error.lower()
    assert not destination.exists()
    assert source_file.exists()


def test_destination_parent_is_a_file_not_a_folder_fails_safely(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    not_a_folder = tmp_path / "not_a_folder.txt"
    not_a_folder.write_text("x")
    destination = not_a_folder / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is False
    assert source_file.exists()


# --- input validation --------------------------------------------------------------


def test_missing_source_input_fails(tool: FileMoveTool, tmp_path: Path) -> None:
    result = _run(tool, destination=str(tmp_path / "dest.txt"))
    assert result.success is False
    assert "source" in result.error.lower()


def test_missing_destination_input_fails(tool: FileMoveTool, source_file: Path) -> None:
    result = _run(tool, source=str(source_file))
    assert result.success is False
    assert "destination" in result.error.lower()


def test_blank_source_fails(tool: FileMoveTool, tmp_path: Path) -> None:
    result = _run(tool, source="   ", destination=str(tmp_path / "dest.txt"))
    assert result.success is False


def test_blank_destination_fails(tool: FileMoveTool, source_file: Path) -> None:
    result = _run(tool, source=str(source_file), destination="   ")
    assert result.success is False


# --- source-path behavior after success ---------------------------------------------


def test_source_path_no_longer_exists_after_success(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    _run(tool, source=str(source_file), destination=str(destination))
    assert not source_file.exists()


def test_destination_bytes_exactly_match_original_source_bytes(
    tool: FileMoveTool, tmp_path: Path
) -> None:
    source = tmp_path / "precise.bin"
    original_bytes = b"\x00\x01\xff\xfe\x10\x20abc\n\r\t"
    source.write_bytes(original_bytes)
    destination = tmp_path / "precise_moved.bin"

    _run(tool, source=str(source), destination=str(destination))
    assert destination.read_bytes() == original_bytes


def test_failed_move_leaves_source_untouched(
    tool: FileMoveTool, tmp_path: Path, source_file: Path
) -> None:
    """A failure at any validation step must never partially move or
    otherwise disturb the source file."""
    destination = tmp_path / "dest.txt"
    destination.write_text("blocking")

    before = source_file.read_bytes()
    _run(tool, source=str(source_file), destination=str(destination))
    after = source_file.read_bytes()
    assert before == after
    assert source_file.exists()


# --- security --------------------------------------------------------------------


def test_action_for_is_fixed_regardless_of_input(tool: FileMoveTool) -> None:
    action_a = tool.action_for(
        ToolRequest(
            tool_name="file_move", input_data={"source": "a.txt", "destination": "b.txt"}
        )
    )
    action_b = tool.action_for(
        ToolRequest(
            tool_name="file_move",
            input_data={"source": "delete_all.txt", "destination": "forget_all.txt"},
        )
    )
    assert action_a == action_b == "move file"


def test_action_for_classifies_yellow(tool: FileMoveTool) -> None:
    action = tool.action_for(
        ToolRequest(
            tool_name="file_move", input_data={"source": "a.txt", "destination": "b.txt"}
        )
    )
    decision = SecurityManager().classify_action(action)
    assert decision.tier is SecurityTier.YELLOW


# --- structural: no execution/AI/network capability ---------------------------------


def test_tool_module_never_imports_subprocess_ai_or_web_search() -> None:
    import ast
    import inspect

    import tools.builtin.file_move_tool as module

    source = inspect.getsource(module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    forbidden_modules = {"subprocess", "os.system", "shutil"}
    forbidden_names = {
        "AIReasoningEngine",
        "AIRouter",
        "WebSearchProvider",
        "WebSearchTool",
        "CommandRouter",
        "ToolExecutor",
        "ApprovalManager",
    }
    assert imported_modules & forbidden_modules == set()
    assert imported_names & forbidden_names == set()


def test_tool_has_no_delete_copy_or_execute_method() -> None:
    forbidden_name_fragments = (
        "delete",
        "remove",
        "copy",
        "execute",
        "run_command",
    )
    public_methods = [
        name
        for name in dir(FileMoveTool)
        if not name.startswith("_") and callable(getattr(FileMoveTool, name))
    ]
    for method_name in public_methods:
        lowered = method_name.lower()
        for fragment in forbidden_name_fragments:
            assert fragment not in lowered, (
                f"FileMoveTool.{method_name} looks like a delete/copy/execute "
                "method; Phase 26 requires a narrow move/rename-only tool"
            )
