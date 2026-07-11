"""
test_paused_workflow_restart_end_to_end.py

End-to-end integration test for a durable paused workflow surviving a
simulated process restart (Phase 27, Batch 2), driven through the real
production composition root (main.build_orchestrator()) and the real
Phase 15 "remember this and forget it: <text>" workflow command - not a
hand-built Plan.

This is the closest a test can come to proving a real process restart
without literally spawning a subprocess: it builds one full orchestrator,
pauses a real workflow on approval, discards every in-memory object, then
builds a completely separate orchestrator bound only to the same on-disk
SQLite database file, and proves the workflow reloads, requires an
explicit approval decision, and resumes correctly.

Run with:
    pytest tests/integration/test_paused_workflow_restart_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

import main
from config.constants import StepStatus


@pytest.fixture()
def hermetic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "shared_test_jarvis.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    return db_path


def test_paused_workflow_survives_restart_and_resumes_correctly(
    hermetic_db: Path,
) -> None:
    # --- "process one": pause a real workflow, then vanish. ---------------
    orchestrator_one = main.build_orchestrator()
    response = orchestrator_one.handle_request(
        "remember this and forget it: a secret to forget"
    )
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    request_id = response.approval_request.request_id
    workflow_id = response.approval_request.metadata.get("workflow_id")
    assert workflow_id is not None
    del orchestrator_one, response  # simulate crash

    # --- "process two": fresh orchestrator, same database file. -----------
    orchestrator_two = main.build_orchestrator()

    # reload happened inside build_orchestrator() itself - both the
    # approval and the paused workflow should already be back.
    assert orchestrator_two.approvals.has_pending(request_id)
    assert orchestrator_two._workflow_engine.has_paused(workflow_id)

    decision = orchestrator_two.approvals.approve(request_id)
    result = orchestrator_two._workflow_engine.resume(workflow_id, decision)

    assert result.overall_status is StepStatus.COMPLETED

    # The durable paused-workflow row is gone now that it resumed.
    from workflow.paused_workflow_store import PausedWorkflowStore

    from storage.database import create_session_factory, create_database_engine
    from config.settings import load_settings

    settings = load_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    assert PausedWorkflowStore(session_factory).get(workflow_id) is None


def test_build_orchestrator_signature_still_unchanged_after_batch_2() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
