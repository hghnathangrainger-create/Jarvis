"""
request_models.py

Request and response data structures for the Jarvis Core.

Responsibilities:
    - Define JarvisRequest: the input passed into the orchestrator.
    - Define JarvisResponse: the structured result the orchestrator returns.

Does NOT:
    - Implement orchestration logic (see orchestrator.py).
    - Execute tools, plan, or classify security.

These models are pure data. They give the Core a stable, typed contract for
what goes in and what comes out, independent of how a request is handled.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from approval.approval_models import ApprovalRequest
from planner.plan_models import Plan
from tools.base_tool import ToolResult


@dataclass(frozen=True, slots=True)
class JarvisRequest:
    """A single request submitted to the Jarvis Core.

    Attributes:
        user_input: The user's request in natural language.
        session_id: Optional session identifier for the audit trail.
    """

    user_input: str
    session_id: int | None = None


@dataclass(frozen=True, slots=True)
class JarvisResponse:
    """The structured result of handling a request.

    A response is always returned; problems are reported through these fields
    rather than by raising, so callers can handle every outcome uniformly.

    Attributes:
        success: True if the request was handled and produced a usable result.
        message: A human-readable summary of what happened.
        plan: The plan generated for the request, if one was generated.
        tool_result: The result of any tool that was executed, if any.
        requires_confirmation: True when the request was withheld because it
            needs user confirmation (a YELLOW action).
        blocked: True when the request was blocked outright (a RED action).
        approval_request: The pending approval request created for a YELLOW
            action, if any. Present only when requires_confirmation is True and
            the action was routed into the approval flow.
        tool_name: The name of the tool that should run once the action is
            approved, if this request is a tool-backed YELLOW action. Empty for
            GREEN, RED, and plan-only (non-tool) responses.
        tool_input: The input the tool should run with once approved. Empty
            unless tool_name is set.
        ai_suggestion: An optional, advisory AI reasoning summary attached to
            the response. Present only when AI reasoning is enabled and produced
            a result. It is informational only: it never affects routing,
            classification, approval, or execution, all of which are decided by
            the Planner, SecurityManager, ToolExecutor, and ApprovalManager.
    """

    success: bool
    message: str
    plan: Plan | None = None
    tool_result: ToolResult | None = None
    requires_confirmation: bool = False
    blocked: bool = False
    approval_request: ApprovalRequest | None = None
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    ai_suggestion: str | None = None