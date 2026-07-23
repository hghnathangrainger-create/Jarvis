"""
approval_models.py

Data structures for the Jarvis approval flow (Phase 2).

Responsibilities:
    - Define ApprovalRequest: a request to run a sensitive (YELLOW) action.
    - Define ApprovalDecision: the user's approve-or-decline answer.
    - Define ApprovalStatus: the lifecycle states of an approval.

Does NOT:
    - Connect to the Core, the CLI, or the Tool Executor.
    - Ask the user anything or run any action.
    - Call the Claude API or any AI provider.

These models are pure data with light validation. They describe what an
approval request and decision look like and enforce the rules that keep them
valid, but they perform no side effects. The logic that presents requests and
carries out approved actions lives in later Phase 2 modules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from config.constants import SecurityTier


def _utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime.

    Returns:
        The current moment in UTC, as a timezone-aware datetime.
    """
    return datetime.now(timezone.utc)


def _new_request_id() -> str:
    """Generate a unique identifier for an approval request.

    Returns:
        A new UUID string.
    """
    return str(uuid.uuid4())


class ApprovalError(Exception):
    """Raised when an approval request or decision is invalid.

    This is the single exception type for approval-model problems, so callers
    can catch invalid approvals distinctly from other errors.
    """


class ApprovalStatus(Enum):
    """The lifecycle state of an approval request.

    Attributes:
        PENDING: The request has been created and is awaiting a decision.
        APPROVED: The user approved the request.
        DECLINED: The user declined the request.
        EXPIRED: The request timed out before a decision was made.
    """

    PENDING = "pending"
    APPROVED = "approved"
    DECLINED = "declined"
    EXPIRED = "expired"


class PendingApprovalHandoffStatus(Enum):
    """The durable execution-handoff lifecycle state of one
    pending_approval_state row (Approval-to-Resume Handoff Interlock,
    Batch 1 - docs/phase_98_approval_handoff_plan.md).

    A wholly separate concept from ApprovalStatus above: ApprovalStatus
    describes whether a *decision* was made (approved/declined/
    expired); this enum describes whether an already-approved
    request's *execution* has actually been handed off to, and
    consumed by, a resuming workflow yet. Batch 1 adds this type, the
    matching pending_approval_state.handoff_status column, and narrow
    compare-and-set store primitives only - ApprovalManager's live
    approve()/decline()/_decide() lifecycle does not yet read or write
    this field; that wiring is deferred to a later, separately-accepted
    batch.

    Attributes:
        PENDING: The request has been created and is awaiting a
            decision. The initial, and only non-terminal-approval,
            state - matches every row ApprovalManager.create_request()
            persists today.
        APPROVED_UNCONSUMED: The request has been approved but no
            resuming workflow has yet claimed it for execution. Not
            written by any live code in Batch 1.
        CLAIMED: Exactly one caller has claimed this approved request
            for execution, via a single compare-and-set transition -
            a second, concurrent claim attempt always fails. Not
            written by any live code in Batch 1.
        CONSUMED: The claiming caller's execution handoff completed;
            this is a terminal state. Ownership transfer only - this
            never implies the underlying tool/workflow itself
            succeeded or failed, which remains recorded independently
            by WorkflowHistoryStore/ToolResult. Not written by any live
            code in Batch 1.
        CLAIM_INTERRUPTED: A claimed request whose execution outcome
            could not be confirmed (for example, a crash between claim
            and completion) - a terminal, manual-review state. No
            automatic replay and no reuse of the original approval is
            ever permitted from this state. Not written by any live
            code in Batch 1.
        DECLINED: The user declined the request - terminal, mirroring
            ApprovalStatus.DECLINED.
        EXPIRED: The request's approval window elapsed unanswered -
            terminal, mirroring ApprovalStatus.EXPIRED.
    """

    PENDING = "pending"
    APPROVED_UNCONSUMED = "approved_unconsumed"
    CLAIMED = "claimed"
    CONSUMED = "consumed"
    CLAIM_INTERRUPTED = "claim_interrupted"
    DECLINED = "declined"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """A request for the user to approve a sensitive (YELLOW) action.

    An ApprovalRequest may only be created for a YELLOW action. Attempting to
    create one for a GREEN action (which runs automatically) or a RED action
    (which is always blocked) raises ApprovalError, because neither should ever
    go through the approval flow.

    Attributes:
        action: The action string that requires approval.
        reason: A human-readable explanation of why approval is needed.
        security_tier: The security tier of the action. Must be YELLOW.
        session_id: Optional session the request belongs to.
        metadata: Optional extra string key/value details about the request.
        request_id: A unique identifier for this request. Generated if omitted.
        created_at: UTC timestamp of when the request was created. Set if
            omitted.
    """

    action: str
    reason: str
    security_tier: SecurityTier
    session_id: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    request_id: str = field(default_factory=_new_request_id)
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Validate the request immediately after construction.

        Raises:
            ApprovalError: If the action or reason is empty, or if the security
                tier is not YELLOW.
        """
        if not self.action.strip():
            raise ApprovalError("An approval request must have a non-empty action.")
        if not self.reason.strip():
            raise ApprovalError("An approval request must have a non-empty reason.")
        if self.security_tier is not SecurityTier.YELLOW:
            raise ApprovalError(
                "Approval requests are only valid for YELLOW actions. "
                f"Received tier: {self.security_tier.name}. GREEN actions run "
                "automatically and RED actions are always blocked, so neither "
                "should ever require approval."
            )

    def decide(self, *, approved: bool, decided_by: str, reason: str | None = None) -> ApprovalDecision:
        """Create a decision that answers this request.

        This is a convenience for producing an ApprovalDecision whose
        request_id already matches this request, so the two cannot drift apart.

        Args:
            approved: True to approve the action, False to decline it.
            decided_by: Who made the decision (for example, "user").
            reason: Optional explanation for the decision.

        Returns:
            An ApprovalDecision linked to this request.
        """
        return ApprovalDecision(
            request_id=self.request_id,
            approved=approved,
            decided_by=decided_by,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    """The user's answer to an approval request.

    A decision preserves the request_id of the request it answers, so the two
    can always be linked. An approved decision means the action may proceed; a
    declined decision means it must be cancelled.

    Attributes:
        request_id: The identifier of the request this decision answers.
        approved: True if the action was approved, False if declined.
        decided_by: Who made the decision (for example, "user").
        reason: Optional explanation for the decision.
        decided_at: UTC timestamp of when the decision was made. Set if
            omitted.
    """

    request_id: str
    approved: bool
    decided_by: str
    reason: str | None = None
    decided_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        """Validate the decision immediately after construction.

        Raises:
            ApprovalError: If the request_id or decided_by is empty.
        """
        if not self.request_id.strip():
            raise ApprovalError("A decision must reference a non-empty request_id.")
        if not self.decided_by.strip():
            raise ApprovalError("A decision must record who decided (decided_by).")

    @property
    def is_approved(self) -> bool:
        """Whether the action was approved.

        Returns:
            True if the action was approved.
        """
        return self.approved

    @property
    def is_declined(self) -> bool:
        """Whether the action was declined.

        Returns:
            True if the action was declined.
        """
        return not self.approved

    @property
    def status(self) -> ApprovalStatus:
        """The approval status implied by this decision.

        Returns:
            ApprovalStatus.APPROVED if approved, otherwise
            ApprovalStatus.DECLINED.
        """
        return ApprovalStatus.APPROVED if self.approved else ApprovalStatus.DECLINED