"""
window_tool.py

A YELLOW tool for window management operations in the Jarvis
Computer Control system.

Actions: launch, close, list, switch, resize, move, minimize, maximize.
Requires user confirmation for launch/close.

YELLOW because it modifies window state (launching/closing apps,
moving/resizing windows).
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class WindowTool(BaseTool):
    """Manages application windows: launch, close, list, switch, resize.

    Attributes:
        _manager: The ComputerControlManager providing window operations.
    """

    def __init__(self, manager: Any) -> None:
        """Initialise the tool.

        Args:
            manager: A ComputerControlManager instance.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        return "window_manager"

    @property
    def description(self) -> str:
        return "Manage windows: launch, close, list, switch, resize, move, minimize, maximize."

    def action_for(self, request: ToolRequest) -> str:
        """Window operations modify state — always YELLOW."""
        return "window_manager"

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a window management request.

        Args:
            request: The request with input_data containing:
                - action (str): The operation to perform.
                - Other fields depend on the action.

        Returns:
            A ToolResult with the outcome.
        """
        action = str(request.input_data.get("action", "list")).strip().lower()

        dispatch = {
            "launch": self._launch,
            "close": self._close,
            "list": self._list,
            "switch": self._switch,
            "resize": self._resize,
            "move": self._move,
            "minimize": self._minimize,
            "maximize": self._maximize,
        }

        handler = dispatch.get(action)
        if handler is None:
            return self.fail(
                f"Unknown action '{action}'. "
                "Use: launch, close, list, switch, resize, move, minimize, maximize."
            )
        return handler(request)

    def _launch(self, request: ToolRequest) -> ToolResult:
        """Launch an application."""
        command = str(request.input_data.get("command", "")).strip()
        if not command:
            return self.fail("No command provided. Usage: command='notepad'")
        success = self._manager.launch_application(command)
        if success:
            return self.ok(f"Launched: {command}")
        return self.fail(f"Failed to launch: {command}")

    def _close(self, request: ToolRequest) -> ToolResult:
        """Close an application by name."""
        name = str(request.input_data.get("name", "")).strip()
        if not name:
            return self.fail("No name provided. Usage: name='notepad'")
        success = self._manager.close_application(name)
        if success:
            return self.ok(f"Closed: {name}")
        return self.fail(f"No matching process found for: {name}")

    def _list(self, request: ToolRequest) -> ToolResult:
        """List all visible windows."""
        windows = self._manager.list_windows()
        if not windows:
            return self.ok("No visible windows found.")
        lines = [f"Windows ({len(windows)}):"]
        for w in windows:
            active = " [ACTIVE]" if w.is_active else ""
            lines.append(
                f"  \"{w.title}\"{active} ({w.width}x{w.height} at {w.x},{w.y})"
                if w.title
                else f"  [untitled]{active} ({w.width}x{w.height} at {w.x},{w.y})"
            )
        return self.ok("\n".join(lines))

    def _switch(self, request: ToolRequest) -> ToolResult:
        """Switch to a window by title."""
        title = str(request.input_data.get("title", "")).strip()
        if not title:
            return self.fail("No title provided. Usage: title='Notepad'")
        success = self._manager.switch_to_window(title)
        if success:
            return self.ok(f"Switched to: {title}")
        return self.fail(f"Window not found: {title}")

    def _resize(self, request: ToolRequest) -> ToolResult:
        """Resize a window."""
        title = str(request.input_data.get("title", "")).strip()
        if not title:
            return self.fail("No title provided.")
        try:
            width = int(request.input_data.get("width", 0))
            height = int(request.input_data.get("height", 0))
        except (ValueError, TypeError):
            return self.fail("Width and height must be integers.")
        if width <= 0 or height <= 0:
            return self.fail("Width and height must be positive.")
        success = self._manager.resize_window(title, width, height)
        if success:
            return self.ok(f"Resized '{title}' to {width}x{height}")
        return self.fail(f"Window not found: {title}")

    def _move(self, request: ToolRequest) -> ToolResult:
        """Move a window."""
        title = str(request.input_data.get("title", "")).strip()
        if not title:
            return self.fail("No title provided.")
        try:
            x = int(request.input_data.get("x", 0))
            y = int(request.input_data.get("y", 0))
        except (ValueError, TypeError):
            return self.fail("x and y must be integers.")
        success = self._manager.move_window(title, x, y)
        if success:
            return self.ok(f"Moved '{title}' to ({x}, {y})")
        return self.fail(f"Window not found: {title}")

    def _minimize(self, request: ToolRequest) -> ToolResult:
        """Minimize a window."""
        title = str(request.input_data.get("title", "")).strip()
        if not title:
            return self.fail("No title provided.")
        success = self._manager.minimize_window(title)
        if success:
            return self.ok(f"Minimized: {title}")
        return self.fail(f"Window not found: {title}")

    def _maximize(self, request: ToolRequest) -> ToolResult:
        """Maximize a window."""
        title = str(request.input_data.get("title", "")).strip()
        if not title:
            return self.fail("No title provided.")
        success = self._manager.maximize_window(title)
        if success:
            return self.ok(f"Maximized: {title}")
        return self.fail(f"Window not found: {title}")
