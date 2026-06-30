"""
registry.py

Registration and lookup of tools for the Jarvis AI Operating System.

Responsibilities:
    - Hold the set of available tools, keyed by name.
    - Register new tools, retrieve a tool by name, and list registered tools.

Does NOT:
    - Execute tools or enforce security (see executor.py).
    - Load tools from disk or discover plugins (advanced plugin loading is
      deliberately out of scope for Phase 1).

The registry is a simple in-memory store. Tools are registered explicitly at
startup, which keeps Phase 1 predictable and avoids the complexity and risk of
dynamic plugin loading.
"""

from __future__ import annotations

from tools.base_tool import BaseTool


class ToolRegistry:
    """An in-memory registry of available tools, keyed by name.

    Attributes:
        _tools: Mapping of tool name to tool instance.
    """

    def __init__(self) -> None:
        """Initialise an empty registry."""
        self._tools: dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool) -> None:
        """Register a tool under its declared name.

        Args:
            tool: The tool instance to register.

        Raises:
            ValueError: If a tool with the same name is already registered, or
                if the tool's name is empty.
        """
        name = tool.name.strip()
        if not name:
            raise ValueError("A tool must have a non-empty name.")
        if name in self._tools:
            raise ValueError(f"A tool named '{name}' is already registered.")
        self._tools[name] = tool

    def get_tool(self, name: str) -> BaseTool | None:
        """Return the tool registered under the given name.

        Args:
            name: The name of the tool to retrieve.

        Returns:
            The registered tool, or None if no tool has that name.
        """
        return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Report whether a tool with the given name is registered.

        Args:
            name: The name to check.

        Returns:
            True if a tool with that name is registered, False otherwise.
        """
        return name in self._tools

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools, sorted by name.

        Returns:
            A list of registered tool instances ordered by name.
        """
        return [self._tools[name] for name in sorted(self._tools)]

    def list_tool_names(self) -> list[str]:
        """Return the names of all registered tools, sorted.

        Returns:
            A sorted list of registered tool names.
        """
        return sorted(self._tools)