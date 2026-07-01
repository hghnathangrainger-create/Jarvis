"""
approval_models_smoke_test.py

A standalone smoke test for the Jarvis approval data models.

Run this directly (no pytest needed) to see how approval requests and
decisions behave: a valid YELLOW request is created, approved and declined
decisions are shown, and invalid requests (GREEN, RED, empty fields) are
correctly rejected.

Place this file in the project root and run it from PowerShell:

    poetry run python approval_models_smoke_test.py
"""

from __future__ import annotations

from approval import ApprovalError, ApprovalRequest
from config.constants import SecurityTier


def main() -> None:
    """Demonstrate the approval models and their validation rules."""
    print("Jarvis Approval Models - smoke test")
    print("=" * 70)
    print()

    # A valid YELLOW request.
    request = ApprovalRequest(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
        session_id=1,
        metadata={"to": "alex@example.com"},
    )
    print("Created a valid YELLOW approval request:")
    print(f"  request_id:  {request.request_id}")
    print(f"  action:      {request.action}")
    print(f"  reason:      {request.reason}")
    print(f"  tier:        {request.security_tier.name}")
    print(f"  created_at:  {request.created_at.isoformat()}")
    print(f"  metadata:    {request.metadata}")
    print()

    # Approve it.
    approved = request.decide(approved=True, decided_by="user")
    print("Approved decision:")
    print(f"  request_id:  {approved.request_id}")
    print(f"  is_approved: {approved.is_approved}")
    print(f"  status:      {approved.status.name}")
    print()

    # Decline it.
    declined = request.decide(approved=False, decided_by="user", reason="Not right now")
    print("Declined decision:")
    print(f"  request_id:  {declined.request_id}")
    print(f"  is_declined: {declined.is_declined}")
    print(f"  status:      {declined.status.name}")
    print(f"  reason:      {declined.reason}")
    print()

    # Show that invalid requests are rejected.
    print("Invalid requests are rejected:")
    _try_invalid("GREEN action", "search memories", "read only", SecurityTier.GREEN)
    _try_invalid("RED action", "format drive", "dangerous", SecurityTier.RED)
    _try_invalid("empty action", "   ", "a reason", SecurityTier.YELLOW)
    _try_invalid("empty reason", "send email", "   ", SecurityTier.YELLOW)

    print()
    print("=" * 70)
    print("Approval requests are only ever valid for YELLOW actions.")
    print("GREEN runs automatically; RED is always blocked; neither needs approval.")


def _try_invalid(
    label: str, action: str, reason: str, tier: SecurityTier
) -> None:
    """Attempt an invalid request and report that it was rejected."""
    try:
        ApprovalRequest(action=action, reason=reason, security_tier=tier)
        print(f"  [NOT REJECTED] {label} (this should not happen)")
    except ApprovalError as exc:
        print(f"  [rejected] {label}: {exc}")


if __name__ == "__main__":
    main()