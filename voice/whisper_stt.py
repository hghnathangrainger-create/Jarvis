"""
whisper_stt.py

Speech-to-text implementation using faster-whisper for the Jarvis
voice pipeline.

Responsibilities:
    - Transcribe audio bytes or file paths using faster-whisper
      (local, no API key needed).
    - Load the Whisper model lazily (on first use, not at import).
    - Return transcription results with text, confidence, and language.

Does NOT:
    - Capture audio (see wake_word.py or pipeline.py).
    - Synthesise speech (see tts.py).
    - Orchestrate the full pipeline (see pipeline.py).

Requires: pip install faster-whisper
"""

from __future__ import annotations

import io
import logging
import tempfile
from pathlib import Path

from voice.models import PipelineTranscriptionResult

logger = logging.getLogger(__name__)


class WhisperSpeechToText:
    """Speech-to-text using faster-whisper (local, no API needed).

    The Whisper model is loaded lazily on the first call to transcribe().
    This avoids importing large ML libraries at module load time.

    Attributes:
        model_size: The Whisper model size to load.
        language: BCP-47 language code for transcription.
        _model: The loaded faster-whisper model (None until first use).
    """

    def __init__(
        self,
        model_size: str = "base",
        language: str = "en",
    ) -> None:
        """Initialise the STT engine.

        Args:
            model_size: Whisper model size — "tiny", "base", "small",
                "medium", or "large". Smaller models are faster but
                less accurate.
            language: BCP-47 language code (e.g. "en", "fr", "de").
        """
        self.model_size = model_size
        self.language = language
        self._model = None

    @property
    def available(self) -> bool:
        """Whether faster-whisper is installed."""
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    def _ensure_model(self) -> None:
        """Load the Whisper model if not already loaded."""
        if self._model is not None:
            return

        if not self.available:
            raise RuntimeError(
                "faster-whisper is not installed. "
                "Install it with: pip install faster-whisper"
            )

        logger.info("Loading Whisper model '%s'...", self.model_size)
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            logger.info("Whisper model '%s' loaded.", self.model_size)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load Whisper model '{self.model_size}': {exc}"
            ) from exc

    def transcribe(
        self,
        audio: str | Path | bytes,
    ) -> PipelineTranscriptionResult:
        """Transcribe audio to text.

        Args:
            audio: Audio input — either a file path (str or Path) or
                raw audio bytes (WAV format expected).

        Returns:
            A PipelineTranscriptionResult with the transcription.
        """
        try:
            self._ensure_model()
        except RuntimeError as exc:
            return PipelineTranscriptionResult(
                success=False, error=str(exc)
            )

        # If bytes, write to a temporary file for faster-whisper.
        temp_file = None
        try:
            if isinstance(audio, bytes):
                temp_file = tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False
                )
                temp_file.write(audio)
                temp_file.close()
                audio_path = temp_file.name
            elif isinstance(audio, (str, Path)):
                audio_path = str(audio)
            else:
                return PipelineTranscriptionResult(
                    success=False,
                    error=f"Unsupported audio type: {type(audio).__name__}",
                )

            # Transcribe with faster-whisper.
            segments, info = self._model.transcribe(
                audio_path,
                language=self.language,
                beam_size=5,
                vad_filter=True,
            )

            # Collect all segments into a single text.
            texts = []
            total_duration_ms = 0
            for segment in segments:
                texts.append(segment.text.strip())
                total_duration_ms = int(segment.end * 1000)

            full_text = " ".join(texts).strip()

            if not full_text:
                return PipelineTranscriptionResult(
                    success=False,
                    error="No speech detected in audio.",
                    duration_ms=total_duration_ms,
                )

            # Extract confidence if available from segments.
            confidence = None
            if info.language_probability is not None:
                confidence = float(info.language_probability)

            detected_language = info.language if info.language else None

            return PipelineTranscriptionResult(
                success=True,
                text=full_text,
                confidence=confidence,
                language=detected_language,
                duration_ms=total_duration_ms,
            )

        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            return PipelineTranscriptionResult(
                success=False, error=f"Transcription failed: {exc}"
            )
        finally:
            # Clean up temporary file.
            if temp_file is not None:
                try:
                    Path(temp_file.name).unlink(missing_ok=True)
                except Exception:
                    pass
