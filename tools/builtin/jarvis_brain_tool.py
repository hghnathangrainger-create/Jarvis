"""
jarvis_brain_tool.py

A safe, read-only tool that reports Jarvis's own current "brain"
status (Phase 86, Batch 1): real AI/reasoning configuration, real
memory/approval/workflow foundations, tool registry size, and an
honest "current limits" section naming what Jarvis cannot do yet.

JarvisBrainStatusTool is a GREEN tool: every value it reports traces
to an already-loaded Settings object or an already-constructed store/
manager's existing, proven read method - the same "reuse, never
fabricate" discipline HealthCheckTool/ConfigTool already established.
It never opens a new database connection, never constructs a new
store, and never calls AI, a subprocess, or the web.

This is deliberately distinct from HealthCheckTool: HealthCheckTool
answers "is everything reachable/working" (a diagnostic), while this
tool answers "what do I actually know and what can I actually do"
(a capability/self-description report). The two tools share no code,
but reuse the exact same underlying store/manager methods, never
duplicating store logic.

This tool has no live knowledge of the current git branch, commit, or
test suite result - no such state is tracked anywhere in this app -
and it never calls the Claude API, any other AI provider, or a
subprocess to find out. It reports only what is genuinely, already
known to the running process.

Extended Phase 86, Batch 2 with get_context(), a public method
returning the same real data as a structured ai.prompt_studio.
PromptContext - reused directly by PreparePromptTool's "Jarvis
Context" section, never by parsing this tool's own formatted text
output back apart.
"""

from __future__ import annotations

from ai.prompt_studio import PromptContext
from approval.approval_history_store import (
    KNOWN_APPROVAL_STATUSES,
    ApprovalHistoryStore,
)
from config.settings import Settings
from memory.memory_manager import MemoryManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.registry import ToolRegistry
from workflow.workflow_history_store import WorkflowHistoryStore

#: Fixed, hand-maintained list of real, current limits - never
#: aspirational, never implying a capability that doesn't exist.
#: Updated only when a real limit changes, mirroring HelpTool's own
#: "static, hand-maintained, never invented" discipline (_HELP_LINES).
_CURRENT_LIMITS: tuple[str, ...] = (
    "Cannot call the Claude API or any other AI provider from this "
    "command - Jarvis's own advisory AI features are separate and "
    "gated by AI_REASONING_ENABLED.",
    "Cannot edit, patch, or apply changes to its own repository.",
    "Cannot run autonomously - every write action still requires "
    "your explicit approval.",
    "Has no live knowledge of the current git branch, commit, or "
    "test suite result - that state is not tracked anywhere in this "
    "app.",
    "Every figure above is a real, live count or configuration "
    "value - never simulated, estimated, or fabricated.",
)


class JarvisBrainStatusTool(BaseTool):
    """Reports Jarvis's own current capability/status, honestly.

    Read-only and safe; every reported value is a real, already-proven
    count or configuration field - nothing here is estimated,
    simulated, or fabricated.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        settings: Settings,
        memory_manager: MemoryManager,
        approval_history_store: ApprovalHistoryStore,
        workflow_history_store: WorkflowHistoryStore,
    ) -> None:
        """Initialise the tool with already-built dependencies only.

        Every argument is an object main.py's build_orchestrator()
        already constructs for other tools' use - this tool never
        constructs its own database connection, store, or manager.

        Args:
            registry: The application's already-populated ToolRegistry.
                Only list_tool_names() is ever called.
            settings: The already-loaded Settings object. This tool
                never calls load_settings() itself and never reads
                .env/os.environ directly.
            memory_manager: The already-constructed MemoryManager.
                Only count() is ever called.
            approval_history_store: The already-constructed
                ApprovalHistoryStore. Only count_by_status() is ever
                called, once per status in KNOWN_APPROVAL_STATUSES.
            workflow_history_store: The already-constructed
                WorkflowHistoryStore. Only count_distinct_workflows()
                is ever called.
        """
        self._registry = registry
        self._settings = settings
        self._memory_manager = memory_manager
        self._approval_history_store = approval_history_store
        self._workflow_history_store = workflow_history_store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "jarvis_brain".
        """
        return "jarvis_brain"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Reports Jarvis's current AI configuration, real memory/"
            "approval/workflow counts, and known limits. Read-only "
            "and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        Always the same fixed phrase, regardless of which grammar
        alias ("jarvis brain status" or "show jarvis brain") was
        used, so classification never varies with user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show jarvis brain status", classified GREEN.
        """
        return "show jarvis brain status"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the current brain status report.

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult listing real AI configuration,
            real memory/approval/workflow counts, tool registry size,
            and a fixed "current limits" section. Never fails outright
            - each section reports its own honest state.
        """
        lines = [
            "Jarvis Brain Status:",
            "",
            "AI / Reasoning:",
            f"  AI reasoning enabled: {self._settings.ai_reasoning_enabled}",
            f"  AI model: {self._settings.ai_model}",
            f"  Anthropic API key: {self._api_key_status()}",
            "",
            "Memory:",
            f"  Total memories stored: {self._memory_manager.count()}",
            "",
            "Approval History:",
            f"  {self._approval_history_status()}",
            "",
            "Workflow History:",
            f"  {self._workflow_history_status()}",
            "",
            f"Tool registry: {len(self._registry.list_tool_names())} "
            "tools registered",
            "",
            "Current limits (what Jarvis cannot do yet):",
        ]
        lines.extend(f"  - {limit}" for limit in _CURRENT_LIMITS)
        return self.ok("\n".join(lines))

    def _api_key_status(self) -> str:
        """Report the API key's presence only - never its value.

        Mirrors ConfigTool's own established secret-handling
        discipline exactly: "set"/"not set", never a value, masked
        form, length, or hash/fingerprint.

        Returns:
            "set" or "not set".
        """
        return "set" if self._settings.anthropic_api_key.strip() else "not set"

    def _approval_counts(self) -> dict[str, int]:
        """Return real, honest per-status approval counts.

        Sums the already-injected ApprovalHistoryStore.count_by_status()
        across every status in KNOWN_APPROVAL_STATUSES - the same
        reuse ApprovalHistoryTool._format_history() already
        established, never a new store method, never an invented or
        partial status list. Every status is included, even one with
        zero entries - an honest zero, never omitted. Shared by
        _approval_history_status() (this tool's own text report) and
        get_context() (the structured data PreparePromptTool reuses),
        so the underlying store calls are never duplicated.

        Returns:
            A dict mapping each known status to its real, total count.
        """
        return {
            status: self._approval_history_store.count_by_status(status)
            for status in KNOWN_APPROVAL_STATUSES
        }

    def _approval_history_status(self) -> str:
        """Report a real, honest approval-history status breakdown.

        Returns:
            A short, human-readable status line.
        """
        counts = self._approval_counts()
        total = sum(counts.values())
        breakdown = ", ".join(
            f"{status}: {count}" for status, count in counts.items()
        )
        return f"{total} total ({breakdown})"

    def _workflow_history_status(self) -> str:
        """Report the real, unbounded count of distinct workflows recorded.

        Calls only count_distinct_workflows() (Phase 80, Batch 2) - a
        true, unbounded COUNT of distinct workflow ids, never raw
        transition rows.

        Returns:
            A short, human-readable status line.
        """
        count = self._workflow_history_store.count_distinct_workflows()
        return f"{count} distinct workflow{'' if count == 1 else 's'} recorded"

    def get_context(self) -> PromptContext:
        """Return real Jarvis state as a structured PromptContext
        (Phase 86, Batch 2).

        Reuses the exact same private helper methods run() itself
        already uses - never re-derives or duplicates the underlying
        Settings/store/manager calls, and never requires a caller
        (such as PreparePromptTool) to parse this tool's own
        human-readable text output back apart.

        Returns:
            A PromptContext populated entirely from real, already-
            proven data - nothing here is estimated or fabricated.
        """
        counts = self._approval_counts()
        total = sum(counts.values())
        breakdown = ", ".join(
            f"{status}: {count}" for status, count in counts.items()
        )
        return PromptContext(
            ai_reasoning_enabled=self._settings.ai_reasoning_enabled,
            ai_model=self._settings.ai_model,
            api_key_status=self._api_key_status(),
            memory_count=self._memory_manager.count(),
            approval_total=total,
            approval_breakdown=breakdown,
            workflow_count=self._workflow_history_store.count_distinct_workflows(),
            tool_count=len(self._registry.list_tool_names()),
        )
