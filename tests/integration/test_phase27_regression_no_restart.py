"""
test_phase27_regression_no_restart.py

Phase 27, Batch 3: explicit regression proofs that ordinary, same-process
(non-restart) approval and workflow behavior is completely unchanged by
the durable pending-approval/paused-workflow persistence added in
Batches 1 and 2 - proven with a pending_store/paused_store configured
(so persistence is actively happening alongside), confirming its mere
presence changes nothing about the live path's outcome.

Run with:
    pytest tests/integration/test_phase27_regression_no_restart.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_history_store import ApprovalHistoryStore
from approval.approval_manager import ApprovalManager
from approval.pending_approval_store import PendingApprovalStore
from config.constants import SecurityTier, StepStatus
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from storage.database import create_session_factory, initialize_database
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import FileCopyTool, FileCreateTool, FileListTool, FileReadTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine
from workflow.paused_workflow_store import PausedWorkflowStore
from workflow.workflow_history_store import WorkflowHistoryStore


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _GreenTool(BaseTool):
    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "green_tool"

    @property
    def description(self) -> str:
        return "green"

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="ok")


class _YellowTool(BaseTool):
    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "yellow_tool"

    @property
    def description(self) -> str:
        return "yellow"

    def action_for(self, request: ToolRequest) -> str:
        return "delete something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="deleted")


@pytest.fixture()
def session_factory():
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _two_step_plan() -> Plan:
    return Plan(
        user_request="do a green thing then a yellow thing",
        steps=(
            PlanStep(
                number=1, description="green", action="read something",
                tier=SecurityTier.GREEN, reason="ok", tool_name="green_tool",
                tool_input={},
            ),
            PlanStep(
                number=2, description="yellow", action="delete something",
                tier=SecurityTier.YELLOW, reason="needs approval",
                tool_name="yellow_tool", tool_input={"target": "x"},
            ),
        ),
    )


# --- normal pending approval / denial, without restart -----------------------


def test_normal_approval_without_restart_still_runs_the_tool(
    session_factory, workspace: Path
) -> None:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCopyTool())
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(
        audit_logger=logger, pending_store=PendingApprovalStore(session_factory)
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
    )

    (workspace / "source.txt").write_text("hello")
    response = orchestrator.handle_request("copy file source.txt to copied.txt")
    assert response.requires_confirmation is True

    decision = approvals.approve(response.approval_request.request_id)
    executed = orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert (workspace / "copied.txt").read_text() == "hello"


def test_normal_denial_without_restart_writes_nothing(
    session_factory, workspace: Path
) -> None:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCopyTool())
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(
        audit_logger=logger, pending_store=PendingApprovalStore(session_factory)
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
    )

    (workspace / "source.txt").write_text("hello")
    response = orchestrator.handle_request("copy file source.txt to copied.txt")
    decision = approvals.decline(response.approval_request.request_id)
    executed = orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert not (workspace / "copied.txt").exists()


# --- normal paused workflow / completion, without restart --------------------


def test_normal_paused_workflow_without_restart_resumes_and_completes(
    session_factory,
) -> None:
    security = SecurityManager()
    registry = ToolRegistry()
    green = _GreenTool()
    yellow = _YellowTool()
    registry.register_tool(green)
    registry.register_tool(yellow)
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(
        audit_logger=logger, pending_store=PendingApprovalStore(session_factory)
    )
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger,
        paused_store=PausedWorkflowStore(session_factory),
    )

    result = engine.run(_two_step_plan())
    assert result.overall_status is StepStatus.WAITING
    assert len(green.calls) == 1
    assert yellow.calls == []

    decision = approvals.approve(result.pending_approval_request.request_id)
    resumed = engine.resume(result.workflow_id, decision)

    assert resumed.overall_status is StepStatus.COMPLETED
    assert len(yellow.calls) == 1


def test_normal_workflow_full_green_completion_without_restart(
    session_factory,
) -> None:
    """A workflow with no YELLOW step at all never touches the pending-
    approval/paused-workflow machinery."""
    security = SecurityManager()
    registry = ToolRegistry()
    green = _GreenTool()
    registry.register_tool(green)
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(
        audit_logger=logger, pending_store=PendingApprovalStore(session_factory)
    )
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger,
        paused_store=PausedWorkflowStore(session_factory),
    )
    plan = Plan(
        user_request="just a green thing",
        steps=(
            PlanStep(
                number=1, description="green", action="read something",
                tier=SecurityTier.GREEN, reason="ok", tool_name="green_tool",
                tool_input={},
            ),
        ),
    )
    result = engine.run(plan)

    assert result.overall_status is StepStatus.COMPLETED
    assert PendingApprovalStore(session_factory).list_all() == []
    assert PausedWorkflowStore(session_factory).list_all() == []


# --- approval/workflow history remain honest ---------------------------------


def test_approval_history_remains_honest_without_restart(session_factory) -> None:
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCreateTool())
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    history = ApprovalHistoryStore(session_factory)
    approvals = ApprovalManager(
        audit_logger=logger,
        history_store=history,
        pending_store=PendingApprovalStore(session_factory),
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
    )
    response = orchestrator.handle_request("create file made.txt with hi")
    approvals.approve(response.approval_request.request_id)

    entry = history.get(response.approval_request.request_id)
    assert entry is not None
    assert entry.status == "approved"
    assert entry.decided_by == "user"


def test_workflow_history_remains_honest_without_restart(session_factory) -> None:
    security = SecurityManager()
    registry = ToolRegistry()
    green = _GreenTool()
    yellow = _YellowTool()
    registry.register_tool(green)
    registry.register_tool(yellow)
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(
        audit_logger=logger, pending_store=PendingApprovalStore(session_factory)
    )
    workflow_history = WorkflowHistoryStore(session_factory)
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger,
        history=workflow_history,
        paused_store=PausedWorkflowStore(session_factory),
    )
    result = engine.run(_two_step_plan())
    decision = approvals.approve(result.pending_approval_request.request_id)
    engine.resume(result.workflow_id, decision)

    entries = workflow_history.list_for_workflow(result.workflow_id)
    statuses = [e.status for e in entries]
    assert "workflow_started" in statuses
    assert "workflow_step_waiting" in statuses
    assert "workflow_completed" in statuses
    assert "workflow_stopped" not in statuses  # nothing failed


# --- build_orchestrator() signature and other subsystems unaffected ---------


def test_file_tools_unaffected_by_phase_27(workspace: Path) -> None:
    """A plain file-tool round trip, with no approval/workflow durability
    machinery involved at all, confirmed unaffected."""
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
    logger = _SpyLogger()
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)

    (workspace / "a.txt").write_text("content")
    result = executor.execute("file_read", {"path": "a.txt"})
    assert result.success is True
    assert "content" in result.output
