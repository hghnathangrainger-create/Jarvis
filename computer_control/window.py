"""
window.py

Window management for the Jarvis Computer Control module.

Responsibilities:
    - Launch and close applications.
    - List, switch, resize, move, minimize, maximize windows.
    - Platform-aware with graceful fallbacks.

Does NOT:
    - Control mouse/keyboard input (see input.py).
    - Execute arbitrary shell commands (see commands.py).

Requires: pip install pygetwindow psutil
"""

from __future__ import annotations

import logging
import platform
import subprocess
from typing import Any

from computer_control.models import ComputerControlError, WindowInfo

logger = logging.getLogger(__name__)


class WindowManager:
    """Manages application windows and processes.

    Uses pygetwindow for window operations and psutil for process
    detection. Gracefully handles missing libraries or permissions.

    Attributes:
        available: Whether the required libraries are installed.
    """

    def __init__(self) -> None:
        """Initialise the window manager."""
        self._pygetwindow = None
        self._psutil = None
        self.available = False

        try:
            import pygetwindow  # noqa: F401
            self._pygetwindow = pygetwindow
        except ImportError:
            logger.debug("pygetwindow not installed.")

        try:
            import psutil  # noqa: F401
            self._psutil = psutil
        except ImportError:
            logger.debug("psutil not installed.")

        self.available = self._pygetwindow is not None or self._psutil is not None

    def launch_application(self, command: str) -> bool:
        """Launch an application using a platform-appropriate method.

        Args:
            command: The application command or path to launch.

        Returns:
            True if the launch was attempted, False on failure.
        """
        logger.info("Launching application: %s", command)
        try:
            system = platform.system()
            if system == "Windows":
                subprocess.Popen(
                    ["cmd", "/c", "start", "", command],
                    shell=False,
                )
            elif system == "Darwin":
                subprocess.Popen(["open", command])
            else:
                subprocess.Popen(["xdg-open", command])
            return True
        except Exception as exc:
            logger.error("Failed to launch '%s': %s", command, exc)
            return False

    def close_application(self, name: str) -> bool:
        """Close an application by name using psutil.

        Args:
            name: The application name to close (case-insensitive).

        Returns:
            True if at least one process was terminated.
        """
        if self._psutil is None:
            logger.warning("psutil not available for close_application.")
            return False

        logger.info("Closing application: %s", name)
        closed = False
        name_lower = name.lower()
        try:
            for proc in self._psutil.process_iter(["name", "pid"]):
                try:
                    proc_name = proc.info["name"]
                    if proc_name and name_lower in proc_name.lower():
                        proc.terminate()
                        closed = True
                        logger.info("Terminated process: %s (pid=%d)", proc_name, proc.pid)
                except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                    continue
        except Exception as exc:
            logger.error("Error closing application '%s': %s", name, exc)

        return closed

    def list_windows(self) -> list[WindowInfo]:
        """Return all visible windows.

        Returns:
            A list of WindowInfo objects for each visible window.
        """
        if self._pygetwindow is None:
            logger.debug("pygetwindow not available for list_windows.")
            return []

        windows = []
        try:
            all_windows = self._pygetwindow.getAllWindows()
            for w in all_windows:
                if not w.visible:
                    continue
                try:
                    bounds = w.bounds
                    windows.append(
                        WindowInfo(
                            handle=getattr(w, "_hWnd", None),
                            title=w.title or "",
                            app_name=None,
                            is_active=getattr(w, "_isCurrentWindow", False),
                            x=bounds.get("left", 0) if isinstance(bounds, dict) else getattr(w, "left", 0),
                            y=bounds.get("top", 0) if isinstance(bounds, dict) else getattr(w, "top", 0),
                            width=bounds.get("width", 0) if isinstance(bounds, dict) else getattr(w, "width", 0),
                            height=bounds.get("height", 0) if isinstance(bounds, dict) else getattr(w, "height", 0),
                        )
                    )
                except Exception:
                    # Skip windows that can't be read.
                    continue
        except Exception as exc:
            logger.error("Error listing windows: %s", exc)

        return windows

    def get_active_window(self) -> WindowInfo | None:
        """Return information about the currently focused window.

        Returns:
            A WindowInfo, or None if no active window is found.
        """
        if self._pygetwindow is None:
            return None

        try:
            w = self._pygetwindow.getActiveWindow()
            if w is None:
                return None
            bounds = w.bounds if hasattr(w, "bounds") else {}
            return WindowInfo(
                handle=getattr(w, "_hWnd", None),
                title=w.title or "",
                app_name=None,
                is_active=True,
                x=bounds.get("left", 0) if isinstance(bounds, dict) else getattr(w, "left", 0),
                y=bounds.get("top", 0) if isinstance(bounds, dict) else getattr(w, "top", 0),
                width=bounds.get("width", 0) if isinstance(bounds, dict) else getattr(w, "width", 0),
                height=bounds.get("height", 0) if isinstance(bounds, dict) else getattr(w, "height", 0),
            )
        except Exception as exc:
            logger.error("Error getting active window: %s", exc)
            return None

    def switch_to_window(self, title: str) -> bool:
        """Bring a window to the front by title.

        Args:
            title: The window title (case-insensitive substring match).

        Returns:
            True if a matching window was found and focused.
        """
        if self._pygetwindow is None:
            return False

        logger.info("Switching to window: %s", title)
        try:
            windows = self._pygetwindow.getWindowsWithTitle(title)
            if not windows:
                return False
            w = windows[0]
            if w.isMinimized:
                w.restore()
            w.activate()
            return True
        except Exception as exc:
            logger.error("Error switching to window '%s': %s", title, exc)
            return False

    def resize_window(self, title: str, width: int, height: int) -> bool:
        """Resize a window by title.

        Args:
            title: The window title (case-insensitive substring match).
            width: New width in pixels.
            height: New height in pixels.

        Returns:
            True if a matching window was found and resized.
        """
        if self._pygetwindow is None:
            return False

        logger.info("Resizing window '%s' to %dx%d", title, width, height)
        try:
            windows = self._pygetwindow.getWindowsWithTitle(title)
            if not windows:
                return False
            windows[0].resizeTo(width, height)
            return True
        except Exception as exc:
            logger.error("Error resizing window '%s': %s", title, exc)
            return False

    def move_window(self, title: str, x: int, y: int) -> bool:
        """Move a window by title.

        Args:
            title: The window title (case-insensitive substring match).
            x: New X coordinate.
            y: New Y coordinate.

        Returns:
            True if a matching window was found and moved.
        """
        if self._pygetwindow is None:
            return False

        logger.info("Moving window '%s' to (%d, %d)", title, x, y)
        try:
            windows = self._pygetwindow.getWindowsWithTitle(title)
            if not windows:
                return False
            windows[0].moveTo(x, y)
            return True
        except Exception as exc:
            logger.error("Error moving window '%s': %s", title, exc)
            return False

    def minimize_window(self, title: str) -> bool:
        """Minimize a window by title.

        Args:
            title: The window title (case-insensitive substring match).

        Returns:
            True if a matching window was found and minimized.
        """
        if self._pygetwindow is None:
            return False

        logger.info("Minimizing window: %s", title)
        try:
            windows = self._pygetwindow.getWindowsWithTitle(title)
            if not windows:
                return False
            windows[0].minimize()
            return True
        except Exception as exc:
            logger.error("Error minimizing window '%s': %s", title, exc)
            return False

    def maximize_window(self, title: str) -> bool:
        """Maximize a window by title.

        Args:
            title: The window title (case-insensitive substring match).

        Returns:
            True if a matching window was found and maximized.
        """
        if self._pygetwindow is None:
            return False

        logger.info("Maximizing window: %s", title)
        try:
            windows = self._pygetwindow.getWindowsWithTitle(title)
            if not windows:
                return False
            windows[0].maximize()
            return True
        except Exception as exc:
            logger.error("Error maximizing window '%s': %s", title, exc)
            return False
