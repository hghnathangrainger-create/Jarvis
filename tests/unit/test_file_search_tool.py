"""
test_file_search_tool.py

Unit tests for the Jarvis FileSearchTool (tools/builtin/file_search_tool.py),
Phase 24.

The tool is read-only and uses real temporary directories, so these tests
need no database, AI, or network. They confirm both search modes (name
and content), honest empty/no-match behaviour, safe handling of binary/
unreadable/oversized files, result-limit clamping, excluded-directory
pruning, and the tool's own read-only/GREEN safety guarantees.

Run with:
    pytest tests/unit/test_file_search_tool.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.builtin import FileSearchTool


@pytest.fixture()
def tool() -> FileSearchTool:
    return FileSearchTool()


def _run(tool: FileSearchTool, **input_data: object):
    return tool.run(ToolRequest(tool_name="file_search", input_data=dict(input_data)))


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Build a small directory tree with matching and non-matching files,
    an excluded directory, a binary file, and a subdirectory."""
    (tmp_path / "readme_notes.txt").write_text("Hello Jarvis, this is readme content.")
    (tmp_path / "other.txt").write_text("nothing relevant here")

    sub = tmp_path / "subdir"
    sub.mkdir()
    (sub / "deep_readme.md").write_text("deep jarvis content here too")

    excluded = tmp_path / "__pycache__"
    excluded.mkdir()
    (excluded / "readme_cache.txt").write_text("jarvis content that must never be found")

    binary = tmp_path / "image.bin"
    binary.write_bytes(b"\x00\x01\x02binary jarvis content\x00")

    return tmp_path


# --- name search ---------------------------------------------------------------


def test_name_search_finds_matching_filenames(tool: FileSearchTool, workspace: Path) -> None:
    result = _run(tool, mode="name", query="readme", path=str(workspace))
    assert result.success is True
    assert "readme_notes.txt" in result.output
    assert "deep_readme.md" in result.output
    assert "other.txt" not in result.output


def test_name_search_is_case_insensitive(tool: FileSearchTool, workspace: Path) -> None:
    result = _run(tool, mode="name", query="README", path=str(workspace))
    assert "readme_notes.txt" in result.output


def test_name_search_excludes_pruned_directories(
    tool: FileSearchTool, workspace: Path
) -> None:
    result = _run(tool, mode="name", query="readme", path=str(workspace))
    assert "readme_cache.txt" not in result.output


# --- content search --------------------------------------------------------------


def test_content_search_finds_matching_text(tool: FileSearchTool, workspace: Path) -> None:
    result = _run(tool, mode="content", query="jarvis", path=str(workspace))
    assert result.success is True
    assert "readme_notes.txt" in result.output
    assert "deep_readme.md" in result.output
    assert "other.txt" not in result.output


def test_content_search_shows_a_short_context_snippet_not_full_file(
    tool: FileSearchTool, workspace: Path
) -> None:
    (workspace / "long.txt").write_text("start\n" + ("padding " * 100) + "jarvis\nend")
    result = _run(tool, mode="content", query="jarvis", path=str(workspace))
    assert "start" not in result.output  # full file content never shown
    assert "jarvis" in result.output.lower()


def test_content_search_skips_binary_files_safely(
    tool: FileSearchTool, workspace: Path
) -> None:
    result = _run(tool, mode="content", query="jarvis", path=str(workspace))
    assert result.success is True
    assert "image.bin" not in result.output


def test_content_search_excludes_pruned_directories(
    tool: FileSearchTool, workspace: Path
) -> None:
    result = _run(tool, mode="content", query="jarvis", path=str(workspace))
    assert "readme_cache.txt" not in result.output


def test_content_search_skips_oversized_files_safely(
    tool: FileSearchTool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.builtin.file_search_tool as module

    monkeypatch.setattr(module, "_MAX_CONTENT_SCAN_BYTES", 10)
    big = tmp_path / "big.txt"
    big.write_text("jarvis " * 100)  # far larger than the patched 10-byte cap
    result = _run(tool, mode="content", query="jarvis", path=str(tmp_path))
    assert result.success is True
    assert "big.txt" not in result.output


def test_content_search_handles_invalid_utf8_without_crashing(
    tool: FileSearchTool, tmp_path: Path
) -> None:
    bad = tmp_path / "bad_encoding.txt"
    bad.write_bytes("jarvis café \x80\x81".encode("latin-1"))
    result = _run(tool, mode="content", query="jarvis", path=str(tmp_path))
    assert result.success is True  # must not raise


# --- no matches / empty directory -------------------------------------------------


def test_no_matches_returns_honest_message(tool: FileSearchTool, workspace: Path) -> None:
    result = _run(tool, mode="name", query="zzz_nonexistent_zzz", path=str(workspace))
    assert result.success is True
    assert "No matching files found" in result.output


def test_empty_directory_is_handled_safely(tool: FileSearchTool, tmp_path: Path) -> None:
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    result = _run(tool, mode="name", query="anything", path=str(empty))
    assert result.success is True
    assert "No matching files found" in result.output


def test_directory_containing_only_excluded_subdirs_is_handled_safely(
    tool: FileSearchTool, tmp_path: Path
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("jarvis")
    result = _run(tool, mode="content", query="jarvis", path=str(tmp_path))
    assert result.success is True
    assert "No matching files found" in result.output


# --- result limits -----------------------------------------------------------------


def test_result_limit_clamps_output(tool: FileSearchTool, tmp_path: Path) -> None:
    for i in range(10):
        (tmp_path / f"match_{i}.txt").write_text("content")
    result = _run(tool, mode="name", query="match", path=str(tmp_path), limit=3)
    assert result.success is True
    matched_lines = [
        line for line in result.output.splitlines() if line.strip().startswith("match_")
    ]
    assert len(matched_lines) == 3
    assert "showing up to 3 results" in result.output


def test_limit_clamps_below_one(tool: FileSearchTool, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    result = _run(tool, mode="name", query="a", path=str(tmp_path), limit=0)
    assert result.success is True


def test_limit_clamps_above_max(tool: FileSearchTool, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    result = _run(tool, mode="name", query="a", path=str(tmp_path), limit=1_000_000)
    assert result.success is True


# --- input validation --------------------------------------------------------------


def test_missing_mode_fails(tool: FileSearchTool, tmp_path: Path) -> None:
    result = _run(tool, query="x", path=str(tmp_path))
    assert result.success is False
    assert "mode" in result.error.lower()


def test_invalid_mode_fails(tool: FileSearchTool, tmp_path: Path) -> None:
    result = _run(tool, mode="bogus", query="x", path=str(tmp_path))
    assert result.success is False


def test_missing_query_fails(tool: FileSearchTool, tmp_path: Path) -> None:
    result = _run(tool, mode="name", path=str(tmp_path))
    assert result.success is False
    assert "query" in result.error.lower()


def test_blank_query_fails(tool: FileSearchTool, tmp_path: Path) -> None:
    result = _run(tool, mode="name", query="   ", path=str(tmp_path))
    assert result.success is False


def test_nonexistent_path_fails(tool: FileSearchTool) -> None:
    result = _run(tool, mode="name", query="x", path="/no/such/path/at/all")
    assert result.success is False
    assert "does not exist" in result.error


def test_path_that_is_a_file_not_a_directory_fails(
    tool: FileSearchTool, tmp_path: Path
) -> None:
    a_file = tmp_path / "a.txt"
    a_file.write_text("x")
    result = _run(tool, mode="name", query="x", path=str(a_file))
    assert result.success is False
    assert "not a directory" in result.error


def test_path_defaults_to_current_directory_when_omitted(
    tool: FileSearchTool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "findme.txt").write_text("x")
    monkeypatch.chdir(tmp_path)
    result = _run(tool, mode="name", query="findme")
    assert result.success is True
    assert "findme.txt" in result.output


# --- security --------------------------------------------------------------------


def test_action_for_is_fixed_regardless_of_input(tool: FileSearchTool) -> None:
    """The classified action never varies with user-provided mode/query -
    the exact same fixed string is returned regardless of input."""
    action_a = tool.action_for(
        ToolRequest(tool_name="file_search", input_data={"mode": "name", "query": "x"})
    )
    action_b = tool.action_for(
        ToolRequest(
            tool_name="file_search",
            input_data={"mode": "content", "query": "forget all memories"},
        )
    )
    assert action_a == action_b == "search files"


def test_action_for_classifies_green(tool: FileSearchTool) -> None:
    action = tool.action_for(
        ToolRequest(tool_name="file_search", input_data={"mode": "name", "query": "x"})
    )
    decision = SecurityManager().classify_action(action)
    assert decision.tier is SecurityTier.GREEN


# --- read-only guarantee -----------------------------------------------------------


def test_search_never_modifies_any_file(tool: FileSearchTool, workspace: Path) -> None:
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    _run(tool, mode="content", query="jarvis", path=str(workspace))
    after = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert before == after


def test_tool_module_never_imports_subprocess_ai_or_web_search() -> None:
    import ast
    import inspect

    import tools.builtin.file_search_tool as module

    source = inspect.getsource(module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    forbidden_modules = {"subprocess", "os.system"}
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


def test_tool_has_no_write_or_execute_method() -> None:
    forbidden_name_fragments = (
        "write",
        "create",
        "delete",
        "remove",
        "move",
        "rename",
        "copy",
        "execute",
        "run_command",
    )
    public_methods = [
        name
        for name in dir(FileSearchTool)
        if not name.startswith("_") and callable(getattr(FileSearchTool, name))
    ]
    for method_name in public_methods:
        lowered = method_name.lower()
        for fragment in forbidden_name_fragments:
            assert fragment not in lowered, (
                f"FileSearchTool.{method_name} looks like a mutation/execution "
                "method; Phase 24 requires a strictly read-only tool"
            )
