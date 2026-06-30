"""
executor.py

Safe execution of tools for the Jarvis AI Operating System.

Responsibilities:
    - Look up a requested tool in the registry.
    - Classify the tool's action with the Security Manager BEFORE running it.
    - Run GREEN actions, withhold YELLOW actions pending confirmation, and
      block RED actions.
    - Log every execution attempt and its outcome through Observability.

Does NOT:
    - Decide security tiers itself (it delegates to the Security Manager).
    - Connect to the Workflow Engine.
    - Use the Claude API.

The executor is the single safety gate for tool use. No tool runs unless its
action has been classified GREEN. This is what keeps Phase 1 safe: the gate is
enforced here, in one place, for every tool.
"""

from __future__ import annotations

import time
from typing import Any

from config.constants import EventOutcome, SecurityTier
from observability.logger import EventLogger
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest, ToolResult
from tools.registry import ToolRegistry

_SOURCE = "tool_executor"
_ACTION_TYPE = "tool_call"


class ToolExecutor:
    """Executes tools through a mandatory security gate.

    Every execution flows through classify-then-run: the tool's action is
    classified by the Security Manager, and only GREEN actions proceed. YELLOW
    actions are withheld pending confirmation; RED actions are blocked.

    Attributes:
        _registry: The registry used to look up tools by name.
        _security: The Security Manager used to classify each action.
        _logger: The event logger used to record every execution attempt.
    """

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        security_manager: SecurityManager,
        logger: EventLogger,
    ) -> None:
        """Initialise the executor with its collaborators.

        Args:
            registry: The tool registry to resolve tool names against.
            security_manager: The Security Manager used to classify actions.
            logger: The event logger used to record execution attempts.
        """
        self._registry = registry
        self._security = security_manager
        self._logger = logger

    def execute(
        self,
        tool_name: str,
        input_data: dict[str, Any] | None = None,
        *,
        session_id: int | None = None,
    ) -> ToolResult:
        """Execute a tool by name, enforcing the security gate first.

        Args:
            tool_name: The registered name of the tool to run.
            input_data: Keyword inputs for the tool. Defaults to an empty dict.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A ToolResult describing the outcome. Unknown tools, blocked
            actions, and actions pending confirmation are all reported through
            the result rather than by raising.
        """
        request = ToolRequest(
            tool_name=tool_name,
            input_data=dict(input_data or {}),
            session_id=session_id,
        )

        tool = self._registry.get_tool(tool_name)
        if tool is None:
            return self._handle_unknown(request)

        decision = self._security.classify_action(tool.action_for(request))

        if decision.tier is SecurityTier.RED:
            return self._handle_blocked(request, decision.reason)

        if decision.tier is SecurityTier.YELLOW:
            return self._handle_needs_confirmation(request, decision.reason)

        return self._handle_run(tool, request)

    def _handle_unknown(self, request: ToolRequest) -> ToolResult:
        """Handle a request for a tool that is not registered.

        Args:
            request: The originating request.

        Returns:
            A failed ToolResult describing the unknown tool.
        """
        message = f"No tool named '{request.tool_name}' is registered."
        self._logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=EventOutcome.FAILURE,
            detail=f"unknown_tool={request.tool_name}",
            session_id=request.session_id,
        )
        return ToolResult(
            tool_name=request.tool_name,
            success=False,
            error=message,
        )

    def _handle_blocked(self, request: ToolRequest, reason: str) -> ToolResult:
        """Handle a RED action that must be blocked.

        Args:
            request: The originating request.
            reason: The Security Manager's reason for blocking.

        Returns:
            A blocked ToolResult.
        """
        self._logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=EventOutcome.BLOCKED,
            detail=f"tool={request.tool_name} reason={reason}",
            security_tier=SecurityTier.RED,
            session_id=request.session_id,
        )
        return ToolResult(
            tool_name=request.tool_name,
            success=False,
            error=f"Action blocked: {reason}",
            blocked=True,
        )

    def _handle_needs_confirmation(
        self, request: ToolRequest, reason: str
    ) -> ToolResult:
        """Handle a YELLOW action that requires user confirmation.

        Approval UI is not built in Phase 1, so the action is withheld and a
        result is returned indicating that confirmation is required.

        Args:
            request: The originating request.
            reason: The Security Manager's reason for requiring confirmation.

        Returns:
            A ToolResult indicating confirmation is required.
        """
        self._logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=EventOutcome.PENDING,
            detail=f"tool={request.tool_name} reason={reason}",
            security_tier=SecurityTier.YELLOW,
            session_id=request.session_id,
        )
        return ToolResult(
            tool_name=request.tool_name,
            success=False,
            error=f"Confirmation required before running this tool: {reason}",
            requires_confirmation=True,
        )

    def _handle_run(self, tool: Any, request: ToolRequest) -> ToolResult:
        """Run a GREEN tool and log the outcome.

        Any exception raised by the tool is caught and converted into a failed
        ToolResult so that a misbehaving tool cannot crash the caller.

        Args:
            tool: The tool to run.
            request: The originating request.

        Returns:
            The tool's ToolResult, or a failed result if the tool raised.
        """
        start = time.monotonic()
        try:
            result = tool.run(request)
        except Exception as exc:  # noqa: BLE001 - isolate tool failures
            duration_ms = self._elapsed_ms(start)
            self._logger.emit(
                source=_SOURCE,
                action_type=_ACTION_TYPE,
                outcome=EventOutcome.FAILURE,
                detail=f"tool={request.tool_name} error={exc}",
                security_tier=SecurityTier.GREEN,
                duration_ms=duration_ms,
                session_id=request.session_id,
            )
            return ToolResult(
                tool_name=request.tool_name,
                success=False,
                error=f"Tool raised an unexpected error: {exc}",
            )

        duration_ms = self._elapsed_ms(start)
        outcome = EventOutcome.SUCCESS if result.success else EventOutcome.FAILURE
        self._logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=outcome,
            detail=f"tool={request.tool_name} success={result.success}",
            security_tier=SecurityTier.GREEN,
            duration_ms=duration_ms,
            session_id=request.session_id,
        )
        return result

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        """Compute elapsed milliseconds since a monotonic start time.

        Args:
            start: The monotonic start time captured before the call.

        Returns:
            The elapsed time in whole milliseconds.
        """
        return int((time.monotonic() - start) * 1000)