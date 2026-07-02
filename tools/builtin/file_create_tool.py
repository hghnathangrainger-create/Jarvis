"""
file_create_tool.py

A guarded write tool that creates a NEW text file (Phase 4, Batch 2).

FileCreateTool is a YELLOW tool: creating a file changes state, so its action
is classified YELLOW and it runs only after explicit approval through the normal
Tool Executor and Approval Manager path. It is deliberately conservative:

    - It creates a new file only. It never overwrites an existing file.
    - It does NOT create parent folders. If the parent directory does not
      already exist, the tool fails cleanly rather than building a directory
      tree the user did not ask for.
    - It only writes text content. It never deletes, moves, renames, edits in
      place, installs, or runs commands.

Supported input (via input_data):
    path:    the new file to create (required, must not already exist).
    content: the text to write into the new file (optional, defaults to "").

Safety note:
    This tool does not enforce approval itself. Approval is enforced by the
    Tool Executor, which classifies this tool's action ("create text file") as
    YELLOW and withholds it until an approved decision is supplied. This tool
    simply performs the create when it is finally allowed to run.
"""

from __future__ import annotations

from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: The largest amount of text this tool will write in one call.
_MAX_CONTENT_CHARS = 100_000


class FileCreateTool(BaseTool):
    """Creates a new text file. Sensitive (YELLOW); never overwrites."""

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_create".
        """
        return "file_create"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Creates a new text file with the given content. Sensitive: "
            "requires approval. Never overwrites an existing file."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Creating a file changes state, so it is phrased as a "create text file"
        action, which the Security Manager classifies YELLOW. This is what makes
        the action require approval before it can run.

        Args:
            request: The request being handled.

        Returns:
            The action string "create text file".
        """
        return "create text file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Create the requested new text file.

        Args:
            request: The request. Recognised input keys:
                path: the new file to create (required, must not exist).
                content: the text to write (optional, defaults to "").

        Returns:
            A successful ToolResult when the file is created, or a failed
            result if the path is missing, the file already exists, the parent
            folder does not exist, the target is a directory, or the content is
            too large.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail(
                "Missing required input: 'path' (the new file to create)."
            )

        content = request.input_data.get("content", "")
        if not isinstance(content, str):
            return self.fail("Input 'content' must be text.")
        if len(content) > _MAX_CONTENT_CHARS:
            return self.fail(
                f"Refusing to write {len(content)} characters; the limit is "
                f"{_MAX_CONTENT_CHARS}."
            )

        file_path = Path(raw_path.strip()).expanduser()

        if file_path.exists():
            return self.fail(
                f"Refusing to create '{file_path}': it already exists. This "
                "tool never overwrites an existing file."
            )

        parent = file_path.parent
        if not parent.exists():
            return self.fail(
                f"Parent folder does not exist: {parent}. This tool does not "
                "create folders; please create the folder first."
            )
        if not parent.is_dir():
            return self.fail(f"Parent path is not a folder: {parent}")

        try:
            with file_path.open("x", encoding="utf-8") as handle:
                handle.write(content)
        except FileExistsError:
            # A race: the file appeared between the check and the create.
            return self.fail(
                f"Refusing to create '{file_path}': it already exists."
            )
        except PermissionError:
            return self.fail(f"Permission denied when creating: {file_path}")
        except OSError as exc:
            return self.fail(f"Could not create file: {exc}")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Created new file: {file_path} "
                f"({len(content)} characters written)."
            ),
            metadata={
                "path": str(file_path),
                "chars_written": str(len(content)),
                "operation": "create",
            },
        )