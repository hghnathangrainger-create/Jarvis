"""
test_approval_manager_logger_isolation.py

Focused tests for the Phase 15 Batch 4B corrective closure: ApprovalManager's
own _audit()/_audit_timeout() logger.emit() calls must never let a failing
logger alter an otherwise-authoritative approval decision, timeout, or
caller-visible control flow.

Empirically proven (not assumed) defect this closes: _audit() ran *after*
approve()/decline() had already removed the request from _pending and
recorded the decision in _decisions; _audit_timeout() ran after
_sweep_expired() had already popped an expired request from _pending. A
raising logger therefore propagated out of approve()/decline()/
get_pending()/list_pending()/has_pending() - even when has_pending() was
checking a request_id entirely unrelated to whichever request happened to
expire - silently orphaning an already-decided or already-expired request:
the caller (and, for a Phase 15 workflow, WorkflowEngine.resume()) never
received the decision, the durable ApprovalHistoryStore write for it was
skipped, and a paused workflow could be left permanently stuck.

Run with:
    pytest tests/unit/test_approval_manager_logger_isolation.py
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone

import pytest

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from config.constants import EventOutcome, SecurityTier

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FailingLogger:
    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("simulated logger failure")


class _RecordingHistory:
    """A fake ApprovalHistoryStore-shaped recorder, to prove the durable
    history write now reliably happens even when the audit logger fails."""

    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.decisions: list[dict[str, object]] = []
        self.timeouts: list[dict[str, object]] = []

    def record_request(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return len(self.requests)

    def record_decision(self, **kwargs: object) -> object:
        self.decisions.append(kwargs)
        return len(self.decisions)

    def record_timeout(self, **kwargs: object) -> object:
        self.timeouts.append(kwargs)
        return len(self.timeouts)


def _manager(
    *, logger: object | None = None, history: object | None = None, **kwargs: object
) -> ApprovalManager:
    return ApprovalManager(audit_logger=logger, history_store=history, **kwargs)  # type: ignore[arg-type]


# --- create_request (no audit call exists here - confirmed no defect) -------


def test_create_request_survives_raising_logger() -> None:
    """create_request() never calls the audit logger at all (only approve/
    decline/timeout do) - confirmed by direct inspection - so this was
    never actually vulnerable; this test proves it explicitly rather than
    assuming."""
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    assert manager.has_pending(request.request_id) is True


def test_create_request_does_not_create_duplicate_with_raising_logger() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    assert len(manager.list_pending()) == 1
    assert manager.list_pending()[0].request_id == request.request_id


# --- approve() ----------------------------------------------------------------


def test_approve_survives_raising_logger() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    decision = manager.approve(request.request_id)
    assert decision.is_approved is True


def test_approved_decision_is_authoritative_and_retrievable() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    manager.approve(request.request_id)
    assert manager.get_decision(request.request_id).is_approved is True
    assert manager.has_pending(request.request_id) is False


def test_approved_history_write_now_reliably_reached_despite_raising_logger() -> (
    None
):
    """Positive side effect of the fix: the durable history write, which
    was previously skipped entirely when the audit logger raised (since
    the exception propagated before _record_history_decision was ever
    reached), now reliably happens."""
    history = _RecordingHistory()
    manager = _manager(logger=_FailingLogger(), history=history)
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    manager.approve(request.request_id)
    assert len(history.decisions) == 1
    assert history.decisions[0]["approved"] is True


def test_second_approve_after_raising_logger_still_raises_approval_error() -> (
    None
):
    """Idempotency is not weakened: the request is genuinely gone from
    pending after the first approve(), regardless of logger health."""
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    manager.approve(request.request_id)
    with pytest.raises(ApprovalError):
        manager.approve(request.request_id)


# --- decline() ----------------------------------------------------------------


def test_decline_survives_raising_logger() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    decision = manager.decline(request.request_id)
    assert decision.is_declined is True


def test_declined_decision_is_authoritative_and_retrievable() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    manager.decline(request.request_id)
    assert manager.get_decision(request.request_id).is_declined is True


def test_declined_history_write_now_reliably_reached_despite_raising_logger() -> (
    None
):
    history = _RecordingHistory()
    manager = _manager(logger=_FailingLogger(), history=history)
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    manager.decline(request.request_id)
    assert len(history.decisions) == 1
    assert history.decisions[0]["approved"] is False


def test_second_decision_after_raising_logger_still_raises() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    manager.decline(request.request_id)
    with pytest.raises(ApprovalError):
        manager.decline(request.request_id)


# --- timeout/expiry -------------------------------------------------------------


def test_expired_request_removed_and_no_exception_with_raising_logger() -> None:
    clock = _FakeClock(_START)
    manager = _manager(logger=_FailingLogger(), timeout_seconds=60, clock=clock)
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    clock.now = _START + timedelta(seconds=61)
    assert manager.has_pending(request.request_id) is False


def test_expiry_does_not_create_a_decision_despite_raising_logger() -> None:
    clock = _FakeClock(_START)
    manager = _manager(logger=_FailingLogger(), timeout_seconds=60, clock=clock)
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    clock.now = _START + timedelta(seconds=61)
    manager.has_pending(request.request_id)  # triggers the sweep
    with pytest.raises(ApprovalError):
        manager.get_decision(request.request_id)


def test_unrelated_request_check_no_longer_corrupted_by_a_different_expiring_request() -> (
    None
):
    """The exact cross-contamination defect empirically reproduced during
    this batch's investigation: checking req2 must not raise merely
    because req1 happens to expire during the same sweep."""
    clock = _FakeClock(_START)
    manager = _manager(logger=_FailingLogger(), timeout_seconds=60, clock=clock)
    req1 = manager.create_request(
        action="delete something", reason="r1", security_tier=SecurityTier.YELLOW
    )
    req2 = manager.create_request(
        action="delete something else", reason="r2", security_tier=SecurityTier.YELLOW
    )
    clock.now = _START + timedelta(seconds=61)
    assert manager.has_pending(req2.request_id) is False  # req2 itself also expired
    assert req1.request_id not in manager._pending


def test_timeout_history_reliably_reached_despite_raising_logger() -> None:
    history = _RecordingHistory()
    clock = _FakeClock(_START)
    manager = _manager(
        logger=_FailingLogger(), history=history, timeout_seconds=60, clock=clock
    )
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    clock.now = _START + timedelta(seconds=61)
    manager.has_pending(request.request_id)
    assert len(history.timeouts) == 1
    assert history.timeouts[0]["request_id"] == request.request_id


def test_no_timeout_configured_is_unaffected() -> None:
    manager = _manager(logger=_FailingLogger())
    request = manager.create_request(
        action="delete something", reason="r", security_tier=SecurityTier.YELLOW
    )
    assert manager.has_pending(request.request_id) is True


# --- Invalid/duplicate errors not swallowed -------------------------------------


def test_unknown_request_id_still_raises_approval_error() -> None:
    manager = _manager(logger=_FailingLogger())
    with pytest.raises(ApprovalError):
        manager.approve("does-not-exist")


def test_get_decision_for_unknown_id_still_raises() -> None:
    manager = _manager(logger=_FailingLogger())
    with pytest.raises(ApprovalError):
        manager.get_decision("does-not-exist")


# --- Structural proof: isolation scoped only to emit() --------------------------


def test_emit_audit_event_helper_exists_and_wraps_only_emit() -> None:
    import approval.approval_manager as module

    tree = ast.parse(inspect.getsource(module))
    except_handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and getattr(node.type, "id", None) == "Exception"
    ]
    assert len(except_handlers) == 1


def test_logger_isolation_except_block_body_is_a_single_pass() -> None:
    import textwrap

    import approval.approval_manager as module

    source = textwrap.dedent(
        inspect.getsource(module.ApprovalManager._emit_audit_event)
    )
    tree = ast.parse(source)
    except_handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and getattr(node.type, "id", None) == "Exception"
    ]
    assert len(except_handlers) == 1
    body = except_handlers[0].body
    assert len(body) == 1
    assert isinstance(body[0], ast.Pass)


def test_no_state_mutation_occurs_inside_emit_audit_event() -> None:
    """Structural proof via real AST attribute-access inspection (not
    substring search, which would also match this method's own prose
    docstring): _emit_audit_event only ever reads/writes
    self._audit_logger - never self._pending, self._decisions, or
    self._history."""
    import textwrap

    import approval.approval_manager as module

    source = textwrap.dedent(
        inspect.getsource(module.ApprovalManager._emit_audit_event)
    )
    tree = ast.parse(source)

    accessed_self_attrs = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    }
    assert accessed_self_attrs == {"_audit_logger"}


def test_all_audit_sites_use_the_shared_helper() -> None:
    import approval.approval_manager as module

    tree = ast.parse(inspect.getsource(module))

    def _count_calls(attr_name: str) -> int:
        return sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr_name
        )

    # 3 call sites: _audit() (decide), _audit_timeout() (expire), and
    # _audit_reload_invalidation() (Phase 27, Batch 1 - a pending row that
    # fails reload revalidation) - all three reuse this one isolated
    # helper rather than calling self._audit_logger.emit() directly.
    assert _count_calls("_emit_audit_event") == 3
    assert _count_calls("emit") == 1


def test_approval_error_and_timeout_are_not_swallowed_by_isolation() -> None:
    """The logger-isolation try/except is scoped to _emit_audit_event only
    - ApprovalError from get_pending()/_decide() must still propagate
    normally."""
    manager = _manager(logger=_RecordingLogger())
    with pytest.raises(ApprovalError):
        manager.get_pending("does-not-exist")


# --- Ordinary (non-workflow) end-to-end proof, real Orchestrator ------------


def _ordinary_orchestrator(approvals_logger: object):
    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from planner.planner import Planner
    from security.security_manager import SecurityManager
    from tools.builtin import FileCreateTool
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry

    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCreateTool())
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_RecordingLogger()  # type: ignore[arg-type]
    )
    approvals = ApprovalManager(audit_logger=approvals_logger)  # type: ignore[arg-type]
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
        security_manager=security,
    )
    return orchestrator


def test_ordinary_yellow_approval_survives_raising_approval_manager_logger(
    tmp_path,
) -> None:
    orchestrator = _ordinary_orchestrator(_FailingLogger())
    target = tmp_path / "not_written.txt"
    response = orchestrator.handle_request(
        f"create file {target} with content hello"
    )
    assert response.requires_confirmation is True
    decision = orchestrator.approvals.approve(response.approval_request.request_id)
    assert decision.is_approved is True

    resumed = orchestrator.execute_approved(response, decision)
    assert resumed.success is True
    assert target.exists()


def test_ordinary_decline_survives_raising_approval_manager_logger(tmp_path) -> None:
    orchestrator = _ordinary_orchestrator(_FailingLogger())
    target = tmp_path / "not_written2.txt"
    response = orchestrator.handle_request(
        f"create file {target} with content hello"
    )
    decision = orchestrator.approvals.decline(response.approval_request.request_id)
    assert decision.is_declined is True

    resumed = orchestrator.execute_approved(response, decision)
    assert resumed.success is False
    assert not target.exists()


# --- Phase 15 workflow proof with the ApprovalManager logger specifically ---
# (not the ToolExecutor logger - see test_tool_executor_logger_isolation.py
# and test_cli_workflow_commands.py for that separate, already-closed
# boundary).


def _workflow_orchestrator(approvals_logger: object):
    import sqlalchemy  # noqa: F401 - import guard, matches repo convention

    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from memory.episodic_memory import EpisodicMemoryStore
    from memory.memory_manager import MemoryManager
    from planner.planner import Planner
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.builtin.memory_forget_tool import MemoryForgetTool
    from tools.builtin.memory_tool import MemoryTool
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry
    from workflow.engine import WorkflowEngine

    engine = sqlalchemy.create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    memory = MemoryManager(EpisodicMemoryStore(factory))

    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_RecordingLogger()  # type: ignore[arg-type]
    )
    approvals = ApprovalManager(audit_logger=approvals_logger)  # type: ignore[arg-type]
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=_RecordingLogger()  # type: ignore[arg-type]
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
        security_manager=security,
        memory_manager=memory,
        workflow_engine=workflow_engine,
    )
    return orchestrator, memory


def test_phase15_waiting_workflow_survives_raising_approval_manager_logger() -> (
    None
):
    orchestrator, memory = _workflow_orchestrator(_FailingLogger())
    response = orchestrator.handle_request(
        "remember this and forget it: Waiting despite ApprovalManager logger failure"
    )
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    assert any(
        r.content == "Waiting despite ApprovalManager logger failure"
        for r in memory.list_recent(limit=5)
    )


def test_phase15_approved_resume_survives_raising_approval_manager_logger() -> (
    None
):
    """This is the exact scenario Batch 4B's investigation proved was
    broken before this fix: without it, approvals.approve() would raise,
    execute_approved()/WorkflowEngine.resume() would never be called, and
    the memory would never be forgotten despite a genuinely recorded
    approval."""
    orchestrator, memory = _workflow_orchestrator(_FailingLogger())
    response = orchestrator.handle_request(
        "remember this and forget it: Approved despite ApprovalManager logger failure"
    )
    decision = orchestrator.approvals.approve(response.approval_request.request_id)
    assert decision.is_approved is True

    resumed = orchestrator.execute_approved(response, decision)

    assert resumed.success is True
    assert not any(
        r.content == "Approved despite ApprovalManager logger failure"
        for r in memory.list_recent(limit=5)
    )


def test_phase15_declined_resume_survives_raising_approval_manager_logger() -> (
    None
):
    orchestrator, memory = _workflow_orchestrator(_FailingLogger())
    response = orchestrator.handle_request(
        "remember this and forget it: Declined despite ApprovalManager logger failure"
    )
    decision = orchestrator.approvals.decline(response.approval_request.request_id)
    assert decision.is_declined is True

    resumed = orchestrator.execute_approved(response, decision)

    assert resumed.success is False
    assert any(
        r.content == "Declined despite ApprovalManager logger failure"
        for r in memory.list_recent(limit=5)
    )


def test_expired_workflow_state_reaping_still_works_with_raising_approval_manager_logger() -> (
    None
):
    """WorkflowEngine._reap_stale_paused() calls ApprovalManager.has_pending(),
    which internally triggers _sweep_expired() - proving this still
    correctly reaps a stale paused workflow (unblocking future run() calls)
    even when the ApprovalManager's own timeout-audit logging fails."""
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry
    from workflow.engine import WorkflowEngine
    from planner.plan_models import Plan, PlanStep
    from security.security_manager import SecurityManager

    security = SecurityManager()
    registry = ToolRegistry()

    from tools.base_tool import BaseTool, ToolRequest, ToolResult

    class _YellowTool(BaseTool):
        @property
        def name(self) -> str:
            return "yellow"

        @property
        def description(self) -> str:
            return "x"

        def action_for(self, request: ToolRequest) -> str:
            return "delete something"

        def run(self, request: ToolRequest) -> ToolResult:
            return ToolResult(tool_name=self.name, success=True, output="deleted")

    registry.register_tool(_YellowTool())
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_RecordingLogger()  # type: ignore[arg-type]
    )
    clock = _FakeClock(_START)
    approvals = ApprovalManager(
        audit_logger=_FailingLogger(), timeout_seconds=60, clock=clock  # type: ignore[arg-type]
    )
    engine = WorkflowEngine(executor=executor, approvals=approvals, logger=_RecordingLogger())  # type: ignore[arg-type]

    step = PlanStep(
        number=1,
        description="d",
        action="placeholder",
        tier=SecurityTier.GREEN,
        reason="placeholder",
        tool_name="yellow",
    )
    plan = Plan(user_request="req", steps=(step,))

    result = engine.run(plan)
    assert result.overall_status.value == "waiting"

    clock.now = _START + timedelta(seconds=61)

    # A brand new workflow can now start - the stale paused state was
    # reaped, even though the ApprovalManager logger that fired during the
    # reap's own has_pending() check is failing.
    second_result = engine.run(plan)
    assert second_result.overall_status.value in ("waiting", "completed")
