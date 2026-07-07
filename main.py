"""
main.py

Entry point for the Jarvis AI Operating System (Phase 1).

Responsibilities:
    - Load configuration.
    - Initialise the database and storage layer.
    - Wire together every Phase 1 subsystem: Observability, Security, Memory,
      Planner, Tool Manager, and the Core orchestrator.
    - Register the built-in tools.
    - Start the terminal CLI.

Does NOT:
    - Call the Claude API, add voice, or add phone support.
    - Contain any business logic; it only assembles the system and starts it.

This module is the single composition root for Phase 1. It is the one place
where concrete components are created and connected, which keeps every other
module free of wiring concerns and easy to test in isolation.
"""

from __future__ import annotations

from approval.approval_history_store import ApprovalHistoryStore
from approval.approval_manager import ApprovalManager
from config.settings import load_settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from observability.logger import EventLogger
from planner.planner import Planner
from security.audit_log import AuditLog
from security.security_manager import SecurityManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from tools.builtin import (
    ApprovalHistoryTool,
    EchoTool,
    FileAppendTool,
    FileCreateTool,
    FileListTool,
    FileReadTool,
    InfoTool,
    MemoryForgetTool,
    MemoryTool,
    MemoryUpdateTool,
)
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI


def build_orchestrator() -> JarvisOrchestrator:
    """Assemble and return a fully wired Jarvis Core orchestrator.

    This is the composition root: it loads settings, prepares storage, and
    constructs and connects every Phase 1 subsystem. It is exposed as a
    function so that the same wiring can be reused by scripts and tests.

    Returns:
        A ready-to-use JarvisOrchestrator.
    """
    settings = load_settings()

    engine = create_database_engine(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    # Observability and security.
    logger = EventLogger(AuditLog(session_factory))
    security = SecurityManager()

    # Memory.
    memory = MemoryManager(EpisodicMemoryStore(session_factory))

    # Durable, read-only approval history (Phase 6, Batch 1). This store only
    # ever records what already happened; it has no tool_name or tool_input
    # columns, so nothing here can be replayed. The ApprovalManager built from
    # it is passed into the orchestrator below - previously the orchestrator
    # silently built its own disconnected default, so approve/decline
    # decisions were reaching neither the audit log nor any durable history.
    # That gap is fixed here, and only here: no approval behaviour changes.
    #
    # timeout_seconds enables YELLOW approval-window expiry (Phase 6,
    # Batch 3): a pending YELLOW request unanswered for this many seconds
    # expires (ApprovalStatus.EXPIRED), never RED, and never as a decision.
    approval_history = ApprovalHistoryStore(session_factory)
    approvals = ApprovalManager(
        audit_logger=logger,
        history_store=approval_history,
        timeout_seconds=settings.approval_timeout_seconds,
    )

    # Planning.
    planner = Planner(security)

    # Tools, behind the security gate.
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryUpdateTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
    registry.register_tool(FileCreateTool())
    registry.register_tool(FileAppendTool())
    registry.register_tool(ApprovalHistoryTool(approval_history))
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,
    )

    # Command routing (Phase 7, Batch 1): matches request text to a
    # registered tool and builds its input. Extracted from the orchestrator
    # so the Core coordinates rather than performing command-matching itself.
    command_router = CommandRouter(registry)

    return JarvisOrchestrator(
        planner=planner,
        executor=executor,
        registry=registry,
        command_router=command_router,
        approval_manager=approvals,
    )


def main() -> None:
    """Build the system and start the interactive CLI."""
    orchestrator = build_orchestrator()
    cli = JarvisCLI(orchestrator)
    cli.run()


if __name__ == "__main__":
    main()