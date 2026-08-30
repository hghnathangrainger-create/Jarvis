"""
pyttsx3_tts.py

Text-to-speech implementation using pyttsx3 for the Jarvis voice pipeline.

Responsibilities:
    - Synthesise text to speech using pyttsx3 (offline, no API key needed).
    - Support choosing voice and speed.
    - Play audio directly via speak() or return raw audio via synthesize().

Does NOT:
    - Capture audio or implement speech-to-text (see stt.py).
    - Detect wake words (see wake_word.py).
    - Orchestrate the full pipeline (see pipeline.py).

Requires: pip install pyttsx3
"""

from __future__ import annotations

import io
import logging
from typing import Any

from voice.models import TTSRequest
from voice.tts import SpeechResult

logger = logging.getLogger(__name__)


class Pyttsx3TextToSpeech:
    """Text-to-speech using pyttsx3 (offline, no API key needed).

    pyttsx3 uses the OS's built-in TTS engines:
    - Windows: SAPI5
    - macOS: NSSpeechSynthesizer
    - Linux: espeak

    Attributes:
        voice: Voice name/ID, or None for the OS default.
        speed: Speech rate multiplier (1.0 = normal).
    """

    def __init__(
        self,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> None:
        """Initialise the TTS engine.

        Args:
            voice: Voice name/ID (engine-specific), or None for default.
            speed: Speech rate multiplier (1.0 = normal, 0.5 = slow,
                2.0 = fast).
        """
        self.voice = voice
        self.speed = max(0.1, min(5.0, speed))
        self._engine = None

    @property
    def available(self) -> bool:
        """Whether pyttsx3 is installed."""
        try:
            import pyttsx3  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_engine(self) -> Any:
        """Initialise the pyttsx3 engine if not already done."""
        if self._engine is not None:
            return self._engine

        if not self.available:
            raise RuntimeError(
                "pyttsx3 is not installed. "
                "Install it with: pip install pyttsx3"
            )

        try:
            import pyttsx3

            self._engine = pyttsx3.init()

            # Set voice if specified.
            if self.voice is not None:
                voices = self._engine.getProperty("voices")
                for v in voices:
                    if self.voice.lower() in v.id.lower():
                        self._engine.setProperty("voice", v.id)
                        break

            # Set speech rate. pyttsx3 uses words-per-minute (default ~200).
            # Adjust based on speed multiplier.
            base_rate = 200
            self._engine.setProperty("rate", int(base_rate * self.speed))

            logger.info(
                "pyttsx3 TTS engine initialised (voice=%s, speed=%.1f)",
                self.voice or "default",
                self.speed,
            )
            return self._engine

        except Exception as exc:
            raise RuntimeError(f"Failed to initialise pyttsx3: {exc}") from exc

    def synthesize(self, request: TTSRequest) -> bytes | None:
        """Synthesise text to audio bytes.

        Args:
            request: The TTS request with text and parameters.

        Returns:
            Audio bytes (WAV format), or None on failure.
        """
        try:
            engine = self._ensure_engine()
        except RuntimeError as exc:
            logger.error("TTS engine unavailable: %s", exc)
            return None

        try:
            # Use pyttsx3's save-to-file then read back.
            # pyttsx3 doesn't have a direct "speak to bytes" API,
            # so we save to a temporary buffer.
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as tmp:
                tmp_path = tmp.name

            try:
                engine.save_to_file(request.text, tmp_path)
                engine.runAndWait()

                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()

                return audio_bytes if audio_bytes else None
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        except Exception as exc:
            logger.error("TTS synthesis failed: %s", exc)
            return None

    def speak(self, text: str) -> SpeechResult:
        """Speak text directly through the OS audio output.

        Args:
            text: The text to speak.

        Returns:
            A SpeechResult indicating success or failure.
        """
        if not text or not text.strip():
            return SpeechResult(success=False, error="No text to speak.")

        try:
            engine = self._ensure_engine()
        except RuntimeError as exc:
            return SpeechResult(success=False, error=str(exc))

        try:
            engine.say(text)
            engine.runAndWait()
            return SpeechResult(success=True)
        except Exception as exc:
            logger.error("TTS speak failed: %s", exc)
            return SpeechResult(success=False, error=f"TTS failed: {exc}")

    def list_voices(self) -> list[dict[str, str]]:
        """List available voices on this system.

        Returns:
            A list of dicts with 'id' and 'name' keys.
        """
        try:
            engine = self._ensure_engine()
            voices = engine.getProperty("voices")
            return [{"id": v.id, "name": v.name} for v in voices]
        except Exception as exc:
            logger.error("Failed to list voices: %s", exc)
            return []
