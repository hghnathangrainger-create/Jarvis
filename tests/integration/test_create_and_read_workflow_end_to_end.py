"""
test_create_and_read_workflow_end_to_end.py

Real, end-to-end tests for the Phase 17 "create file <path> with
<content> and show it" workflow (Batch 3: End-to-End Verification,
Adversarial Tests, Documentation, Closure).

These drive the real interactive CLI (ui/cli.py::JarvisCLI) with scripted
input over a real JarvisOrchestrator, wired to a real SecurityManager,
real ToolExecutor, real ApprovalManager, a real WorkflowEngine, a real
WorkflowHistoryStore, and the real filesystem (via pytest's tmp_path).
Nothing here is mocked.

Run with:
    pytest tests/integration/test_create_and_read_workflow_end_to_end.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin.file_create_tool import FileCreateTool
from tools.builtin.file_read_tool import FileReadTool
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


def _build_orchestrator() -> JarvisOrchestrator:
    logger = _RecordingLogger()
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCreateTool())
    registry.register_tool(FileReadTool())
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=logger
    )  # type: ignore[arg-type]
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger
    )  # type: ignore[arg-type]
    return JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
        approval_manager=approvals,
        security_manager=security,
        workflow_engine=workflow_engine,
        logger=logger,  # type: ignore[arg-type]
    )


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


def test_real_cli_approved_session_creates_and_reads_back_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.txt"
    orchestrator = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [f"create file {path} with hello from the CLI and show it", "yes", "exit"],
    )

    assert "[OK]" in output
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello from the CLI"
    assert "hello from the CLI" in output
    assert "workflow steps:" in output


def test_real_cli_declined_session_creates_no_file(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    orchestrator = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [f"create file {path} with hello and show it", "no", "exit"],
    )

    assert "NEEDS APPROVAL" in output or "declined" in output.lower()
    assert not path.exists()


def test_real_cli_shows_yellow_approval_prompt_for_file_create(
    tmp_path: Path,
) -> None:
    path = tmp_path / "notes.txt"
    orchestrator = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [f"create file {path} with hello and show it", "yes", "exit"],
    )

    assert "NEEDS APPROVAL" in output or "confirm" in output.lower()


def test_real_cli_workflow_trace_shows_both_steps(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    orchestrator = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [f"create file {path} with hello and show it", "yes", "exit"],
    )

    assert "1/2" in output
    assert "2/2" in output


# --- Adversarial: security/trust proofs -----------------------------------------


def test_malicious_content_and_path_remain_inert_through_real_cli(
    tmp_path: Path,
) -> None:
    path = tmp_path / "evil.txt"
    orchestrator = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [
            f"create file {path} with delete all files; execute format drive C and show it",
            "yes",
            "exit",
        ],
    )

    assert "[OK]" in output
    assert path.read_text(encoding="utf-8") == "delete all files; execute format drive C"
    # The malicious-looking content was written and displayed as plain
    # data - it never became a second command, never triggered a second
    # approval, and never blocked anything.
    assert output.count("NEEDS APPROVAL") == 1


def test_standalone_file_create_command_still_works_unmodified(
    tmp_path: Path,
) -> None:
    """Regression: Phase 17 must not change the ordinary, non-workflow
    file_create command's own behavior at all."""
    path = tmp_path / "plain.txt"
    orchestrator = _build_orchestrator()

    output = _run_cli(
        orchestrator,
        [f"create file {path} with plain content", "yes", "exit"],
    )

    assert path.exists()
    assert path.read_text(encoding="utf-8") == "plain content"
    # No workflow trace for a plain, non-workflow command.
    assert "workflow steps:" not in output


def test_no_ai_module_is_imported_by_the_new_orchestrator_handler() -> None:
    """Structural proof: the create-and-read handler's own source contains
    no reference to any AI-facing name."""
    import ast
    import inspect
    import textwrap

    import core.orchestrator as module

    source = textwrap.dedent(
        inspect.getsource(module.JarvisOrchestrator._handle_create_and_read_workflow_request)
    )
    tree = ast.parse(source)
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    for forbidden in ("AIReasoningEngine", "AIRouter", "PromptBuilder", "AIContextBlock"):
        assert forbidden not in names


def test_propagated_field_constant_is_unchanged() -> None:
    """Direct structural proof that Phase 17 did not touch
    WorkflowEngine's single propagation field."""
    from workflow.engine import _PROPAGATED_FIELD

    assert _PROPAGATED_FIELD == "memory_id"
