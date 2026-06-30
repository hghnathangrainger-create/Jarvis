"""
tools_smoke_test.py

A standalone smoke test for the Jarvis Tool Manager.

Run this directly (no pytest needed) to see the full tool-execution safety
gate in action against a real SQLite database: GREEN tools run, YELLOW actions
are withheld pending confirmation, and RED actions are blocked. It also shows
the memory tool listing and searching real stored memories.

Place this file in the project root and run it from PowerShell:

    poetry run python tools_smoke_test.py
"""

from __future__ import annotations

from config.settings import load_settings
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from observability.logger import EventLogger
from security.audit_log import AuditLog
from security.security_manager import SecurityManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _DemoDeleteTool(BaseTool):
    """A demo tool whose action is dangerous, to show RED blocking.

    Its run method intentionally raises: the safety gate must block the action
    before run is ever reached.
    """

    @property
    def name(self) -> str:
        return "demo_delete"

    @property
    def description(self) -> str:
        return "Demonstration tool with a dangerous action (never runs)."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("This must never run; the gate should block it.")


class _DemoSendTool(BaseTool):
    """A demo tool whose action is sensitive, to show YELLOW confirmation."""

    @property
    def name(self) -> str:
        return "demo_send"

    @property
    def description(self) -> str:
        return "Demonstration tool with a sensitive action (needs confirmation)."

    def action_for(self, request: ToolRequest) -> str:
        return "send email"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("This must not run without confirmation.")


def _show(label: str, result: ToolResult) -> None:
    """Print a single tool result in a readable form."""
    status = (
        "BLOCKED"
        if result.blocked
        else "NEEDS CONFIRMATION"
        if result.requires_confirmation
        else "OK"
        if result.success
        else "FAILED"
    )
    print(f"[{status:18}] {label}")
    if result.output:
        for line in result.output.splitlines():
            print(f"                     {line}")
    if result.error:
        print(f"                     {result.error}")
    print()


def main() -> None:
    """Wire up the tool system and run a representative set of tool calls."""
    settings = load_settings()

    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(factory))
    memory.save("Nathan prefers concise answers.", source="smoke_test")
    memory.save("Nathan is learning trading.", source="smoke_test")

    logger = EventLogger(AuditLog(factory))
    security = SecurityManager()

    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(_DemoSendTool())
    registry.register_tool(_DemoDeleteTool())

    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)

    print("Jarvis Tool Manager - smoke test")
    print("=" * 70)
    print(f"Registered tools: {', '.join(registry.list_tool_names())}")
    print()

    _show("echo (GREEN)", executor.execute("echo", {"text": "Hello from Jarvis."}))
    _show("info (GREEN)", executor.execute("info"))
    _show("memory list (GREEN)", executor.execute("memory", {"operation": "list"}))
    _show(
        "memory search 'trading' (GREEN)",
        executor.execute("memory", {"operation": "search", "query": "trading"}),
    )
    _show("demo_send (YELLOW)", executor.execute("demo_send"))
    _show("demo_delete (RED)", executor.execute("demo_delete"))
    _show("unknown tool", executor.execute("does_not_exist"))

    print("=" * 70)
    print("GREEN tools ran. The YELLOW action needed confirmation. The RED")
    print("action was blocked. No dangerous tool ever executed.")


if __name__ == "__main__":
    main()