"""
approval_audit_smoke_test.py

A standalone smoke test for approval audit logging.

Run this directly (no pytest needed) to see approve and decline decisions
recorded in the real SQLite audit log. It creates two YELLOW requests, approves
one and declines the other through an ApprovalManager wired to the real
EventLogger, then reads the audit log back to show the recorded events.

Place this file in the project root and run it from PowerShell:

    poetry run python approval_audit_smoke_test.py
"""

from __future__ import annotations

from approval.approval_manager import ApprovalManager
from config.constants import SecurityTier
from config.settings import load_settings
from observability.logger import EventLogger
from security.audit_log import AuditLog
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)


def main() -> None:
    """Record two approval decisions and read them back from the audit log."""
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    audit_log = AuditLog(factory)
    logger = EventLogger(audit_log)

    manager = ApprovalManager(audit_logger=logger)

    print("Jarvis Approval Audit Logging - smoke test")
    print("=" * 70)
    print()

    before = audit_log.count()
    print(f"Audit log entries before: {before}")
    print()

    # Approve one request, decline another.
    email = manager.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
        session_id=None,
    )
    manager.approve(email.request_id, decided_by="user", reason="Looks good.")
    print(f"Approved: {email.action}")

    install = manager.create_request(
        action="install a package",
        reason="Installing changes the system.",
        security_tier=SecurityTier.YELLOW,
        session_id=None,
    )
    manager.decline(install.request_id, decided_by="user", reason="Not right now.")
    print(f"Declined: {install.action}")
    print()

    after = audit_log.count()
    print(f"Audit log entries after: {after}  (added {after - before})")
    print()

    print("Most recent audit entries:")
    for entry in audit_log.get_recent(limit=5):
        if entry.action_type == "approval_decision":
            print(f"  [{entry.outcome}] {entry.detail}")

    print()
    print("=" * 70)
    print("Every approve and decline is now permanently recorded in the audit")
    print("log, with the request_id, action, outcome, decider, and reason.")


if __name__ == "__main__":
    main()
