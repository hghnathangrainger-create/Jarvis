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
    - Coordinate the explicit file-summary workflow (Phase 8, Batch 2) by
      calling ai.file_ingestion.ingest_file_for_ai() and AIReasoningEngine -
      never by reading a file or building AI context itself.

Does NOT:
    - Call the Claude API or any AI provider.
    - Execute anything directly; all tool execution goes through ToolExecutor.
    - Bypass the security gate under any circumstance.
    - Implement autonomous behaviour, voice, phone, or UI.
    - Read a file itself, or construct/relabel an AIContextBlock. File
      acquisition and provenance labelling belong solely to
      ai.file_ingestion.ingest_file_for_ai() (Phase 8, Batch 1).

The orchestrator coordinates existing subsystems; it owns no planning,
security, or execution logic of its own. Every consequential action flows
through the components that already enforce safety, so the Core cannot become
a way around them.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalDecision
from ai.file_ingestion import ingest_file_for_ai
from ai.memory_ingestion import (
    MemoryIngestionResult,
    MemorySetIngestionResult,
    ingest_memories_for_ai,
    ingest_memory_for_ai,
)
from ai.memory_selection import (
    CategorySelectionResult,
    QuerySelectionResult,
    RecentCountSelectionResult,
    RecentSelectionResult,
    select_memory_ids_by_category,
    select_memory_ids_by_query,
    select_recent_memory_ids,
    select_recent_memory_ids_by_count,
)
from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import AIReasoningRequest, AIReasoningResult
from config.constants import EventOutcome, SecurityTier
from core.command_router import CommandRouter
from core.request_models import JarvisRequest, JarvisResponse
from memory.memory_manager import MemoryManager
from memory.memory_models import KNOWN_CATEGORIES
from planner.plan_models import Plan
from planner.planner import Planner
from security.security_manager import (
    SecurityManager,
    UnexpectedActionDecision,
    UnexpectedActionVerdict,
)
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


class _AuditLogger(Protocol):
    """The minimal logging interface JarvisOrchestrator depends on.

    This matches the emit method of observability.logger.EventLogger.
    Declaring it as a Protocol keeps the orchestrator decoupled from the
    concrete logger, mirroring approval.approval_manager._ApprovalAuditLogger
    (Phase 7, Batch 4).
    """

    def emit(
        self,
        *,
        source: str,
        action_type: str,
        outcome: EventOutcome,
        detail: str | None = ...,
        duration_ms: int | None = ...,
        security_tier: SecurityTier | None = ...,
        session_id: int | None = ...,
    ) -> str:
        """Emit a structured event. See EventLogger.emit for details."""
        ...


_SOURCE = "jarvis_orchestrator"
_UNEXPECTED_ACTION_TYPE = "unexpected_ai_action"

#: Advisory label for a file-summary response's message (Phase 8, Batch 2).
#: Deliberately distinct from _attach_ai_suggestion's own
#: "[AI suggestion - advisory only]" label: that label marks an *appended*
#: annotation on an already-decided response; this one marks a response
#: whose entire content *is* the AI's own advisory output.
_FILE_SUMMARY_LABEL = "[AI file summary - advisory only]"
_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise this file's contents."
)
_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for this file right now."
)

#: Advisory label for a memory-summary response's message (Phase 9, Batch 2).
#: Distinct from _FILE_SUMMARY_LABEL for the same reason that label is
#: distinct from _attach_ai_suggestion's own annotation label: this marks a
#: response whose entire content *is* the AI's own advisory output about a
#: stored memory, not an annotation appended to an already-decided response.
_MEMORY_SUMMARY_LABEL = "[AI memory summary - advisory only]"
_MEMORY_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise this memory's contents."
)
_MEMORY_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for this memory right now."
)
_MEMORY_MANAGER_NOT_AVAILABLE_MESSAGE = (
    "Memory access is not available, so I can't summarise this memory."
)

#: Advisory label for a multi-memory-summary response's message (Phase 10,
#: Batch 2). Distinct from _MEMORY_SUMMARY_LABEL for the same reason that
#: label is distinct from _FILE_SUMMARY_LABEL: each marks a different
#: response shape, though all three share the same advisory-only authority
#: boundary.
_MEMORY_SET_SUMMARY_LABEL = "[AI multi-memory summary - advisory only]"
_MEMORY_SET_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these memories' contents."
)
_MEMORY_SET_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for these memories right now."
)
_MEMORY_SET_MANAGER_NOT_AVAILABLE_MESSAGE = (
    "Memory access is not available, so I can't summarise these memories."
)

#: Maximum number of distinct memory ids one "summarise memories <ids>"
#: request may name (Phase 10 plan, Section 15). Kept in sync with
#: ai.memory_ingestion.ingest_memories_for_ai's own max_records default
#: (10): this is the honest, user-facing rejection check performed *before*
#: any retrieval is attempted; ingest_memories_for_ai's own max_records
#: guard is a defensive backstop that should never actually trigger through
#: this orchestrator path, mirroring the same "validate here, backstop
#: there" relationship already established between _parse_memory_id and
#: ingest_memory_for_ai's own max_chars guard.
_MAX_MEMORY_SET_SIZE = 10

#: Action type for the orchestrator's own memory-acquisition audit event
#: (Phase 9, Batch 2). Acquisition here goes directly through
#: MemoryManager.get() rather than ToolExecutor, so it never receives the
#: generic "tool_call" event ToolExecutor would otherwise emit for free; this
#: is the explicit, disclosed replacement (Phase 9 plan, Section 15).
_MEMORY_ACQUISITION_ACTION_TYPE = "memory_acquisition"

#: Advisory label for a query-based memory-summary response's message
#: (Phase 11, Batch 2). Distinct from the other three summary labels for
#: the same reason each of those is distinct from the others: this marks a
#: response whose entire content *is* the AI's own advisory output about a
#: deterministically-searched set of memories, not an annotation appended
#: to an already-decided response.
_MEMORY_QUERY_SUMMARY_LABEL = "[AI query-based memory summary - advisory only]"
_MEMORY_QUERY_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these memories' contents."
)
_MEMORY_QUERY_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for these memories right now."
)
_MEMORY_QUERY_MANAGER_NOT_AVAILABLE_MESSAGE = (
    "Memory access is not available, so I can't search your memories."
)
#: Honest rejection message for a query-based summary request with no query
#: text at all (docs/phase_11_implementation_plan.md, Section 8, category
#: 1 - "invalid query", rejected before select_memory_ids_by_query() is
#: ever called, mirroring _parse_memory_id/_parse_memory_ids's own
#: pre-acquisition rejection of malformed input).
_MEMORY_QUERY_EMPTY_MESSAGE = (
    "Please provide a query to search your memories for, for example "
    "'summarise memories about the budget review'."
)

#: Action type for the orchestrator's own query-selection audit event
#: (Phase 11, Batch 2). Reports that a deterministic search was attempted
#: and its outcome, distinct from the per-id memory_acquisition events
#: Phase 10's ingestion still emits afterward for the ids that search
#: selected (docs/phase_11_implementation_plan.md, Section 12.2/13). Never
#: embeds the raw query text - only its length, matching
#: ai/prompt_builder.py's own audit_suspicious_injection convention of
#: logging text_length rather than text.
_MEMORY_QUERY_SELECTION_ACTION_TYPE = "memory_query_selection"

#: Advisory label for a category-based memory-summary response's message
#: (Phase 12, Batch 2). Distinct from the other summary labels for the
#: same reason each of those is distinct from the others: this marks a
#: response whose entire content *is* the AI's own advisory output about a
#: deterministically category-selected set of memories, not an annotation
#: appended to an already-decided response.
_MEMORY_CATEGORY_SUMMARY_LABEL = "[AI category memory summary - advisory only]"
_MEMORY_CATEGORY_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these memories' contents."
)
_MEMORY_CATEGORY_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for these memories right now."
)
_MEMORY_CATEGORY_MANAGER_NOT_AVAILABLE_MESSAGE = (
    "Memory access is not available, so I can't look up memories by category."
)
#: Honest rejection message for a category-based summary request with no
#: category text at all (docs/phase_12_implementation_plan.md, Section 8,
#: category 1 - "empty category syntax", rejected before
#: select_memory_ids_by_category() is ever called, mirroring Phase 11's
#: own pre-selector rejection of an empty query).
_MEMORY_CATEGORY_EMPTY_MESSAGE = (
    "Please provide a category to look up, for example "
    "'summarise memories in project'."
)

#: Action type for the orchestrator's own category-selection audit event
#: (Phase 12, Batch 2). Reports that a deterministic category lookup was
#: attempted and its outcome, distinct from the per-id memory_acquisition
#: events Phase 10's ingestion still emits afterward for the ids the
#: lookup selected (docs/phase_12_implementation_plan.md, Section 12/13).
#: Unlike the query-selection event, the category value itself is logged
#: directly when one was actually established - categories are a small,
#: fixed, non-sensitive vocabulary (docs/phase_12_implementation_plan.md,
#: Section 12) - but never for an invalid category, where no canonical
#: category was ever established (CategorySelectionResult.category is
#: None), so the field is omitted entirely rather than carrying the raw,
#: unvalidated input or a fabricated "general" value.
_MEMORY_CATEGORY_SELECTION_ACTION_TYPE = "memory_category_selection"

#: Advisory label for a recent-memory-summary response's message (Phase 13,
#: Batch 2). Distinct from the other summary labels for the same reason
#: each of those is distinct from the others: this marks a response whose
#: entire content *is* the AI's own advisory output about a deterministically
#: recency-selected set of memories, not an annotation appended to an
#: already-decided response.
_MEMORY_RECENT_SUMMARY_LABEL = "[AI recent memory summary - advisory only]"
_MEMORY_RECENT_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these memories' contents."
)
_MEMORY_RECENT_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for these memories right now."
)
_MEMORY_RECENT_MANAGER_NOT_AVAILABLE_MESSAGE = (
    "Memory access is not available, so I can't look up recent memories."
)
#: Honest rejection message for a valid lookup that returned nothing stored
#: at all (docs/phase_13_implementation_plan.md, Section 9). Unlike the
#: query/category workflows, there is no user-supplied criterion to name in
#: this wording - "recent" carries no query text or category label - so this
#: message names only the actual, honest fact: the store is empty.
_MEMORY_RECENT_ZERO_RECORDS_MESSAGE = "No memories are stored yet."
#: Fallback lookup-failure wording, used only if a future caller ever
#: constructs a RecentSelectionResult.failed with no `error` set (never true
#: for select_recent_memory_ids() itself, which always sets `error` for this
#: state) - mirrors the same defensive `or` pattern already used for the
#: query/category workflows' own failure branches.
_MEMORY_RECENT_LOOKUP_FAILURE_FALLBACK_MESSAGE = (
    "Could not look up recent stored memories right now."
)

#: Action type for the orchestrator's own recency-selection audit event
#: (Phase 13, Batch 2). Reports that a deterministic recent-memory lookup
#: was attempted and its outcome, distinct from the per-id
#: memory_acquisition events Phase 10's ingestion still emits afterward for
#: the ids the lookup selected (docs/phase_13_implementation_plan.md,
#: Section 13/14). Unlike the category-selection event, there is no
#: criterion value to log at all (no query text, no category label) - the
#: fixed selection ceiling (10) is a code-level constant with no per-request
#: variance, so no `requested_count=` field is added either, mirroring the
#: plan's own reasoning for why that field would be redundant.
_MEMORY_RECENT_SELECTION_ACTION_TYPE = "memory_recent_selection"

#: Advisory label for a count-based recent-memory-summary response's
#: message (Phase 14, Batch 2). Distinct from the other summary labels for
#: the same reason each of those is distinct from the others: this marks a
#: response whose entire content *is* the AI's own advisory output about a
#: deterministically count-bounded recency-selected set of memories, not
#: an annotation appended to an already-decided response.
_MEMORY_RECENT_COUNT_SUMMARY_LABEL = (
    "[AI recent-count memory summary - advisory only]"
)
#: Deliberately a fifth, independently-declared copy of the same wording
#: every other memory-summary workflow already uses for these two
#: messages (docs/phase_14_implementation_plan.md, Section 12) - not
#: centralised in this batch, per the explicit instruction not to perform
#: that refactor here.
_MEMORY_RECENT_COUNT_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these memories' contents."
)
_MEMORY_RECENT_COUNT_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for these memories right now."
)
_MEMORY_RECENT_COUNT_MANAGER_NOT_AVAILABLE_MESSAGE = (
    "Memory access is not available, so I can't look up recent memories by count."
)

#: Action type for the orchestrator's own count-based recency-selection
#: audit event (Phase 14, Batch 2). A new, distinct event from Phase 13's
#: own memory_recent_selection - reusing that event would force it to
#: handle two semantically different call shapes (a fixed command with no
#: per-request variance, and a user-controlled one with genuine variance),
#: silently altering an already-shipped event's meaning for the *existing*
#: command too (docs/phase_14_implementation_plan.md, Section 8). Unlike
#: Phase 13's event, this one does carry a `requested_count=` field - the
#: user-supplied count is genuine, safe-to-log, per-request metadata, a
#: small bounded integer once validated - but only when a valid count was
#: actually established; omitted entirely, never a fabricated value, for
#: an invalid count.
_MEMORY_RECENT_COUNT_SELECTION_ACTION_TYPE = "memory_recent_count_selection"

# The unexpected-action verdict is observability only in Batch 4 (nothing lets
# an AI suggestion execute yet). ESCALATE and BLOCK reuse existing
# EventOutcome values that ToolExecutor already logs purely at
# classification time, with no execution attempt required: PENDING for a
# YELLOW action withheld pending confirmation, and BLOCKED for a RED action
# stopped before it is ever run (tools/executor.py's _handle_needs_
# confirmation / _handle_blocked). FLAG has no honest existing analogue:
# SUCCESS is only ever recorded elsewhere in this codebase after a tool
# actually ran and returned success, which never happens here, so reusing it
# would misrepresent a flagged-but-untouched anomaly as a completed action.
# FLAGGED was added to EventOutcome for exactly this shape, the same way
# TIMEOUT was added in Phase 6 for a genuinely new outcome that no existing
# value covered - both extend the single existing EventOutcome/EventLogger
# machinery rather than introducing a parallel one.
_UNEXPECTED_ACTION_OUTCOME: dict[UnexpectedActionVerdict, EventOutcome] = {
    UnexpectedActionVerdict.FLAG: EventOutcome.FLAGGED,
    UnexpectedActionVerdict.ESCALATE: EventOutcome.PENDING,
    UnexpectedActionVerdict.BLOCK: EventOutcome.BLOCKED,
}


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
        _security: Used only to evaluate whether an AI-suggested action falls
            outside the plan's expected scope (Phase 7, Batch 4). It is never
            used to reclassify, execute, or approve anything; the security
            gate remains solely ToolExecutor's.
        _memory_manager: Optional MemoryManager used only by the explicit
            memory-summary workflow (Phase 9, Batch 2 - a single stored
            memory by id via ingest_memory_for_ai()) and its multi-memory
            sibling (Phase 10, Batch 2 - a small, explicit set of ids via
            ingest_memories_for_ai()). The orchestrator never calls
            MemoryManager.get() itself in either path, never constructs or
            combines an AIContextBlock itself, and never reads
            MemoryRecord.source - acquisition and provenance stay entirely
            inside ai.memory_ingestion. When omitted, both memory-summary
            workflows fail honestly rather than raising.
        _logger: Optional audit logger for the unexpected-action verdict.
            When omitted, evaluation still happens but nothing is recorded.
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
        security_manager: SecurityManager | None = None,
        memory_manager: MemoryManager | None = None,
        logger: _AuditLogger | None = None,
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
            security_manager: Used only to evaluate the unexpected-action
                verdict for AI-suggested actions (Phase 7, Batch 4). A new one
                is created if omitted; it is stateless, so this is equivalent
                to sharing the application's existing instance.
            memory_manager: An optional MemoryManager, used only by the
                explicit "summarise memory <id>" workflow (Phase 9, Batch 2).
                No new instance is ever created here if omitted - unlike
                approval_manager/security_manager, MemoryManager requires a
                real store, so there is no safe stateless default; when
                omitted, memory-summary requests fail honestly instead.
            logger: Optional audit logger for the unexpected-action verdict.
                The verdict is always evaluated; when logger is omitted,
                nothing is recorded, matching how approval_manager behaves
                without an audit_logger.
        """
        self._planner = planner
        self._executor = executor
        self._registry = registry
        self._command_router = command_router
        self._approvals = approval_manager or ApprovalManager()
        self._reasoning = reasoning_engine
        self._security = security_manager or SecurityManager()
        self._memory_manager = memory_manager
        self._logger = logger

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

        An explicit file-summary request ("summarise file <path>", Phase 8,
        Batch 2), singular memory-summary request ("summarise memory <id>",
        Phase 9, Batch 2), query-based memory-summary request ("summarise
        memories about <query>", Phase 11, Batch 2), category-based
        memory-summary request ("summarise memories in <category>", Phase
        12, Batch 2), recent-memory-summary request ("summarise recent
        memories", Phase 13, Batch 2), count-based recent-memory-summary
        request ("summarise latest <count> memories", Phase 14, Batch 2),
        or explicit-id multi-memory-summary request ("summarise memories
        <ids>", Phase 10, Batch 2) is recognised first and handled by its
        own terminal path (_handle_file_summary_request /
        _handle_memory_summary_request / _handle_memory_query_summary_request
        / _handle_memory_category_summary_request /
        _handle_memory_recent_summary_request /
        _handle_memory_recent_count_summary_request /
        _handle_memory_set_summary_request) - it never reaches the
        rule-based handler below or _attach_ai_suggestion, since its entire
        response *is* the AI's own advisory output, not an annotation
        appended to an already-decided one. Every other request is a thin
        wrapper around the rule-based request handler: the response is
        produced entirely by the existing Planner, SecurityManager,
        ToolExecutor, and ApprovalManager path. Only after that
        authoritative response is built is an *advisory* AI suggestion
        optionally attached, and only when a reasoning engine is active.
        The AI never changes the outcome: routing, classification,
        approval, and execution are all already decided before the AI is
        consulted.

        Dispatch precedence is significant and deliberately ordered
        (docs/phase_11_implementation_plan.md, Section 3.2.1;
        docs/phase_12_implementation_plan.md, Section 3.2): both the
        query-based and category-based matchers are checked BEFORE the
        explicit-id plural matcher, because "summarise memories about" and
        "summarise memories in" are both strict superset-strings of
        "summarise memories" - checking the plural matcher first would
        incorrectly swallow either request and reject it as an invalid id
        list. Neither matcher's position relative to the singular matcher,
        nor relative to each other, affects correctness (none of their
        prefixes collide with one another), but they are grouped together
        here, immediately before the plural matcher they must both
        precede.

        The recent-memory matcher (Phase 13) is checked immediately after
        the category matcher, grouped narratively with the other
        deterministic-selection commands, but - unlike the query/category
        matchers - its position here is **not** a correctness requirement:
        "summarise recent memories" places its qualifier ("recent") before
        "memories" rather than after it, so it is not a superset-string of
        any other summary-family prefix in either direction
        (docs/phase_13_implementation_plan.md, Section 4.1/11). It would
        route identically from any position in this dispatch block.

        The count-based recent-memory matcher (Phase 14) is checked
        immediately after the fixed recent-memory matcher, grouped
        narratively as the third member of the "recency family"
        (category -> recent -> recent-count), but its position here is
        likewise **not** a correctness requirement: "summarise latest
        <count> memories" requires the literal "latest" keyword and a
        mandatory "memories" suffix that no other summary-family prefix
        shares, and its own exact grammar is never a superset-string of,
        nor collides with, any of the other five matchers in either
        direction (docs/phase_14_implementation_plan.md, Section 4.2/4.3).
        It would route identically from any position in this dispatch
        block.

        Args:
            user_request: The user's request in natural language.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse describing the outcome, with an advisory
            ai_suggestion attached only when AI reasoning is active.
        """
        file_summary_path = self._command_router.match_file_summary(
            user_request.strip()
        )
        if file_summary_path is not None:
            return self._handle_file_summary_request(
                file_summary_path, user_request, session_id
            )

        memory_summary_raw_id = self._command_router.match_memory_summary(
            user_request.strip()
        )
        if memory_summary_raw_id is not None:
            return self._handle_memory_summary_request(
                memory_summary_raw_id, user_request, session_id
            )

        memory_query_summary_raw_text = (
            self._command_router.match_memory_query_summary(user_request.strip())
        )
        if memory_query_summary_raw_text is not None:
            return self._handle_memory_query_summary_request(
                memory_query_summary_raw_text, user_request, session_id
            )

        memory_category_summary_raw_text = (
            self._command_router.match_memory_category_summary(
                user_request.strip()
            )
        )
        if memory_category_summary_raw_text is not None:
            return self._handle_memory_category_summary_request(
                memory_category_summary_raw_text, user_request, session_id
            )

        if self._command_router.match_memory_recent_summary(user_request.strip()):
            return self._handle_memory_recent_summary_request(
                user_request, session_id
            )

        memory_recent_count_summary_raw_text = (
            self._command_router.match_memory_recent_count_summary(
                user_request.strip()
            )
        )
        if memory_recent_count_summary_raw_text is not None:
            return self._handle_memory_recent_count_summary_request(
                memory_recent_count_summary_raw_text, user_request, session_id
            )

        memory_set_summary_raw_ids = self._command_router.match_memory_set_summary(
            user_request.strip()
        )
        if memory_set_summary_raw_ids is not None:
            return self._handle_memory_set_summary_request(
                memory_set_summary_raw_ids, user_request, session_id
            )

        response = self._handle_request_core(user_request, session_id=session_id)
        return self._attach_ai_suggestion(response, user_request, session_id)

    def _handle_file_summary_request(
        self, path: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle an explicit "summarise file <path>" request (Phase 8, Batch 2).

        This is a terminal response path, separate from the rule-based
        _handle_request_core/_attach_ai_suggestion flow: the AI's own output
        is the entire point of this request, not an annotation appended to
        an already-decided response. It still coordinates only existing,
        already-secured components - it owns no file-reading, context
        construction, or unexpected-action logic of its own:

            1. A Plan is generated normally (Planner.create_plan), so the
               existing unexpected-action policy has a real expected-action
               scope to evaluate AI suggestions against, exactly as for any
               other request.
            2. ai.file_ingestion.ingest_file_for_ai() performs the file read
               through the real ToolExecutor (the same GREEN, already-
               classified, already-audited "file_read" tool call any other
               file-reading request goes through) and returns either an
               UNTRUSTED AIContextBlock or a represented failure - this
               method never calls FileReadTool directly, never constructs an
               AIContextBlock itself, and never re-labels or re-derives
               trust or provenance.
            3. On success, the returned context_block - already trust-tagged
               and labelled by ingest_file_for_ai - is forwarded, unchanged,
               into a new AIReasoningRequest.
            4. AIReasoningEngine.reason() is called exactly as it always is;
               this method has no ability to execute anything regardless of
               what the AI returns.
            5. Every AI-suggested action is evaluated through the existing,
               unmodified _evaluate_unexpected_actions/_audit_unexpected_action
               methods - the same Batch 4 policy and audit path every other
               request already uses. This is not optional: a multi-line AI
               summary can produce AISuggestedAction entries under
               AIReasoningEngine._parse()'s existing behaviour, and this
               path is at least as exposed to adversarial content as any
               other, since the AI reasoned about real file content.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            path: The file path extracted by CommandRouter.match_file_summary.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced; otherwise success=False with an honest explanation of
            which stage did not complete (AI reasoning disabled/unavailable,
            or file acquisition failed) - never blocked or requiring
            confirmation, since reading a GREEN file and consulting
            advisory AI about already-permitted content requires no new
            approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        ingestion = ingest_file_for_ai(self._executor, path, session_id=session_id)
        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read the file.",
                plan=plan,
            )

        reasoning_request = AIReasoningRequest(
            user_input=user_request,
            context_block=ingestion.context,
            session_id=session_id,
        )
        result = self._reasoning.reason(reasoning_request)
        if result is None:
            return JarvisResponse(
                success=False,
                message=_AI_REASONING_UNAVAILABLE_MESSAGE,
                plan=plan,
            )

        summary = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            summary = f"{result.summary} Suggested steps: {steps}"

        response = JarvisResponse(
            success=True,
            message=f"{_FILE_SUMMARY_LABEL} {summary}",
            plan=plan,
        )

        # Reused, not duplicated: the exact same Batch 4 policy/audit method
        # every other request's advisory suggestion already goes through.
        self._evaluate_unexpected_actions(response, result, session_id)

        return response

    def _handle_memory_summary_request(
        self, raw_id_text: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle an explicit "summarise memory <id>" request (Phase 9, Batch 2).

        This is a terminal response path, the direct architectural sibling of
        _handle_file_summary_request, separate from the rule-based
        _handle_request_core/_attach_ai_suggestion flow: the AI's own output
        about a stored memory is the entire point of this request, not an
        annotation appended to an already-decided response. It still
        coordinates only existing, already-secured components - it owns no
        memory-retrieval, context-construction, or unexpected-action logic of
        its own:

            1. A Plan is generated normally (Planner.create_plan), so the
               existing unexpected-action policy has a real expected-action
               scope to evaluate AI suggestions against, exactly as for any
               other request.
            2. The raw trailing id text CommandRouter.match_memory_summary
               extracted is parsed into an int here, before anything else is
               attempted - an invalid id fails honestly with no memory read,
               no audit event, and no AI ever consulted.
            3. Required collaborators (AI reasoning, then the memory_manager)
               are confirmed available, each with its own honest failure.
            4. ai.memory_ingestion.ingest_memory_for_ai() performs the memory
               read directly through MemoryManager.get() - the same typed
               acquisition boundary Batch 1 established - and returns either
               an UNTRUSTED AIContextBlock or a represented failure. This
               method never calls MemoryManager.get() directly, never
               constructs an AIContextBlock itself, never reads
               MemoryRecord.source, and never re-labels or re-derives trust
               or provenance.
            5. The orchestrator's own acquisition audit event is emitted
               (_audit_memory_acquisition) - the explicit, disclosed
               replacement for the tool_call event this path does not
               receive for free, since it never goes through ToolExecutor.
            6. On success, the returned context_block - already trust-tagged
               and labelled by ingest_memory_for_ai - is forwarded, unchanged,
               into a new AIReasoningRequest.
            7. AIReasoningEngine.reason() is called exactly as it always is;
               this method has no ability to execute anything regardless of
               what the AI returns.
            8. Every AI-suggested action is evaluated through the existing,
               unmodified _evaluate_unexpected_actions/_audit_unexpected_action
               methods - the same Batch 4 policy and audit path every other
               request already uses.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            raw_id_text: The raw, unparsed trailing text extracted by
                CommandRouter.match_memory_summary - possibly empty or
                non-numeric.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced from a genuinely retrieved memory; otherwise
            success=False with an honest explanation of which stage did not
            complete (invalid id, AI reasoning disabled/unavailable, memory
            subsystem unavailable, or memory acquisition failure) - never
            blocked or requiring confirmation, since reading a memory is
            already GREEN and consulting advisory AI about already-permitted
            content requires no new approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        memory_id = self._parse_memory_id(raw_id_text)
        if memory_id is None:
            return JarvisResponse(
                success=False,
                message=(
                    f"'{raw_id_text}' is not a valid memory id. Please "
                    "provide a numeric id, for example 'summarise memory 42'."
                ),
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._memory_manager is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_MANAGER_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        ingestion = ingest_memory_for_ai(self._memory_manager, memory_id)
        self._audit_memory_acquisition(ingestion, memory_id, session_id)

        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read that memory.",
                plan=plan,
            )

        reasoning_request = AIReasoningRequest(
            user_input=user_request,
            context_block=ingestion.context,
            session_id=session_id,
        )
        result = self._reasoning.reason(reasoning_request)
        if result is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_AI_REASONING_UNAVAILABLE_MESSAGE,
                plan=plan,
            )

        summary = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            summary = f"{result.summary} Suggested steps: {steps}"
        if ingestion.truncated:
            summary = (
                f"{summary} Note: only part of this memory's content was "
                "available for this summary."
            )

        response = JarvisResponse(
            success=True,
            message=f"{_MEMORY_SUMMARY_LABEL} {summary}",
            plan=plan,
        )

        # Reused, not duplicated: the exact same Batch 4 policy/audit method
        # every other request's advisory suggestion already goes through.
        self._evaluate_unexpected_actions(response, result, session_id)

        return response

    def _handle_memory_query_summary_request(
        self, raw_query_text: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle an explicit "summarise memories about <query>" request
        (Phase 11, Batch 2).

        This is a terminal response path, the query-based sibling of
        _handle_memory_set_summary_request, generalised from a small,
        explicit, user-named id set to a deterministic search selection.
        It owns no search invocation beyond the one call to
        ai.memory_selection.select_memory_ids_by_query(), no memory
        retrieval/combination beyond reusing
        ai.memory_ingestion.ingest_memories_for_ai() unchanged, and no
        unexpected-action logic of its own - every one of those
        responsibilities stays inside the components it calls, or in the
        existing, unmodified Phase 7 Batch 4 methods:

            1. A Plan is generated normally, exactly as for every other
               request.
            2. The raw trailing query text CommandRouter.match_memory_
               query_summary extracted is checked for emptiness here
               (docs/phase_11_implementation_plan.md, Section 8, category
               1) - a query-command phrase with no trailing text at all
               fails honestly with no search attempted, no audit event,
               and no AI ever consulted. Any other query text, including
               punctuation-only text, is passed on unchanged: this method
               performs no semantic validation of the query.
            3. Required collaborators (AI reasoning, then the
               memory_manager) are confirmed available, each with its own
               honest failure - mirroring the explicit-id workflow's own
               order.
            4. ai.memory_selection.select_memory_ids_by_query() performs
               the one deterministic search call, at the fixed Phase 11
               selection ceiling (10), preserving the store's own result
               order exactly. This method never calls
               MemoryManager.search() itself and never ranks, reorders,
               or deduplicates its result.
            5. The Phase 11 selection outcome is audited once
               (_audit_memory_query_selection) - a new, narrow,
               non-authoritative event distinct from Phase 10's per-id
               acquisition events.
            6. Zero matches and a genuine search failure each return their
               own distinct, honest response - neither ever reaches
               ingestion or AI reasoning.
            7. On a non-empty selection, the ordered selected ids are
               handed, unchanged and in the same order, into
               ai.memory_ingestion.ingest_memories_for_ai() - the exact
               same Phase 10 primitive the explicit-id workflow already
               uses, unmodified. This method never constructs or combines
               an AIContextBlock itself.
            8. The existing per-id acquisition audit
               (_audit_memory_set_acquisition) fires exactly as it already
               does for the explicit-id workflow.
            9. If no id could be included, this fails honestly with the
               ingestion result's own itemized error - the AI is never
               consulted with no usable context.
            10. On partial or full success, the one combined context_block
                - already trust-tagged and labelled from the *included*
                set by ingest_memories_for_ai - is forwarded, unchanged,
                into a new AIReasoningRequest. The raw search query is
                never included in this context_block; it reaches the AI
                only as part of the live user_input, exactly as every
                other summary command's own trailing text already does
                (docs/phase_11_implementation_plan.md, Section 6.1).
            11. AIReasoningEngine.reason() is called exactly as it always
                is; this method has no ability to execute anything
                regardless of what the AI returns.
            12. Every AI-suggested action is evaluated through the
                existing, unmodified _evaluate_unexpected_actions/
                _audit_unexpected_action methods.
            13. The response honestly distinguishes two separate layers of
                accounting: the Phase 11 search-selection count (how many
                memories matched the query) and Phase 10's own itemized
                ingestion disclosure (not_found/retrieval_errors/
                omitted_for_size/truncated_records) via the existing,
                unmodified _build_memory_set_disclosure - neither is ever
                mixed into, or fed back into, the untrusted memory context
                the AI reasoned about.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            raw_query_text: The raw, unparsed trailing text extracted by
                CommandRouter.match_memory_query_summary - possibly empty.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced from at least one genuinely retrieved memory;
            otherwise success=False with an honest explanation of which
            stage did not complete (empty query, AI reasoning
            disabled/unavailable, memory subsystem unavailable, zero
            search matches, a search failure, or no usable context after
            ingestion) - never blocked or requiring confirmation, since
            searching and reading memories is already GREEN and consulting
            advisory AI about already-permitted content requires no new
            approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        query = raw_query_text.strip()
        if not query:
            return JarvisResponse(
                success=False,
                message=_MEMORY_QUERY_EMPTY_MESSAGE,
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_QUERY_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._memory_manager is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_QUERY_MANAGER_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        selection = select_memory_ids_by_query(self._memory_manager, query)
        self._audit_memory_query_selection(selection, session_id)

        if selection.zero_matches:
            return JarvisResponse(
                success=False,
                message=f"No stored memories matched '{query}'.",
                plan=plan,
            )

        if selection.failed:
            return JarvisResponse(
                success=False,
                message=selection.error or "Could not search stored memories right now.",
                plan=plan,
            )

        ingestion = ingest_memories_for_ai(self._memory_manager, selection.selected_ids)
        self._audit_memory_set_acquisition(ingestion, session_id)

        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read those memories.",
                plan=plan,
            )

        match_count = len(selection.selected_ids)
        memory_noun = "memory" if match_count == 1 else "memories"
        selection_sentence = f"Found {match_count} matching {memory_noun} for '{query}'."

        return self._build_memory_summary_response(
            ingestion=ingestion,
            user_request=user_request,
            session_id=session_id,
            plan=plan,
            ai_unavailable_message=_MEMORY_QUERY_AI_REASONING_UNAVAILABLE_MESSAGE,
            label=_MEMORY_QUERY_SUMMARY_LABEL,
            selection_sentence=selection_sentence,
        )

    def _handle_memory_category_summary_request(
        self, raw_category_text: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle an explicit "summarise memories in <category>" request
        (Phase 12, Batch 2).

        This is a terminal response path, the category-based sibling of
        _handle_memory_query_summary_request, generalised from a
        deterministic search query to a deterministic category lookup. It
        owns no category validation/canonicalisation beyond the one call
        to ai.memory_selection.select_memory_ids_by_category() (which is
        itself the defensive, authoritative correctness boundary - see
        docs/phase_12_implementation_plan.md, Section 5.3), no memory
        retrieval/combination beyond reusing
        ai.memory_ingestion.ingest_memories_for_ai() unchanged, and no
        unexpected-action logic of its own:

            1. A Plan is generated normally, exactly as for every other
               request.
            2. The raw trailing category text CommandRouter.match_memory_
               category_summary extracted is checked for emptiness here
               (docs/phase_12_implementation_plan.md, Section 4/8, category
               1) - a category-command phrase with no trailing text at all
               fails honestly with no lookup attempted, no audit event,
               and no AI ever consulted. This is the *only* pre-selector
               check this method performs: whether the supplied text is a
               *known* category is the selector's own responsibility, not
               this method's (Section 5.3, Candidate B) - no second
               category vocabulary is duplicated here.
            3. Required collaborators (AI reasoning, then the
               memory_manager) are confirmed available, each with its own
               honest failure - mirroring the query workflow's own order.
            4. ai.memory_selection.select_memory_ids_by_category() performs
               the one deterministic category lookup, at the fixed Phase
               12 selection ceiling (10), preserving the store's own
               result order exactly. This method never calls
               MemoryManager.list_by_category() itself, never calls
               MemoryTool, and never ranks, reorders, or deduplicates the
               selector's result.
            5. The Phase 12 selection outcome is audited once
               (_audit_memory_category_selection) - a new, narrow,
               non-authoritative event distinct from Phase 10's per-id
               acquisition events.
            6. An invalid category, zero matching records, and a genuine
               lookup failure each return their own distinct, honest
               response - none of the three ever reaches ingestion or AI
               reasoning. An unknown category (e.g. "spaceships") never
               selects "general" memories: select_memory_ids_by_category()
               already refused to call MemoryManager.list_by_category() at
               all for it (Section 2.1/5.3).
            7. On a non-empty selection, the ordered selected ids are
               handed, unchanged and in the same order, into
               ai.memory_ingestion.ingest_memories_for_ai() - the exact
               same Phase 10 primitive the explicit-id and query-based
               workflows already use, unmodified. This method never
               constructs or combines an AIContextBlock itself.
            8. The existing per-id acquisition audit
               (_audit_memory_set_acquisition) fires exactly as it already
               does for the explicit-id and query-based workflows.
            9. If no id could be included, this fails honestly with the
               ingestion result's own itemized error - the AI is never
               consulted with no usable context.
            10. On partial or full success, the one combined context_block
                - already trust-tagged and labelled from the *included*
                set by ingest_memories_for_ai - is forwarded, unchanged,
                into a new AIReasoningRequest. The raw category text is
                never included in this context_block; it reaches the AI
                only as part of the live user_input, exactly as every
                other summary command's own trailing text already does
                (docs/phase_12_implementation_plan.md, Section 9).
            11. AIReasoningEngine.reason() is called exactly as it always
                is; this method has no ability to execute anything
                regardless of what the AI returns.
            12. Every AI-suggested action is evaluated through the
                existing, unmodified _evaluate_unexpected_actions/
                _audit_unexpected_action methods.
            13. The response honestly distinguishes two separate layers of
                accounting: the Phase 12 category-selection count (how
                many memories are in the category) and Phase 10's own
                itemized ingestion disclosure (not_found/retrieval_errors/
                omitted_for_size/truncated_records) via the existing,
                unmodified _build_memory_set_disclosure - neither is ever
                mixed into, or fed back into, the untrusted memory context
                the AI reasoned about. The category named in the response
                is always the *canonical* value from
                CategorySelectionResult.category (e.g. "project"), never
                the raw, as-typed spelling (e.g. "PROJECT").

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            raw_category_text: The raw, unparsed trailing text extracted
                by CommandRouter.match_memory_category_summary - possibly
                empty.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced from at least one genuinely retrieved memory;
            otherwise success=False with an honest explanation of which
            stage did not complete (empty category, AI reasoning
            disabled/unavailable, memory subsystem unavailable, invalid
            category, zero matching records, a lookup failure, or no
            usable context after ingestion) - never blocked or requiring
            confirmation, since looking up and reading memories by
            category is already GREEN and consulting advisory AI about
            already-permitted content requires no new approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        category_text = raw_category_text.strip()
        if not category_text:
            return JarvisResponse(
                success=False,
                message=_MEMORY_CATEGORY_EMPTY_MESSAGE,
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_CATEGORY_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._memory_manager is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_CATEGORY_MANAGER_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        selection = select_memory_ids_by_category(self._memory_manager, category_text)
        self._audit_memory_category_selection(selection, session_id)

        if selection.invalid_category:
            return JarvisResponse(
                success=False,
                message=(
                    f"'{category_text}' is not a known memory category. "
                    "Known categories are: "
                    + ", ".join(KNOWN_CATEGORIES)
                    + "."
                ),
                plan=plan,
            )

        if selection.zero_matches:
            return JarvisResponse(
                success=False,
                message=(
                    f"No stored memories are in the '{selection.category}' "
                    "category."
                ),
                plan=plan,
            )

        if selection.failed:
            return JarvisResponse(
                success=False,
                message=(
                    selection.error
                    or "Could not look up stored memories by category right now."
                ),
                plan=plan,
            )

        ingestion = ingest_memories_for_ai(self._memory_manager, selection.selected_ids)
        self._audit_memory_set_acquisition(ingestion, session_id)

        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read those memories.",
                plan=plan,
            )

        match_count = len(selection.selected_ids)
        memory_noun = "memory" if match_count == 1 else "memories"
        selection_sentence = (
            f"Found {match_count} {memory_noun} in category "
            f"'{selection.category}'."
        )

        return self._build_memory_summary_response(
            ingestion=ingestion,
            user_request=user_request,
            session_id=session_id,
            plan=plan,
            ai_unavailable_message=_MEMORY_CATEGORY_AI_REASONING_UNAVAILABLE_MESSAGE,
            label=_MEMORY_CATEGORY_SUMMARY_LABEL,
            selection_sentence=selection_sentence,
        )

    def _handle_memory_recent_summary_request(
        self, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the exact "summarise recent memories" request (Phase 13,
        Batch 2).

        This is a terminal response path, the direct architectural sibling
        of _handle_memory_query_summary_request/
        _handle_memory_category_summary_request, generalised from an
        explicit query/category criterion to no criterion at all: the
        command carries no trailing free-text argument, so there is no
        empty-input pre-flight check to perform here (unlike the query/
        category workflows) - CommandRouter.match_memory_recent_summary()
        already proved the exact command text was used before this method
        is ever called. It owns no memory-retrieval, selection, or
        combination logic of its own:

            1. A Plan is generated normally (Planner.create_plan), exactly
               as every other summary workflow already does.
            2. AI reasoning availability and memory-subsystem availability
               (self._reasoning, self._memory_manager) are confirmed
               available, each with its own honest failure - mirroring the
               query/category workflows' own order.
            3. ai.memory_selection.select_recent_memory_ids() performs the
               one deterministic recency lookup, at the fixed Phase 13
               selection ceiling (10), preserving the store's own
               newest-first result order exactly. This method never calls
               MemoryManager.list_recent() itself, never calls MemoryTool,
               and never ranks, reorders, or deduplicates the selector's
               result.
            4. The Phase 13 selection outcome is audited once
               (_audit_memory_recent_selection) - a new, narrow,
               non-authoritative event distinct from Phase 10's per-id
               acquisition events.
            5. Zero stored memories and a genuine lookup failure each
               return their own distinct, honest response - neither ever
               reaches ingestion or AI reasoning.
            6. On a non-empty selection, the ordered selected ids are
               handed, unchanged and in exactly the same newest-first
               order, into ai.memory_ingestion.ingest_memories_for_ai() -
               the exact same Phase 10 primitive the explicit-id, query-
               based, and category-based workflows already use, unmodified.
               This method never constructs or combines an AIContextBlock
               itself, and never reverses the selected set into
               chronological order (docs/phase_13_implementation_plan.md,
               Section 6) - Phase 10's combined-context budget is
               streaming/order-sensitive, so reversing would invert which
               of the selected records survive if that budget is exceeded.
            7. The existing per-id acquisition audit
               (_audit_memory_set_acquisition) fires exactly as it already
               does for the other three memory-summary workflows.
            8. If no id could be included, this fails honestly with the
               ingestion result's own itemized error - the AI is never
               consulted with no usable context.
            9. On partial or full success, the one combined context_block
               - already trust-tagged and labelled from the *included* set
               by ingest_memories_for_ai - is forwarded, unchanged, into a
               new AIReasoningRequest. No recency bookkeeping (selection
               count, "recent" criterion) is ever included in this
               context_block; it reaches the AI only as part of the live
               user_input, exactly as every other summary command's own
               text already does.
            10. AIReasoningEngine.reason() is called exactly as it always
                is; this method has no ability to execute anything
                regardless of what the AI returns.
            11. Every AI-suggested action is evaluated through the
                existing, unmodified _evaluate_unexpected_actions/
                _audit_unexpected_action methods.
            12. The response honestly distinguishes two separate layers of
                accounting: the Phase 13 recency-selection count (how many
                of the newest stored memories were found) and Phase 10's
                own itemized ingestion disclosure (not_found/
                retrieval_errors/omitted_for_size/truncated_records) via
                the existing, unmodified _build_memory_set_disclosure -
                neither is ever mixed into, or fed back into, the
                untrusted memory context the AI reasoned about. The
                wording never claims a time window, calendar meaning, or
                relevance ranking - only the fixed newest-N selection
                actually performed (docs/phase_13_implementation_plan.md,
                Section 16).

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            user_request: The original, full request text (the exact
                recognised command itself, since there is no trailing
                criterion to separate out).
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced from at least one genuinely retrieved memory;
            otherwise success=False with an honest explanation of which
            stage did not complete (AI reasoning disabled/unavailable,
            memory subsystem unavailable, no stored memories at all, a
            lookup failure, or no usable context after ingestion) - never
            blocked or requiring confirmation, since looking up and reading
            the newest stored memories is already GREEN and consulting
            advisory AI about already-permitted content requires no new
            approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_RECENT_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._memory_manager is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_RECENT_MANAGER_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        selection = select_recent_memory_ids(self._memory_manager)
        self._audit_memory_recent_selection(selection, session_id)

        if selection.zero_matches:
            return JarvisResponse(
                success=False,
                message=_MEMORY_RECENT_ZERO_RECORDS_MESSAGE,
                plan=plan,
            )

        if selection.failed:
            return JarvisResponse(
                success=False,
                message=(
                    selection.error
                    or _MEMORY_RECENT_LOOKUP_FAILURE_FALLBACK_MESSAGE
                ),
                plan=plan,
            )

        ingestion = ingest_memories_for_ai(self._memory_manager, selection.selected_ids)
        self._audit_memory_set_acquisition(ingestion, session_id)

        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read those memories.",
                plan=plan,
            )

        match_count = len(selection.selected_ids)
        memory_noun = "memory" if match_count == 1 else "memories"
        selection_sentence = f"Found {match_count} recent {memory_noun}."

        return self._build_memory_summary_response(
            ingestion=ingestion,
            user_request=user_request,
            session_id=session_id,
            plan=plan,
            ai_unavailable_message=_MEMORY_RECENT_AI_REASONING_UNAVAILABLE_MESSAGE,
            label=_MEMORY_RECENT_SUMMARY_LABEL,
            selection_sentence=selection_sentence,
        )

    def _handle_memory_recent_count_summary_request(
        self, raw_count_text: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle a "summarise latest <count> memories" request (Phase 14,
        Batch 2).

        This is a terminal response path, the count-bounded sibling of
        _handle_memory_recent_summary_request, generalised from a fixed,
        criterion-free newest-10 selection to a user-supplied, strictly
        validated, bounded count. It owns no count validation beyond the
        one call to
        ai.memory_selection.select_recent_memory_ids_by_count(), no memory
        retrieval/combination beyond reusing
        ai.memory_ingestion.ingest_memories_for_ai() unchanged, and no
        unexpected-action logic of its own - every one of those
        responsibilities stays inside the components it calls, or in the
        existing, unmodified Phase 7 Batch 4 methods:

            1. A Plan is generated normally, exactly as for every other
               request.
            2. Required collaborators (AI reasoning, then the
               memory_manager) are confirmed available, each with its own
               honest failure - mirroring every other memory-summary
               workflow's own order. There is no separate emptiness
               pre-check here (unlike the query/category workflows):
               CommandRouter.match_memory_recent_count_summary()'s
               mandatory "memories" suffix already means there is no
               realistic "keyword with nothing after it" case to
               distinguish (docs/phase_14_implementation_plan.md, Section
               4.4).
            3. ai.memory_selection.select_recent_memory_ids_by_count()
               performs the one strict count validation and, for a valid
               count, the one deterministic recency lookup - delegating
               internally, unchanged, to the existing
               select_recent_memory_ids(). This method never calls
               MemoryManager.list_recent() itself, never calls MemoryTool,
               and never ranks, reorders, or deduplicates the selector's
               result.
            4. The Phase 14 selection outcome is audited once
               (_audit_memory_recent_count_selection) - a new, narrow,
               non-authoritative event distinct from Phase 13's own
               memory_recent_selection event and from Phase 10's per-id
               acquisition events.
            5. An invalid count, zero stored memories, and a genuine
               lookup failure each return their own distinct, honest
               response - none of the three ever reaches ingestion or AI
               reasoning. An out-of-range or malformed count (zero, over
               the fixed maximum, non-numeric, or otherwise not entirely
               digits) never selects a silently-clamped substitute count -
               select_recent_memory_ids_by_count() already refused to call
               select_recent_memory_ids() at all for it.
            6. On a non-empty selection, the ordered selected ids are
               handed, unchanged and in exactly the same newest-first
               order, into ai.memory_ingestion.ingest_memories_for_ai() -
               the exact same Phase 10 primitive every other
               memory-summary workflow already uses, unmodified. This
               method never constructs or combines an AIContextBlock
               itself.
            7. The existing per-id acquisition audit
               (_audit_memory_set_acquisition) fires exactly as it already
               does for the other four memory-summary workflows.
            8. If no id could be included, this fails honestly with the
               ingestion result's own itemized error - the AI is never
               consulted with no usable context.
            9. On partial or full success, the one combined context_block
               - already trust-tagged and labelled from the *included*
               set by ingest_memories_for_ai - is forwarded, unchanged,
               into a new AIReasoningRequest. No recency-count bookkeeping
               (the requested count, the "latest" criterion) is ever
               included in this context_block; it reaches the AI only as
               part of the live user_input, exactly as every other summary
               command's own text already does.
            10. AIReasoningEngine.reason() is called exactly as it always
                is; this method has no ability to execute anything
                regardless of what the AI returns.
            11. Every AI-suggested action is evaluated through the
                existing, unmodified _evaluate_unexpected_actions/
                _audit_unexpected_action methods.
            12. The response honestly distinguishes two separate layers of
                accounting: the Phase 14 selection-count sentence, built
                from the selector's own actual `match_count` - never the
                raw `requested_count` - so a request for the latest 10
                that only matched 6 stored memories is disclosed as 6, not
                10; and Phase 10's own itemized ingestion disclosure
                (not_found/retrieval_errors/omitted_for_size/
                truncated_records) via the existing, unmodified
                _build_memory_set_disclosure - neither is ever mixed into,
                or fed back into, the untrusted memory context the AI
                reasoned about.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            raw_count_text: The raw, unparsed, unvalidated count text
                extracted by
                CommandRouter.match_memory_recent_count_summary - possibly
                non-numeric, out of range, or containing internal
                whitespace.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced from at least one genuinely retrieved memory;
            otherwise success=False with an honest explanation of which
            stage did not complete (AI reasoning disabled/unavailable,
            memory subsystem unavailable, an invalid count, no stored
            memories at all, a lookup failure, or no usable context after
            ingestion) - never blocked or requiring confirmation, since
            looking up and reading the newest N stored memories is already
            GREEN and consulting advisory AI about already-permitted
            content requires no new approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_RECENT_COUNT_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._memory_manager is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_RECENT_COUNT_MANAGER_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        selection = select_recent_memory_ids_by_count(
            self._memory_manager, raw_count_text
        )
        self._audit_memory_recent_count_selection(selection, session_id)

        if selection.invalid_count:
            return JarvisResponse(
                success=False,
                message=(
                    f"'{raw_count_text.strip()}' is not a valid memory "
                    "count. Please provide a whole number from 1 to 10, "
                    "for example 'summarise latest 5 memories'."
                ),
                plan=plan,
            )

        if selection.zero_matches:
            return JarvisResponse(
                success=False,
                message=_MEMORY_RECENT_ZERO_RECORDS_MESSAGE,
                plan=plan,
            )

        if selection.failed:
            return JarvisResponse(
                success=False,
                message=(
                    selection.error
                    or _MEMORY_RECENT_LOOKUP_FAILURE_FALLBACK_MESSAGE
                ),
                plan=plan,
            )

        ingestion = ingest_memories_for_ai(self._memory_manager, selection.selected_ids)
        self._audit_memory_set_acquisition(ingestion, session_id)

        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read those memories.",
                plan=plan,
            )

        match_count = selection.match_count
        memory_noun = "memory" if match_count == 1 else "memories"
        selection_sentence = f"Found {match_count} recent {memory_noun}."

        return self._build_memory_summary_response(
            ingestion=ingestion,
            user_request=user_request,
            session_id=session_id,
            plan=plan,
            ai_unavailable_message=_MEMORY_RECENT_COUNT_AI_REASONING_UNAVAILABLE_MESSAGE,
            label=_MEMORY_RECENT_COUNT_SUMMARY_LABEL,
            selection_sentence=selection_sentence,
        )

    def _handle_memory_set_summary_request(
        self, raw_ids_text: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle an explicit "summarise memories <ids>" request (Phase 10,
        Batch 2).

        This is a terminal response path, the direct architectural sibling
        of _handle_memory_summary_request, generalised from one explicit id
        to a small, explicit, user-named set. It owns no memory-retrieval,
        context-construction, combination, or unexpected-action logic of its
        own - every one of those responsibilities stays inside
        ai.memory_ingestion.ingest_memories_for_ai() (Phase 10, Batch 1) or
        the existing, unmodified Phase 7 Batch 4 methods:

            1. A Plan is generated normally, exactly as for every other
               request.
            2. The raw trailing id-list text CommandRouter.match_memory_set_
               summary extracted is parsed, stably deduplicated (first-
               occurrence order preserved, never sorted), and validated here
               - _parse_memory_ids() - before anything else is attempted. An
               empty or malformed list fails honestly with no memory read,
               no audit event, and no AI ever consulted.
            3. The cardinality ceiling is enforced honestly, with a specific
               message naming the limit - never a silent "use only the
               first N".
            4. Required collaborators (AI reasoning, then the
               memory_manager) are confirmed available, each with its own
               honest failure - mirroring the singular workflow's own order.
            5. ai.memory_ingestion.ingest_memories_for_ai() performs every
               retrieval directly through MemoryManager.get(), in the
               stably-deduplicated, ordered id list handed to it - the same
               GREEN, unconditional, disclosed exception to the ToolExecutor
               gate Phase 9 already established, now for a set rather than
               one id. This method never calls MemoryManager.get() itself,
               never constructs or combines an AIContextBlock itself, and
               never reads MemoryRecord.source.
            6. One acquisition audit event is emitted per requested id
               (_audit_memory_set_acquisition), reusing the exact same
               per-id event shape _audit_memory_acquisition already
               establishes for the singular path.
            7. If no id could be included, this fails honestly with the
               ingestion result's own itemized error - the AI is never
               consulted with no usable context.
            8. On partial or full success, the one combined context_block -
               already trust-tagged and labelled from the *included* set by
               ingest_memories_for_ai - is forwarded, unchanged, into a new
               AIReasoningRequest, exactly as the singular workflow forwards
               its own single-record block.
            9. AIReasoningEngine.reason() is called exactly as it always is;
               this method has no ability to execute anything regardless of
               what the AI returns, and never calls a provider directly.
            10. Every AI-suggested action is evaluated through the existing,
                unmodified _evaluate_unexpected_actions/_audit_unexpected_
                action methods.
            11. Any requested id that was not found, could not be
                retrieved, was omitted for size, or was truncated is
                honestly, distinctly disclosed in the final response
                message (_build_memory_set_disclosure) - this disclosure
                text is Jarvis's own, built entirely from the ingestion
                result's structured accounting, and is appended only to the
                already-produced AI summary; it is never mixed into, or fed
                back into, the untrusted memory context the AI reasoned
                about.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller.

        Args:
            raw_ids_text: The raw, unparsed trailing text extracted by
                CommandRouter.match_memory_set_summary - possibly empty or
                malformed.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced from at least one genuinely retrieved memory;
            otherwise success=False with an honest explanation of which
            stage did not complete - never blocked or requiring
            confirmation, since reading memories is already GREEN and
            consulting advisory AI about already-permitted content requires
            no new approval gate.
        """
        plan = self._planner.create_plan(user_request.strip())

        memory_ids = self._parse_memory_ids(raw_ids_text)
        if memory_ids is None:
            return JarvisResponse(
                success=False,
                message=(
                    f"'{raw_ids_text}' is not a valid list of memory ids. "
                    "Please provide numeric ids separated by commas or "
                    "spaces, for example 'summarise memories 3, 7, 12'."
                ),
                plan=plan,
            )

        if len(memory_ids) > _MAX_MEMORY_SET_SIZE:
            return JarvisResponse(
                success=False,
                message=(
                    f"Too many memory ids requested ({len(memory_ids)}); "
                    f"the maximum is {_MAX_MEMORY_SET_SIZE}. Please narrow "
                    "your request."
                ),
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_SET_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._memory_manager is None:
            return JarvisResponse(
                success=False,
                message=_MEMORY_SET_MANAGER_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        ingestion = ingest_memories_for_ai(self._memory_manager, memory_ids)
        self._audit_memory_set_acquisition(ingestion, session_id)

        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not read those memories.",
                plan=plan,
            )

        return self._build_memory_summary_response(
            ingestion=ingestion,
            user_request=user_request,
            session_id=session_id,
            plan=plan,
            ai_unavailable_message=_MEMORY_SET_AI_REASONING_UNAVAILABLE_MESSAGE,
            label=_MEMORY_SET_SUMMARY_LABEL,
            selection_sentence="",
        )

    def _build_memory_summary_response(
        self,
        *,
        ingestion: MemorySetIngestionResult,
        user_request: str,
        session_id: int | None,
        plan: Plan,
        ai_unavailable_message: str,
        label: str,
        selection_sentence: str,
    ) -> JarvisResponse:
        """Build the shared post-selection AI-summary response common to
        every memory-summary workflow (Phases 10-14), reused, not
        duplicated (Retrieval Workflow Maintenance, Batch 1 - see
        docs/retrieval_workflow_maintenance_plan.md, Sections 6/7).

        Precondition, enforced by every caller, never by this method: the
        caller has already run selector invocation, selector audit,
        selector-state early returns, ingest_memories_for_ai(), and
        _audit_memory_set_acquisition() - and has already confirmed
        `ingestion.success` is True - before ever calling this method. This
        method owns none of that; it begins only at the point every
        existing handler's own post-ingestion-success tail was previously
        byte-for-byte identical (docs/retrieval_workflow_maintenance_plan.md,
        Section 4).

        Owns, in this exact order, unchanged from every handler's own
        prior inline code:
            1. AIReasoningRequest construction (user_input=user_request,
               context_block=ingestion.context, session_id=session_id -
               the same three fields, from the same three sources, every
               handler already used).
            2. self._reasoning.reason(...) - if it returns None, an honest
               failure response carrying the caller-supplied
               `ai_unavailable_message` is returned immediately; this
               method never fabricates a success in that case.
            3. Suggested-step formatting, byte-for-byte identical to every
               handler's own prior inline code.
            4. Appending `selection_sentence` - already fully resolved,
               selector-specific text the caller computed itself (this
               method never generates or infers selector-specific wording)
               - only when non-empty, so Phase 10's own "no selection
               sentence at all" behaviour is reproduced exactly by passing
               an empty string, never a placeholder or a doubled space.
            5. Appending self._build_memory_set_disclosure(ingestion) -
               the existing, unmodified Phase 10 formatter - unchanged.
            6. Constructing the final successful JarvisResponse, applying
               the caller-supplied `label` exactly as every handler
               already did.
            7. Calling self._evaluate_unexpected_actions(response, result,
               session_id) exactly once, immediately after response
               construction - the same existing, unmodified Batch 4
               policy/audit method every handler already called at this
               exact point, never skipped, never called twice.

        Does NOT own: selector invocation, selector audit, selector-state
        branching, ingest_memories_for_ai(), acquisition auditing, or the
        ingestion-success check - all of that remains visibly explicit in
        each calling handler (docs/retrieval_workflow_maintenance_plan.md,
        Section 9), because the audit-then-check sequence is a genuine
        decision boundary, not incidental repetition. Does NOT understand
        QuerySelectionResult, CategorySelectionResult, RecentSelectionResult,
        or RecentCountSelectionResult - it never receives a selector result
        of any kind, only an already-successful `ingestion` and a
        precomputed string. Does NOT receive selected ids, a MemoryManager,
        or any selector function - structurally incapable of selecting,
        reordering, or requesting additional memory. Does NOT construct,
        alter, or inspect an AIContextBlock, its trust, or its
        source/provenance - `ingestion.context` is forwarded to
        AIReasoningRequest unchanged, exactly as every handler already
        forwarded it.

        Args:
            ingestion: The result of ingest_memories_for_ai(), already
                confirmed successful by the caller.
            user_request: The original, full request text, forwarded
                unchanged into AIReasoningRequest.user_input.
            session_id: Optional session identifier for the audit trail.
            plan: The Plan already generated by the caller, carried
                through unchanged on every returned JarvisResponse.
            ai_unavailable_message: The caller's own existing
                phase-specific "AI reasoning could not produce a summary"
                constant, used unchanged if reason() returns None.
            label: The caller's own existing phase-specific advisory
                label (e.g. "[AI query-based memory summary - advisory
                only]"), applied exactly as every handler already did.
            selection_sentence: The caller's own already-formatted,
                selector-specific selection-count sentence (e.g. "Found 3
                matching memories for 'x'."), or an empty string for
                Phase 10, which has no such sentence at all.

        Returns:
            A JarvisResponse. success=True only when a real AI summary was
            produced; otherwise success=False with the caller-supplied
            `ai_unavailable_message` - never blocked or requiring
            confirmation, matching every existing handler's own contract.
        """
        reasoning_request = AIReasoningRequest(
            user_input=user_request,
            context_block=ingestion.context,
            session_id=session_id,
        )
        result = self._reasoning.reason(reasoning_request)
        if result is None:
            return JarvisResponse(
                success=False,
                message=ai_unavailable_message,
                plan=plan,
            )

        summary = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            summary = f"{result.summary} Suggested steps: {steps}"

        if selection_sentence:
            summary = f"{summary} {selection_sentence}"

        disclosure = self._build_memory_set_disclosure(ingestion)
        if disclosure:
            summary = f"{summary} {disclosure}"

        response = JarvisResponse(
            success=True,
            message=f"{label} {summary}",
            plan=plan,
        )

        # Reused, not duplicated: the exact same Batch 4 policy/audit method
        # every other request's advisory suggestion already goes through.
        self._evaluate_unexpected_actions(response, result, session_id)

        return response

    @staticmethod
    def _parse_memory_ids(raw_ids_text: str) -> tuple[int, ...] | None:
        """Parse raw trailing id-list text into a stably-deduplicated,
        ordered tuple of memory ids.

        Splits on commas and/or whitespace; every resulting token must be
        digits-only (mirroring _parse_memory_id's own strictness), or the
        whole list is rejected as invalid - never silently skipping a
        malformed token or reinterpreting it as a search query. Deduplicates
        preserving first-occurrence order (Phase 10 plan, Section 10.1):
        "27, 12, 27, 18" parses to (27, 12, 18) - records are never
        numerically sorted or otherwise reordered.

        Deliberately does NOT enforce the cardinality ceiling itself - that
        is a separate, distinctly-worded check in
        _handle_memory_set_summary_request, so a user who names too many
        otherwise-valid ids is told specifically that (naming the limit),
        rather than receiving the same generic message a malformed list
        would produce.

        Args:
            raw_ids_text: The raw, unparsed trailing text
                CommandRouter.match_memory_set_summary extracted after the
                command prefix.

        Returns:
            A stably-deduplicated, ordered tuple of ids, or None if the text
            is empty or contains any non-digit token.
        """
        tokens = raw_ids_text.replace(",", " ").split()
        if not tokens:
            return None

        ids: list[int] = []
        seen: set[int] = set()
        for token in tokens:
            if not token.isdigit():
                return None
            value = int(token)
            if value not in seen:
                seen.add(value)
                ids.append(value)

        return tuple(ids)

    @staticmethod
    def _build_memory_set_disclosure(ingestion: MemorySetIngestionResult) -> str:
        """Build an honest, itemized disclosure of any requested memory that
        did not fully enter AI context, for a multi-memory summary response.

        This text is Jarvis's own, built entirely from the ingestion
        result's already-structured accounting fields - never derived from,
        and never mixed into, the AIContextBlock the AI itself reasoned
        about. Returns an empty string when every requested id was included
        and none was truncated, since no disclosure is needed.

        Args:
            ingestion: The result of ingest_memories_for_ai().

        Returns:
            A distinctly-worded disclosure sentence per loss category
            (not-found, retrieval error, omitted for size, truncated), or
            an empty string if nothing needs disclosing.
        """
        parts: list[str] = []
        if ingestion.not_found:
            parts.append(
                "not found: " + ", ".join(str(i) for i in ingestion.not_found)
            )
        if ingestion.retrieval_errors:
            parts.append(
                "could not be retrieved: "
                + ", ".join(str(i) for i in ingestion.retrieval_errors)
            )
        if ingestion.omitted_for_size:
            parts.append(
                "omitted to stay within the combined size limit: "
                + ", ".join(str(i) for i in ingestion.omitted_for_size)
            )
        if ingestion.truncated_records:
            parts.append(
                "shortened: "
                + ", ".join(str(i) for i in ingestion.truncated_records)
            )

        if not parts:
            return ""
        return "Note: " + "; ".join(parts) + "."

    @staticmethod
    def _parse_memory_id(raw_id_text: str) -> int | None:
        """Parse a raw trailing id string into a memory id.

        Deliberately strict: only a string of digits (after stripping
        surrounding whitespace) is accepted. Missing, blank, non-numeric, or
        malformed text (including a negative sign, decimal point, or any
        embedded whitespace) is rejected as invalid, never guessed at or
        reinterpreted as a search query.

        Args:
            raw_id_text: The raw, unparsed trailing text
                CommandRouter.match_memory_summary extracted after the
                command prefix.

        Returns:
            The parsed id as a non-negative int, or None if the text is
            empty or is not made up entirely of digits.
        """
        text = raw_id_text.strip()
        if not text.isdigit():
            return None
        return int(text)

    def _audit_memory_acquisition(
        self,
        ingestion: MemoryIngestionResult,
        memory_id: int,
        session_id: int | None,
    ) -> None:
        """Record the single-memory acquisition outcome (Phase 9, Batch 2).

        This is the explicit, disclosed replacement for the free tool_call
        audit event ToolExecutor would have produced had this path gone
        through it (Phase 9 plan, Section 15) - acquisition here goes
        directly through MemoryManager.get(), which emits nothing on its own.

        Delegates its actual event emission to _emit_memory_acquisition_event
        (Phase 10, Batch 2 compatibility-preserving refactor) - the event
        shape (source, action_type, detail format, security_tier, and the
        outcome/detail mapping) is byte-for-byte unchanged from before that
        refactor, proven by this method's own pre-existing Phase 9 tests
        continuing to pass unchanged.

        Args:
            ingestion: The result of ingest_memory_for_ai().
            memory_id: The id that was requested.
            session_id: Optional session identifier for the event.
        """
        outcome = EventOutcome.SUCCESS if ingestion.success else EventOutcome.FAILURE
        self._emit_memory_acquisition_event(
            outcome=outcome,
            memory_id=memory_id,
            truncated=ingestion.truncated,
            session_id=session_id,
        )

    def _audit_memory_set_acquisition(
        self,
        ingestion: MemorySetIngestionResult,
        session_id: int | None,
    ) -> None:
        """Record one memory-acquisition audit event per requested id, for
        the multi-memory workflow (Phase 10, Batch 2).

        Reuses the exact same per-id event shape _audit_memory_acquisition
        already established for the singular path, via the shared
        _emit_memory_acquisition_event helper - never a duplicated or
        parallel audit mechanism. `included` ids are audited as SUCCESS
        (with their own truncated flag); `not_found`, `retrieval_errors`,
        and `omitted_for_size` ids are each audited as FAILURE, with a
        `reason` naming which of the three applies, so a reviewer can tell
        them apart in the audit trail without embedding raw content.

        Args:
            ingestion: The result of ingest_memories_for_ai().
            session_id: Optional session identifier for each event.
        """
        for memory_id in ingestion.included:
            self._emit_memory_acquisition_event(
                outcome=EventOutcome.SUCCESS,
                memory_id=memory_id,
                truncated=memory_id in ingestion.truncated_records,
                session_id=session_id,
            )
        for memory_id in ingestion.not_found:
            self._emit_memory_acquisition_event(
                outcome=EventOutcome.FAILURE,
                memory_id=memory_id,
                truncated=False,
                session_id=session_id,
                reason="not_found",
            )
        for memory_id in ingestion.retrieval_errors:
            self._emit_memory_acquisition_event(
                outcome=EventOutcome.FAILURE,
                memory_id=memory_id,
                truncated=False,
                session_id=session_id,
                reason="retrieval_error",
            )
        for memory_id in ingestion.omitted_for_size:
            self._emit_memory_acquisition_event(
                outcome=EventOutcome.FAILURE,
                memory_id=memory_id,
                truncated=False,
                session_id=session_id,
                reason="omitted_for_size",
            )

    def _audit_memory_query_selection(
        self,
        selection: QuerySelectionResult,
        session_id: int | None,
    ) -> None:
        """Record the query-based selection outcome (Phase 11, Batch 2).

        A new, narrow, non-authoritative audit event distinct from Phase
        10's per-id memory_acquisition events: this one describes the
        search step itself (was a search attempted, what was its outcome,
        how many ids did it select) exactly once per query-based request,
        never repeating information the subsequent per-id acquisition
        events already carry during ingestion
        (docs/phase_11_implementation_plan.md, Section 12.2/13).

        Never embeds the raw query text - only its length
        (`selection.query_length`), mirroring
        ai/prompt_builder.py's audit_suspicious_injection convention of
        logging text_length rather than the text itself. `success` and
        `zero_matches` are distinguished from a genuine `failed` search by
        an `outcome=` field inside detail, not by a new EventOutcome
        member: both `zero_matches` and `failed` map to the existing
        EventOutcome.FAILURE value, mirroring how
        _emit_memory_acquisition_event already distinguishes not_found/
        retrieval_error/omitted_for_size failures via a `reason=` field
        inside one shared FAILURE outcome.

        When no logger is configured, this is a no-op, matching every
        other optional-audit call site in this class. A raising logger is
        caught here, scoped only around the emit() call itself, so a
        failing audit event can never break the authoritative selection
        outcome, the subsequent Phase 10 ingestion, or the AI reasoning
        result already computed or about to be computed - the same
        precedent as AIRouter._emit_audit_event and
        _emit_memory_acquisition_event.

        Args:
            selection: The result of select_memory_ids_by_query().
            session_id: Optional session identifier for the event.
        """
        if self._logger is None:
            return

        if selection.success:
            outcome = EventOutcome.SUCCESS
            outcome_label = "success"
        elif selection.zero_matches:
            outcome = EventOutcome.FAILURE
            outcome_label = "zero_matches"
        else:
            outcome = EventOutcome.FAILURE
            outcome_label = "failure"

        detail = (
            f"outcome={outcome_label} query_length={selection.query_length} "
            f"match_count={len(selection.selected_ids)} "
            f"selected_ids={','.join(str(i) for i in selection.selected_ids)}"
        )

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_MEMORY_QUERY_SELECTION_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                security_tier=SecurityTier.GREEN,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative query-based memory-summary workflow
            # already in progress - same precedent as
            # _emit_memory_acquisition_event and AIRouter._emit_audit_event.
            pass

    def _audit_memory_category_selection(
        self,
        selection: CategorySelectionResult,
        session_id: int | None,
    ) -> None:
        """Record the category-based selection outcome (Phase 12, Batch 2).

        A new, narrow, non-authoritative audit event distinct from Phase
        10's per-id memory_acquisition events: this one describes the
        category-lookup step itself (was a lookup attempted, what was its
        outcome, how many/which ids did it select) exactly once per
        category-based request, never repeating information the
        subsequent per-id acquisition events already carry during
        ingestion (docs/phase_12_implementation_plan.md, Section 12/15).

        Unlike _audit_memory_query_selection, the category value itself is
        logged directly - via `selection.category` - whenever one was
        actually established (`success`, `zero_records`, and `failure`
        alike), because categories are a small, fixed, non-sensitive
        vocabulary, never arbitrary free text (docs/phase_12_
        implementation_plan.md, Section 6/12). For `invalid_category`,
        `selection.category` is always None (enforced by
        CategorySelectionResult's own construction invariant), so the
        `category=` field is omitted entirely from the detail string -
        never the raw, unvalidated input, and never a fabricated
        "general" value.

        `success`, `zero_records`, `invalid_category`, and `failure` are
        distinguished via an `outcome=` field inside detail, not by new
        EventOutcome members: `zero_records`, `invalid_category`, and a
        genuine lookup exception all map to the existing
        EventOutcome.FAILURE value, mirroring how
        _emit_memory_acquisition_event already distinguishes not_found/
        retrieval_error/omitted_for_size failures via a `reason=` field
        inside one shared FAILURE outcome.

        When no logger is configured, this is a no-op, matching every
        other optional-audit call site in this class. A raising logger is
        caught here, scoped only around the emit() call itself, so a
        failing audit event can never break the authoritative selection
        outcome (including invalid-category rejection), the subsequent
        Phase 10 ingestion, or the AI reasoning result already computed or
        about to be computed - the same precedent as
        _audit_memory_query_selection, _emit_memory_acquisition_event, and
        AIRouter._emit_audit_event.

        Args:
            selection: The result of select_memory_ids_by_category().
            session_id: Optional session identifier for the event.
        """
        if self._logger is None:
            return

        if selection.success:
            outcome = EventOutcome.SUCCESS
            outcome_label = "success"
        elif selection.invalid_category:
            outcome = EventOutcome.FAILURE
            outcome_label = "invalid_category"
        elif selection.zero_matches:
            outcome = EventOutcome.FAILURE
            outcome_label = "zero_records"
        else:
            outcome = EventOutcome.FAILURE
            outcome_label = "failure"

        detail = f"outcome={outcome_label}"
        if selection.category is not None:
            detail += f" category={selection.category}"
        detail += (
            f" match_count={len(selection.selected_ids)} "
            f"selected_ids={','.join(str(i) for i in selection.selected_ids)}"
        )

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_MEMORY_CATEGORY_SELECTION_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                security_tier=SecurityTier.GREEN,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative category-based memory-summary workflow
            # already in progress - same precedent as
            # _audit_memory_query_selection and AIRouter._emit_audit_event.
            pass

    def _audit_memory_recent_selection(
        self,
        selection: RecentSelectionResult,
        session_id: int | None,
    ) -> None:
        """Record the recency-based selection outcome (Phase 13, Batch 2).

        A new, narrow, non-authoritative audit event distinct from Phase
        10's per-id memory_acquisition events: this one describes the
        recency-lookup step itself (was a lookup attempted, what was its
        outcome, how many/which ids did it select) exactly once per
        recent-memory request, never repeating information the subsequent
        per-id acquisition events already carry during ingestion
        (docs/phase_13_implementation_plan.md, Section 13/15).

        Unlike _audit_memory_query_selection (which logs `query_length`)
        and _audit_memory_category_selection (which logs `category`), this
        event carries no criterion-describing field at all: recency
        selection takes no caller-supplied criterion beyond the fixed
        selection ceiling, so there is nothing else here to log. No
        `requested_count=` field is added either - the ceiling (10) is a
        fixed, code-level constant with no per-request variance, so
        logging it on every single event would be a constant, redundant
        value carrying no review-time information (docs/phase_13_
        implementation_plan.md, Section 13).

        `success` and `zero_matches` are distinguished from a genuine
        `failed` lookup by an `outcome=` field inside detail, not by a new
        EventOutcome member: both `zero_matches` and `failed` map to the
        existing EventOutcome.FAILURE value, mirroring
        _audit_memory_query_selection's own convention.

        When no logger is configured, this is a no-op, matching every
        other optional-audit call site in this class. A raising logger is
        caught here, scoped only around the emit() call itself, so a
        failing audit event can never break the authoritative selection
        outcome, the subsequent Phase 10 ingestion, or the AI reasoning
        result already computed or about to be computed - the same
        precedent as _audit_memory_query_selection,
        _audit_memory_category_selection, and AIRouter._emit_audit_event.

        Args:
            selection: The result of select_recent_memory_ids().
            session_id: Optional session identifier for the event.
        """
        if self._logger is None:
            return

        if selection.success:
            outcome = EventOutcome.SUCCESS
            outcome_label = "success"
        elif selection.zero_matches:
            outcome = EventOutcome.FAILURE
            outcome_label = "zero_records"
        else:
            outcome = EventOutcome.FAILURE
            outcome_label = "failure"

        detail = (
            f"outcome={outcome_label} "
            f"match_count={len(selection.selected_ids)} "
            f"selected_ids={','.join(str(i) for i in selection.selected_ids)}"
        )

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_MEMORY_RECENT_SELECTION_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                security_tier=SecurityTier.GREEN,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative recent-memory-summary workflow already in
            # progress - same precedent as _audit_memory_category_selection
            # and AIRouter._emit_audit_event.
            pass

    def _audit_memory_recent_count_selection(
        self,
        selection: RecentCountSelectionResult,
        session_id: int | None,
    ) -> None:
        """Record the count-based recency-selection outcome (Phase 14,
        Batch 2).

        A new, narrow, non-authoritative audit event distinct from Phase
        13's own memory_recent_selection event and from Phase 10's per-id
        memory_acquisition events: this one describes the count-lookup
        step itself (was a lookup attempted, what was its outcome, how
        many/which ids did it select) exactly once per count-based
        request, never repeating information the subsequent per-id
        acquisition events already carry during ingestion
        (docs/phase_14_implementation_plan.md, Section 8).

        Unlike _audit_memory_recent_selection (which carries no criterion
        field at all, since the fixed Phase 13 command takes none), this
        event does carry `requested_count` directly - via
        `selection.requested_count` - whenever one was actually
        established (`success`, `zero_records`, and `failure` alike),
        because a validated count is always a small, bounded integer
        (1-10), never arbitrary or sensitive free text (Phase 14 plan,
        Section 8). For `invalid_count`, `selection.requested_count` is
        always None (enforced by RecentCountSelectionResult's own
        construction invariant), so the `requested_count=` field is
        omitted entirely from the detail string - never the raw,
        unvalidated input, and never a fabricated value.

        `success`, `zero_matches`, `invalid_count`, and `failed` are
        distinguished via an `outcome=` field inside detail, not by new
        EventOutcome members: `zero_matches`, `invalid_count`, and a
        genuine lookup exception all map to the existing
        EventOutcome.FAILURE value, mirroring
        _audit_memory_category_selection's own four-state convention.

        When no logger is configured, this is a no-op, matching every
        other optional-audit call site in this class. A raising logger is
        caught here, scoped only around the emit() call itself, so a
        failing audit event can never break the authoritative selection
        outcome (including invalid-count rejection), the subsequent Phase
        10 ingestion, or the AI reasoning result already computed or about
        to be computed - the same precedent as
        _audit_memory_recent_selection, _audit_memory_category_selection,
        and AIRouter._emit_audit_event.

        Args:
            selection: The result of select_recent_memory_ids_by_count().
            session_id: Optional session identifier for the event.
        """
        if self._logger is None:
            return

        if selection.success:
            outcome = EventOutcome.SUCCESS
            outcome_label = "success"
        elif selection.invalid_count:
            outcome = EventOutcome.FAILURE
            outcome_label = "invalid_count"
        elif selection.zero_matches:
            outcome = EventOutcome.FAILURE
            outcome_label = "zero_records"
        else:
            outcome = EventOutcome.FAILURE
            outcome_label = "failure"

        detail = f"outcome={outcome_label}"
        if selection.requested_count is not None:
            detail += f" requested_count={selection.requested_count}"
        detail += (
            f" match_count={len(selection.selected_ids)} "
            f"selected_ids={','.join(str(i) for i in selection.selected_ids)}"
        )

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_MEMORY_RECENT_COUNT_SELECTION_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                security_tier=SecurityTier.GREEN,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative count-based recent-memory-summary workflow
            # already in progress - same precedent as
            # _audit_memory_recent_selection and AIRouter._emit_audit_event.
            pass

    def _emit_memory_acquisition_event(
        self,
        *,
        outcome: EventOutcome,
        memory_id: int,
        truncated: bool,
        session_id: int | None,
        reason: str | None = None,
    ) -> None:
        """Emit one memory_acquisition audit event for a single id, if a
        logger is configured.

        Shared by both the Phase 9 singular memory-summary path
        (_audit_memory_acquisition) and the Phase 10 plural path
        (_audit_memory_set_acquisition) - factored out here as the approved
        compatibility-preserving internal refactor
        (docs/phase_10_implementation_plan.md, Section 17, Batch 2). The
        singular caller never passes `reason`, so its own detail string is
        byte-for-byte identical to before this refactor:
        "memory_id=<id> outcome=<outcome>" (plus " truncated=<bool>" on
        success) - proven by Phase 9's own pre-existing audit tests passing
        unchanged. The plural caller passes `reason` only for its three
        distinct FAILURE categories, itemizing why without embedding raw
        content.

        When no logger is configured, this is a no-op, matching how every
        other optional-audit call site in this class behaves without one.
        A raising logger is caught here, per call, so one id's failing
        audit event can never break the authoritative workflow already in
        progress, and - in the plural case - never prevents any other id's
        own audit event, or the overall reasoning result, from being
        recorded or returned normally.

        Never embeds raw memory content, the AI-facing truncation notice
        text, or any historical user instruction in the audit detail - only
        the requested memory id, the outcome, and (when acquisition
        succeeded) whether truncation occurred. Makes no claim of session
        isolation or authorization enforcement: memory retrieval by id
        remains the same unscoped-by-id lookup it already is (Phase 9 plan,
        Sections 6, 12, 21).

        Args:
            outcome: The acquisition outcome for this specific id.
            memory_id: The id this event describes.
            truncated: Whether this id's content was truncated. Only
                embedded in the detail when outcome is SUCCESS.
            session_id: Optional session identifier for the event.
            reason: Optional, short machine-readable reason embedded in the
                detail only when outcome is not SUCCESS. None (the default)
                preserves the exact singular-path detail format with no
                reason segment at all.
        """
        if self._logger is None:
            return

        detail = f"memory_id={memory_id} outcome={outcome.value}"
        if outcome is EventOutcome.SUCCESS:
            detail += f" truncated={truncated}"
        elif reason is not None:
            detail += f" reason={reason}"

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_MEMORY_ACQUISITION_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                security_tier=SecurityTier.GREEN,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative memory-summary workflow already in
            # progress - same precedent as _audit_unexpected_action
            # (Phase 7, Batch 4) and PromptBuilder's report_injection guard
            # (Phase 7, Batch 5A). Scoped per-call, per-id: one failing
            # event never prevents another id's own event, or the caller's
            # loop, from continuing normally.
            pass

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

        Every suggested action is also evaluated against the response's plan
        for the unexpected-action policy (Phase 7, Batch 4), purely for
        observability - see _evaluate_unexpected_actions. That evaluation
        never influences the returned response.

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

        self._evaluate_unexpected_actions(response, result, session_id)

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

    def _evaluate_unexpected_actions(
        self,
        response: JarvisResponse,
        result: AIReasoningResult,
        session_id: int | None,
    ) -> None:
        """Evaluate every AI-suggested action for the unexpected-action policy.

        This is purely for policy evaluation and observability (Phase 7,
        Batch 4). It never converts a suggestion into a ToolRequest, never
        executes or approves anything, never changes response, and never
        changes the Plan or a SecurityTier - it only computes a verdict and,
        if a logger is configured, records it.

        The expected scope for this request is the set of action strings the
        Planner already produced: frozenset(step.action for step in
        response.plan.steps). response.plan can be None (the empty-request
        path), in which case nothing is expected and every suggestion is
        evaluated as unexpected.

        Args:
            response: The authoritative response already produced by the
                rule-based path, carrying the plan to compare against.
            result: The AI reasoning result whose suggested actions are
                evaluated.
            session_id: Optional session identifier for the audit event.
        """
        if not result.has_suggestions:
            return

        expected_actions: frozenset[str] = (
            frozenset(step.action for step in response.plan.steps)
            if response.plan is not None
            else frozenset()
        )

        for suggested in result.suggested_actions:
            try:
                decision = self._security.evaluate_unexpected_action(
                    suggested.description, expected_actions
                )
            except ValueError:
                # An AI suggestion with blank description text has nothing
                # meaningful to evaluate; never let a malformed suggestion
                # break response construction.
                continue

            if decision is None:
                continue

            self._audit_unexpected_action(decision, session_id)

    def _audit_unexpected_action(
        self, decision: UnexpectedActionDecision, session_id: int | None
    ) -> None:
        """Record an unexpected-action verdict, if a logger is configured.

        When no logger is configured, this is a no-op, matching how
        ApprovalManager behaves without an audit_logger. This evaluation and
        audit are observability-only (Phase 7, Batch 4): a logger that raises
        must never break response construction, change the already-decided
        JarvisResponse, or grant the AI any new authority - the worst a
        failing logger can do is mean this one audit event was not recorded.

        Args:
            decision: The verdict to record.
            session_id: Optional session identifier for the event.
        """
        if self._logger is None:
            return

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_UNEXPECTED_ACTION_TYPE,
                outcome=_UNEXPECTED_ACTION_OUTCOME[decision.verdict],
                detail=(
                    f"action={decision.action!r} verdict={decision.verdict.value} "
                    f"tier={decision.tier.value} reason={decision.reason}"
                ),
                security_tier=decision.tier,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break the
            # authoritative response that was already decided by the
            # rule-based path. There is nothing else safe to do with the
            # failure here - Batch 4 does not introduce a parallel logging
            # system to record it elsewhere.
            pass

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
