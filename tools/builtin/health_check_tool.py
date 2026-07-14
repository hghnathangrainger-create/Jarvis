"""
health_check_tool.py

A safe, read-only tool that reports basic Jarvis system health (Phase
57, Batch 1).

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

Deferred to Batch 2 (not included here): Inbox/Schedule/Quarantine
store reachability checks, and a SecurityManager self-classification
check.
"""

from __future__ import annotations

import logging
from pathlib import Path

from config.constants import APP_NAME
from config.settings import Settings
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.registry import ToolRegistry

#: The deliberately minimal set of foundational tools checked for
#: presence in the registry - not an exhaustive roster (see module
#: docstring for why a second full roster is not maintained here).
_CORE_TOOL_NAMES: tuple[str, ...] = ("echo", "info", "help", "config")


class HealthCheckTool(BaseTool):
    """Reports basic Jarvis system health.

    Read-only and safe; every check reads an already-constructed
    object's existing state - nothing is created, opened, or mutated.
    """

    def __init__(self, registry: ToolRegistry, settings: Settings) -> None:
        """Initialise the tool with the already-built registry/settings.

        Args:
            registry: The application's already-populated ToolRegistry.
                This tool never registers, unregisters, or executes a
                tool through it - only list_tool_names()/has_tool() are
                ever called.
            settings: The already-loaded Settings object. This tool
                never calls load_settings() itself and never reads
                .env/os.environ directly.
        """
        self._registry = registry
        self._settings = settings

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
