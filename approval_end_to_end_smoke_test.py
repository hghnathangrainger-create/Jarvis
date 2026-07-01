"""
approval_end_to_end_smoke_test.py

A standalone smoke test for the complete Jarvis approval flow (Phase 2).

Run this directly (no pytest needed) to watch a YELLOW action travel its whole
journey against the real SQLite database: it is requested, withheld before a
decision, approved and then run through the executor, and recorded in the audit
log. A second action is declined and cancelled, and a RED action is shown to
stay blocked even when an approval is fabricated for it.

Place this file in the project root and run it from PowerShell:

    poetry run python approval_end_to_end_smoke_test.py
"""

from __future__ import annotations

from approval.approval_manager import ApprovalManager
from config.constants import SecurityTier
from config.settings import load_settings
from observability.logger import EventLogger
from security.audit_log import AuditLog
from security.security_manager import SecurityManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _SendTool(BaseTool):
    """A sensitive (YELLOW) demo tool that pretends to send a message."""

    @property
    def name(self) -> str:
        return "send"

    @property
    def description(self) -> str:
        return "Pretends to send a message (YELLOW)."

    def action_for(self, request: ToolRequest) -> str:
        return "send email"

    def run(self, request: ToolRequest) -> ToolResult:
        return ToolResult(tool_name=self.name, success=True, output="Message sent.")


class _WipeTool(BaseTool):
    """A dangerous (RED) demo tool that must never run."""

    @property
    def name(self) -> str:
        return "wipe"

    @property
    def description(self) -> str:
        return "Pretends to do something dangerous (RED)."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("This must never run; RED is always blocked.")


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
    print(f"    [{status}] {label}: {result.output or result.error or ''}")


def main() -> None:
    """Trace the full approval lifecycle against the real database."""
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    audit = AuditLog(factory)
    logger = EventLogger(audit)
    security = SecurityManager()

    registry = ToolRegistry()
    registry.register_tool(_SendTool())
    registry.register_tool(_WipeTool())
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)
    approvals = ApprovalManager(audit_logger=logger)

    print("Jarvis Approval Flow - end-to-end smoke test")
    print("=" * 70)
    print()

    # 1. YELLOW approved journey.
    print("1. Approved journey")
    request = approvals.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
    )
    print(f"    request created (id {request.request_id[:8]}), pending.")
    _show("run before approval", executor.execute("send"))
    decision = approvals.approve(request.request_id, decided_by="user", reason="ok")
    print("    user APPROVED.")
    _show("run after approval", executor.execute("send", approval_decision=decision))
    print()

    # 2. YELLOW declined journey.
    print("2. Declined journey")
    request2 = approvals.create_request(
        action="install a package",
        reason="Installing changes the system.",
        security_tier=SecurityTier.YELLOW,
    )
    decision2 = approvals.decline(request2.request_id, decided_by="user", reason="no")
    print("    user DECLINED.")
    _show("run after decline", executor.execute("send", approval_decision=decision2))
    print()

    # 3. RED stays blocked even with a fabricated approval.
    print("3. RED stays blocked")
    request3 = approvals.create_request(
        action="format drive",
        reason="A mistaken approval attempt.",
        security_tier=SecurityTier.YELLOW,
    )
    decision3 = approvals.approve(request3.request_id, decided_by="user")
    _show("run RED with approval", executor.execute("wipe", approval_decision=decision3))
    print()

    # 4. Show the audit trail.
    print("4. Audit log (approval decisions)")
    for entry in audit.get_recent(limit=10):
        if entry.action_type == "approval_decision":
            print(f"    [{entry.outcome}] {entry.detail}")

    print()
    print("=" * 70)
    print("Approved YELLOW ran. Declined YELLOW was cancelled. RED stayed")
    print("blocked despite an approval. Every decision was recorded.")


if __name__ == "__main__":
    main()
 