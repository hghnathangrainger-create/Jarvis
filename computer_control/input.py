"""
input.py

Input automation for the Jarvis Computer Control module.

Responsibilities:
    - Provide mouse and keyboard control via pyautogui.
    - Enforce FAILSAFE=True (mouse to corner = abort).
    - Log all actions to observability.

Does NOT:
    - Manage windows (see window.py).
    - Execute shell commands (see commands.py).

Requires: pip install pyautogui
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class InputAutomator:
    """Mouse and keyboard automation via pyautogui.

    All methods log actions before execution. pyautogui.FAILSAFE is
    always True — moving the mouse to the top-left corner aborts.

    Attributes:
        available: Whether pyautogui is installed.
    """

    def __init__(self) -> None:
        """Initialise the input automator."""
        self.available = self._check_available()
        self._pyautogui: Any = None
        if self.available:
            try:
                import pyautogui

                pyautogui.FAILSAFE = True
                pyautogui.PAUSE = 0.15
                self._pyautogui = pyautogui
            except Exception as exc:
                logger.warning("Failed to initialise pyautogui: %s", exc)
                self.available = False

    @staticmethod
    def _check_available() -> bool:
        """Check if pyautogui is installed."""
        try:
            import pyautogui  # noqa: F401
            return True
        except ImportError:
            return False

    def _require_available(self) -> Any:
        """Return the pyautogui module or raise."""
        if not self.available or self._pyautogui is None:
            raise RuntimeError(
                "pyautogui is not installed. "
                "Install it with: pip install pyautogui"
            )
        return self._pyautogui

    def click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        """Click at screen coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
            button: Mouse button ("left", "right", "middle").
            clicks: Number of clicks.
        """
        pyautogui = self._require_available()
        logger.info("Click at (%d, %d) button=%s clicks=%d", x, y, button, clicks)
        pyautogui.click(x, y, clicks=clicks, button=button)

    def double_click(self, x: int, y: int) -> None:
        """Double-click at screen coordinates."""
        pyautogui = self._require_available()
        logger.info("Double-click at (%d, %d)", x, y)
        pyautogui.doubleClick(x, y)

    def right_click(self, x: int, y: int) -> None:
        """Right-click at screen coordinates."""
        pyautogui = self._require_available()
        logger.info("Right-click at (%d, %d)", x, y)
        pyautogui.rightClick(x, y)

    def type_text(self, text: str, interval: float = 0.02) -> None:
        """Type text character by character.

        Args:
            text: The text to type.
            interval: Seconds between each character.
        """
        pyautogui = self._require_available()
        logger.info("Typing %d chars", len(text))
        pyautogui.typewrite(text, interval=interval)

    def press_key(self, key: str) -> None:
        """Press and release a single key.

        Args:
            key: Key name (e.g. "enter", "tab", "escape", "space").
        """
        pyautogui = self._require_available()
        logger.info("Press key: %s", key)
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        """Press a key combination.

        Args:
            keys: Key names (e.g. "ctrl", "c" for Ctrl+C).
        """
        pyautogui = self._require_available()
        logger.info("Hotkey: %s", "+".join(keys))
        pyautogui.hotkey(*keys)

    def scroll(
        self, amount: int, x: int | None = None, y: int | None = None
    ) -> None:
        """Scroll the mouse wheel.

        Args:
            amount: Positive = up, negative = down.
            x: Optional X position to scroll at.
            y: Optional Y position to scroll at.
        """
        pyautogui = self._require_available()
        logger.info("Scroll %d at (%s, %s)", amount, x, y)
        if x is not None and y is not None:
            pyautogui.scroll(amount, x=x, y=y)
        else:
            pyautogui.scroll(amount)

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5,
    ) -> None:
        """Drag from one position to another.

        Args:
            start_x: Starting X coordinate.
            start_y: Starting Y coordinate.
            end_x: Ending X coordinate.
            end_y: Ending Y coordinate.
            duration: Duration of the drag in seconds.
        """
        pyautogui = self._require_available()
        logger.info(
            "Drag from (%d, %d) to (%d, %d) duration=%.1f",
            start_x, start_y, end_x, end_y, duration,
        )
        pyautogui.moveTo(start_x, start_y)
        pyautogui.drag(
            end_x - start_x, end_y - start_y, duration=duration
        )

    def move_mouse(self, x: int, y: int) -> None:
        """Move the mouse to screen coordinates.

        Args:
            x: X coordinate.
            y: Y coordinate.
        """
        pyautogui = self._require_available()
        logger.info("Move mouse to (%d, %d)", x, y)
        pyautogui.moveTo(x, y)

    def get_mouse_position(self) -> tuple[int, int]:
        """Return the current mouse position.

        Returns:
            A tuple of (x, y) screen coordinates.
        """
        pyautogui = self._require_available()
        pos = pyautogui.position()
        return (pos[0], pos[1])
