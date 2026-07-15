"""
health_check_tool.py

A safe, read-only tool that reports basic Jarvis system health (Phase
57).

HealthCheckTool is a GREEN tool: every check it performs is read-only
introspection of objects already constructed and loaded by main.py's
own composition root (build_orchestrator()) - it never opens a new
database connection, never constructs a new store, never creates a
file or a database row, and never mutates settings, the database, the
scheduler, the Inbox, quarantine, the dashboard, approvals, memory, or
workflow state.

Batch 1 checks (narrow, no new store dependencies):
    - Settings: confirms the already-loaded Settings object this tool
      was constructed with is present. Trivially true whenever this
      tool actually runs (if config.settings.load_settings() had
      failed, Jarvis would never have started at all) - still reported
      explicitly, as a health check should.
    - Database path: confirms settings.database_path (or its parent
      directory) exists on disk, using only pathlib.Path.exists() -
      a pure filesystem stat call. Never opens a database connection,
      never creates the file or any parent directory.
    - Tool registry: reports how many tools are registered and whether
      a small, deliberately minimal set of foundational tools (echo,
      info, help, config) is present - a smoke test that the registry
      is genuinely populated, not an exhaustive roster (that already
      exists, verified elsewhere, in
      tests/unit/test_command_router.py's own _ALL_TOOL_NAMES fixture
      and tests/unit/test_help_output_routing_consistency.py - adding
      a second hand-maintained full roster here would just be a new
      drift risk of exactly the kind Phase 51/52 closed elsewhere).
    - Console logging: confirms whether observability.logging_setup.
      configure_console_logging() (Phase 54) has already attached a
      handler to the "jarvis" app logger in this process, and reports
      its current level. Pure read of logging.getLogger(APP_NAME)'s
      existing state - never calls configure_console_logging() itself,
      so this can never attach a duplicate handler.

Batch 2 checks (reusing main.py's already-built store/SecurityManager
instances - never a new database connection, never a new store):
    - Inbox: calls the already-injected InboxStore.count() - a pure SQL
      COUNT query, no row hydration, no write of any kind.
    - Schedules: calls the already-injected ScheduleStore.count() - same
      shape as Inbox above.
    - Quarantine: calls the already-injected QuarantineStore.count()
      (Phase 68) - a true, unbounded COUNT query, the same shape as the
      Inbox/Schedule checks above. QuarantineStore had no count() method
      when this tool was first written (Phase 57); Phase 66 added one
      for the dashboard's own Quarantine Summary panel, and this check
      now reuses it rather than the previous limit=1 list_recent() probe
      that could only prove reachability, never a real total. Never
      restores, deletes, or modifies anything.
    - Security Manager: calls the already-injected SecurityManager's own
      classify_action() on this tool's own fixed "show system health"
      action string and confirms it still classifies GREEN - a pure,
      stateless classification call that never touches ApprovalManager,
      never approves or declines anything, and changes no approval or
      security state.

Batch 1 (Phase 80) checks (reusing main.py's already-built MemoryManager
and ApprovalHistoryStore instances - never a new database connection,
never a new store):
    - Memory: calls the already-injected MemoryManager.count() - the
      same shape as the Inbox/Schedule/Quarantine checks above.
    - Approval history: sums the already-injected
      ApprovalHistoryStore.count_by_status() across every status in
      KNOWN_APPROVAL_STATUSES - the same reuse
      ApprovalHistoryTool._format_history() already established (Phase
      73, Batch 1), never a new store method, never an invented or
      partial status list.

Batch 2 (Phase 80) check (reusing main.py's already-built
WorkflowHistoryStore instance - never a new database connection, never
a new store):
    - Workflow history: calls the already-injected
      WorkflowHistoryStore.count_distinct_workflows() - a new, narrow,
      read-only COUNT(DISTINCT workflow_id) method added because no
      already-fetched true total existed (list_recent_workflow_ids()
      is clamped to 50). Counts distinct workflows, never raw
      transition rows.

dashboard.py is never invoked and DashboardReadModel is never
constructed - it is a wholly separate process with its own independent
database connection; the shared SQLite file's existence is already
covered by the database-path check above, which is the only meaningful
proxy reachable from this process.
"""

from __future__ import annotations

import logging
from pathlib import Path

from approval.approval_history_store import (
    KNOWN_APPROVAL_STATUSES,
    ApprovalHistoryStore,
)
from config.constants import APP_NAME, SecurityTier
from config.settings import Settings
from inbox.inbox_store import InboxStore
from memory.memory_manager import MemoryManager
from quarantine.quarantine_store import QuarantineStore
from scheduling.schedule_store import ScheduleStore
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.registry import ToolRegistry
from workflow.workflow_history_store import WorkflowHistoryStore

#: The deliberately minimal set of foundational tools checked for
#: presence in the registry - not an exhaustive roster (see module
#: docstring for why a second full roster is not maintained here).
_CORE_TOOL_NAMES: tuple[str, ...] = ("echo", "info", "help", "config")


class HealthCheckTool(BaseTool):
    """Reports basic Jarvis system health.

    Read-only and safe; every check reads an already-constructed
    object's existing state - nothing is created, opened, or mutated.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        settings: Settings,
        inbox_store: InboxStore,
        schedule_store: ScheduleStore,
        quarantine_store: QuarantineStore,
        security_manager: SecurityManager,
        memory_manager: MemoryManager,
        approval_history_store: ApprovalHistoryStore,
        workflow_history_store: WorkflowHistoryStore,
    ) -> None:
        """Initialise the tool with already-built dependencies only.

        Every argument is an object main.py's build_orchestrator()
        already constructs for other tools' use - this tool never
        constructs its own database connection, store, or
        SecurityManager instance.

        Args:
            registry: The application's already-populated ToolRegistry.
                This tool never registers, unregisters, or executes a
                tool through it - only list_tool_names()/has_tool() are
                ever called.
            settings: The already-loaded Settings object. This tool
                never calls load_settings() itself and never reads
                .env/os.environ directly.
            inbox_store: The already-constructed InboxStore. Only
                count() is ever called.
            schedule_store: The already-constructed ScheduleStore. Only
                count() is ever called.
            quarantine_store: The already-constructed QuarantineStore.
                Only count() is ever called (Phase 68).
            security_manager: The application's already-constructed
                SecurityManager. Only classify_action() is ever called,
                on this tool's own fixed action string - never anything
                that touches approval state.
            memory_manager: The already-constructed MemoryManager
                (Phase 80, Batch 1). Only count() is ever called.
            approval_history_store: The already-constructed
                ApprovalHistoryStore (Phase 80, Batch 1). Only
                count_by_status() is ever called, once per status in
                KNOWN_APPROVAL_STATUSES.
            workflow_history_store: The already-constructed
                WorkflowHistoryStore (Phase 80, Batch 2). Only
                count_distinct_workflows() is ever called.
        """
        self._registry = registry
        self._settings = settings
        self._inbox_store = inbox_store
        self._schedule_store = schedule_store
        self._quarantine_store = quarantine_store
        self._security_manager = security_manager
        self._memory_manager = memory_manager
        self._approval_history_store = approval_history_store
        self._workflow_history_store = workflow_history_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "health_check".
        """
        return "health_check"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Reports basic Jarvis system health (settings, database "
            "path, tool registry, console logging). Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        Always the same fixed phrase, regardless of which grammar alias
        ("health check", "show health", or "system health") was used,
        so classification never varies with user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show system health", classified GREEN.
        """
        return "show system health"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the current system health report.

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult listing each health check's
            outcome. Never fails outright - each check reports its own
            status line, including a negative one, rather than raising.
        """
        lines = [
            "Jarvis health check:",
            f"  Settings: loaded ({self._settings.ai_model})",
            f"  Database path: {self._database_path_status()}",
            f"  Tool registry: {self._registry_status()}",
            f"  Console logging: {self._logging_status()}",
            f"  Inbox store: {self._inbox_status()}",
            f"  Schedule store: {self._schedule_status()}",
            f"  Quarantine store: {self._quarantine_status()}",
            f"  Memory store: {self._memory_status()}",
            f"  Approval history store: {self._approval_history_status()}",
            f"  Workflow history store: {self._workflow_history_status()}",
            f"  Security Manager: {self._security_manager_status()}",
        ]
        return self.ok("\n".join(lines))

    def _database_path_status(self) -> str:
        """Report whether the configured database path is reachable.

        Never opens a database connection and never creates the file or
        any parent directory - only pathlib.Path.exists() is called.

        Returns:
            A short, human-readable status string.
        """
        path = Path(self._settings.database_path)
        if path.exists():
            return f"{path} (exists)"
        if path.parent.exists():
            return f"{path} (file not yet created, parent directory exists)"
        return f"{path} (NOT reachable - neither the file nor its parent directory exists)"

    def _registry_status(self) -> str:
        """Report the tool registry's population and core-tool presence.

        Returns:
            A short, human-readable status string.
        """
        names = self._registry.list_tool_names()
        missing = [name for name in _CORE_TOOL_NAMES if name not in names]
        if missing:
            return (
                f"{len(names)} tools registered, but missing expected "
                f"core tool(s): {', '.join(missing)}"
            )
        return f"{len(names)} tools registered, including all core tools"

    @staticmethod
    def _logging_status() -> str:
        """Report whether console logging has been configured in this process.

        Never calls configure_console_logging() itself - only reads the
        "jarvis" app logger's already-existing state, so this can never
        attach a duplicate handler.

        Returns:
            A short, human-readable status string.
        """
        logger = logging.getLogger(APP_NAME)
        if not logger.handlers:
            return "not configured in this process (no console handler attached)"
        level_name = logging.getLevelName(logger.level)
        return f"configured ({len(logger.handlers)} handler(s), level={level_name})"

    def _inbox_status(self) -> str:
        """Report whether the already-injected InboxStore is reachable.

        Calls only count() - a pure SQL COUNT query, no row hydration,
        no write of any kind. Never constructs a new InboxStore or
        database connection.

        Returns:
            A short, human-readable status string.
        """
        try:
            count = self._inbox_store.count()
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        return f"reachable ({count} entr{'y' if count == 1 else 'ies'} recorded)"

    def _schedule_status(self) -> str:
        """Report whether the already-injected ScheduleStore is reachable.

        Calls only count() - a pure SQL COUNT query, no row hydration,
        no write of any kind. Never constructs a new ScheduleStore or
        database connection.

        Returns:
            A short, human-readable status string.
        """
        try:
            count = self._schedule_store.count()
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        return f"reachable ({count} schedule{'' if count == 1 else 's'} recorded)"

    def _quarantine_status(self) -> str:
        """Report whether the already-injected QuarantineStore is reachable.

        Calls only count() (Phase 68) - a true, unbounded SQL COUNT
        query, no row hydration, no write of any kind - the same shape
        as _inbox_status()/_schedule_status() above. Never restores,
        deletes, or modifies anything, and never constructs a new
        QuarantineStore or database connection.

        Returns:
            A short, human-readable status string.
        """
        try:
            count = self._quarantine_store.count()
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        return f"reachable ({count} file{'' if count == 1 else 's'} recorded)"

    def _memory_status(self) -> str:
        """Report whether the already-injected MemoryManager is reachable
        (Phase 80, Batch 1).

        Calls only count() - a pure SQL COUNT query, no row hydration,
        no write of any kind - the same shape as
        _inbox_status()/_schedule_status()/_quarantine_status() above.
        Never constructs a new MemoryManager or database connection.

        Returns:
            A short, human-readable status string.
        """
        try:
            count = self._memory_manager.count()
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        return f"reachable ({count} memor{'y' if count == 1 else 'ies'} recorded)"

    def _approval_history_status(self) -> str:
        """Report whether the already-injected ApprovalHistoryStore is
        reachable (Phase 80, Batch 1).

        The total is a true, unbounded sum of count_by_status() across
        every status in KNOWN_APPROVAL_STATUSES - the same reuse
        ApprovalHistoryTool._format_history() already established
        (Phase 73, Batch 1) - never an invented or partial status list,
        and never a new store method. No row is ever hydrated, and
        nothing is ever created, approved, or declined.

        Returns:
            A short, human-readable status string.
        """
        try:
            count = sum(
                self._approval_history_store.count_by_status(status)
                for status in KNOWN_APPROVAL_STATUSES
            )
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        return f"reachable ({count} entr{'y' if count == 1 else 'ies'} recorded)"

    def _workflow_history_status(self) -> str:
        """Report whether the already-injected WorkflowHistoryStore is
        reachable (Phase 80, Batch 2).

        Calls only count_distinct_workflows() - a true, unbounded COUNT
        of distinct workflow ids, never raw transition rows and never
        the bounded/clamped list_recent_workflow_ids(). No row is ever
        hydrated, and nothing is ever created, started, or resumed.

        Returns:
            A short, human-readable status string.
        """
        try:
            count = self._workflow_history_store.count_distinct_workflows()
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        return f"reachable ({count} workflow{'' if count == 1 else 's'} recorded)"

    def _security_manager_status(self) -> str:
        """Report whether the already-injected SecurityManager correctly
        classifies this tool's own action as GREEN.

        A pure, stateless call to classify_action() - it never touches
        ApprovalManager, never approves or declines anything, and
        changes no approval or security state. Never constructs a new
        SecurityManager instance.

        Returns:
            A short, human-readable status string.
        """
        try:
            decision = self._security_manager.classify_action(
                self.action_for(ToolRequest(tool_name=self.name))
            )
        except Exception as exc:  # noqa: BLE001 - a health check must never crash
            return f"NOT reachable ({exc})"
        if decision.tier is SecurityTier.GREEN:
            return "reachable (self-classification: GREEN, as expected)"
        return f"reachable, but self-classification was unexpected: {decision.tier.value}"
