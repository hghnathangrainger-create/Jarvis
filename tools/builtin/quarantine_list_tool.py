"""
quarantine_list_tool.py

A safe, read-only tool that lists the contents of Jarvis's quarantine
directory (Phase 36).

QuarantineListTool is a GREEN tool: it only reads directory entries and
file metadata (name, size, modified time) from `.jarvis_trash/` - the
same Jarvis-managed quarantine directory FileDeleteTool moves files
into (Phase 35). It is purely observational and never implies restore
support exists, because none does.

Does NOT:
    - Create `.jarvis_trash/` if it does not already exist - an absent
      directory is reported honestly as "nothing has been quarantined
      yet", never silently created just to be listed.
    - Read any file's content. Only filesystem metadata (name, size,
      modified time) is inspected.
    - Modify, move, rename, or delete anything - no production code
      path in this module calls os.remove(), os.unlink(),
      Path.unlink(), shutil.rmtree(), os.rmdir(), or Path.rmdir(), and
      none writes or moves a file either.
    - Recurse into an unexpected subdirectory that might appear inside
      `.jarvis_trash/` (FileDeleteTool itself never creates one, but
      this tool still handles that case safely if it's ever found some
      other way) - such an entry is reported as an unsupported,
      skipped entry, never traversed into.
    - Persist anything - this is a read of the live filesystem state at
      the moment the command runs, nothing more.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME


class QuarantineListTool(BaseTool):
    """Lists the contents of Jarvis's quarantine directory (.jarvis_trash/).

    Read-only and safe - never creates, modifies, moves, or deletes
    anything, and never implies restore support exists.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "quarantine_list".
        """
        return "quarantine_list"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description, explicit that this is read-only
            and implies no restore support.
        """
        return (
            "Lists files currently in Jarvis's quarantine directory "
            "(.jarvis_trash/). Read-only: does not restore, delete, or "
            "clean up anything."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Args:
            request: The request being handled.

        Returns:
            "list quarantine" - classified GREEN via the existing,
            unchanged generic "list" rule; no new Security Manager
            rule was needed for this tool.
        """
        return "list quarantine"

    def run(self, request: ToolRequest) -> ToolResult:
        """List the current contents of the quarantine directory.

        Args:
            request: The request (no recognised input keys).

        Returns:
            A ToolResult reporting: no quarantine directory exists yet;
            the directory exists but is empty; or the quarantined
            files present, each with its size and modified time.
            Never creates the directory, never reads a file's content,
            and never modifies, moves, or deletes anything.
        """
        quarantine_dir = Path(_QUARANTINE_DIR_NAME)

        if not quarantine_dir.exists():
            return self.ok(
                "No quarantine directory exists yet - nothing has been "
                "quarantined."
            )
        if not quarantine_dir.is_dir():
            return self.fail(f"'{quarantine_dir}' exists but is not a directory.")

        entries = sorted(quarantine_dir.iterdir(), key=lambda entry: entry.name)
        files = [entry for entry in entries if entry.is_file()]
        unsupported = sorted(entry.name for entry in entries if not entry.is_file())

        if not files and not unsupported:
            return self.ok("Quarantine is empty - nothing is currently quarantined.")

        lines: list[str] = []
        if files:
            lines.append("Quarantined files:")
            lines.extend(self._format_entry(entry) for entry in files)
        else:
            lines.append("No quarantined files found.")

        if unsupported:
            lines.append(
                "Unsupported entries (skipped, not files): "
                + ", ".join(unsupported)
            )

        return ToolResult(
            tool_name=self.name,
            success=True,
            output="\n".join(lines),
            metadata={
                "file_count": str(len(files)),
                "unsupported_count": str(len(unsupported)),
            },
        )

    @staticmethod
    def _format_entry(entry: Path) -> str:
        """Format one quarantined file as a single readable line.

        Never reads the file's content - only filesystem metadata.

        Args:
            entry: The quarantined file to describe.

        Returns:
            A single line naming the file, its size in bytes, and when
            it was last modified (a reasonable proxy for "when it was
            quarantined", since FileDeleteTool only ever moves a file
            into quarantine once, never rewrites it afterward).
        """
        try:
            stat = entry.stat()
        except OSError as exc:
            return f"  {entry.name} (could not read details: {exc})"

        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        return (
            f"  {entry.name} - {stat.st_size} bytes, quarantined at "
            f"{modified.isoformat(timespec='seconds')}"
        )
