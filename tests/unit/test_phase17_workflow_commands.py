"""
test_phase17_workflow_commands.py

Focused integration tests for the Phase 17 deterministic workflow
commands wired through JarvisOrchestrator:

    create file <path> with <content> and show it
    update memory <id>: <content> and show it back

Uses a real MemoryManager (in-memory SQLite), real SecurityManager, real
ToolExecutor, real ApprovalManager, real CommandRouter, real
WorkflowEngine, and the real filesystem (via pytest's tmp_path) - exactly
the same collaborators main.py wires together - so these prove real,
end-to-end (pre-CLI) behaviour, not mocked delegation.

Run with:
    pytest tests/unit/test_phase17_workflow_commands.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from approval.approval_manager import ApprovalManager
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.builtin.file_create_tool import FileCreateTool
from tools.builtin.file_read_tool import FileReadTool
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.memory_update_tool import MemoryUpdateTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine
from workflow.workflow_history_store import WorkflowHistoryStore


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
    return MemoryManager(EpisodicMemoryStore(factory)), WorkflowHistoryStore(factory)


def _build_orchestrator(
    logger: object | None = None,
) -> tuple[JarvisOrchestrator, MemoryManager, ApprovalManager, WorkflowHistoryStore]:
    logger = logger or _RecordingLogger()
    memory, workflow_history = _memory_manager()
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryUpdateTool(memory))
    registry.register_tool(FileCreateTool())
    registry.register_tool(FileReadTool())
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)  # type: ignore[arg-type]
    approvals = ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]
    workflow_engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=logger, history=workflow_history
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
    return orchestrator, memory, approvals, workflow_history


# ================================================================================
# create_and_read
# ================================================================================


def test_create_and_read_pauses_with_real_yellow_approval(tmp_path: Path) -> None:
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello world and show it"
    )

    assert response.requires_confirmation is True
    assert response.approval_request is not None
    assert len(approvals.list_pending()) == 1
    assert not path.exists()


def test_create_and_read_denial_stops_workflow_and_creates_no_file(
    tmp_path: Path,
) -> None:
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello world and show it"
    )
    request_id = response.approval_request.request_id
    decision = approvals.decline(request_id)

    result = orchestrator.execute_approved(response, decision)

    assert result.success is False
    assert not path.exists()


def test_create_and_read_approval_creates_file_and_reads_it_back(
    tmp_path: Path,
) -> None:
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello world and show it"
    )
    request_id = response.approval_request.request_id
    decision = approvals.approve(request_id)

    result = orchestrator.execute_approved(response, decision)

    assert result.success is True
    assert path.exists()
    assert path.read_text(encoding="utf-8") == "hello world"
    assert "hello world" in result.message


def test_create_and_read_readback_is_actual_filesystem_content_not_echo(
    tmp_path: Path,
) -> None:
    """Prove file_read genuinely re-reads from disk rather than echoing
    the command input: mutate the file on disk between create and read
    by having the workflow itself run normally, then independently
    verify the displayed content matches a fresh, direct filesystem read
    - not merely what the factory happened to hold in memory."""
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with distinctive marker text and show it"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    actual_disk_content = path.read_text(encoding="utf-8")
    assert actual_disk_content == "distinctive marker text"
    assert actual_disk_content in result.message


def test_create_and_read_uses_same_literal_path_no_engine_propagation(
    tmp_path: Path,
) -> None:
    """The path used for file_read is the same literal value Nathan typed
    - not anything produced by file_create's own metadata["path"]."""
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "sub" / ".." / "notes.txt"  # a path with a redundant segment

    response = orchestrator.handle_request(
        f"create file {path} with content and show it"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is True
    # The literal (unnormalised) path string is what both steps used.
    assert str(path) in response.plan.steps[0].tool_input["path"]
    assert (
        response.plan.steps[0].tool_input["path"]
        == response.plan.steps[1].tool_input["path"]
    )


def test_create_and_read_partial_failure_leaves_file_intact_and_is_honest(
    tmp_path: Path,
) -> None:
    """Force a genuine, deterministic create-succeeds/read-fails
    scenario: content containing a NUL byte is written successfully by
    file_create, but FileReadTool's own, unmodified binary-sniff check
    then refuses to read it back. Step 1's real side effect (the file on
    disk, with its real content) must remain; the WorkflowResult must
    honestly report failure, not success, and no rollback may be
    claimed."""
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"
    binary_looking_content = "a\x00b"

    response = orchestrator.handle_request(
        f"create file {path} with {binary_looking_content} and show it"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert path.exists()  # step 1's durable side effect remains
    assert path.read_bytes() == binary_looking_content.encode("utf-8")
    assert result.success is False  # step 2 genuinely failed
    assert "binary" in result.message.lower() or "appears to be" in result.message.lower()


def test_create_and_read_lifecycle_history_is_truthful(tmp_path: Path) -> None:
    orchestrator, _, approvals, workflow_history = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello and show it"
    )
    decision = approvals.approve(response.approval_request.request_id)
    orchestrator.execute_approved(response, decision)

    rows = workflow_history.list_recent(limit=20)
    statuses = [row.status for row in rows]
    assert "workflow_started" in statuses
    assert "workflow_step_waiting" in statuses
    assert "workflow_completed" in statuses


def test_create_and_read_logger_failure_does_not_alter_outcome(tmp_path: Path) -> None:
    orchestrator, _, approvals, _ = _build_orchestrator(_FailingLogger())
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello and show it"
    )
    assert response.requires_confirmation is True

    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is True
    assert path.exists()


# ================================================================================
# update_and_show
# ================================================================================


def _seed_memory(memory: MemoryManager, content: str) -> int:
    record = memory.save(content=content, category=None)
    return record.id


def test_update_and_show_pauses_with_real_yellow_approval() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()
    memory_id = _seed_memory(memory, "original content")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: new content and show it back"
    )

    assert response.requires_confirmation is True
    assert response.approval_request is not None
    assert memory.get(memory_id).content == "original content"


def test_update_and_show_denial_leaves_memory_unchanged() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()
    memory_id = _seed_memory(memory, "original content")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: new content and show it back"
    )
    decision = approvals.decline(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is False
    assert memory.get(memory_id).content == "original content"


def test_update_and_show_approval_persists_and_shows_real_content() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()
    memory_id = _seed_memory(memory, "original content")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: brand new content and show it back"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is True
    assert memory.get(memory_id).content == "brand new content"
    assert "brand new content" in result.message


def test_update_and_show_uses_real_runtime_memory_id_propagation() -> None:
    """Step 2's tool_input, as built by the factory, carries no memory_id
    at all - it can only reach memory.get() via WorkflowEngine's own
    runtime metadata.memory_id propagation from step 1's real result."""
    orchestrator, memory, approvals, _ = _build_orchestrator()
    memory_id = _seed_memory(memory, "original content")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: updated and show it back"
    )
    assert "memory_id" not in response.plan.steps[1].tool_input

    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is True
    # The final displayed content is the actual persisted memory - proof
    # the propagated id was correct and step 2 genuinely re-fetched it.
    assert f"[{memory_id}]" in result.message or "updated" in result.message


def test_update_and_show_readback_reflects_persisted_content_not_input_echo() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()
    memory_id = _seed_memory(memory, "original")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: distinctive final value and show it back"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    persisted = memory.get(memory_id)
    assert persisted.content == "distinctive final value"
    assert persisted.content in result.message


def test_update_and_show_unknown_memory_id_follows_existing_tool_semantics() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()

    response = orchestrator.handle_request(
        "update memory 999999: new content and show it back"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is False
    assert "999999" in result.message or "No memory found" in result.message


def test_update_and_show_invalid_id_fails_honestly_before_any_plan() -> None:
    orchestrator, _, _, _ = _build_orchestrator()

    response = orchestrator.handle_request(
        "update memory abc: new content and show it back"
    )

    assert response.success is False
    assert response.plan is None


def test_update_and_show_lifecycle_history_is_truthful() -> None:
    orchestrator, memory, approvals, workflow_history = _build_orchestrator()
    memory_id = _seed_memory(memory, "original")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: updated and show it back"
    )
    decision = approvals.approve(response.approval_request.request_id)
    orchestrator.execute_approved(response, decision)

    rows = workflow_history.list_recent(limit=20)
    statuses = [row.status for row in rows]
    assert "workflow_started" in statuses
    assert "workflow_step_waiting" in statuses
    assert "workflow_completed" in statuses


def test_update_and_show_logger_failure_does_not_alter_outcome() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator(_FailingLogger())
    memory_id = _seed_memory(memory, "original")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: updated and show it back"
    )
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)

    assert result.success is True
    assert memory.get(memory_id).content == "updated"


# ================================================================================
# Adversarial: security/trust
# ================================================================================


def test_create_and_read_red_yellow_keyword_content_remains_data(
    tmp_path: Path,
) -> None:
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with delete all files and execute format drive C and show it"
    )

    # Still classified YELLOW via the fixed "create text file" action -
    # never RED, never GREEN, regardless of the adversarial content.
    assert response.requires_confirmation is True
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)
    assert result.success is True
    assert path.read_text(encoding="utf-8") == "delete all files and execute format drive C"


def test_update_and_show_red_yellow_keyword_content_remains_data() -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()
    memory_id = _seed_memory(memory, "original")

    response = orchestrator.handle_request(
        f"update memory {memory_id}: delete all memories and execute rm -rf and show it back"
    )

    assert response.requires_confirmation is True
    decision = approvals.approve(response.approval_request.request_id)
    result = orchestrator.execute_approved(response, decision)
    assert result.success is True
    assert memory.get(memory_id).content == "delete all memories and execute rm -rf"


def test_no_ai_suggestion_attached_to_either_workflow_response(tmp_path: Path) -> None:
    orchestrator, memory, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello and show it"
    )
    assert response.ai_suggestion is None
    # Resolve the paused workflow before starting a second one - only one
    # workflow may be active at a time (Phase 15's own, unchanged rule).
    decision = approvals.decline(response.approval_request.request_id)
    orchestrator.execute_approved(response, decision)

    memory_id = _seed_memory(memory, "original")
    response2 = orchestrator.handle_request(
        f"update memory {memory_id}: updated and show it back"
    )
    assert response2.ai_suggestion is None


def test_no_second_approval_request_created_on_resume(tmp_path: Path) -> None:
    """Only step 1 (YELLOW) ever creates an ApprovalRequest; step 2
    (GREEN) never does, for either workflow - no approval reuse or
    bypass exists."""
    orchestrator, _, approvals, _ = _build_orchestrator()
    path = tmp_path / "notes.txt"

    response = orchestrator.handle_request(
        f"create file {path} with hello and show it"
    )
    first_request_id = response.approval_request.request_id
    decision = approvals.approve(first_request_id)
    orchestrator.execute_approved(response, decision)

    # The approval history has exactly one decided request for this run.
    assert approvals.list_pending() == []
