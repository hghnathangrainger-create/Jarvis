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

from config.constants import SecurityTier
from core.request_models import JarvisRequest, JarvisResponse
from planner.plan_models import Plan
from planner.planner import Planner
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry

# Recognised intents map to a built-in tool and the input that tool expects.
# Only safe, read-only tools are wired here in Phase 1.
_ECHO_KEYWORDS: tuple[str, ...] = ("echo", "repeat", "say")
_INFO_KEYWORDS: tuple[str, ...] = ("system info", "version", "about", "who are you")
_MEMORY_KEYWORDS: tuple[str, ...] = ("memory", "memories", "remember", "recall")
_SEARCH_KEYWORDS: tuple[str, ...] = ("search", "find", "look up", "lookup")


class JarvisOrchestrator:
    """Coordinates the Phase 1 subsystems to handle a user request.

    The orchestrator plans the request, enforces the plan's security outcome,
    and routes recognised safe requests to a tool through the ToolExecutor.

    Attributes:
        _planner: Produces a Plan from the request.
        _executor: Runs tools behind the security gate.
        _registry: Used to check which tools are available.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        executor: ToolExecutor,
        registry: ToolRegistry,
    ) -> None:
        """Initialise the orchestrator with its collaborators.

        Args:
            planner: The Planner used to plan requests.
            executor: The ToolExecutor used to run tools safely.
            registry: The ToolRegistry used to check tool availability.
        """
        self._planner = planner
        self._executor = executor
        self._registry = registry

    def handle_request(
        self, user_request: str, *, session_id: int | None = None
    ) -> JarvisResponse:
        """Handle a user request and return a structured response.

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
        tool_name = self._match_tool(text)
        if tool_name is not None:
            tool_input = self._build_tool_input(tool_name, text)
            result = self._executor.execute(
                tool_name, tool_input, session_id=request.session_id
            )
            return self._tool_response(plan, result)

        # No tool matched. Fall back to the plan's own classification so the
        # request is still handled safely: blocked if RED, withheld if YELLOW,
        # otherwise reported as a safe-but-unsupported request.
        if plan.has_blocked_steps:
            return self._blocked_response(plan)

        if plan.requires_confirmation:
            return self._confirmation_response(plan)

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

    def _confirmation_response(self, plan: Plan) -> JarvisResponse:
        """Build a response for a plan that requires user confirmation.

        Args:
            plan: The plan that requires confirmation.

        Returns:
            A JarvisResponse indicating confirmation is required, with the plan.
        """
        step = next(step for step in plan.steps if step.requires_confirmation)
        return JarvisResponse(
            success=False,
            message=(
                "This request needs your confirmation before Jarvis can "
                f"proceed: {step.reason}"
            ),
            plan=plan,
            requires_confirmation=True,
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

    def _tool_response(self, plan: Plan, result: ToolResult) -> JarvisResponse:
        """Build a response from a tool execution result.

        The ToolExecutor enforces the security gate, so even a GREEN-planned
        request may still come back needing confirmation or blocked if the
        tool's own action classifies higher. Those outcomes are reflected here.

        Args:
            plan: The plan that led to this execution.
            result: The result returned by the ToolExecutor.

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
            return JarvisResponse(
                success=False,
                message=result.error or "This action requires your confirmation.",
                plan=plan,
                tool_result=result,
                requires_confirmation=True,
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

    # ----- intent matching ---------------------------------------------------

    def _match_tool(self, text: str) -> str | None:
        """Map a request to a known safe tool name, if one applies.

        Only tools that are actually registered are returned, so the
        orchestrator never routes to a tool that is not available.

        Args:
            text: The stripped request text.

        Returns:
            The name of a registered tool to handle the request, or None.
        """
        lowered = text.casefold()

        if self._contains(lowered, _MEMORY_KEYWORDS) and self._registry.has_tool(
            "memory"
        ):
            return "memory"

        if self._contains(lowered, _INFO_KEYWORDS) and self._registry.has_tool("info"):
            return "info"

        if self._contains(lowered, _ECHO_KEYWORDS) and self._registry.has_tool("echo"):
            return "echo"

        return None

    def _build_tool_input(self, tool_name: str, text: str) -> dict[str, object]:
        """Build the input dictionary for the matched tool.

        Args:
            tool_name: The name of the tool that will run.
            text: The stripped request text.

        Returns:
            The input dictionary the tool expects.
        """
        if tool_name == "memory":
            lowered = text.casefold()
            if self._contains(lowered, _SEARCH_KEYWORDS):
                return {"operation": "search", "query": text}
            return {"operation": "list"}

        if tool_name == "echo":
            return {"text": text}

        # info takes no input
        return {}

    @staticmethod
    def _contains(text: str, keywords: tuple[str, ...]) -> bool:
        """Report whether any keyword appears in the text.

        Args:
            text: The already-lowercased text to search.
            keywords: The keywords to look for.

        Returns:
            True if any keyword is present, False otherwise.
        """
        return any(keyword in text for keyword in keywords)