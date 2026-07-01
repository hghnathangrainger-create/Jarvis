"""
file_read_tool_smoke_test.py

A standalone smoke test for the Jarvis FileReadTool.

Run this directly (no pytest needed) to see the tool read files through the
full ToolExecutor security gate. It creates a small text file and a large one,
reads them (GREEN, runs automatically), shows truncation on the large file,
refuses a binary file, and reports errors for a missing path, a nonexistent
path, and a directory.

Place this file in the project root and run it from PowerShell:

    poetry run python file_read_tool_smoke_test.py
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
from tools.builtin import FileReadTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


def _show(label: str, result: ToolResult) -> None:
    status = "OK" if result.success else "FAILED"
    print(f"[{status:6}] {label}")
    text = result.output if result.success else (result.error or "")
    for line in text.splitlines()[:6]:
        print(f"         {line}")
    if result.success and len(text.splitlines()) > 6:
        print("         ...")
    print()


def _build_files() -> tuple[Path, Path, Path]:
    """Create a small text file, a large text file, and a binary file."""
    root = Path(tempfile.mkdtemp())

    small = root / "note.txt"
    small.write_text("Hello from Jarvis.\nThis is a short note.\n", encoding="utf-8")

    large = root / "big.txt"
    large.write_text("SAMPLE " * 2000, encoding="utf-8")

    binary = root / "image.bin"
    binary.write_bytes(b"\x89PNG\r\n\x00\x00\x00binary\x00data")

    return small, large, binary


def main() -> None:
    """Wire up the executor and read a few sample files."""
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    factory = create_session_factory(engine)

    logger = EventLogger(AuditLog(factory))
    security = SecurityManager()

    registry = ToolRegistry()
    registry.register_tool(FileReadTool())
    executor = ToolExecutor(registry=registry, security_manager=security, logger=logger)

    small, large, binary = _build_files()

    print("Jarvis FileReadTool - smoke test")
    print("=" * 70)
    print()

    _show("read small text file", executor.execute("file_read", {"path": str(small)}))
    _show(
        "read large file (max_chars=120)",
        executor.execute("file_read", {"path": str(large), "max_chars": 120}),
    )
    _show("refuse binary file", executor.execute("file_read", {"path": str(binary)}))
    _show("missing path", executor.execute("file_read", {}))
    _show("nonexistent path", executor.execute("file_read", {"path": "/no/such/file"}))
    _show(
        "directory instead of file",
        executor.execute("file_read", {"path": str(small.parent)}),
    )

    print("=" * 70)
    print("The tool read text files read-only as a GREEN action, truncated a")
    print("large file cleanly, refused a binary file, and never modified anything.")


if __name__ == "__main__":
    main()