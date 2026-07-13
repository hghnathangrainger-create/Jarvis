"""
test_file_restore_tool.py

Unit tests for the Jarvis FileRestoreTool
(tools/builtin/file_restore_tool.py), Phase 38, Batch 1.

The tool restores exactly one previously-quarantined file back to its
recorded original path (Phase 37 metadata), moving it (never copying),
never overwriting an existing file, never creating the original parent
folder, and never restoring a file with no known metadata record.
These tests use real temporary directories (via tmp_path and
monkeypatch.chdir) plus a minimal fake QuarantineStore, so no real
database, AI, or network is needed.

Run with:
    pytest tests/unit/test_file_restore_tool.py
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.base_tool import ToolRequest
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME
from tools.builtin.file_restore_tool import FileRestoreTool


class _FakeQuarantineStore:
    """A minimal stand-in for QuarantineStore: returns a pre-seeded
    original_path for an exact quarantine_path match, or None
    otherwise. Records every lookup it receives."""

    def __init__(self, records: dict[str, str] | None = None) -> None:
        self._records = dict(records or {})
        self.lookups: list[str] = []

    def get_by_quarantine_path(self, quarantine_path: str):
        self.lookups.append(quarantine_path)
        original_path = self._records.get(quarantine_path)
        if original_path is None:
            return None
        return SimpleNamespace(original_path=original_path)


class _StrictFakeQuarantineStore(_FakeQuarantineStore):
    """Like _FakeQuarantineStore, but raises if any write-shaped method
    is ever called - proving FileRestoreTool never mutates quarantine
    metadata (QuarantineStore's only write method is record_quarantine();
    there is no update/delete/restore/cleanup method to call by
    mistake, Phase 37)."""

    def record_quarantine(self, **kwargs: object) -> None:
        raise AssertionError(
            "FileRestoreTool must never call record_quarantine() - "
            "restoring must never create, update, or delete quarantine "
            "metadata."
        )


def _run(tool: FileRestoreTool, **input_data: object):
    return tool.run(
        ToolRequest(tool_name="file_restore", input_data=dict(input_data))
    )


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def quarantine_dir(workspace: Path) -> Path:
    path = workspace / _QUARANTINE_DIR_NAME
    path.mkdir()
    return path


@pytest.fixture()
def quarantined_file(quarantine_dir: Path) -> Path:
    path = quarantine_dir / "notes__a1b2c3d4.txt"
    path.write_text("Hello Jarvis! This should be restored.", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Successful restore
# ---------------------------------------------------------------------------


def test_successful_restore_moves_file_back_to_original_path(
    workspace: Path, quarantined_file: Path
) -> None:
    original_path = workspace / "notes.txt"
    store = _FakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined_file.name)

    assert result.success is True
    assert original_path.exists()
    assert result.metadata["original_path"] == str(original_path)
    assert result.metadata["quarantine_path"] == str(quarantined_file.resolve())


def test_successful_restore_removes_file_from_quarantine(
    workspace: Path, quarantined_file: Path
) -> None:
    original_path = workspace / "notes.txt"
    store = _FakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    _run(tool, path=quarantined_file.name)

    assert not quarantined_file.exists()


def test_restored_content_is_preserved_byte_for_byte(
    workspace: Path, quarantine_dir: Path
) -> None:
    quarantined = quarantine_dir / "binary__eeeeeeee.bin"
    original_bytes = bytes(range(256))
    quarantined.write_bytes(original_bytes)
    original_path = workspace / "restored.bin"

    store = _FakeQuarantineStore({str(quarantined.resolve()): str(original_path)})
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined.name)

    assert result.success is True
    assert original_path.read_bytes() == original_bytes


def test_no_duplicate_remains_in_quarantine_after_success(
    workspace: Path, quarantine_dir: Path, quarantined_file: Path
) -> None:
    original_path = workspace / "notes.txt"
    store = _FakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    _run(tool, path=quarantined_file.name)

    assert list(quarantine_dir.iterdir()) == []


def test_no_metadata_record_is_mutated_on_success(
    workspace: Path, quarantined_file: Path
) -> None:
    """Restoring must never call QuarantineStore.record_quarantine() (its
    only write method) - the record remains untouched historical
    metadata."""
    original_path = workspace / "notes.txt"
    store = _StrictFakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined_file.name)

    assert result.success is True  # would have raised if record_quarantine() were called


# ---------------------------------------------------------------------------
# Missing input / missing file / missing metadata
# ---------------------------------------------------------------------------


def test_missing_input_fails_cleanly(workspace: Path, quarantine_dir: Path) -> None:
    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool)

    assert result.success is False
    assert store.lookups == []


def test_quarantine_file_missing_fails_cleanly(
    workspace: Path, quarantine_dir: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path="does_not_exist__ffffffff.txt")

    assert result.success is False
    assert "does not exist" in result.error.lower()


def test_no_metadata_record_fails_cleanly(
    workspace: Path, quarantined_file: Path
) -> None:
    store = _FakeQuarantineStore()  # no records seeded
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined_file.name)

    assert result.success is False
    assert "metadata" in result.error.lower()
    assert quarantined_file.exists()  # untouched - nothing was moved


def test_metadata_less_old_quarantined_file_is_not_restored(
    workspace: Path, quarantine_dir: Path
) -> None:
    """A file quarantined before Phase 37's metadata table existed
    (Phase 35/36) has no database row at all - simulated here by a
    store with no matching record."""
    legacy_file = quarantine_dir / "legacy__abcdef01.txt"
    legacy_file.write_text("pre-Phase-37 content", encoding="utf-8")

    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path=legacy_file.name)

    assert result.success is False
    assert legacy_file.exists()


# ---------------------------------------------------------------------------
# Path safety: outside quarantine, traversal, directory, symlink
# ---------------------------------------------------------------------------


def test_path_outside_quarantine_rejected(
    workspace: Path, quarantine_dir: Path
) -> None:
    outside_file = workspace / "outside.txt"
    outside_file.write_text("not quarantined", encoding="utf-8")

    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path=str(outside_file))

    assert result.success is False
    assert store.lookups == []  # rejected before any metadata lookup


def test_path_traversal_escaping_quarantine_rejected(
    workspace: Path, quarantine_dir: Path
) -> None:
    outside_file = workspace / "secret.txt"
    outside_file.write_text("should not be reachable", encoding="utf-8")

    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path="../secret.txt")

    assert result.success is False
    assert store.lookups == []
    assert outside_file.exists()  # completely untouched


def test_directory_source_inside_quarantine_rejected(
    workspace: Path, quarantine_dir: Path
) -> None:
    (quarantine_dir / "a_folder").mkdir()

    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path="a_folder")

    assert result.success is False
    assert "directory" in result.error.lower()
    assert store.lookups == []


def test_symlink_source_rejected(workspace: Path, quarantine_dir: Path) -> None:
    target = workspace / "real_target.txt"
    target.write_text("real content", encoding="utf-8")
    link = quarantine_dir / "link_to_target.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip(
            "Symlink creation is not permitted in this environment "
            "(requires elevated privileges/developer mode on Windows)."
        )

    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path="link_to_target.txt")

    assert result.success is False
    assert "symlink" in result.error.lower()
    assert store.lookups == []


# ---------------------------------------------------------------------------
# Destination behavior: never overwrite, never create parent folders
# ---------------------------------------------------------------------------


def test_original_path_already_exists_refuses_and_does_not_overwrite(
    workspace: Path, quarantined_file: Path
) -> None:
    original_path = workspace / "notes.txt"
    original_path.write_text("this must survive untouched", encoding="utf-8")

    store = _FakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined_file.name)

    assert result.success is False
    assert "already exists" in result.error.lower()
    assert original_path.read_text(encoding="utf-8") == "this must survive untouched"
    assert quarantined_file.exists()  # still in quarantine - nothing moved


def test_original_parent_directory_missing_refuses_and_does_not_create(
    workspace: Path, quarantined_file: Path
) -> None:
    missing_parent = workspace / "no_longer_here"
    original_path = missing_parent / "notes.txt"

    store = _FakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined_file.name)

    assert result.success is False
    assert not missing_parent.exists()  # never created
    assert quarantined_file.exists()  # still in quarantine - nothing moved


def test_restore_move_failure_fails_cleanly(
    workspace: Path, quarantined_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_path = workspace / "notes.txt"
    store = _FakeQuarantineStore(
        {str(quarantined_file.resolve()): str(original_path)}
    )
    tool = FileRestoreTool(store)

    def _raise_permission_error(self: Path, target: object) -> None:
        raise PermissionError("simulated permission error")

    monkeypatch.setattr(Path, "rename", _raise_permission_error)

    result = _run(tool, path=quarantined_file.name)

    assert result.success is False
    assert "permission" in result.error.lower()


# ---------------------------------------------------------------------------
# action_for()
# ---------------------------------------------------------------------------


def test_action_for_returns_fixed_string() -> None:
    tool = FileRestoreTool(_FakeQuarantineStore())
    request = ToolRequest(tool_name="file_restore", input_data={"path": "anything.txt"})
    assert tool.action_for(request) == "restore file"


def test_action_for_is_input_independent() -> None:
    tool = FileRestoreTool(_FakeQuarantineStore())
    a = ToolRequest(tool_name="file_restore", input_data={"path": "a.txt"})
    b = ToolRequest(tool_name="file_restore", input_data={"path": "../escape.txt"})
    assert tool.action_for(a) == tool.action_for(b) == "restore file"


# ---------------------------------------------------------------------------
# Metadata lookup behavior
# ---------------------------------------------------------------------------


def test_get_by_quarantine_path_is_used_for_lookup(
    workspace: Path, quarantined_file: Path
) -> None:
    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    _run(tool, path=quarantined_file.name)

    assert store.lookups == [str(quarantined_file.resolve())]


def test_original_path_is_never_inferred_from_quarantine_filename(
    workspace: Path, quarantine_dir: Path
) -> None:
    """The quarantine filename only ever preserves the original
    stem/suffix (Phase 35), never the original directory - with no
    metadata record, restore must refuse, never guess a location from
    the name itself."""
    quarantined = quarantine_dir / "budget__12345678.txt"
    quarantined.write_text("content", encoding="utf-8")

    store = _FakeQuarantineStore()
    tool = FileRestoreTool(store)

    result = _run(tool, path=quarantined.name)

    assert result.success is False
    assert not (workspace / "budget.txt").exists()


# ---------------------------------------------------------------------------
# Structural: no permanent-delete/copy APIs, no forbidden imports
# ---------------------------------------------------------------------------


def test_module_never_calls_permanent_delete_or_copy_apis() -> None:
    source = Path("tools/builtin/file_restore_tool.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden_calls = {"remove", "unlink", "rmtree", "rmdir", "copy", "copy2", "copyfile"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls, (
                f"forbidden call found: {node.func.attr}"
            )


def test_module_imports_no_forbidden_packages() -> None:
    source = Path("tools/builtin/file_restore_tool.py").read_text(encoding="utf-8")
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
        "web",
        "shutil",
    }
    assert not (imported_names & forbidden), imported_names
