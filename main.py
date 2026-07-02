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

from config.settings import load_settings
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
    EchoTool,
    FileListTool,
    FileReadTool,
    InfoTool,
    MemoryTool,
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

    # Planning.
    planner = Planner(security)

    # Tools, behind the security gate.
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,
    )

    return JarvisOrchestrator(planner=planner, executor=executor, registry=registry)


def main() -> None:
    """Build the system and start the interactive CLI."""
    orchestrator = build_orchestrator()
    cli = JarvisCLI(orchestrator)
    cli.run()


if __name__ == "__main__":
    main()