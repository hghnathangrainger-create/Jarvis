"""
models.py

Data models for the Jarvis Computer Control module.

Responsibilities:
    - Define WindowInfo for window management data.
    - Define CommandResult for command execution outcomes.
    - Define ComputerControlError for module-specific exceptions.

Does NOT:
    - Implement any computer control logic.
    - Access the filesystem or run commands.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone


class ComputerControlError(Exception):
    """Raised when a computer control operation fails."""


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """Information about a visible window.

    Attributes:
        handle: Platform-specific window handle (int or platform object).
        title: The window title.
        app_name: The application name, or None if unknown.
        is_active: Whether this is the currently focused window.
        x: Window left edge X coordinate.
        y: Window top edge Y coordinate.
        width: Window width in pixels.
        height: Window height in pixels.
    """

    handle: int | None = None
    title: str = ""
    app_name: str | None = None
    is_active: bool = False
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "handle": self.handle,
            "title": self.title,
            "app_name": self.app_name,
            "is_active": self.is_active,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of executing a shell command.

    Attributes:
        stdout: Standard output text.
        stderr: Standard error text.
        exit_code: The process exit code (0 = success).
        timed_out: True if the command exceeded the timeout.
        command: The original command string that was executed.
    """

    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    command: str = ""

    @property
    def success(self) -> bool:
        """Whether the command succeeded (exit code 0 and no timeout)."""
        return self.exit_code == 0 and not self.timed_out

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "command": self.command,
            "success": self.success,
        }


@dataclass(frozen=True, slots=True)
class ScreenshotResult:
    """The outcome of taking a screenshot.

    Attributes:
        image_bytes: Raw PNG image data.
        width: Image width in pixels.
        height: Image height in pixels.
        timestamp: When the screenshot was taken (UTC).
        format: Image format (e.g. "png").
    """

    image_bytes: bytes = b""
    width: int = 0
    height: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    format: str = "png"

    @property
    def base64(self) -> str:
        """Return the image as a base64-encoded string."""
        return base64.b64encode(self.image_bytes).decode("ascii")

    @property
    def size(self) -> tuple[int, int]:
        """Return (width, height) tuple."""
        return (self.width, self.height)

    def to_dict(self) -> dict:
        """Serialise to a plain dict (without image_bytes)."""
        return {
            "width": self.width,
            "height": self.height,
            "timestamp": self.timestamp.isoformat(),
            "format": self.format,
            "size_bytes": len(self.image_bytes),
        }


@dataclass(frozen=True, slots=True)
class UIElement:
    """A detected UI element from screen analysis.

    Attributes:
        element_type: The type of element (e.g. "text", "button", "field").
        text: The text content of the element.
        x: Bounding box left edge.
        y: Bounding box top edge.
        width: Bounding box width.
        height: Bounding box height.
        confidence: Detection confidence (0.0-1.0).
    """

    element_type: str = "text"
    text: str = ""
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        """Serialise to a plain dict."""
        return {
            "element_type": self.element_type,
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
        }
