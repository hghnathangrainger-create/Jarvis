"""
test_project_state_store.py

Unit tests for ProjectStateStore (Phase 89, Batch 1): the single,
durable, manually-maintained record of Jarvis's project context.

These use a real SQLite database (not a fake), exercising the same
storage layer Jarvis uses at runtime. A key set of tests locks in the
single-row/upsert boundary at the API-model level, mirroring
test_scheduled_inbox_notice_store.py's own established pattern exactly:
a second write never creates a second row, and only the requested
field changes.

Run with:
    pytest tests/unit/test_project_state_store.py
"""

from __future__ import annotations

import ast
import inspect

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from project_state.project_state_store import (
    UPDATABLE_FIELDS,
    ProjectStateRecord,
    ProjectStateStore,
)
from storage.database import create_session_factory, initialize_database, session_scope
from storage.models import ProjectState

import project_state.project_state_store as store_module


def _make_store() -> ProjectStateStore:
    """Build a ProjectStateStore backed by a fresh in-memory database."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ProjectStateStore(factory)


@pytest.fixture()
def store() -> ProjectStateStore:
    return _make_store()


# --- first-run / no-record behavior --------------------------------------------


def test_get_on_empty_store_returns_none(store: ProjectStateStore) -> None:
    assert store.get() is None


# --- update / upsert behavior ---------------------------------------------------


def test_first_update_inserts_the_singleton_row(store: ProjectStateStore) -> None:
    store.update("branch", "phase-4-ai-reasoning-and-write-actions")

    with session_scope(store._session_factory) as db:  # type: ignore[attr-defined]
        rows = db.query(ProjectState).all()
        assert len(rows) == 1
        assert rows[0].branch == "phase-4-ai-reasoning-and-write-actions"


def test_second_update_mutates_the_same_row_not_a_second_one(
    store: ProjectStateStore,
) -> None:
    store.update("branch", "main")
    store.update("branch", "phase-4-ai-reasoning-and-write-actions")

    with session_scope(store._session_factory) as db:  # type: ignore[attr-defined]
        rows = db.query(ProjectState).all()
        assert len(rows) == 1
        assert rows[0].branch == "phase-4-ai-reasoning-and-write-actions"


def test_update_only_changes_the_requested_field(store: ProjectStateStore) -> None:
    store.update("branch", "main")
    record = store.update("phase", "Phase 89")

    assert record.branch == "main"
    assert record.phase == "Phase 89"
    assert record.commit is None
    assert record.suite_result is None
    assert record.focus is None


def test_update_returns_a_record_reflecting_the_change(
    store: ProjectStateStore,
) -> None:
    record = store.update("commit", "d5c582d")
    assert isinstance(record, ProjectStateRecord)
    assert record.commit == "d5c582d"


def test_get_after_updates_reflects_all_stored_fields(
    store: ProjectStateStore,
) -> None:
    store.update("branch", "main")
    store.update("phase", "Phase 89")
    store.update("commit", "d5c582d")
    store.update("suite_result", "4204 passed, 3 skipped, 0 failed")
    store.update("focus", "manual project context")

    record = store.get()
    assert record is not None
    assert record.branch == "main"
    assert record.phase == "Phase 89"
    assert record.commit == "d5c582d"
    assert record.suite_result == "4204 passed, 3 skipped, 0 failed"
    assert record.focus == "manual project context"


def test_fields_never_updated_remain_none(store: ProjectStateStore) -> None:
    record = store.update("focus", "only focus set")
    assert record.branch is None
    assert record.phase is None
    assert record.commit is None
    assert record.suite_result is None


# --- last_updated behavior -------------------------------------------------------


def test_last_updated_is_set_on_first_write(store: ProjectStateStore) -> None:
    assert store.get() is None
    record = store.update("branch", "main")
    assert record.last_updated is not None


def test_last_updated_advances_on_every_write(store: ProjectStateStore) -> None:
    first = store.update("branch", "main")
    second = store.update("phase", "Phase 89")
    assert second.last_updated is not None
    assert first.last_updated is not None
    assert second.last_updated >= first.last_updated


def test_last_updated_is_none_before_any_write(store: ProjectStateStore) -> None:
    assert store.get() is None


# --- update() validates the field name -------------------------------------------


def test_update_rejects_an_unknown_field(store: ProjectStateStore) -> None:
    with pytest.raises(ValueError):
        store.update("not_a_real_field", "x")


def test_updatable_fields_matches_the_real_model_columns() -> None:
    assert UPDATABLE_FIELDS == frozenset(
        {"branch", "phase", "commit", "suite_result", "focus"}
    )


# --- persistence across sessions -------------------------------------------------


def test_record_persists_across_database_reopens(tmp_path) -> None:
    db_path = tmp_path / "project_state_persistence_check.db"

    write_engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(write_engine)
    write_store = ProjectStateStore(create_session_factory(write_engine))
    write_store.update("branch", "main")
    write_engine.dispose()

    read_engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(read_engine)
    read_store = ProjectStateStore(create_session_factory(read_engine))
    record = read_store.get()
    assert record is not None
    assert record.branch == "main"
    read_engine.dispose()


# --- structural: no live git/subprocess/filesystem detection ---------------------


def test_table_is_created_by_the_existing_initialize_database_call() -> None:
    from sqlalchemy import inspect as sa_inspect

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    inspector = sa_inspect(engine)
    assert "project_state" in inspector.get_table_names()


_FORBIDDEN_NAMES = {
    "AIRouter",
    "AIReasoningEngine",
    "PromptBuilder",
    "ClaudeProvider",
    "anthropic",
    "WebSearchProvider",
    "WebSearchTool",
    "CommandRouter",
    "core.command_router",
}
_FORBIDDEN_MODULES = {"subprocess", "os.system", "shutil", "git"}


def test_store_module_imports_no_forbidden_dependency() -> None:
    """Structural proof this store never reaches git, a subprocess, or
    any AI-provider/self-coding machinery - every field it persists
    comes only from an explicit update() call."""
    source = inspect.getsource(store_module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
            if node.module:
                imported_modules.add(node.module)
        elif isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)

    assert imported_names & _FORBIDDEN_NAMES == set()
    assert imported_modules & _FORBIDDEN_MODULES == set()


def test_store_module_calls_no_subprocess_or_os_system() -> None:
    source = inspect.getsource(store_module)
    for forbidden in ("subprocess.", "os.system(", "shutil."):
        assert forbidden not in source
