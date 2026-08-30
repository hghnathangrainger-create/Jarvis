"""
security_manager_v2.py

Enhanced Security Manager for the Jarvis AI Operating System — Chapter 12.

Responsibilities:
    - Classify actions into GREEN/YELLOW/RED tiers.
    - Detect prompt injection attempts with confidence scoring.
    - Manage approval workflows for YELLOW/RED actions.
    - Log all security events to the audit trail.
    - Expire stale approval requests.

Does NOT:
    - Execute actions (only classifies and approves/denies).
    - Implement AI logic.
    - Connect to external security services.

This module enhances the existing SecurityManager (security_manager.py)
with approval workflows, injection enforcement, and event logging.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from security.models import (
    ApprovalRequest,
    ApprovalStatus,
    InjectionResult,
    SecurityEvent,
    SecurityLevel,
)
from security.injection_detector import InjectionDetector
from security.approval_store import ApprovalStore

logger = logging.getLogger(__name__)


class SecurityManagerV2:
    """Enhanced Security Manager with approval workflows and injection detection.

    Combines action classification, injection detection, approval management,
    and security event logging into a single cohesive interface.

    Attributes:
        _injection_detector: The injection detection engine.
        _approval_store: SQLite-backed approval persistence.
        _security_events: In-memory list of recent security events.
        _injection_stats: Counters for injection detection by technique.
    """

    def __init__(
        self,
        injection_sensitivity: str = "medium",
        approval_ttl_seconds: int = 300,
        log_all_green: bool = False,
    ) -> None:
        """Initialise the enhanced security manager.

        Args:
            injection_sensitivity: Detection threshold (low/medium/high).
            approval_ttl_seconds: Seconds before pending approvals expire.
            log_all_green: If True, log GREEN actions too.
        """
        self._injection_detector = InjectionDetector(sensitivity=injection_sensitivity)
        self._approval_store = ApprovalStore()
        self._approval_ttl = approval_ttl_seconds
        self._log_all_green = log_all_green
        self._security_events: list[SecurityEvent] = []
        self._injection_stats: dict[str, int] = {}

    # -------------------------------------------------------------------
    # Action classification (delegates to existing SecurityManager logic)
    # -------------------------------------------------------------------

    def classify_action(self, action: str) -> SecurityLevel:
        """Classify an action into a security tier.

        Uses keyword-based classification with the existing rule set.

        Args:
            action: The action to classify.

        Returns:
            The SecurityLevel (GREEN, YELLOW, or RED).
        """
        from security.security_manager import SecurityManager

        legacy = SecurityManager()
        decision = legacy.classify_action(action)
        return SecurityLevel(decision.tier.value)

    # -------------------------------------------------------------------
    # Injection detection
    # -------------------------------------------------------------------

    def check_input(self, text: str) -> InjectionResult:
        """Check input text for prompt injection patterns.

        Args:
            text: The text to analyze.

        Returns:
            InjectionResult with confidence score and technique details.
        """
        result = self._injection_detector.detect(text)

        if result.is_injection:
            # Update stats
            for pattern in result.patterns:
                self._injection_stats[pattern] = self._injection_stats.get(pattern, 0) + 1

            # Log the event
            self.log_event(
                level=SecurityLevel.RED,
                action="prompt_injection_detected",
                tool_name="security",
                details=f"Confidence: {result.confidence}, Technique: {result.technique}",
                approved=False,
            )

        return result

    def get_injection_stats(self) -> dict[str, Any]:
        """Return injection detection statistics.

        Returns:
            Dict with total detections and breakdown by technique.
        """
        return {
            "total_detections": sum(self._injection_stats.values()),
            "by_pattern": dict(self._injection_stats),
        }

    # -------------------------------------------------------------------
    # Approval workflows
    # -------------------------------------------------------------------

    def request_approval(
        self,
        action: str,
        tool_name: str,
        input_data: dict[str, Any] | None = None,
        level: SecurityLevel | None = None,
    ) -> ApprovalRequest:
        """Create an approval request for a sensitive action.

        Args:
            action: The action description.
            tool_name: The tool that would execute.
            input_data: The input the tool would receive.
            level: Security level (YELLOW or RED). Auto-detected if None.

        Returns:
            The created ApprovalRequest.
        """
        if level is None:
            level = self.classify_action(action)

        expires_at = None
        if level == SecurityLevel.YELLOW:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self._approval_ttl)

        request = ApprovalRequest(
            request_id=str(uuid.uuid4()),
            action=action,
            tool_name=tool_name,
            input_data=input_data or {},
            level=level,
            requested_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            status=ApprovalStatus.PENDING,
        )

        self._approval_store.save_request(request)

        self.log_event(
            level=level,
            action=action,
            tool_name=tool_name,
            details=f"Approval requested (ID: {request.request_id})",
            approved=False,
        )

        return request

    def approve(self, request_id: str, response: str | None = None) -> bool:
        """Approve a pending request.

        Args:
            request_id: The request to approve.
            response: Optional response text from the approver.

        Returns:
            True if the request was found and approved.
        """
        request = self._approval_store.get_request(request_id)
        if request is None or request.status != ApprovalStatus.PENDING:
            return False

        success = self._approval_store.update_status(
            request_id, ApprovalStatus.APPROVED, response
        )

        if success:
            self.log_event(
                level=request.level,
                action=request.action,
                tool_name=request.tool_name,
                details=f"Approved (ID: {request_id})",
                approved=True,
            )

        return success

    def deny(self, request_id: str, reason: str | None = None) -> bool:
        """Deny a pending request.

        Args:
            request_id: The request to deny.
            reason: Reason for denial.

        Returns:
            True if the request was found and denied.
        """
        request = self._approval_store.get_request(request_id)
        if request is None or request.status != ApprovalStatus.PENDING:
            return False

        success = self._approval_store.update_status(
            request_id, ApprovalStatus.DENIED, reason
        )

        if success:
            self.log_event(
                level=request.level,
                action=request.action,
                tool_name=request.tool_name,
                details=f"Denied (ID: {request_id}, reason: {reason})",
                approved=False,
            )

        return success

    def get_pending_approvals(self) -> list[ApprovalRequest]:
        """Get all pending approval requests.

        Returns:
            List of pending ApprovalRequest objects.
        """
        # Auto-expire old requests first
        self._approval_store.expire_old_requests(ttl_seconds=self._approval_ttl)
        return self._approval_store.list_pending()

    def expire_requests(self, ttl_seconds: int | None = None) -> int:
        """Expire old pending requests.

        Args:
            ttl_seconds: Override the default TTL.

        Returns:
            Number of requests that were expired.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._approval_ttl
        return self._approval_store.expire_old_requests(ttl_seconds=ttl)

    # -------------------------------------------------------------------
    # Security event logging
    # -------------------------------------------------------------------

    def log_event(
        self,
        level: SecurityLevel,
        action: str,
        tool_name: str,
        details: str = "",
        approved: bool = True,
    ) -> SecurityEvent:
        """Log a security event.

        Args:
            level: The security level.
            action: The action description.
            tool_name: The tool involved.
            details: Additional details.
            approved: Whether the action was approved.

        Returns:
            The created SecurityEvent.
        """
        # Skip GREEN logging if not enabled
        if level == SecurityLevel.GREEN and not self._log_all_green:
            # Still create the event but don't store it
            return SecurityEvent(
                level=level,
                action=action,
                tool_name=tool_name,
                details=details,
                approved=approved,
            )

        event = SecurityEvent(
            level=level,
            action=action,
            tool_name=tool_name,
            details=details,
            approved=approved,
        )

        self._security_events.append(event)

        # Keep only the last 1000 events in memory
        if len(self._security_events) > 1000:
            self._security_events = self._security_events[-1000:]

        return event

    def get_security_events(self, limit: int = 100) -> list[SecurityEvent]:
        """Get recent security events.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of SecurityEvent objects, newest first.
        """
        return list(reversed(self._security_events[-limit:]))

    # -------------------------------------------------------------------
    # Full pipeline: classify + check injection + request approval
    # -------------------------------------------------------------------

    def enforce(
        self,
        action: str,
        tool_name: str,
        input_data: dict[str, Any] | None = None,
        user_input: str | None = None,
    ) -> dict[str, Any]:
        """Full security enforcement pipeline.

        Classifies the action, checks for injection, and requests approval
        if needed.

        Args:
            action: The action to evaluate.
            tool_name: The tool that would execute.
            input_data: The tool input data.
            user_input: Optional user input to scan for injection.

        Returns:
            Dict with classification, injection check, and approval status.
        """
        result: dict[str, Any] = {
            "action": action,
            "tool_name": tool_name,
            "approved": False,
            "level": None,
            "injection": None,
            "approval_request": None,
        }

        # 1. Classify the action
        level = self.classify_action(action)
        result["level"] = level.value

        # 2. Check for injection if user input is provided
        if user_input:
            injection_result = self.check_input(user_input)
            result["injection"] = injection_result.to_dict()

            if injection_result.is_injection:
                result["denied_reason"] = "Prompt injection detected"
                self.log_event(
                    level=SecurityLevel.RED,
                    action=action,
                    tool_name=tool_name,
                    details=f"Blocked due to injection: {injection_result.technique}",
                    approved=False,
                )
                return result

        # 3. Handle by tier
        if level == SecurityLevel.GREEN:
            result["approved"] = True
            self.log_event(
                level=level,
                action=action,
                tool_name=tool_name,
                details="Auto-approved (GREEN tier)",
                approved=True,
            )
        else:
            # YELLOW or RED: create approval request
            approval = self.request_approval(
                action=action,
                tool_name=tool_name,
                input_data=input_data,
                level=level,
            )
            result["approval_request"] = approval.to_dict()

        return result
