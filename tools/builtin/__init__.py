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
    - MemoryUpdateTool: updates a memory's content or category by id.
    - MemoryForgetTool: forgets one specific memory by id; no bulk delete.
    - ScheduleCreateTool: creates a new daily web-search-summary schedule
      (Phase 21). Persists a row only; never performs a search, calls AI,
      or writes an Inbox entry itself.
    - ScheduleEnableTool: re-enables a schedule by id (Phase 21).
    - ScheduleDisableTool: disables a schedule by id (Phase 21) - the
      only way to stop a schedule from running; there is no delete tool.

No built-in tool deletes, edits in place, installs software, runs commands,
or controls the computer. FileMoveTool is the sole exception to "no move" -
it moves/renames a single file, with approval, and never overwrites, never
deletes, and never touches directories.
"""

from __future__ import annotations
from tools.builtin.approval_history_tool import ApprovalHistoryTool

from tools.builtin.echo_tool import EchoTool
from tools.builtin.file_append_tool import FileAppendTool
from tools.builtin.file_copy_tool import FileCopyTool
from tools.builtin.file_create_tool import FileCreateTool
from tools.builtin.file_list_tool import FileListTool
from tools.builtin.file_move_tool import FileMoveTool
from tools.builtin.file_read_tool import FileReadTool
from tools.builtin.file_search_tool import FileSearchTool
from tools.builtin.info_tool import InfoTool
from tools.builtin.memory_forget_tool import MemoryForgetTool
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.memory_update_tool import MemoryUpdateTool
from tools.builtin.schedule_create_tool import ScheduleCreateTool
from tools.builtin.schedule_disable_tool import ScheduleDisableTool
from tools.builtin.schedule_enable_tool import ScheduleEnableTool
from tools.builtin.schedule_list_tool import ScheduleListTool
from tools.builtin.web_search_tool import WebSearchTool
from tools.builtin.workflow_history_tool import WorkflowHistoryTool

__all__ = [
    "ApprovalHistoryTool",
    "EchoTool",
    "InfoTool",
    "MemoryTool",
    "FileListTool",
    "FileReadTool",
    "FileSearchTool",
    "FileCreateTool",
    "FileAppendTool",
    "FileCopyTool",
    "FileMoveTool",
    "MemoryUpdateTool",
    "MemoryForgetTool",
    "WorkflowHistoryTool",
    "WebSearchTool",
    "ScheduleCreateTool",
    "ScheduleListTool",
    "ScheduleEnableTool",
    "ScheduleDisableTool",
]
