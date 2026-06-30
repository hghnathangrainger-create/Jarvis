"""
echo_tool.py

A minimal, safe tool that echoes its input text.

EchoTool is a GREEN tool: it performs no state changes and touches nothing
outside the request. It exists to exercise the tool pipeline end to end and to
serve as the simplest possible example of a BaseTool implementation.
"""

from __future__ import annotations

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class EchoTool(BaseTool):
    """Returns the text it was given, unchanged."""

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "echo".
        """
        return "echo"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return "Echoes back the provided text. Safe and read-only."

    def action_for(self, request: ToolRequest) -> str:
        """Return a read-only action string for security classification.

        Echoing only returns the provided text; it is a read-only,
        side-effect-free operation, so it is phrased as a "show" action that
        the Security Manager classifies GREEN.

        Args:
            request: The request being handled.

        Returns:
            A read-only action string.
        """
        return "show provided text"

    def run(self, request: ToolRequest) -> ToolResult:
        """Echo the 'text' input back to the caller.

        Args:
            request: The request. Expects an optional 'text' key in input_data.

        Returns:
            A successful ToolResult containing the echoed text, or a failed
            result if 'text' is missing or not a string.
        """
        text = request.input_data.get("text")
        if text is None:
            return self.fail("Missing required input: 'text'.")
        if not isinstance(text, str):
            return self.fail("Input 'text' must be a string.")
        return self.ok(text)