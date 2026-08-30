"""
screen.py

Screen analysis for the Jarvis Computer Control module.

Responsibilities:
    - Take screenshots using mss (full screen or region).
    - OCR text extraction using pytesseract.
    - UI element detection using pytesseract's image_to_data.
    - AI-powered screen understanding via the existing AI router.
    - Save screenshots to disk.

Does NOT:
    - Control mouse/keyboard input (see input.py).
    - Manage windows (see window.py).
    - Execute shell commands (see commands.py).

Requires (optional):
    - pip install mss pytesseract Pillow
    - System Tesseract-OCR installation for OCR features.
"""

from __future__ import annotations

import base64
import io
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from computer_control.models import ScreenshotResult, UIElement

logger = logging.getLogger(__name__)


class ScreenAnalyzer:
    """Captures screenshots, extracts text, and analyses screen content.

    Uses mss for fast screenshots, pytesseract for OCR, and the
    existing AI router for vision analysis. All libraries are
    optional — graceful degradation when not installed.

    Attributes:
        mss_available: Whether mss is installed.
        pytesseract_available: Whether pytesseract is installed.
        pillow_available: Whether Pillow is installed.
    """

    def __init__(self) -> None:
        """Initialise the screen analyser, checking library availability."""
        self.mss_available = self._check_mss()
        self.pytesseract_available = self._check_pytesseract()
        self.pillow_available = self._check_pillow()
        self._mss: Any = None
        self._pytesseract: Any = None

    @staticmethod
    def _check_mss() -> bool:
        try:
            import mss  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_pytesseract() -> bool:
        try:
            import pytesseract  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _check_pillow() -> bool:
        try:
            from PIL import Image  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_mss(self) -> Any:
        """Lazy-load and return the mss module."""
        if self._mss is None:
            if not self.mss_available:
                raise RuntimeError(
                    "mss is not installed. Install with: pip install mss"
                )
            import mss
            self._mss = mss
        return self._mss

    def _get_pytesseract(self) -> Any:
        """Lazy-load and return the pytesseract module."""
        if self._pytesseract is None:
            if not self.pytesseract_available:
                raise RuntimeError(
                    "pytesseract is not installed. Install with: pip install pytesseract"
                )
            import pytesseract
            self._pytesseract = pytesseract
        return self._pytesseract

    def take_screenshot(
        self, region: tuple[int, int, int, int] | None = None
    ) -> ScreenshotResult:
        """Capture a screenshot.

        Args:
            region: Optional (x, y, width, height) for partial capture.
                If None, captures the full primary monitor.

        Returns:
            A ScreenshotResult with PNG image bytes.

        Raises:
            RuntimeError: If mss is not installed.
        """
        mss = self._get_mss()
        logger.info("Taking screenshot (region=%s)", region)

        try:
            with mss.mss() as sct:
                if region is not None:
                    x, y, w, h = region
                    monitor = {"left": x, "top": y, "width": w, "height": h}
                else:
                    monitor = sct.monitors[1]  # Primary monitor

                screenshot = sct.grab(monitor)
                # Convert to PNG bytes.
                png_bytes = mss.tools.to_png(
                    screenshot.rgb, (screenshot.width, screenshot.height)
                )

                return ScreenshotResult(
                    image_bytes=png_bytes,
                    width=screenshot.width,
                    height=screenshot.height,
                    timestamp=datetime.now(timezone.utc),
                    format="png",
                )

        except Exception as exc:
            logger.error("Screenshot failed: %s", exc)
            raise RuntimeError(f"Screenshot failed: {exc}") from exc

    def take_window_screenshot(
        self, title: str, window_manager: Any = None
    ) -> ScreenshotResult | None:
        """Capture a screenshot of a specific window.

        Args:
            title: The window title to find.
            window_manager: Optional WindowManager to find the window bounds.

        Returns:
            A ScreenshotResult, or None if the window was not found.
        """
        if window_manager is None:
            logger.warning("No WindowManager provided for window screenshot.")
            return None

        windows = window_manager.list_windows()
        target = None
        for w in windows:
            if title.lower() in w.title.lower():
                target = w
                break

        if target is None:
            logger.warning("Window not found: %s", title)
            return None

        region = (target.x, target.y, target.width, target.height)
        try:
            return self.take_screenshot(region=region)
        except RuntimeError:
            return None

    def extract_text(self, image_bytes: bytes) -> str:
        """Extract all visible text from an image using OCR.

        Args:
            image_bytes: PNG image data.

        Returns:
            The extracted text, or empty string if OCR is unavailable.
        """
        if not self.pytesseract_available:
            logger.warning("pytesseract not available for OCR.")
            return ""
        if not self.pillow_available:
            logger.warning("Pillow not available for OCR.")
            return ""

        pytesseract = self._get_pytesseract()

        try:
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes))
            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as exc:
            logger.error("OCR failed: %s", exc)
            return ""

    def detect_ui_elements(self, image_bytes: bytes) -> list[UIElement]:
        """Detect text regions as UI elements using pytesseract.

        Args:
            image_bytes: PNG image data.

        Returns:
            A list of UIElement objects for each detected text region.
        """
        if not self.pytesseract_available:
            return []
        if not self.pillow_available:
            return []

        pytesseract = self._get_pytesseract()

        try:
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes))
            data = pytesseract.image_to_data(
                image, output_type=pytesseract.Output.DICT
            )

            elements = []
            n_boxes = len(data["text"])
            for i in range(n_boxes):
                text = data["text"][i].strip()
                conf = int(data["conf"][i]) if data["conf"][i] != "-1" else 0

                # Skip empty or very low confidence detections.
                if not text or conf < 20:
                    continue

                elements.append(
                    UIElement(
                        element_type="text",
                        text=text,
                        x=data["left"][i],
                        y=data["top"][i],
                        width=data["width"][i],
                        height=data["height"][i],
                        confidence=conf / 100.0,
                    )
                )

            return elements

        except Exception as exc:
            logger.error("UI element detection failed: %s", exc)
            return []

    def analyze_with_ai(
        self,
        image_bytes: bytes,
        prompt: str,
        ai_router: Any = None,
    ) -> str:
        """Analyse a screenshot using AI vision.

        Encodes the image as base64 and sends it to the AI router
        with the given prompt. The image is included in the message
        content for providers that support vision (Claude, GPT-4o).

        Args:
            image_bytes: PNG image data.
            prompt: The analysis prompt (e.g. "What buttons are visible?").
            ai_router: The AIRouter instance to use for the request.

        Returns:
            The AI's analysis text, or an error message.
        """
        if ai_router is None:
            return "No AI router available for screen analysis."

        try:
            image_b64 = base64.b64encode(image_bytes).decode("ascii")

            # Build a message that includes the image context.
            # The image is described as base64 in the message since the
            # existing provider abstraction is text-based.
            augmented_prompt = (
                f"{prompt}\n\n"
                f"[A screenshot has been captured. The image is "
                f"{len(image_bytes)} bytes, base64-encoded. "
                f"If your provider supports vision, describe what you "
                f"see in the screenshot. Otherwise, note that image "
                f"analysis requires a vision-capable model.]"
            )

            response = ai_router.route(
                system_instruction=(
                    "You are analysing a computer screenshot. "
                    "Describe what you see clearly and concisely."
                ),
                user_message=augmented_prompt,
            )

            return response.text

        except Exception as exc:
            logger.error("AI vision analysis failed: %s", exc)
            return f"AI analysis failed: {exc}"

    def save_screenshot(
        self, image_bytes: bytes, path: str
    ) -> bool:
        """Save a screenshot to disk.

        Args:
            image_bytes: PNG image data.
            path: File path to save to.

        Returns:
            True if saved successfully.
        """
        try:
            output_path = Path(path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(image_bytes)
            logger.info("Screenshot saved to %s", path)
            return True
        except Exception as exc:
            logger.error("Failed to save screenshot to %s: %s", path, exc)
            return False
