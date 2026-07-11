"""
scheduled_summary_runner.py

Narrow, trust-safe execution helper for exactly one action - run a
scheduled web-search summary and, on genuine success, save it to the
Inbox (Phase 21, Batch 2).

Responsibilities:
    - Given a schedule's stored query, perform the search (reusing the
      existing, unchanged ai.web_search_ingestion.ingest_web_search_for_ai
      exactly as the interactive command does).
    - Combine the query with the search results into ONE new UNTRUSTED
      AIContextBlock - never modifying ai/web_search_ingestion.py itself.
    - Call AIReasoningEngine.reason() with a FIXED, Jarvis-authored
      user_input - never the stored query.
    - On a validated success, append one Inbox entry with
      source_type="scheduled_web_search_summary".
    - Emit narrow, metadata-only audit events for the succeeded/failed
      outcome.

Does NOT:
    - Treat the stored query as live user input. It is used only (a) as
      a WebSearchProvider.search() parameter (unchanged from the
      interactive path), and (b) as a labelled line INSIDE the UNTRUSTED
      context text - unlike the interactive command's own `user_message`
      (which is never injection-scanned, because its whole design
      assumption is "a live human is typing this right now"), the query
      here goes through the exact same PromptBuilder.build() injection
      scan every other UNTRUSTED context already receives. This is a
      stricter posture than the interactive path, deliberately, because
      no live human confirms a scheduled run each time it fires.
    - Reuse or modify core.orchestrator._handle_web_search_summary_request.
      This is a wholly separate code path; the interactive command's
      behaviour and code are completely unaffected by this module's
      existence.
    - Import CommandRouter, ToolExecutor, ApprovalManager, or
      WorkflowEngine. There is no live command to route and no approval
      to gate - the schedule was already approved (YELLOW) at creation
      time, through the ordinary tool pipeline.
    - Create an Inbox entry from a failed search, zero results, a failed/
      unavailable/invalid AI response, or a failed Inbox write. Only a
      genuinely successful, validated summary is ever saved.
    - Run the interactive path's unexpected-action policy
      (_evaluate_unexpected_actions). That policy compares an AI
      suggestion against a request's own Plan-derived expected scope,
      which has no equivalent for a scheduled run (there is no live
      Plan to compare against - the scope is always exactly "run this
      one search summary"). This is a disclosed, narrow omission, not a
      new authority: an AI-suggested action remains exactly as inert
      here as it is everywhere else in this project - plain text folded
      into the stored summary, never executable, whether or not this
      particular audit signal fires for it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.context_models import AIContextBlock
from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import AIReasoningRequest
from ai.web_search_ingestion import ingest_web_search_for_ai
from core.orchestrator import _WEB_SEARCH_SUMMARY_LABEL
from inbox.inbox_store import InboxStore
from tools.web_search_provider import WebSearchProvider

_SOURCE = "scheduled_summary_runner"

#: Fixed, Jarvis-authored instruction - never the stored query. This is
#: the entire point of the trust-boundary fix this module exists for:
#: nothing stored/replayed ever occupies the live-input prompt slot.
_FIXED_USER_INPUT = "Summarise the following web search results."

#: The scheduler-produced Inbox entries' own source_type - a distinct,
#: honest value from the interactive path's "web_search_summary", so
#: Nathan (and the dashboard) can always tell an overnight, unattended
#: result apart from one he asked for directly. No schema change: the
#: column already accepts any string.
SCHEDULED_SOURCE_TYPE = "scheduled_web_search_summary"


@dataclass(frozen=True, slots=True)
class ScheduledSummaryOutcome:
    """The result of one attempted scheduled web-search-summary run.

    Attributes:
        success: True only if a real, validated AI summary was produced
            and successfully saved to the Inbox.
        stage: Which stage the run reached - "search", "ai", or
            "inbox_write" - useful for logging/debugging. None on
            success.
        reason: A short, human-readable failure reason, for logging only
            - never stored in the Inbox and never containing raw query
            or result content.
    """

    success: bool
    stage: str | None = None
    reason: str | None = None


def run_scheduled_web_search_summary(
    *,
    schedule_id: int,
    query: str,
    provider: WebSearchProvider,
    reasoning: AIReasoningEngine,
    inbox: InboxStore,
    logger: object | None = None,
) -> ScheduledSummaryOutcome:
    """Run one scheduled web-search summary and save it to the Inbox.

    Called only after ScheduleStore.claim_due() has already succeeded for
    this schedule_id - this function has no opinion about whether a
    schedule is due; it only performs the one hard-coded action.

    Args:
        schedule_id: The schedule this run belongs to, for audit context
            only (never used to look anything up here).
        query: The schedule's literal stored query, used only as a
            search parameter and as scanned UNTRUSTED context text.
        provider: The WebSearchProvider to search with.
        reasoning: The AIReasoningEngine to summarise with.
        inbox: The InboxStore to save a successful result to.
        logger: Optional audit logger. A no-op when None; a raising
            logger is caught and never allowed to affect the outcome.

    Returns:
        A ScheduledSummaryOutcome describing whether a real Inbox entry
        was saved.
    """
    ingestion = ingest_web_search_for_ai(provider, query)
    if not ingestion.success:
        _audit_failure(logger, schedule_id, stage="search", error=ingestion.error)
        return ScheduledSummaryOutcome(
            success=False, stage="search", reason=ingestion.error
        )

    # The query rides along as UNTRUSTED, scanned data - never the
    # unscanned user_message/live-input slot. A fresh AIContextBlock is
    # built here (not inside ai/web_search_ingestion.py, which is left
    # completely unmodified) so the interactive command's own context
    # shape is untouched.
    combined_text = f"Search query: {query}\n\n{ingestion.context.text}"
    context = AIContextBlock.from_untrusted(
        combined_text, source=f"scheduled-web-search:schedule_id={schedule_id}"
    )

    request = AIReasoningRequest(
        user_input=_FIXED_USER_INPUT,
        context_block=context,
        session_id=None,
    )
    result = reasoning.reason(request)
    if result is None:
        _audit_failure(logger, schedule_id, stage="ai", error="AI reasoning unavailable")
        return ScheduledSummaryOutcome(
            success=False, stage="ai", reason="AI reasoning unavailable"
        )

    summary = result.summary
    if result.has_suggestions:
        steps = "; ".join(action.description for action in result.suggested_actions)
        summary = f"{result.summary} Suggested steps: {steps}"

    body = f"{_WEB_SEARCH_SUMMARY_LABEL} {summary}"

    try:
        inbox.append(
            source_type=SCHEDULED_SOURCE_TYPE,
            source_query=query,
            body=body,
            included_count=ingestion.included_count,
            session_id=None,
        )
    except Exception as exc:  # noqa: BLE001 - a save failure must be reported, not raised
        _audit_failure(logger, schedule_id, stage="inbox_write", error=str(exc))
        return ScheduledSummaryOutcome(success=False, stage="inbox_write", reason=str(exc))

    _audit_success(logger, schedule_id, included_count=ingestion.included_count)
    return ScheduledSummaryOutcome(success=True)


def _audit_success(logger: object | None, schedule_id: int, *, included_count: int | None) -> None:
    """Emit one scheduled_summary_succeeded audit event, if configured.

    Never embeds the query or body - only the schedule id and the
    content-free included_count, mirroring Phase 20's own
    inbox_entry_created convention.
    """
    if logger is None:
        return
    try:
        logger.emit(  # type: ignore[attr-defined]
            source=_SOURCE,
            action_type="scheduled_summary_succeeded",
            outcome="success",
            detail=f"schedule_id={schedule_id} included={included_count}",
            session_id=None,
        )
    except Exception:  # noqa: BLE001 - observability must never break execution
        pass


def _audit_failure(
    logger: object | None, schedule_id: int, *, stage: str, error: object
) -> None:
    """Emit one scheduled_summary_failed audit event, if configured.

    Never embeds the query - only the schedule id, the stage reached,
    and the error message (a controlled, human-readable failure reason,
    never raw search-result content or AI output).
    """
    if logger is None:
        return
    try:
        logger.emit(  # type: ignore[attr-defined]
            source=_SOURCE,
            action_type="scheduled_summary_failed",
            outcome="failure",
            detail=f"schedule_id={schedule_id} stage={stage} error={error}",
            session_id=None,
        )
    except Exception:  # noqa: BLE001 - observability must never break execution
        pass
