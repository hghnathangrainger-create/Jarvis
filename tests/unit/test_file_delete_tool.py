"""
test_file_delete_tool.py

Unit tests for the Jarvis FileDeleteTool
(tools/builtin/file_delete_tool.py), Phase 35, Batch 1; extended
Batch 2 with adversarial quarantine safety tests; extended Phase 37,
Batch 1 with durable quarantine-metadata recording tests.

The tool is write-capable but deliberately not a real delete: it moves
one existing file into a Jarvis-managed quarantine directory
(.jarvis_trash/, relative to the current working directory), never
permanently destroying anything and never overwriting a file already
in quarantine. These tests use real temporary files/directories (via
tmp_path and monkeypatch.chdir), so no database, AI, or network is
needed.

Run with:
    pytest tests/unit/test_file_delete_tool.py
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from tools.base_tool import ToolRequest
from tools.builtin import FileDeleteTool
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME


@pytest.fixture()
def tool() -> FileDeleteTool:
    return FileDeleteTool()


def _run(tool: FileDeleteTool, **input_data: object):
    return tool.run(ToolRequest(tool_name="file_delete", input_data=dict(input_data)))


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def source_file(workspace: Path) -> Path:
    path = workspace / "notes.txt"
    path.write_text("Hello Jarvis! This should be quarantined.", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Successful quarantine
# ---------------------------------------------------------------------------


def test_successful_quarantine_of_a_normal_file(
    tool: FileDeleteTool, workspace: Path, source_file: Path
) -> None:
    result = _run(tool, path=str(source_file))

    assert result.success is True
    assert result.metadata["original_path"] == str(source_file)
    quarantine_path = Path(result.metadata["quarantine_path"])
    assert quarantine_path.exists()
    assert quarantine_path.read_text(encoding="utf-8") == (
        "Hello Jarvis! This should be quarantined."
    )


def test_source_no_longer_exists_at_original_path_after_success(
    tool: FileDeleteTool, workspace: Path, source_file: Path
) -> None:
    _run(tool, path=str(source_file))
    assert not source_file.exists()


def test_file_exists_in_quarantine_directory_after_success(
    tool: FileDeleteTool, workspace: Path, source_file: Path
) -> None:
    _run(tool, path=str(source_file))
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    assert quarantine_dir.is_dir()
    quarantined_files = list(quarantine_dir.iterdir())
    assert len(quarantined_files) == 1
    assert quarantined_files[0].stem.startswith("notes__")


def test_success_message_says_quarantined_not_permanently_deleted(
    tool: FileDeleteTool, workspace: Path, source_file: Path
) -> None:
    result = _run(tool, path=str(source_file))
    lowered = result.output.lower()
    assert "quarantine" in lowered
    assert "not permanently deleted" in lowered
    assert "deleted forever" not in lowered


def test_quarantine_directory_is_created_on_demand(
    tool: FileDeleteTool, workspace: Path, source_file: Path
) -> None:
    assert not (workspace / _QUARANTINE_DIR_NAME).exists()
    _run(tool, path=str(source_file))
    assert (workspace / _QUARANTINE_DIR_NAME).is_dir()


# ---------------------------------------------------------------------------
# Missing / invalid input
# ---------------------------------------------------------------------------


def test_missing_path_input_fails_cleanly(tool: FileDeleteTool, workspace: Path) -> None:
    result = _run(tool)
    assert result.success is False
    assert "path" in result.error.lower()


def test_whitespace_only_path_input_fails_cleanly(
    tool: FileDeleteTool, workspace: Path
) -> None:
    result = _run(tool, path="   ")
    assert result.success is False


def test_nonexistent_source_fails_cleanly(tool: FileDeleteTool, workspace: Path) -> None:
    result = _run(tool, path=str(workspace / "does_not_exist.txt"))
    assert result.success is False
    assert "does not exist" in result.error.lower()


def test_directory_source_is_rejected(tool: FileDeleteTool, workspace: Path) -> None:
    a_directory = workspace / "a_folder"
    a_directory.mkdir()
    result = _run(tool, path=str(a_directory))
    assert result.success is False
    assert "directory" in result.error.lower()
    assert a_directory.exists()


# ---------------------------------------------------------------------------
# Symlinks: rejected explicitly
# ---------------------------------------------------------------------------


def test_symlink_source_is_rejected(tool: FileDeleteTool, workspace: Path) -> None:
    target = workspace / "real_target.txt"
    target.write_text("real content", encoding="utf-8")
    link = workspace / "link_to_target.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip(
            "Symlink creation is not permitted in this environment "
            "(requires elevated privileges/developer mode on Windows)."
        )

    result = _run(tool, path=str(link))

    assert result.success is False
    assert "symlink" in result.error.lower()
    assert link.exists()  # untouched
    assert target.exists()  # untouched


# ---------------------------------------------------------------------------
# Already-quarantined source
# ---------------------------------------------------------------------------


def test_source_already_inside_quarantine_is_rejected(
    tool: FileDeleteTool, workspace: Path
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    already_quarantined = quarantine_dir / "already_here.txt"
    already_quarantined.write_text("already quarantined", encoding="utf-8")

    result = _run(tool, path=str(already_quarantined))

    assert result.success is False
    assert "already been quarantined" in result.error.lower()
    assert already_quarantined.exists()  # untouched


# ---------------------------------------------------------------------------
# Naming/collision behavior
# ---------------------------------------------------------------------------


def test_two_same_named_files_can_both_be_quarantined_without_overwrite(
    tool: FileDeleteTool, workspace: Path
) -> None:
    dir_a = workspace / "a"
    dir_b = workspace / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    file_a = dir_a / "notes.txt"
    file_b = dir_b / "notes.txt"
    file_a.write_text("content from a", encoding="utf-8")
    file_b.write_text("content from b", encoding="utf-8")

    result_a = _run(tool, path=str(file_a))
    result_b = _run(tool, path=str(file_b))

    assert result_a.success is True
    assert result_b.success is True
    quarantine_path_a = Path(result_a.metadata["quarantine_path"])
    quarantine_path_b = Path(result_b.metadata["quarantine_path"])

    assert quarantine_path_a != quarantine_path_b
    assert quarantine_path_a.exists()
    assert quarantine_path_b.exists()
    assert quarantine_path_a.read_text(encoding="utf-8") == "content from a"
    assert quarantine_path_b.read_text(encoding="utf-8") == "content from b"


def test_destination_collision_is_avoided_via_retry(
    tool: FileDeleteTool,
    workspace: Path,
    source_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forces the first two short-suffix attempts to collide with an
    already-occupied name, proving the retry loop moves on to a fresh
    attempt rather than overwriting the occupied file or failing."""
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    fixed_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    occupied_name = f"{source_file.stem}__{fixed_uuid.hex[:8]}{source_file.suffix}"
    occupied_path = quarantine_dir / occupied_name
    occupied_path.write_text("occupying this exact name", encoding="utf-8")

    real_uuid4 = uuid.uuid4
    calls = iter([fixed_uuid, fixed_uuid, real_uuid4()])
    monkeypatch.setattr(
        "tools.builtin.file_delete_tool.uuid.uuid4", lambda: next(calls)
    )

    result = _run(tool, path=str(source_file))

    assert result.success is True
    assert Path(result.metadata["quarantine_path"]) != occupied_path
    # The pre-existing occupied file must never have been touched.
    assert occupied_path.read_text(encoding="utf-8") == "occupying this exact name"


# ---------------------------------------------------------------------------
# Adversarial quarantine safety (Batch 2)
# ---------------------------------------------------------------------------


def test_path_traversal_source_cannot_escape_the_quarantine_directory(
    tool: FileDeleteTool, workspace: Path
) -> None:
    """The quarantine destination is always built from source.stem/
    source.suffix (Path's own last-component name parsing), never from
    the full source path string - so a source path containing ".."
    components has no way to influence where inside .jarvis_trash/ the
    quarantined copy ends up. Proven here with a source path that
    itself contains ".." segments (still resolving to a real file)."""
    nested = workspace / "a" / "b"
    nested.mkdir(parents=True)
    real_file = nested / "secret.txt"
    real_file.write_text("sensitive content", encoding="utf-8")

    traversal_path = workspace / "a" / ".." / "a" / "b" / "secret.txt"
    assert traversal_path.resolve() == real_file.resolve()

    result = _run(tool, path=str(traversal_path))

    assert result.success is True
    quarantine_path = Path(result.metadata["quarantine_path"])
    quarantine_dir = (workspace / _QUARANTINE_DIR_NAME).resolve()
    # The quarantined file lands directly inside the quarantine
    # directory, one level deep - never nested further, and never
    # outside it - regardless of the ".." segments in the source path.
    assert quarantine_path.resolve().parent == quarantine_dir
    assert ".." not in quarantine_path.parts
    assert quarantine_path.read_text(encoding="utf-8") == "sensitive content"


def test_original_parent_directory_is_not_removed_after_quarantine(
    tool: FileDeleteTool, workspace: Path
) -> None:
    nested = workspace / "keep_this_folder"
    nested.mkdir()
    nested_file = nested / "notes.txt"
    nested_file.write_text("content", encoding="utf-8")

    result = _run(tool, path=str(nested_file))

    assert result.success is True
    assert nested.exists()  # the now-empty parent folder is untouched
    assert nested.is_dir()


def test_quarantine_directory_itself_is_rejected_as_a_source(
    tool: FileDeleteTool, workspace: Path
) -> None:
    """The quarantine directory is a directory, not a file - rejected by
    the same is_dir() check every other directory source hits, proven
    explicitly for this specific, security-relevant directory."""
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()

    result = _run(tool, path=str(quarantine_dir))

    assert result.success is False
    assert "directory" in result.error.lower()
    assert quarantine_dir.exists()


def test_absolute_and_relative_paths_behave_consistently(
    tool: FileDeleteTool, workspace: Path
) -> None:
    relative_file = workspace / "relative.txt"
    relative_file.write_text("via relative path", encoding="utf-8")
    absolute_file = workspace / "absolute.txt"
    absolute_file.write_text("via absolute path", encoding="utf-8")

    relative_result = _run(tool, path="relative.txt")
    absolute_result = _run(tool, path=str(absolute_file.resolve()))

    assert relative_result.success is True
    assert absolute_result.success is True
    assert Path(relative_result.metadata["quarantine_path"]).read_text(
        encoding="utf-8"
    ) == "via relative path"
    assert Path(absolute_result.metadata["quarantine_path"]).read_text(
        encoding="utf-8"
    ) == "via absolute path"


def test_binary_and_special_character_content_is_preserved_byte_for_byte(
    tool: FileDeleteTool, workspace: Path
) -> None:
    source = workspace / "binary.dat"
    payload = bytes(range(256)) + "special: café \n\t\r".encode("utf-8")
    source.write_bytes(payload)

    result = _run(tool, path=str(source))

    assert result.success is True
    quarantine_path = Path(result.metadata["quarantine_path"])
    assert quarantine_path.read_bytes() == payload


# ---------------------------------------------------------------------------
# Move failure
# ---------------------------------------------------------------------------


def test_move_failure_returns_a_clean_result(
    tool: FileDeleteTool,
    workspace: Path,
    source_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_permission_error(self: Path, target: object) -> None:
        raise PermissionError("simulated permission error")

    monkeypatch.setattr(Path, "rename", _raise_permission_error)

    result = _run(tool, path=str(source_file))

    assert result.success is False
    assert "permission" in result.error.lower()
    assert source_file.exists()  # never actually moved


# ---------------------------------------------------------------------------
# action_for()
# ---------------------------------------------------------------------------


def test_action_for_returns_fixed_string_regardless_of_path(
    tool: FileDeleteTool,
) -> None:
    request = ToolRequest(
        tool_name="file_delete", input_data={"path": "some/adversarial/path.txt"}
    )
    assert tool.action_for(request) == "delete file"


def test_action_for_fixed_even_with_no_input(tool: FileDeleteTool) -> None:
    request = ToolRequest(tool_name="file_delete", input_data={})
    assert tool.action_for(request) == "delete file"


# ---------------------------------------------------------------------------
# Structural: no permanent-delete APIs, no forbidden imports
# ---------------------------------------------------------------------------


def test_module_never_calls_permanent_delete_apis() -> None:
    source = Path("tools/builtin/file_delete_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_calls = {"remove", "unlink", "rmtree", "rmdir"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls, (
                f"forbidden call found: {node.func.attr}"
            )


def test_module_imports_no_forbidden_packages() -> None:
    source = Path("tools/builtin/file_delete_tool.py").read_text(encoding="utf-8")
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
        "shutil",
    }
    assert not (imported_names & forbidden), imported_names


# ---------------------------------------------------------------------------
# Quarantine metadata recording (Phase 37, Batch 1)
# ---------------------------------------------------------------------------


class _FakeQuarantineStore:
    """A minimal stand-in for QuarantineStore, recording every call it
    receives and optionally raising to simulate a recording failure."""

    def __init__(self, *, raise_on_record: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._raise_on_record = raise_on_record

    def record_quarantine(
        self,
        *,
        original_path: str,
        quarantine_path: str,
        session_id: int | None = None,
    ) -> None:
        self.calls.append(
            {
                "original_path": original_path,
                "quarantine_path": quarantine_path,
                "session_id": session_id,
            }
        )
        if self._raise_on_record is not None:
            raise self._raise_on_record


def test_successful_quarantine_writes_exactly_one_metadata_record(
    workspace: Path, source_file: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    result = _run(tool, path=str(source_file))

    assert result.success is True
    assert len(store.calls) == 1


def test_metadata_original_path_matches_resolved_source(
    workspace: Path, source_file: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    _run(tool, path=str(source_file))

    assert store.calls[0]["original_path"] == str(source_file.resolve())


def test_metadata_quarantine_path_matches_the_actual_quarantined_path(
    workspace: Path, source_file: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    result = _run(tool, path=str(source_file))

    expected = str(Path(result.metadata["quarantine_path"]).resolve())
    assert store.calls[0]["quarantine_path"] == expected


def test_metadata_records_session_id_from_the_request(
    workspace: Path, source_file: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    tool.run(
        ToolRequest(
            tool_name="file_delete",
            input_data={"path": str(source_file)},
            session_id=42,
        )
    )

    assert store.calls[0]["session_id"] == 42


def test_missing_path_input_writes_no_metadata(workspace: Path) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    _run(tool)

    assert store.calls == []


def test_nonexistent_source_writes_no_metadata(workspace: Path) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    _run(tool, path=str(workspace / "does_not_exist.txt"))

    assert store.calls == []


def test_directory_source_writes_no_metadata(workspace: Path) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)
    a_directory = workspace / "a_folder"
    a_directory.mkdir()

    _run(tool, path=str(a_directory))

    assert store.calls == []


def test_symlink_source_writes_no_metadata(workspace: Path) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)
    target = workspace / "real_target.txt"
    target.write_text("real content", encoding="utf-8")
    link = workspace / "link_to_target.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip(
            "Symlink creation is not permitted in this environment "
            "(requires elevated privileges/developer mode on Windows)."
        )

    _run(tool, path=str(link))

    assert store.calls == []


def test_already_quarantined_source_writes_no_metadata(workspace: Path) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    already_quarantined = quarantine_dir / "already_here.txt"
    already_quarantined.write_text("already quarantined", encoding="utf-8")

    _run(tool, path=str(already_quarantined))

    assert store.calls == []


def test_move_failure_writes_no_metadata(
    workspace: Path, source_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    def _raise_permission_error(self: Path, target: object) -> None:
        raise PermissionError("simulated permission error")

    monkeypatch.setattr(Path, "rename", _raise_permission_error)

    result = _run(tool, path=str(source_file))

    assert result.success is False
    assert store.calls == []


def test_metadata_write_failure_is_disclosed_honestly_not_hidden(
    workspace: Path, source_file: Path
) -> None:
    """The file is genuinely quarantined even when metadata recording
    fails - that must never be hidden or contradicted - but the result
    must not look like an ordinary, fully-successful quarantine either."""
    store = _FakeQuarantineStore(raise_on_record=RuntimeError("simulated DB failure"))
    tool = FileDeleteTool(store)

    result = _run(tool, path=str(source_file))

    assert result.success is True  # the move really did happen
    assert not source_file.exists()  # confirmed: it moved
    assert "WARNING" in result.output
    assert "simulated DB failure" in result.output
    assert result.metadata["metadata_recorded"] == "False"
    quarantine_path = Path(result.metadata["quarantine_path"])
    assert quarantine_path.exists()  # the file is safe, just unrecorded


def test_successful_metadata_recording_sets_recorded_flag_true(
    workspace: Path, source_file: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileDeleteTool(store)

    result = _run(tool, path=str(source_file))

    assert result.metadata["metadata_recorded"] == "True"
    assert "WARNING" not in result.output


def test_no_store_preserves_original_behavior_with_no_metadata_key(
    workspace: Path, source_file: Path
) -> None:
    """Backward compatibility: a tool constructed with no store (every
    pre-Phase-37 caller) behaves exactly as before - no
    "metadata_recorded" key at all, no warning text."""
    tool = FileDeleteTool()

    result = _run(tool, path=str(source_file))

    assert result.success is True
    assert "metadata_recorded" not in result.metadata
    assert "WARNING" not in result.output
