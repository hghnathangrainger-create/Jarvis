"""
file_read_tool.py

A safe, read-only tool that reads the contents of a single text file.

FileReadTool is a GREEN tool: it only reads file contents, and only up to a
bounded number of characters. It never creates, deletes, moves, renames,
writes, or modifies anything. It refuses likely-binary files and never loads
more than the requested amount into memory.

Supported input (via input_data):
    path:      the file to read (required).
    max_chars: the maximum number of characters to return (optional,
               default 4000).
"""

from __future__ import annotations

from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_MAX_CHARS = 4000
_MAX_ALLOWED_CHARS = 100_000

# Number of leading bytes inspected to decide whether a file is binary.
_SNIFF_BYTES = 4096


class FileReadTool(BaseTool):
    """Reads the text contents of a single file, up to a character limit.

    The tool reads at most the requested number of characters, so a very large
    file is never fully loaded. Files that appear to be binary are refused
    rather than returned as unreadable text.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_read".
        """
        return "file_read"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Reads the contents of a text file. Read-only and safe."

    def action_for(self, request: ToolRequest) -> str:
        """Return a read-only action string for security classification.

        Reading a file is a read-only operation, so it is phrased as a "read
        file" action that the Security Manager classifies GREEN.

        Args:
            request: The request being handled.

        Returns:
            A read-only action string.
        """
        return "read file"

    def run(self, request: ToolRequest) -> ToolResult:
        """Read the requested file's contents up to the character limit.

        Args:
            request: The request. Recognised input keys:
                path: the file to read (required).
                max_chars: maximum number of characters to return (optional).

        Returns:
            A ToolResult containing the file contents (marked as truncated when
            the limit was reached), or a failed result if the path is missing,
            does not exist, is a directory, or appears to be a binary file.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail("Missing required input: 'path' (a file to read).")

        max_chars = self._clamp_max_chars(
            request.input_data.get("max_chars", _DEFAULT_MAX_CHARS)
        )
        file_path = Path(raw_path.strip()).expanduser()

        if not file_path.exists():
            return self.fail(f"Path does not exist: {file_path}")
        if file_path.is_dir():
            return self.fail(
                f"Path is a directory, not a file: {file_path}. "
                "Use the file_list tool to see what is inside it."
            )

        try:
            if self._looks_binary(file_path):
                return self.fail(
                    f"Refusing to read '{file_path}': it appears to be a binary "
                    "file, not text."
                )
            text, truncated = self._read_text(file_path, max_chars)
        except PermissionError:
            return self.fail(f"Permission denied when reading: {file_path}")
        except OSError as exc:
            return self.fail(f"Could not read file: {exc}")

        return self.ok(self._format(file_path, text, truncated, max_chars))

    @staticmethod
    def _clamp_max_chars(value: object) -> int:
        """Coerce and clamp a max_chars input into a safe range.

        Args:
            value: The raw max_chars input, which may be of any type.

        Returns:
            An integer between 1 and the maximum allowed character count.
        """
        try:
            max_chars = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return _DEFAULT_MAX_CHARS
        if max_chars < 1:
            return 1
        if max_chars > _MAX_ALLOWED_CHARS:
            return _MAX_ALLOWED_CHARS
        return max_chars

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

    @staticmethod
    def _read_text(file_path: Path, max_chars: int) -> tuple[str, bool]:
        """Read up to max_chars characters of text from a file.

        Only max_chars + 1 characters are read: the extra character is used to
        detect whether the file continues beyond the limit, without loading the
        rest of a large file.

        Args:
            file_path: The file to read.
            max_chars: The maximum number of characters to return.

        Returns:
            A tuple of (text, truncated), where text is at most max_chars
            characters and truncated indicates the file had more content.
        """
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            data = handle.read(max_chars + 1)

        if len(data) > max_chars:
            return data[:max_chars], True
        return data, False

    @staticmethod
    def _format(
        file_path: Path, text: str, truncated: bool, max_chars: int
    ) -> str:
        """Format the file contents into a readable result.

        Args:
            file_path: The file that was read.
            text: The text content read from the file.
            truncated: Whether the content was cut off at the limit.
            max_chars: The character limit that was applied.

        Returns:
            A formatted string with a header, the contents, and a clear
            truncation notice when applicable.
        """
        header = f"Contents of {file_path}:"
        if truncated:
            notice = (
                f"\n\n[... truncated: showing the first {max_chars} characters. "
                "Increase max_chars to read more.]"
            )
            return f"{header}\n{text}{notice}"
        return f"{header}\n{text}"