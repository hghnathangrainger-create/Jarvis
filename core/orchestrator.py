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
from typing import Callable, Protocol

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
from ai.router import AIRouter
from ai.web_search_ingestion import ingest_web_search_for_ai
from ai.webpage_ingestion import ingest_webpage_for_ai
from config.constants import EventOutcome, SecurityTier, StepStatus
from core.command_router import CommandRouter
from core.request_models import JarvisRequest, JarvisResponse, WorkflowTraceStep
from inbox.inbox_store import InboxStore
from intelligence.capability_catalog import (
    CAPABILITY_CATALOG,
    CapabilityId,
    ExecutionStrategy,
)
from intelligence.context import ContextAssembler, build_ai_context_block
from intelligence.grounding import UngroundedReason
from intelligence.planning import (
    UNSUPPORTED_CAPABILITY_MESSAGE,
    PlanningOutcome,
    PlanningOutcomeKind,
    select_tool,
)
from intelligence.verification import (
    SCHEDULE_DISABLED_EXACT_MATCH_VERIFIER_ID,
    SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID,
    VerificationOutcome,
    verify_focus_update,
    verify_schedule_enabled_state,
)
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
from tools.web_search_provider import WebSearchProvider
from workflow.engine import WorkflowEngine
from workflow.workflow_models import WorkflowResult
from workflow.workflow_plan_factory import (
    build_create_and_read_plan,
    build_file_search_and_copy_plan,
    build_remember_and_forget_plan,
    build_remember_and_show_plan,
    build_update_and_show_plan,
)


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

#: Advisory label for a web-search-summary response's message (Phase 18,
#: Batch 2). Distinct from _FILE_SUMMARY_LABEL for the same reason that
#: label is distinct from _attach_ai_suggestion's own annotation label -
#: and its own wording explicitly, unconditionally discloses that the
#: synthesis is based on search-result snippets, not full webpage
#: content. This label is the code-enforced honesty guarantee
#: (docs/phase_18_implementation_plan.md, Section 12): it is applied to
#: every successful response regardless of the AI's own wording.
_WEB_SEARCH_SUMMARY_LABEL = (
    "[AI web search summary - based on search-result snippets, not full "
    "webpages]"
)
#: A sixth, independently-declared message pair, matching the already-
#: established, already-reviewed per-summary-family convention (five
#: prior copies already exist: the file-summary pair above, and four
#: memory-summary-family pairs below) rather than reusing the file-
#: summary pair's own file-specific wording, which would be factually
#: wrong for a web-search request. Centralising all six copies remains
#: the same disclosed, deferred maintenance-turn candidate already
#: identified in docs/phase_14_completion_report.md - not fixed here.
_WEB_SEARCH_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these web search results."
)
_WEB_SEARCH_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for these web search results right now."
)

#: Advisory label for a webpage-summary response's message (Phase 34,
#: Batch 2). Mirrors _WEB_SEARCH_SUMMARY_LABEL's own code-enforced
#: honesty guarantee: applied to every successful response regardless
#: of the AI's own wording, so it is always clear this is a synthesis
#: of one page's extracted text, not the raw page itself.
_WEBPAGE_SUMMARY_LABEL = "[AI webpage summary - based on extracted page text]"
#: A seventh, independently-declared message pair, matching the
#: already-established, already-reviewed per-summary-family convention
#: noted above rather than reusing another family's wording, which
#: would be factually wrong for a webpage request. Centralising all
#: seven copies remains the same disclosed, deferred maintenance-turn
#: candidate already identified in docs/phase_14_completion_report.md -
#: not fixed here, per Phase 34 Batch 2's explicit instruction not to
#: perform a broad orchestrator refactor.
_WEBPAGE_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise this webpage."
)
_WEBPAGE_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce a summary for this webpage right now."
)

#: Advisory label for an "ask jarvis: <request>" response's message
#: (Phase 90, Batch 1). Distinct from every other summary label for the
#: same reason each of those is distinct from the others: this marks a
#: response whose entire content *is* the AI's own advisory output about
#: a bounded, automatically-assembled context (memory + manually-recorded
#: ProjectState), not an annotation appended to an already-decided
#: response, and not a file/memory/web-search/webpage summary of a
#: single, explicitly-named source.
_ASK_JARVIS_LABEL = "[AI advisory response - based on automatically assembled context]"
_ASK_JARVIS_EMPTY_REQUEST_MESSAGE = (
    "Please include what you'd like to ask after 'ask jarvis:'"
)
_ASK_JARVIS_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't answer this request."
)
_ASK_JARVIS_AI_REASONING_UNAVAILABLE_MESSAGE = (
    "AI reasoning could not produce an answer for this request right now."
)
_ASK_JARVIS_CONTEXT_NOT_AVAILABLE_MESSAGE = (
    "Context assembly is not available, so I can't answer this request."
)

#: Fixed label for a successful "ask jarvis to: <request>" execution
#: (Phase 90, Batch 2) - the code-enforced honesty guarantee that the
#: substantive content is the real ToolResult.output, never an AI
#: paraphrase of it, mirroring _ASK_JARVIS_LABEL's own convention.
_ASK_JARVIS_TO_LABEL = "[Jarvis tool result]"
_ASK_JARVIS_TO_EMPTY_REQUEST_MESSAGE = (
    "Please include what you'd like Jarvis to do after 'ask jarvis to:'"
)
_ASK_JARVIS_TO_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so Jarvis can't select a tool for this request."
)
_ASK_JARVIS_TO_CONTEXT_NOT_AVAILABLE_MESSAGE = (
    "Context assembly is not available, so Jarvis can't select a tool for this "
    "request."
)
_ASK_JARVIS_TO_PROVIDER_UNAVAILABLE_MESSAGE = (
    "Jarvis's AI provider is not available right now, so it can't select a "
    "tool for this request."
)
_ASK_JARVIS_TO_PROVIDER_FAILED_MESSAGE = (
    "Jarvis's AI provider could not process this request right now."
)
_ASK_JARVIS_TO_INVALID_OUTPUT_PREFIX = "Jarvis could not safely process that request:"
#: Phase 92, Batch 2: the two public refusal messages for
#: PlanningOutcomeKind.UNGROUNDED_SELECTION (intelligence.grounding.
#: ground_decision()). Neither ever exposes the bounded internal
#: UngroundedReason code, the live request, a candidate argument span,
#: or a rejected/candidate value - each is a short, fixed, generic
#: sentence asking for a direct restatement, exactly like every other
#: outcome kind's own fixed message.
#:
#: _ASK_JARVIS_TO_ACTION_SELECTION_REFUSAL_MESSAGE covers the reasons
#: where the request itself could not be tied to exactly one supported
#: action: no signature matched, more than one signature matched, or
#: the uniquely-grounded capability differed from the model's
#: selection (see _ACTION_SELECTION_UNGROUNDED_REASONS below).
_ASK_JARVIS_TO_ACTION_SELECTION_REFUSAL_MESSAGE = (
    "Jarvis could not safely match that request to one supported action, so "
    "nothing was run. Please restate exactly what you'd like Jarvis to do."
)
#: _ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE covers the reasons
#: where the action itself was recognisable but the exact request or
#: argument value could not be safely confirmed: a negated or
#: conflicting request, a missing or ambiguous argument span, or a
#: model-supplied value that did not exactly match the request (all
#: remaining UngroundedReason members, by construction - see
#: _ACTION_SELECTION_UNGROUNDED_REASONS below).
_ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE = (
    "Jarvis could not safely confirm the exact request or value, so nothing "
    "was run. Please restate it directly and exactly."
)
#: The subset of UngroundedReason values mapped to the action-selection
#: message above; every other member (checked exhaustively against the
#: real enum by a structural test) maps to the exact-request message.
_ACTION_SELECTION_UNGROUNDED_REASONS = frozenset(
    {
        UngroundedReason.NO_SIGNATURE_MATCHED.value,
        UngroundedReason.MULTIPLE_SIGNATURES_MATCHED.value,
        UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH.value,
    }
)


def _ask_jarvis_to_ungrounded_message(detail: str | None) -> str:
    """Maps an UNGROUNDED_SELECTION outcome's bounded `detail` string to
    one of exactly two public refusal messages (Phase 92, Batch 2) -
    never a per-reason message, and never the raw detail itself."""
    if detail in _ACTION_SELECTION_UNGROUNDED_REASONS:
        return _ASK_JARVIS_TO_ACTION_SELECTION_REFUSAL_MESSAGE
    return _ASK_JARVIS_TO_EXACT_REQUEST_REFUSAL_MESSAGE
#: Phase 90, Batch 3: the update-focus-and-verify workflow requires a
#: real, configured WorkflowEngine - unlike Batch 2's project_state_show
#: path, which only needs ToolExecutor.
_ASK_JARVIS_TO_WORKFLOW_NOT_AVAILABLE_MESSAGE = (
    "Workflow execution is not available, so Jarvis can't safely update "
    "the project focus for this request."
)
#: Shown only if the first WorkflowEngine.run() call for the update-
#: focus workflow does not pause for approval, even though preflight
#: required exactly YELLOW - a genuine execution-time safety mismatch
#: (Batch 3 planning prompt). Never shown for an ordinary tool failure.
_ASK_JARVIS_TO_SAFETY_MISMATCH_MESSAGE = (
    "Jarvis refused this update: the safety check that should have "
    "required your approval did not behave as expected, so nothing was "
    "changed."
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
#: Shared AI-reasoning availability messages for the multi-memory-summary
#: family (Phase 10-14; Retrieval Workflow Maintenance, Batch 2). These five
#: workflows share one meaning - a stored-memory-set summary could not be
#: produced because AI reasoning is disabled or unavailable - previously
#: five byte-identical, independently-declared copies (one per handler);
#: this is now the sole authority for both messages, referenced from Phase
#: 10 (memory set), Phase 11 (query), Phase 12 (category), Phase 13
#: (recent), and Phase 14 (recent-count). Deliberately does not cover Phase
#: 8's file-summary message or Phase 9's own singular memory-summary
#: message (_AI_REASONING_*/_MEMORY_AI_REASONING_*): both are worded for a
#: single file/memory ("this file's"/"this memory's contents"), not a set
#: ("these memories' contents"), so they are separate messages for a
#: separate workflow shape, not further copies of this one.
_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE = (
    "AI reasoning is not enabled, so I can't summarise these memories' contents."
)
_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE = (
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
#: Uses the shared _MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE /
#: _MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE (declared with Phase
#: 10's own constants above) - not a separate copy (Retrieval Workflow
#: Maintenance, Batch 2).
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
#: Uses the shared _MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE /
#: _MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE (declared with Phase
#: 10's own constants above) - not a separate copy (Retrieval Workflow
#: Maintenance, Batch 2).
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
#: Uses the shared _MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE /
#: _MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE (declared with Phase
#: 10's own constants above) - not a separate copy (Retrieval Workflow
#: Maintenance, Batch 2).
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
#: Previously a fifth, independently-declared copy of the same wording
#: every other memory-summary workflow already used for these two messages
#: (docs/phase_14_implementation_plan.md, Section 12); now uses the shared
#: _MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE /
#: _MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE (declared with Phase
#: 10's own constants above) - Retrieval Workflow Maintenance, Batch 2.
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
        workflow_engine: WorkflowEngine | None = None,
        web_search_provider: WebSearchProvider | None = None,
        inbox_store: InboxStore | None = None,
        logger: _AuditLogger | None = None,
        context_assembler: ContextAssembler | None = None,
        tool_selection_router: AIRouter | None = None,
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
            workflow_engine: An optional WorkflowEngine, used only by the two
                explicit Phase 15 workflow commands ("remember this and show
                it back: <text>" / "remember this and forget it: <text>",
                Batch 3). No new instance is ever created here if omitted -
                like memory_manager, a WorkflowEngine requires real
                collaborators of its own, so there is no safe stateless
                default; when omitted, workflow commands fail honestly
                instead. Every existing construction site that omits this
                parameter continues to behave exactly as before Phase 15.
            web_search_provider: An optional WebSearchProvider, used only
                by the explicit "summarise web search for <query>"
                AI-summary workflow (Phase 18, Batch 2). Never invoked
                through WebSearchTool or ToolExecutor - this workflow
                calls search() directly, mirroring memory_manager's own
                established precedent. No new instance is ever created
                here if omitted; when omitted, web-search-summary
                requests fail honestly instead. Every existing
                construction site that omits this parameter continues to
                behave exactly as before Phase 18.
            inbox_store: An optional InboxStore, used only to save a
                durable copy of a successfully-produced "summarise web
                search for <query>" advisory summary (Phase 20, Batch 2).
                Purely additive: the write happens only after the exact
                same success JarvisResponse this method already returns
                has been built, and a failed write never changes,
                delays, or blocks that response. No new instance is ever
                created here if omitted; when omitted, the command
                behaves exactly as it did before Phase 20 - no entry is
                ever saved, but nothing else changes.
            logger: Optional audit logger for the unexpected-action verdict.
                The verdict is always evaluated; when logger is omitted,
                nothing is recorded, matching how approval_manager behaves
                without an audit_logger.
            context_assembler: An optional ContextAssembler, used only by
                the explicit "ask jarvis: <request>" Context Intelligence
                workflow (Phase 90, Batch 1) to automatically assemble
                bounded memory + ProjectState context. No new instance is
                ever created here if omitted - like memory_manager, it
                requires real collaborators of its own, so there is no
                safe stateless default; when omitted, "ask jarvis:"
                requests fail honestly instead.
            tool_selection_router: An optional, already-constructed
                AIRouter, used only by the explicit "ask jarvis to:
                <request>" tool-intent workflow (Phase 90, Batch 2) to
                select at most one allowlisted GREEN capability. This is
                deliberately the same real AIRouter instance main.py
                already builds for reasoning_engine when AI reasoning is
                enabled - never a second instance - passed directly
                because AIReasoningEngine.reason() hardcodes one shared
                system instruction with no field for this call's own
                trusted planning instruction (Section 26.C). When
                omitted (AI reasoning disabled, mirroring
                reasoning_engine's own None-when-disabled convention),
                "ask jarvis to:" requests fail honestly instead of
                calling any provider.
        """
        self._planner = planner
        self._executor = executor
        self._registry = registry
        self._command_router = command_router
        self._approvals = approval_manager or ApprovalManager()
        self._reasoning = reasoning_engine
        self._security = security_manager or SecurityManager()
        self._memory_manager = memory_manager
        self._workflow_engine = workflow_engine
        self._web_search_provider = web_search_provider
        self._inbox_store = inbox_store
        self._logger = logger
        self._context_assembler = context_assembler
        self._tool_selection_router = tool_selection_router

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

        Phase 15, Batch 3: if `response` carries the approval request for a
        step paused by a Phase 15 workflow, this delegates to
        WorkflowEngine.resume() instead of re-running a single tool - the
        public signature of this method is unchanged, and every non-workflow
        call site behaves exactly as before. This method never records the
        approval decision itself in either case: by the time it is called,
        the caller (the CLI, via self.approvals.approve()/decline()) has
        already recorded it - execute_approved only ever acts on an
        already-decided ApprovalDecision.

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
        workflow_id = self._paused_workflow_id_for(response)
        if workflow_id is not None:
            result = self._workflow_engine.resume(
                workflow_id,
                decision,
                session_id=(
                    response.approval_request.session_id
                    if response.approval_request is not None
                    else None
                ),
            )
            # Phase 90, Batch 3; generalized Phase 94, Batch 2: each real
            # verified-workflow shape is recognised purely structurally
            # (no new persisted marker, per Section 24.C.12) - never
            # mistaken for any of the five pre-existing fixed Phase 15
            # workflows, whose own tool names never match either pair.
            return self._translate_verified_workflow_result(result)

        if self._is_pending_webpage_summary(response):
            return self._execute_approved_webpage_summary(response, decision)

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

    def _paused_workflow_id_for(self, response: JarvisResponse) -> str | None:
        """Return the workflow id response's approval request is paused on,
        if any (Phase 15, Batch 3).

        Uses only the existing ApprovalRequest.metadata mechanism - no new
        field is added anywhere. Treats metadata as untrusted: a missing,
        empty, or malformed "workflow_id" entry, or one that does not
        correspond to a workflow this engine instance actually has paused
        right now, is never treated as workflow-linked. This is what
        prevents an unrelated approval that happens to carry workflow-like
        metadata, or a stale/already-resumed workflow id, from redirecting
        execution anywhere.

        Args:
            response: The response being resumed via execute_approved().

        Returns:
            The workflow id, only if self._workflow_engine is configured,
            response.approval_request is present, its metadata names a
            non-empty "workflow_id", and that id is currently paused.
            None otherwise.
        """
        if self._workflow_engine is None:
            return None
        if response.approval_request is None:
            return None

        workflow_id = response.approval_request.metadata.get("workflow_id")
        if not workflow_id:
            return None
        if not self._workflow_engine.has_paused(workflow_id):
            return None
        return workflow_id

    @staticmethod
    def _is_pending_webpage_summary(response: JarvisResponse) -> bool:
        """Return whether response is a pending "summarize webpage" approval.

        Uses only the existing ApprovalRequest.metadata mechanism (Phase
        34, Batch 2), mirroring _paused_workflow_id_for's own narrow,
        defensive discriminator pattern exactly: a missing or unrelated
        metadata entry is never treated as a webpage-summary approval,
        which is what prevents an unrelated approval that happens to
        carry a same-shaped metadata key from being misrouted into the
        AI-summarization continuation below.

        Args:
            response: The response being resumed via execute_approved().

        Returns:
            True only if response.approval_request is present and its
            metadata's "webpage_summary" entry is exactly "true". False
            otherwise.
        """
        if response.approval_request is None:
            return False
        return response.approval_request.metadata.get("webpage_summary") == "true"

    @staticmethod
    def _should_save_webpage_summary_to_inbox(response: JarvisResponse) -> bool:
        """Return whether a pending webpage-summary approval should save
        its resulting summary to the Inbox once it succeeds (Phase 61,
        Batch 1).

        Mirrors _is_pending_webpage_summary's own narrow, defensive
        discriminator pattern exactly: a missing or unrelated metadata
        entry is never treated as an instruction to save. Only the
        explicit "... and save to inbox" grammar
        (match_webpage_summary_and_save) ever sets this key when the
        approval request was created - the plain "summarize webpage
        <url>" command never does, so this always returns False for it.

        Args:
            response: The response being resumed via execute_approved().

        Returns:
            True only if response.approval_request is present and its
            metadata's "save_to_inbox" entry is exactly "true". False
            otherwise.
        """
        if response.approval_request is None:
            return False
        return response.approval_request.metadata.get("save_to_inbox") == "true"

    def _execute_approved_webpage_summary(
        self, response: JarvisResponse, decision: ApprovalDecision
    ) -> JarvisResponse:
        """Run the approved webpage fetch, then summarize it with AI.

        Reached only via execute_approved(), only when
        _is_pending_webpage_summary(response) is True (Phase 34, Batch
        2). This re-runs the exact "webpage_read" tool and input carried
        on response - identical to how execute_approved()'s own generic
        path re-runs any other approved tool - so the fetch is always
        gated by the same YELLOW approval and the same
        WebpageReadTool/ToolExecutor/SecurityManager path a plain "read
        webpage <url>" request already uses. AI summarization is only
        ever attempted after that fetch has already succeeded.

        Args:
            response: The original response that carried the pending
                webpage-summary approval request.
            decision: The approval decision authorising the run.

        Returns:
            A JarvisResponse. If declined, an honest "declined" response
            with no fetch and no AI call. Otherwise, the result of
            running the approved fetch and, only on its success,
            attempting AI summarization - see
            _continue_webpage_summary_after_fetch for the rest of that
            behaviour.
        """
        if not decision.is_approved:
            return JarvisResponse(
                success=False,
                message="The action was declined and was not run.",
                plan=response.plan,
            )

        session_id = (
            response.approval_request.session_id
            if response.approval_request is not None
            else None
        )
        fetch_result = self._executor.execute(
            response.tool_name,
            response.tool_input,
            session_id=session_id,
            approval_decision=decision,
        )

        if fetch_result.blocked or not fetch_result.success:
            return self._tool_result_to_response(response.plan, fetch_result)

        url = str(response.tool_input.get("url", ""))
        original_user_input = (
            response.approval_request.action
            if response.approval_request is not None
            else f"summarize webpage {url}"
        )
        summary_response = self._continue_webpage_summary_after_fetch(
            response.plan, fetch_result, url, original_user_input, session_id
        )

        # Phase 61, Batch 1: purely additive, reached only after the exact
        # `summary_response` the CLI will return already exists, and only
        # when the explicit "... and save to inbox" grammar created this
        # approval request in the first place. A failed save is caught
        # inside _save_webpage_summary_to_inbox itself and never changes,
        # delays, or replaces summary_response.
        if summary_response.success and self._should_save_webpage_summary_to_inbox(
            response
        ):
            self._save_webpage_summary_to_inbox(
                url=url, body=summary_response.message, session_id=session_id
            )

        return summary_response

    def _handle_remember_and_show_back_workflow_request(
        self, content: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the exact "remember this and show it back: <text>" request
        (Phase 15, Batch 3).

        Builds the fixed, all-GREEN two-step Plan via
        workflow.workflow_plan_factory.build_remember_and_show_plan() and
        executes it through WorkflowEngine - never executing a tool,
        classifying security, or creating an approval directly itself.

        Args:
            content: The raw trailing text extracted by
                CommandRouter.match_remember_and_show_back_workflow -
                possibly empty or whitespace-only.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse translated from the WorkflowResult, or an
            honest failure if WorkflowEngine is not configured.
        """
        plan = build_remember_and_show_plan(content)
        return self._handle_workflow_request(plan, session_id=session_id)

    def _handle_remember_and_forget_workflow_request(
        self, content: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the exact "remember this and forget it: <text>" request
        (Phase 15, Batch 3).

        Builds the fixed, GREEN-then-YELLOW two-step Plan via
        workflow.workflow_plan_factory.build_remember_and_forget_plan() and
        executes it through WorkflowEngine - never executing a tool,
        classifying security, or creating an approval directly itself. The
        YELLOW pause on step 2 arises naturally from the existing
        ToolExecutor/SecurityManager path inside WorkflowEngine, exactly as
        it would for any other "forget memory" action.

        Args:
            content: The raw trailing text extracted by
                CommandRouter.match_remember_and_forget_workflow -
                possibly empty or whitespace-only.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse translated from the WorkflowResult, or an
            honest failure if WorkflowEngine is not configured.
        """
        plan = build_remember_and_forget_plan(content)
        return self._handle_workflow_request(plan, session_id=session_id)

    def _handle_create_and_read_workflow_request(
        self, path: str, content: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the exact "create file <path> with <content> and show
        it" request (Phase 17, Batch 2).

        Builds the fixed, YELLOW-then-GREEN two-step Plan via
        workflow.workflow_plan_factory.build_create_and_read_plan() and
        executes it through the exact same shared _handle_workflow_request
        path the two Phase 15 workflows already use - never executing a
        tool, classifying security, or creating an approval directly
        itself. Both path and content are passed through exactly as
        CommandRouter.match_create_and_read_workflow() extracted them -
        possibly empty, in which case FileCreateTool itself reports the
        problem honestly, exactly as it already does for the standalone
        command.

        Args:
            path: The raw path extracted by
                CommandRouter.match_create_and_read_workflow - possibly
                empty.
            content: The raw content extracted by the same matcher -
                possibly empty.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse translated from the WorkflowResult, or an
            honest failure if WorkflowEngine is not configured.
        """
        plan = build_create_and_read_plan(path, content)
        return self._handle_workflow_request(plan, session_id=session_id)

    def _handle_file_search_and_copy_workflow_request(
        self, pattern: str, destination: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the exact "search files for <pattern> and copy first to
        <destination>" request (Phase 29).

        Builds the fixed, GREEN-then-YELLOW two-step Plan via
        workflow.workflow_plan_factory.build_file_search_and_copy_plan()
        and executes it through the exact same shared
        _handle_workflow_request path every other workflow command
        already uses - never executing a tool, classifying security, or
        creating an approval directly itself. Both pattern and
        destination are passed through exactly as
        CommandRouter.match_file_search_and_copy_workflow() extracted
        them - possibly empty, in which case FileSearchTool/FileCopyTool
        themselves report the problem honestly, exactly as they already
        do for their standalone commands. This method never selects
        among search matches or inspects step 1's result itself - that
        is entirely WorkflowEngine's own existing previous-step
        propagation mechanism (see workflow/engine.py's
        _PROPAGATED_FIELDS).

        Args:
            pattern: The raw filename pattern extracted by
                CommandRouter.match_file_search_and_copy_workflow -
                possibly empty.
            destination: The raw destination path extracted by the same
                matcher - possibly empty.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse translated from the WorkflowResult, or an
            honest failure if WorkflowEngine is not configured.
        """
        plan = build_file_search_and_copy_plan(pattern, destination)
        return self._handle_workflow_request(plan, session_id=session_id)

    def _handle_update_and_show_workflow_request(
        self, memory_id: int | None, content: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the exact "update memory <id>: <content> and show it
        back" request (Phase 17, Batch 2).

        Builds the fixed, YELLOW-then-GREEN two-step Plan via
        workflow.workflow_plan_factory.build_update_and_show_plan() and
        executes it through the exact same shared _handle_workflow_request
        path the two Phase 15 workflows already use. Unlike the other
        three workflow handlers, this one must check memory_id before
        calling the factory: build_update_and_show_plan() requires a real
        int, since - unlike a path or free-text content - there is no
        honest way for a downstream tool to report "the id you gave was
        not a number" once a non-int has already been forced into an int
        parameter. A None id (CommandRouter.match_update_and_show_workflow
        already tolerates an unparsable id, exactly as the standalone
        "update memory" command's own _extract_memory_id already does)
        is therefore rejected here, honestly, before any Plan is built.

        Args:
            memory_id: The id extracted by
                CommandRouter.match_update_and_show_workflow, or None if
                it could not be parsed as an integer.
            content: The raw replacement content extracted by the same
                matcher - possibly empty.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse translated from the WorkflowResult, an
            honest failure if memory_id could not be parsed, or an honest
            failure if WorkflowEngine is not configured.
        """
        if memory_id is None:
            return JarvisResponse(
                success=False,
                message=(
                    "Updating a memory requires a valid numeric id."
                ),
            )
        plan = build_update_and_show_plan(memory_id, content)
        return self._handle_workflow_request(plan, session_id=session_id)

    def _handle_workflow_request(
        self, plan: Plan, *, session_id: int | None
    ) -> JarvisResponse:
        """Run a deterministically-built Phase 15 workflow Plan and
        translate its result.

        Shared by both workflow handlers - the only difference between them
        is which workflow_plan_factory function built `plan`. Never
        executes a tool, classifies an action, or creates an approval
        itself: WorkflowEngine.run() owns all of that, reusing the existing
        ToolExecutor/ApprovalManager path unchanged.

        Args:
            plan: The fixed two-step Plan built by workflow_plan_factory.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse translated from the WorkflowResult, or an
            honest failure if WorkflowEngine is not configured (mirroring
            how a missing memory_manager fails the memory-summary
            workflows honestly rather than raising).
        """
        if self._workflow_engine is None:
            return JarvisResponse(
                success=False,
                message="Workflow execution is not available.",
                plan=plan,
            )

        result = self._workflow_engine.run(plan, session_id=session_id)
        return self._workflow_result_to_response(result)

    @staticmethod
    def _workflow_result_to_response(result: WorkflowResult) -> JarvisResponse:
        """Translate a WorkflowResult into a JarvisResponse (Phase 15,
        Batch 3; workflow_trace added Batch 4).

        Deliberately never sets tool_name/tool_input on the returned
        response, unlike the ordinary single-tool YELLOW-pending path: a
        workflow response is always resumed through
        execute_approved()'s own workflow-linked branch
        (_paused_workflow_id_for), never through the ordinary
        single-tool re-execution path below it. Leaving tool_name/tool_input
        unset means that even if that recognition were ever to fail, the
        existing "no runnable tool" fallback would apply harmlessly,
        instead of risking a second, out-of-sequence tool execution.

        Args:
            result: The WorkflowResult returned by WorkflowEngine.run() or
                .resume().

        Returns:
            A JarvisResponse honestly reflecting COMPLETED (success, no
            approval request), WAITING (not successful, not blocked,
            carries the real pending ApprovalRequest, no completion
            claim), or FAILED (not successful, blocked only when the
            terminal step's own ToolResult reports blocked, no fabricated
            approval request) - always carrying an honest, post-run
            workflow_trace of every step actually attempted, in order.
        """
        last_outcome = result.step_outcomes[-1] if result.step_outcomes else None
        last_tool_result = last_outcome.tool_result if last_outcome else None
        trace = JarvisOrchestrator._build_workflow_trace(result)

        if result.overall_status is StepStatus.WAITING:
            return JarvisResponse(
                success=False,
                message=result.message,
                plan=result.plan,
                tool_result=last_tool_result,
                requires_confirmation=True,
                approval_request=result.pending_approval_request,
                workflow_trace=trace,
            )

        if result.overall_status is StepStatus.FAILED:
            blocked = bool(last_tool_result and last_tool_result.blocked)
            return JarvisResponse(
                success=False,
                message=result.message,
                plan=result.plan,
                tool_result=last_tool_result,
                blocked=blocked,
                workflow_trace=trace,
            )

        final_output = last_tool_result.output if last_tool_result else ""
        message = f"{result.message} {final_output}".strip()
        return JarvisResponse(
            success=True,
            message=message,
            plan=result.plan,
            workflow_trace=trace,
            tool_result=last_tool_result,
        )

    @staticmethod
    def _build_workflow_trace(
        result: WorkflowResult,
    ) -> tuple[WorkflowTraceStep, ...]:
        """Build the honest, post-run execution trace for a WorkflowResult
        (Phase 15, Batch 4).

        Converts each WorkflowStepOutcome that was actually attempted into
        a narrow, CLI-safe WorkflowTraceStep - never exposing
        WorkflowStepOutcome, ToolResult, ApprovalRequest, or tool_input
        directly. This is explicitly a record of what already happened by
        the time WorkflowEngine.run()/resume() returned, not a live or
        streaming progress feed: no entry exists here for a step that was
        never reached, and no entry is ever fabricated.

        Args:
            result: The WorkflowResult to summarise.

        Returns:
            An ordered tuple of WorkflowTraceStep, one per attempted step,
            in the exact order WorkflowEngine produced them.
        """
        total = len(result.plan.steps)
        trace: list[WorkflowTraceStep] = []
        for outcome in result.step_outcomes:
            if outcome.status is StepStatus.WAITING:
                message = (
                    outcome.approval_request.reason
                    if outcome.approval_request is not None
                    else ""
                )
            elif outcome.tool_result is not None:
                message = outcome.tool_result.output or outcome.tool_result.error or ""
            else:
                message = ""

            trace.append(
                WorkflowTraceStep(
                    step_number=outcome.step.number,
                    total_steps=total,
                    description=outcome.step.description,
                    status=outcome.status.value,
                    message=message,
                )
            )
        return tuple(trace)

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

        web_search_summary_query = (
            self._command_router.match_web_search_summary(user_request.strip())
        )
        if web_search_summary_query is not None:
            return self._handle_web_search_summary_request(
                web_search_summary_query, user_request, session_id
            )

        # Phase 61, Batch 1: the explicit "... and save to inbox" variant
        # is a strict superset-string of the base webpage-summary prefix,
        # exactly like Phase 11/12's query/category summary matchers
        # relative to the plural set-summary matcher - it MUST be checked
        # first, or it would be swallowed by match_webpage_summary below
        # and misread as a URL literally containing the trailing words.
        webpage_summary_and_save_url = (
            self._command_router.match_webpage_summary_and_save(
                user_request.strip()
            )
        )
        if webpage_summary_and_save_url is not None:
            return self._handle_webpage_summary_request(
                webpage_summary_and_save_url,
                user_request,
                session_id,
                save_to_inbox=True,
            )

        webpage_summary_url = self._command_router.match_webpage_summary(
            user_request.strip()
        )
        if webpage_summary_url is not None:
            return self._handle_webpage_summary_request(
                webpage_summary_url, user_request, session_id
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

        # Phase 15, Batch 3: the two exact deterministic workflow commands are
        # checked here, in the same pre-_handle_request_core dispatch position
        # every Phase 8-14 special-case matcher already occupies. This is
        # load-bearing: "remember this and show it back: ..." and "remember
        # this and forget it: ..." both start with "remember this", which
        # _build_memory_input's own generic save-parsing branch
        # (lowered.startswith("remember this")) would otherwise silently
        # capture and misinterpret as a plain "remember this: ..." save,
        # discarding the "and show it back"/"and forget it" wording entirely
        # (confirmed by direct inspection before this batch - see
        # docs/phase_15_implementation_plan.md's Batch 3 investigation).
        # Checking these here, before the fallback to _handle_request_core
        # (which is the only path that ever reaches match()/
        # _build_memory_input), prevents that collision entirely. Neither new
        # matcher collides with any of the seven existing special-case
        # matchers above (none of which share the "remember" leading word),
        # so this position relative to them is not itself a correctness
        # requirement - only its position relative to the generic fallback is.
        remember_and_show_back_content = (
            self._command_router.match_remember_and_show_back_workflow(
                user_request.strip()
            )
        )
        if remember_and_show_back_content is not None:
            return self._handle_remember_and_show_back_workflow_request(
                remember_and_show_back_content, session_id
            )

        remember_and_forget_content = (
            self._command_router.match_remember_and_forget_workflow(
                user_request.strip()
            )
        )
        if remember_and_forget_content is not None:
            return self._handle_remember_and_forget_workflow_request(
                remember_and_forget_content, session_id
            )

        # Phase 17: two more fixed workflow commands, checked in the same
        # position relative to the generic fallback as the two Phase 15
        # workflow checks above, for the identical reason - each matcher
        # returns None on any non-match, so a non-workflow-shaped request
        # falls through to _handle_request_core exactly as before.
        create_and_read_match = self._command_router.match_create_and_read_workflow(
            user_request.strip()
        )
        if create_and_read_match is not None:
            path, content = create_and_read_match
            return self._handle_create_and_read_workflow_request(
                path, content, session_id
            )

        update_and_show_match = self._command_router.match_update_and_show_workflow(
            user_request.strip()
        )
        if update_and_show_match is not None:
            memory_id, content = update_and_show_match
            return self._handle_update_and_show_workflow_request(
                memory_id, content, session_id
            )

        # Phase 29: one more fixed workflow command, checked in the same
        # position relative to the generic fallback as every workflow
        # check above, for the identical reason - the matcher returns
        # None on any non-match (including the standalone "search files
        # for <pattern>"/"find files named <pattern>" commands, which
        # have no trailing " and copy first to " marker), so a
        # non-workflow-shaped request falls through to
        # _handle_request_core exactly as before.
        search_and_copy_match = (
            self._command_router.match_file_search_and_copy_workflow(
                user_request.strip()
            )
        )
        if search_and_copy_match is not None:
            pattern, destination = search_and_copy_match
            return self._handle_file_search_and_copy_workflow_request(
                pattern, destination, session_id
            )

        # Phase 90, Batch 2: the "ask jarvis to: <request>" tool-intent
        # command is checked immediately before its Batch 1 sibling
        # "ask jarvis:", per Section 25.A's fixed (though not
        # correctness-critical - the two prefixes never collide, see
        # CommandRouter's own collision proof) dispatch ordering. Both
        # remain in the same final special-handler cluster, immediately
        # before the generic fallback.
        ask_jarvis_to_request_text = self._command_router.match_ask_jarvis_to(
            user_request.strip()
        )
        if ask_jarvis_to_request_text is not None:
            return self._handle_ask_jarvis_to_request(
                ask_jarvis_to_request_text, user_request, session_id
            )

        # Phase 90, Batch 1: the "ask jarvis: <request>" Context
        # Intelligence command is checked last, immediately before the
        # generic fallback - the exact dispatch position Section 24.A.7
        # requires. No existing deterministic command or special matcher
        # above starts with "ask jarvis:" (confirmed by grep against
        # every exact/prefix table in core/command_router.py before this
        # matcher was added), so this cannot shadow or steal priority
        # from any of them, and every request not starting with this
        # exact prefix falls through to _handle_request_core exactly as
        # before - this never converts an unmatched request into an
        # intelligence request.
        ask_jarvis_request_text = self._command_router.match_ask_jarvis(
            user_request.strip()
        )
        if ask_jarvis_request_text is not None:
            return self._handle_ask_jarvis_request(
                ask_jarvis_request_text, user_request, session_id
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

    def _handle_web_search_summary_request(
        self, raw_query: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle an explicit "summarise web search for <query>" request
        (Phase 18, Batch 2).

        This is a terminal response path, the direct architectural
        sibling of _handle_file_summary_request/_handle_memory_summary_request,
        separate from the rule-based _handle_request_core/_attach_ai_suggestion
        flow: the AI's own synthesis of live web search results is the
        entire point of this request. It still coordinates only
        existing, already-secured components - it owns no search
        acquisition, context construction, or unexpected-action logic of
        its own:

            1. A Plan is generated normally (Planner.create_plan), so the
               existing unexpected-action policy has a real expected-action
               scope to evaluate AI suggestions against.
            2. The raw trailing query text CommandRouter.match_web_search_summary
               extracted is checked for emptiness here, before anything
               else is attempted - an empty query fails honestly with no
               search performed and no AI ever consulted.
            3. Required collaborators (AI reasoning, then the
               web_search_provider) are confirmed available, each with
               its own honest failure.
            4. ai.web_search_ingestion.ingest_web_search_for_ai() performs
               the search directly through WebSearchProvider.search() -
               called exactly once - and returns either an UNTRUSTED
               AIContextBlock or a represented failure. This method never
               calls WebSearchProvider.search() itself, never constructs
               an AIContextBlock itself, and never parses WebSearchTool's
               own rendered display output.
            5. On ingestion failure (a provider error, or zero results),
               an honest failure is returned and the AI is never called -
               a summary is never fabricated from context that does not
               exist.
            6. AIReasoningEngine.reason() is called exactly as it always
               is; this method has no ability to execute anything
               regardless of what the AI returns, and nothing here can
               trigger a second search.
            7. The fixed _WEB_SEARCH_SUMMARY_LABEL is prepended to every
               successful response unconditionally - the code-enforced
               honesty guarantee that this is a synthesis of search-result
               snippets, never full webpage content, regardless of the
               AI's own wording.
            8. Every AI-suggested action is evaluated through the
               existing, unmodified _evaluate_unexpected_actions/
               _audit_unexpected_action methods - the same Batch 4 policy
               and audit path every other request already uses.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        summary, and never raises into the caller. Raw search results are
        never substituted as a fake summary: Nathan can use the existing,
        separate "search the web for <query>" command directly if AI
        summarization is unavailable.

        Args:
            raw_query: The raw trailing query text extracted by
                CommandRouter.match_web_search_summary - possibly empty.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary
            was produced; otherwise success=False with an honest
            explanation of which stage did not complete - never blocked
            or requiring confirmation, since this workflow performs no
            write action of any kind.
        """
        plan = self._planner.create_plan(user_request.strip())
        query = raw_query.strip()

        if not query:
            return JarvisResponse(
                success=False,
                message="Summarising a web search requires a non-empty query.",
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_WEB_SEARCH_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._web_search_provider is None:
            return JarvisResponse(
                success=False,
                message="Web search is not available.",
                plan=plan,
            )

        ingestion = ingest_web_search_for_ai(self._web_search_provider, query)
        self._audit_web_search_summary_acquisition(ingestion, session_id)
        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=ingestion.error or "Could not search the web.",
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
                message=_WEB_SEARCH_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
                plan=plan,
            )

        summary = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            summary = f"{result.summary} Suggested steps: {steps}"

        response = JarvisResponse(
            success=True,
            message=f"{_WEB_SEARCH_SUMMARY_LABEL} {summary}",
            plan=plan,
        )

        # Reused, not duplicated: the exact same Batch 4 policy/audit method
        # every other request's advisory suggestion already goes through.
        self._evaluate_unexpected_actions(response, result, session_id)

        # Phase 20, Batch 2: purely additive. This is the one and only
        # place in the codebase that writes to the inbox - reached only
        # after the exact success `response` above (identical to what the
        # CLI will return) already exists. A failed save is caught inside
        # _save_web_search_summary_to_inbox itself and never changes,
        # delays, or replaces `response`.
        self._save_web_search_summary_to_inbox(
            query=query,
            body=response.message,
            included_count=ingestion.included_count,
            session_id=session_id,
        )

        return response

    def _handle_ask_jarvis_to_request(
        self, raw_request: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the explicit "ask jarvis to: <request>" request (Phase
        90, Batch 2 - Planning and Safe GREEN Tool Selection).

        This is a terminal response path, the tool-executing sibling of
        _handle_ask_jarvis_request: instead of an advisory answer, this
        workflow asks the AI to select at most one allowlisted GREEN
        capability, deterministically validates that selection, runs a
        real security preflight, and - only if every check passes -
        executes the real, corresponding tool through the existing,
        unmodified ToolExecutor. It still coordinates only existing,
        already-secured components, plus the new, narrow
        intelligence.planning.select_tool() helper:

            1. A Plan is generated normally (Planner.create_plan).
            2. The raw trailing request text is checked for emptiness
               here, before anything else is attempted - an empty
               request performs no context retrieval, no AI call, no
               preflight, and no tool execution.
            3. Required collaborators (the tool-selection AIRouter, then
               the context_assembler) are confirmed available, each
               with its own honest, distinct failure - "AI reasoning is
               not enabled" is never confused with "the provider is
               unavailable" or "the provider failed".
            4. intelligence.context.ContextAssembler.assemble() performs
               the exact same bounded, deterministic context assembly
               Batch 1 already uses - unchanged.
            5. intelligence.planning.select_tool() calls the real
               AIRouter directly (with its own fixed, trusted planning
               instruction - never mixed into any ContextItem), parses
               and validates the response, and - for a valid "execute"
               decision - runs the real SecurityManager preflight,
               requiring GREEN before ever returning an executable
               StructuredPlan. This method never constructs an
               AIContextBlock, never calls a provider, and never
               classifies security itself.
            6. A valid "unsupported" decision, or any parsing/
               validation/preflight failure, terminates here - zero
               tool execution, zero approval, zero store mutation.
            7. Only a real, GREEN-preflighted StructuredPlan reaches
               self._executor.execute() - the same real, unmodified
               ToolExecutor every other tool call in the system goes
               through, which independently re-classifies the action
               from scratch. Its real ToolResult is translated via the
               existing, unmodified _tool_result_to_response() helper,
               so an unexpected execution-time confirmation-required or
               blocked result is reported exactly as honestly as it
               already is for every other tool call - never converted
               into an approval flow, never claimed as a success.
            8. A successful execution's response is grounded in the
               real ToolResult.output, with only a fixed label
               prepended - no second AI call ever summarizes,
               paraphrases, or embellishes it.

        Args:
            raw_request: The raw trailing request text extracted by
                CommandRouter.match_ask_jarvis_to - possibly empty.
            user_request: The original, full request text (including
                the "ask jarvis to:" prefix), used only for
                Planner.create_plan.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True for a real, grounded
            execution or a valid "unsupported" decision; success=False
            for every disabled/unavailable/failed/invalid/diverged
            outcome - never blocked or requiring confirmation as a
            claimed success, and never presenting a failure as if it
            were a valid "unsupported" decision.
        """
        plan = self._planner.create_plan(user_request.strip())
        request_text = raw_request.strip()

        if not request_text:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_EMPTY_REQUEST_MESSAGE,
                plan=plan,
            )

        if self._tool_selection_router is None:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._context_assembler is None:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_CONTEXT_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        assembled = self._context_assembler.assemble(request_text)

        outcome = select_tool(
            request_text=request_text,
            assembled_context=assembled,
            router=self._tool_selection_router,
            tool_registry=self._registry,
            security_manager=self._security,
            session_id=session_id,
        )

        if outcome.kind is PlanningOutcomeKind.PROVIDER_UNAVAILABLE:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_PROVIDER_UNAVAILABLE_MESSAGE,
                plan=plan,
            )

        if outcome.kind is PlanningOutcomeKind.PROVIDER_FAILED:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_PROVIDER_FAILED_MESSAGE,
                plan=plan,
            )

        if outcome.kind is PlanningOutcomeKind.INVALID_OUTPUT:
            return JarvisResponse(
                success=False,
                message=f"{_ASK_JARVIS_TO_INVALID_OUTPUT_PREFIX} {outcome.detail}.",
                plan=plan,
            )

        if outcome.kind is PlanningOutcomeKind.UNSUPPORTED:
            return JarvisResponse(
                success=True,
                message=UNSUPPORTED_CAPABILITY_MESSAGE,
                plan=plan,
            )

        if outcome.kind is PlanningOutcomeKind.EXECUTABLE_WORKFLOW:
            return self._start_update_focus_workflow(plan, outcome, session_id)

        if outcome.kind is PlanningOutcomeKind.UNGROUNDED_SELECTION:
            # Phase 92, Batch 2: refused before any preflight, approval,
            # execution, or verification - see
            # intelligence.grounding.ground_decision(). One of exactly
            # two honest, non-technical public messages, chosen from
            # the bounded internal reason - never the reason code
            # itself, never the request, never a candidate/rejected
            # value.
            return JarvisResponse(
                success=False,
                message=_ask_jarvis_to_ungrounded_message(outcome.detail),
                plan=plan,
            )

        # PlanningOutcomeKind.EXECUTABLE: a real, GREEN-preflighted
        # StructuredPlan with exactly one step.
        assert outcome.plan is not None
        step = outcome.plan.steps[0]
        result = self._executor.execute(
            step.tool_name, step.arguments, session_id=session_id
        )

        base_response = self._tool_result_to_response(plan, result)
        if not base_response.success:
            return base_response

        return replace(
            base_response,
            message=f"{_ASK_JARVIS_TO_LABEL} {base_response.message}".strip(),
        )

    def _start_update_focus_workflow(
        self,
        plan: Plan,
        outcome: PlanningOutcome,
        session_id: int | None,
    ) -> JarvisResponse:
        """Run the deterministic, two-step update-focus-and-verify Plan
        through the real, unmodified WorkflowEngine (Phase 90, Batch 3).

        Args:
            plan: The generic Plan built for the raw "ask jarvis to:"
                request text (used only if WorkflowEngine is
                unavailable - the real workflow response otherwise
                carries its own, internal two-step Plan instead).
            outcome: The EXECUTABLE_WORKFLOW PlanningOutcome carrying
                the real, already-preflighted two-step workflow_plan.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. If WorkflowEngine is not configured, an
            honest failure. If the first run() call does not pause for
            approval (step 1 was preflighted YELLOW but did not
            require confirmation at real execution time - a genuine
            safety mismatch), an honest refusal that never claims
            success under any circumstance. Otherwise, the translated,
            verification-aware response for whatever real state the
            workflow reached.
        """
        if self._workflow_engine is None:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_WORKFLOW_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        assert outcome.workflow_plan is not None  # guaranteed by EXECUTABLE_WORKFLOW
        result = self._workflow_engine.run(outcome.workflow_plan, session_id=session_id)

        if result.overall_status is not StepStatus.WAITING:
            # Step 1 was preflighted YELLOW but did not pause for
            # approval at real execution time - refuse honestly
            # regardless of what actually happened; never report
            # success here under any circumstance (Batch 3 planning
            # prompt's own "execution-time divergence" safety
            # requirement).
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_TO_SAFETY_MISMATCH_MESSAGE,
                plan=plan,
                intelligence_trace=(
                    "Step 1/2: safety mismatch - the expected approval "
                    "requirement was not applied.",
                ),
            )

        return self._translate_verified_workflow_result(result)

    def _translate_verified_workflow_result(
        self, result: WorkflowResult
    ) -> JarvisResponse:
        """Dispatch a completed/paused two-step verified-workflow
        WorkflowResult to its own capability-specific response
        translator - recognised purely structurally, never a new
        persisted marker (Section 24.C.12).

        Shared by both the initial run() path (this method's own
        caller, _start_update_focus_workflow) and the resume() path
        (execute_approved()), so the dispatch itself is defined in
        exactly one place. Phase 94, Batch 3: which capability a result
        belongs to is now derived purely from CAPABILITY_CATALOG, by
        iterating every registered TWO_STEP_WORKFLOW entry
        (_matching_two_step_write_capability) - there is no per-
        capability `if`/`elif` recognition branch here or anywhere else
        in this method, and none is added by registering a future
        TWO_STEP_WORKFLOW capability. Only the final step - choosing
        which bespoke response-formatting method to call for the one
        matched capability - is a small, static, trusted lookup table
        (_response_builders below), exactly like every other per-
        capability trusted config table this codebase already uses
        (CAPABILITY_CATALOG itself, _FIXED_ARGUMENTS_BY_CAPABILITY,
        _NUMERIC_ARGUMENT_MARKER_BY_CAPABILITY) - a data addition, never
        a growing control-flow chain. The two response-formatting
        methods themselves remain distinct because their grounded
        response wording genuinely differs per capability (different
        fields, different verification signatures) - the same reason
        every real tool in this codebase has its own bespoke run()
        rather than sharing one generic formatter.

        Args:
            result: A real WorkflowResult, from either run() or
                resume().

        Returns:
            The capability-specific, verification-aware JarvisResponse
            for whichever real workflow shape result.plan matches, or
            the existing generic translation for any other workflow
            shape (the five pre-existing fixed Phase 15 workflows).
        """
        write_capability_id = self._matching_two_step_write_capability(result)
        response_builders: dict[
            CapabilityId, Callable[[WorkflowResult], JarvisResponse]
        ] = {
            CapabilityId.PROJECT_STATE_UPDATE_FOCUS: (
                self._update_focus_workflow_result_to_response
            ),
            CapabilityId.SCHEDULE_ENABLE: (
                self._schedule_enable_workflow_result_to_response
            ),
            CapabilityId.SCHEDULE_DISABLE: (
                self._schedule_disable_workflow_result_to_response
            ),
        }
        if write_capability_id is not None and write_capability_id in response_builders:
            return response_builders[write_capability_id](result)
        return self._workflow_result_to_response(result)

    @staticmethod
    def _matching_two_step_write_capability(
        result: WorkflowResult,
    ) -> CapabilityId | None:
        """Derive which, if any, registered TWO_STEP_WORKFLOW write
        capability's real tool-name pair matches this result's plan
        shape - purely from trusted, static CAPABILITY_CATALOG data,
        never a hardcoded per-capability check (Phase 94, Batch 3).

        Iterates every CAPABILITY_CATALOG entry whose
        allowed_strategy is TWO_STEP_WORKFLOW (today exactly
        PROJECT_STATE_UPDATE_FOCUS and SCHEDULE_ENABLE) and returns the
        first whose write-tool/paired-verify-tool pair matches
        result.plan's exact two steps, in order. A future
        TWO_STEP_WORKFLOW capability added to the catalog is recognised
        here automatically, with zero change to this method.

        Args:
            result: A real WorkflowResult, from either run() or resume().

        Returns:
            The matching CapabilityId, or None if result.plan does not
            match any registered TWO_STEP_WORKFLOW capability's shape
            (for example, one of the five pre-existing fixed Phase 15
            workflows).
        """
        for capability_id, adapter in CAPABILITY_CATALOG.items():
            if adapter.allowed_strategy is not ExecutionStrategy.TWO_STEP_WORKFLOW:
                continue
            if JarvisOrchestrator._matches_two_step_workflow_shape(
                result, capability_id
            ):
                return capability_id
        return None

    @staticmethod
    def _matches_two_step_workflow_shape(
        result: WorkflowResult, write_capability_id: CapabilityId
    ) -> bool:
        """Shared structural-shape check both workflow recognizers use:
        does result.plan's exact two-step tool-name pair match
        write_capability_id's own catalog-declared write tool and
        paired verify tool, in that order.

        A private, non-public helper - never exposed as a way to check
        an arbitrary capability_id against an arbitrary result; the two
        real recognizers above are the only callers, each fixed to its
        own one real capability id.

        Args:
            result: A real WorkflowResult, from either run() or resume().
            write_capability_id: The one TWO_STEP_WORKFLOW capability
                whose shape to check against.

        Returns:
            True only if the exact tool-name pair matches, in order.
        """
        steps = result.plan.steps
        if len(steps) != 2:
            return False

        write_adapter = CAPABILITY_CATALOG[write_capability_id]
        verify_capability_id = write_adapter.paired_verify_capability_id
        if verify_capability_id is None:
            return False
        verify_adapter = CAPABILITY_CATALOG.get(verify_capability_id)
        if verify_adapter is None:
            return False

        return (
            steps[0].tool_name == write_adapter.tool_name
            and steps[1].tool_name == verify_adapter.tool_name
        )

    def _update_focus_workflow_result_to_response(
        self, result: WorkflowResult
    ) -> JarvisResponse:
        """Translate a real update-focus-and-verify WorkflowResult into
        a grounded, verification-aware JarvisResponse (Phase 90, Batch 3).

        Never asks AI to judge success: verification is always the
        real, exact-string-equality comparison
        intelligence.verification.verify_focus_update() performs
        against the real, already-durable PlanStep.tool_input["value"]
        and the verify step's real ToolResult.metadata["focus"].

        Args:
            result: The real WorkflowResult from run() or resume().

        Returns:
            A JarvisResponse honestly reflecting exactly one of:
            pending approval (WAITING); the write step itself never
            executed (failed/blocked/declined - no verification
            attempted); or, once the write step completed, a real
            VerificationOutcome (VERIFIED/FAILED/UNAVAILABLE) grounded
            in real values only - never AI prose, never a claimed
            success the real results do not support.
        """
        if result.overall_status is StepStatus.WAITING:
            base = self._workflow_result_to_response(result)
            return replace(
                base,
                intelligence_trace=(
                    "Step 1/2: awaiting your approval to update the "
                    "project focus.",
                ),
            )

        write_outcome = result.step_outcomes[0]
        if write_outcome.status is not StepStatus.COMPLETED:
            base = self._workflow_result_to_response(result)
            return replace(
                base,
                intelligence_trace=(
                    "Step 1/2: update did not execute; no verification "
                    "attempted.",
                ),
            )

        verify_outcome = (
            result.step_outcomes[1] if len(result.step_outcomes) > 1 else None
        )
        expected_value = str(write_outcome.step.tool_input.get("value", ""))
        verification = verify_focus_update(
            expected_value=expected_value,
            verify_tool_result=(
                verify_outcome.tool_result if verify_outcome is not None else None
            ),
        )
        trace = (
            "Step 1/2: update executed.",
            f"Step 2/2: verification {verification.outcome.value}.",
        )

        if verification.outcome is VerificationOutcome.VERIFIED:
            message = (
                f"Jarvis updated the project focus to: {expected_value}. "
                "Verification succeeded - the stored value matches."
            )
            success = True
        elif verification.outcome is VerificationOutcome.FAILED:
            message = (
                "Jarvis's update tool reported success, but the structured "
                "read-back found a different value than requested - the "
                "update is not confirmed."
            )
            success = False
        else:
            message = (
                "Jarvis's update tool reported success, but verification "
                "could not be completed, so the update is not confirmed."
            )
            success = False

        return JarvisResponse(
            success=success,
            message=message,
            plan=result.plan,
            tool_result=(
                verify_outcome.tool_result if verify_outcome is not None else None
            ),
            intelligence_trace=trace,
        )

    def _schedule_enable_workflow_result_to_response(
        self, result: WorkflowResult
    ) -> JarvisResponse:
        """Translate a real schedule-enable-and-verify WorkflowResult
        into a grounded, verification-aware JarvisResponse (Phase 94,
        Batch 2 - docs/phase_94_implementation_plan.md, Section 14),
        mirroring _update_focus_workflow_result_to_response's exact
        shape for the second real verified workflow.

        Never asks AI to judge success: verification is always the
        real, exact-boolean-identity comparison
        intelligence.verification.verify_schedule_enabled_state()
        performs against the fixed, trusted expected state (always
        True) and the verify step's real
        ToolResult.metadata["enabled"].

        Args:
            result: The real WorkflowResult from run() or resume().

        Returns:
            A JarvisResponse honestly reflecting exactly one of:
            pending approval (WAITING); the write step itself never
            executed (failed/blocked/declined - no verification
            attempted); or, once the write step completed, a real
            VerificationOutcome (VERIFIED/FAILED/UNAVAILABLE) grounded
            in real values only - never AI prose, never a claimed
            success the real results do not support.
        """
        if result.overall_status is StepStatus.WAITING:
            base = self._workflow_result_to_response(result)
            return replace(
                base,
                intelligence_trace=(
                    "Step 1/2: awaiting your approval to enable the "
                    "schedule.",
                ),
            )

        write_outcome = result.step_outcomes[0]
        if write_outcome.status is not StepStatus.COMPLETED:
            base = self._workflow_result_to_response(result)
            return replace(
                base,
                intelligence_trace=(
                    "Step 1/2: enable did not execute; no verification "
                    "attempted.",
                ),
            )

        verify_outcome = (
            result.step_outcomes[1] if len(result.step_outcomes) > 1 else None
        )
        schedule_id = write_outcome.step.tool_input.get("schedule_id")
        verification = verify_schedule_enabled_state(
            expected_enabled=True,
            verifier_id=SCHEDULE_ENABLED_EXACT_MATCH_VERIFIER_ID,
            verify_tool_result=(
                verify_outcome.tool_result if verify_outcome is not None else None
            ),
        )
        trace = (
            "Step 1/2: enable executed.",
            f"Step 2/2: verification {verification.outcome.value}.",
        )

        if verification.outcome is VerificationOutcome.VERIFIED:
            message = (
                f"Jarvis enabled schedule {schedule_id}. Verification "
                "succeeded - the stored state matches."
            )
            success = True
        elif verification.outcome is VerificationOutcome.FAILED:
            message = (
                "Jarvis's enable tool reported success, but the structured "
                "read-back found the schedule is not enabled - the update "
                "is not confirmed."
            )
            success = False
        else:
            message = (
                "Jarvis's enable tool reported success, but verification "
                "could not be completed, so the update is not confirmed."
            )
            success = False

        return JarvisResponse(
            success=success,
            message=message,
            plan=result.plan,
            tool_result=(
                verify_outcome.tool_result if verify_outcome is not None else None
            ),
            intelligence_trace=trace,
        )

    def _schedule_disable_workflow_result_to_response(
        self, result: WorkflowResult
    ) -> JarvisResponse:
        """Translate a real schedule-disable-and-verify WorkflowResult
        into a grounded, verification-aware JarvisResponse (Phase 95 -
        docs/phase_95_implementation_plan.md), mirroring
        _schedule_enable_workflow_result_to_response's exact shape for
        the third real verified workflow, with the one deliberate
        difference the postcondition itself requires:
        expected_enabled=False instead of True.

        Never asks AI to judge success: verification is always the
        real, exact-boolean-identity comparison
        intelligence.verification.verify_schedule_enabled_state()
        performs against the fixed, trusted expected state (always
        False for this workflow) and the verify step's real
        ToolResult.metadata["enabled"].

        Args:
            result: The real WorkflowResult from run() or resume().

        Returns:
            A JarvisResponse honestly reflecting exactly one of:
            pending approval (WAITING); the write step itself never
            executed (failed/blocked/declined - no verification
            attempted); or, once the write step completed, a real
            VerificationOutcome (VERIFIED/FAILED/UNAVAILABLE) grounded
            in real values only - never AI prose, never a claimed
            success the real results do not support.
        """
        if result.overall_status is StepStatus.WAITING:
            base = self._workflow_result_to_response(result)
            return replace(
                base,
                intelligence_trace=(
                    "Step 1/2: awaiting your approval to disable the "
                    "schedule.",
                ),
            )

        write_outcome = result.step_outcomes[0]
        if write_outcome.status is not StepStatus.COMPLETED:
            base = self._workflow_result_to_response(result)
            return replace(
                base,
                intelligence_trace=(
                    "Step 1/2: disable did not execute; no verification "
                    "attempted.",
                ),
            )

        verify_outcome = (
            result.step_outcomes[1] if len(result.step_outcomes) > 1 else None
        )
        schedule_id = write_outcome.step.tool_input.get("schedule_id")
        verification = verify_schedule_enabled_state(
            expected_enabled=False,
            verifier_id=SCHEDULE_DISABLED_EXACT_MATCH_VERIFIER_ID,
            verify_tool_result=(
                verify_outcome.tool_result if verify_outcome is not None else None
            ),
        )
        trace = (
            "Step 1/2: disable executed.",
            f"Step 2/2: verification {verification.outcome.value}.",
        )

        if verification.outcome is VerificationOutcome.VERIFIED:
            message = (
                f"Jarvis disabled schedule {schedule_id}. Verification "
                "succeeded - the stored state matches."
            )
            success = True
        elif verification.outcome is VerificationOutcome.FAILED:
            message = (
                "Jarvis's disable tool reported success, but the structured "
                "read-back found the schedule is still enabled - the update "
                "is not confirmed."
            )
            success = False
        else:
            message = (
                "Jarvis's disable tool reported success, but verification "
                "could not be completed, so the update is not confirmed."
            )
            success = False

        return JarvisResponse(
            success=success,
            message=message,
            plan=result.plan,
            tool_result=(
                verify_outcome.tool_result if verify_outcome is not None else None
            ),
            intelligence_trace=trace,
        )

    def _handle_ask_jarvis_request(
        self, raw_request: str, user_request: str, session_id: int | None
    ) -> JarvisResponse:
        """Handle the explicit "ask jarvis: <request>" request (Phase 90,
        Batch 1 - Context Intelligence).

        This is a terminal response path, the direct architectural
        sibling of _handle_file_summary_request/
        _handle_web_search_summary_request/_handle_webpage_summary_request:
        the AI's own advisory answer, grounded in automatically-assembled
        context, is the entire point of this request. It still
        coordinates only existing, already-secured components, and
        executes no tool of any kind:

            1. A Plan is generated normally (Planner.create_plan), so the
               existing unexpected-action policy has a real expected-
               action scope to evaluate AI suggestions against.
            2. The raw trailing request text
               CommandRouter.match_ask_jarvis extracted is checked for
               emptiness here, before anything else is attempted - an
               empty request fails honestly with no context retrieval
               and no AI call at all.
            3. Required collaborators (AI reasoning, then the
               context_assembler) are confirmed available, each with its
               own honest failure.
            4. intelligence.context.ContextAssembler.assemble() performs
               bounded, deterministic memory search/recency selection and
               a ProjectStateStore.get() read - never an AI call, never a
               tool execution, never an approval.
            5. intelligence.context.build_ai_context_block() combines the
               assembled, always-UNTRUSTED ContextItems into one
               AIContextBlock - this method never constructs an
               AIContextBlock itself, and never re-labels or re-derives
               trust.
            6. AIReasoningEngine.reason() is called exactly as it always
               is, with the live request text as the trusted user_input
               and the combined block as context_block - this method has
               no ability to execute anything regardless of what the AI
               returns, and the combined block still passes through
               PromptBuilder's existing, unmodified untrusted-context
               framing and injection scanner unchanged.
            7. The fixed _ASK_JARVIS_LABEL is prepended to every
               successful response unconditionally - the code-enforced
               honesty guarantee that this is an advisory answer grounded
               in automatically assembled context, regardless of the
               AI's own wording.
            8. Every AI-suggested action is evaluated through the
               existing, unmodified _evaluate_unexpected_actions method -
               the same Batch 4 policy and audit path every other request
               already uses.

        A failure at any stage returns an honest, distinct JarvisResponse
        rather than ever presenting a failure as if it were a real AI
        answer, and never raises into the caller. No tool is ever
        executed, no approval is ever created, and no store is ever
        mutated by this method.

        Args:
            raw_request: The raw trailing request text extracted by
                CommandRouter.match_ask_jarvis - possibly empty.
            user_request: The original, full request text (including the
                "ask jarvis:" prefix), used only for Planner.create_plan.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI answer was
            produced; otherwise success=False with an honest explanation
            of which stage did not complete - never blocked or requiring
            confirmation, since this workflow performs no write action of
            any kind.
        """
        plan = self._planner.create_plan(user_request.strip())
        request_text = raw_request.strip()

        if not request_text:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_EMPTY_REQUEST_MESSAGE,
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if self._context_assembler is None:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_CONTEXT_NOT_AVAILABLE_MESSAGE,
                plan=plan,
            )

        assembled = self._context_assembler.assemble(request_text)
        context_block = build_ai_context_block(assembled)

        reasoning_request = AIReasoningRequest(
            user_input=request_text,
            context_block=context_block,
            session_id=session_id,
        )
        result = self._reasoning.reason(reasoning_request)
        if result is None:
            return JarvisResponse(
                success=False,
                message=_ASK_JARVIS_AI_REASONING_UNAVAILABLE_MESSAGE,
                plan=plan,
            )

        summary = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            summary = f"{result.summary} Suggested steps: {steps}"

        response = JarvisResponse(
            success=True,
            message=f"{_ASK_JARVIS_LABEL} {summary}",
            plan=plan,
        )

        # Reused, not duplicated: the exact same Batch 4 policy/audit method
        # every other request's advisory suggestion already goes through.
        self._evaluate_unexpected_actions(response, result, session_id)

        return response

    def _handle_webpage_summary_request(
        self,
        raw_url: str,
        user_request: str,
        session_id: int | None,
        *,
        save_to_inbox: bool = False,
    ) -> JarvisResponse:
        """Handle an explicit "summarize/summarise webpage <url>" request
        (Phase 34, Batch 2), optionally saving the resulting summary to
        the Inbox (Phase 61, Batch 1).

        Unlike _handle_web_search_summary_request above, this is a
        two-phase workflow: acquisition is never performed here directly.
        Instead, this method executes the real, registered
        WebpageReadTool through the real ToolExecutor - exactly the way
        a plain "read webpage <url>" request already does - so a first
        (unapproved) call always comes back requiring the same YELLOW
        confirmation, classified via the tool's own fixed "read webpage"
        action string. Only once Nathan approves that pending request
        (via execute_approved(), which detects this specific pending
        approval through _is_pending_webpage_summary() and delegates to
        _execute_approved_webpage_summary() below) does the actual fetch
        happen, and only after that fetch succeeds does AI summarization
        ever occur. This is the central safety property the Phase 34
        implementation plan exists to guarantee: an AI-summarization
        command must never itself acquire arbitrary webpage content
        without going through the exact same approval gate a plain
        webpage read already requires - see
        docs/phase_34_implementation_plan.md, Section 2, for the finding
        that made this necessary (the web-search-summary handler above
        is safe to leave un-approval-gated only because it always calls
        one fixed, vetted provider - a webpage URL is not that).

        Args:
            raw_url: The raw trailing URL text extracted by
                CommandRouter.match_webpage_summary or
                match_webpage_summary_and_save - possibly empty.
            user_request: The original, full request text.
            session_id: Optional session identifier for the audit trail.
            save_to_inbox: True only when this request was matched via
                the explicit "... and save to inbox" grammar
                (match_webpage_summary_and_save). Threaded into the
                created approval request's metadata
                (Phase 61, Batch 1) so execute_approved() can later
                decide, after a real successful summary, whether to
                durably save it - the plain "summarize webpage <url>"
                command never sets this and remains completely
                Inbox-free, exactly as before this phase.

        Returns:
            A JarvisResponse. requires_confirmation=True on a first,
            unapproved call (identical in shape to a plain "read
            webpage <url>" response); success=True only once a real AI
            summary was produced after an approved fetch; otherwise
            success=False with an honest explanation of which stage did
            not complete. Never raises.
        """
        plan = self._planner.create_plan(user_request.strip())
        url = raw_url.strip()

        if not url:
            return JarvisResponse(
                success=False,
                message="Summarising a webpage requires a non-empty URL.",
                plan=plan,
            )

        if self._reasoning is None:
            return JarvisResponse(
                success=False,
                message=_WEBPAGE_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
                plan=plan,
            )

        if not self._registry.has_tool("webpage_read"):
            return JarvisResponse(
                success=False,
                message="Reading webpages is not available.",
                plan=plan,
            )

        result = self._executor.execute(
            "webpage_read", {"url": url}, session_id=session_id
        )

        if result.blocked:
            return JarvisResponse(
                success=False,
                message=result.error or "The action was blocked for safety.",
                plan=plan,
                tool_result=result,
                blocked=True,
            )

        if result.requires_confirmation:
            metadata = {"webpage_summary": "true"}
            if save_to_inbox:
                # Phase 61, Batch 1: only the explicit "... and save to
                # inbox" grammar ever sets this key - its absence is what
                # keeps the plain "summarize webpage <url>" command
                # completely Inbox-free, exactly as before this phase.
                metadata["save_to_inbox"] = "true"
            approval = self._approvals.create_request(
                action=user_request.strip(),
                reason=(
                    (result.error or "This action requires your confirmation.")
                    + " Jarvis will summarize the page with AI after it is"
                    " fetched."
                ),
                security_tier=SecurityTier.YELLOW,
                session_id=session_id,
                tool_name="webpage_read",
                tool_input={"url": url},
                metadata=metadata,
            )
            return JarvisResponse(
                success=False,
                message=result.error or "This action requires your confirmation.",
                plan=plan,
                tool_result=result,
                requires_confirmation=True,
                approval_request=approval,
                tool_name="webpage_read",
                tool_input={"url": url},
            )

        # Not reached today - "read webpage" is always classified YELLOW
        # (security/security_manager.py) - but handled honestly rather
        # than assumed structurally impossible: if the fetch somehow
        # already ran without needing approval, proceed directly to
        # summarization using its result, exactly like the post-approval
        # path below would.
        response = self._continue_webpage_summary_after_fetch(
            plan, result, url, user_request.strip(), session_id
        )
        if save_to_inbox and response.success:
            self._save_webpage_summary_to_inbox(
                url=url, body=response.message, session_id=session_id
            )
        return response

    def _continue_webpage_summary_after_fetch(
        self,
        plan: Plan | None,
        fetch_result: ToolResult,
        url: str,
        original_user_input: str,
        session_id: int | None,
    ) -> JarvisResponse:
        """Ingest an already-fetched webpage and ask AI to summarize it.

        Called only after WebpageReadTool has already run successfully
        (either the not-reached-today immediate-GREEN path in
        _handle_webpage_summary_request, or the approved path in
        _execute_approved_webpage_summary below) - never before, and
        never with unfetched content.

        Args:
            plan: The plan from the original request, carried through.
            fetch_result: The successful ToolResult from running
                "webpage_read" - fetch_result.success must be True.
            url: The webpage URL that was fetched, for display/source
                labelling only.
            original_user_input: The original request text, passed to
                AIReasoningEngine.reason() as user_input, exactly like
                every other summary handler passes its own original
                request text through unchanged.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A JarvisResponse. success=True only when a real AI summary
            was produced; otherwise success=False with an honest
            explanation of which stage (ingestion or AI reasoning) did
            not complete. The AI summary, when produced, is
            display-only: it is attached to JarvisResponse.message and
            nowhere else - never written to a file, the database, or
            any write-tool's input.
        """
        ingestion = ingest_webpage_for_ai(
            url,
            fetch_result.metadata.get("extracted_text", ""),
            content_type=fetch_result.metadata.get("content_type"),
            status_code=self._metadata_int(fetch_result.metadata, "status_code"),
            byte_count=self._metadata_int(fetch_result.metadata, "byte_count"),
            extraction_truncated=fetch_result.metadata.get("truncated") == "True",
        )
        if not ingestion.success:
            return JarvisResponse(
                success=False,
                message=(
                    ingestion.error
                    or "Could not prepare the webpage for summarization."
                ),
                plan=plan,
                tool_result=fetch_result,
            )

        reasoning_request = AIReasoningRequest(
            user_input=original_user_input,
            context_block=ingestion.context,
            session_id=session_id,
        )
        result = self._reasoning.reason(reasoning_request)
        if result is None:
            return JarvisResponse(
                success=False,
                message=_WEBPAGE_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
                plan=plan,
                tool_result=fetch_result,
            )

        summary = result.summary
        if result.has_suggestions:
            steps = "; ".join(a.description for a in result.suggested_actions)
            summary = f"{result.summary} Suggested steps: {steps}"

        response = JarvisResponse(
            success=True,
            message=f"{_WEBPAGE_SUMMARY_LABEL} {summary}",
            plan=plan,
            tool_result=fetch_result,
        )

        # Reused, not duplicated: the exact same Batch 4 policy/audit
        # method every other request's advisory suggestion already goes
        # through.
        self._evaluate_unexpected_actions(response, result, session_id)

        return response

    @staticmethod
    def _metadata_int(metadata: dict[str, str], key: str) -> int | None:
        """Parse an optional integer out of a ToolResult's string metadata.

        Args:
            metadata: The ToolResult metadata mapping (string values only).
            key: The metadata key to parse.

        Returns:
            The parsed integer, or None if the key is absent or not a
            valid integer.
        """
        raw = metadata.get(key)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _save_web_search_summary_to_inbox(
        self,
        *,
        query: str,
        body: str,
        included_count: int | None,
        session_id: int | None,
    ) -> None:
        """Save one durable inbox entry for a successful web-search summary.

        Phase 20, Batch 2. Called only once, from the single success
        path of _handle_web_search_summary_request, after the exact
        JarvisResponse the CLI will return already exists. `body` is that
        response's own message text verbatim - disclosure label included,
        suggested-steps appendage included if present - never
        reconstructed separately, so the saved entry is always exactly
        what Nathan was shown.

        When self._inbox_store is None (the default, matching every
        other optional collaborator on this class), this is a no-op: no
        entry is saved, and the command behaves exactly as it did before
        Phase 20.

        A raising InboxStore.append() call is caught here and audited
        (never re-raised) - a failed save must never change, delay, or
        replace the response this method's caller has already built and
        is about to return.

        Args:
            query: The literal search query this entry is about, stored
                verbatim (Phase 20's own reasoned query-privacy decision -
                this is a user-facing store only Nathan ever reads, not
                the audit log).
            body: The exact final response text to store.
            included_count: The number of search results the summary was
                based on, if known.
            session_id: Optional session identifier for the audit trail.
        """
        if self._inbox_store is None:
            return

        try:
            self._inbox_store.append(
                source_type="web_search_summary",
                source_query=query,
                body=body,
                included_count=included_count,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001 - a save failure must never break the response
            self._audit_inbox_entry_creation(
                outcome=EventOutcome.FAILURE,
                detail=f"source_type=web_search_summary error={exc}",
                session_id=session_id,
            )
            return

        self._audit_inbox_entry_creation(
            outcome=EventOutcome.SUCCESS,
            detail="source_type=web_search_summary",
            session_id=session_id,
        )

    def _save_webpage_summary_to_inbox(
        self, *, url: str, body: str, session_id: int | None
    ) -> None:
        """Save one durable inbox entry for a successful, explicitly-
        requested webpage summary (Phase 61, Batch 1).

        Called only from _execute_approved_webpage_summary (and the
        currently-unreached immediate-GREEN fallback in
        _handle_webpage_summary_request), only when
        _should_save_webpage_summary_to_inbox() is True - i.e. only when
        the explicit "... and save to inbox" grammar was used - and only
        after the exact JarvisResponse the CLI will return already
        exists. `body` is that response's own message text verbatim -
        the "[AI webpage summary...]" disclosure label included - never
        the raw extracted webpage text, mirroring
        _save_web_search_summary_to_inbox's own body=response.message
        pattern exactly.

        When self._inbox_store is None (the default), this is a no-op:
        no entry is saved.

        A raising InboxStore.append() call is caught here and audited
        (never re-raised) - a failed save must never change, delay, or
        replace the response this method's caller has already built and
        is about to return, mirroring
        _save_web_search_summary_to_inbox's own failure-isolation
        guarantee exactly.

        Args:
            url: The webpage URL this entry is about, stored verbatim as
                source_query.
            body: The exact final response text to store - never raw
                webpage content.
            session_id: Optional session identifier for the audit trail.
        """
        if self._inbox_store is None:
            return

        try:
            self._inbox_store.append(
                source_type="webpage_summary",
                source_query=url,
                body=body,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001 - a save failure must never break the response
            self._audit_inbox_entry_creation(
                outcome=EventOutcome.FAILURE,
                detail=f"source_type=webpage_summary error={exc}",
                session_id=session_id,
            )
            return

        self._audit_inbox_entry_creation(
            outcome=EventOutcome.SUCCESS,
            detail="source_type=webpage_summary",
            session_id=session_id,
        )

    def _audit_inbox_entry_creation(
        self, *, outcome: EventOutcome, detail: str, session_id: int | None
    ) -> None:
        """Emit one inbox_entry_created/inbox_entry_creation_failed audit
        event, if a logger is configured.

        A new, narrow, genuinely distinct event (Phase 20, Batch 2) -
        never a duplication of _audit_web_search_summary_acquisition
        (which records the earlier *search* step's included/omitted
        counts) or AIRouter's own ai_call event (which records the
        *reasoning* step). This records only the separate *persistence*
        step's outcome. Never embeds the raw query or body text in the
        audit detail - only the source_type and, on failure, the
        exception message.

        When no logger is configured, this is a no-op. A raising logger
        is caught here so a failing audit event can never break the
        already-decided inbox-save outcome.

        Args:
            outcome: SUCCESS if the entry was saved, FAILURE otherwise.
            detail: A short, content-free detail string.
            session_id: Optional session identifier for the audit trail.
        """
        if self._logger is None:
            return

        try:
            self._logger.emit(
                source=_SOURCE,
                action_type="inbox_entry_created"
                if outcome is EventOutcome.SUCCESS
                else "inbox_entry_creation_failed",
                outcome=outcome,
                detail=detail,
                session_id=session_id,
            )
        except Exception:  # noqa: BLE001 - observability must never break execution
            pass

    def _audit_web_search_summary_acquisition(
        self, ingestion: object, session_id: int | None
    ) -> None:
        """Emit one web_search_summary_acquisition audit event, if a
        logger is configured.

        A new, narrow, genuinely distinct event (Phase 18, Batch 2) -
        never a duplication of WebSearchTool's own tool_call events
        (this path never invokes WebSearchTool/ToolExecutor at all) or
        of AIRouter's own ai_call event (which fires separately, for the
        subsequent reason() call). Never embeds the raw query text or
        any raw result content in the audit detail - only the outcome
        and the honest included/omitted counts.

        When no logger is configured, this is a no-op, matching how
        every other optional-audit call site in this class behaves
        without one. A raising logger is caught here so a failing audit
        event can never break the authoritative ingestion outcome
        already computed.

        Args:
            ingestion: The WebSearchIngestionResult to record.
            session_id: Optional session identifier for the audit trail.
        """
        if self._logger is None:
            return

        outcome = EventOutcome.SUCCESS if ingestion.success else EventOutcome.FAILURE
        detail = (
            f"included={ingestion.included_count} "
            f"omitted_for_size={ingestion.omitted_for_size}"
        )
        try:
            self._logger.emit(
                source=_SOURCE,
                action_type="web_search_summary_acquisition",
                outcome=outcome,
                detail=detail,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative ingestion outcome already computed.
            pass

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
                message=_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
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
            ai_unavailable_message=_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
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
                message=_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
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
            ai_unavailable_message=_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
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
                message=_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
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
            ai_unavailable_message=_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
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
                message=_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
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
            ai_unavailable_message=_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
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
                message=_MEMORY_SUMMARY_AI_REASONING_NOT_ENABLED_MESSAGE,
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
            ai_unavailable_message=_MEMORY_SUMMARY_AI_REASONING_UNAVAILABLE_MESSAGE,
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
        understood. The message points toward the "help" command (Phase 43)
        so the user can discover what Jarvis currently supports, rather than
        guessing at another unsupported phrasing.

        Args:
            plan: The (safe) plan that has no matching tool.

        Returns:
            A JarvisResponse explaining the missing capability, with the plan.
        """
        return JarvisResponse(
            success=False,
            message=(
                "Jarvis can plan this request, but does not yet have a tool to "
                "carry it out. More capability will be added in a later phase. "
                "Try 'help', 'list commands', or 'show commands' to see what "
                "Jarvis currently supports."
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
            # Phase 27, Batch 1: pass this request's own tool_name/tool_input
            # through to ApprovalManager so its execution state can be
            # durably persisted and safely resumed after a restart. This is
            # purely additive - create_request() defaults both to None, so
            # behaviour is unchanged for any caller (including
            # _confirmation_response below) that omits them, and the
            # JarvisResponse returned here still carries its own
            # tool_name/tool_input exactly as before, unaffected by whether
            # a pending_store is configured.
            approval = self._approvals.create_request(
                action=action,
                reason=result.error or "This action requires your confirmation.",
                security_tier=SecurityTier.YELLOW,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=dict(tool_input),
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
