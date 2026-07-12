"""
file_delete_tool.py

A guarded write tool that quarantines an existing file instead of
permanently deleting it (Phase 35).

FileDeleteTool is a YELLOW tool: removing a file from its original
location changes state, so its action is classified YELLOW and it
runs only after explicit approval through the normal Tool Executor and
Approval Manager path, exactly like FileCreateTool/FileAppendTool/
FileCopyTool/FileMoveTool. It is deliberately conservative, and
deliberately NOT a real delete:

    - It never permanently destroys a file. "Deleting" a file with
      this tool moves it into a Jarvis-managed quarantine directory
      (see _QUARANTINE_DIR_NAME below) - the file still exists on
      disk afterward, just no longer at its original path. No
      production code path in this module calls os.remove(),
      os.unlink(), Path.unlink(), shutil.rmtree(), os.rmdir(), or
      Path.rmdir() - moving (Path.rename()) is the only filesystem
      mutation this tool performs.
    - It moves exactly one existing file into the quarantine directory
      per call. It never overwrites a file already in quarantine -
      each quarantined file gets a unique name (see
      _quarantine_destination below), so a second file with the same
      original name can always be quarantined safely alongside the
      first.
    - The quarantine directory is created on demand, only when a file
      is actually being quarantined - never eagerly, and never as a
      user-provided destination. Nathan never names or chooses this
      location; it is entirely Jarvis-managed.
    - It refuses to quarantine a symlink (matching this codebase's
      existing, established caution around symlinks - see
      FileSearchTool's own is_symlink() exclusion during content
      scans): moving a symlink risks moving a link, not the data
      Nathan actually meant to remove, and this tool does not attempt
      to disambiguate that.
    - It refuses to quarantine a file that is already inside the
      quarantine directory - there is nothing further to do, and
      re-quarantining a quarantined file would just create a redundant
      copy at a new random name for no benefit.
    - It does not restore, list, empty, or clean up the quarantine
      directory in any way - there is no companion "restore file" or
      "empty trash" command in this phase. Once quarantined, a file
      stays there until Nathan manages it himself outside of Jarvis.
    - It never reads or interprets the file's content in any way -
      Path.rename() relocates the file directly, so binary files are
      quarantined correctly with no special handling required.

Supported input (via input_data):
    path: the existing file to quarantine (required, must exist, must
          be a file, must not be a symlink, must not already be inside
          the quarantine directory).

Safety note:
    This tool does not enforce approval itself. Approval is enforced
    by the Tool Executor, which classifies this tool's action ("delete
    file") as YELLOW and withholds it until an approved decision is
    supplied. This tool simply performs the quarantine move when it is
    finally allowed to run.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: The Jarvis-managed quarantine directory, resolved relative to the
#: current working directory at call time - exactly how every other
#: file tool in this codebase already resolves relative paths (there is
#: no separate "project root" concept anywhere else to be consistent
#: with instead). Created on demand inside run(), never eagerly, and
#: never configurable by a caller - this is not a user-provided
#: destination.
_QUARANTINE_DIR_NAME = ".jarvis_trash"

#: How many randomly-suffixed name attempts to try before falling back
#: to a full (128-bit) UUID4 suffix. A short suffix is friendlier to
#: read in a directory listing; the bounded retry loop only exists to
#: defend against the astronomically unlikely case of a short-suffix
#: collision, never expected to iterate more than once in practice.
_MAX_SHORT_NAME_ATTEMPTS = 5


class FileDeleteTool(BaseTool):
    """Moves one existing file into a Jarvis-managed quarantine directory.

    Sensitive (YELLOW); never permanently deletes anything, never
    overwrites a file already in quarantine, and never touches a
    symlink or a file already inside the quarantine directory.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_delete".
        """
        return "file_delete"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description, explicit that this quarantines
            rather than permanently deletes.
        """
        return (
            "Moves an existing file into a Jarvis-managed quarantine "
            "directory - it is not permanently deleted. Sensitive: "
            "requires approval. Never overwrites a file already in "
            "quarantine."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed action string for security classification.

        This is always the same fixed phrase regardless of the actual
        source path - quarantining a file changes state (the original
        path stops existing) in exactly the same way every time, so
        the string the Security Manager classifies never varies with
        user input. "delete file" already matches an existing,
        pre-established YELLOW rule (confirmed directly in
        security/security_manager.py before this tool was written), so
        no new Security Manager rule is required by this tool.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "delete file", classified YELLOW.
        """
        return "delete file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Quarantine the requested file.

        Args:
            request: The request. Recognised input key:
                path: the existing file to quarantine (required).

        Returns:
            A successful ToolResult when the file is moved into
            quarantine, or a failed result if the path is missing,
            does not exist, is a directory, is a symlink, is already
            inside the quarantine directory, or a permission/OS error
            occurs. Never raises, and never permanently deletes
            anything.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail(
                "Missing required input: 'path' (the existing file to "
                "quarantine)."
            )

        source = Path(raw_path.strip()).expanduser()
        quarantine_dir = Path(_QUARANTINE_DIR_NAME)

        if not source.exists():
            return self.fail(f"Source file does not exist: {source}")

        if source.is_symlink():
            return self.fail(
                f"Refusing to quarantine '{source}': it is a symlink, not "
                "a regular file. This tool does not support symlinks."
            )

        if source.is_dir():
            return self.fail(
                f"Source path is a directory, not a file: {source}. This "
                "tool only quarantines single files."
            )

        resolved_source = source.resolve()
        resolved_quarantine_root = quarantine_dir.resolve()
        if resolved_source == resolved_quarantine_root or resolved_source.is_relative_to(
            resolved_quarantine_root
        ):
            return self.fail(
                f"'{source}' is already inside the quarantine directory "
                f"('{quarantine_dir}'); it has already been quarantined."
            )

        try:
            quarantine_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return self.fail(f"Could not create quarantine directory: {exc}")

        destination = self._quarantine_destination(quarantine_dir, source)

        try:
            source.rename(destination)
        except FileExistsError:
            # A race: the chosen quarantine name appeared between the
            # uniqueness check and the rename - never overwritten,
            # exactly like FileMoveTool's own equivalent race guard.
            return self.fail(
                f"Refusing to quarantine '{source}': the destination "
                f"'{destination}' already exists."
            )
        except PermissionError:
            return self.fail(
                f"Permission denied while quarantining '{source}'."
            )
        except OSError as exc:
            return self.fail(f"Could not quarantine file: {exc}")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Moved '{source}' to quarantine at '{destination}'. The "
                "file was not permanently deleted - it can still be found "
                "at that location."
            ),
            metadata={
                "original_path": str(source),
                "quarantine_path": str(destination),
                "operation": "quarantine",
            },
        )

    @staticmethod
    def _quarantine_destination(quarantine_dir: Path, source: Path) -> Path:
        """Choose a unique, never-overwriting destination inside quarantine.

        The original filename is preserved as a readable prefix, with a
        short random suffix appended before the extension so two files
        quarantined with the same original name never collide. A
        bounded number of short-suffix attempts is tried first (purely
        for a friendlier, shorter name); an exceptionally unlikely
        collision across all of them falls back to a full-length UUID4
        suffix, which is collision-resistant enough to treat as never
        colliding in practice.

        Args:
            quarantine_dir: The quarantine directory (already created).
            source: The file being quarantined.

        Returns:
            A destination path inside quarantine_dir that does not
            currently exist.
        """
        stem = source.stem
        suffix = source.suffix

        for _ in range(_MAX_SHORT_NAME_ATTEMPTS):
            candidate = quarantine_dir / f"{stem}__{uuid.uuid4().hex[:8]}{suffix}"
            if not candidate.exists():
                return candidate

        return quarantine_dir / f"{stem}__{uuid.uuid4().hex}{suffix}"
