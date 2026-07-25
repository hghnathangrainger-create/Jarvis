"""
test_production_approval_wiring.py

Proves production claim enforcement cannot rely on ApprovalManager's
no-store test-compatibility fallback (Approval-to-Resume Handoff
Interlock, Batch 3 - docs/phase_98_approval_handoff_plan.md, Mandatory
issue 2).

`ApprovalManager.claim_for_resume()`/`mark_consumed()`/
`mark_claim_interrupted()` return a safe, successful compatibility value
when no `pending_store` is configured - correct for isolated legacy unit
tests, but production YELLOW execution must never rely on that
fallback. These tests prove: main.build_orchestrator() always
constructs its ApprovalManager with a real, durable PendingApprovalStore;
production claim_for_resume() always performs a real, rowcount-checked
CAS (never the bypass); the test-only no-store fallback exists but
cannot be reached from any real production entry point; and neither
dashboard.py nor scheduler.py imports ApprovalManager/JarvisOrchestrator
at all.

Run with:
    pytest tests/unit/test_production_approval_wiring.py
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

import main  # noqa: E402
from approval.approval_manager import ApprovalManager  # noqa: E402
from approval.approval_models import PendingApprovalHandoffStatus  # noqa: E402
from config.constants import SecurityTier  # noqa: E402
from config.settings import load_settings  # noqa: E402
from storage.database import create_database_engine, create_session_factory  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def hermetic_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "wiring_test_jarvis.db"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    return db_path


# --- production wiring: the durable store is always supplied -----------------


def test_build_orchestrator_approval_manager_has_a_durable_pending_store(
    hermetic_db: Path,
) -> None:
    orchestrator = main.build_orchestrator()
    # Reaching into the private collaborator is the only way to prove
    # the *real* constructed instance, not merely main.py's own source
    # text - matching this repository's own established convention
    # (test_paused_workflow_restart_end_to_end.py reaches into
    # orchestrator._workflow_engine the same way).
    assert orchestrator.approvals._pending_store is not None


def test_build_orchestrator_approval_manager_performs_a_real_cas(
    hermetic_db: Path,
) -> None:
    """A production-wired ApprovalManager's claim_for_resume() must
    return False for an unclaimed/unknown id - never the no-store
    bypass's unconditional True."""
    orchestrator = main.build_orchestrator()
    assert orchestrator.approvals.claim_for_resume("no-such-request-id") is False


def test_main_source_always_passes_pending_store_to_approval_manager() -> None:
    """Structural proof (AST-based, not brittle text search): every
    ApprovalManager(...) call in main.py's own source supplies
    pending_store as a keyword argument - except one, deliberately
    inert exception (Phase 98, Batch 3 -
    docs/phase_98_live_compound_reentry_plan.md): reconcile_claimed_
    handoffs()'s dedicated compound-recovery WorkflowEngine is
    constructed with a bare ApprovalManager() solely to satisfy
    WorkflowEngine's own required constructor argument, because that
    particular WorkflowEngine instance is only ever used for its own
    read-only reconstruct_claimed_compound_plan() accessor - which its
    own docstring guarantees "never mutates approval or paused-workflow
    state itself" - never run()/resume(), so no real CAS/claim path is
    ever reachable through it. Identified structurally (the `approvals=`
    value of the one WorkflowEngine(...) call whose `executor=` is
    `compound_executor`), never by a blanket carve-out."""
    source = (_REPO_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ApprovalManager"
    ]
    assert calls, "main.py must construct at least one ApprovalManager"

    def _is_inert_compound_recovery_exception(call: ast.Call) -> bool:
        for parent in ast.walk(tree):
            if not (
                isinstance(parent, ast.Call)
                and isinstance(parent.func, ast.Name)
                and parent.func.id == "WorkflowEngine"
            ):
                continue
            approvals_kw = next(
                (kw for kw in parent.keywords if kw.arg == "approvals"), None
            )
            executor_kw = next(
                (kw for kw in parent.keywords if kw.arg == "executor"), None
            )
            if (
                approvals_kw is not None
                and approvals_kw.value is call
                and executor_kw is not None
                and isinstance(executor_kw.value, ast.Name)
                and executor_kw.value.id == "compound_executor"
            ):
                return True
        return False

    for call in calls:
        keyword_names = {kw.arg for kw in call.keywords}
        if "pending_store" in keyword_names:
            continue
        assert _is_inert_compound_recovery_exception(call), (
            "every production ApprovalManager must receive pending_store, "
            "except the one, deliberately inert compound-recovery "
            "ApprovalManager() built only to satisfy WorkflowEngine's "
            "constructor for a read-only accessor"
        )


# --- test-only fallback exists, but cannot affect production -----------------


def test_bare_orchestrator_fallback_still_exists_for_test_compatibility() -> None:
    """The pre-existing JarvisOrchestrator() convenience default (no
    approval_manager supplied) is not removed - only ever exercised by
    isolated unit tests, never by main.build_orchestrator()."""
    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from planner.planner import Planner
    from security.security_manager import SecurityManager
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry

    class _NullLogger:
        def emit(self, **kwargs: object) -> str:
            return "1"

    security = SecurityManager()
    registry = ToolRegistry()
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=ToolExecutor(
            registry=registry, security_manager=security, logger=_NullLogger()
        ),
        registry=registry,
        command_router=CommandRouter(registry),
    )
    # The documented, safe, no-store compatibility behaviour: claiming
    # always "succeeds" because there is no durable state to race
    # against - correct for this isolated construction, never reachable
    # from main.build_orchestrator()'s own real production wiring.
    assert orchestrator.approvals._pending_store is None
    assert orchestrator.approvals.claim_for_resume("anything") is True


def test_no_store_fallback_is_unreachable_from_build_orchestrator(
    hermetic_db: Path,
) -> None:
    """The two constructions produce observably different ApprovalManager
    behaviour - proving build_orchestrator()'s own wiring is never the
    bare, no-store fallback."""
    orchestrator = main.build_orchestrator()
    bare = ApprovalManager()

    assert orchestrator.approvals._pending_store is not None
    assert bare._pending_store is None
    assert orchestrator.approvals.claim_for_resume("no-such-id") is False
    assert bare.claim_for_resume("no-such-id") is True


def test_durable_claim_actually_requires_prior_approved_unconsumed_state(
    hermetic_db: Path,
) -> None:
    """End-to-end proof the production wiring's CAS is real: a freshly
    created (never approved) request cannot be claimed; approving it
    (durably transitioning to APPROVED_UNCONSUMED) makes exactly one
    claim succeed, and a second claim fail."""
    orchestrator = main.build_orchestrator()
    approvals = orchestrator.approvals

    request = approvals.create_request(
        "copy file",
        "needs approval",
        SecurityTier.YELLOW,
        tool_name="file_copy",
        tool_input={"source": "a.txt", "destination": "b.txt"},
    )
    assert approvals.claim_for_resume(request.request_id) is False  # still PENDING

    approvals.approve(request.request_id)
    assert (
        approvals.handoff_status_for(request.request_id)
        == PendingApprovalHandoffStatus.APPROVED_UNCONSUMED
    )
    assert approvals.claim_for_resume(request.request_id) is True
    assert approvals.claim_for_resume(request.request_id) is False  # second claim fails


# --- scheduler/dashboard boundary -------------------------------------------


def test_scheduler_never_imports_approval_manager_or_orchestrator() -> None:
    source = (_REPO_ROOT / "scheduler.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        alias.name.split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "ApprovalManager" not in identifiers
    assert "JarvisOrchestrator" not in identifiers
    assert "WorkflowEngine" not in identifiers


def test_dashboard_never_imports_approval_manager_or_orchestrator() -> None:
    source = (_REPO_ROOT / "dashboard.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    identifiers = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        alias.name.split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "ApprovalManager" not in identifiers
    assert "JarvisOrchestrator" not in identifiers
    assert "WorkflowEngine" not in identifiers


def test_dashboard_module_has_no_write_or_execute_call_sites() -> None:
    """Mirrors the Batch 1 audit's own established grep-based proof:
    dashboard.py contains no write/mutate/execute call site of any kind."""
    source = (_REPO_ROOT / "dashboard.py").read_text(encoding="utf-8")
    for forbidden in (".approve(", ".decline(", ".claim_for_resume(", ".resume(", ".execute("):
        assert forbidden not in source


def test_dashboard_style_read_access_remains_functional_while_lock_held(
    hermetic_db: Path,
) -> None:
    """The execution lock is a separate sidecar file from the SQLite
    database itself - a real, independent read connection (mirroring
    dashboard.py's own composition-root pattern) must remain fully
    functional the entire time the lock is held."""
    from approval.approval_history_store import ApprovalHistoryStore
    from workflow.workflow_history_store import WorkflowHistoryStore

    orchestrator, lock = main.start_execution_session()
    try:
        assert lock.is_acquired is True

        request = orchestrator.approvals.create_request(
            "copy file",
            "needs approval",
            SecurityTier.YELLOW,
            tool_name="file_copy",
            tool_input={"source": "a.txt", "destination": "b.txt"},
        )

        # A second, independent read-only connection to the same
        # database file, exactly as dashboard.py's own composition root
        # builds one - never touches the lock file at all.
        settings = load_settings()
        read_engine = create_database_engine(settings)
        read_session_factory = create_session_factory(read_engine)
        history_reader = ApprovalHistoryStore(read_session_factory)
        workflow_reader = WorkflowHistoryStore(read_session_factory)

        entry = history_reader.get(request.request_id)
        assert entry is not None
        assert entry.status == "pending"
        assert workflow_reader.list_recent() == []  # no workflow activity yet; read succeeds
    finally:
        lock.release()
