"""
test_quarantine_list_tool.py

Unit tests for the Jarvis QuarantineListTool
(tools/builtin/quarantine_list_tool.py), Phase 36; extended Phase 37,
Batch 2 with original-path metadata display tests.

The tool is read-only: it lists whatever currently exists inside
.jarvis_trash/ (name, size, modified time, and - when a QuarantineStore
is supplied - the recorded original path), never reads file content,
never creates the quarantine directory, never writes quarantine
metadata, and never modifies, moves, or deletes anything. These tests
use real temporary directories (via tmp_path and monkeypatch.chdir), so
no database, AI, or network is needed for the Phase 36 behavior; the
Phase 37 metadata-display tests use a minimal fake store (matching
test_file_delete_tool.py's own _FakeQuarantineStore pattern), plus one
end-to-end test using a real QuarantineStore.

Run with:
    pytest tests/unit/test_quarantine_list_tool.py
"""

from __future__ import annotations

import ast
import os
import time
from pathlib import Path
from types import SimpleNamespace

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
# Original-path metadata display (Phase 37, Batch 2)
# ---------------------------------------------------------------------------


class _FakeQuarantineStore:
    """A minimal stand-in for QuarantineStore: returns a pre-seeded
    original_path for an exact quarantine_path match, or None otherwise.
    Records every lookup it receives so tests can confirm read-only use
    (get_by_quarantine_path only - never a write method)."""

    def __init__(self, records: dict[str, str] | None = None) -> None:
        self._records = dict(records or {})
        self.lookups: list[str] = []

    def get_by_quarantine_path(self, quarantine_path: str):
        self.lookups.append(quarantine_path)
        original_path = self._records.get(quarantine_path)
        if original_path is None:
            return None
        return SimpleNamespace(original_path=original_path)


def test_shows_original_path_when_metadata_exists(workspace: Path) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    quarantined = quarantine_dir / "notes__a1b2c3d4.txt"
    quarantined.write_text("content", encoding="utf-8")

    store = _FakeQuarantineStore(
        {str(quarantined.resolve()): str(workspace / "notes.txt")}
    )
    result = _run(QuarantineListTool(store))

    assert result.success is True
    assert f"original path: {workspace / 'notes.txt'}" in result.output


def test_shows_unknown_fallback_when_metadata_missing_but_store_present(
    workspace: Path,
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "orphan__eeeeeeee.txt").write_text(
        "content", encoding="utf-8"
    )

    store = _FakeQuarantineStore()
    result = _run(QuarantineListTool(store))

    assert result.success is True
    assert "original path: unknown" in result.output.lower()


def test_shows_unknown_fallback_when_no_store_supplied(workspace: Path) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "orphan__ffffffff.txt").write_text(
        "content", encoding="utf-8"
    )

    result = _run(QuarantineListTool())

    assert result.success is True
    assert "original path: unknown" in result.output.lower()


def test_does_not_infer_original_path_from_filename(workspace: Path) -> None:
    """The filename only ever preserves the stem/suffix (Phase 35) -
    never the original directory. With no metadata record, the tool
    must show an honest "unknown", never a guess derived from the
    filename itself."""
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "budget__12345678.txt").write_text(
        "content", encoding="utf-8"
    )

    result = _run(QuarantineListTool(_FakeQuarantineStore()))

    assert "original path: budget" not in result.output
    assert "original path: unknown" in result.output.lower()


def test_missing_metadata_does_not_crash(workspace: Path) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "solo__99999999.txt").write_text(
        "content", encoding="utf-8"
    )

    result = _run(QuarantineListTool(_FakeQuarantineStore()))

    assert result.success is True


def test_pre_existing_metadata_less_quarantined_file_is_listed(
    workspace: Path,
) -> None:
    """A file quarantined before Phase 37's metadata table existed
    (Phase 35/36) has no database row at all - simulated here by a
    store with no matching record. Listing must still succeed."""
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    old_file = quarantine_dir / "legacy__abcdef01.txt"
    old_file.write_text("content", encoding="utf-8")

    result = _run(QuarantineListTool(_FakeQuarantineStore()))

    assert result.success is True
    assert "legacy__abcdef01.txt" in result.output
    assert "original path: unknown" in result.output.lower()


def test_newly_quarantined_file_with_metadata_is_listed_with_original_path(
    workspace: Path,
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    quarantined = quarantine_dir / "fresh__abcdabcd.txt"
    quarantined.write_text("content", encoding="utf-8")

    store = _FakeQuarantineStore(
        {str(quarantined.resolve()): str(workspace / "fresh.txt")}
    )
    result = _run(QuarantineListTool(store))

    assert f"original path: {workspace / 'fresh.txt'}" in result.output


def test_known_and_unknown_entries_can_appear_together(workspace: Path) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    known = quarantine_dir / "known__11111111.txt"
    known.write_text("content", encoding="utf-8")
    unknown = quarantine_dir / "unknown__22222222.txt"
    unknown.write_text("content", encoding="utf-8")

    store = _FakeQuarantineStore({str(known.resolve()): str(workspace / "known.txt")})
    result = _run(QuarantineListTool(store))

    assert f"original path: {workspace / 'known.txt'}" in result.output
    assert "unknown__22222222.txt" in result.output
    lines = result.output.splitlines()
    unknown_line = next(line for line in lines if "unknown__22222222.txt" in line)
    assert "original path: unknown" in unknown_line.lower()


def test_lookup_uses_resolved_absolute_quarantine_path(
    workspace: Path,
) -> None:
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    quarantined = quarantine_dir / "check__33333333.txt"
    quarantined.write_text("content", encoding="utf-8")

    store = _FakeQuarantineStore()
    _run(QuarantineListTool(store))

    assert store.lookups == [str(quarantined.resolve())]


def test_no_metadata_written_during_listing(workspace: Path) -> None:
    """Confirms the store is only ever read, never written, during a
    listing - QuarantineListTool must not (and, since _FakeQuarantineStore
    exposes no write method at all, structurally cannot) call anything
    resembling record_quarantine()."""
    quarantine_dir = workspace / _QUARANTINE_DIR_NAME
    quarantine_dir.mkdir()
    (quarantine_dir / "readonly__44444444.txt").write_text(
        "content", encoding="utf-8"
    )

    store = _FakeQuarantineStore()
    assert not hasattr(store, "record_quarantine")

    result = _run(QuarantineListTool(store))

    assert result.success is True
    assert len(store.lookups) == 1


def test_end_to_end_with_real_quarantine_store(workspace: Path) -> None:
    """An end-to-end check using a real QuarantineStore (not a fake):
    quarantining a file via FileDeleteTool records metadata, and
    QuarantineListTool then displays that recorded original path -
    without QuarantineListTool ever adding a row itself."""
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine, func
    from sqlalchemy.orm import Session as OrmSession

    from quarantine.quarantine_store import QuarantineStore
    from storage.database import create_session_factory, initialize_database
    from storage.models import QuarantineRecord
    from tools.builtin.file_delete_tool import FileDeleteTool

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    store = QuarantineStore(create_session_factory(engine))

    source = workspace / "important.txt"
    source.write_text("content", encoding="utf-8")

    delete_result = FileDeleteTool(store).run(
        ToolRequest(tool_name="file_delete", input_data={"path": str(source)})
    )
    assert delete_result.success is True

    with OrmSession(engine) as session:
        row_count_before = session.query(func.count()).select_from(
            QuarantineRecord
        ).scalar()

    list_result = _run(QuarantineListTool(store))

    with OrmSession(engine) as session:
        row_count_after = session.query(func.count()).select_from(
            QuarantineRecord
        ).scalar()

    assert list_result.success is True
    assert f"original path: {source.resolve()}" in list_result.output
    assert row_count_after == row_count_before  # listing wrote nothing


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
