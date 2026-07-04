"""
builtin

Built-in tools shipped with Jarvis.

Read-only tools (GREEN) - these never change any state:
    - EchoTool: returns the provided text.
    - InfoTool: returns basic Jarvis system information.
    - MemoryTool: lists or searches stored memories.
    - FileListTool: lists files and folders in a directory (Phase 2).
    - FileReadTool: reads the contents of a text file (Phase 2).

Guarded write tools (YELLOW) - these change state and require approval before
they run, enforced by the Tool Executor and Approval Manager (Phase 4):
    - FileCreateTool: creates a NEW text file; never overwrites.
    - FileAppendTool: appends text to an EXISTING text file; never overwrites.
    - MemoryUpdateTool: updates a memory's content or category by id.
    - MemoryForgetTool: forgets one specific memory by id; no bulk delete.

No built-in tool deletes, moves, renames, edits in place, installs software,
runs commands, or controls the computer.
"""

from __future__ import annotations
from tools.builtin.approval_history_tool import ApprovalHistoryTool

from tools.builtin.echo_tool import EchoTool
from tools.builtin.file_append_tool import FileAppendTool
from tools.builtin.file_create_tool import FileCreateTool
from tools.builtin.file_list_tool import FileListTool
from tools.builtin.file_read_tool import FileReadTool
from tools.builtin.info_tool import InfoTool
from tools.builtin.memory_forget_tool import MemoryForgetTool
from tools.builtin.memory_tool import MemoryTool
from tools.builtin.memory_update_tool import MemoryUpdateTool

__all__ = [
    "ApprovalHistoryTool",
    "EchoTool",
    "InfoTool",
    "MemoryTool",
    "FileListTool",
    "FileReadTool",
    "FileCreateTool",
    "FileAppendTool",
    "MemoryUpdateTool",
    "MemoryForgetTool",
]
