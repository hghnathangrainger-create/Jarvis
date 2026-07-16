"""
file_move_tool.py

A guarded write tool that moves or renames an existing file to a new
destination path (Phase 26; extended Phase 85, Batch 1 so the success
confirmation discloses the moved file's real byte size, matching
FileCopyTool's own established convention).

FileMoveTool is a YELLOW tool: relocating a file changes state - and,
unlike file_copy, makes the original path stop existing - so its action
is classified YELLOW and it runs only after explicit approval through
the normal Tool Executor and Approval Manager path, exactly like
FileCreateTool/FileAppendTool/FileCopyTool. It is deliberately
conservative:

    - It moves/renames one existing file to one new destination path
      only. A same-directory destination is a rename; a different-
      directory destination is a move - both are the exact same
      underlying operation (Path.rename()), so this is one tool, not
      two, and there is no separate "rename" tool.
    - It never overwrites an existing destination - not even with
      approval; approval only ever authorises the move attempt, never a
      decision to overwrite something already there.
    - It does NOT create parent folders, mirroring FileCreateTool/
      FileCopyTool's own choice exactly: if the destination's parent
      directory does not already exist, the tool fails cleanly.
    - It never reads or interprets the file's content in any way -
      Path.rename() relocates the file directly; no bytes are read or
      rewritten, so binary files move correctly with no special
      handling required.
    - It never deletes, copies, edits in place, or executes anything.
      There is no bulk/recursive/directory move, and no separate delete
      capability is introduced by this tool at all.

Supported input (via input_data):
    source:      the existing file to move/rename (required, must
                 exist, must be a file).
    destination: the new path for the file (required, must not already
                 exist).

Safety note:
    This tool does not enforce approval itself. Approval is enforced by
    the Tool Executor, which classifies this tool's action ("move
    file") as YELLOW and withholds it until an approved decision is
    supplied. This tool simply performs the move when it is finally
    allowed to run - and even then, still refuses if the destination
    exists.
"""

from __future__ import annotations

from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class FileMoveTool(BaseTool):
    """Moves or renames one existing file to a new destination path.

    Sensitive (YELLOW); never overwrites an existing destination, never
    reads or rewrites the file's content, and never creates parent
    folders. A same-directory destination is a rename; a cross-
    directory destination is a move - both are handled by this single
    tool via the same underlying operation.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_move".
        """
        return "file_move"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Moves or renames an existing file to a new destination path. "
            "Sensitive: requires approval. Never overwrites an existing "
            "destination."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed action string for security classification.

        This is always the same fixed phrase regardless of the actual
        source/destination paths - moving a file changes state (the
        original path stops existing) in exactly the same way every
        time, so the string the Security Manager classifies never
        varies with user input. "move file" already matches an
        existing, pre-established YELLOW rule (confirmed directly in
        security/security_manager.py before this tool was written), so
        no new Security Manager rule is required by this tool.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "move file", classified YELLOW.
        """
        return "move file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Move or rename the requested source file to the destination.

        Args:
            request: The request. Recognised input keys:
                source: the existing file to move/rename (required).
                destination: the new path for the file (required).

        Returns:
            A successful ToolResult when the move completes, whose
            output and metadata disclose the moved file's real byte
            size - read from the destination path after the move
            succeeds, since that is the file's actual, resulting state
            (Phase 85, Batch 1) - or a failed result if either path is
            missing, the source does not exist or is not a file, the
            source and destination are the same path, the destination
            already exists, the destination's parent folder does not
            exist, or a permission/OS error occurs (including an
            attempt to move across two different drives/filesystems,
            which a plain rename cannot do).
        """
        raw_source = request.input_data.get("source")
        if not isinstance(raw_source, str) or not raw_source.strip():
            return self.fail(
                "Missing required input: 'source' (the existing file to move)."
            )

        raw_destination = request.input_data.get("destination")
        if not isinstance(raw_destination, str) or not raw_destination.strip():
            return self.fail(
                "Missing required input: 'destination' (the new file path)."
            )

        source = Path(raw_source.strip()).expanduser()
        destination = Path(raw_destination.strip()).expanduser()

        if source.resolve() == destination.resolve():
            return self.fail(
                "Source and destination must be different paths - refusing "
                "to move a file onto itself."
            )

        if not source.exists():
            return self.fail(f"Source file does not exist: {source}")
        if source.is_dir():
            return self.fail(
                f"Source path is a directory, not a file: {source}. This "
                "tool only moves single files."
            )

        if destination.exists():
            return self.fail(
                f"Refusing to move to '{destination}': it already exists. "
                "This tool never overwrites an existing file."
            )

        parent = destination.parent
        if not parent.exists():
            return self.fail(
                f"Parent folder does not exist: {parent}. This tool does "
                "not create folders; please create the folder first."
            )
        if not parent.is_dir():
            return self.fail(f"Parent path is not a folder: {parent}")

        try:
            source.rename(destination)
        except FileExistsError:
            # A race: the destination appeared between the check and the
            # rename - never overwritten. On this project's target
            # platform (Windows), Path.rename() itself refuses to
            # replace an existing destination and raises this exact
            # exception, exactly like FileCopyTool's own "xb"-mode race
            # guard for the same narrow window.
            return self.fail(
                f"Refusing to move to '{destination}': it already exists."
            )
        except PermissionError:
            return self.fail(
                f"Permission denied while moving '{source}' to '{destination}'."
            )
        except OSError as exc:
            return self.fail(f"Could not move file: {exc}")

        size = destination.stat().st_size
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Moved '{source}' to '{destination}' ({size} bytes).",
            metadata={
                "source": str(source),
                "destination": str(destination),
                "size_bytes": str(size),
                "operation": "move",
            },
        )
