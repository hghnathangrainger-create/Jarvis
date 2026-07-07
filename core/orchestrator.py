"""
orchestrator.py

The Jarvis Core orchestrator for Phase 1.

Responsibilities:
    - Receive a user request and produce a structured JarvisResponse.
    - Use the Planner to turn the request into a Plan.
    - Inspect the Plan for blocked (RED) and confirmation (YELLOW) steps.
    - For safe, recognised requests, route to the correct built-in tool through
      the ToolExecutor, which enforces the security gate.
    - Always include the generated Plan in the response.

Does NOT:
    - Call the Claude API or any AI provider.
    - Execute anything directly; all tool execution goes through ToolExecutor.
    - Bypass the security gate under any circumstance.
    - Implement autonomous behaviour, voice, phone, or UI.

The orchestrator coordinates existing subsystems; it owns no planning,
security, or execution logic of its own. Every consequential action flows
through the components that already enforce safety, so the Core cannot become
a way around them.
"""

from __future__ import annotations

from dataclasses import replace

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalDecision
from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import AIReasoningRequest
from config.constants import SecurityTier
from core.command_router import CommandRouter
from core.request_models import JarvisRequest, JarvisResponse
from planner.plan_models import Plan
from planner.planner import Planner
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class JarvisOrchestrator:
    """Coordinates the Phase 1 subsystems to handle a user request.

    The orchestrator plans the request, enforces the plan's security outcome,
    and routes recognised safe requests to a tool through the ToolExecutor.

    Attributes:
        _planner: Produces a Plan from the request.
        _executor: Runs tools behind the security gate.
        _registry: Used to check which tools are available.
        _command_router: Matches request text to a registered tool and builds
            its input (Phase 7, Batch 1 - extracted from this class so the
            Core coordinates rather than performing command-matching itself).
        _approvals: Creates and holds pending approval requests for YELLOW
            actions.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        executor: ToolExecutor,
        registry: ToolRegistry,
        command_router: CommandRouter,
        approval_manager: ApprovalManager | None = None,
        reasoning_engine: AIReasoningEngine | None = None,
    ) -> None:
        """Initialise the orchestrator with its collaborators.

        Args:
            planner: The Planner used to plan requests.
            executor: The ToolExecutor used to run tools safely.
            registry: The ToolRegistry used to check tool availability.
            command_router: The CommandRouter used to match request text to a
                registered tool and build its input.
            approval_manager: The ApprovalManager used to create approval
                requests for YELLOW actions. A new one is created if omitted.
            reasoning_engine: An optional advisory AI reasoning engine. When
                omitted or inactive, behaviour is exactly as before: no AI is
                consulted and responses are unchanged. When active, an advisory
                suggestion is attached to the response, but it never affects
                routing, classification, approval, or execution.
        """
        self._planner = planner
        self._executor = executor
        self._registry = registry
        self._command_router = command_router
        self._approvals = approval_manager or ApprovalManager()
        self._reasoning = reasoning_engine

    @property
    def approvals(self) -> ApprovalManager:
        """Return the approval manager this orchestrator uses.

        Exposed so that a later step (CLI or approval flow) can retrieve and
        act on the pending requests this orchestrator creates.

        Returns:
            The ApprovalManager instance.
        """
        return self._approvals

    def execute_approved(
        self, response: JarvisResponse, decision: ApprovalDecision
    ) -> JarvisResponse:
        """Run a previously-approved tool action through the security gate.

        This is used after the user approves a YELLOW action in the CLI. It
        re-runs the exact tool and input carried on the original response,
        passing the approval decision to the ToolExecutor. The executor still
        classifies the action, so a RED action can never be run this way even
        if a decision is supplied.

        Args:
            response: The original response that carried the approval request,
                including the tool name and input to run.
            decision: The approval decision authorising the run. Must be
                approved for anything to execute.

        Returns:
            A JarvisResponse describing the executed result. If the response
            has no tool to run, or the decision is not approved, a response is
            returned that explains that nothing was executed.
        """
        if not decision.is_approved:
            return JarvisResponse(
                success=False,
                message="The action was declined and was not run.",
                plan=response.plan,
            )

        if not response.tool_name:
            # A plan-only YELLOW action with no backing tool: there is nothing
            # to execute. The approval is still recorded by the caller.
            return JarvisResponse(
                success=True,
                message="Approved. There is no runnable tool for this action yet.",
                plan=response.plan,
            )

        result = self._executor.execute(
            response.tool_name,
            response.tool_input,
            session_id=(
                response.approval_request.session_id
                if response.approval_request is not None
                else None
            ),
            approval_decision=decision,
        )
        return self._tool_result_to_response(response.plan, result)

    @staticmethod
    def _tool_result_to_response(
        plan: Plan | None, result: ToolResult
    ) -> JarvisResponse:
        """Convert a post-approval tool result into a response.

        Args:
            plan: The plan from the original request, carried through.
            result: The result of running the approved tool.

        Returns:
            A JarvisResponse reflecting the executed result.
        """
        if result.blocked:
            return JarvisResponse(
                success=False,
                message=result.error or "The action was blocked for safety.",
                plan=plan,
                tool_result=result,
                blocked=True,
            )
        if not result.success:
            return JarvisResponse(
                success=False,
                message=result.error or "The tool could not complete the request.",
                plan=plan,
                tool_result=result,
            )
        return JarvisResponse(
            success=True,
            message=result.output,
            plan=plan,
            tool_result=result,
        )

    def handle_request(
        self, user_request: str, *, session_id: int | None = None
    ) -> JarvisResponse:
        """Handle a user request and return a structured response.

        This is a thin wrapper around the rule-based request handler. The
        response is produced entirely by the existing Planner, SecurityManager,
        ToolExecutor, and ApprovalManager path. Only after that authoritative
        response is built is an *advisory* AI suggestion optionally attached,
        and only when a reasoning engine is active. The AI never changes the
        outcome: routing, classification, approval, and execution are all
        already decided before the AI is consulted.

        Args:
            user_request: The user's request in natural language.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse describing the outcome, with an advisory
            ai_suggestion attached only when AI reasoning is active.
        """
        response = self._handle_request_core(user_request, session_id=session_id)
        return self._attach_ai_suggestion(response, user_request, session_id)

    def _attach_ai_suggestion(
        self,
        response: JarvisResponse,
        user_request: str,
        session_id: int | None,
    ) -> JarvisResponse:
        """Attach an advisory AI suggestion to an already-decided response.

        The AI reasoning engine, if active, is consulted purely for advice. Its
        result is placed in the response's ai_suggestion field and nowhere else.
        It cannot execute anything, and it cannot change the response's success,
        blocked, requires_confirmation, plan, or tool fields. If the engine is
        inactive or returns nothing, the response is returned unchanged.

        Args:
            response: The authoritative response already produced by the
                rule-based path.
            user_request: The original user request text.
            session_id: Optional session identifier.

        Returns:
            The response, possibly with an advisory ai_suggestion attached.
        """
        if self._reasoning is None:
            return response

        reasoning_request = AIReasoningRequest(
            user_input=user_request, session_id=session_id
        )
        result = self._reasoning.reason(reasoning_request)
        if result is None:
            return response

        # Build a short, clearly-advisory suggestion string. This is the ONLY
        # field the AI can influence; every safety-relevant field is untouched.
        suggestion = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            suggestion = f"{result.summary} Suggested steps: {steps}"

        # JarvisResponse is frozen, so return a copy with only ai_suggestion
        # changed. Every other field is preserved exactly as decided.
        return replace(
            response,
            ai_suggestion=f"[AI suggestion - advisory only] {suggestion}",
        )

    def _handle_request_core(
        self, user_request: str, *, session_id: int | None = None
    ) -> JarvisResponse:
        """Handle a user request using the rule-based path only.

        A plan is generated first and is always included in the response. If
        the request maps to a known safe tool, that tool is run through the
        ToolExecutor, which classifies the tool's own action and enforces the
        security gate (blocking RED, withholding YELLOW). If no tool matches,
        the plan's own classification is used: blocked requests return a
        blocked response, requests needing confirmation return a confirmation
        response, and otherwise a safe-but-unsupported response is returned.

        Args:
            user_request: The user's request in natural language.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse describing the outcome. Empty input is reported as
            a failed response rather than raising.
        """
        request = JarvisRequest(user_input=user_request, session_id=session_id)

        text = request.user_input.strip()
        if not text:
            return JarvisResponse(
                success=False,
                message="Empty request. Please say what you would like Jarvis to do.",
            )

        # The plan is always generated for transparency and is always returned.
        plan = self._planner.create_plan(text)

        # Routing decision: if the request maps to a known safe tool, run it
        # through the ToolExecutor. The executor classifies the TOOL'S action
        # (not the raw sentence) and enforces the security gate, so this is the
        # authoritative safety check for tool-backed requests.
        tool_name = self._command_router.match(text)
        if tool_name is not None:
            tool_input = self._command_router.build_input(tool_name, text)
            result = self._executor.execute(
                tool_name, tool_input, session_id=request.session_id
            )
            return self._tool_response(
                plan, result, text, request.session_id, tool_name, tool_input
            )

        # No tool matched. Fall back to the plan's own classification so the
        # request is still handled safely: blocked if RED, withheld if YELLOW,
        # otherwise reported as a safe-but-unsupported request.
        if plan.has_blocked_steps:
            return self._blocked_response(plan)

        if plan.requires_confirmation:
            return self._confirmation_response(plan, text, request.session_id)

        return self._unrecognised_green_response(plan)

    # ----- response builders -------------------------------------------------

    def _blocked_response(self, plan: Plan) -> JarvisResponse:
        """Build a response for a plan containing a blocked (RED) step.

        Args:
            plan: The plan that contains a blocked step.

        Returns:
            A blocked JarvisResponse including the plan.
        """
        blocked = next(step for step in plan.steps if step.is_blocked)
        return JarvisResponse(
            success=False,
            message=f"This request is blocked for safety: {blocked.reason}",
            plan=plan,
            blocked=True,
        )

    def _confirmation_response(
        self, plan: Plan, action: str, session_id: int | None
    ) -> JarvisResponse:
        """Build a response for a plan that requires user confirmation.

        A pending approval request is created for the YELLOW action via the
        ApprovalManager and returned in the response. The action is not
        executed in this step; it simply becomes pending.

        Args:
            plan: The plan that requires confirmation.
            action: The request text to record as the action needing approval.
            session_id: Optional session identifier for the request.

        Returns:
            A JarvisResponse indicating confirmation is required, including the
            plan and the pending approval request.
        """
        step = next(step for step in plan.steps if step.requires_confirmation)
        approval = self._approvals.create_request(
            action=action,
            reason=step.reason,
            security_tier=SecurityTier.YELLOW,
            session_id=session_id,
        )
        return JarvisResponse(
            success=False,
            message=(
                "This request needs your confirmation before Jarvis can "
                f"proceed: {step.reason}"
            ),
            plan=plan,
            requires_confirmation=True,
            approval_request=approval,
        )

    def _unrecognised_green_response(self, plan: Plan) -> JarvisResponse:
        """Build a response for a safe request with no matching tool.

        The request was classified safe, but Jarvis has no Phase 1 capability
        to fulfil it. The plan is returned so the user can see what Jarvis
        understood.

        Args:
            plan: The (safe) plan that has no matching tool.

        Returns:
            A JarvisResponse explaining the missing capability, with the plan.
        """
        return JarvisResponse(
            success=False,
            message=(
                "Jarvis can plan this request, but does not yet have a tool to "
                "carry it out. More capability will be added in a later phase."
            ),
            plan=plan,
        )

    def _tool_response(
        self,
        plan: Plan,
        result: ToolResult,
        action: str,
        session_id: int | None,
        tool_name: str,
        tool_input: dict[str, object],
    ) -> JarvisResponse:
        """Build a response from a tool execution result.

        The ToolExecutor enforces the security gate, so even a GREEN-planned
        request may still come back needing confirmation or blocked if the
        tool's own action classifies higher. Those outcomes are reflected here.
        When the tool needs confirmation (YELLOW), a pending approval request
        is created and returned, along with the tool name and input needed to
        run it once approved; the action is not executed in this step.

        Args:
            plan: The plan that led to this execution.
            result: The result returned by the ToolExecutor.
            action: The request text to record as the action needing approval.
            session_id: Optional session identifier for the approval request.
            tool_name: The tool that was attempted, carried so an approved
                action can be re-run through the executor.
            tool_input: The input the tool was attempted with.

        Returns:
            A JarvisResponse reflecting the tool result, with the plan.
        """
        if result.blocked:
            return JarvisResponse(
                success=False,
                message=result.error or "The action was blocked for safety.",
                plan=plan,
                tool_result=result,
                blocked=True,
            )

        if result.requires_confirmation:
            approval = self._approvals.create_request(
                action=action,
                reason=result.error or "This action requires your confirmation.",
                security_tier=SecurityTier.YELLOW,
                session_id=session_id,
            )
            return JarvisResponse(
                success=False,
                message=result.error or "This action requires your confirmation.",
                plan=plan,
                tool_result=result,
                requires_confirmation=True,
                approval_request=approval,
                tool_name=tool_name,
                tool_input=dict(tool_input),
            )

        if not result.success:
            return JarvisResponse(
                success=False,
                message=result.error or "The tool could not complete the request.",
                plan=plan,
                tool_result=result,
            )

        return JarvisResponse(
            success=True,
            message=result.output,
            plan=plan,
            tool_result=result,
        )
