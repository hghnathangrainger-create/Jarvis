"""
tool_executor_approval_smoke_test.py

A standalone smoke test for the Jarvis ToolExecutor approved-YELLOW path.

Run this directly (no pytest needed) to see the security gate decide each case:
a GREEN tool runs, a YELLOW tool is withheld without approval, runs with an
approved decision, and is withheld with a declined decision, and a RED tool
stays blocked even when an approved decision is supplied.

Place this file in the project root and run it from PowerShell:

    poetry run python tool_executor_approval_smoke_test.py
"""

from __future__ import annotations

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier
from observability.logger import EventLogger
from security.audit_log import AuditLog
from security.security_manager import SecurityManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from config.settings import load_settings
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _DemoSendTool(BaseTool):
    """A demo tool with a sensitive (YELLOW) action."""

    @property
    def name(self) -> str:
        return "demo_send"

    @property
    def description(self) -> str:
        return "Pretends to send a message (YELLOW)."

    def action_for(self, request: ToolRequest) -> str:
        return "send email"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="Message sent.")


class _DemoDeleteTool(BaseTool):
    """A demo tool with a dangerous (RED) action."""

    @property
    def name(self) -> str:
        return "demo_delete"

    @property
    def description(self) -> str:
        return "Pretends to do something dangerous (RED)."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("This must never run; RED is always blocked.")


def _approved(action: str):
    request = ApprovalRequest(
        action=action, reason="user approved", security_tier=SecurityTier.YELLOW
    )
    return request.decide(approved=True, decided_by="user")


def _declined(action: str):
    request = ApprovalRequest(
        action=action, reason="user declined", security_tier=SecurityTier.YELLOW
    )
    return request.decide(approved=False, decided_by="user")


def _show(label: str, result: ToolResult) -> None:
    status = (
        "BLOCKED"
        if result.blocked
        else "WITHHELD"
        if result.requires_confirmation
        else "OK"
        if result.success
        else "FAILED"
    )
    print(f"[{status:9}] {label}")
    if result.output:
        print(f"            output: {result.output}")
    if result.metadata.get("approval_request_id"):
        print(f"            approved via: {result.metadata['approval_request_id'][:8]}")
    print()


def main() -> None:
    """Wire up the executor and demonstrate every approval outcome."""
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    logger = EventLogger(AuditLog(factory))
    security = SecurityManager()

    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(_DemoSendTool())
    registry.register_tool(_DemoDeleteTool())

    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)

    print("Jarvis ToolExecutor - approved YELLOW path smoke test")
    print("=" * 70)
    print()

    _show("GREEN echo, no approval", executor.execute("echo", {"text": "Hello."}))
    _show("YELLOW send, no approval", executor.execute("demo_send"))
    _show(
        "YELLOW send, APPROVED",
        executor.execute("demo_send", approval_decision=_approved("send email")),
    )
    _show(
        "YELLOW send, DECLINED",
        executor.execute("demo_send", approval_decision=_declined("send email")),
    )
    _show(
        "RED delete, APPROVED (must stay blocked)",
        executor.execute("demo_delete", approval_decision=_approved("format drive")),
    )

    print("=" * 70)
    print("Only an approved YELLOW action ran. RED stayed blocked even with an")
    print("approved decision. The Security Manager remains the source of truth.")


if __name__ == "__main__":
    main()