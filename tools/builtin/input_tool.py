"""
input_tool.py

A YELLOW tool for input automation (mouse/keyboard) in the Jarvis
Computer Control system.

Actions: click, type, hotkey, scroll, drag, move, position.
Requires user confirmation before execution.

YELLOW because it controls mouse/keyboard input which can interact
with any application on the system.
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class InputTool(BaseTool):
    """Controls mouse and keyboard input via the ComputerControlManager.

    Attributes:
        _manager: The ComputerControlManager providing input operations.
    """

    def __init__(self, manager: Any) -> None:
        """Initialise the tool.

        Args:
            manager: A ComputerControlManager instance.
        """
        self._manager = manager

    @property
    def name(self) -> str:
        return "input_control"

    @property
    def description(self) -> str:
        return "Control mouse and keyboard: click, type, hotkey, scroll, drag, move."

    def action_for(self, request: ToolRequest) -> str:
        """Input operations require confirmation — always YELLOW."""
        return "input_control"

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle an input control request.

        Args:
            request: The request with input_data containing:
                - action (str): The operation to perform.
                - Other fields depend on the action.

        Returns:
            A ToolResult with the outcome.
        """
        action = str(request.input_data.get("action", "position")).strip().lower()

        dispatch = {
            "click": self._click,
            "double_click": self._double_click,
            "right_click": self._right_click,
            "type": self._type,
            "press_key": self._press_key,
            "hotkey": self._hotkey,
            "scroll": self._scroll,
            "drag": self._drag,
            "move": self._move,
            "position": self._position,
        }

        handler = dispatch.get(action)
        if handler is None:
            return self.fail(
                f"Unknown action '{action}'. "
                "Use: click, type, hotkey, scroll, drag, move, position."
            )
        return handler(request)

    def _click(self, request: ToolRequest) -> ToolResult:
        """Click at coordinates."""
        x, y = self._parse_xy(request)
        if x is None:
            return self.fail("x and y coordinates are required.")
        button = str(request.input_data.get("button", "left")).strip()
        clicks = int(request.input_data.get("clicks", 1) or 1)
        self._manager.click(x, y, button=button, clicks=clicks)
        pos = self._manager.get_mouse_position()
        return self.ok(f"Clicked ({x}, {y}) button={button} clicks={clicks}. Mouse at {pos}.")

    def _double_click(self, request: ToolRequest) -> ToolResult:
        """Double-click at coordinates."""
        x, y = self._parse_xy(request)
        if x is None:
            return self.fail("x and y coordinates are required.")
        self._manager.double_click(x, y)
        pos = self._manager.get_mouse_position()
        return self.ok(f"Double-clicked ({x}, {y}). Mouse at {pos}.")

    def _right_click(self, request: ToolRequest) -> ToolResult:
        """Right-click at coordinates."""
        x, y = self._parse_xy(request)
        if x is None:
            return self.fail("x and y coordinates are required.")
        self._manager.right_click(x, y)
        pos = self._manager.get_mouse_position()
        return self.ok(f"Right-clicked ({x}, {y}). Mouse at {pos}.")

    def _type(self, request: ToolRequest) -> ToolResult:
        """Type text."""
        text = str(request.input_data.get("text", "")).strip()
        if not text:
            return self.fail("No text provided. Usage: text='hello world'")
        interval = float(request.input_data.get("interval", 0.02) or 0.02)
        self._manager.type_text(text, interval=interval)
        return self.ok(f"Typed {len(text)} characters.")

    def _press_key(self, request: ToolRequest) -> ToolResult:
        """Press a key."""
        key = str(request.input_data.get("key", "")).strip()
        if not key:
            return self.fail("No key provided. Usage: key='enter'")
        self._manager.press_key(key)
        return self.ok(f"Pressed key: {key}")

    def _hotkey(self, request: ToolRequest) -> ToolResult:
        """Press a key combination."""
        keys = request.input_data.get("keys")
        if not isinstance(keys, list) or not keys:
            return self.fail("No keys provided. Usage: keys=['ctrl', 'c']")
        str_keys = [str(k) for k in keys]
        self._manager.hotkey(*str_keys)
        return self.ok(f"Pressed hotkey: {'+'.join(str_keys)}")

    def _scroll(self, request: ToolRequest) -> ToolResult:
        """Scroll the mouse wheel."""
        amount = int(request.input_data.get("amount", 3) or 3)
        x = request.input_data.get("x")
        y = request.input_data.get("y")
        x = int(x) if x is not None else None
        y = int(y) if y is not None else None
        self._manager.scroll(amount, x=x, y=y)
        return self.ok(f"Scrolled {amount} units.")

    def _drag(self, request: ToolRequest) -> ToolResult:
        """Drag from one position to another."""
        start_x, start_y = self._parse_xy(request, prefix="start_")
        end_x, end_y = self._parse_xy(request, prefix="end_")
        if start_x is None or end_x is None:
            return self.fail(
                "start_x, start_y, end_x, end_y are required."
            )
        duration = float(request.input_data.get("duration", 0.5) or 0.5)
        self._manager.drag(start_x, start_y, end_x, end_y, duration)
        return self.ok(f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y}).")

    def _move(self, request: ToolRequest) -> ToolResult:
        """Move the mouse."""
        x, y = self._parse_xy(request)
        if x is None:
            return self.fail("x and y coordinates are required.")
        self._manager.move_mouse(x, y)
        return self.ok(f"Mouse moved to ({x}, {y}).")

    def _position(self, request: ToolRequest) -> ToolResult:
        """Get current mouse position."""
        pos = self._manager.get_mouse_position()
        return self.ok(f"Mouse position: ({pos[0]}, {pos[1]})")

    @staticmethod
    def _parse_xy(
        request: ToolRequest, prefix: str = ""
    ) -> tuple[int | None, int | None]:
        """Parse x, y coordinates from request input_data.

        Args:
            request: The tool request.
            prefix: Optional prefix (e.g. "start_" or "end_").

        Returns:
            Tuple of (x, y) or (None, None) if not found/parsable.
        """
        raw_x = request.input_data.get(f"{prefix}x")
        raw_y = request.input_data.get(f"{prefix}y")
        try:
            x = int(raw_x) if raw_x is not None else None
            y = int(raw_y) if raw_y is not None else None
            return x, y
        except (ValueError, TypeError):
            return None, None
