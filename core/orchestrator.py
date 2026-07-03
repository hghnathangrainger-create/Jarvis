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

#: Leading phrases that indicate a file-listing request. The text after the
#: phrase is treated as the directory path.
_FILE_LIST_PREFIXES: tuple[str, ...] = (
    "list files in",
    "show files in",
    "list files",
    "show files",
    "list directory",
    "list dir",
)

#: Leading phrases that indicate a file-reading request. The text after the
#: phrase is treated as the file path. All of these are read-only; "open" here
#: means "open to read", never to modify.
_FILE_READ_PREFIXES: tuple[str, ...] = (
    "read file",
    "show file",
    "open file",
    "read the file",
    "cat file",
)

#: Practical read-only workflow aliases. Each maps an exact phrase (matched
#: case-insensitively, after stripping surrounding whitespace) to a fixed tool
#: and path, so a beginner can use a friendly command instead of typing a path.
#: Every alias here is read-only: it routes only to file_list or file_read.
_WORKFLOW_ALIASES: dict[str, tuple[str, str]] = {
    "show project files": ("file_list", "."),
    "list project files": ("file_list", "."),
    "show docs": ("file_list", "docs"),
    "list docs": ("file_list", "docs"),
    "read readme": ("file_read", "README.md"),
    "show readme": ("file_read", "README.md"),
    "show phase 3 plan": ("file_read", "docs/phase_3_implementation_plan.md"),
    "read phase 3 plan": ("file_read", "docs/phase_3_implementation_plan.md"),
}

#: Leading phrases that indicate a create-file request. The text after the
#: phrase is the path, optionally followed by " with <content>". Creating a
#: file is a WRITE action (YELLOW) and always requires approval.
_FILE_CREATE_PREFIXES: tuple[str, ...] = (
    "create text file",
    "create file",
    "create a file",
    "new file",
    "make file",
)

#: Leading phrases that indicate an append-file request. Appending is a WRITE
#: action (YELLOW) and always requires approval. Two shapes are supported:
#:   "append <content> to file <path>"
#:   "append to file <path> <content>"
_FILE_APPEND_PREFIXES: tuple[str, ...] = (
    "append text file",
    "append to file",
    "append to",
    "append",
)
_SEARCH_KEYWORDS: tuple[str, ...] = ("search", "find", "look up", "lookup")


class JarvisOrchestrator:
    """Coordinates the Phase 1 subsystems to handle a user request.

    The orchestrator plans the request, enforces the plan's security outcome,
    and routes recognised safe requests to a tool through the ToolExecutor.

    Attributes:
        _planner: Produces a Plan from the request.
        _executor: Runs tools behind the security gate.
        _registry: Used to check which tools are available.
        _approvals: Creates and holds pending approval requests for YELLOW
            actions.
    """

    def __init__(
        self,
        *,
        planner: Planner,
        executor: ToolExecutor,
        registry: ToolRegistry,
        approval_manager: ApprovalManager | None = None,
        reasoning_engine: AIReasoningEngine | None = None,
    ) -> None:
        """Initialise the orchestrator with its collaborators.

        Args:
            planner: The Planner used to plan requests.
            executor: The ToolExecutor used to run tools safely.
            registry: The ToolRegistry used to check tool availability.
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
        tool_name = self._match_tool(text)
        if tool_name is not None:
            tool_input = self._build_tool_input(tool_name, text)
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

        # Practical workflow aliases are checked first: an exact friendly phrase
        # maps to a fixed read-only tool. Only route if that tool is registered.
        alias = _WORKFLOW_ALIASES.get(lowered.strip())
        if alias is not None and self._registry.has_tool(alias[0]):
            return alias[0]

        # File commands are checked next because their phrasing is specific.
        # Only route to a file tool if it is actually registered.
        if self._file_prefix(lowered, _FILE_LIST_PREFIXES) is not None and (
            self._registry.has_tool("file_list")
        ):
            return "file_list"

        if self._file_prefix(lowered, _FILE_READ_PREFIXES) is not None and (
            self._registry.has_tool("file_read")
        ):
            return "file_read"

        # Write commands (create, append) are YELLOW and require approval. They
        # are matched here but the safety gate is enforced by the Tool Executor,
        # exactly as for any other YELLOW action.
        if self._file_prefix(lowered, _FILE_CREATE_PREFIXES) is not None and (
            self._registry.has_tool("file_create")
        ):
            return "file_create"

        if self._file_prefix(lowered, _FILE_APPEND_PREFIXES) is not None and (
            self._registry.has_tool("file_append")
        ):
            return "file_append"

        # Bulk forget is dangerous (RED). Route it to the forget tool so its
        # action string ("forget all memories") is classified RED by the
        # Security Manager and blocked by the Tool Executor - never to the
        # read-only memory tool, which would misclassify it as a safe list.
        if lowered.startswith("forget all") and self._registry.has_tool(
            "memory_forget"
        ):
            return "memory_forget"

        # Memory change commands (update, move, forget) are YELLOW and must be
        # matched before the generic read-only memory tool. The safety gate is
        # still enforced by the Tool Executor; this only selects the tool.
        if lowered.startswith("forget memory") and self._registry.has_tool(
            "memory_forget"
        ):
            return "memory_forget"

        if (
            lowered.startswith("update memory") or lowered.startswith("move memory")
        ) and self._registry.has_tool("memory_update"):
            return "memory_update"

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
            return self._build_memory_input(text)

        if tool_name == "memory_update":
            return self._build_memory_update_input(text)

        if tool_name == "memory_forget":
            if text.strip().casefold().startswith("forget all"):
                # Bulk forget: no id. The tool's action classifies RED and the
                # executor blocks it; nothing is ever forgotten in bulk.
                return {"all": True}
            return {"memory_id": self._extract_memory_id(text, "forget memory")}

        if tool_name == "echo":
            return {"text": text}

        if tool_name == "file_list":
            alias = _WORKFLOW_ALIASES.get(text.casefold().strip())
            if alias is not None:
                return {"path": alias[1]}
            path = self._extract_path(text, _FILE_LIST_PREFIXES)
            # Default to the current directory when no path is given.
            return {"path": path or "."}

        if tool_name == "file_read":
            alias = _WORKFLOW_ALIASES.get(text.casefold().strip())
            if alias is not None:
                return {"path": alias[1]}
            path = self._extract_path(text, _FILE_READ_PREFIXES)
            return {"path": path}

        if tool_name == "file_create":
            path, content = self._extract_create_input(text)
            return {"path": path, "content": content}

        if tool_name == "file_append":
            path, content = self._extract_append_input(text)
            return {"path": path, "content": content}

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

    @staticmethod
    def _file_prefix(lowered: str, prefixes: tuple[str, ...]) -> str | None:
        """Return the first file-command prefix the text starts with.

        Prefixes are checked longest-first so that a more specific phrase (for
        example "list files in") is preferred over a shorter one ("list files").

        Args:
            lowered: The already-lowercased request text.
            prefixes: The candidate prefixes to check.

        Returns:
            The matching prefix, or None if the text starts with none of them.
        """
        for prefix in sorted(prefixes, key=len, reverse=True):
            if lowered.startswith(prefix):
                return prefix
        return None

    @classmethod
    def _extract_path(cls, text: str, prefixes: tuple[str, ...]) -> str:
        """Extract the path portion of a file command.

        The matching prefix is removed from the start of the request, and the
        remainder is treated as the path. A leading filler word ("the") and
        surrounding quotes or whitespace are stripped.

        Args:
            text: The original (unlowered) request text.
            prefixes: The prefixes for this file command.

        Returns:
            The extracted path, or an empty string if none was given.
        """
        prefix = cls._file_prefix(text.casefold(), prefixes)
        if prefix is None:
            return ""

        remainder = text[len(prefix) :].strip()
        # Drop a leading filler word such as "the" ("read the file the notes").
        if remainder.casefold().startswith("the "):
            remainder = remainder[4:].strip()
        # Strip surrounding quotes if the user quoted the path.
        return remainder.strip("'\"").strip()

    @classmethod
    def _extract_create_input(cls, text: str) -> tuple[str, str]:
        """Extract (path, content) from a create-file command.

        The recognised shape is: "<create-prefix> <path> with <content>". The
        "with <content>" part is optional; when absent, the content is empty and
        an empty file is created.

        Args:
            text: The original request text.

        Returns:
            A tuple of (path, content). Either may be empty, in which case the
            tool itself reports the problem (empty path is rejected).
        """
        remainder = cls._strip_write_prefix(text, _FILE_CREATE_PREFIXES)
        path_part, content = cls._split_on_keyword(remainder, " with ")
        return cls._clean_path(path_part), content

    @classmethod
    def _extract_append_input(cls, text: str) -> tuple[str, str]:
        """Extract (path, content) from an append-file command.

        Two shapes are recognised:
            "append <content> to file <path>"
            "append to file <path> <content>"
        The first shape is preferred: if the phrase contains " to file " or
        " to ", the text before it is the content and the text after it is the
        path.

        Args:
            text: The original request text.

        Returns:
            A tuple of (path, content). Either may be empty, in which case the
            tool itself reports the problem.
        """
        remainder = cls._strip_write_prefix(text, _FILE_APPEND_PREFIXES)

        for separator in (" to file ", " to "):
            if separator in remainder.casefold():
                idx = remainder.casefold().index(separator)
                content = remainder[:idx].strip()
                path_part = remainder[idx + len(separator) :].strip()
                return cls._clean_path(path_part), cls._clean_content(content)

        # No separator: treat the whole remainder as the path, no content. The
        # append tool will then reject the empty content, which is correct.
        return cls._clean_path(remainder), ""

    @classmethod
    def _strip_write_prefix(cls, text: str, prefixes: tuple[str, ...]) -> str:
        """Remove the matching write-command prefix from the text.

        Args:
            text: The original request text.
            prefixes: The write-command prefixes to check.

        Returns:
            The text after the prefix, stripped, or the original text if no
            prefix matched.
        """
        prefix = cls._file_prefix(text.casefold(), prefixes)
        if prefix is None:
            return text.strip()
        return text[len(prefix) :].strip()

    @staticmethod
    def _split_on_keyword(text: str, keyword: str) -> tuple[str, str]:
        """Split text once on a keyword, case-insensitively.

        Args:
            text: The text to split.
            keyword: The separator to split on (for example, " with ").

        Returns:
            A tuple of (before, after). If the keyword is absent, after is
            empty and before is the whole text.
        """
        lowered = text.casefold()
        if keyword in lowered:
            idx = lowered.index(keyword)
            return text[:idx].strip(), text[idx + len(keyword) :].strip()
        return text.strip(), ""

    @staticmethod
    def _clean_path(path_part: str) -> str:
        """Clean an extracted path fragment.

        Args:
            path_part: The raw path fragment.

        Returns:
            The path with a leading "the ", surrounding quotes, and whitespace
            removed.
        """
        cleaned = path_part.strip()
        if cleaned.casefold().startswith("the "):
            cleaned = cleaned[4:].strip()
        return cleaned.strip("'\"").strip()

    @staticmethod
    def _clean_content(content: str) -> str:
        """Clean an extracted content fragment.

        Args:
            content: The raw content fragment.

        Returns:
            The content with surrounding quotes and whitespace removed.
        """
        return content.strip().strip("'\"")

    @classmethod
    def _build_memory_input(cls, text: str) -> dict[str, object]:
        """Parse a memory command into a memory-tool input dictionary.

        Six command shapes are recognised (case-insensitively):
            remember this: <text>                     -> save (general)
            remember this as <category>: <text>       -> save (<category>)
            show memories                             -> list
            show memories in <category>               -> list (<category>)
            search memories for <query>               -> search
            search memories in <category> for <query> -> search (<category>)

        Anything unrecognised falls back to a plain list, so the command is
        always safe and read-only by default.

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the memory tool.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        # --- Show one by id: "show memory <id>" ---
        if lowered.startswith("show memory") or lowered.startswith("view memory"):
            memory_id = cls._extract_trailing_id(stripped)
            if memory_id is not None:
                return {"operation": "get", "memory_id": memory_id}
            # "show memories" (no id) falls through to the list handling below.

        # --- Save: "remember this[ as <category>]: <content>" ---
        if lowered.startswith("remember this"):
            after = stripped[len("remember this"):]
            category: str | None = None
            # Optional "as <category>" before the colon.
            if after.casefold().lstrip().startswith("as "):
                as_part = after.lstrip()[3:]
                if ":" in as_part:
                    cat_text, content = as_part.split(":", 1)
                    category = cat_text.strip()
                    return {
                        "operation": "save",
                        "content": content.strip(),
                        "category": category,
                    }
            # Plain "remember this: <content>".
            if ":" in after:
                _, content = after.split(":", 1)
                return {"operation": "save", "content": content.strip()}
            # "remember this <content>" with no colon: treat the rest as content.
            return {"operation": "save", "content": after.strip()}

        # --- Search: "search memories [in <category>] for <query>" ---
        if "search" in lowered and (
            "memor" in lowered
        ):
            category = cls._extract_between(lowered, stripped, " in ", " for ")
            query = cls._extract_after(stripped, " for ")
            result: dict[str, object] = {"operation": "search"}
            if query:
                result["query"] = query
            if category:
                result["category"] = category
            return result

        # --- List: "show memories [in <category>]" ---
        if ("show" in lowered or "list" in lowered) and "memor" in lowered:
            category = cls._extract_after(stripped, " in ")
            result = {"operation": "list"}
            if category:
                result["category"] = category
            return result

        # Fallback: safe read-only list.
        return {"operation": "list"}

    @staticmethod
    def _extract_after(text: str, marker: str) -> str:
        """Return the text after a marker phrase, cleaned. Empty if absent.

        Args:
            text: The original text.
            marker: The marker phrase to search for (case-insensitive).

        Returns:
            The trimmed, unquoted text after the marker, or "" if not present.
        """
        lowered = text.casefold()
        idx = lowered.find(marker)
        if idx == -1:
            return ""
        return text[idx + len(marker):].strip().strip("'\"")

    @staticmethod
    def _extract_between(text: str, lowered: str, start: str, end: str) -> str:
        """Return the text between two markers, cleaned. Empty if absent.

        Args:
            text: The original text.
            lowered: The lower-cased original text (for index finding).
            start: The starting marker phrase.
            end: The ending marker phrase.

        Returns:
            The trimmed text between the markers, or "" if the pair is absent.
        """
        start_idx = lowered.find(start)
        if start_idx == -1:
            return ""
        after_start = start_idx + len(start)
        end_idx = lowered.find(end, after_start)
        if end_idx == -1:
            return ""
        return text[after_start:end_idx].strip().strip("'\"")

    @classmethod
    def _build_memory_update_input(cls, text: str) -> dict[str, object]:
        """Parse an update or move command into memory_update tool input.

        Recognised shapes:
            update memory <id>: <new text>   -> operation "update"
            move memory <id> to <category>   -> operation "move"

        Args:
            text: The original request text.

        Returns:
            The input dictionary for the memory_update tool. Missing pieces are
            left absent so the tool reports the problem clearly.
        """
        stripped = text.strip()
        lowered = stripped.casefold()

        if lowered.startswith("move memory"):
            memory_id = cls._extract_memory_id(stripped, "move memory")
            category = cls._extract_after(stripped, " to ")
            result: dict[str, object] = {"operation": "move"}
            if memory_id is not None:
                result["memory_id"] = memory_id
            if category:
                result["category"] = category
            return result

        # Default: update content. "update memory <id>: <new text>"
        memory_id = cls._extract_memory_id(stripped, "update memory")
        content = ""
        if ":" in stripped:
            content = stripped.split(":", 1)[1].strip()
        result = {"operation": "update"}
        if memory_id is not None:
            result["memory_id"] = memory_id
        if content:
            result["content"] = content
        return result

    @staticmethod
    def _extract_memory_id(text: str, prefix: str) -> int | None:
        """Extract the first integer id following a command prefix.

        Args:
            text: The original request text.
            prefix: The command prefix (e.g. "forget memory") to strip first.

        Returns:
            The id as an int, or None if none was found.
        """
        lowered = text.casefold()
        idx = lowered.find(prefix.casefold())
        remainder = text[idx + len(prefix):] if idx != -1 else text
        for token in remainder.replace(":", " ").split():
            if token.isdigit():
                return int(token)
        return None

    @staticmethod
    def _extract_trailing_id(text: str) -> int | None:
        """Extract a numeric id from a 'show memory <id>' style command.

        Args:
            text: The original request text.

        Returns:
            The id as an int, or None if no numeric token is present.
        """
        for token in text.replace(":", " ").split():
            if token.isdigit():
                return int(token)
        return None