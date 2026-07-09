"""
test_cli_workflow_commands.py

Real, end-to-end CLI tests for the Phase 15 workflow commands (Batch 4:
CLI Workflow Progress Surface and Full End-to-End Security Proof):

    remember this and show it back: <text>
    remember this and forget it: <text>

These drive the real interactive CLI (ui/cli.py::JarvisCLI) with scripted
input over a real JarvisOrchestrator, wired to a real in-memory SQLite
MemoryManager, real SecurityManager, real ToolExecutor, real
ApprovalManager, and a real WorkflowEngine - exactly the collaborators
main.py wires together. Nothing about WorkflowEngine, SecurityManager, or
the concrete memory tools is mocked in the principal success/approval
proofs.

Run with:
    pytest tests/unit/test_cli_workflow_commands.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager
from config.constants import EventOutcome, SecurityTier
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin.memory_forget_tool import MemoryForgetTool
from tools.builtin.memory_tool import MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI
from workflow.engine import WorkflowEngine


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FailingLogger:
    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("simulated logger failure")


def _memory_manager() -> MemoryManager:
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _build_orchestrator(
    logger: object | None = None,
    *,
    workflow_logger: object | None = None,
) -> tuple[JarvisOrchestrator, MemoryManager]:
    """Build a real orchestrator.

    `logger` is used for ToolExecutor/ApprovalManager/Orchestrator (always
    a healthy, working logger in every test in this file - none of these
    collaborators' own logger isolation is under test here; that is
    ToolExecutor's/ApprovalManager's own established, separately-tested
    responsibility). `workflow_logger`, when supplied, is used only for
    WorkflowEngine's own workflow_* audit family, so a test can prove that
    family's own isolation without confounding it with ToolExecutor's own,
    separate, unguarded logger.emit() calls (see this batch's own
    ToolExecutor logger-failure investigation).
    """
    logger = logger or _RecordingLogger()
    memory = _memory_manager()
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)  # type: ignore[arg-type]
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=workflow_logger or logger
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
    return orchestrator, memory


def _run_cli(
    orchestrator: JarvisOrchestrator, inputs: list[str]
) -> str:
    scripted = iter(inputs)
    outputs: list[str] = []
    cli = JarvisCLI(
        orchestrator,
        input_fn=lambda _prompt: next(scripted),
        output_fn=outputs.append,
    )
    cli.run()
    return "\n".join(outputs)


# --- Real CLI all-GREEN end-to-end chain (Section 8) --------------------------


def test_real_cli_show_back_workflow_completes_end_to_end() -> None:
    orchestrator, memory = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        ["remember this and show it back: Distinctive CLI text", "exit"],
    )

    assert "[OK]" in output
    # The real memory was actually saved.
    records = memory.list_recent(limit=5)
    assert any(r.content == "Distinctive CLI text" for r in records)
    # Step 2 genuinely retrieved it back by the real id step 1 produced.
    assert "Distinctive CLI text" in output


def test_real_cli_show_back_workflow_trace_is_honest_post_run_summary() -> None:
    orchestrator, _ = _build_orchestrator()

    output = _run_cli(
        orchestrator, ["remember this and show it back: Trace check", "exit"]
    )

    assert "workflow steps:" in output
    assert "1/2 [completed]" in output
    assert "2/2 [completed]" in output
    # Ordering: step 1 line appears before step 2 line.
    assert output.index("1/2 [completed]") < output.index("2/2 [completed]")


def test_real_cli_show_back_workflow_step_two_uses_real_propagated_id() -> None:
    """Structured metadata propagation, not a guess: two different runs
    show back two different pieces of content, proving each one's step 2
    used its own step 1's real memory_id."""
    orchestrator, _ = _build_orchestrator()

    first_output = _run_cli(
        orchestrator, ["remember this and show it back: First unique value", "exit"]
    )

    orchestrator2, _ = _build_orchestrator()
    second_output = _run_cli(
        orchestrator2,
        ["remember this and show it back: Second unique value", "exit"],
    )

    assert "First unique value" in first_output
    assert "Second unique value" not in first_output
    assert "Second unique value" in second_output
    assert "First unique value" not in second_output


# --- Real CLI YELLOW waiting/approve chain (Section 9) ------------------------


def test_real_cli_forget_workflow_waits_for_real_approval() -> None:
    orchestrator, memory = _build_orchestrator()

    # The CLI's blocking prompt immediately follows the waiting response in
    # the same loop iteration, so a decline is scripted to keep the workflow
    # from ever completing - isolating exactly the pre-decision waiting
    # output this test is about (the approved-completion path is proven
    # separately below).
    output = _run_cli(
        orchestrator,
        ["remember this and forget it: Pending forget note", "no", "exit"],
    )

    assert "NEEDS APPROVAL" in output
    assert "workflow steps:" in output
    assert "1/2 [completed]" in output
    assert "2/2 [waiting]" in output
    # No completion claim anywhere in this output.
    assert "[OK]" not in output
    # Step 1 really did save the memory already.
    assert any(r.content == "Pending forget note" for r in memory.list_recent(limit=5))


def test_real_cli_forget_workflow_approved_completes_and_forgets_once() -> None:
    orchestrator, memory = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            "remember this and forget it: Approve me please",
            "yes",
            "exit",
        ],
    )

    assert "[APPROVED]" in output
    assert "[OK]" in output
    # Exactly-once forget proof: MemoryForgetTool.run() fails honestly
    # ("No memory found with id ...") if the same memory is forgotten a
    # second time, which would flip this final response to a non-"[OK]"
    # failure. "[OK]" appearing here is only possible because the forget
    # tool ran exactly once. (The resumed trace legitimately re-lists step
    # 1 as completed alongside step 2 - the same already-completed outcome
    # redisplayed in the final summary, exactly like the "plan:" section is
    # redisplayed on every response - this is not a re-execution.)
    assert not any(
        r.content == "Approve me please" for r in memory.list_recent(limit=5)
    )


def test_real_cli_forget_workflow_yellow_reached_by_live_classification() -> None:
    """SecurityManager itself is not mocked: YELLOW arises from the real,
    unchanged rule table classifying the real 'forget memory' action."""
    security = SecurityManager()
    decision = security.classify_action("forget memory")
    assert decision.tier is SecurityTier.YELLOW

    orchestrator, _ = _build_orchestrator()
    output = _run_cli(
        orchestrator,
        ["remember this and forget it: Live classification check", "no", "exit"],
    )
    assert "NEEDS APPROVAL" in output


# --- Real CLI declined chain (Section 10) -------------------------------------


def test_real_cli_forget_workflow_declined_does_not_forget() -> None:
    orchestrator, memory = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            "remember this and forget it: Please decline me",
            "no",
            "exit",
        ],
    )

    assert "[DECLINED]" in output
    assert "[OK]" not in output.split("[DECLINED]")[-1]
    assert any(
        r.content == "Please decline me" for r in memory.list_recent(limit=5)
    )


def test_real_cli_declined_workflow_creates_no_second_approval() -> None:
    logger = _RecordingLogger()
    orchestrator, _ = _build_orchestrator(logger)

    _run_cli(
        orchestrator,
        ["remember this and forget it: Single approval only", "no", "exit"],
    )

    approval_events = [
        c for c in logger.calls if c.get("action_type") == "approval_decision"
    ]
    assert len(approval_events) == 1


# --- Compatibility -------------------------------------------------------------


def test_real_cli_ordinary_remember_command_unaffected() -> None:
    orchestrator, memory = _build_orchestrator()
    output = _run_cli(orchestrator, ["remember this: Ordinary save", "exit"])
    assert "[OK]" in output
    assert "workflow steps:" not in output
    assert any(r.content == "Ordinary save" for r in memory.list_recent(limit=5))


def test_real_cli_ordinary_forget_command_still_uses_single_tool_approval() -> None:
    orchestrator, memory = _build_orchestrator()
    _run_cli(orchestrator, ["remember this: To be forgotten", "exit"])
    memory_id = memory.list_recent(limit=1)[0].id

    output = _run_cli(orchestrator, [f"forget memory {memory_id}", "yes", "exit"])

    assert "workflow steps:" not in output
    assert not any(r.id == memory_id for r in memory.list_recent(limit=5))


# --- WorkflowEngine logger-failure isolation, proven through the real CLI ----


def test_real_cli_workflow_engine_logger_failure_does_not_alter_completed_result() -> (
    None
):
    """Proves only WorkflowEngine's own workflow_* audit family is
    isolated - ToolExecutor/ApprovalManager keep their own healthy logger,
    since their own logger.emit() calls are unguarded (see this batch's
    ToolExecutor logger-failure investigation) and are not what this test
    is about."""
    orchestrator, memory = _build_orchestrator(workflow_logger=_FailingLogger())
    output = _run_cli(
        orchestrator,
        ["remember this and show it back: Survives logger failure", "exit"],
    )
    assert "[OK]" in output
    assert any(
        r.content == "Survives logger failure" for r in memory.list_recent(limit=5)
    )


def test_real_cli_workflow_engine_logger_failure_does_not_alter_waiting_result() -> (
    None
):
    orchestrator, _ = _build_orchestrator(workflow_logger=_FailingLogger())
    output = _run_cli(
        orchestrator,
        [
            "remember this and forget it: Waiting despite logger failure",
            "no",
            "exit",
        ],
    )
    assert "NEEDS APPROVAL" in output
