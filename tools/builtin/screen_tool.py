"""
screen_tool.py

A GREEN tool for screen analysis in the Jarvis Computer Control system.

Actions: screenshot, read_text, analyze, detect_ui.
All actions are read-only (GREEN tier) — never mutates any state.

Screenshots are taken via mss, text extracted via pytesseract,
and analysis done via the AI router.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ScreenTool(BaseTool):
    """Analyses screen content: screenshots, OCR, AI vision, UI detection.

    GREEN-tier tool — all operations are read-only.

    Attributes:
        _manager: The ComputerControlManager providing screen operations.
    """

    def __init__(self, manager: Any, ai_router: Any = None) -> None:
        """Initialise the tool.

        Args:
            manager: A ComputerControlManager instance.
            ai_router: Optional AIRouter for AI vision analysis.
        """
        self._manager = manager
        self._ai_router = ai_router

    @property
    def name(self) -> str:
        return "screen_analyzer"

    @property
    def description(self) -> str:
        return (
            "Analyse screen content: take screenshots, extract text via OCR, "
            "detect UI elements, and AI-powered screen understanding. Read-only."
        )

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a screen analysis request.

        Args:
            request: The request with input_data containing:
                - action (str): The operation to perform.
                - Other fields depend on the action.

        Returns:
            A ToolResult with the analysis results.
        """
        action = str(request.input_data.get("action", "screenshot")).strip().lower()

        dispatch = {
            "screenshot": self._screenshot,
            "read_text": self._read_text,
            "analyze": self._analyze,
            "detect_ui": self._detect_ui,
        }

        handler = dispatch.get(action)
        if handler is None:
            return self.fail(
                f"Unknown action '{action}'. "
                "Use: screenshot, read_text, analyze, detect_ui."
            )
        return handler(request)

    def _screenshot(self, request: ToolRequest) -> ToolResult:
        """Take a screenshot and optionally save it."""
        try:
            region = None
            raw_region = request.input_data.get("region")
            if isinstance(raw_region, list) and len(raw_region) == 4:
                region = tuple(int(v) for v in raw_region)

            result = self._manager.take_screenshot(region=region)

            # Save if path provided.
            save_path = str(request.input_data.get("save_path", "")).strip()
            if save_path:
                self._manager.save_screenshot(result.image_bytes, save_path)
                return self.ok(
                    f"Screenshot saved to {save_path}\n"
                    f"Size: {result.width}x{result.height}, "
                    f"{len(result.image_bytes)} bytes"
                )

            # Save to temp file for reference.
            temp = tempfile.NamedTemporaryFile(
                suffix=".png", prefix="jarvis_screenshot_", delete=False
            )
            temp.write(result.image_bytes)
            temp.close()

            return self.ok(
                f"Screenshot captured: {result.width}x{result.height}, "
                f"{len(result.image_bytes)} bytes\n"
                f"Saved to: {temp.name}"
            )

        except RuntimeError as exc:
            return self.fail(str(exc))

    def _read_text(self, request: ToolRequest) -> ToolResult:
        """Take a screenshot and extract text via OCR."""
        if not self._manager.screen_analyzer.pytesseract_available:
            return self.fail(
                "OCR unavailable: pytesseract not installed. "
                "Install with: pip install pytesseract"
            )

        try:
            text = self._manager.read_screen()
            if not text:
                return self.ok("No text detected on screen.")
            return self.ok(f"Detected text:\n\n{text[:5000]}")
        except RuntimeError as exc:
            return self.fail(str(exc))

    def _analyze(self, request: ToolRequest) -> ToolResult:
        """Take a screenshot and analyse it with AI vision."""
        prompt = str(request.input_data.get("prompt", "")).strip()
        if not prompt:
            prompt = "Describe what you see on this screenshot in detail."

        if self._ai_router is None:
            return self.fail(
                "No AI router available for screen analysis."
            )

        try:
            result = self._manager.take_screenshot()
            analysis = self._manager.screen_analyzer.analyze_with_ai(
                result.image_bytes, prompt, ai_router=self._ai_router
            )
            return self.ok(
                f"Screenshot: {result.width}x{result.height}\n\n"
                f"Analysis:\n{analysis}"
            )
        except RuntimeError as exc:
            return self.fail(str(exc))

    def _detect_ui(self, request: ToolRequest) -> ToolResult:
        """Take a screenshot and detect UI elements."""
        if not self._manager.screen_analyzer.pytesseract_available:
            return self.fail(
                "UI detection unavailable: pytesseract not installed."
            )

        try:
            elements = self._manager.detect_ui_elements()
            if not elements:
                return self.ok("No UI elements detected.")

            lines = [f"Detected {len(elements)} UI elements:", ""]
            for elem in elements[:50]:  # Limit output
                conf_str = f"{elem.confidence:.0%}"
                lines.append(
                    f"  [{elem.element_type}] \"{elem.text}\" "
                    f"at ({elem.x},{elem.y}) {elem.width}x{elem.height} "
                    f"conf={conf_str}"
                )
            if len(elements) > 50:
                lines.append(f"  ... and {len(elements) - 50} more")

            return self.ok("\n".join(lines))

        except RuntimeError as exc:
            return self.fail(str(exc))
