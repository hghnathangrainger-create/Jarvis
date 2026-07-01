"""
approval_manager_smoke_test.py

A standalone smoke test for the Jarvis ApprovalManager.

Run this directly (no pytest needed) to watch the full approval lifecycle in
memory: requests are created and listed as pending, one is approved and one is
declined, both then move out of pending into completed decisions, and invalid
operations (unknown ids, deciding twice) are correctly rejected.

Place this file in the project root and run it from PowerShell:

    poetry run python approval_manager_smoke_test.py
"""

from __future__ import annotations

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalError
from config.constants import SecurityTier


def main() -> None:
    """Demonstrate the approval manager lifecycle end to end."""
    manager = ApprovalManager()

    print("Jarvis Approval Manager - smoke test")
    print("=" * 70)
    print()

    # Create two pending requests.
    email = manager.create_request(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
        metadata={"to": "alex@example.com"},
    )
    install = manager.create_request(
        action="install a package",
        reason="Installing changes the system.",
        security_tier=SecurityTier.YELLOW,
    )

    print("Pending requests after creation:")
    for request in manager.list_pending():
        print(f"  [{request.request_id[:8]}] {request.action}")
    print()

    # Approve the first, decline the second.
    approved = manager.approve(email.request_id, reason="Looks fine.")
    declined = manager.decline(install.request_id, reason="Not right now.")

    print(f"Approved: {email.action}  ->  status {approved.status.name}")
    print(f"Declined: {install.action}  ->  status {declined.status.name}")
    print()

    print("Pending requests after decisions:")
    remaining = manager.list_pending()
    if remaining:
        for request in remaining:
            print(f"  [{request.request_id[:8]}] {request.action}")
    else:
        print("  (none - both requests were decided)")
    print()

    print("Recorded decisions:")
    for decision in manager.list_decisions():
        outcome = "APPROVED" if decision.is_approved else "DECLINED"
        print(f"  [{decision.request_id[:8]}] {outcome} by {decision.decided_by}")
    print()

    # Show that invalid operations are rejected.
    print("Invalid operations are rejected:")
    _try(lambda: manager.get_pending("no-such-id"), "get unknown pending")
    _try(lambda: manager.get_decision("no-such-id"), "get unknown decision")
    _try(lambda: manager.approve(email.request_id), "approve an already-decided request")

    print()
    print("=" * 70)
    print("Each request has exactly one decision. Once decided, it leaves")
    print("pending and cannot be decided again.")


def _try(operation, label: str) -> None:
    """Run an operation expected to fail and report the rejection."""
    try:
        operation()
        print(f"  [NOT REJECTED] {label} (this should not happen)")
    except ApprovalError as exc:
        print(f"  [rejected] {label}: {exc}")


if __name__ == "__main__":
    main()