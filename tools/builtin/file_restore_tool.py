"""
file_restore_tool.py

A guarded write tool that restores one previously-quarantined file back
to its recorded original location (Phase 38, Batch 1).

FileRestoreTool is a YELLOW tool: moving a file out of Jarvis's
quarantine directory and back onto the filesystem changes state, so its
action is classified YELLOW and it runs only after explicit approval
through the normal Tool Executor and Approval Manager path, exactly
like FileCreateTool/FileAppendTool/FileCopyTool/FileMoveTool/
FileDeleteTool. It is deliberately conservative, and deliberately
narrow:

    - It restores exactly one file per call, and only a file that is
      currently inside Jarvis's quarantine directory (.jarvis_trash/,
      Phase 35) - never an arbitrary path elsewhere on disk.
    - It only restores a file that has a durable QuarantineRecord
      (Phase 37) - i.e. one quarantined since Phase 37's metadata
      table existed (or otherwise recorded). A quarantined file with no
      matching record fails cleanly with an honest explanation; this
      tool never guesses an original location from the quarantine
      filename (the filename only ever preserves the original
      stem/suffix, Phase 35, never the original directory).
    - It never reads QuarantineRecord.original_path from user input -
      the destination always comes only from the stored metadata,
      never from anything the caller supplies.
    - It never overwrites an existing file: if the recorded
      original_path already exists, the restore is refused, exactly
      like FileMoveTool/FileCopyTool's own destination-exists refusal.
    - It never creates the original parent folder: if the recorded
      original_path's parent directory no longer exists, the restore is
      refused rather than recreating it - mirroring FileMoveTool/
      FileCopyTool's own "does not create folders" behaviour.
    - It moves the file (Path.rename()) - it never copies. On success,
      no duplicate is left behind in quarantine; the file is gone from
      .jarvis_trash/ and present at its restored original_path.
    - It never permanently deletes anything - no production code path
      in this module calls os.remove(), os.unlink(), Path.unlink(),
      shutil.rmtree(), os.rmdir(), or Path.rmdir().
    - It never updates or deletes the underlying QuarantineRecord row -
      QuarantineStore exposes no such method (Phase 37), and this tool
      does not ask it to. The record remains historical metadata: "this
      file was quarantined," not "this file's current status."
    - It refuses to restore a symlink or a directory found at the
      supplied quarantine path, matching FileDeleteTool's own existing
      symlink/directory caution exactly.
    - It refuses any path that does not resolve to a file directly
      inside the quarantine directory - including path traversal
      attempts (e.g. "../secret.txt") and absolute paths pointing
      elsewhere. This tool never restores an arbitrary file that was
      never actually quarantined.

Supported input (via input_data):
    path: identifies the quarantined file to restore (required). Either
          a bare filename with no path separators - resolved directly
          inside the quarantine directory, exactly as shown by
          "list quarantine"/"show quarantine" - or a path (relative or
          absolute) that must resolve to a file directly inside the
          quarantine directory. Any other path is rejected.

Safety note:
    This tool does not enforce approval itself. Approval is enforced by
    the Tool Executor, which classifies this tool's action ("restore
    file") as YELLOW and withholds it until an approved decision is
    supplied. This tool simply performs the restore when it is finally
    allowed to run - and even then, still refuses to overwrite an
    existing file or restore a file with no known original location.
"""

from __future__ import annotations

from pathlib import Path

from quarantine.quarantine_store import QuarantineStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin.file_delete_tool import _QUARANTINE_DIR_NAME


class FileRestoreTool(BaseTool):
    """Restores one previously-quarantined file back to its recorded
    original location.

    Sensitive (YELLOW); only restores files with a known quarantine
    metadata record, never overwrites an existing file, never creates
    the original parent folder, never copies (always moves), and never
    permanently deletes or mutates quarantine metadata.

    Attributes:
        _store: The QuarantineStore used to look up each restore
            target's recorded original path. Required - this tool has
            no useful behaviour without it, unlike FileDeleteTool/
            QuarantineListTool, which remain fully functional (just
            without metadata) when constructed with no store.
    """

    def __init__(self, store: QuarantineStore) -> None:
        """Initialise the tool with a QuarantineStore.

        Args:
            store: The store used to read (never write) each restore
                target's recorded original path. Injected, never
                constructed here - mirrors FileDeleteTool/
                QuarantineListTool's own store-injection pattern.
        """
        self._store = store

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_restore".
        """
        return "file_restore"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description, explicit about the metadata
            requirement and the never-overwrite guarantee.
        """
        return (
            "Restores one previously-quarantined file back to its recorded "
            "original location. Sensitive: requires approval. Only works "
            "for files with a known quarantine metadata record; never "
            "overwrites an existing file."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed action string for security classification.

        This is always the same fixed phrase regardless of the actual
        quarantine path - restoring a file changes state (a new file
        appears at the original path, and the quarantine copy
        disappears) in exactly the same way every time, so the string
        the Security Manager classifies never varies with user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "restore file", classified YELLOW.
        """
        return "restore file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Restore the requested quarantined file to its recorded original path.

        Args:
            request: The request. Recognised input key:
                path: identifies the quarantined file to restore
                    (required) - see the module docstring for the two
                    accepted forms.

        Returns:
            A successful ToolResult when the file is restored, or a
            failed result if the path is missing, does not resolve to a
            file directly inside the quarantine directory, does not
            exist, is a symlink, is a directory, has no matching
            quarantine metadata record, its recorded original_path
            already exists, its recorded original parent folder no
            longer exists, or a permission/OS error occurs. Never
            raises, never overwrites, never copies, and never
            permanently deletes or mutates quarantine metadata.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail(
                "Missing required input: 'path' (the quarantined file to "
                "restore, as shown by 'list quarantine')."
            )

        quarantine_dir = Path(_QUARANTINE_DIR_NAME)
        resolved_quarantine_root = quarantine_dir.resolve()

        raw = raw_path.strip()
        candidate = Path(raw).expanduser()

        is_bare_name = (
            not candidate.is_absolute()
            and candidate.parent == Path(".")
            and candidate.name not in ("", "..")
        )
        if is_bare_name:
            # The exact form "list quarantine" displays - always
            # resolved directly inside the quarantine directory,
            # regardless of the current working directory's other
            # contents.
            candidate = quarantine_dir / candidate.name

        resolved_candidate = candidate.resolve()

        if resolved_candidate.parent != resolved_quarantine_root:
            return self.fail(
                f"'{raw}' does not refer to a file directly inside the "
                f"quarantine directory ('{quarantine_dir}'). This tool "
                "only restores files that are currently quarantined."
            )

        if not resolved_candidate.exists():
            return self.fail(
                f"Quarantined file does not exist: {resolved_candidate}"
            )

        if resolved_candidate.is_symlink():
            return self.fail(
                f"Refusing to restore '{resolved_candidate}': it is a "
                "symlink, not a regular file. This tool does not support "
                "symlinks."
            )

        if resolved_candidate.is_dir():
            return self.fail(
                f"Quarantine path is a directory, not a file: "
                f"{resolved_candidate}. This tool only restores single "
                "files."
            )

        record = self._store.get_by_quarantine_path(str(resolved_candidate))
        if record is None:
            return self.fail(
                f"No quarantine metadata record found for "
                f"'{resolved_candidate}'. Jarvis cannot restore this file "
                "automatically because its original location is unknown - "
                "it may have been quarantined before original-path "
                "metadata tracking was added."
            )

        original_path = Path(record.original_path)

        if original_path.exists():
            return self.fail(
                f"Refusing to restore to '{original_path}': it already "
                "exists. This tool never overwrites an existing file."
            )

        parent = original_path.parent
        if not parent.exists():
            return self.fail(
                f"Original parent folder no longer exists: {parent}. This "
                "tool does not recreate folders; please create the folder "
                "first if you want to restore this file."
            )
        if not parent.is_dir():
            return self.fail(f"Original parent path is not a folder: {parent}")

        try:
            resolved_candidate.rename(original_path)
        except FileExistsError:
            # A race: the destination appeared between the check and the
            # rename - never overwritten, exactly like FileMoveTool's own
            # equivalent race guard.
            return self.fail(
                f"Refusing to restore to '{original_path}': it already "
                "exists."
            )
        except PermissionError:
            return self.fail(
                f"Permission denied while restoring '{resolved_candidate}' "
                f"to '{original_path}'."
            )
        except OSError as exc:
            return self.fail(f"Could not restore file: {exc}")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Restored '{resolved_candidate}' from quarantine back to "
                f"'{original_path}'. It is no longer in quarantine."
            ),
            metadata={
                "quarantine_path": str(resolved_candidate),
                "original_path": str(original_path),
                "operation": "restore",
            },
        )
