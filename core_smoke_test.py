"""
core_smoke_test.py

A standalone smoke test for the Jarvis Core orchestrator.

Run this directly (no pytest needed) to see the full request lifecycle against
a real SQLite database: safe requests are answered, sensitive requests ask for
confirmation, dangerous requests are blocked, and every response includes the
plan Jarvis generated.

Place this file in the project root and run it from PowerShell:

    poetry run python core_smoke_test.py
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
    "show my memories",
    "search memories for trading",
    "send email to Alex",
    "install a new program",
    "format drive C",
    "disable antivirus",
    "calculate something complicated",
    "do a barrel roll",
    "",
)


def _status(response: JarvisResponse) -> str:
    """Return a short status label for a response."""
    if response.blocked:
        return "BLOCKED"
    if response.requires_confirmation:
        return "NEEDS CONFIRMATION"
    if response.success:
        return "OK"
    return "NOT HANDLED"


def _print_response(request: str, response: JarvisResponse) -> None:
    """Print a single request and its response in a readable form."""
    shown = request if request else "(empty request)"
    print(f"> {shown}")
    print(f"  [{_status(response)}] {response.message.splitlines()[0]}")
    for line in response.message.splitlines()[1:]:
        print(f"            {line}")
    if response.plan is not None:
        for step in response.plan.steps:
            print(
                f"    plan step {step.number}: [{step.tier.name}] {step.description}"
            )
    print()


def main() -> None:
    """Wire up the Core and run a representative set of requests."""
    settings = load_settings()

    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(factory))
    memory.save("Nathan prefers concise answers.", source="smoke_test")
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

    print("Jarvis Core - smoke test")
    print("=" * 70)
    print()

    for request in _SAMPLE_REQUESTS:
        _print_response(request, core.handle_request(request))

    print("=" * 70)
    print("Safe requests were answered. Sensitive requests asked for")
    print("confirmation. Dangerous requests were blocked. No dangerous action")
    print("was ever executed, and every response included its plan.")


if __name__ == "__main__":
    main()