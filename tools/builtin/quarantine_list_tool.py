"""
quarantine_list_tool.py

A safe, read-only tool that lists the contents of Jarvis's quarantine
directory (Phase 36; extended Phase 37, Batch 2 to display known
original-path metadata; extended Phase 72, Batch 2 with a real, honest
total-file count in the list header).

QuarantineListTool is a GREEN tool: it only reads directory entries and
file metadata (name, size, modified time) from `.jarvis_trash/` - the
same Jarvis-managed quarantine directory FileDeleteTool moves files
into (Phase 35) - plus, when a QuarantineStore is supplied, a read-only
lookup of each file's recorded original path (Phase 37). It is purely
observational and never implies restore support exists, because none
does.

Does NOT:
    - Create `.jarvis_trash/` if it does not already exist - an absent
      directory is reported honestly as "nothing has been quarantined
      yet", never silently created just to be listed.
    - Read any file's content. Only filesystem metadata (name, size,
      modified time) and, when available, its recorded original path
      are inspected.
    - Modify, move, rename, or delete anything - no production code
      path in this module calls os.remove(), os.unlink(),
      Path.unlink(), shutil.rmtree(), os.rmdir(), or Path.rmdir(), and
      none writes or moves a file either.
    - Write any quarantine metadata - only QuarantineStore.
      get_by_quarantine_path() (a read) is ever called here; this
      module never calls record_quarantine() or any other write.
    - Infer an original path from a quarantine filename. The filename
      only ever preserves the original stem/suffix (Phase 35's own
      collision-safe naming), never the original directory - guessing
      one from the name would be misleading, so a missing metadata
      record is always shown as an honest "unknown", never a guess.
    - Recurse into an unexpected subdirectory that might appear inside
      `.jarvis_trash/` (FileDeleteTool itself never creates one, but
      this tool still handles that case safely if it's ever found some
      other way) - such an entry is reported as an unsupported,
      skipped entry, never traversed into.
    - Persist anything - this is a read of the live filesystem state
      (and, when available, the durable quarantine metadata) at the
      moment the command runs, nothing more.

Phase 37, Batch 2 addition: when constructed with a QuarantineStore,
each listed file's original path is looked up and displayed if a
durable record exists for it (Phase 37, Batch 1). Files quarantined
before that table existed - or when no store was supplied at all -
show an honest "unknown (quarantined before metadata tracking)"
fallback rather than failing or guessing. The store is optional
(defaults to None), so every pre-existing caller/test that constructs
this tool with no arguments continues to behave exactly as Phase 36
already did, aside from that added fallback text.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from quarantine.quarantine_store import QuarantineStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME

#: Shown in place of a recorded original path when no QuarantineStore
#: was supplied, or the store has no record for a given quarantined
#: file (the ordinary, expected case for anything quarantined before
#: Phase 37's metadata table existed - never treated as an error).
_UNKNOWN_ORIGINAL_PATH = "unknown (quarantined before metadata tracking)"


class QuarantineListTool(BaseTool):
    """Lists the contents of Jarvis's quarantine directory (.jarvis_trash/).

    Read-only and safe - never creates, modifies, moves, or deletes
    anything, and never implies restore support exists.

    Attributes:
        _store: Optional QuarantineStore used to look up each listed
            file's recorded original path. When None (the default),
            every entry shows the "unknown" fallback instead.
    """

    def __init__(self, store: QuarantineStore | None = None) -> None:
        """Initialise the tool, optionally with a QuarantineStore.

        Args:
            store: Optional store used to read (never write) each
                listed file's recorded original path. Injected, never
                constructed here - mirrors FileDeleteTool's own
                store-injection pattern. Defaults to None, preserving
                every pre-Phase-37 caller's behaviour unchanged aside
                from the added "unknown" fallback text.
        """
        self._store = store

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
            "(.jarvis_trash/), showing each file's original path when "
            "known. Read-only: does not restore, delete, or clean up "
            "anything."
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
            files present, each with its size and modified time, with
            the header reporting a real, honest total count (Phase 72,
            Batch 2) tallied from this same already-computed `files`
            list - no new store method or query. Never creates the
            directory, never reads a file's content, and never
            modifies, moves, or deletes anything.
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
            lines.append(f"Quarantined files ({len(files)} total):")
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

    def _format_entry(self, entry: Path) -> str:
        """Format one quarantined file as a single readable line.

        Never reads the file's content - only filesystem metadata and,
        when a store is available, the file's recorded original path.

        Args:
            entry: The quarantined file to describe.

        Returns:
            A single line naming the file, its size in bytes, when it
            was last modified (a reasonable proxy for "when it was
            quarantined", since FileDeleteTool only ever moves a file
            into quarantine once, never rewrites it afterward), and its
            original path - either the recorded path, or an honest
            "unknown" fallback if no record exists or no store was
            supplied.
        """
        try:
            stat = entry.stat()
        except OSError as exc:
            return f"  {entry.name} (could not read details: {exc})"

        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        original_path = self._lookup_original_path(entry)
        return (
            f"  {entry.name} - {stat.st_size} bytes, quarantined at "
            f"{modified.isoformat(timespec='seconds')}, original path: "
            f"{original_path}"
        )

    def _lookup_original_path(self, entry: Path) -> str:
        """Return the recorded original path for a quarantined file, if known.

        A pure read: calls only QuarantineStore.get_by_quarantine_path(),
        never a write method. Resolves entry to an absolute path first,
        since FileDeleteTool records quarantine_path in that same
        resolved form (Phase 37, Batch 1).

        Args:
            entry: The quarantined file to look up.

        Returns:
            The recorded original path, or _UNKNOWN_ORIGINAL_PATH if no
            store was supplied or no record exists for this file - the
            ordinary, expected case for anything quarantined before
            Phase 37's metadata table existed.
        """
        if self._store is None:
            return _UNKNOWN_ORIGINAL_PATH

        record = self._store.get_by_quarantine_path(str(entry.resolve()))
        if record is None:
            return _UNKNOWN_ORIGINAL_PATH

        return record.original_path
