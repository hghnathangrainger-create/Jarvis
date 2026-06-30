"""
info_tool.py

A safe tool that reports basic Jarvis system information.

InfoTool is a GREEN tool: it reads static application identity constants and
returns them. It changes nothing and touches no external resource.
"""

from __future__ import annotations

from config.constants import APP_DESCRIPTION, APP_NAME, APP_VERSION
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class InfoTool(BaseTool):
    """Returns basic identity information about this Jarvis instance."""

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "info".
        """
        return "info"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Returns basic Jarvis system information. Safe and read-only."

    def action_for(self, request: ToolRequest) -> str:
        """Return a read-only action string for security classification.

        Reporting system information is a read-only operation, so it is phrased
        as a "show" action that the Security Manager classifies GREEN.

        Args:
            request: The request being handled.

        Returns:
            A read-only action string.
        """
        return "show system information"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the application's name, version, and description.

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult containing the system information.
        """
        lines = (
            f"Name: {APP_NAME}",
            f"Version: {APP_VERSION}",
            f"Description: {APP_DESCRIPTION}",
        )
        return self.ok("\n".join(lines))