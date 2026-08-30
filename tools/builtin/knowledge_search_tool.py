"""
knowledge_search_tool.py

A GREEN tool that searches the Jarvis Knowledge Library.

KnowledgeSearchTool is a read-only tool. It supports keyword, semantic,
and hybrid search modes. It delegates entirely to the KnowledgeManager.

Supported operations (via the 'mode' input):
    - "keyword":  SQLite substring match on title/content.
    - "semantic": ChromaDB vector similarity search.
    - "hybrid":   Combines both with deduplication (default).
"""

from __future__ import annotations

from knowledge.manager import KnowledgeManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


class KnowledgeSearchTool(BaseTool):
    """Searches the Knowledge Library using keyword, semantic, or hybrid search.

    Attributes:
        _manager: The KnowledgeManager providing search access.
    """

    def __init__(self, manager: KnowledgeManager) -> None:
        """Initialise the tool with a KnowledgeManager.

        Args:
            manager: The KnowledgeManager providing search access.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "knowledge_search"

    @property
    def description(self) -> str:
        """Return a short description of the tool."""
        return "Searches the knowledge library. Read-only and safe."

    def run(self, request: ToolRequest) -> ToolResult:
        """Search knowledge entries by query and mode.

        Args:
            request: The request. Recognised input keys:
                query: The search text (required).
                mode: "keyword", "semantic", or "hybrid" (default: "hybrid").
                top_k: Maximum results (default: 10).
                category: Optional category filter.

        Returns:
            A ToolResult with formatted search results or an error.
        """
        query = request.input_data.get("query")
        if not isinstance(query, str) or not query.strip():
            return self.fail("Search requires a non-empty 'query' string.")

        mode = str(request.input_data.get("mode", "hybrid")).strip().lower()
        if mode not in ("keyword", "semantic", "hybrid"):
            return self.fail(
                f"Unknown search mode '{mode}'. Use 'keyword', 'semantic', or 'hybrid'."
            )

        top_k = self._clamp_limit(request.input_data.get("top_k", _DEFAULT_LIMIT))
        category = request.input_data.get("category")
        category = category if isinstance(category, str) and category.strip() else None

        try:
            entries = self._manager.search_knowledge(
                query, mode=mode, top_k=top_k, category=category
            )
        except RuntimeError as exc:
            return self.fail(str(exc))

        if not entries:
            return self.ok(f"No knowledge entries found matching '{query.strip()}'.")

        lines = [f"Knowledge entries matching '{query.strip()}' ({mode} search):"]
        for entry in entries:
            lines.append(self._format_entry(entry))
        return self.ok("\n".join(lines))

    @staticmethod
    def _format_entry(entry) -> str:
        """Format a single knowledge entry as one readable line."""
        tags_str = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        created = entry.created_at
        if hasattr(created, "isoformat"):
            created = created.isoformat(timespec="seconds")
        return (
            f"  [{entry.id}] ({entry.category}) {entry.title}{tags_str} "
            f"(source: {entry.source}, created: {created})"
        )

    @staticmethod
    def _clamp_limit(value: object) -> int:
        """Coerce and clamp a limit input into a safe range."""
        try:
            limit = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return _DEFAULT_LIMIT
        if limit < 1:
            return 1
        if limit > _MAX_LIMIT:
            return _MAX_LIMIT
        return limit
