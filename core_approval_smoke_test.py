"""
core_approval_smoke_test.py

A standalone smoke test for the Jarvis Core approval integration (Phase 2).

Run this directly (no pytest needed) to see how the Core now handles each kind
of request against a real SQLite database: GREEN runs, RED is blocked, and
YELLOW creates a pending approval request that appears in the response and in
the Approval Manager. No YELLOW action is executed at this step.

Place this file in the project root and run it from PowerShell:

    poetry run python core_approval_smoke_test.py
"""

from __future__ import annotations

from config.settings import load_settings
from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse
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
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry

_SAMPLE_REQUESTS: tuple[str, ...] = (
    "show me system info",
    "echo Hello from Jarvis",
    "search memories for trading",
    "send email to Alex",
    "install a new program",
    "format drive C",
    "disable antivirus",
)


def _status(response: JarvisResponse) -> str:
    if response.blocked:
        return "BLOCKED"
    if response.requires_confirmation:
        return "NEEDS APPROVAL"
    if response.success:
        return "OK"
    return "NOT HANDLED"


def _print(request: str, response: JarvisResponse) -> None:
    print(f"> {request}")
    print(f"  [{_status(response)}] {response.message.splitlines()[0]}")
    if response.approval_request is not None:
        approval = response.approval_request
        print(f"    approval_request id: {approval.request_id[:8]}")
        print(f"    action: {approval.action}")
        print(f"    tier:   {approval.security_tier.name}")
    print()


def main() -> None:
    """Wire up the Core and run a representative set of requests."""
    settings = load_settings()

    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(factory))
    memory.save("Nathan is learning trading.", source="smoke_test")

    security = SecurityManager()
    planner = Planner(security)
    logger = EventLogger(AuditLog(factory))

    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))

    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    core = JarvisOrchestrator(planner=planner, executor=executor, registry=registry)

    print("Jarvis Core - approval integration smoke test")
    print("=" * 70)
    print()

    for request in _SAMPLE_REQUESTS:
        _print(request, core.handle_request(request))

    pending = core.approvals.list_pending()
    print("=" * 70)
    print(f"Pending approval requests now held by the Core: {len(pending)}")
    for request in pending:
        print(f"  [{request.request_id[:8]}] {request.action}")
    print()
    print("YELLOW actions created approval requests but were NOT executed.")
    print("GREEN ran automatically. RED stayed blocked.")


if __name__ == "__main__":
    main()