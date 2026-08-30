"""
models.py

Data models for the Jarvis voice pipeline.

Responsibilities:
    - Define VoiceConfig for pipeline configuration.
    - Define PipelineTranscriptionResult with extended transcription info.
    - Define TTSRequest for text-to-speech synthesis parameters.
    - Define VoiceEvent enum for pipeline state transitions.

Does NOT:
    - Implement any voice processing (see pipeline.py, wake_word.py,
      stt.py, tts.py).
    - Access audio devices or the network.

These models are used by the voice pipeline and its components.
They are separate from the existing voice/stt.py TranscriptionResult
and voice/tts.py SpeechResult, which are provider-neutral types used
by the lower-level provider abstraction layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VoiceEvent(str, Enum):
    """Events emitted by the voice pipeline during operation.

    Used for state tracking and observability.
    """

    WAKE_WORD_DETECTED = "wake_word_detected"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    SPEAKING = "speaking"
    IDLE = "idle"
    ERROR = "error"
    PIPELINE_STARTED = "pipeline_started"
    PIPELINE_STOPPED = "pipeline_stopped"


@dataclass(frozen=True, slots=True)
class VoiceConfig:
    """Configuration for the voice pipeline.

    Attributes:
        wake_word: The wake word phrase to listen for (case-insensitive).
        stt_provider: Which STT engine to use ("whisper" or "fake").
        tts_provider: Which TTS engine to use ("pyttsx3" or "fake").
        language: BCP-47 language code for STT (e.g. "en").
        wake_word_sensitivity: Detection threshold (0.0-1.0).
        continuous: If True, keep listening after each interaction.
            If False, one-shot mode: single interaction then stop.
        stt_model_size: Whisper model size ("tiny", "base", "small",
            "medium", "large"). Smaller is faster, less accurate.
        tts_voice: Voice name/ID for TTS (engine-specific).
        tts_speed: Speech rate multiplier (1.0 = normal).
        max_recording_seconds: Maximum seconds to record per utterance.
    """

    wake_word: str = "jarvis"
    stt_provider: str = "whisper"
    tts_provider: str = "pyttsx3"
    language: str = "en"
    wake_word_sensitivity: float = 0.5
    continuous: bool = True
    stt_model_size: str = "base"
    tts_voice: str | None = None
    tts_speed: float = 1.0
    max_recording_seconds: int = 30

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "wake_word": self.wake_word,
            "stt_provider": self.stt_provider,
            "tts_provider": self.tts_provider,
            "language": self.language,
            "wake_word_sensitivity": self.wake_word_sensitivity,
            "continuous": self.continuous,
            "stt_model_size": self.stt_model_size,
            "tts_voice": self.tts_voice,
            "tts_speed": self.tts_speed,
            "max_recording_seconds": self.max_recording_seconds,
        }


@dataclass(frozen=True, slots=True)
class PipelineTranscriptionResult:
    """Extended transcription result with confidence and timing.

    This is the pipeline-level transcription type, carrying more
    information than the lower-level voice/stt.TranscriptionResult.

    Attributes:
        success: Whether transcription produced usable text.
        text: The transcribed text (empty when success is False).
        confidence: Confidence score (0.0-1.0), or None if unavailable.
        language: Detected language code, or None if unavailable.
        duration_ms: Audio duration in milliseconds, or None if unknown.
        error: Human-readable error when success is False.
    """

    success: bool
    text: str = ""
    confidence: float | None = None
    language: str | None = None
    duration_ms: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TTSRequest:
    """Parameters for a text-to-speech synthesis request.

    Attributes:
        text: The text to synthesise.
        voice: Voice name/ID, or None for default.
        speed: Speech rate multiplier (1.0 = normal).
        output_format: Audio format ("wav", "mp3", etc.).
    """

    text: str
    voice: str | None = None
    speed: float = 1.0
    output_format: str = "wav"


@dataclass
class PipelineState:
    """Mutable state tracked by the voice pipeline.

    Attributes:
        current_event: The most recent pipeline event.
        last_transcription: The last successful transcription, if any.
        total_interactions: How many wake→transcribe→respond cycles
            have completed.
        errors: List of recent error messages.
    """

    current_event: VoiceEvent = VoiceEvent.IDLE
    last_transcription: PipelineTranscriptionResult | None = None
    total_interactions: int = 0
    errors: list[str] = field(default_factory=list)

    def record_error(self, message: str) -> None:
        """Record an error and update the event state.

        Args:
            message: A human-readable error description.
        """
        self.current_event = VoiceEvent.ERROR
        self.errors.append(message)
        # Keep only the last 20 errors.
        if len(self.errors) > 20:
            self.errors = self.errors[-20:]
