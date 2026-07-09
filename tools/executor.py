"""
executor.py

Safe execution of tools for the Jarvis AI Operating System.

Responsibilities:
    - Look up a requested tool in the registry.
    - Classify the tool's action with the Security Manager BEFORE running it.
    - Run GREEN actions automatically.
    - Run YELLOW actions ONLY when an explicit approved ApprovalDecision is
      supplied; otherwise withhold them pending confirmation.
    - Block RED actions, even when an approval decision is supplied.
    - Log every execution attempt and its outcome through Observability.

Does NOT:
    - Decide security tiers itself (it delegates to the Security Manager).
    - Let an approval decision override a RED classification.
    - Connect to the Workflow Engine or the CLI.
    - Use the Claude API.

The executor is the single safety gate for tool use. The Security Manager
remains the source of truth for an action's risk: an approval decision only
permits a YELLOW action to proceed, and can never unblock a RED action. RED is
classified and blocked first, before any approval is even considered.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from approval.approval_models import ApprovalDecision
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
    classified by the Security Manager. GREEN actions run automatically. YELLOW
    actions run only when an explicit approved ApprovalDecision is supplied,
    and are otherwise withheld pending confirmation. RED actions are always
    blocked, and no approval can change that.

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
        approval_decision: ApprovalDecision | None = None,
    ) -> ToolResult:
        """Execute a tool by name, enforcing the security gate first.

        The tool's action is classified by the Security Manager before anything
        runs. RED actions are blocked regardless of any approval. GREEN actions
        run automatically. YELLOW actions run only when approval_decision is an
        approved decision; a missing or declined decision withholds the action.

        Args:
            tool_name: The registered name of the tool to run.
            input_data: Keyword inputs for the tool. Defaults to an empty dict.
            session_id: Optional session identifier for the audit trail.
            approval_decision: An optional decision authorising a YELLOW action.
                Only an approved decision permits a YELLOW action to run. This
                has no effect on GREEN (which always runs) or RED (which is
                always blocked).

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

        # RED is blocked first and unconditionally. An approval decision is
        # never even consulted for a RED action, so it cannot unblock one.
        if decision.tier is SecurityTier.RED:
            return self._handle_blocked(request, decision.reason)

        # YELLOW runs only with an explicit approved decision.
        if decision.tier is SecurityTier.YELLOW:
            if approval_decision is not None and approval_decision.is_approved:
                return self._handle_run(
                    tool, request, SecurityTier.YELLOW, approval_decision
                )
            return self._handle_needs_confirmation(
                request, decision.reason, approval_decision
            )

        # GREEN runs automatically.
        return self._handle_run(tool, request, SecurityTier.GREEN, None)

    def _handle_unknown(self, request: ToolRequest) -> ToolResult:
        """Handle a request for a tool that is not registered.

        Args:
            request: The originating request.

        Returns:
            A failed ToolResult describing the unknown tool.
        """
        message = f"No tool named '{request.tool_name}' is registered."
        self._emit_audit_event(
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
        self._emit_audit_event(
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
        self,
        request: ToolRequest,
        reason: str,
        approval_decision: ApprovalDecision | None,
    ) -> ToolResult:
        """Handle a YELLOW action that is not authorised to run.

        This is reached when no approval decision was supplied, or when the
        supplied decision was a decline. In both cases the action is withheld
        and not run.

        Args:
            request: The originating request.
            reason: The Security Manager's reason for requiring confirmation.
            approval_decision: The supplied decision, if any (a decline here).

        Returns:
            A ToolResult indicating confirmation is required.
        """
        declined = approval_decision is not None and approval_decision.is_declined
        detail = f"tool={request.tool_name} reason={reason}"
        if declined:
            detail += " decision=declined"

        self._emit_audit_event(
            outcome=EventOutcome.PENDING,
            detail=detail,
            security_tier=SecurityTier.YELLOW,
            session_id=request.session_id,
        )

        if declined:
            message = "This action was declined and will not run."
        else:
            message = f"Confirmation required before running this tool: {reason}"

        return ToolResult(
            tool_name=request.tool_name,
            success=False,
            error=message,
            requires_confirmation=True,
        )

    def _handle_run(
        self,
        tool: Any,
        request: ToolRequest,
        tier: SecurityTier,
        approval_decision: ApprovalDecision | None,
    ) -> ToolResult:
        """Run a tool and log the outcome.

        Any exception raised by the tool is caught and converted into a failed
        ToolResult so that a misbehaving tool cannot crash the caller. When the
        run was authorised by an approval decision, that decision's request_id
        is recorded in the result metadata if the result carries a metadata
        mapping.

        Args:
            tool: The tool to run.
            request: The originating request.
            tier: The classified tier of the action (GREEN or approved YELLOW).
            approval_decision: The approval that authorised a YELLOW run, if any.

        Returns:
            The tool's ToolResult, or a failed result if the tool raised.
        """
        start = time.monotonic()
        try:
            result = tool.run(request)
        except Exception as exc:  # noqa: BLE001 - isolate tool failures
            duration_ms = self._elapsed_ms(start)
            self._emit_audit_event(
                outcome=EventOutcome.FAILURE,
                detail=f"tool={request.tool_name} error={exc}",
                security_tier=tier,
                duration_ms=duration_ms,
                session_id=request.session_id,
            )
            return ToolResult(
                tool_name=request.tool_name,
                success=False,
                error=f"Tool raised an unexpected error: {exc}",
            )

        result = self._record_approval(result, approval_decision)

        duration_ms = self._elapsed_ms(start)
        outcome = EventOutcome.SUCCESS if result.success else EventOutcome.FAILURE
        detail = f"tool={request.tool_name} success={result.success}"
        if approval_decision is not None:
            detail += f" approved_by={approval_decision.decided_by}"
        self._emit_audit_event(
            outcome=outcome,
            detail=detail,
            security_tier=tier,
            duration_ms=duration_ms,
            session_id=request.session_id,
        )
        return result

    def _emit_audit_event(
        self,
        *,
        outcome: EventOutcome,
        detail: str,
        security_tier: SecurityTier | None = None,
        duration_ms: int | None = None,
        session_id: int | None,
    ) -> None:
        """Emit one tool_call audit event, isolating a failing logger so it
        can never alter the already-authoritative ToolResult about to be
        returned (Retrieval Workflow Maintenance-adjacent closure, Phase 15
        Batch 4A).

        Every one of ToolExecutor's five emit sites (unknown tool, RED
        blocked, YELLOW needs-confirmation, tool-raised failure, and the
        ordinary success/failure return) now calls this one helper instead
        of self._logger.emit() directly. The event name (action_type),
        outcome, detail, security_tier, duration_ms, and session_id passed
        in are byte-for-byte identical to what each call site already
        built before this change - only the emit() call itself is now
        wrapped, exactly matching the narrow, established observability-
        isolation pattern already used elsewhere in this codebase (e.g.
        core.orchestrator._emit_memory_acquisition_event,
        workflow.engine.WorkflowEngine._emit,
        approval.approval_manager.ApprovalManager._audit). No new event is
        created, renamed, or removed; no EventOutcome mapping changes; no
        detail content changes.

        The one and only behavioural change: a logger exception no longer
        escapes ToolExecutor.execute(). This does intentionally accept
        losing that one audit event when the logger genuinely fails - the
        standing invariant is that observability failure must never alter
        an authoritative execution outcome, not that logging can never
        fail. Nothing is retried, buffered, or written to a fallback
        destination.

        Args:
            outcome: The EventOutcome to record.
            detail: The already-built detail string.
            security_tier: The tier to record, if applicable.
            duration_ms: The duration to record, if applicable.
            session_id: Optional session identifier.
        """
        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                duration_ms=duration_ms,
                security_tier=security_tier,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative tool-execution outcome already decided.
            pass

    @staticmethod
    def _record_approval(
        result: ToolResult, approval_decision: ApprovalDecision | None
    ) -> ToolResult:
        """Return a result carrying the approval request_id in its metadata.

        When a decision authorised the run, a new result is returned whose
        metadata includes the approval's request_id (merged with any metadata
        the tool already set). The original result is not mutated, because
        ToolResult is immutable. When no decision was supplied, the result is
        returned unchanged.

        Args:
            result: The tool's result.
            approval_decision: The approval that authorised the run, if any.

        Returns:
            The result, with the approval request_id recorded in its metadata
            when a decision was supplied.
        """
        if approval_decision is None:
            return result

        merged = dict(result.metadata)
        merged["approval_request_id"] = approval_decision.request_id
        return replace(result, metadata=merged)

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        """Compute elapsed milliseconds since a monotonic start time.

        Args:
            start: The monotonic start time captured before the call.

        Returns:
            The elapsed time in whole milliseconds.
        """
        return int((time.monotonic() - start) * 1000)