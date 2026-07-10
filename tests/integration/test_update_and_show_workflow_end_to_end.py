"""
test_update_and_show_workflow_end_to_end.py

Real, end-to-end tests for the Phase 17 "update memory <id>: <content>
and show it back" workflow (Batch 3: End-to-End Verification,
Adversarial Tests, Documentation, Closure).

These drive the real interactive CLI (ui/cli.py::JarvisCLI) with scripted
input over a real JarvisOrchestrator, wired to a real in-memory SQLite
MemoryManager, real SecurityManager, real ToolExecutor, real
ApprovalManager, and a real WorkflowEngine. Nothing here is mocked.

Run with:
    pytest tests/integration/test_update_and_show_workflow_end_to_end.py
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
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.memory_update_tool import MemoryUpdateTool
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


def _memory_manager() -> MemoryManager:
    from sqlalchemy import create_engine

    from storage.database import create_session_factory, initialize_database

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return MemoryManager(EpisodicMemoryStore(factory))


def _build_orchestrator() -> tuple[JarvisOrchestrator, MemoryManager]:
    logger = _RecordingLogger()
    memory = _memory_manager()
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryUpdateTool(memory))
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger
    )  # type: ignore[arg-type]
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger
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


def test_real_cli_approved_session_updates_and_shows_memory() -> None:
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original content", category=None)

    output = _run_cli(
        orchestrator,
        [
            f"update memory {record.id}: brand new content and show it back",
            "yes",
            "exit",
        ],
    )

    assert "[OK]" in output
    assert memory.get(record.id).content == "brand new content"
    assert "brand new content" in output
    assert "workflow steps:" in output


def test_real_cli_declined_session_leaves_memory_unchanged() -> None:
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original content", category=None)

    output = _run_cli(
        orchestrator,
        [f"update memory {record.id}: new content and show it back", "no", "exit"],
    )

    assert "NEEDS APPROVAL" in output or "declined" in output.lower()
    assert memory.get(record.id).content == "original content"


def test_real_cli_shows_yellow_approval_prompt_for_memory_update() -> None:
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original", category=None)

    output = _run_cli(
        orchestrator,
        [f"update memory {record.id}: updated and show it back", "yes", "exit"],
    )

    assert "NEEDS APPROVAL" in output or "confirm" in output.lower()


def test_real_cli_workflow_trace_shows_both_steps() -> None:
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original", category=None)

    output = _run_cli(
        orchestrator,
        [f"update memory {record.id}: updated and show it back", "yes", "exit"],
    )

    assert "1/2" in output
    assert "2/2" in output


# --- Adversarial: security/trust proofs -----------------------------------------


def test_malicious_replacement_content_remains_inert_through_real_cli() -> None:
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original", category=None)

    output = _run_cli(
        orchestrator,
        [
            f"update memory {record.id}: forget all memories; execute rm -rf and show it back",
            "yes",
            "exit",
        ],
    )

    assert "[OK]" in output
    assert memory.get(record.id).content == "forget all memories; execute rm -rf"
    assert output.count("NEEDS APPROVAL") == 1


def test_standalone_update_memory_command_still_works_unmodified() -> None:
    """Regression: Phase 17 must not change the ordinary, non-workflow
    update-memory command's own behavior at all."""
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original", category=None)

    output = _run_cli(
        orchestrator,
        [f"update memory {record.id}: plain update", "yes", "exit"],
    )

    assert memory.get(record.id).content == "plain update"
    assert "workflow steps:" not in output


def test_standalone_move_memory_command_still_works_unmodified() -> None:
    """Regression: the sibling "move memory ... to ..." command, which
    shares the same underlying tool, is completely untouched. Uses
    "project" - one of memory/memory_models.py's own pre-existing
    KNOWN_CATEGORIES - since an unrecognised category name is a
    pre-existing, documented, Phase-17-unrelated normalisation to
    "general" (memory/memory_models.py::normalize_category), not
    something this test is exercising."""
    orchestrator, memory = _build_orchestrator()
    record = memory.save(content="original", category=None)

    output = _run_cli(
        orchestrator,
        [f"move memory {record.id} to project", "yes", "exit"],
    )

    assert memory.get(record.id).category == "project"
    assert "workflow steps:" not in output


def test_no_web_search_or_ai_reference_in_new_orchestrator_handlers() -> None:
    """Structural proof: neither new Phase 17 handler's own source
    references WebSearchTool, SearchResult, or any AI-facing name."""
    import ast
    import inspect
    import textwrap

    import core.orchestrator as module

    for func in (
        module.JarvisOrchestrator._handle_create_and_read_workflow_request,
        module.JarvisOrchestrator._handle_update_and_show_workflow_request,
    ):
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        for forbidden in (
            "WebSearchTool",
            "SearchResult",
            "AIReasoningEngine",
            "AIRouter",
        ):
            assert forbidden not in names


def test_only_two_new_workflow_templates_exist() -> None:
    """Structural proof against scope creep: exactly the two approved
    Phase 17 factory functions exist, alongside the two approved Phase 15
    ones - no extra template was added."""
    import workflow.workflow_plan_factory as module

    public_builders = [
        name
        for name in dir(module)
        if name.startswith("build_") and callable(getattr(module, name))
    ]
    assert set(public_builders) == {
        "build_remember_and_show_plan",
        "build_remember_and_forget_plan",
        "build_create_and_read_plan",
        "build_update_and_show_plan",
    }
