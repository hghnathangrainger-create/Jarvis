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
    - Acquire the OS-enforced execution-process lock and run startup
      recovery (Approval-to-Resume Handoff Interlock, Batch 2 -
      docs/phase_98_approval_handoff_plan.md), via start_execution_session()
      and reconcile_claimed_handoffs() - both called only from main(),
      never from build_orchestrator() itself, so build_orchestrator()'s
      own 100+ existing test callers (including the two restart-
      simulation tests that call it twice in one process) remain
      completely unaffected.

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

from dataclasses import dataclass
from datetime import datetime, timezone

from ai.prompt_builder import PromptBuilder, audit_suspicious_injection
from ai.providers.claude import ClaudeProvider
from ai.reasoning_engine import AIReasoningEngine
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from approval.approval_history_store import ApprovalHistoryStore
from approval.approval_manager import ApprovalManager
from approval.approval_models import PendingApprovalHandoffStatus
from approval.pending_approval_store import PendingApprovalStore
from config.settings import load_settings
from core.command_router import CommandRouter
from core.compound_workflow import (
    reconcile_claimed_compound_workflows,
    repair_or_isolate_pending_compound_progress,
    terminalize_declined_or_expired_compound_progress,
)
from core.orchestrator import JarvisOrchestrator
from core.schedule_compound_workflow import (
    reconcile_claimed_schedule_compound_workflows,
    repair_or_isolate_pending_schedule_compound_progress,
    terminalize_declined_or_expired_schedule_compound_progress,
)
from inbox.inbox_store import InboxStore
from intelligence.context import ContextAssembler
from intelligence.verified_action_context import VerifiedActionContextBuilder
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from notice.scheduled_inbox_notice import build_scheduled_inbox_notice
from notice.scheduled_inbox_notice_store import ScheduledInboxNoticeStore
from observability.logger import EventLogger
from observability.logging_setup import configure_console_logging
from planner.planner import Planner
from project_state.project_state_store import ProjectStateStore
from quarantine.quarantine_store import QuarantineStore
from runtime.process_lock import ExecutionLockError, ExecutionProcessLock
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
    PreparePromptTool,
    ProjectStateShowTool,
    ProjectStateUpdateTool,
    ProjectStateVerifyTool,
    QuarantineListTool,
    ScheduleCreateTool,
    ScheduleDisableTool,
    ScheduleEnableTool,
    ScheduleListTool,
    ScheduleShowEnabledStateTool,
    ScheduleVerifyEnabledStateTool,
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
from workflow.compound_workflow_progress_store import CompoundWorkflowProgressStore
from workflow.engine import WorkflowEngine
from workflow.paused_workflow_store import PausedWorkflowStore
from workflow.schedule_compound_workflow_progress_store import (
    ScheduleCompoundWorkflowProgressStore,
)
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
    # Internal-only verifier for the "ask jarvis to: enable schedule
    # <id>" workflow (Phase 94, Batch 2) - shares this exact same,
    # already-constructed ScheduleStore, so execution and verification
    # always observe identical durable state. Never reachable via
    # CommandRouter grammar; never selectable by AI output.
    registry.register_tool(ScheduleVerifyEnabledStateTool(schedule_store))
    # Real, public, read-only capability (Phase 99, Batch 1) - shares
    # this exact same ScheduleStore. No CommandRouter grammar entry;
    # selectable only through the existing, unmodified generic
    # "ask jarvis to:" single-capability path.
    registry.register_tool(ScheduleShowEnabledStateTool(schedule_store))

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
    jarvis_brain = JarvisBrainStatusTool(
        registry,
        settings,
        memory,
        approval_history,
        workflow_history,
    )
    registry.register_tool(jarvis_brain)

    # Durable, manually-maintained project-state record (Phase 89,
    # Batch 1): a single row Nathan updates by hand via "update jarvis
    # project state: <field>=<value>" - never populated from git, a
    # subprocess, or the filesystem. ProjectStateShowTool (GREEN) and
    # ProjectStateUpdateTool (YELLOW) both read/write the same store
    # instance; neither constructs a second one. Constructed before
    # PreparePromptTool below (Phase 89, Batch 2) so it can reuse this
    # same instance too.
    project_state_store = ProjectStateStore(session_factory)
    registry.register_tool(ProjectStateShowTool(project_state_store))
    registry.register_tool(ProjectStateUpdateTool(project_state_store))
    # ProjectStateVerifyTool (Phase 90, Batch 3): internal-only - no
    # CommandRouter grammar, not documented in HelpTool. Registered here
    # only so WorkflowEngine/ToolExecutor can execute and audit it as
    # the fixed second step of the "ask jarvis to: update my project
    # focus..." workflow. Reuses the same project_state_store instance -
    # never a second store or connection.
    registry.register_tool(ProjectStateVerifyTool(project_state_store))

    # PreparePromptTool (Phase 86, Batch 2; extended Phase 89, Batch 2
    # with project-state context): reuses the exact same jarvis_brain
    # and project_state_store instances just constructed above (via
    # get_context() and get() respectively) - never a new store/
    # manager connection, never AI, never a subprocess, never git.
    registry.register_tool(PreparePromptTool(jarvis_brain, project_state_store))

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

    # Durable, per-step compound-workflow progress (Phase 98, Batch 3 -
    # docs/phase_98_live_compound_reentry_plan.md): the sole checkpoint
    # authority for the one trusted compound template
    # (PROJECT_STATE_UPDATE_PHASE -> phase verification ->
    # PROJECT_STATE_SHOW). A *different* table from paused_workflows/
    # workflow_history above - see
    # workflow/compound_workflow_progress_store.py's own module
    # docstring. Passed into JarvisOrchestrator below so it can
    # establish/validate progress for that one template; every other
    # request path never touches it.
    compound_progress_store = CompoundWorkflowProgressStore(session_factory)

    # Durable, per-step schedule-compound-workflow progress (Phase 99,
    # Batch 3 - docs/phase_99_second_compound_template_planning.md): the
    # sole checkpoint authority for the second trusted compound template
    # (SCHEDULE_ENABLE -> internal enabled-state verification ->
    # SCHEDULE_SHOW_ENABLED_STATE). A wholly separate table/store from
    # compound_progress_store above - never shared. Passed into
    # JarvisOrchestrator below so it can establish/validate progress for
    # that one template; every other request path never touches it.
    schedule_compound_progress_store = ScheduleCompoundWorkflowProgressStore(
        session_factory
    )

    # VerifiedActionContextBuilder (Phase 100, Batch 2 -
    # docs/phase_100_intelligence_core_gap_audit.md): the one narrow,
    # owned dependency wrapping the two compound progress stores and
    # PendingApprovalStore already constructed above (not second
    # instances) - so ContextAssembler below never threads three stores
    # independently, and never imports a SQLAlchemy model directly.
    verified_action_context_builder = VerifiedActionContextBuilder(
        project_state_progress_store=compound_progress_store,
        schedule_progress_store=schedule_compound_progress_store,
        pending_approval_store=pending_approvals,
    )

    # ContextAssembler (Phase 90, Batch 1; extended Phase 100, Batch 2
    # with a third, optional Verified Action Context source): powers
    # the explicit "ask jarvis: <request>" Context Intelligence command
    # and the "ask jarvis to: <request>" tool-selection command (both
    # single-capability and compound) identically, via this one shared
    # instance. Reuses the exact same `memory`/`project_state_store`/
    # `verified_action_context_builder` instances already constructed
    # above - never a second MemoryManager/ProjectStateStore/builder.
    # Registers no tool of its own: it is never reachable through
    # CommandRouter's ordinary match()/build_input() path, only through
    # JarvisOrchestrator's own dedicated "ask jarvis:"/"ask jarvis to:"
    # dispatch branches.
    context_assembler = ContextAssembler(
        memory_manager=memory,
        project_state_store=project_state_store,
        verified_action_context_builder=verified_action_context_builder,
    )

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
    # Phase 90, Batch 2: the same real AIRouter instance built below (not
    # a second one) also powers the "ask jarvis to: <request>" tool-
    # selection workflow, called directly rather than through
    # AIReasoningEngine (Section 26.C) - so it stays None whenever AI
    # reasoning is disabled, exactly mirroring reasoning_engine's own
    # None-when-disabled convention.
    tool_selection_router: AIRouter | None = None
    if settings.ai_reasoning_enabled:
        from ai.providers.gemini_provider import GeminiProvider
        from ai.providers.openai_provider import OpenAIProvider

        claude_provider = ClaudeProvider(settings)
        openai_provider = OpenAIProvider(settings.openai_api_key)
        gemini_provider = GeminiProvider(settings.google_api_key)
        ai_router = AIRouter(
            providers=(claude_provider, openai_provider, gemini_provider),
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
        tool_selection_router = ai_router

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
        # Phase 90, Batch 1: the same ContextAssembler instance already
        # built above (not a second one) powers the explicit "ask
        # jarvis: <request>" Context Intelligence command.
        context_assembler=context_assembler,
        # Phase 90, Batch 2: the same AIRouter instance already built
        # above (not a second one) powers the explicit "ask jarvis to:
        # <request>" tool-selection command.
        tool_selection_router=tool_selection_router,
        # Phase 98, Batch 3: the same PausedWorkflowStore/
        # CompoundWorkflowProgressStore instances already built above
        # (not second ones) power the one trusted compound workflow's
        # progress-creation and approval-time-validation gates.
        paused_workflow_store=paused_workflows,
        compound_progress_store=compound_progress_store,
        # Phase 99, Batch 3: the same ScheduleCompoundWorkflowProgressStore
        # instance already built above (not a second one) powers the
        # second trusted compound workflow's own progress-creation and
        # approval-time-validation gates.
        schedule_compound_progress_store=schedule_compound_progress_store,
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


class AlreadyRunningError(Exception):
    """Raised when another execution-capable Jarvis process already holds
    the OS execution lock for this exact database (Approval-to-Resume
    Handoff Interlock, Batch 2 - docs/phase_98_approval_handoff_plan.md).

    Deliberately a plain, bounded exception with no recovery/retry logic
    of its own - the caller (main()) catches this and prints a single,
    honest message; nothing is initialized, migrated, or mutated before
    this is raised.
    """


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    """A small, honest summary of what reconcile_claimed_handoffs() did.

    Attributes:
        history_repaired: Number of pending_approval_state rows whose
            approval_history record was missing or still "pending" and
            was backfilled to match the row's own durable handoff_status.
        claimed_consumed: Number of inherited CLAIMED rows for which
            positive terminal workflow-history evidence was found and
            which were transitioned to CONSUMED - includes both
            generic rows and the exact trusted compound template
            (Phase 98, Batch 3), resolved by its own dedicated,
            compound-first reconciliation pass before the generic one
            ever runs.
        claimed_interrupted: Number of inherited CLAIMED rows for which
            no such evidence was found (or could not be proven) and
            which were transitioned to CLAIM_INTERRUPTED - includes
            both generic rows and the exact trusted compound template.
        compound_progress_repaired: Number of exact trusted compound
            PENDING rows whose missing CompoundWorkflowProgress row was
            idempotently repaired before being shown as an actionable
            approval (Phase 98, Batch 3, Foundation F).
        compound_progress_isolated: Number of exact trusted compound
            PENDING rows whose progress could not be unambiguously
            repaired and were terminally isolated instead.
        compound_progress_terminalized: Number of exact trusted
            compound DECLINED/EXPIRED rows whose progress row was
            found still pristine (never terminalized live - a crash,
            for a decline, or always, for an expiry) and was
            idempotently marked NOT_EXECUTED (Phase 98, Batch 3).
        schedule_compound_progress_repaired: The second trusted
            schedule compound template's own equivalent of
            compound_progress_repaired (Phase 99, Batch 3 -
            docs/phase_99_second_compound_template_planning.md).
        schedule_compound_progress_isolated: The schedule compound
            template's own equivalent of compound_progress_isolated.
        schedule_compound_progress_terminalized: The schedule compound
            template's own equivalent of compound_progress_terminalized.
    """

    history_repaired: int
    claimed_consumed: int
    claimed_interrupted: int
    compound_progress_repaired: int = 0
    compound_progress_isolated: int = 0
    compound_progress_terminalized: int = 0
    schedule_compound_progress_repaired: int = 0
    schedule_compound_progress_isolated: int = 0
    schedule_compound_progress_terminalized: int = 0


def start_execution_session() -> tuple[JarvisOrchestrator, ExecutionProcessLock]:
    """Acquire the OS execution lock, then build and recover the system.

    Approval-to-Resume Handoff Interlock, Batch 2. This is the sole
    entry point that acquires runtime.process_lock.ExecutionProcessLock -
    called only by main(), never by build_orchestrator() itself (see
    build_orchestrator()'s own docstring for why: over 100 existing
    tests, including two that call it twice in one process to simulate a
    restart, depend on it remaining lock-free and side-effect-bounded to
    exactly what it already does).

    Exact order: (1) load enough configuration to identify the database;
    (2) resolve its canonical path and acquire the lock (fails closed,
    before anything else); (3)/(4)/(5) call the existing, unchanged
    build_orchestrator() - database init/migration, every store, the
    orchestrator itself, and its own existing reload_pending()/
    reload_paused() calls (which only ever populate still-PENDING
    approvals and their linked paused workflows - see
    ApprovalManager.reload_pending()'s and WorkflowEngine.reload_paused()'s
    own Batch 2 changes); (6)-(8) call reconcile_claimed_handoffs() -
    approval-history consistency repair, inherited-CLAIMED reconciliation,
    and interruption-event backfill, all using their own independent
    engine/session_factory (mirroring build_startup_notice()'s own
    established pattern), operating only on rows build_orchestrator()'s
    own reload already deliberately left untouched (CLAIMED and the four
    terminal handoff states), so there is no ordering conflict between
    the two; (9) no separate in-memory rebuild step is needed - it
    already happened as part of (3)-(5), and reconciliation never touches
    any row already reflected in the live ApprovalManager/WorkflowEngine
    instances' own in-memory state; (10)
    continue_approved_unconsumed_workflows() (Batch 3) - continues each
    durably APPROVED_UNCONSUMED workflow (reconstructed into the live
    WorkflowEngine's own in-memory state by build_orchestrator()'s own
    reload_paused() call, per Batch 3's own reload_paused()/
    _reap_stale_paused() corrections) through the exact same trusted
    claim-before-resume path live execution already uses - never a new
    approval, never a new model call, never a new workflow.

    Returns:
        A tuple of (orchestrator, lock) - the caller (main()) must hold
        `lock` for the remainder of the process's lifetime and release it
        via a try/finally or context manager on every exit path.

    Raises:
        AlreadyRunningError: If another process already holds the
            execution lock for this exact database. Nothing is
            initialized, migrated, or mutated before this is raised.
    """
    settings = load_settings()
    lock = ExecutionProcessLock(settings.database_path)
    try:
        lock.acquire()
    except ExecutionLockError as exc:
        raise AlreadyRunningError(
            "Jarvis appears to already be running against this database "
            f"({settings.database_path}). Only one execution-capable "
            "instance may run at a time."
        ) from exc

    try:
        orchestrator = build_orchestrator()
        reconcile_claimed_handoffs(lock)
        continue_approved_unconsumed_workflows(orchestrator)
    except Exception:
        lock.release()
        raise

    return orchestrator, lock


def reconcile_claimed_handoffs(lock: ExecutionProcessLock) -> ReconciliationSummary:
    """Run exclusive startup recovery: repair approval-history
    consistency, then reconcile every inherited CLAIMED handoff row.

    Approval-to-Resume Handoff Interlock, Batch 2. `lock` is a required
    parameter structurally requiring an already-acquired
    ExecutionProcessLock - it is impossible to call this function without
    one, making "recovery cannot run before lock acquisition" a
    structural, not merely conventional, guarantee. This is exactly why
    calling it is safe: the lock proves no other execution-capable CLI
    process is live for this database, so every inherited CLAIMED row
    found here genuinely belongs to a prior, now-terminated process -
    never a live, competing claimant.

    Uses its own independent engine/session_factory/stores (mirroring
    build_startup_notice()'s own established pattern) rather than reusing
    build_orchestrator()'s - both point at the same real SQLite file, so
    every write here is immediately visible to it, but this function
    never needs build_orchestrator()'s own return type to change to reach
    them.

    Never resumes, executes, or replays anything: every row is either
    left alone (already terminal, or genuinely still pending/approved-
    unconsumed) or transitioned to CONSUMED/CLAIM_INTERRUPTED via
    PendingApprovalStore's own compare-and-set primitives - the same
    ones ApprovalManager already uses for the live path.

    Args:
        lock: The already-acquired ExecutionProcessLock for this exact
            database.

    Returns:
        A ReconciliationSummary of what was repaired/reconciled.

    Raises:
        RuntimeError: If `lock` is not currently held - startup recovery
            must never run before lock acquisition.
    """
    if not lock.is_acquired:
        raise RuntimeError(
            "reconcile_claimed_handoffs() requires an already-acquired "
            "ExecutionProcessLock - startup recovery must never run "
            "before the execution lock is held."
        )

    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)  # idempotent; already done by build_orchestrator()
    session_factory = create_session_factory(engine)

    pending_store = PendingApprovalStore(session_factory)
    history_store = ApprovalHistoryStore(session_factory)
    workflow_history = WorkflowHistoryStore(session_factory)
    compound_progress_store = CompoundWorkflowProgressStore(session_factory)
    schedule_compound_progress_store = ScheduleCompoundWorkflowProgressStore(
        session_factory
    )

    history_repaired = _repair_approval_history_consistency(
        pending_store, history_store
    )

    # Phase 98, Batch 3 (docs/phase_98_live_compound_reentry_plan.md):
    # a small, dedicated stack for the one trusted compound template
    # only - never the full production ToolRegistry, since compound
    # recovery only ever needs the three ProjectState tools this one
    # template uses. The invalidator is a durable-store-only adapter
    # (mark_expired + record_timeout), never ApprovalManager's own
    # in-memory _pending dict - a fresh ApprovalManager would require
    # calling reload_pending() against this narrow registry first,
    # which would incorrectly invalidate every real, unrelated pending
    # approval whose own tool is not one of these three.
    compound_project_state_store = ProjectStateStore(session_factory)
    compound_registry = ToolRegistry()
    compound_registry.register_tool(ProjectStateShowTool(compound_project_state_store))
    compound_registry.register_tool(ProjectStateUpdateTool(compound_project_state_store))
    compound_registry.register_tool(ProjectStateVerifyTool(compound_project_state_store))
    compound_security = SecurityManager()
    compound_executor = ToolExecutor(
        registry=compound_registry, security_manager=compound_security, logger=None
    )
    # This WorkflowEngine instance is only ever used for its own
    # read-only reconstruct_claimed_compound_plan() accessor - never
    # run()/resume() - so its own approvals/paused_store collaborators
    # are never meaningfully invoked.
    compound_workflow_engine = WorkflowEngine(
        executor=compound_executor, approvals=ApprovalManager()
    )
    compound_invalidator = _DurableCompoundApprovalInvalidator(
        pending_store=pending_store,
        history_store=history_store,
        clock=lambda: datetime.now(timezone.utc),
    )

    compound_repair = repair_or_isolate_pending_compound_progress(
        pending_store=pending_store,
        paused_workflow_store=PausedWorkflowStore(session_factory),
        progress_store=compound_progress_store,
        approval_invalidator=compound_invalidator,
        pending_status=PendingApprovalHandoffStatus.PENDING,
    )

    compound_claimed = reconcile_claimed_compound_workflows(
        pending_store=pending_store,
        paused_workflow_store=PausedWorkflowStore(session_factory),
        progress_store=compound_progress_store,
        workflow_engine=compound_workflow_engine,
        tool_registry=compound_registry,
        security_manager=compound_security,
        tool_executor=compound_executor,
        claimed_status=PendingApprovalHandoffStatus.CLAIMED,
    )

    # Phase 99, Batch 3 (docs/phase_99_second_compound_template_planning.md):
    # the second trusted compound template's own small, dedicated stack -
    # mirrors compound_registry/compound_executor/compound_workflow_engine
    # above exactly, against the three schedule tools this one template
    # uses. The same compound_invalidator instance is reused (it is a
    # stateless, template-agnostic adapter over pending_store/history_store),
    # never a second one.
    schedule_compound_schedule_store = ScheduleStore(session_factory)
    schedule_compound_registry = ToolRegistry()
    schedule_compound_registry.register_tool(
        ScheduleEnableTool(schedule_compound_schedule_store)
    )
    schedule_compound_registry.register_tool(
        ScheduleVerifyEnabledStateTool(schedule_compound_schedule_store)
    )
    schedule_compound_registry.register_tool(
        ScheduleShowEnabledStateTool(schedule_compound_schedule_store)
    )
    schedule_compound_security = SecurityManager()
    schedule_compound_executor = ToolExecutor(
        registry=schedule_compound_registry,
        security_manager=schedule_compound_security,
        logger=None,
    )
    # Read-only reconstruct_claimed_compound_plan() accessor only - never
    # run()/resume() - mirrors compound_workflow_engine above exactly.
    schedule_compound_workflow_engine = WorkflowEngine(
        executor=schedule_compound_executor, approvals=ApprovalManager()
    )

    schedule_compound_repair = repair_or_isolate_pending_schedule_compound_progress(
        pending_store=pending_store,
        paused_workflow_store=PausedWorkflowStore(session_factory),
        progress_store=schedule_compound_progress_store,
        approval_invalidator=compound_invalidator,
        pending_status=PendingApprovalHandoffStatus.PENDING,
    )

    schedule_compound_claimed = reconcile_claimed_schedule_compound_workflows(
        pending_store=pending_store,
        paused_workflow_store=PausedWorkflowStore(session_factory),
        progress_store=schedule_compound_progress_store,
        workflow_engine=schedule_compound_workflow_engine,
        tool_registry=schedule_compound_registry,
        security_manager=schedule_compound_security,
        tool_executor=schedule_compound_executor,
        claimed_status=PendingApprovalHandoffStatus.CLAIMED,
    )

    # Phase 98, Batch 3: the dedicated non-execution terminalization
    # path's own crash-recovery backstop - a declined compound row a
    # crash prevented from being terminalized live, or (its only
    # mechanism at all) an expired one, since WorkflowEngine's own lazy
    # paused-workflow reaping never calls back into this module. Order
    # relative to the PENDING/CLAIMED passes above never matters: this
    # only ever touches rows already durably DECLINED/EXPIRED, a
    # disjoint set from PENDING/CLAIMED.
    compound_terminalized = terminalize_declined_or_expired_compound_progress(
        pending_store=pending_store,
        progress_store=compound_progress_store,
        declined_status=PendingApprovalHandoffStatus.DECLINED,
        expired_status=PendingApprovalHandoffStatus.EXPIRED,
    )

    # Phase 99, Batch 3: the schedule compound template's own equivalent
    # crash-recovery backstop - never touches a row already resolved by
    # the ProjectState pass above, since the two templates' own trusted
    # fingerprints are structurally disjoint (a persisted plan can only
    # ever match one of the two).
    schedule_compound_terminalized = terminalize_declined_or_expired_schedule_compound_progress(
        pending_store=pending_store,
        progress_store=schedule_compound_progress_store,
        declined_status=PendingApprovalHandoffStatus.DECLINED,
        expired_status=PendingApprovalHandoffStatus.EXPIRED,
    )

    # Only now does the existing, unchanged generic CLAIMED fallback
    # run - it will only ever see rows neither compound-specific pass
    # above already resolved (left_for_generic), since every resolved
    # compound row (either template) has already transitioned out of
    # CLAIMED.
    claimed_consumed, claimed_interrupted = _reconcile_claimed_rows(
        pending_store, history_store, workflow_history
    )
    return ReconciliationSummary(
        history_repaired=history_repaired,
        claimed_consumed=(
            claimed_consumed + compound_claimed.consumed + schedule_compound_claimed.consumed
        ),
        claimed_interrupted=(
            claimed_interrupted
            + compound_claimed.interrupted
            + schedule_compound_claimed.interrupted
        ),
        compound_progress_repaired=compound_repair.repaired,
        compound_progress_isolated=compound_repair.isolated,
        compound_progress_terminalized=compound_terminalized,
        schedule_compound_progress_repaired=schedule_compound_repair.repaired,
        schedule_compound_progress_isolated=schedule_compound_repair.isolated,
        schedule_compound_progress_terminalized=schedule_compound_terminalized,
    )


class _DurableCompoundApprovalInvalidator:
    """Adapts PendingApprovalStore/ApprovalHistoryStore's own durable
    primitives to core.compound_workflow's approval-invalidator
    contract (a single `invalidate_pending(request_id, *, reason) ->
    bool` method), mirroring ApprovalManager.invalidate_pending()'s
    exact durable behaviour (mark_expired + record_timeout) - without
    depending on ApprovalManager's own in-memory `_pending` dict, which
    would otherwise require an incorrect reload_pending() call against
    a registry that only knows about this one template's own three
    tools (Phase 98, Batch 3).
    """

    def __init__(self, *, pending_store, history_store, clock) -> None:
        self._pending_store = pending_store
        self._history_store = history_store
        self._clock = clock

    def invalidate_pending(self, request_id: str, *, reason: str) -> bool:
        """Mirrors ApprovalManager.invalidate_pending()'s own durable
        behaviour exactly: CAS PENDING -> EXPIRED, then record an
        honest approval-history timeout entry. A no-op (returns False)
        if the row is not currently PENDING.

        Args:
            request_id: The pending approval request id to invalidate.
            reason: A short, bounded, honest reason.

        Returns:
            True if the row was found and invalidated; False otherwise.
        """
        if not self._pending_store.mark_expired(request_id):
            return False
        self._history_store.record_timeout(
            request_id=request_id,
            timed_out_at=self._clock(),
            reason=f"Could not be resumed after restart: {reason}",
        )
        return True


def _expected_history_status(handoff_status: PendingApprovalHandoffStatus) -> str:
    """Return the approval_history `status` a durable handoff_status
    implies, for the sole purpose of detecting a missing/stale backfill.

    Args:
        handoff_status: The durable, authoritative handoff state.

    Returns:
        "pending" for PENDING; "approved" for every state that can only
        be reached by first being approved (APPROVED_UNCONSUMED, CLAIMED,
        CONSUMED, CLAIM_INTERRUPTED); "declined" for DECLINED; "expired"
        for EXPIRED.
    """
    if handoff_status is PendingApprovalHandoffStatus.PENDING:
        return "pending"
    if handoff_status is PendingApprovalHandoffStatus.DECLINED:
        return "declined"
    if handoff_status is PendingApprovalHandoffStatus.EXPIRED:
        return "expired"
    return "approved"


def _repair_approval_history_consistency(
    pending_store: PendingApprovalStore, history_store: ApprovalHistoryStore
) -> int:
    """Ensure a truthful, non-contradictory approval_history record
    exists for every durable pending_approval_state row.

    For each row: if no history entry exists at all, one is created
    (record_request(), status "pending"). If the history entry's own
    status is still "pending" but the durable handoff_status shows the
    request was actually decided, the missing decision is backfilled
    (record_decision()/record_timeout(), and additionally
    record_interruption() for a durably CLAIM_INTERRUPTED row) - honestly
    attributed to "system_repair" at the current moment, since the
    original decider/timestamp is not independently recoverable. An
    already-decided history entry (status "approved"/"declined"/
    "expired"/"interrupted") is never touched again - repair only ever
    fills a genuine gap, never overwrites a real record contradictorily.

    Args:
        pending_store: The durable pending-approval store to inspect.
        history_store: The durable approval-history store to repair.

    Returns:
        The number of rows whose history was created or backfilled.
    """
    repaired = 0
    now = datetime.now(timezone.utc)

    for record in pending_store.list_all():
        existing = history_store.get(record.request_id)
        if existing is None:
            history_store.record_request(
                request_id=record.request_id,
                action=record.action,
                reason=record.reason,
                security_tier=record.security_tier,
                session_id=record.session_id,
            )
            existing_status = "pending"
            repaired += 1
        else:
            existing_status = existing.status

        expected = _expected_history_status(record.handoff_status)
        if expected == "pending" or existing_status != "pending":
            continue

        repair_reason = "Backfilled by startup consistency repair."
        if expected == "approved":
            history_store.record_decision(
                request_id=record.request_id,
                approved=True,
                decided_by="system_repair",
                decided_at=now,
                reason=repair_reason,
            )
            if record.handoff_status is PendingApprovalHandoffStatus.CLAIM_INTERRUPTED:
                history_store.record_interruption(
                    request_id=record.request_id,
                    interrupted_at=now,
                    reason=repair_reason,
                )
        elif expected == "declined":
            history_store.record_decision(
                request_id=record.request_id,
                approved=False,
                decided_by="system_repair",
                decided_at=now,
                reason=repair_reason,
            )
        else:  # "expired"
            history_store.record_timeout(
                request_id=record.request_id,
                timed_out_at=now,
                reason=repair_reason,
            )
        repaired += 1

    return repaired


def _reconcile_claimed_rows(
    pending_store: PendingApprovalStore,
    history_store: ApprovalHistoryStore,
    workflow_history: WorkflowHistoryStore,
) -> tuple[int, int]:
    """Reconcile every inherited CLAIMED handoff row using positive-only
    workflow-history evidence.

    For each CLAIMED row: its linked workflow_id (from the row's own
    metadata, set only by WorkflowEngine at pause time) is looked up via
    WorkflowHistoryStore.latest_status_for() - the same positive-only
    evidence rule already established (docs/phase_98_implementation_plan.md
    Section 12): a "workflow_completed"/"workflow_stopped" entry is
    reliable positive proof; absence proves nothing and is never read as
    "did not execute". A row with exact terminal evidence is CAS'd to
    CONSUMED; one without is CAS'd to CLAIM_INTERRUPTED and one bounded,
    idempotent interruption event is recorded. Nothing here ever resumes,
    executes, or replays anything - only these two CAS transitions.

    Args:
        pending_store: The durable pending-approval store to reconcile.
        history_store: The durable approval-history store to record an
            interruption event in, when needed.
        workflow_history: The durable workflow-history store to consult
            for terminal evidence.

    Returns:
        A tuple of (consumed_count, interrupted_count).
    """
    consumed = 0
    interrupted = 0
    now = datetime.now(timezone.utc)

    for record in pending_store.list_by_handoff_status(
        PendingApprovalHandoffStatus.CLAIMED
    ):
        workflow_id = record.metadata.get("workflow_id")
        has_terminal_evidence = False
        if workflow_id:
            latest = workflow_history.latest_status_for(workflow_id)
            if latest is not None and latest.status in (
                "workflow_completed",
                "workflow_stopped",
            ):
                has_terminal_evidence = True

        if has_terminal_evidence:
            if pending_store.mark_consumed(record.request_id):
                consumed += 1
        else:
            if pending_store.mark_claim_interrupted(record.request_id):
                history_store.record_interruption(
                    request_id=record.request_id,
                    interrupted_at=now,
                    reason=(
                        "No confirmed terminal workflow outcome was found "
                        "during exclusive startup recovery."
                    ),
                )
                interrupted += 1

    return consumed, interrupted


@dataclass(frozen=True, slots=True)
class ContinuationSummary:
    """A small, honest summary of what
    continue_approved_unconsumed_workflows() did (Approval-to-Resume
    Handoff Interlock, Batch 3 - docs/phase_98_approval_handoff_plan.md).

    Attributes:
        continued: Number of APPROVED_UNCONSUMED workflows that were
            claimed, resumed, and reached a known terminal result
            (CONSUMED) - regardless of whether that result was itself a
            tool success or failure; CONSUMED never means success
            specifically.
        interrupted: Number that were claimed but could not be resumed
            to a known terminal result (paused workflow missing/invalid,
            or an unexpected failure after claim) and are now
            CLAIM_INTERRUPTED.
        left_pending: Number that could not even be identified as a
            continuable, workflow-linked, durably APPROVED_UNCONSUMED
            request with a real available paused workflow (no claim was
            ever attempted for these) - they remain durably
            APPROVED_UNCONSUMED, untouched, for a future startup attempt.
    """

    continued: int
    interrupted: int
    left_pending: int


def continue_approved_unconsumed_workflows(
    orchestrator: JarvisOrchestrator,
) -> ContinuationSummary:
    """Continue every durably APPROVED_UNCONSUMED workflow through the
    exact trusted claim-before-resume path (Approval-to-Resume Handoff
    Interlock, Batch 3 - docs/phase_98_approval_handoff_plan.md).

    This is the mandatory correction the Batch 3 audit requires: durable
    discoverability of an APPROVED_UNCONSUMED row alone is insufficient,
    since no existing production path (no CLI command, no CommandRouter
    grammar, no AI-reachable dispatch) ever calls
    ApprovalManager.claim_for_resume() for a request restored after a
    restart - JarvisOrchestrator.execute_approved() is only ever reached
    with a live, in-memory JarvisResponse from the exact same process
    that created the approval. Outcome B (narrow automatic startup
    continuation) is implemented here.

    Processes every APPROVED_UNCONSUMED row in
    ApprovalManager.list_approved_unconsumed()'s own deterministic,
    creation-time order (oldest first - an existing, repository-supported
    durable field; never inferred from a capability name). Each row is
    claimed and resumed independently, through
    JarvisOrchestrator.resume_approved_unconsumed_workflow(): no new
    approval is ever created (claim_for_resume() only ever transitions
    an already-APPROVED_UNCONSUMED row), no AI/model call is made, no
    parser or grounding call is made, and the exact persisted approved
    tool_input is the only input ever used (read from the paused
    workflow's own already-reconstructed, already-revalidated
    resolved_tool_input - the identical value the live approval path
    would have used). Only a real, already-paused, already-reloaded
    workflow can ever be continued - nothing is ever reconstructed from
    scratch or from model output.

    Whether one particular row fails (for any reason, at any point) can
    never corrupt, block, or change the identity of any other - each
    row's own claim/resume/terminal-transition is entirely independent,
    and a per-row failure is always isolated (caught here) so processing
    always continues to every remaining row, matching this codebase's
    own established "one bad row must never block every other valid
    row" convention (reload_pending()/reload_paused()). Startup itself
    is never aborted by a continuation failure - only reported via the
    returned summary and via each row's own durable handoff_status
    (APPROVED_UNCONSUMED if nothing could be attempted at all; CLAIM_
    INTERRUPTED if claimed but not confirmed complete; CONSUMED if a
    real terminal result was reached) - never silently swallowed.

    Never continues a PENDING, DECLINED, EXPIRED, CLAIMED, CONSUMED, or
    CLAIM_INTERRUPTED row - only APPROVED_UNCONSUMED rows are ever
    listed by list_approved_unconsumed() in the first place.

    Args:
        orchestrator: The fully built, already-recovered orchestrator
            (from build_orchestrator(), after reconcile_claimed_handoffs()
            has already run on the same database).

    Returns:
        A ContinuationSummary of how many rows were continued to a
        terminal result, interrupted, or left untouched.
    """
    continued = 0
    interrupted = 0
    left_pending = 0
    approvals = orchestrator.approvals

    for record in approvals.list_approved_unconsumed():
        try:
            orchestrator.resume_approved_unconsumed_workflow(record.request_id)
        except Exception:  # noqa: BLE001 - isolated per-row; outcome read from durable state below
            pass

        status = approvals.handoff_status_for(record.request_id)
        if status is PendingApprovalHandoffStatus.CONSUMED:
            continued += 1
        elif status is PendingApprovalHandoffStatus.CLAIM_INTERRUPTED:
            interrupted += 1
        else:
            left_pending += 1

    return ContinuationSummary(
        continued=continued, interrupted=interrupted, left_pending=left_pending
    )


def main() -> None:
    """Acquire the execution lock, build and recover the system, and
    start the interactive CLI.

    Approval-to-Resume Handoff Interlock, Batch 2: if another process
    already holds the execution lock for this database,
    start_execution_session() raises AlreadyRunningError before
    anything is initialized, migrated, or mutated - this is reported
    here as a single, bounded, honest message, and the process exits
    without starting the CLI. Otherwise, the lock is held via try/finally
    across the complete interactive CLI lifetime - database
    initialization, recovery, every approval decision, claim, workflow
    resume, and tool execution - and released on every exit path,
    including an unhandled exception propagating out of cli.run().
    """
    try:
        orchestrator, lock = start_execution_session()
    except AlreadyRunningError as exc:
        print(str(exc))
        return

    try:
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
    finally:
        lock.release()


if __name__ == "__main__":
    main()