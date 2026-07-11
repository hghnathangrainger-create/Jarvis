"""
file_copy_tool.py

A guarded write tool that copies an existing file to a new destination
path (Phase 25).

FileCopyTool is a YELLOW tool: creating a new file changes state, so its
action is classified YELLOW and it runs only after explicit approval
through the normal Tool Executor and Approval Manager path, exactly like
FileCreateTool/FileAppendTool. It is deliberately conservative:

    - It copies one existing file to one new destination path only. It
      never overwrites an existing destination - not even with approval;
      approval only ever authorises the copy attempt, never a decision
      to overwrite something already there.
    - It does NOT create parent folders, mirroring FileCreateTool's own
      choice exactly: if the destination's parent directory does not
      already exist, the tool fails cleanly.
    - It never reads the source file's content as text, and never
      interprets it in any way - bytes are copied exactly as they are,
      in bounded chunks, so binary files are copied safely and
      correctly, exactly like any other file.
    - It never moves, renames, deletes, edits in place, or executes
      anything - the source file is left completely untouched.

Supported input (via input_data):
    source:      the existing file to copy from (required, must exist,
                 must be a file).
    destination: the new file to copy to (required, must not already
                 exist).

Safety note:
    This tool does not enforce approval itself. Approval is enforced by
    the Tool Executor, which classifies this tool's action ("copy file")
    as YELLOW and withholds it until an approved decision is supplied.
    This tool simply performs the copy when it is finally allowed to
    run - and even then, still refuses if the destination exists.
"""

from __future__ import annotations

from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: Read/write in bounded chunks rather than loading an entire file into
#: memory at once, mirroring this project's established discipline of
#: never loading unbounded content (see FileReadTool's own max_chars
#: bound, FileSearchTool's own content-scan size cap).
_CHUNK_SIZE = 1_048_576  # 1 MiB

#: The largest source file this tool will copy in one call. A generous
#: but real bound, so an accidental attempt to copy an unexpectedly huge
#: file fails cleanly and quickly rather than silently consuming a long
#: time and a large amount of disk I/O.
_MAX_COPY_BYTES = 100_000_000  # 100 MB


class FileCopyTool(BaseTool):
    """Copies one existing file to a new destination path.

    Sensitive (YELLOW); never overwrites an existing destination, never
    reads the source as text, and never touches the source file itself
    in any way.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_copy".
        """
        return "file_copy"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Copies an existing file to a new destination path. Sensitive: "
            "requires approval. Never overwrites an existing destination."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed action string for security classification.

        This is always the same fixed phrase regardless of the actual
        source/destination paths - copying a file changes state
        (a new file is created) in exactly the same way every time, so
        the string the Security Manager classifies never varies with
        user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "copy file", classified YELLOW.
        """
        return "copy file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Copy the requested source file to the requested destination.

        Args:
            request: The request. Recognised input keys:
                source: the existing file to copy from (required).
                destination: the new file to copy to (required).

        Returns:
            A successful ToolResult when the copy completes, or a failed
            result if either path is missing, the source does not exist
            or is not a file, the source and destination are the same
            path, the destination already exists, the destination's
            parent folder does not exist, the source is too large, or a
            permission/OS error occurs.
        """
        raw_source = request.input_data.get("source")
        if not isinstance(raw_source, str) or not raw_source.strip():
            return self.fail(
                "Missing required input: 'source' (the existing file to copy)."
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
                "to copy a file onto itself."
            )

        if not source.exists():
            return self.fail(f"Source file does not exist: {source}")
        if source.is_dir():
            return self.fail(
                f"Source path is a directory, not a file: {source}. This "
                "tool only copies single files."
            )

        if destination.exists():
            return self.fail(
                f"Refusing to copy to '{destination}': it already exists. "
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
            size = source.stat().st_size
        except OSError as exc:
            return self.fail(f"Could not read source file: {exc}")

        if size > _MAX_COPY_BYTES:
            return self.fail(
                f"Refusing to copy '{source}': it is {size} bytes, over the "
                f"{_MAX_COPY_BYTES}-byte limit."
            )

        try:
            self._copy_bytes(source, destination)
        except FileExistsError:
            # A race: the destination appeared between the check and the
            # copy - never overwritten, exactly like FileCreateTool's own
            # equivalent race guard.
            return self.fail(
                f"Refusing to copy to '{destination}': it already exists."
            )
        except PermissionError:
            return self.fail(
                f"Permission denied while copying '{source}' to '{destination}'."
            )
        except OSError as exc:
            return self.fail(f"Could not copy file: {exc}")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=f"Copied '{source}' to '{destination}' ({size} bytes).",
            metadata={
                "source": str(source),
                "destination": str(destination),
                "bytes_copied": str(size),
                "operation": "copy",
            },
        )

    @staticmethod
    def _copy_bytes(source: Path, destination: Path) -> None:
        """Copy source's bytes to destination in bounded chunks.

        Never reads or interprets the content as text - this is a pure
        byte-for-byte copy, so binary files are copied correctly with no
        special handling required. Opens the destination in exclusive-
        create binary mode ("xb"), so a destination that appears between
        the caller's own existence check and this call raises
        FileExistsError rather than silently overwriting anything.

        Args:
            source: The existing file to read from.
            destination: The new file to write to; must not already exist.
        """
        with source.open("rb") as src, destination.open("xb") as dst:
            while True:
                chunk = src.read(_CHUNK_SIZE)
                if not chunk:
                    break
                dst.write(chunk)
