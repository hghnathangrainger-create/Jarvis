"""
main.py

Entry point for the Jarvis AI Operating System (Phase 1).

Responsibilities:
    - Load configuration.
    - Initialise the database and storage layer.
    - Wire together every Phase 1 subsystem: Observability, Security, Memory,
      Planner, Tool Manager, and the Core orchestrator.
    - Register the built-in tools.
    - Independently build the Phase 22 CLI startup notice (see
      build_startup_notice()) - a small, separate composition step, not
      part of build_orchestrator()'s own wiring.
    - Start the terminal CLI.

Does NOT:
    - Call the Claude API unless AI_REASONING_ENABLED=true (Phase 7, Batch 2);
      add voice or phone support.
    - Contain any business logic; it only assembles the system and starts it.

This module is the single composition root for Phase 1. It is the one place
where concrete components are created and connected, which keeps every other
module free of wiring concerns and easy to test in isolation.
"""

from __future__ import annotations

from ai.prompt_builder import PromptBuilder, audit_suspicious_injection
from ai.providers.claude import ClaudeProvider
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from approval.approval_history_store import ApprovalHistoryStore
from approval.approval_manager import ApprovalManager
from config.settings import load_settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from inbox.inbox_store import InboxStore
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from notice.scheduled_inbox_notice import build_scheduled_inbox_notice
from notice.scheduled_inbox_notice_store import ScheduledInboxNoticeStore
from observability.logger import EventLogger
from planner.planner import Planner
from security.audit_log import AuditLog
from security.security_manager import SecurityManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from scheduling.schedule_store import ScheduleStore
from tools.builtin import (
    ApprovalHistoryTool,
    EchoTool,
    FileAppendTool,
    FileCreateTool,
    FileListTool,
    FileReadTool,
    InfoTool,
    MemoryForgetTool,
    MemoryTool,
    MemoryUpdateTool,
    ScheduleCreateTool,
    ScheduleDisableTool,
    ScheduleEnableTool,
    ScheduleListTool,
    WebSearchTool,
    WorkflowHistoryTool,
)
from tools.duckduckgo_search_provider import DuckDuckGoSearchProvider
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI
from workflow.engine import WorkflowEngine
from workflow.workflow_history_store import WorkflowHistoryStore


def build_orchestrator() -> JarvisOrchestrator:
    """Assemble and return a fully wired Jarvis Core orchestrator.

    This is the composition root: it loads settings, prepares storage, and
    constructs and connects every Phase 1 subsystem. It is exposed as a
    function so that the same wiring can be reused by scripts and tests.

    Returns:
        A ready-to-use JarvisOrchestrator.
    """
    settings = load_settings()

    engine = create_database_engine(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    # Observability and security.
    logger = EventLogger(AuditLog(session_factory))
    security = SecurityManager()

    # Memory.
    memory = MemoryManager(EpisodicMemoryStore(session_factory))

    # Durable, read-only approval history (Phase 6, Batch 1). This store only
    # ever records what already happened; it has no tool_name or tool_input
    # columns, so nothing here can be replayed. The ApprovalManager built from
    # it is passed into the orchestrator below - previously the orchestrator
    # silently built its own disconnected default, so approve/decline
    # decisions were reaching neither the audit log nor any durable history.
    # That gap is fixed here, and only here: no approval behaviour changes.
    #
    # timeout_seconds enables YELLOW approval-window expiry (Phase 6,
    # Batch 3): a pending YELLOW request unanswered for this many seconds
    # expires (ApprovalStatus.EXPIRED), never RED, and never as a decision.
    approval_history = ApprovalHistoryStore(session_factory)
    approvals = ApprovalManager(
        audit_logger=logger,
        history_store=approval_history,
        timeout_seconds=settings.approval_timeout_seconds,
    )

    # Planning.
    planner = Planner(security)

    # Tools, behind the security gate.
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryUpdateTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
    registry.register_tool(FileCreateTool())
    registry.register_tool(FileAppendTool())
    registry.register_tool(ApprovalHistoryTool(approval_history))

    # Durable workflow lifecycle history (Durable Workflow Lifecycle
    # Foundation - a prerequisite turn, not a numbered phase). Mirrors
    # approval_history immediately above: a durable, read-only record of
    # what already happened, correlated by workflow_id. The same store
    # instance is reused by both WorkflowEngine (which writes to it) and
    # this read-only tool - never two separately constructed stores.
    workflow_history = WorkflowHistoryStore(session_factory)
    registry.register_tool(WorkflowHistoryTool(workflow_history))

    # Durable inbox (Phase 20, Batch 1/2): a durable, append-only record of
    # saved Jarvis-produced outputs - today, exactly one producer, the
    # "summarise web search for <query>" advisory summary. No tool is
    # registered for it: it is written directly by the orchestrator (below)
    # and read directly by the dashboard's own read model, never through
    # ToolExecutor.
    inbox_store = InboxStore(session_factory)

    # Durable web-search-summary schedules (Phase 21, Batch 1): storage
    # and CRUD only - creating, listing, enabling, and disabling a
    # schedule row. Unlike inbox_store above, schedule management IS
    # registered as ordinary tools, since schedule creation/enable/
    # disable are plain durable writes (like "remember this"), not an AI
    # reasoning call - they go through the exact same, unmodified
    # CommandRouter/ToolExecutor/SecurityManager/ApprovalManager pipeline
    # every other write tool already uses. No runner/claim/execution
    # logic exists yet; this batch never performs a search, calls AI, or
    # writes an Inbox entry.
    schedule_store = ScheduleStore(session_factory)
    registry.register_tool(ScheduleCreateTool(schedule_store))
    registry.register_tool(ScheduleListTool(schedule_store))
    registry.register_tool(ScheduleEnableTool(schedule_store))
    registry.register_tool(ScheduleDisableTool(schedule_store))

    # Web search (Phase 16): Jarvis's first external-network tool.
    # Read-only, GREEN, and deliberately provider-independent - this is
    # the only place a concrete search vendor (DuckDuckGo) is constructed.
    # WebSearchTool itself depends only on the WebSearchProvider
    # abstraction, never this concrete type directly. The same instance
    # is reused by the "summarise web search for <query>" AI workflow
    # (Phase 18, Batch 2) below - never a second, separately constructed
    # provider.
    web_search_provider = DuckDuckGoSearchProvider()
    registry.register_tool(WebSearchTool(web_search_provider))
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,
    )

    # Command routing (Phase 7, Batch 1): matches request text to a
    # registered tool and builds its input. Extracted from the orchestrator
    # so the Core coordinates rather than performing command-matching itself.
    command_router = CommandRouter(registry)

    # Sequential Workflow Engine (Phase 15, Batch 2/3): reuses the exact same
    # ToolExecutor, ApprovalManager, and EventLogger instances already built
    # above - no duplicate execution, approval, or logging authority is ever
    # constructed. Powers only the two explicit Phase 15 workflow commands
    # ("remember this and show it back: <text>" / "remember this and forget
    # it: <text>"); every other request path is completely unaffected.
    workflow_engine = WorkflowEngine(
        executor=executor,
        approvals=approvals,
        logger=logger,
        # Durable Workflow Lifecycle Foundation: the same WorkflowHistoryStore
        # instance already built above (not a second one) - so every
        # workflow_* transition WorkflowEngine already emits as an audit
        # event is additionally recorded durably, queryable via the
        # workflow_history tool registered above.
        history=workflow_history,
    )

    # Advisory AI reasoning (Phase 7, Batch 2): reachable only when
    # AI_REASONING_ENABLED=true. This is the only place a real AIRouter and
    # AIReasoningEngine are constructed - previously main.py never built
    # either, so the flag had no effect on the running application no matter
    # how it was set. With the flag false or unset (the default), reasoning
    # stays None here exactly as it silently always has: no new behaviour,
    # no new AI authority, nothing bypasses the Security Manager or Tool
    # Executor - the engine remains strictly advisory either way.
    reasoning_engine: AIReasoningEngine | None = None
    if settings.ai_reasoning_enabled:
        ai_router = AIRouter(
            provider=ClaudeProvider(settings),
            # Phase 7, Batch 5A: a suspicious injection scan is now audited
            # through the same real logger, closing the gap where a
            # detected pattern was never reported anywhere.
            prompt_builder=PromptBuilder(
                report_injection=audit_suspicious_injection(logger)
            ),
            validator=ResponseValidator(),
            logger=logger,
            settings=settings,
        )
        reasoning_engine = AIReasoningEngine(router=ai_router, enabled=True)

    return JarvisOrchestrator(
        planner=planner,
        executor=executor,
        registry=registry,
        command_router=command_router,
        approval_manager=approvals,
        reasoning_engine=reasoning_engine,
        security_manager=security,
        # Phase 9, Batch 2: the same MemoryManager instance already built
        # above (not a second one) is passed through so the explicit
        # "summarise memory <id>" workflow can retrieve a memory directly,
        # exactly as the plan requires.
        memory_manager=memory,
        # Phase 15, Batch 3: the same WorkflowEngine instance already built
        # above (not a second one) powers the two explicit workflow commands.
        workflow_engine=workflow_engine,
        # Phase 18, Batch 2: the same WebSearchProvider instance already
        # built above (not a second one) powers the explicit "summarise
        # web search for <query>" AI-summary workflow, called directly -
        # never through WebSearchTool/ToolExecutor.
        web_search_provider=web_search_provider,
        # Phase 20, Batch 2: the same InboxStore instance already built
        # above (not a second one) lets the web-search-summary workflow
        # save a durable copy of its own successful advisory summary.
        inbox_store=inbox_store,
        logger=logger,
    )


def build_startup_notice() -> str | None:
    """Independently build the Phase 22 CLI startup notice, or None.

    Mirrors dashboard.py/scheduler.py's own composition-root pattern: a
    second, independent engine/session_factory over the same configured
    SQLite file, never sharing state with build_orchestrator()'s own
    engine - so build_orchestrator()'s widely-depended-on return type
    (reused by 26 existing test files) never needs to change for this
    narrow, unrelated addition.

    Never raises: any failure while opening this second connection is
    caught here too, so a problem with this purely-informational check
    can never prevent the primary orchestrator/database connection
    (already established by build_orchestrator()) from starting Jarvis.

    Returns:
        A single, content-free notice line, or None when there is
        nothing to report or this check could not run.
    """
    try:
        settings = load_settings()
        engine = create_database_engine(settings)
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        inbox_store = InboxStore(session_factory)
        notice_store = ScheduledInboxNoticeStore(session_factory)
        return build_scheduled_inbox_notice(inbox_store, notice_store)
    except Exception:  # noqa: BLE001 - a failing notice check must never block startup
        return None


def main() -> None:
    """Build the system and start the interactive CLI."""
    orchestrator = build_orchestrator()
    startup_notice = build_startup_notice()
    cli = JarvisCLI(orchestrator, startup_notice=startup_notice)
    cli.run()


if __name__ == "__main__":
    main()