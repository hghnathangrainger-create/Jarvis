"""
brain_read_tool.py

The GREEN (read-only) brain tool: status, search, and read over Nathan's
external Markdown "3D brain".

BrainReadTool is a GREEN tool: it only ever reports configuration, walks
directory entries, and reads note bytes through BrainService's own bounds.
It never creates, modifies, moves, renames, or deletes anything, never
calls AI or the network, and works exactly the same with AI reasoning
disabled (or with no API key configured) - brain commands never route
through AIRouter/ai/ at all.

Supported input (via input_data):
    op:    "status" | "search" | "read" (required).
    query: the search text (required for op="search").
    path:  the relative path or exact note title (required for op="read").

Security classification (see action_for): three fixed, input-independent
action strings - "show brain status", "search brain notes", and "read
brain note" - each GREEN. User content (a query or a path) never reaches
the classified action string, so it can never influence the tier.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.brain_service import BrainError, BrainService

#: Marker lines bracketing a read note, so an excerpt's boundaries are
#: never ambiguous in terminal scrollback.
_BEGIN_NOTE = "----- begin note -----"
_END_NOTE = "----- end note -----"


class BrainReadTool(BaseTool):
    """Read-only access to the configured Markdown brain (GREEN).

    Attributes:
        _service: The BrainService built from Settings in main.py; the
            single shared instance also used by BrainWriteTool and the
            optional AI-context builder.
    """

    def __init__(self, service: BrainService) -> None:
        """Initialise the tool with its shared service.

        Args:
            service: The configured BrainService instance.
        """
        self._service = service

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "brain_read".
        """
        return "brain_read"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Shows brain status, searches the configured Markdown brain, or "
            "reads one brain note. Read-only and safe."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, GREEN action string for security classification.

        The classified string depends only on which of the three fixed
        sub-commands was routed - never on the user's query, path, or any
        note content - so classification can never vary with user input.

        Args:
            request: The request being handled.

        Returns:
            "show brain status", "search brain notes", or "read brain
            note" - each classified GREEN by SecurityManager's explicit
            brain rules.
        """
        op = request.input_data.get("op")
        if op == "search":
            return "search brain notes"
        if op == "read":
            return "read brain note"
        return "show brain status"

    def run(self, request: ToolRequest) -> ToolResult:
        """Run the requested read-only brain operation.

        Args:
            request: The request. Recognised input keys: op (required),
                query (for op="search"), path (for op="read").

        Returns:
            A successful ToolResult with the formatted output, or a
            failed result with an honest message (disabled, unconfigured,
            missing input, no match, ambiguous title, unreadable note).
            Expected BrainError failures are reported, never raised.
        """
        op = request.input_data.get("op")
        try:
            if op == "status":
                return self.ok(self._format_status())
            if op == "search":
                return self._run_search(request)
            if op == "read":
                return self._run_read(request)
        except BrainError as exc:
            return self.fail(str(exc))
        except OSError as exc:
            return self.fail(f"Brain operation failed: {exc}")

        return self.fail(
            "Missing or invalid 'op' (must be 'status', 'search', or "
            "'read')."
        )

    # ----- operations ------------------------------------------------------

    def _run_search(self, request: ToolRequest) -> ToolResult:
        """Run a deterministic, case-insensitive brain search.

        Args:
            request: The request carrying "query".

        Returns:
            A successful ToolResult listing bounded snippets with
            relative source paths, or a failed result for an empty
            query / disabled brain.
        """
        raw_query = request.input_data.get("query")
        if not isinstance(raw_query, str) or not raw_query.strip():
            return self.fail("Missing required input: 'query'.")

        result = self._service.search(raw_query)
        lines = [
            f"Brain search for '{result.query}' "
            f"(limit {result.limit}):"
        ]
        if not result.matches:
            lines.append("  No matching notes found.")
        for match in result.matches:
            if match.snippet:
                lines.append(f"  {match.rel_path}: {match.snippet}")
            else:
                lines.append(f"  {match.rel_path}")
        if result.truncated:
            lines.append(
                f"\n[showing up to {result.limit} results; more may exist]"
            )
        return ToolResult(
            tool_name=self.name,
            success=True,
            output="\n".join(lines),
            metadata={"match_count": str(len(result.matches))},
        )

    def _run_read(self, request: ToolRequest) -> ToolResult:
        """Read one bounded note by relative path or exact title.

        Args:
            request: The request carrying "path".

        Returns:
            A successful ToolResult bracketing the note text with its
            relative source path (and an honest truncation notice), or a
            failed result when the note cannot be resolved/read.
        """
        raw_path = request.input_data.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return self.fail(
                "Missing required input: 'path' (a relative brain path or "
                "a note title)."
            )

        result = self._service.read(raw_path)
        lines = [
            f"Brain note: {result.rel_path}",
            _BEGIN_NOTE,
            result.content.rstrip("\n"),
            _END_NOTE,
        ]
        if result.truncated:
            lines.append(
                "[note truncated: only its first "
                f"{self._service.max_file_bytes} bytes are shown "
                "(BRAIN_MAX_FILE_BYTES)]"
            )
        return ToolResult(
            tool_name=self.name,
            success=True,
            output="\n".join(lines),
            metadata={"rel_path": result.rel_path},
        )

    # ----- status ----------------------------------------------------------

    def _format_status(self) -> str:
        """Format honest configuration status for the CLI.

        Returns:
            A multi-line status report. Never prints any .env value other
            than the brain path itself, and never lists note contents.
        """
        status = self._service.status()
        lines: list[str] = []

        if not status.enabled:
            lines.append(
                "Brain integration: disabled (BRAIN_ENABLED is false)."
            )
            lines.append(
                "Set BRAIN_ENABLED=true and BRAIN_PATH=<brain folder> in "
                ".env to use brain commands."
            )
        elif not status.configured:
            lines.append(
                "Brain integration: enabled, but not configured "
                "(BRAIN_PATH is not set)."
            )
            lines.append(
                "Set BRAIN_PATH=<brain folder> in .env to use brain "
                "commands."
            )
        else:
            lines.append("Brain integration: enabled and configured.")

        if status.root is not None:
            lines.append(f"Brain root: {status.root}")
            lines.append(
                f"Brain root exists: {'yes' if status.root_exists else 'no'}"
            )
            if not status.folders:
                lines.append("Allowed folders: (none configured)")
            for folder in status.folders:
                if not folder.exists:
                    state = "missing"
                elif not folder.in_scope:
                    state = "exists but outside the root (never scanned)"
                else:
                    state = "exists"
                lines.append(f"Allowed folder '{folder.name}': {state}")
        else:
            lines.append("Brain root: not configured (BRAIN_PATH is empty).")

        lines.append(
            "Scope: only .md notes inside the allowed folders are ever "
            "read; hidden folders, .git, apps/ (the visualizer), and "
            "node_modules are always excluded. Jarvis never deletes a note."
        )
        return "\n".join(lines)
