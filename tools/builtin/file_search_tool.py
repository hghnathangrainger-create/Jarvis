"""
file_search_tool.py

A safe, read-only tool that searches for files by name or by content
within a directory tree (Phase 24).

FileSearchTool is a GREEN tool: it only reads directory entries and file
contents to look for matches. It never creates, deletes, moves, renames,
writes, or modifies anything, never executes anything, and never calls
AI or the web. Noisy build/cache/version-control directories are
skipped so results stay useful. Content matches return a short context
snippet only - never a whole file's contents (that remains file_read's
own, separate job).

Supported input (via input_data):
    mode:  "name" (search filenames) or "content" (search file text)
           (required).
    query: the pattern/text to search for (required).
    path:  the directory to search from (optional, defaults to ".",
           mirroring FileListTool's own default).
    limit: the maximum number of matching files to return (optional,
           default 50).

Result metadata (Phase 29): every successful result also carries a
"match_count" metadata entry, and - only when there is exactly one
match - a "matched_path" entry holding that match's absolute path. This
exists so a workflow step can safely chain off of "exactly one file was
found" (via WorkflowEngine's existing, narrow previous-step propagation
mechanism - see workflow/engine.py's own _PROPAGATED_FIELDS) without ever
parsing this tool's own human-readable formatted output text. Standalone
use of this tool (outside a workflow) is completely unaffected - the
formatted text output is unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500

#: Safety cap on the total number of files inspected in one search, so a
#: pathological or unexpectedly large tree cannot make a single search
#: run for an unbounded amount of time. Never expected to be reached in
#: normal use; this is a defensive bound only.
_MAX_FILES_SCANNED = 20_000

#: Files larger than this are skipped for content search rather than
#: fully read - a search is not a substitute for file_read, and a
#: multi-hundred-megabyte file should never be loaded into memory just
#: to look for a substring.
_MAX_CONTENT_SCAN_BYTES = 2_000_000

#: Number of leading bytes inspected to decide whether a file is binary,
#: mirroring FileReadTool's own convention exactly.
_SNIFF_BYTES = 4096

#: Maximum length of the context snippet shown for a content match - a
#: short excerpt only, never the full matching line if it is unusually
#: long, and never the rest of the file.
_MAX_CONTEXT_CHARS = 200

#: Directory names skipped entirely during a search - noisy version-
#: control, cache, virtual-environment, and build directories that would
#: otherwise dominate results with no value. Comparison is by exact
#: directory name, case-sensitive, matching how these tools/directories
#: are conventionally named.
_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "dist",
        "build",
        ".tox",
    }
)


class FileSearchTool(BaseTool):
    """Searches for files by filename or by content within a directory tree.

    Two independent modes are supported: "name" (a case-insensitive
    substring match against each file's own name) and "content" (a
    case-insensitive substring match against each file's text, skipping
    binary and oversized files). Both modes recurse into subdirectories,
    skipping a fixed set of noisy directories (see _EXCLUDED_DIR_NAMES),
    and both are bounded by a result limit and a total-files-scanned
    safety cap so a search can never return an unbounded amount of
    output or run for an unbounded amount of time.
    """

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "file_search".
        """
        return "file_search"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Searches for files by name or by content within a directory "
            "tree. Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        This is always the same fixed phrase regardless of which mode or
        exact command phrasing was used - the action being performed
        (a read-only search) never changes, so the string the Security
        Manager classifies never varies with user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "search files", classified GREEN.
        """
        return "search files"

    def run(self, request: ToolRequest) -> ToolResult:
        """Search for files matching the requested name or content query.

        Args:
            request: The request. Recognised input keys:
                mode: "name" or "content" (required).
                query: the text to search for (required).
                path: the directory to search from (optional, default ".").
                limit: maximum number of matches to return (optional).

        Returns:
            A ToolResult containing the formatted matches (or an honest
            "no matches" message), or a failed result if the input is
            invalid or the path does not exist / is not a directory.
        """
        mode = request.input_data.get("mode")
        if mode not in ("name", "content"):
            return self.fail("Missing or invalid 'mode' (must be 'name' or 'content').")

        raw_query = request.input_data.get("query")
        if not isinstance(raw_query, str) or not raw_query.strip():
            return self.fail("Missing required input: 'query' (text to search for).")
        query = raw_query.strip()

        raw_path = request.input_data.get("path") or "."
        if not isinstance(raw_path, str) or not raw_path.strip():
            raw_path = "."
        root = Path(raw_path.strip()).expanduser()

        limit = self._clamp_limit(request.input_data.get("limit", _DEFAULT_LIMIT))

        if not root.exists():
            return self.fail(f"Path does not exist: {root}")
        if not root.is_dir():
            return self.fail(f"Path is not a directory: {root}")

        try:
            if mode == "name":
                matches = self._search_by_name(root, query, limit)
            else:
                matches = self._search_by_content(root, query, limit)
        except PermissionError:
            return self.fail(f"Permission denied while searching: {root}")
        except OSError as exc:
            return self.fail(f"Could not search directory: {exc}")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=self._format(root, mode, query, matches, limit),
            metadata=self._build_metadata(root, matches),
        )

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

    @classmethod
    def _walk(cls, root: Path):
        """Yield (dirpath, filenames) pairs, pruning excluded directories.

        A thin wrapper around os.walk that removes excluded directory
        names from the in-place dirnames list os.walk itself provides,
        so os.walk never descends into them at all - not merely
        filtering their results out afterward.

        Args:
            root: The directory to walk.

        Yields:
            (dirpath, filenames) pairs, exactly like os.walk, with
            excluded directories never descended into.
        """
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_NAMES]
            yield dirpath, filenames

    @classmethod
    def _search_by_name(cls, root: Path, query: str, limit: int) -> list[str]:
        """Find files whose own name contains the query, case-insensitively.

        Args:
            root: The directory to search from.
            query: The case-insensitive substring to match against each
                file's name.
            limit: The maximum number of matches to collect.

        Returns:
            A sorted list of paths (as strings, relative to root when
            possible), truncated to limit. Stops scanning early once
            the limit is reached.
        """
        lowered_query = query.casefold()
        matches: list[str] = []
        scanned = 0

        for dirpath, filenames in cls._walk(root):
            for filename in filenames:
                scanned += 1
                if scanned > _MAX_FILES_SCANNED:
                    return sorted(matches)[:limit]
                if lowered_query in filename.casefold():
                    matches.append(cls._relative_display(root, Path(dirpath) / filename))
                    if len(matches) >= limit:
                        return sorted(matches)[:limit]

        return sorted(matches)

    @classmethod
    def _search_by_content(cls, root: Path, query: str, limit: int) -> list[tuple[str, str]]:
        """Find files whose text contains the query, case-insensitively.

        Binary files (sniffed the same way FileReadTool does), files
        larger than _MAX_CONTENT_SCAN_BYTES, and any single file that
        raises while being read are all silently skipped - one
        unreadable file never aborts the rest of the search.

        Args:
            root: The directory to search from.
            query: The case-insensitive substring to match against each
                file's text content.
            limit: The maximum number of matching files to collect.

        Returns:
            A sorted (by path) list of (path, context_snippet) pairs,
            truncated to limit. Only the first match's short context is
            kept per file - never the full file content, and never
            every match within one file.
        """
        lowered_query = query.casefold()
        matches: list[tuple[str, str]] = []
        scanned = 0

        for dirpath, filenames in cls._walk(root):
            for filename in filenames:
                scanned += 1
                if scanned > _MAX_FILES_SCANNED:
                    matches.sort(key=lambda item: item[0])
                    return matches[:limit]

                file_path = Path(dirpath) / filename
                snippet = cls._find_content_match(file_path, lowered_query)
                if snippet is not None:
                    matches.append((cls._relative_display(root, file_path), snippet))
                    if len(matches) >= limit:
                        matches.sort(key=lambda item: item[0])
                        return matches[:limit]

        matches.sort(key=lambda item: item[0])
        return matches

    @classmethod
    def _find_content_match(cls, file_path: Path, lowered_query: str) -> str | None:
        """Return a short context snippet if file_path's text contains the
        query, or None if it does not match, is binary, too large, or
        unreadable for any reason.

        Every failure mode here (permission error, decode error, any
        other OSError) is treated identically to "no match" - a single
        problematic file is skipped, never allowed to raise out of the
        overall search.

        Args:
            file_path: The file to inspect.
            lowered_query: The already-casefolded query to search for.

        Returns:
            A short (at most _MAX_CONTEXT_CHARS) snippet of the first
            matching line, or None.
        """
        try:
            if file_path.is_symlink() or not file_path.is_file():
                return None
            if file_path.stat().st_size > _MAX_CONTENT_SCAN_BYTES:
                return None
            with file_path.open("rb") as handle:
                sniff = handle.read(_SNIFF_BYTES)
            if b"\x00" in sniff:
                return None  # looks binary

            with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if lowered_query in line.casefold():
                        stripped = line.strip()
                        if len(stripped) > _MAX_CONTEXT_CHARS:
                            stripped = stripped[:_MAX_CONTEXT_CHARS] + "..."
                        return stripped
        except (OSError, UnicodeError):
            return None
        return None

    @staticmethod
    def _relative_display(root: Path, path: Path) -> str:
        """Format a matched path for display, relative to the search root
        when possible.

        Args:
            root: The directory the search started from.
            path: The matched file's full path.

        Returns:
            The path relative to root as a string, or the path
            unchanged if it cannot be expressed relatively.
        """
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    @staticmethod
    def _build_metadata(
        root: Path, matches: list[str] | list[tuple[str, str]]
    ) -> dict[str, str]:
        """Build structured, trusted result metadata for safe propagation
        to a later workflow step (Phase 29).

        This is always derived directly from the same `matches` data
        `_format` renders into human-readable text - never by parsing
        that formatted text back out. "matched_path" is set only when
        there is exactly one match, so a later workflow step chaining
        off of it (via WorkflowEngine's existing input_from_previous_step
        propagation) can safely assume "exactly one file" without any
        disambiguation of its own; a search with zero or multiple
        matches has no "matched_path" entry at all, which is what makes
        WorkflowEngine's own existing "usable" check stop such a
        workflow honestly, with no special-case handling needed here or
        in the engine.

        The path is always resolved to an absolute path. The human-
        facing display path elsewhere in this tool (_relative_display)
        is relative to `root`, which may itself be relative to the
        current working directory - a later tool step must be able to
        use this path correctly regardless of its own working directory.

        Args:
            root: The directory that was searched.
            matches: The matches found, shaped per mode - a list of path
                strings for "name" mode, or a list of (path, snippet)
                tuples for "content" mode.

        Returns:
            A dict with "match_count" always set, and "matched_path" set
            only when there is exactly one match.
        """
        metadata = {"match_count": str(len(matches))}
        if len(matches) == 1:
            first = matches[0]
            display_path = first if isinstance(first, str) else first[0]
            metadata["matched_path"] = str((root / display_path).resolve())
        return metadata

    @staticmethod
    def _format(
        root: Path,
        mode: str,
        query: str,
        matches: list[str] | list[tuple[str, str]],
        limit: int,
    ) -> str:
        """Format search matches into readable text.

        Args:
            root: The directory that was searched.
            mode: "name" or "content".
            query: The query that was searched for.
            matches: The matches found, shaped per mode.
            limit: The result limit that was applied.

        Returns:
            A formatted, multi-line string. Reports honestly when there
            are no matches, and notes when the result limit may have
            cut off further matches.
        """
        label = "name" if mode == "name" else "content"
        header = f"File search ({label}) for '{query}' in {root}:"

        if not matches:
            return f"{header}\n  No matching files found."

        lines = [header]
        if mode == "name":
            for path in matches:
                lines.append(f"  {path}")
        else:
            for path, snippet in matches:
                lines.append(f"  {path}: {snippet}")

        if len(matches) >= limit:
            lines.append(
                f"\n[showing up to {limit} results; more may exist]"
            )

        return "\n".join(lines)
