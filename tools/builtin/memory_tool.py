"""
memory_tool.py

A safe tool that saves, lists, and searches stored memories.

MemoryTool is a GREEN tool. It reads from the Memory Engine (list, search) and
performs one explicit, user-requested write: saving a memory the user directly
asked Jarvis to remember. It cannot update, delete, or forget memories - those
are separate, approval-gated tools. It delegates entirely to the existing
MemoryManager, adding no storage logic of its own, and it honours the
"do not remember" rule enforced by the manager.

Supported operations (via the 'operation' input):
    - "list":       return the most recent memories, optionally filtered by
                    category. Discloses an honest, exact truncation notice
                    (Phase 75, Batch 1) when more memories exist than are
                    shown, using MemoryManager.count()/count_by_category() -
                    both already-existing methods, never a new query.
    - "search":     return memories matching the 'query' input, optionally
                    filtered by category. Discloses an honest, exact
                    truncation notice (Phase 75, Batch 2) when more matches
                    exist than are shown, using MemoryManager.count_matching()
                    - a new, narrow COUNT query mirroring search()'s own
                    filter semantics exactly.
    - "save":       store the 'content' text the user explicitly asked to
                    remember, under an optional 'category' (defaulting to
                    "general").
    - "categories": return a real, honest count per known category (Phase
                    71, Batch 1) - every category in
                    memory.memory_models.KNOWN_CATEGORIES, including an
                    honest zero for one with no memories, always in that
                    fixed, declared order - never sorted by count, so
                    nothing here implies one category is more important
                    than another.

Why "save" is GREEN:
    A manual save happens only when the user explicitly says "remember this".
    Nothing is overwritten or removed, the user sees exactly what will be
    stored, and the "do not remember" rule still applies. The Security Manager
    classifies "save memory" as GREEN for this reason. The AI never triggers a
    save; only an explicit user command does.
"""

from __future__ import annotations

from memory.memory_manager import MemoryManager
from memory.episodic_memory import MemoryRecord
from memory.memory_models import KNOWN_CATEGORIES
from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


class MemoryTool(BaseTool):
    """Lists or searches stored memories using the Memory Engine.

    Attributes:
        _memory: The Memory Manager used for read-only memory access.
    """

    def __init__(self, memory_manager: MemoryManager) -> None:
        """Initialise the tool with a Memory Manager.

        Args:
            memory_manager: The Memory Manager providing read access.
        """
        self._memory = memory_manager

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "memory".
        """
        return "memory"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Lists or searches stored memories. Read-only and safe."

    def action_for(self, request: ToolRequest) -> str:
        """Return an honest action string for security classification.

        The action names what the operation actually does: "save memory" for a
        save, "search memories" for a search, and "list memories" for a list.
        The Security Manager classifies all of these as GREEN - a manual save
        is a single, explicit, user-requested store, not a broad state
        change, and "show memory categories" (Phase 71, Batch 1) is a plain
        read, classified GREEN via the same existing, unchanged generic
        "show" rule "show system health"/"show configuration" already use -
        no new Security Manager rule was needed or added for it.

        Args:
            request: The request being handled.

        Returns:
            An action string describing the operation.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()
        if operation == "save":
            return "save memory"
        if operation == "search":
            return "search memories"
        if operation == "get":
            return "show memory"
        if operation == "categories":
            return "show memory categories"
        return "list memories"

    def run(self, request: ToolRequest) -> ToolResult:
        """Save, list, search, or summarise-by-category memories according
        to the requested operation.

        Args:
            request: The request. Recognised input keys:
                operation: "list" (default), "search", "save", "get", or
                    "categories".
                query: the search text, required when operation is "search".
                content: the text to store, required when operation is "save".
                category: optional category for save/list/search filtering.
                limit: optional maximum number of results.

        Returns:
            A ToolResult containing the formatted memories or a save
            confirmation, or a failed result if the operation is unknown or its
            required input is missing.
        """
        operation = str(request.input_data.get("operation", "list")).strip().lower()
        limit = self._clamp_limit(request.input_data.get("limit", _DEFAULT_LIMIT))
        category = request.input_data.get("category")
        category = category if isinstance(category, str) and category.strip() else None

        if operation == "save":
            return self._run_save(request, category)

        if operation == "get":
            memory_id = self._parse_id(request.input_data.get("memory_id"))
            if memory_id is None:
                return self.fail(
                    "Showing a memory requires a valid numeric 'memory_id'."
                )
            record = self._memory.get(memory_id)
            if record is None:
                return self.fail(f"No memory found with id {memory_id}.")
            return self.ok(self._format_row(record))

        if operation == "categories":
            return self.ok(self._format_categories())

        if operation == "list":
            records = self._list_recent(limit=limit, category=category)
            header = "Recent memories"
            if category:
                header = f"Recent memories in '{category.strip().lower()}'"
            return self.ok(self._format_list(records, header, category))

        if operation == "search":
            query = request.input_data.get("query")
            if not isinstance(query, str) or not query.strip():
                return self.fail("Search requires a non-empty 'query' string.")
            records = self._search(query, limit=limit, category=category)
            header = f"Memories matching '{query.strip()}'"
            if category:
                header = (
                    f"Memories in '{category.strip().lower()}' "
                    f"matching '{query.strip()}'"
                )
            return self.ok(self._format_search(records, header, query, category))

        return self.fail(
            f"Unknown operation '{operation}'. Use 'list', 'search', 'save', "
            "'get', or 'categories'."
        )

    def _run_save(
        self, request: ToolRequest, category: str | None
    ) -> ToolResult:
        """Handle the explicit, user-requested save operation.

        The content is stored through the Memory Manager, which enforces the
        "do not remember" rule. When the manager declines to store (empty text
        or a "do not remember" signal), a clear, non-failing message is
        returned so the user knows nothing was saved.

        Args:
            request: The request carrying the 'content' to store.
            category: The optional category to store under.

        Returns:
            A ToolResult confirming the save, reporting that nothing was stored,
            or failing when no content was provided.
        """
        content = request.input_data.get("content")
        if not isinstance(content, str) or not content.strip():
            return self.fail("Saving a memory requires non-empty 'content'.")

        record = self._memory.save(content=content, category=category)
        if record is None:
            # The Memory Manager declined (empty or "do not remember").
            return self.ok("Understood - I did not save that to memory.")

        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Saved to memory under '{record.category}': {record.content}"
            ),
            metadata={
                "operation": "save",
                "memory_id": str(record.id),
                "category": record.category,
            },
        )

    @staticmethod
    def _parse_id(raw: object) -> int | None:
        """Parse a memory id from raw input.

        Args:
            raw: The raw id value, an int or numeric string.

        Returns:
            The id as an int, or None if it cannot be parsed.
        """
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.strip().isdigit():
            return int(raw.strip())
        return None

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

    def _list_recent(self, *, limit: int = 10, category: str | None = None):
        try:
            return self._memory.list_recent(limit=limit, category=category)
        except TypeError as exc:
            if "category" not in str(exc) and "unexpected keyword" not in str(exc):
                raise
            try:
                return self._memory.list_recent(limit=limit)
            except TypeError:
                return self._memory.list_recent()

    def _search(self, query: str, *, limit: int = 10, category: str | None = None):
        try:
            return self._memory.search(query=query, limit=limit, category=category)
        except TypeError as exc:
            if "category" not in str(exc) and "unexpected keyword" not in str(exc):
                raise
            try:
                return self._memory.search(query=query, limit=limit)
            except TypeError:
                try:
                    return self._memory.search(query=query)
                except TypeError:
                    return self._memory.search(query)

    @staticmethod
    def _format(records: list[MemoryRecord], header: str) -> str:
        """Format a list of memory records into readable text.

        Args:
            records: The memory records to format.
            header: A header line describing the result set.

        Returns:
            A formatted, multi-line string. Reports when there are no results.
        """
        if not records:
            return f"{header}: none found."
        lines = [f"{header}:"]
        for record in records:
            lines.append(f"  {MemoryTool._format_row(record)}")
        return "\n".join(lines)

    def _format_list(
        self, records: list[MemoryRecord], header: str, category: str | None
    ) -> str:
        """Format the "list" operation's output, including an honest
        truncation notice when more memories exist than are shown
        (Phase 75, Batch 1).

        Reuses the existing, shared _format() for the header and rows
        completely unchanged - this method only appends a trailing
        notice, and only for the "list" operation. "search" (which
        also calls _format() directly, on its own separate code path)
        is entirely unaffected by this method.

        The real total comes from one call to MemoryManager.count()
        (no category filter) or MemoryManager.count_by_category()
        (category-filtered) - both already-existing methods (the
        latter already used by this class's own "categories" operation
        since Phase 71) - never a new query, never estimated, never
        AI-derived. The notice deliberately never says "increase
        'limit'" or similar, since no user-facing CLI syntax exists to
        do that today - it states the honest fact only.

        Args:
            records: The already-fetched memory records this listing
                is about to render.
            header: The plain header text (already built by the
                caller) - unchanged from before this batch.
            category: The category filter that was applied, if any -
                used only to pick the matching real total and to name
                the category in the notice text.

        Returns:
            The same formatted text _format() would already produce,
            with an honest "[showing N of M memories...; more memories
            exist]" notice appended only when the real total is
            greater than the number of records actually shown. The
            empty-result case ("{header}: none found.") is returned
            completely unchanged - an empty result always means the
            real total is honestly zero too, so no notice is needed to
            say so.
        """
        formatted = self._format(records, header)
        if not records:
            return formatted

        shown = len(records)
        if category:
            total = self._memory.count_by_category(category)
            scope = f" in category '{category.strip().lower()}'"
        else:
            total = self._memory.count()
            scope = ""

        if total > shown:
            formatted += (
                f"\n\n[showing {shown} of {total} memories{scope}; "
                "more memories exist]"
            )
        return formatted

    def _format_search(
        self,
        records: list[MemoryRecord],
        header: str,
        query: str,
        category: str | None,
    ) -> str:
        """Format the "search" operation's output, including an honest
        truncation notice when more matches exist than are shown
        (Phase 75, Batch 2).

        Reuses the existing, shared _format() for the header and rows
        completely unchanged - this method only appends a trailing
        notice. "list" (which uses its own separate _format_list()
        method) is entirely unaffected by this method, and vice versa.

        The real total comes from one call to
        MemoryManager.count_matching() (Phase 75, Batch 2) - a true,
        exact COUNT query mirroring search()'s own filter semantics,
        never a fetch-and-count in Python, never estimated, never
        AI-derived. The notice deliberately never says "increase
        'limit'" or similar, since no user-facing CLI syntax exists to
        do that today - it states the honest fact only.

        Args:
            records: The already-fetched matching records this search
                is about to render.
            header: The plain header text (already built by the
                caller) - unchanged from before this batch.
            query: The search query that was used - passed through to
                count_matching() so its real total reflects the exact
                same filter search() itself already applied.
            category: The category filter that was applied, if any -
                used both to pick the matching real total and to name
                the category in the notice text.

        Returns:
            The same formatted text _format() would already produce,
            with an honest "[showing N of M matches...; more matches
            exist]" notice appended only when the real total is
            greater than the number of records actually shown. The
            empty-result case ("{header}: none found.") is returned
            completely unchanged.
        """
        formatted = self._format(records, header)
        if not records:
            return formatted

        shown = len(records)
        total = self._memory.count_matching(query, category=category)
        scope = f" in category '{category.strip().lower()}'" if category else ""

        if total > shown:
            formatted += (
                f"\n\n[showing {shown} of {total} matches{scope}; "
                "more matches exist]"
            )
        return formatted

    @staticmethod
    def _format_row(record: MemoryRecord) -> str:
        """Format a single memory record as one readable line.

        Includes the record's real creation time (Phase 70), using the
        same `isoformat(timespec="seconds")` convention
        ApprovalHistoryTool/WorkflowHistoryTool already use for their own
        timestamps - never a new date format.

        Args:
            record: The memory record to format.

        Returns:
            A single-line summary of the memory, including when it was
            created.
        """
        created = record.created_at.isoformat(timespec="seconds")
        return f"[{record.id}] ({record.category}) {record.content} (created: {created})"

    def _format_categories(self) -> str:
        """Format a real, per-category memory count breakdown (Phase 71,
        Batch 1).

        Each count comes from one call to
        MemoryManager.count_by_category() - never a fabricated,
        estimated, or inferred value, and no AI involvement. Every
        category in memory.memory_models.KNOWN_CATEGORIES is included,
        even one with zero memories - an honest zero is reported, never
        omitted. Categories are rendered in KNOWN_CATEGORIES's own
        fixed, declared order - never sorted by count - so nothing here
        implies one category is more important than another, mirroring
        the dashboard's own established Category Breakdown panel
        (Phase 63) exactly.

        Returns:
            A formatted, multi-line string: a header line followed by
            one "<category>: <count>" line per known category.
        """
        lines = ["Memory categories:"]
        for category in KNOWN_CATEGORIES:
            count = self._memory.count_by_category(category)
            lines.append(f"  {category}: {count}")
        return "\n".join(lines)