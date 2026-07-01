"""
builtin

Built-in tools shipped with Jarvis.

All built-in tools listed here are safe and read-only:
    - EchoTool: returns the provided text.
    - InfoTool: returns basic Jarvis system information.
    - MemoryTool: lists or searches stored memories.
    - FileListTool: lists files and folders in a directory (Phase 2).

None of these tools change system state, run commands, delete data, install
software, send messages, or read file contents.
"""

from __future__ import annotations

from tools.builtin.echo_tool import EchoTool
from tools.builtin.file_list_tool import FileListTool
from tools.builtin.info_tool import InfoTool
from tools.builtin.memory_tool import MemoryTool

__all__ = ["EchoTool", "InfoTool", "MemoryTool", "FileListTool"]