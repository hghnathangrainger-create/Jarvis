"""
scheduler.py

Entry point for the independent web-search-summary scheduler runner
(Phase 21, Batch 2).

Responsibilities:
    - Load configuration and open the same configured SQLite-backed
      Jarvis database main.py/dashboard.py use, independently.
    - Construct ScheduleStore, InboxStore, a DuckDuckGoSearchProvider,
      and (when AI reasoning is enabled) an AIRouter/AIReasoningEngine.
    - Poll on a modest interval; for each enabled schedule, atomically
      claim it if due, and if claimed, run the one hard-coded scheduled
      web-search-summary action via scheduling.scheduled_summary_runner.

Does NOT:
    - Import or depend on main.py, JarvisOrchestrator, JarvisCLI,
      CommandRouter, ToolExecutor, ApprovalManager, or WorkflowEngine.
      There is no live command to route and no approval to gate here -
      a schedule was already approved (YELLOW) when it was created,
      through the ordinary tool pipeline.
    - Require the Jarvis CLI process to be running. This is a wholly
      separate local process that shares only the SQLite database file
      on disk with main.py/dashboard.py - no IPC, no socket, no shared
      Python objects.
    - Live inside dashboard.py, or give the dashboard any write
      capability - the dashboard remains a wholly separate, read-only
      process/module, untouched by this file.
    - Execute more than one hard-coded action type. There is no
      action_type dispatch here - every claimed schedule runs the exact
      same scheduled-web-search-summary-to-Inbox call.
    - Configure console logging anywhere but main() (Phase 54, Batch 2).
      observability.logging_setup.configure_console_logging() is called
      once, directly inside main(), independently of build_components()
      - never inside build_components() itself, so every existing test
      that calls build_components() directly is unaffected. Idempotent,
      matching main.py's own Batch 1 wiring exactly: attaches at most
      one console handler to the "jarvis" app logger regardless of how
      many times main() runs in a process. Uses the already-validated
      settings.log_level (Phase 46) - no new setting.

Run with:
    poetry run python scheduler.py
"""

from __future__ import annotations

import time
from typing import Protocol

from ai.prompt_builder import PromptBuilder, audit_suspicious_injection
from ai.providers.claude import ClaudeProvider
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.settings import load_settings
from inbox.inbox_store import InboxStore
from observability.logger import EventLogger
from observability.logging_setup import configure_console_logging
from scheduling.schedule_store import ScheduleStore
from scheduling.scheduled_summary_runner import run_scheduled_web_search_summary
from security.audit_log import AuditLog
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from tools.duckduckgo_search_provider import DuckDuckGoSearchProvider
from tools.web_search_provider import WebSearchProvider

#: How often the runner checks for due schedules. Frequent enough that a
#: schedule's time_of_day is honoured within a minute; infrequent enough
#: to be a trivial resource cost.
_POLL_INTERVAL_SECONDS = 60

_SOURCE = "scheduler"


class _AuditLogger(Protocol):
    def emit(self, **kwargs: object) -> str: ...


def build_components() -> tuple[
    ScheduleStore, InboxStore, WebSearchProvider, AIReasoningEngine | None, _AuditLogger
]:
    """Assemble the components this runner needs, independently of main.py.

    Mirrors dashboard.py's own composition-root pattern exactly: its own
    engine, its own session factory, its own store instances - nothing is
    shared with, or depends on, main.py's own instances.

    Returns:
        A tuple of (schedule_store, inbox_store, search_provider,
        reasoning_engine, logger). reasoning_engine is None when AI
        reasoning is not enabled - matching main.py's own honest default.
    """
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    logger = EventLogger(AuditLog(session_factory))
    schedule_store = ScheduleStore(session_factory)
    inbox_store = InboxStore(session_factory)
    search_provider = DuckDuckGoSearchProvider()

    reasoning_engine: AIReasoningEngine | None = None
    if settings.ai_reasoning_enabled:
        ai_router = AIRouter(
            provider=ClaudeProvider(settings),
            prompt_builder=PromptBuilder(
                report_injection=audit_suspicious_injection(logger)
            ),
            validator=ResponseValidator(),
            logger=logger,
            settings=settings,
        )
        reasoning_engine = AIReasoningEngine(router=ai_router, enabled=True)

    return schedule_store, inbox_store, search_provider, reasoning_engine, logger


def run_one_poll_cycle(
    schedule_store: ScheduleStore,
    inbox_store: InboxStore,
    search_provider: WebSearchProvider,
    reasoning_engine: AIReasoningEngine | None,
    logger: _AuditLogger | None,
    *,
    now=None,
) -> int:
    """Run exactly one pass over all schedules, claiming and running due ones.

    Exposed as a standalone, single-pass function - never folded into
    the infinite loop itself - so tests can invoke exactly one poll
    cycle deterministically, with a simulated `now`, without depending on
    the real system clock or an infinite loop.

    If AI reasoning is not enabled at all, this returns immediately
    without claiming anything: nothing could succeed regardless of which
    schedule is picked, and not claiming means every due schedule remains
    eligible to catch up the same day once AI becomes available. This is
    deliberately different from a per-schedule failure *after* a
    successful claim (search down, AI call failing for one run) - that
    is a transient failure that correctly consumes the day's attempt
    (see scheduling.scheduled_summary_runner), not a global precondition.

    A malformed/corrupt schedule row, or a raising claim_due call, is
    caught per-schedule so it can never crash the whole poll cycle for
    other schedules.

    Args:
        schedule_store: The store to read schedules from and claim with.
        inbox_store: The store a successful run saves its result to.
        search_provider: The WebSearchProvider to search with.
        reasoning_engine: The AIReasoningEngine to summarise with, or
            None if AI reasoning is not enabled.
        logger: Optional audit logger.
        now: The UTC-aware instant to treat as "the current moment" for
            every schedule this pass considers. Defaults to the real
            current time when None.

    Returns:
        The number of schedules successfully run this pass.
    """
    if reasoning_engine is None:
        return 0

    ran = 0
    for schedule in schedule_store.list_all():
        try:
            claimed = schedule_store.claim_due(schedule.id, now=now)
        except Exception:  # noqa: BLE001 - one bad row must not crash the poll cycle
            continue
        if not claimed:
            continue

        _audit_claimed(logger, schedule.id)
        outcome = run_scheduled_web_search_summary(
            schedule_id=schedule.id,
            query=schedule.query,
            provider=search_provider,
            reasoning=reasoning_engine,
            inbox=inbox_store,
            logger=logger,
        )
        if outcome.success:
            ran += 1
    return ran


def _audit_claimed(logger: _AuditLogger | None, schedule_id: int) -> None:
    """Emit one schedule_claimed audit event, if a logger is configured.

    Never embeds the query - only the schedule id.
    """
    if logger is None:
        return
    try:
        logger.emit(
            source=_SOURCE,
            action_type="schedule_claimed",
            outcome="success",
            detail=f"schedule_id={schedule_id}",
            session_id=None,
        )
    except Exception:  # noqa: BLE001 - observability must never break execution
        pass


def main() -> None:
    """Build components and poll for due schedules indefinitely."""
    schedule_store, inbox_store, search_provider, reasoning_engine, logger = (
        build_components()
    )
    # Phase 54, Batch 2: console logging is configured here, directly in
    # the real process entry point - never inside build_components(), so
    # every existing test that calls build_components() directly is
    # unaffected. Idempotent - see configure_console_logging()'s own
    # docstring. Mirrors main.py's own Batch 1 wiring exactly.
    configure_console_logging(load_settings())
    while True:
        run_one_poll_cycle(
            schedule_store, inbox_store, search_provider, reasoning_engine, logger
        )
        time.sleep(_POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
