"""
test_pending_approval_handoff_schema.py

Schema and guarded-migration tests for
pending_approval_state.handoff_status (Approval-to-Resume Handoff
Interlock, Batch 1 - docs/phase_98_approval_handoff_plan.md).

Mirrors tests/unit/test_database.py's own real-SQLite-engine
convention (not a mock) and the pre-existing
_ensure_memory_category_column guarded-migration shape exactly, applied
to this new column instead.

Run with:
    pytest tests/unit/test_pending_approval_handoff_schema.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from storage.database import (  # noqa: E402
    _ensure_pending_approval_handoff_status_column,
    create_session_factory,
    initialize_database,
    session_scope,
)
from storage.models import (  # noqa: E402
    ApprovalHistoryEntry,
    PausedWorkflowState,
    PendingApprovalState,
)


def _create_pre_batch1_pending_approval_table(engine) -> None:
    """Hand-build the exact pending_approval_state schema as it existed
    immediately before this batch (no handoff_status column), to
    simulate a real, already-deployed database that predates this
    change."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE pending_approval_state (
                    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                    request_id VARCHAR(36) NOT NULL UNIQUE,
                    session_id INTEGER,
                    action TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    security_tier VARCHAR(16) NOT NULL,
                    metadata_json TEXT,
                    tool_name VARCHAR(128),
                    tool_input_json TEXT,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO pending_approval_state
                    (request_id, session_id, action, reason, security_tier,
                     metadata_json, tool_name, tool_input_json,
                     schema_version, created_at)
                VALUES
                    ('req-old-1', NULL, 'copy file', 'needs approval',
                     'yellow', '{}', NULL, NULL, 1, '2026-01-01 00:00:00')
                """
            )
        )


# --- fresh vs. migrated schema -------------------------------------------


def test_fresh_database_contains_handoff_status_column(tmp_path: Path) -> None:
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("pending_approval_state")}
    assert "handoff_status" in columns


def test_migration_adds_column_to_pre_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_pre_batch1_pending_approval_table(engine)

    inspector = inspect(engine)
    columns_before = {
        col["name"] for col in inspector.get_columns("pending_approval_state")
    }
    assert "handoff_status" not in columns_before

    _ensure_pending_approval_handoff_status_column(engine)

    inspector = inspect(engine)
    columns_after = {
        col["name"] for col in inspector.get_columns("pending_approval_state")
    }
    assert "handoff_status" in columns_after


def test_existing_rows_default_to_pending_after_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_pre_batch1_pending_approval_table(engine)
    _ensure_pending_approval_handoff_status_column(engine)

    factory = create_session_factory(engine)
    with session_scope(factory) as db:
        row = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-old-1")
            .one()
        )
        assert row.handoff_status == PendingApprovalHandoffStatus.PENDING.value
        # Every other pre-existing column must survive untouched.
        assert row.action == "copy file"
        assert row.reason == "needs approval"
        assert row.security_tier == "yellow"
        assert row.schema_version == 1


def test_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_pre_batch1_pending_approval_table(engine)

    _ensure_pending_approval_handoff_status_column(engine)
    _ensure_pending_approval_handoff_status_column(engine)  # must not raise
    _ensure_pending_approval_handoff_status_column(engine)  # a third time

    inspector = inspect(engine)
    columns = {col["name"] for col in inspector.get_columns("pending_approval_state")}
    assert "handoff_status" in columns

    factory = create_session_factory(engine)
    with session_scope(factory) as db:
        row = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-old-1")
            .one()
        )
        assert row.handoff_status == PendingApprovalHandoffStatus.PENDING.value


def test_fresh_and_migrated_schemas_behave_identically(tmp_path: Path) -> None:
    fresh_engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    initialize_database(fresh_engine)
    fresh_columns = {
        col["name"]
        for col in inspect(fresh_engine).get_columns("pending_approval_state")
    }

    migrated_engine = create_engine(f"sqlite:///{tmp_path / 'migrated.db'}")
    _create_pre_batch1_pending_approval_table(migrated_engine)
    initialize_database(migrated_engine)  # runs create_all + both guarded steps
    migrated_columns = {
        col["name"]
        for col in inspect(migrated_engine).get_columns("pending_approval_state")
    }

    assert fresh_columns == migrated_columns

    fresh_factory = create_session_factory(fresh_engine)
    with session_scope(fresh_factory) as db:
        db.add(
            PendingApprovalState(
                request_id="req-fresh",
                action="a",
                reason="r",
                security_tier="yellow",
            )
        )
    with session_scope(fresh_factory) as db:
        row = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-fresh")
            .one()
        )
        assert row.handoff_status == PendingApprovalHandoffStatus.PENDING.value


# --- neighbouring tables remain untouched --------------------------------


def test_existing_pending_approvals_remain_readable_after_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_pre_batch1_pending_approval_table(engine)
    initialize_database(engine)

    factory = create_session_factory(engine)
    with session_scope(factory) as db:
        row = (
            db.query(PendingApprovalState)
            .filter(PendingApprovalState.request_id == "req-old-1")
            .one()
        )
        assert row.action == "copy file"


def test_existing_paused_workflows_remain_readable_after_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_pre_batch1_pending_approval_table(engine)
    initialize_database(engine)  # create_all builds paused_workflow_state fresh

    factory = create_session_factory(engine)
    with session_scope(factory) as db:
        db.add(
            PausedWorkflowState(
                workflow_id="wf-1",
                request_id="req-old-1",
                user_request="do a thing",
                plan_steps_json="[]",
                completed_outcomes_json="[]",
                waiting_step_index=0,
                resolved_tool_input_json="{}",
            )
        )
    with session_scope(factory) as db:
        row = (
            db.query(PausedWorkflowState)
            .filter(PausedWorkflowState.workflow_id == "wf-1")
            .one()
        )
        assert row.request_id == "req-old-1"


def test_existing_approval_history_remains_readable_after_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "old.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_pre_batch1_pending_approval_table(engine)
    initialize_database(engine)

    factory = create_session_factory(engine)
    with session_scope(factory) as db:
        db.add(
            ApprovalHistoryEntry(
                request_id="req-old-1",
                action="copy file",
                reason="needs approval",
                security_tier="yellow",
                status="pending",
            )
        )
    with session_scope(factory) as db:
        row = (
            db.query(ApprovalHistoryEntry)
            .filter(ApprovalHistoryEntry.request_id == "req-old-1")
            .one()
        )
        assert row.status == "pending"


def test_no_process_instance_lock_table_exists(tmp_path: Path) -> None:
    """The database-row ProcessInstanceLock design was rejected (see
    docs/phase_98_approval_handoff_plan.md Section 11) in favour of the
    OS-enforced file lock - no such table is ever created."""
    db_path = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{db_path}")
    initialize_database(engine)

    table_names = set(inspect(engine).get_table_names())
    assert "process_instance_lock" not in table_names
    assert not any("processinstancelock" in name.lower().replace("_", "") for name in table_names)
