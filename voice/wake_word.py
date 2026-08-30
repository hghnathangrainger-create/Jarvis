"""
wake_word.py

Wake word detection for the Jarvis voice pipeline.

Responsibilities:
    - Detect a configured wake word ("Jarvis" by default) from microphone
      audio using OpenWakeWord.
    - Run detection in a background thread.
    - Fire a callback when the wake word is detected.
    - Gracefully handle missing audio device or missing library.

Does NOT:
    - Transcribe speech (see stt.py).
    - Synthesise speech (see tts.py).
    - Orchestrate the full pipeline (see pipeline.py).

OpenWakeWord must be installed: pip install openwakeword
sounddevice and numpy are required for microphone access.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Detects a wake word from microphone audio in a background thread.

    Uses OpenWakeWord for detection. The detector runs a continuous
    audio capture loop in a daemon thread and fires a callback when
    the configured wake word exceeds the sensitivity threshold.

    Attributes:
        wake_word: The wake word phrase to detect.
        sensitivity: Detection threshold (0.0-1.0).
        is_running: Whether the detector is currently listening.
    """

    def __init__(
        self,
        wake_word: str = "jarvis",
        sensitivity: float = 0.5,
    ) -> None:
        """Initialise the wake word detector.

        Args:
            wake_word: The wake word phrase (case-insensitive).
            sensitivity: Detection threshold (0.0-1.0). Higher means
                more strict / fewer false positives.
        """
        self.wake_word = wake_word.lower().strip()
        self.sensitivity = max(0.0, min(1.0, sensitivity))
        self._callback: Callable[[], None] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.is_running = False
        self._model = None
        self._available = False

    @property
    def is_listening(self) -> bool:
        """Whether the detector is actively listening for the wake word."""
        return self.is_running

    @property
    def available(self) -> bool:
        """Whether the required libraries are installed."""
        if self._available:
            return True
        try:
            import openwakeword  # noqa: F401
            import sounddevice  # noqa: F401
            import numpy  # noqa: F401
            self._available = True
            return True
        except ImportError:
            return False

    def start_listening(self, callback: Callable[[], None]) -> None:
        """Start listening for the wake word in a background thread.

        Args:
            callback: Function to call when the wake word is detected.
                Called from the background thread — callers should
                handle thread safety.

        Raises:
            RuntimeError: If already listening.
        """
        if self.is_running:
            raise RuntimeError("Wake word detector is already running.")

        if not self.available:
            logger.warning(
                "Wake word detection unavailable: required libraries "
                "(openwakeword, sounddevice, numpy) not installed."
            )
            return

        self._callback = callback
        self._stop_event.clear()
        self.is_running = True

        self._thread = threading.Thread(
            target=self._listen_loop,
            name="wake-word-detector",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Wake word detector started: '%s' (sensitivity=%.2f)",
            self.wake_word,
            self.sensitivity,
        )

    def stop_listening(self) -> None:
        """Stop the wake word detector.

        Signals the background thread to stop and waits for it to finish.
        Safe to call multiple times or when not running.
        """
        if not self.is_running:
            return

        self._stop_event.set()
        self.is_running = False

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._thread = None
        self._callback = None
        logger.info("Wake word detector stopped.")

    def _listen_loop(self) -> None:
        """Background thread: capture audio and check for wake word."""
        try:
            import numpy as np
            import sounddevice as sd
            import openwakeword
        except ImportError as exc:
            logger.error("Failed to import wake word libraries: %s", exc)
            self.is_running = False
            return

        try:
            # Load the default OpenWakeWord model.
            openwakeword.utils.download_models()
            self._model = openwakeword.ModelMultipleWakeword(
                wakeword_models=[],
                inference_framework="onnx",
            )
        except Exception as exc:
            logger.error("Failed to load wake word model: %s", exc)
            self.is_running = False
            return

        # Audio capture parameters.
        sample_rate = 16000
        chunk_duration_ms = 1280  # OpenWakeWord expects 1280ms chunks
        chunk_samples = int(sample_rate * chunk_duration_ms / 1000)

        try:
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                blocksize=chunk_samples,
            ) as stream:
                while not self._stop_event.is_set():
                    try:
                        audio_data, overflowed = stream.read(chunk_samples)
                        if overflowed:
                            logger.debug("Audio buffer overflowed.")

                        # Convert to numpy array for the model.
                        audio_np = np.frombuffer(audio_data, dtype=np.int16)

                        # Run wake word detection.
                        self._model.predict(audio_np)

                        # Check prediction scores.
                        for (
                            wakeword_name,
                            score,
                        ) in self._model.get_scores().items():
                            if score >= self.sensitivity:
                                logger.info(
                                    "Wake word '%s' detected (score=%.3f)",
                                    wakeword_name,
                                    score,
                                )
                                if self._callback is not None:
                                    self._callback()
                                # Brief cooldown after detection.
                                self._stop_event.wait(timeout=2.0)
                                break

                    except Exception as exc:
                        logger.debug("Audio processing error: %s", exc)
                        continue

        except OSError as exc:
            logger.error(
                "Audio device error — wake word detection stopped: %s", exc
            )
        except Exception as exc:
            logger.error("Wake word listener error: %s", exc)
        finally:
            self.is_running = False
            if self._model is not None:
                try:
                    self._model.reset()
                except Exception:
                    pass
