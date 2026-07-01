"""
approval

The Jarvis approval flow (Phase 2).

This package implements controlled approval of sensitive (YELLOW) actions: a
request is created, presented to the user, and either approved or declined
before anything runs. Phase 2 begins with the data models below; later modules
add the component and interface that use them.

Exposed here:
    - ApprovalRequest: a request to approve a YELLOW action.
    - ApprovalDecision: the user's approve-or-decline answer.
    - ApprovalStatus: the lifecycle states of an approval.
    - ApprovalError: raised when a request or decision is invalid.
"""

from __future__ import annotations

from approval.approval_models import (
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    ApprovalStatus,
)

__all__ = [
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalStatus",
    "ApprovalError",
]