"""
builtin

Built-in tools shipped with Jarvis.

Read-only tools (GREEN) - these never change any state:
    - EchoTool: returns the provided text.
    - InfoTool: returns basic Jarvis system information.
    - MemoryTool: lists or searches stored memories.
    - FileListTool: lists files and folders in a directory (Phase 2).
    - FileReadTool: reads the contents of a text file (Phase 2).
    - FileSearchTool: searches for files by name or by content within a
      directory tree (Phase 24). Never returns full file content -
      names/paths and, for content matches, a short context snippet
      only.
    - ApprovalHistoryTool: shows durable approval history (Phase 6).
    - WorkflowHistoryTool: shows durable workflow lifecycle history
      (Durable Workflow Lifecycle Foundation - a prerequisite turn, not a
      numbered phase).
    - WebSearchTool: performs a live web search and returns titles, URLs,
      and snippets - not full webpage content (Phase 16). Jarvis's first
      external-network tool; depends only on the WebSearchProvider
      abstraction, never a concrete search vendor directly.
    - ScheduleListTool: lists Nathan's configured web-search-summary
      schedules (Phase 21). Read-only; never creates, enables, disables,
      claims, or runs anything.
    - ConfigTool: reports Jarvis's current configuration status (Phase
      31). Reads only the already-loaded Settings object - never .env
      or os.environ directly, never mutates anything. The API key is
      reported only as "set"/"not set", never its value.
    - HelpTool: lists Jarvis's currently supported commands (Phase 43).
      A static, hand-maintained list, never AI-generated and never
      derived from CommandRouter at runtime.
    - HealthCheckTool: reports basic Jarvis system health (Phase 57) -
      settings loaded, database path reachable, tool registry
      populated, console logging configured, Inbox store reachable,
      Schedule store reachable, Quarantine store reachable, and a
      SecurityManager self-classification check confirming its own
      action remains GREEN. Every check reads an already-constructed
      object's existing state; nothing is created, opened, or mutated.
    - QuarantineListTool: lists what is currently inside Jarvis's
      quarantine directory (.jarvis_trash/, Phase 36) - name, size, and
      modified time only. Never reads file content, never creates the
      quarantine directory, and never implies restore support exists.
    - JarvisBrainStatusTool: reports Jarvis's own current AI/reasoning
      configuration, real memory/approval/workflow counts, tool
      registry size, and an honest "current limits" section (Phase 86,
      Batch 1). Never calls AI, a subprocess, or the web; has no live
      knowledge of the current git branch, commit, or test suite
      result.
    - PreparePromptTool: assembles a well-structured, Claude-ready
      prompt (implementation/review/brainstorm/critique/compare) for
      the user to copy and paste into an actual Claude conversation
      manually (Phase 86, Batch 2 - "Claude Prompt Studio"). Never
      calls the Claude API, any other AI provider, a subprocess, or
      git; every generated prompt includes an explicit "fill in
      yourself" placeholder for the current phase/commit/branch/test
      result instead of fabricating it.
    - ProjectStateShowTool: reports Jarvis's manually-maintained
      project-state record - branch, phase, commit, suite result, and
      focus (Phase 89, Batch 1). Every field is exactly what Nathan
      last recorded via ProjectStateUpdateTool, or an honest "not
      recorded yet"; never auto-detected from git, a subprocess, or
      the filesystem.

Guarded read tools (YELLOW) - read-only from Jarvis's own state's point of
view, but classified YELLOW because they reach an arbitrary, externally-
controlled network target rather than a fixed, vetted endpoint:
    - WebpageReadTool: fetches one webpage (via Phase 32's WebFetchPolicy/
      SafeWebFetcher) and returns its extracted, sanitized plain text -
      never a summary, never AI-reasoned about, never persisted (Phase 33).

Guarded write tools (YELLOW) - these change state and require approval before
they run, enforced by the Tool Executor and Approval Manager (Phase 4):
    - FileCreateTool: creates a NEW text file; never overwrites.
    - FileAppendTool: appends text to an EXISTING text file; never overwrites.
    - FileCopyTool: copies an EXISTING file to a new destination path
      (Phase 25); never overwrites an existing destination, never
      touches the source file, and never creates parent folders.
    - FileMoveTool: moves/renames an EXISTING file to a new destination
      path (Phase 26); never overwrites an existing destination, never
      creates parent folders, and never deletes, copies, or executes
      anything - a same-directory destination is a rename and a
      cross-directory destination is a move, both via one tool.
    - FileDeleteTool: quarantines an EXISTING file by moving it into a
      Jarvis-managed .jarvis_trash/ directory (Phase 35) - it is never
      permanently destroyed. Never overwrites a file already in
      quarantine, never touches symlinks or directories, and has no
      companion empty-trash command.
    - FileRestoreTool: restores one previously-quarantined file back to
      its recorded original location (Phase 38) - only when a durable
      QuarantineRecord (Phase 37) exists for it. Never overwrites an
      existing file, never creates the original parent folder, never
      copies (always moves), and never permanently deletes or mutates
      quarantine metadata.
    - MemoryUpdateTool: updates a memory's content or category by id.
    - MemoryForgetTool: forgets one specific memory by id; no bulk delete.
    - ScheduleCreateTool: creates a new daily web-search-summary schedule
      (Phase 21). Persists a row only; never performs a search, calls AI,
      or writes an Inbox entry itself.
    - ScheduleEnableTool: re-enables a schedule by id (Phase 21).
    - ScheduleDisableTool: disables a schedule by id (Phase 21) - the
      only way to stop a schedule from running; there is no delete tool.
    - ScheduleVerifyEnabledStateTool: internal-only, reads back one
      schedule's current enabled state as structured metadata (Phase
      94, Batch 2) - never selectable by AI, never a user command;
      reachable only as the fixed second step of the schedule-enable-
      and-verify workflow.
    - ScheduleShowEnabledStateTool: reads back one schedule's current
      enabled state by its exact id (Phase 99, Batch 1) - unlike
      ScheduleVerifyEnabledStateTool, this one is real and public:
      selectable via "ask jarvis to:", with its own catalog entry, and
      intended to be shown to the user as a genuine result. Read-only
      and safe; no CommandRouter grammar entry of its own.
    - ProjectStateUpdateTool: updates one field (branch, phase, commit,
      suite, focus) of Jarvis's manually-maintained project-state
      record (Phase 89, Batch 1). Never inspects git, a subprocess, or
      the filesystem - every value comes only from what Nathan
      explicitly typed.

No built-in tool edits in place, installs software, runs commands, or
controls the computer. FileMoveTool, FileDeleteTool, and FileRestoreTool
are the sole exceptions to "no move" - one relocates a file to a
Nathan-chosen destination, one relocates it into Jarvis's own
quarantine directory, and the third relocates a quarantined file back
to its recorded original location - and none of the three ever
overwrites an existing destination or permanently destroys anything.
"""

from __future__ import annotations
from tools.builtin.approval_history_tool import ApprovalHistoryTool

from tools.builtin.config_tool import ConfigTool
from tools.builtin.echo_tool import EchoTool
from tools.builtin.file_append_tool import FileAppendTool
from tools.builtin.goal_create_tool import GoalCreateTool
from tools.builtin.goal_progress_tool import GoalProgressTool
from tools.builtin.knowledge_add_tool import KnowledgeAddTool
from tools.builtin.knowledge_search_tool import KnowledgeSearchTool
from tools.builtin.observability_tool import ObservabilityTool
from tools.builtin.plugin_manager_tool import PluginManagerTool
from tools.builtin.voice_control_tool import VoiceControlTool
from tools.builtin.project_create_tool import ProjectCreateTool
from tools.builtin.project_status_tool import ProjectStatusTool
from tools.builtin.window_tool import WindowTool
from tools.builtin.input_tool import InputTool
from tools.builtin.command_tool import CommandTool
from tools.builtin.screen_tool import ScreenTool
from tools.builtin.file_copy_tool import FileCopyTool
from tools.builtin.file_create_tool import FileCreateTool
from tools.builtin.file_delete_tool import FileDeleteTool
from tools.builtin.file_list_tool import FileListTool
from tools.builtin.file_move_tool import FileMoveTool
from tools.builtin.file_read_tool import FileReadTool
from tools.builtin.file_restore_tool import FileRestoreTool
from tools.builtin.file_search_tool import FileSearchTool
from tools.builtin.health_check_tool import HealthCheckTool
from tools.builtin.help_tool import HelpTool
from tools.builtin.info_tool import InfoTool
from tools.builtin.jarvis_brain_tool import JarvisBrainStatusTool
from tools.builtin.memory_forget_tool import MemoryForgetTool
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.memory_update_tool import MemoryUpdateTool
from tools.builtin.prepare_prompt_tool import PreparePromptTool
from tools.builtin.project_state_show_tool import ProjectStateShowTool
from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool
from tools.builtin.quarantine_list_tool import QuarantineListTool
from tools.builtin.schedule_create_tool import ScheduleCreateTool
from tools.builtin.schedule_disable_tool import ScheduleDisableTool
from tools.builtin.schedule_enable_tool import ScheduleEnableTool
from tools.builtin.schedule_list_tool import ScheduleListTool
from tools.builtin.schedule_show_enabled_state_tool import (
    ScheduleShowEnabledStateTool,
)
from tools.builtin.schedule_verify_enabled_state_tool import (
    ScheduleVerifyEnabledStateTool,
)
from tools.builtin.task_complete_tool import TaskCompleteTool
from tools.builtin.web_search_tool import WebSearchTool
from tools.builtin.webpage_read_tool import WebpageReadTool
from tools.builtin.workflow_history_tool import WorkflowHistoryTool
from tools.builtin.android_tool import AndroidTool
from tools.builtin.cost_tracking_tool import CostTrackingTool
from tools.builtin.security_tool import SecurityTool
from tools.builtin.agent_tool import AgentTool

__all__ = [
    "ApprovalHistoryTool",
    "ConfigTool",
    "HealthCheckTool",
    "HelpTool",
    "JarvisBrainStatusTool",
    "PreparePromptTool",
    "ProjectStateShowTool",
    "ProjectStateUpdateTool",
    "ProjectStateVerifyTool",
    "QuarantineListTool",
    "EchoTool",
    "GoalCreateTool",
    "GoalProgressTool",
    "InfoTool",
    "KnowledgeAddTool",
    "KnowledgeSearchTool",
    "ObservabilityTool",
    "PluginManagerTool",
    "VoiceControlTool",
    "ProjectCreateTool",
    "ProjectStatusTool",
    "WindowTool",
    "InputTool",
    "CommandTool",
    "ScreenTool",
    "MemoryTool",
    "FileListTool",
    "FileReadTool",
    "FileSearchTool",
    "FileCreateTool",
    "FileAppendTool",
    "FileCopyTool",
    "FileMoveTool",
    "FileDeleteTool",
    "FileRestoreTool",
    "MemoryUpdateTool",
    "MemoryForgetTool",
    "TaskCompleteTool",
    "WorkflowHistoryTool",
    "WebSearchTool",
    "WebpageReadTool",
    "ScheduleCreateTool",
    "ScheduleListTool",
    "ScheduleEnableTool",
    "ScheduleDisableTool",
    "ScheduleVerifyEnabledStateTool",
    "ScheduleShowEnabledStateTool",
    "AndroidTool",
    "CostTrackingTool",
    "SecurityTool",
    "AgentTool",
]
