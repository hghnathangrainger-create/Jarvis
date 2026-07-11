"""
test_file_copy_tool.py

Unit tests for the Jarvis FileCopyTool (tools/builtin/file_copy_tool.py),
Phase 25.

The tool is write-capable but narrow: it copies one existing file to one
new destination path, never overwriting an existing destination and
never touching the source. These tests use real temporary files, so no
database, AI, or network is needed.

Run with:
    pytest tests/unit/test_file_copy_tool.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileCopyTool


@pytest.fixture()
def tool() -> FileCopyTool:
    return FileCopyTool()


def _run(tool: FileCopyTool, **input_data: object):
    return tool.run(ToolRequest(tool_name="file_copy", input_data=dict(input_data)))


@pytest.fixture()
def source_file(tmp_path: Path) -> Path:
    path = tmp_path / "source.txt"
    path.write_text("Hello Jarvis! This is source content.", encoding="utf-8")
    return path


# --- successful copy ----------------------------------------------------------


def test_copies_text_file_successfully(tool: FileCopyTool, tmp_path: Path, source_file: Path) -> None:
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is True
    assert destination.exists()
    assert destination.read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8")


def test_copies_binary_file_successfully(tool: FileCopyTool, tmp_path: Path) -> None:
    source = tmp_path / "image.bin"
    source.write_bytes(bytes(range(256)) * 4)
    destination = tmp_path / "image_copy.bin"

    result = _run(tool, source=str(source), destination=str(destination))
    assert result.success is True
    assert destination.read_bytes() == source.read_bytes()


def test_copies_empty_file_successfully(tool: FileCopyTool, tmp_path: Path) -> None:
    source = tmp_path / "empty.txt"
    source.touch()
    destination = tmp_path / "empty_copy.txt"

    result = _run(tool, source=str(source), destination=str(destination))
    assert result.success is True
    assert destination.exists()
    assert destination.read_bytes() == b""


def test_success_message_mentions_both_paths(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert str(source_file) in result.output
    assert str(destination) in result.output


def test_metadata_reports_operation_and_paths(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.metadata["operation"] == "copy"
    assert result.metadata["source"] == str(source_file)
    assert result.metadata["destination"] == str(destination)


# --- no-overwrite rule ----------------------------------------------------------


def test_refuses_to_overwrite_existing_destination(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "dest.txt"
    destination.write_text("already here")

    result = _run(tool, source=str(source_file), destination=str(destination))

    assert result.success is False
    assert "already exists" in result.error
    assert destination.read_text() == "already here"  # untouched


def test_destination_exists_check_is_not_bypassed_by_content_similarity(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    """Even a destination that already holds byte-identical content must
    still be refused - existence alone is the rule, not content diffing."""
    destination = tmp_path / "dest.txt"
    destination.write_text(source_file.read_text())

    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is False


# --- source validation ------------------------------------------------------------


def test_missing_source_fails_safely(tool: FileCopyTool, tmp_path: Path) -> None:
    result = _run(
        tool,
        source=str(tmp_path / "ghost.txt"),
        destination=str(tmp_path / "dest.txt"),
    )
    assert result.success is False
    assert "does not exist" in result.error


def test_source_directory_fails_safely(tool: FileCopyTool, tmp_path: Path) -> None:
    a_dir = tmp_path / "a_directory"
    a_dir.mkdir()
    result = _run(
        tool, source=str(a_dir), destination=str(tmp_path / "dest.txt")
    )
    assert result.success is False
    assert "directory" in result.error.lower()


def test_same_source_and_destination_fails_safely(
    tool: FileCopyTool, source_file: Path
) -> None:
    result = _run(tool, source=str(source_file), destination=str(source_file))
    assert result.success is False
    assert "same" in result.error.lower() or "different" in result.error.lower()
    assert source_file.exists()


def test_same_source_and_destination_via_different_spelling_fails_safely(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    """"./source.txt" and "source.txt" resolve to the same real path."""
    differently_spelled = tmp_path / "." / source_file.name
    result = _run(tool, source=str(source_file), destination=str(differently_spelled))
    assert result.success is False


# --- destination parent-directory behavior ----------------------------------------


def test_missing_destination_parent_fails_safely(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    destination = tmp_path / "no_such_folder" / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is False
    assert "parent" in result.error.lower()
    assert not destination.exists()


def test_destination_parent_is_a_file_not_a_folder_fails_safely(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    not_a_folder = tmp_path / "not_a_folder.txt"
    not_a_folder.write_text("x")
    destination = not_a_folder / "dest.txt"
    result = _run(tool, source=str(source_file), destination=str(destination))
    assert result.success is False


# --- input validation --------------------------------------------------------------


def test_missing_source_input_fails(tool: FileCopyTool, tmp_path: Path) -> None:
    result = _run(tool, destination=str(tmp_path / "dest.txt"))
    assert result.success is False
    assert "source" in result.error.lower()


def test_missing_destination_input_fails(tool: FileCopyTool, source_file: Path) -> None:
    result = _run(tool, source=str(source_file))
    assert result.success is False
    assert "destination" in result.error.lower()


def test_blank_source_fails(tool: FileCopyTool, tmp_path: Path) -> None:
    result = _run(tool, source="   ", destination=str(tmp_path / "dest.txt"))
    assert result.success is False


def test_blank_destination_fails(tool: FileCopyTool, source_file: Path) -> None:
    result = _run(tool, source=str(source_file), destination="   ")
    assert result.success is False


# --- size limit --------------------------------------------------------------------


def test_oversized_source_fails_safely(
    tool: FileCopyTool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.builtin.file_copy_tool as module

    monkeypatch.setattr(module, "_MAX_COPY_BYTES", 10)
    source = tmp_path / "big.txt"
    source.write_text("x" * 1000)
    destination = tmp_path / "dest.txt"

    result = _run(tool, source=str(source), destination=str(destination))
    assert result.success is False
    assert not destination.exists()


# --- source preservation / read-only-source guarantee ------------------------------


def test_source_file_is_never_modified(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    before = source_file.read_bytes()
    _run(tool, source=str(source_file), destination=str(tmp_path / "dest.txt"))
    after = source_file.read_bytes()
    assert before == after


def test_source_file_still_exists_after_copy(
    tool: FileCopyTool, tmp_path: Path, source_file: Path
) -> None:
    _run(tool, source=str(source_file), destination=str(tmp_path / "dest.txt"))
    assert source_file.exists()


def test_destination_bytes_exactly_match_source_bytes(
    tool: FileCopyTool, tmp_path: Path
) -> None:
    source = tmp_path / "precise.bin"
    source.write_bytes(b"\x00\x01\xff\xfe\x10\x20abc\n\r\t")
    destination = tmp_path / "precise_copy.bin"

    _run(tool, source=str(source), destination=str(destination))
    assert destination.read_bytes() == source.read_bytes()


# --- security --------------------------------------------------------------------


def test_action_for_is_fixed_regardless_of_input(tool: FileCopyTool) -> None:
    action_a = tool.action_for(
        ToolRequest(
            tool_name="file_copy", input_data={"source": "a.txt", "destination": "b.txt"}
        )
    )
    action_b = tool.action_for(
        ToolRequest(
            tool_name="file_copy",
            input_data={"source": "delete_all.txt", "destination": "forget_all.txt"},
        )
    )
    assert action_a == action_b == "copy file"


def test_action_for_classifies_yellow(tool: FileCopyTool) -> None:
    action = tool.action_for(
        ToolRequest(
            tool_name="file_copy", input_data={"source": "a.txt", "destination": "b.txt"}
        )
    )
    decision = SecurityManager().classify_action(action)
    assert decision.tier is SecurityTier.YELLOW


# --- structural: no execution/AI/network capability ---------------------------------


def test_tool_module_never_imports_subprocess_ai_or_web_search() -> None:
    import ast
    import inspect

    import tools.builtin.file_copy_tool as module

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


def test_tool_has_no_move_rename_delete_or_execute_method() -> None:
    forbidden_name_fragments = (
        "move",
        "rename",
        "delete",
        "remove",
        "execute",
        "run_command",
    )
    public_methods = [
        name
        for name in dir(FileCopyTool)
        if not name.startswith("_") and callable(getattr(FileCopyTool, name))
    ]
    for method_name in public_methods:
        lowered = method_name.lower()
        for fragment in forbidden_name_fragments:
            assert fragment not in lowered, (
                f"FileCopyTool.{method_name} looks like a move/rename/delete/"
                "execute method; Phase 25 requires a narrow copy-only tool"
            )
