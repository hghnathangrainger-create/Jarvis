"""
file_list_tool.py

A safe, read-only tool that lists files and folders in a directory.

FileListTool is a GREEN tool: it only reads directory entries. It never opens
file contents, and never creates, deletes, moves, renames, writes, or modifies
anything. It does not recurse into subfolders.

Supported input (via input_data):
    path:  the directory to list (required).
    limit: the maximum number of entries to return (optional, default 50).
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


class FileListTool(BaseTool):
    """Lists the files and folders directly inside a directory.

    The listing is one level deep only: it does not descend into subfolders and
    it never reads file contents. Each entry is labelled as a file or a folder.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_list".
        """
        return "file_list"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Lists files and folders in a directory. Read-only and safe."

    def action_for(self, request: ToolRequest) -> str:
        """Return a read-only action string for security classification.

        Listing a directory is a read-only operation, so it is phrased as a
        "list" action that the Security Manager classifies GREEN.

        Args:
            request: The request being handled.

        Returns:
            A read-only action string.
        """
        return "list files in directory"

    def run(self, request: ToolRequest) -> ToolResult:
        """List the entries in the requested directory.

        Args:
            request: The request. Recognised input keys:
                path: the directory to list (required).
                limit: maximum number of entries to return (optional).

        Returns:
            A ToolResult containing the formatted listing, or a failed result
            if the path is missing, does not exist, or is not a directory.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail("Missing required input: 'path' (a directory to list).")

        limit = self._clamp_limit(request.input_data.get("limit", _DEFAULT_LIMIT))
        directory = Path(raw_path.strip()).expanduser()

        if not directory.exists():
            return self.fail(f"Path does not exist: {directory}")
        if not directory.is_dir():
            return self.fail(f"Path is not a directory: {directory}")

        try:
            entries = self._list_entries(directory, limit)
        except PermissionError:
            return self.fail(f"Permission denied when listing: {directory}")
        except OSError as exc:
            return self.fail(f"Could not list directory: {exc}")

        return self.ok(self._format(directory, entries))

    @staticmethod
    def _clamp_limit(value: object) -> int:
        """Coerce and clamp a limit input into a safe range.

        Args:
            value: The raw limit input, which may be of any type.

        Returns:
            An integer limit between 1 and the maximum allowed limit.
        """
        try:
            limit = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return _DEFAULT_LIMIT
        if limit < 1:
            return 1
        if limit > _MAX_LIMIT:
            return _MAX_LIMIT
        return limit

    @staticmethod
    def _list_entries(directory: Path, limit: int) -> list[tuple[str, str]]:
        """Return up to `limit` entries as (kind, name) pairs, sorted by name.

        The listing is a single level; subfolders are named but not entered,
        and no file is opened. Sorting is case-insensitive.

        Args:
            directory: The directory to list.
            limit: The maximum number of entries to return.

        Returns:
            A list of (kind, name) tuples where kind is "folder" or "file",
            sorted alphabetically by name and truncated to the limit.
        """
        collected: list[tuple[str, str]] = []
        with os.scandir(directory) as scanner:
            for entry in scanner:
                kind = "folder" if entry.is_dir() else "file"
                collected.append((kind, entry.name))

        collected.sort(key=lambda item: item[1].casefold())
        return collected[:limit]

    @staticmethod
    def _format(directory: Path, entries: list[tuple[str, str]]) -> str:
        """Format the directory listing into readable text.

        Args:
            directory: The directory that was listed.
            entries: The (kind, name) pairs to display.

        Returns:
            A formatted, multi-line string. Reports when the directory is empty.
        """
        if not entries:
            return f"{directory} is empty."

        lines = [f"Contents of {directory}:"]
        for kind, name in entries:
            marker = "[DIR] " if kind == "folder" else "      "
            lines.append(f"  {marker}{name}")
        return "\n".join(lines)