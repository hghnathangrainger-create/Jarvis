"""
file_append_tool.py

A guarded write tool that APPENDS text to an existing text file
(Phase 4, Batch 2).

FileAppendTool is a YELLOW tool: appending to a file changes state, so its
action is classified YELLOW and it runs only after explicit approval through
the normal Tool Executor and Approval Manager path. It is deliberately
conservative:

    - It appends to an existing file only. It never creates a new file (use
      the file_create tool for that), and it never overwrites existing content.
    - It refuses folders and likely-binary files.
    - It only appends text. It never deletes, moves, renames, edits earlier
      content, installs, or runs commands.

Supported input (via input_data):
    path:    the existing file to append to (required, must already exist).
    content: the text to append (required, must be non-empty).

Safety note:
    This tool does not enforce approval itself. Approval is enforced by the
    Tool Executor, which classifies this tool's action ("append text file") as
    YELLOW and withholds it until an approved decision is supplied.
"""

from __future__ import annotations

from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

#: The largest amount of text this tool will append in one call.
_MAX_CONTENT_CHARS = 100_000

#: Number of leading bytes inspected to decide whether a file is binary.
_SNIFF_BYTES = 4096


class FileAppendTool(BaseTool):
    """Appends text to an existing text file. Sensitive (YELLOW)."""

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_append".
        """
        return "file_append"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Appends text to an existing text file. Sensitive: requires "
            "approval. Never creates a new file and never overwrites."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        Appending to a file changes state, so it is phrased as an "append text
        file" action, which the Security Manager classifies YELLOW. This is what
        makes the action require approval before it can run.

        Args:
            request: The request being handled.

        Returns:
            The action string "append text file".
        """
        return "append text file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Append the requested text to an existing text file.

        Args:
            request: The request. Recognised input keys:
                path: the existing file to append to (required).
                content: the text to append (required, non-empty).

        Returns:
            A successful ToolResult when the text is appended, or a failed
            result if the path is missing, the file does not exist, the target
            is a directory, the file appears binary, or the content is missing,
            empty, or too large.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail(
                "Missing required input: 'path' (an existing file to append to)."
            )

        content = request.input_data.get("content")
        if not isinstance(content, str) or content == "":
            return self.fail(
                "Missing required input: 'content' (non-empty text to append)."
            )
        if len(content) > _MAX_CONTENT_CHARS:
            return self.fail(
                f"Refusing to append {len(content)} characters; the limit is "
                f"{_MAX_CONTENT_CHARS}."
            )

        file_path = Path(raw_path.strip()).expanduser()

        if not file_path.exists():
            return self.fail(
                f"File does not exist: {file_path}. This tool only appends to "
                "an existing file; use the file_create tool to make a new one."
            )
        if file_path.is_dir():
            return self.fail(f"Path is a directory, not a file: {file_path}")

        try:
            if self._looks_binary(file_path):
                return self.fail(
                    f"Refusing to append to '{file_path}': it appears to be a "
                    "binary file, not text."
                )
            with file_path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        except PermissionError:
            return self.fail(f"Permission denied when appending to: {file_path}")
        except OSError as exc:
            return self.fail(f"Could not append to file: {exc}")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Appended to file: {file_path} "
                f"({len(content)} characters added)."
            ),
            metadata={
                "path": str(file_path),
                "chars_appended": str(len(content)),
                "operation": "append",
            },
        )

    @staticmethod
    def _looks_binary(file_path: Path) -> bool:
        """Report whether a file appears to be binary rather than text.

        The check reads only the first block of bytes. A file is treated as
        binary if that block contains a NUL byte, which is a strong and simple
        signal of non-text content.

        Args:
            file_path: The file to inspect.

        Returns:
            True if the file appears to be binary, False otherwise.
        """
        with file_path.open("rb") as handle:
            chunk = handle.read(_SNIFF_BYTES)
        return b"\x00" in chunk