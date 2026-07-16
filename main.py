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
    - Independently build the Phase 41 voice output service (see
      build_voice_output_service()) - another small, separate,
      best-effort composition step. With VOICE_ENABLED unset/false (the
      default), this always yields a disabled, provider-less service and
      changes nothing about how Jarvis runs.
    - Independently build the Phase 41, Batch 4 voice input service
      (see build_voice_input_service()) - the same pattern, for the
      input side. With VOICE_INPUT_ENABLED unset/false (the default),
      this always yields a disabled, provider-less service, and
      JarvisCLI._handle_voice_input_once() (not reachable from the
      interactive typed-input loop yet) remains a safe no-op.
    - Configure console logging (Phase 54, Batch 1) via
      observability.logging_setup.configure_console_logging(), called
      once, directly inside main() - never inside build_orchestrator(),
      so the many existing tests that call build_orchestrator() directly
      are completely unaffected. Idempotent: attaches at most one console
      handler to the "jarvis" app logger regardless of how many times
      it is called in a single process. Uses the already-validated
      settings.log_level (Phase 46) - no new setting.
    - Start the terminal CLI.

Does NOT:
    - Call the Claude API unless AI_REASONING_ENABLED=true (Phase 7, Batch 2).
    - Add phone support, a microphone, or real speech-to-text of any
      kind - no audio is ever captured anywhere in this project.
    - Construct a real text-to-speech or speech-to-text engine.
      VOICE_PROVIDER="fake"/VOICE_INPUT_PROVIDER="fake" (the only
      non-default values accepted today) only ever construct
      voice/tts.py's/voice/stt.py's own silent, audio-free fake
      providers - never real audio - and neither value is set by
      default.
    - Wire console logging into scheduler.py yet (Phase 54, Batch 2,
      not yet done) or into dashboard.py (which has no logging calls
      of any kind and is not part of this phase's scope at all).
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
from approval.pending_approval_store import PendingApprovalStore
from config.settings import load_settings
from core.command_router import CommandRouter
from core.orchestrator import JarvisOrchestrator
from inbox.inbox_store import InboxStore
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from notice.scheduled_inbox_notice import build_scheduled_inbox_notice
from notice.scheduled_inbox_notice_store import ScheduledInboxNoticeStore
from observability.logger import EventLogger
from observability.logging_setup import configure_console_logging
from planner.planner import Planner
from quarantine.quarantine_store import QuarantineStore
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
    ConfigTool,
    EchoTool,
    FileAppendTool,
    FileCopyTool,
    FileCreateTool,
    FileDeleteTool,
    FileListTool,
    FileMoveTool,
    FileReadTool,
    FileRestoreTool,
    FileSearchTool,
    HealthCheckTool,
    HelpTool,
    InfoTool,
    JarvisBrainStatusTool,
    MemoryForgetTool,
    MemoryTool,
    MemoryUpdateTool,
    QuarantineListTool,
    ScheduleCreateTool,
    ScheduleDisableTool,
    ScheduleEnableTool,
    ScheduleListTool,
    WebSearchTool,
    WebpageReadTool,
    WorkflowHistoryTool,
)
from tools.duckduckgo_search_provider import DuckDuckGoSearchProvider
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from ui.cli import JarvisCLI
from voice.input import VoiceInputService
from voice.output import VoiceOutputService
from voice.stt import FakeSpeechToTextProvider, SpeechToTextProvider
from voice.tts import FakeTextToSpeechProvider, TextToSpeechProvider
from web.safe_web_fetcher import SafeWebFetcher
from workflow.engine import WorkflowEngine
from workflow.paused_workflow_store import PausedWorkflowStore
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
    #
    # pending_approvals (Phase 27, Batch 1) durably persists the execution
    # state (tool_name/tool_input) of a pending YELLOW approval, so it can
    # survive a restart. This is a *different* table from approval_history
    # above - see pending_approval_store.py's own module docstring. Nothing
    # is reloaded from it yet here; reload_pending() is called explicitly,
    # below, only once the tool registry is fully populated.
    approval_history = ApprovalHistoryStore(session_factory)
    pending_approvals = PendingApprovalStore(session_factory)
    approvals = ApprovalManager(
        audit_logger=logger,
        history_store=approval_history,
        timeout_seconds=settings.approval_timeout_seconds,
        pending_store=pending_approvals,
    )

    # Planning.
    planner = Planner(security)

    # Tools, behind the security gate.
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    # HelpTool (Phase 43) returns a static, hand-maintained command list -
    # it takes no dependency, exactly like InfoTool above.
    registry.register_tool(HelpTool())
    # ConfigTool (Phase 31) reads only the already-loaded `settings`
    # object above - it never calls load_settings() again, never reads
    # .env/os.environ directly, and never exposes the API key's value.
    registry.register_tool(ConfigTool(settings))
    # QuarantineStore (Phase 37, Batch 1): records durable metadata
    # (original_path/quarantine_path) for every successful quarantine,
    # so a future restore command has trustworthy information to work
    # with, and lets QuarantineListTool display it (Phase 37, Batch 2).
    # Constructed once here and shared by all three quarantine-family
    # tools below (list/delete/restore) - never a second, separate
    # database connection.
    quarantine_store = QuarantineStore(session_factory)
    # QuarantineListTool (Phase 36; extended Phase 37, Batch 2) only
    # lists .jarvis_trash/'s current contents plus a read-only original-
    # path lookup - it never creates the directory, reads file content,
    # writes quarantine metadata, or modifies/moves/deletes anything.
    registry.register_tool(QuarantineListTool(quarantine_store))
    registry.register_tool(MemoryTool(memory))
    registry.register_tool(MemoryUpdateTool(memory))
    registry.register_tool(MemoryForgetTool(memory))
    registry.register_tool(FileListTool())
    registry.register_tool(FileReadTool())
    registry.register_tool(FileSearchTool())
    registry.register_tool(FileCreateTool())
    registry.register_tool(FileAppendTool())
    registry.register_tool(FileCopyTool())
    registry.register_tool(FileMoveTool())
    registry.register_tool(FileDeleteTool(quarantine_store))
    # FileRestoreTool (Phase 38): restores one quarantined file back to
    # its recorded original_path - reuses the same shared quarantine_store
    # instance above, never a second QuarantineStore/database connection.
    registry.register_tool(FileRestoreTool(quarantine_store))
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

    # Webpage read (Phase 33, Batch 1): the first tool built on Phase
    # 32's fetch/read safety foundation. YELLOW - unlike WebSearchTool
    # above, this sends a network request to an arbitrary, Nathan-
    # supplied target rather than one fixed, vetted provider. Depends
    # only on SafeWebFetcher/extract_text_from_fetched_page; no AI,
    # workflow, scheduler, dashboard, or Inbox integration exists here
    # or anywhere else in this phase.
    web_fetcher = SafeWebFetcher()
    registry.register_tool(WebpageReadTool(web_fetcher))

    # HealthCheckTool (Phase 57): registered last, so its own
    # introspection of `registry` naturally sees every tool registered
    # above (and itself) once it actually runs. Reads only already-built
    # objects - `registry`, `settings`, and the same
    # quarantine_store/inbox_store/schedule_store/security/memory/
    # approval_history/workflow_history instances constructed above for
    # other tools' use - never opens a new database connection, never
    # constructs a new store or SecurityManager, never creates a file
    # or row.
    registry.register_tool(
        HealthCheckTool(
            registry,
            settings,
            inbox_store,
            schedule_store,
            quarantine_store,
            security,
            memory,
            approval_history,
            workflow_history,
        )
    )

    # JarvisBrainStatusTool (Phase 86, Batch 1): reads only the same
    # already-built `registry`, `settings`, `memory`, `approval_history`,
    # and `workflow_history` instances constructed above for other
    # tools' use - never opens a new database connection, never
    # constructs a new store, never calls AI or a subprocess.
    registry.register_tool(
        JarvisBrainStatusTool(
            registry,
            settings,
            memory,
            approval_history,
            workflow_history,
        )
    )

    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=logger,
    )

    # Phase 27, Batch 1: reload any pending approval persisted before a
    # previous restart, now that every tool above is registered. Each row
    # is independently revalidated against this live registry/security
    # before being treated as pending again - see
    # ApprovalManager.reload_pending()'s own docstring for the full
    # fail-closed reasoning. Never executes anything by itself.
    approvals.reload_pending(registry=registry, security_manager=security)

    # Command routing (Phase 7, Batch 1): matches request text to a
    # registered tool and builds its input. Extracted from the orchestrator
    # so the Core coordinates rather than performing command-matching itself.
    command_router = CommandRouter(registry)

    # Durable paused-workflow operational state (Phase 27, Batch 2). A
    # *different* table from workflow_history above - see
    # paused_workflow_store.py's own module docstring. Nothing is
    # reloaded from it until reload_paused() is called explicitly below,
    # after workflow_engine exists and after pending approvals have
    # already been reloaded - reload_paused()'s own revalidation depends
    # on that order.
    paused_workflows = PausedWorkflowStore(session_factory)

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
        paused_store=paused_workflows,
        # Durable Workflow Lifecycle Foundation: the same WorkflowHistoryStore
        # instance already built above (not a second one) - so every
        # workflow_* transition WorkflowEngine already emits as an audit
        # event is additionally recorded durably, queryable via the
        # workflow_history tool registered above.
        history=workflow_history,
    )

    # Phase 27, Batch 2: reload any paused workflow persisted before a
    # previous restart, now that workflow_engine exists. Must run AFTER
    # approvals.reload_pending() above - each paused workflow's own
    # revalidation checks whether its linked approval is still genuinely
    # pending in the already-reloaded `approvals` instance. Never resumes
    # or executes anything by itself - see
    # WorkflowEngine.reload_paused()'s own docstring for the full
    # fail-closed reasoning.
    workflow_engine.reload_paused(registry=registry, security_manager=security)

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


def build_voice_output_service() -> tuple[VoiceOutputService, bool]:
    """Independently build the Phase 41 voice output service.

    Mirrors build_startup_notice()'s own pattern: loads Settings a
    second, independent time rather than changing build_orchestrator()'s
    widely-depended-on return type for this narrow, unrelated addition.

    With VOICE_ENABLED unset/false and VOICE_PROVIDER unset/"none" (both
    defaults), this always returns a disabled, provider-less service and
    speak_responses=False - Jarvis's runtime behaviour is unchanged.
    VOICE_PROVIDER="fake" only ever constructs voice/tts.py's own
    silent, audio-free FakeTextToSpeechProvider - no real TTS engine
    exists yet (docs/phase_41_implementation_plan.md).

    Never raises: any failure while loading settings falls back to a
    disabled, provider-less service, so a problem here can never
    prevent Jarvis from starting.

    Returns:
        A tuple of (the VoiceOutputService to hand to JarvisCLI, whether
        the CLI should actually attempt to speak each response - True
        only when VOICE_SPEAK_MODE="all").
    """
    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001 - a failing settings load must never block startup
        return VoiceOutputService(), False

    provider: TextToSpeechProvider | None = None
    if settings.voice_provider == "fake":
        provider = FakeTextToSpeechProvider()

    service = VoiceOutputService(provider=provider, enabled=settings.voice_enabled)
    speak_responses = settings.voice_speak_mode == "all"
    return service, speak_responses


def build_voice_input_service() -> VoiceInputService:
    """Independently build the Phase 41, Batch 4 voice input service.

    Mirrors build_voice_output_service()'s own pattern: loads Settings a
    second, independent time rather than changing build_orchestrator()'s
    widely-depended-on return type for this narrow, unrelated addition.

    With VOICE_INPUT_ENABLED unset/false and VOICE_INPUT_PROVIDER
    unset/"none" (both defaults), this always returns a disabled,
    provider-less service - Jarvis's runtime behaviour is unchanged, and
    JarvisCLI._handle_voice_input_once() (not reachable from the
    interactive typed-input loop yet) remains a safe no-op.
    VOICE_INPUT_PROVIDER="fake" only ever constructs voice/stt.py's own
    silent, microphone-free FakeSpeechToTextProvider - no real STT
    engine, and no microphone or recording mechanism of any kind, exists
    yet (docs/phase_41_implementation_plan.md).

    Never raises: any failure while loading settings falls back to a
    disabled, provider-less service, so a problem here can never
    prevent Jarvis from starting.

    Returns:
        The VoiceInputService to hand to JarvisCLI.
    """
    try:
        settings = load_settings()
    except Exception:  # noqa: BLE001 - a failing settings load must never block startup
        return VoiceInputService()

    provider: SpeechToTextProvider | None = None
    if settings.voice_input_provider == "fake":
        provider = FakeSpeechToTextProvider()

    return VoiceInputService(provider=provider, enabled=settings.voice_input_enabled)


def main() -> None:
    """Build the system and start the interactive CLI."""
    orchestrator = build_orchestrator()
    startup_notice = build_startup_notice()
    voice_output, speak_responses = build_voice_output_service()
    voice_input = build_voice_input_service()
    # Phase 54, Batch 1: console logging is configured here, directly in
    # the real process entry point - never inside build_orchestrator(),
    # so the many existing tests that call build_orchestrator() directly
    # are never affected. Idempotent - see configure_console_logging()'s
    # own docstring.
    configure_console_logging(load_settings())
    cli = JarvisCLI(
        orchestrator,
        startup_notice=startup_notice,
        voice_output=voice_output,
        speak_responses=speak_responses,
        voice_input=voice_input,
    )
    cli.run()


if __name__ == "__main__":
    main()