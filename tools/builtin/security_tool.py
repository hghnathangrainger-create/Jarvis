"""
security_tool.py

YELLOW-tier tool for security management in the Jarvis AI Operating System.

Provides actions:
  - check: Test a string for injection (returns detection result)
  - approvals: List pending approval requests
  - approve: Approve a pending request by ID
  - deny: Deny a pending request by ID with reason
  - events: Show recent security events
  - stats: Show injection detection statistics
"""

from __future__ import annotations

from typing import Any

from security.security_manager_v2 import SecurityManagerV2
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class SecurityTool(BaseTool):
    """Tool for security management and injection detection."""

    @property
    def name(self) -> str:
        return "security"

    @property
    def description(self) -> str:
        return "Security management: injection detection, approvals, events, stats"

    tier = "YELLOW"

    def __init__(self, security_manager: SecurityManagerV2 | None = None) -> None:
        """Initialise the security tool.

        Args:
            security_manager: The SecurityManagerV2 instance.
        """
        self._manager = security_manager

    def run(self, request: ToolRequest) -> ToolResult:
        """Execute a security management action.

        Args:
            request: The tool request with input_data containing action, etc.

        Returns:
            ToolResult with security information.
        """
        kwargs = request.input_data
        action = kwargs.get("action", "stats")

        if self._manager is None:
            return self.fail("Security manager not available.")

        try:
            if action == "check":
                return self._handle_check(kwargs)
            elif action == "approvals":
                return self._handle_approvals()
            elif action == "approve":
                return self._handle_approve(kwargs)
            elif action == "deny":
                return self._handle_deny(kwargs)
            elif action == "events":
                return self._handle_events(kwargs)
            elif action == "stats":
                return self._handle_stats()
            else:
                return self.fail(f"Unknown action: {action}. Supported: check, approvals, approve, deny, events, stats")
        except Exception as e:
            return self.fail(f"Error: {e}")

    def _handle_check(self, kwargs: dict) -> ToolResult:
        """Handle check action — test a string for injection."""
        text = kwargs.get("text", "")
        if not text:
            return self.fail("No text provided. Use 'text' parameter.")

        result = self._manager.check_input(text)

        lines = [
            "=== Injection Detection Result ===",
            f"  Is Injection: {result.is_injection}",
            f"  Confidence:   {result.confidence:.4f}",
            f"  Technique:    {result.technique}",
            f"  Patterns:     {', '.join(result.patterns) if result.patterns else 'none'}",
            f"  Details:      {result.details}",
        ]

        return self.ok("\n".join(lines))

    def _handle_approvals(self) -> ToolResult:
        """Handle approvals action — list pending approval requests."""
        pending = self._manager.get_pending_approvals()

        if not pending:
            return self.ok("No pending approval requests.")

        lines = ["=== Pending Approvals ===", ""]
        for req in pending:
            lines.append(f"  ID:      {req.request_id}")
            lines.append(f"  Action:  {req.action}")
            lines.append(f"  Tool:    {req.tool_name}")
            lines.append(f"  Level:   {req.level.value}")
            lines.append(f"  Created: {req.requested_at.isoformat()}")
            if req.expires_at:
                lines.append(f"  Expires: {req.expires_at.isoformat()}")
            lines.append("")

        return self.ok("\n".join(lines))

    def _handle_approve(self, kwargs: dict) -> ToolResult:
        """Handle approve action — approve a pending request."""
        request_id = kwargs.get("request_id", "")
        response = kwargs.get("response", None)

        if not request_id:
            return self.fail("No request_id provided.")

        success = self._manager.approve(request_id, response)
        if success:
            return self.ok(f"Request {request_id} approved.")
        else:
            return self.fail(f"Request {request_id} not found or not pending.")

    def _handle_deny(self, kwargs: dict) -> ToolResult:
        """Handle deny action — deny a pending request."""
        request_id = kwargs.get("request_id", "")
        reason = kwargs.get("reason", "Denied by user")

        if not request_id:
            return self.fail("No request_id provided.")

        success = self._manager.deny(request_id, reason)
        if success:
            return self.ok(f"Request {request_id} denied. Reason: {reason}")
        else:
            return self.fail(f"Request {request_id} not found or not pending.")

    def _handle_events(self, kwargs: dict) -> ToolResult:
        """Handle events action — show recent security events."""
        limit = kwargs.get("limit", 20)
        events = self._manager.get_security_events(limit=limit)

        if not events:
            return self.ok("No security events recorded.")

        lines = ["=== Security Events ===", ""]
        for event in events:
            lines.append(f"  [{event.level.value.upper()}] {event.action}")
            lines.append(f"    Tool: {event.tool_name}")
            lines.append(f"    Time: {event.timestamp.isoformat()}")
            lines.append(f"    Approved: {event.approved}")
            if event.details:
                lines.append(f"    Details: {event.details}")
            lines.append("")

        return self.ok("\n".join(lines))

    def _handle_stats(self) -> ToolResult:
        """Handle stats action — show injection detection statistics."""
        stats = self._manager.get_injection_stats()

        lines = [
            "=== Injection Detection Stats ===",
            f"  Total Detections: {stats['total_detections']}",
            "",
        ]

        if stats["by_pattern"]:
            lines.append("  By Pattern:")
            for pattern, count in sorted(stats["by_pattern"].items(), key=lambda x: -x[1]):
                lines.append(f"    {pattern}: {count}")
        else:
            lines.append("  No detections recorded.")

        lines.append("")
        return self.ok("\n".join(lines))
