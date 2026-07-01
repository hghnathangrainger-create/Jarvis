"""
approval_manager.py

In-memory management of approval requests and decisions (Phase 2).

Responsibilities:
    - Create and hold pending approval requests.
    - Look up and list pending requests.
    - Approve or decline a pending request, producing a decision.
    - Move a request from pending to completed once it is decided.
    - Store and retrieve completed decisions.

Does NOT:
    - Use the database (this component is purely in-memory for now).
    - Connect to audit logging, the CLI, or the Core.
    - Call the Claude API or any AI provider.
    - Ask the user anything or run any action.

The manager owns the lifecycle of an approval: a request starts pending, and
exactly one decision moves it to completed. Because a decided request is no
longer pending, it cannot be decided a second time. Keeping this in memory and
free of side effects makes the lifecycle simple to reason about and to test.
"""

from __future__ import annotations

from approval.approval_models import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
)
from config.constants import SecurityTier


class ApprovalManager:
    """Manages pending approval requests and completed decisions in memory.

    A single manager instance holds all currently pending requests and every
    decision made so far. Requests are keyed by their request_id.

    Attributes:
        _pending: Mapping of request_id to a pending ApprovalRequest.
        _decisions: Mapping of request_id to a completed ApprovalDecision.
    """

    def __init__(self) -> None:
        """Initialise an empty approval manager."""
        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    def create_request(
        self,
        action: str,
        reason: str,
        security_tier: SecurityTier,
        *,
        session_id: int | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ApprovalRequest:
        """Create a pending approval request and store it.

        Validation of the action, reason, and security tier is performed by
        ApprovalRequest itself, so a GREEN or RED tier, or an empty action or
        reason, raises ApprovalError before the request is stored.

        Args:
            action: The action string that requires approval.
            reason: A human-readable explanation of why approval is needed.
            security_tier: The security tier of the action. Must be YELLOW.
            session_id: Optional session the request belongs to.
            metadata: Optional extra string details about the request.

        Returns:
            The newly created, pending ApprovalRequest.

        Raises:
            ApprovalError: If the request is invalid (see ApprovalRequest).
        """
        request = ApprovalRequest(
            action=action,
            reason=reason,
            security_tier=security_tier,
            session_id=session_id,
            metadata=dict(metadata) if metadata is not None else {},
        )
        self._pending[request.request_id] = request
        return request

    def get_pending(self, request_id: str) -> ApprovalRequest:
        """Return the pending request with the given id.

        Args:
            request_id: The identifier of the pending request.

        Returns:
            The pending ApprovalRequest.

        Raises:
            ApprovalError: If no pending request has that id.
        """
        request = self._pending.get(request_id)
        if request is None:
            raise ApprovalError(
                f"No pending approval request with id '{request_id}'. It may not "
                "exist, or it may already have been approved or declined."
            )
        return request

    def list_pending(self) -> list[ApprovalRequest]:
        """Return all currently pending requests, oldest first.

        Returns:
            A list of pending ApprovalRequest objects ordered by creation time.
        """
        return sorted(self._pending.values(), key=lambda r: r.created_at)

    def has_pending(self, request_id: str) -> bool:
        """Report whether a request with the given id is still pending.

        Args:
            request_id: The identifier to check.

        Returns:
            True if the request is pending, False otherwise.
        """
        return request_id in self._pending

    def approve(
        self,
        request_id: str,
        *,
        decided_by: str = "user",
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Approve a pending request and record the decision.

        Args:
            request_id: The identifier of the pending request to approve.
            decided_by: Who made the decision. Defaults to "user".
            reason: Optional explanation for the approval.

        Returns:
            The recorded ApprovalDecision (approved).

        Raises:
            ApprovalError: If the request is not pending (unknown id, or it was
                already decided).
        """
        return self._decide(
            request_id, approved=True, decided_by=decided_by, reason=reason
        )

    def decline(
        self,
        request_id: str,
        *,
        decided_by: str = "user",
        reason: str | None = None,
    ) -> ApprovalDecision:
        """Decline a pending request and record the decision.

        Args:
            request_id: The identifier of the pending request to decline.
            decided_by: Who made the decision. Defaults to "user".
            reason: Optional explanation for the decline.

        Returns:
            The recorded ApprovalDecision (declined).

        Raises:
            ApprovalError: If the request is not pending (unknown id, or it was
                already decided).
        """
        return self._decide(
            request_id, approved=False, decided_by=decided_by, reason=reason
        )

    def get_decision(self, request_id: str) -> ApprovalDecision:
        """Return the completed decision for the given request id.

        Args:
            request_id: The identifier of the decided request.

        Returns:
            The recorded ApprovalDecision.

        Raises:
            ApprovalError: If no decision has been recorded for that id.
        """
        decision = self._decisions.get(request_id)
        if decision is None:
            raise ApprovalError(
                f"No decision recorded for request id '{request_id}'. It may not "
                "exist, or it may still be pending."
            )
        return decision

    def list_decisions(self) -> list[ApprovalDecision]:
        """Return all completed decisions, oldest first.

        Returns:
            A list of ApprovalDecision objects ordered by decision time.
        """
        return sorted(self._decisions.values(), key=lambda d: d.decided_at)

    def _decide(
        self,
        request_id: str,
        *,
        approved: bool,
        decided_by: str,
        reason: str | None,
    ) -> ApprovalDecision:
        """Resolve a pending request into a decision.

        The request is looked up (raising if not pending), a decision is
        created from it, the request is removed from pending, and the decision
        is stored. Removing it from pending is what prevents a second decision.

        Args:
            request_id: The identifier of the pending request.
            approved: True to approve, False to decline.
            decided_by: Who made the decision.
            reason: Optional explanation for the decision.

        Returns:
            The recorded ApprovalDecision.

        Raises:
            ApprovalError: If the request is not pending.
        """
        request = self.get_pending(request_id)
        decision = request.decide(
            approved=approved, decided_by=decided_by, reason=reason
        )
        del self._pending[request_id]
        self._decisions[request_id] = decision
        return decision