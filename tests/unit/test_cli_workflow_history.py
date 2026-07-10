"""
test_cli_workflow_history.py

Real, end-to-end tests for the Durable Workflow Lifecycle Foundation (a
prerequisite turn, not a numbered phase): proving a real two-step
workflow's full lifecycle becomes queryable through the real command
path, exactly the way a user would type it.

These drive the real interactive CLI (ui/cli.py::JarvisCLI) with scripted
input over a real JarvisOrchestrator, wired to a real in-memory SQLite
MemoryManager, real SecurityManager, real ToolExecutor, real
ApprovalManager, a real WorkflowEngine, and a real WorkflowHistoryStore/
WorkflowHistoryTool - exactly the collaborators main.py wires together.
Nothing here is mocked; "show workflow history" is classified fresh by
the real SecurityManager and executed through the real ToolExecutor, the
same as every other command.

Run with:
    pytest tests/unit/test_cli_workflow_history.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin.memory_forget_tool import MemoryForgetTool
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.workflow_history_tool import WorkflowHistoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI
from workflow.engine import WorkflowEngine
from workflow.workflow_history_store import WorkflowHistoryStore


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


def _memory_manager_and_history_store() -> tuple[MemoryManager, WorkflowHistoryStore]:
    """Build a real MemoryManager and a real WorkflowHistoryStore sharing
    one in-memory SQLite database - mirroring how main.py shares one real
    session_factory across every durable collaborator."""
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory)), WorkflowHistoryStore(factory)


def _build_orchestrator() -> tuple[JarvisOrchestrator, WorkflowHistoryStore]:
    """Build a real orchestrator with a real, durable WorkflowHistoryStore
    wired to both WorkflowEngine (which writes to it) and a registered
    WorkflowHistoryTool (which reads from it) - exactly as main.py wires
    them, reusing one instance for both."""
    logger = _RecordingLogger()
    memory, workflow_history = _memory_manager_and_history_store()
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    registry.register_tool(WorkflowHistoryTool(workflow_history))
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger
    )  # type: ignore[arg-type]
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    workflow_engine = WorkflowEngine(
        executor=executor,
        approvals=approvals,
        logger=logger,
        history=workflow_history,
    )  # type: ignore[arg-type]
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
        security_manager=security,
        memory_manager=memory,
        workflow_engine=workflow_engine,
        logger=logger,  # type: ignore[arg-type]
    )
    return orchestrator, workflow_history


def _run_cli(orchestrator: JarvisOrchestrator, inputs: list[str]) -> str:
    scripted = iter(inputs)
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    return "\n".join(outputs)


# --- All-GREEN workflow: history queryable through the real command path -----


def test_completed_workflow_history_is_queryable_via_real_command() -> None:
    orchestrator, _ = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            "remember this and show it back: Durable history check",
            "show workflow history",
            "exit",
        ],
    )

    assert "[OK]" in output
    assert "workflow_started" in output
    assert "workflow_completed" in output


def test_workflow_history_shows_both_step_transitions() -> None:
    orchestrator, _ = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            "remember this and show it back: Step transitions",
            "show workflow history",
            "exit",
        ],
    )

    assert "workflow_step_completed" in output
    assert "step 1/2" in output
    assert "step 2/2" in output


def test_show_recent_workflows_command_matches_real_security_classification() -> (
    None
):
    orchestrator, _ = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            "remember this and show it back: Recent workflows check",
            "show recent workflows",
            "exit",
        ],
    )

    assert "[OK]" in output
    assert "workflow_started" in output


# --- Real store cross-check: durable rows exist independent of the CLI -------


def test_completed_workflow_is_durably_recorded_in_the_real_store() -> None:
    orchestrator, workflow_history = _build_orchestrator()

    _run_cli(
        orchestrator,
        ["remember this and show it back: Durable store cross-check", "exit"],
    )

    rows = workflow_history.list_recent(limit=10)
    statuses = [row.status for row in rows]
    assert "workflow_started" in statuses
    assert "workflow_completed" in statuses


# --- YELLOW pause/resume: waiting and completion both durably recorded -------


def test_paused_workflow_is_durably_recorded_as_waiting() -> None:
    orchestrator, workflow_history = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        ["remember this and forget it: Pending forget workflow", "no", "exit"],
    )

    assert "requires your confirmation" in output or "confirm" in output.lower()
    rows = workflow_history.list_recent(limit=10)
    statuses = [row.status for row in rows]
    assert "workflow_step_waiting" in statuses

    waiting_row = next(r for r in rows if r.status == "workflow_step_waiting")
    assert waiting_row.approval_request_id is not None


def test_approved_forget_workflow_completes_and_history_shows_full_lifecycle() -> (
    None
):
    orchestrator, workflow_history = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            "remember this and forget it: Approved forget workflow",
            "yes",
            "show workflow history",
            "exit",
        ],
    )

    assert "[OK]" in output
    rows = workflow_history.list_recent(limit=20)
    statuses = {row.status for row in rows}
    assert "workflow_step_waiting" in statuses
    assert "workflow_completed" in statuses


def test_get_operation_shows_one_workflows_full_story_oldest_first() -> None:
    orchestrator, workflow_history = _build_orchestrator()

    _run_cli(
        orchestrator,
        ["remember this and show it back: Full story check", "exit"],
    )

    workflow_id = workflow_history.list_recent(limit=1)[0].workflow_id
    output = _run_cli(orchestrator, [f"show workflow {workflow_id}", "exit"])

    assert f"Workflow {workflow_id}" in output
    started_index = output.index("workflow_started")
    completed_index = output.index("workflow_completed")
    assert started_index < completed_index
