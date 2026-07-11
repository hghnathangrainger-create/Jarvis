"""
test_main_pending_approval_wiring.py

Composition tests for PendingApprovalStore wiring in main.build_orchestrator()
(Phase 27, Batch 1).

These confirm build_orchestrator() wires a PendingApprovalStore into the
real ApprovalManager and reloads pending state on startup, without ever
needing a real database beyond a temp-file SQLite path, and without
changing build_orchestrator()'s own return type/signature.

Run with:
    pytest tests/unit/test_main_pending_approval_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from config.constants import SecurityTier


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    """Phase 27, Batch 1 must not change build_orchestrator()'s own
    signature - 26+ existing test files depend on it."""
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []


def test_approval_manager_has_a_pending_store_configured() -> None:
    orchestrator = main.build_orchestrator()
    assert orchestrator.approvals._pending_store is not None


def test_pending_approval_persists_across_a_fresh_orchestrator_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pending approval created through one build_orchestrator() call
    is durably visible to a completely separate one over the same
    database file - proving main.py's own wiring, not just
    ApprovalManager in isolation."""
    db_path = tmp_path / "shared_test_jarvis.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)

    orchestrator_one = main.build_orchestrator()
    request = orchestrator_one.approvals.create_request(
        "copy file",
        "reason",
        SecurityTier.YELLOW,
        tool_name="file_copy",
        tool_input={"source": "a.txt", "destination": "b.txt"},
    )

    # A second, independent build_orchestrator() call - reload_pending()
    # runs as part of its own composition, before returning.
    orchestrator_two = main.build_orchestrator()
    assert orchestrator_two.approvals.has_pending(request.request_id)
    state = orchestrator_two.approvals.get_pending_tool_state(request.request_id)
    assert state is not None
    assert state.tool_name == "file_copy"


def test_reload_never_executes_a_tool_on_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "shared_test_jarvis2.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)

    orchestrator_one = main.build_orchestrator()
    orchestrator_one.approvals.create_request(
        "copy file",
        "reason",
        SecurityTier.YELLOW,
        tool_name="file_copy",
        tool_input={
            "source": str(tmp_path / "does-not-exist.txt"),
            "destination": str(tmp_path / "also-does-not-exist.txt"),
        },
    )

    # Rebuilding must not raise or perform the copy, even though the
    # source file named in the persisted tool_input does not exist.
    main.build_orchestrator()
    assert not (tmp_path / "also-does-not-exist.txt").exists()
