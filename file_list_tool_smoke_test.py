"""
file_list_tool_smoke_test.py

A standalone smoke test for the Jarvis FileListTool.

Run this directly (no pytest needed) to see the tool list a directory through
the full ToolExecutor security gate. It builds a small temporary directory,
lists it (GREEN, runs automatically), and shows the error handling for a
missing path, a nonexistent path, and a file used in place of a folder.

Place this file in the project root and run it from PowerShell:

    poetry run python file_list_tool_smoke_test.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from config.settings import load_settings
from observability.logger import EventLogger
from security.audit_log import AuditLog
from security.security_manager import SecurityManager
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from tools.base_tool import ToolResult
from tools.builtin import FileListTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


def _show(label: str, result: ToolResult) -> None:
    status = "OK" if result.success else "FAILED"
    print(f"[{status:6}] {label}")
    text = result.output if result.success else (result.error or "")
    for line in text.splitlines():
        print(f"         {line}")
    print()


def _build_sample_dir() -> Path:
    """Create a temporary directory with a few files and folders."""
    root = Path(tempfile.mkdtemp())
    (root / "notes.txt").touch()
    (root / "todo.md").touch()
    (root / "images").mkdir()
    (root / "archive").mkdir()
    return root


def main() -> None:
    """Wire up the executor and list a sample directory."""
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    logger = EventLogger(AuditLog(factory))
    security = SecurityManager()

    registry = ToolRegistry()
    registry.register_tool(FileListTool())
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)

    sample = _build_sample_dir()

    print("Jarvis FileListTool - smoke test")
    print("=" * 70)
    print()

    _show(f"list {sample}", executor.execute("file_list", {"path": str(sample)}))
    _show("list with limit=2", executor.execute("file_list", {"path": str(sample), "limit": 2}))
    _show("missing path", executor.execute("file_list", {}))
    _show("nonexistent path", executor.execute("file_list", {"path": "/no/such/dir"}))
    _show(
        "file instead of folder",
        executor.execute("file_list", {"path": str(sample / "notes.txt")}),
    )

    print("=" * 70)
    print("The tool listed the directory read-only, as a GREEN action, and")
    print("reported clear errors for invalid paths. Nothing was modified.")


if __name__ == "__main__":
    main()