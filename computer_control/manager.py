"""
manager.py

Facade for the Jarvis Computer Control module.

Responsibilities:
    - Provide a single entry point for all computer control operations.
    - Create and hold InputAutomator, WindowManager, CommandExecutor.
    - Wrap calls in tracer spans for observability.
    - Report availability of submodules based on installed packages.

Does NOT:
    - Implement the actual control logic (delegates to submodules).

The ComputerControlManager is the layer the rest of Jarvis talks to.
"""

from __future__ import annotations

import logging
from typing import Any

from computer_control.commands import CommandExecutor
from computer_control.input import InputAutomator
from computer_control.models import CommandResult, ScreenshotResult, UIElement, WindowInfo
from computer_control.screen import ScreenAnalyzer
from computer_control.window import WindowManager

logger = logging.getLogger(__name__)


class ComputerControlManager:
    """Facade wrapping input, window, and command subsystems.

    Creates all subsystem instances and wraps calls with observability
    tracing when available.

    Attributes:
        input_automator: The mouse/keyboard automation subsystem.
        window_manager: The window management subsystem.
        command_executor: The command execution subsystem.
    """

    def __init__(self, tracer: Any = None, audit_logger: Any = None) -> None:
        """Initialise the computer control manager.

        Args:
            tracer: Optional Tracer for observability spans.
            audit_logger: Optional EventLogger for command audit trail.
        """
        self.input_automator = InputAutomator()
        self.window_manager = WindowManager()
        self.command_executor = CommandExecutor(audit_logger=audit_logger)
        self.screen_analyzer = ScreenAnalyzer()
        self._tracer = tracer

    def is_available(self) -> bool:
        """Whether any computer control capability is available."""
        return (
            self.input_automator.available
            or self.window_manager.available
            or self.command_executor.available
        )

    def get_status(self) -> dict[str, bool]:
        """Return which submodules are available.

        Returns:
            A dict mapping submodule name to availability.
        """
        return {
            "input_automator": self.input_automator.available,
            "window_manager": self.window_manager.available,
            "command_executor": self.command_executor.available,
            "screen_mss": self.screen_analyzer.mss_available,
            "screen_pytesseract": self.screen_analyzer.pytesseract_available,
            "screen_pillow": self.screen_analyzer.pillow_available,
        }

    # ------------------------------------------------------------------
    # Input methods (delegated to InputAutomator)
    # ------------------------------------------------------------------

    def click(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> None:
        """Click at screen coordinates."""
        with self._span("input_click"):
            self.input_automator.click(x, y, button=button, clicks=clicks)

    def double_click(self, x: int, y: int) -> None:
        """Double-click at screen coordinates."""
        with self._span("input_double_click"):
            self.input_automator.double_click(x, y)

    def right_click(self, x: int, y: int) -> None:
        """Right-click at screen coordinates."""
        with self._span("input_right_click"):
            self.input_automator.right_click(x, y)

    def type_text(self, text: str, interval: float = 0.02) -> None:
        """Type text character by character."""
        with self._span("input_type"):
            self.input_automator.type_text(text, interval=interval)

    def press_key(self, key: str) -> None:
        """Press and release a single key."""
        with self._span("input_press_key"):
            self.input_automator.press_key(key)

    def hotkey(self, *keys: str) -> None:
        """Press a key combination."""
        with self._span("input_hotkey"):
            self.input_automator.hotkey(*keys)

    def scroll(
        self, amount: int, x: int | None = None, y: int | None = None
    ) -> None:
        """Scroll the mouse wheel."""
        with self._span("input_scroll"):
            self.input_automator.scroll(amount, x=x, y=y)

    def drag(
        self,
        start_x: int, start_y: int,
        end_x: int, end_y: int,
        duration: float = 0.5,
    ) -> None:
        """Drag from one position to another."""
        with self._span("input_drag"):
            self.input_automator.drag(start_x, start_y, end_x, end_y, duration)

    def move_mouse(self, x: int, y: int) -> None:
        """Move the mouse to screen coordinates."""
        with self._span("input_move"):
            self.input_automator.move_mouse(x, y)

    def get_mouse_position(self) -> tuple[int, int]:
        """Return the current mouse position."""
        return self.input_automator.get_mouse_position()

    # ------------------------------------------------------------------
    # Window methods (delegated to WindowManager)
    # ------------------------------------------------------------------

    def launch_application(self, command: str) -> bool:
        """Launch an application."""
        with self._span("window_launch"):
            return self.window_manager.launch_application(command)

    def close_application(self, name: str) -> bool:
        """Close an application by name."""
        with self._span("window_close"):
            return self.window_manager.close_application(name)

    def list_windows(self) -> list[WindowInfo]:
        """Return all visible windows."""
        return self.window_manager.list_windows()

    def get_active_window(self) -> WindowInfo | None:
        """Return the currently focused window."""
        return self.window_manager.get_active_window()

    def switch_to_window(self, title: str) -> bool:
        """Bring a window to the front."""
        with self._span("window_switch"):
            return self.window_manager.switch_to_window(title)

    def resize_window(self, title: str, width: int, height: int) -> bool:
        """Resize a window."""
        with self._span("window_resize"):
            return self.window_manager.resize_window(title, width, height)

    def move_window(self, title: str, x: int, y: int) -> bool:
        """Move a window."""
        with self._span("window_move"):
            return self.window_manager.move_window(title, x, y)

    def minimize_window(self, title: str) -> bool:
        """Minimize a window."""
        with self._span("window_minimize"):
            return self.window_manager.minimize_window(title)

    def maximize_window(self, title: str) -> bool:
        """Maximize a window."""
        with self._span("window_maximize"):
            return self.window_manager.maximize_window(title)

    # ------------------------------------------------------------------
    # Command methods (delegated to CommandExecutor)
    # ------------------------------------------------------------------

    def run_shell(self, command: str, timeout: int = 30) -> CommandResult:
        """Run a shell command."""
        with self._span("command_shell"):
            return self.command_executor.run_shell(command, timeout=timeout)

    def run_powershell(self, command: str, timeout: int = 30) -> CommandResult:
        """Run a PowerShell command."""
        with self._span("command_powershell"):
            return self.command_executor.run_powershell(command, timeout=timeout)

    def run_python_script(
        self,
        script_path: str,
        args: list[str] | None = None,
        timeout: int = 60,
    ) -> CommandResult:
        """Run a Python script."""
        with self._span("command_script"):
            return self.command_executor.run_python_script(
                script_path, args=args, timeout=timeout
            )

    # ------------------------------------------------------------------
    # Screen methods (delegated to ScreenAnalyzer)
    # ------------------------------------------------------------------

    def take_screenshot(
        self, region: tuple[int, int, int, int] | None = None
    ) -> ScreenshotResult:
        """Capture a screenshot."""
        with self._span("screen_screenshot"):
            return self.screen_analyzer.take_screenshot(region=region)

    def read_screen(self) -> str:
        """Take a screenshot and extract all visible text via OCR."""
        with self._span("screen_ocr"):
            result = self.screen_analyzer.take_screenshot()
            return self.screen_analyzer.extract_text(result.image_bytes)

    def analyze_screen(self, prompt: str, ai_router: Any = None) -> str:
        """Take a screenshot and analyse it with AI vision."""
        with self._span("screen_analyze"):
            result = self.screen_analyzer.take_screenshot()
            return self.screen_analyzer.analyze_with_ai(
                result.image_bytes, prompt, ai_router=ai_router
            )

    def detect_ui_elements(self) -> list[UIElement]:
        """Take a screenshot and detect UI elements."""
        with self._span("screen_detect_ui"):
            result = self.screen_analyzer.take_screenshot()
            return self.screen_analyzer.detect_ui_elements(result.image_bytes)

    def save_screenshot(self, image_bytes: bytes, path: str) -> bool:
        """Save a screenshot to disk."""
        return self.screen_analyzer.save_screenshot(image_bytes, path)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def _span(self, name: str) -> Any:
        """Create a tracer span if a tracer is available.

        Args:
            name: The span name.

        Returns:
            A context manager (tracer span or a no-op).
        """
        if self._tracer is not None and hasattr(self._tracer, "span"):
            return self._tracer.span(
                trace_id="computer_control",
                span_name=name,
                subsystem="computer_control",
            )
        return _NoOpSpan()


class _NoOpSpan:
    """A no-op context manager used when no tracer is available."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
