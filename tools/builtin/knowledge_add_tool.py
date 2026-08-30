"""
knowledge_add_tool.py

A YELLOW tool that adds entries to the Jarvis Knowledge Library.

KnowledgeAddTool is a guarded write tool. It persists a new knowledge
entry to both SQLite and ChromaDB. It delegates entirely to the
KnowledgeManager.

This tool is classified YELLOW because it modifies durable state
(the knowledge library), requiring user confirmation before execution.
"""

from __future__ import annotations

from knowledge.manager import KnowledgeManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class KnowledgeAddTool(BaseTool):
    """Adds a new entry to the Knowledge Library.

    Attributes:
        _manager: The KnowledgeManager providing write access.
    """

    def __init__(self, manager: KnowledgeManager) -> None:
        """Initialise the tool with a KnowledgeManager.

        Args:
            manager: The KnowledgeManager providing write access.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "knowledge_add"

    @property
    def description(self) -> str:
        """Return a short description of the tool."""
        return "Adds a new entry to the knowledge library."

    def run(self, request: ToolRequest) -> ToolResult:
        """Add a new knowledge entry.

        Args:
            request: The request. Recognised input keys:
                title: The entry title (required).
                content: The entry content (required).
                category: Optional category (default: "general").
                tags: Optional list of string tags.
                source: Optional source label (default: "manual").

        Returns:
            A ToolResult confirming the save or failing on missing input.
        """
        title = request.input_data.get("title")
        if not isinstance(title, str) or not title.strip():
            return self.fail("Adding knowledge requires a non-empty 'title'.")

        content = request.input_data.get("content")
        if not isinstance(content, str) or not content.strip():
            return self.fail("Adding knowledge requires non-empty 'content'.")

        category = request.input_data.get("category", "general")
        if not isinstance(category, str) or not category.strip():
            category = "general"

        raw_tags = request.input_data.get("tags", [])
        if isinstance(raw_tags, list):
            tags = [str(t) for t in raw_tags if isinstance(t, (str, int))]
        else:
            tags = []

        source = request.input_data.get("source", "manual")
        if not isinstance(source, str) or not source.strip():
            source = "manual"

        entry = self._manager.add_knowledge(
            title=title.strip(),
            content=content.strip(),
            category=category.strip(),
            tags=tags,
            source=source.strip(),
        )

        tags_str = f" [{', '.join(entry.tags)}]" if entry.tags else ""
        return ToolResult(
            tool_name=self.name,
            success=True,
            output=(
                f"Added knowledge: [{entry.id}] ({entry.category}) "
                f"{entry.title}{tags_str}"
            ),
            metadata={
                "operation": "add",
                "entry_id": str(entry.id),
                "category": entry.category,
            },
        )
