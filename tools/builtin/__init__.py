"""
builtin

Built-in tools shipped with Jarvis in Phase 1.

All Phase 1 built-in tools are safe and read-only:
    - EchoTool: returns the provided text.
    - InfoTool: returns basic Jarvis system information.
    - MemoryTool: lists or searches stored memories.

None of these tools change system state, run commands, delete data, install
software, or send messages.
"""

from __future__ import annotations

from tools.builtin.echo_tool import EchoTool
from tools.builtin.info_tool import InfoTool
from tools.builtin.memory_tool import MemoryTool

__all__ = ["EchoTool", "InfoTool", "MemoryTool"]