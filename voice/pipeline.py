"""
pipeline.py

The main voice pipeline for the Jarvis AI Operating System.

Responsibilities:
    - Chain: wake word detection → audio recording → transcription →
      orchestrator handling → TTS response → speaking.
    - Support both continuous mode (always listening after wake word)
      and one-shot mode (single interaction then stop).
    - Manage pipeline state and emit VoiceEvents for observability.
    - Gracefully handle missing audio device or library.

Does NOT:
    - Modify the orchestrator's core logic — calls
      orchestrator.handle_request() exactly like the CLI does.
    - Implement wake word detection (see wake_word.py).
    - Implement STT or TTS engines (see whisper_stt.py, pyttsx3_tts.py).
    - Access files, memory, or any subsystem directly.

The pipeline is the single entry point for voice-driven interaction.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from voice.models import (
    PipelineState,
    PipelineTranscriptionResult,
    TTSRequest,
    VoiceConfig,
    VoiceEvent,
)
from voice.tts import SpeechResult
from voice.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


class VoicePipeline:
    """Chains wake word → listen → transcribe → respond → speak.

    The pipeline runs in a background thread (when started) and
    interacts with Jarvis through the same orchestrator.handle_request()
    interface the text CLI uses.

    Attributes:
        config: The pipeline configuration.
        state: Mutable pipeline state for observability.
        is_running: Whether the pipeline is currently active.
    """

    def __init__(
        self,
        *,
        config: VoiceConfig | None = None,
        orchestrator: Any = None,
        stt_engine: Any = None,
        tts_engine: Any = None,
        on_event: Callable[[VoiceEvent, PipelineState], None] | None = None,
    ) -> None:
        """Initialise the voice pipeline.

        Args:
            config: Pipeline configuration. Defaults to VoiceConfig().
            orchestrator: The JarvisOrchestrator to handle requests.
                Must implement handle_request(text) -> JarvisResponse.
            stt_engine: Speech-to-text engine with a transcribe(audio)
                method. Can be WhisperSpeechToText or any compatible.
            tts_engine: Text-to-speech engine with a speak(text) method.
                Can be Pyttsx3TextToSpeech or any compatible.
            on_event: Optional callback for pipeline events (for
                observability/UI updates).
        """
        self.config = config or VoiceConfig()
        self.orchestrator = orchestrator
        self.stt_engine = stt_engine
        self.tts_engine = tts_engine
        self.on_event = on_event
        self.state = PipelineState()
        self.is_running = False

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_detector: WakeWordDetector | None = None

    def start(self) -> None:
        """Start the voice pipeline in a background thread.

        Raises:
            RuntimeError: If the pipeline is already running.
        """
        if self.is_running:
            raise RuntimeError("Voice pipeline is already running.")

        self._stop_event.clear()
        self.is_running = True
        self._emit(VoiceEvent.PIPELINE_STARTED)

        self._thread = threading.Thread(
            target=self._run_loop,
            name="voice-pipeline",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Voice pipeline started (mode=%s, wake_word='%s')",
            "continuous" if self.config.continuous else "one-shot",
            self.config.wake_word,
        )

    def stop(self) -> None:
        """Stop the voice pipeline.

        Safe to call multiple times or when not running.
        """
        if not self.is_running:
            return

        self._stop_event.set()
        self.is_running = False

        # Stop the wake word detector if running.
        if self._wake_detector is not None:
            self._wake_detector.stop_listening()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._thread = None
        self._emit(VoiceEvent.PIPELINE_STOPPED)
        logger.info("Voice pipeline stopped.")

    def process_utterance(
        self, audio: Any = None
    ) -> PipelineTranscriptionResult:
        """Process a single utterance: record → transcribe → respond → speak.

        This is the core pipeline step, also callable directly for testing
        or one-shot use without the wake word listener.

        Args:
            audio: Optional pre-recorded audio (bytes or file path).
                If None, records from the microphone.

        Returns:
            The transcription result.
        """
        # Step 1: Get audio (record or use provided).
        self._emit(VoiceEvent.LISTENING)
        if audio is None:
            audio = self._record_audio()

        if audio is None:
            result = PipelineTranscriptionResult(
                success=False, error="No audio captured."
            )
            self.state.record_error(result.error)
            self._emit(VoiceEvent.ERROR)
            return result

        # Step 2: Transcribe.
        self._emit(VoiceEvent.TRANSCRIBING)
        transcription = self._transcribe(audio)

        if not transcription.success:
            self.state.record_error(
                transcription.error or "Transcription failed."
            )
            self._emit(VoiceEvent.ERROR)
            return transcription

        logger.info("Transcribed: '%s'", transcription.text)
        self.state.last_transcription = transcription

        # Step 3: Send to orchestrator.
        response_text = self._handle_request(transcription.text)

        # Step 4: Speak the response.
        if response_text:
            self._emit(VoiceEvent.SPEAKING)
            self._speak(response_text)

        self.state.total_interactions += 1
        self._emit(VoiceEvent.IDLE)
        return transcription

    def _run_loop(self) -> None:
        """Main pipeline loop: wake word → interaction → repeat."""
        if self.config.continuous:
            self._run_continuous()
        else:
            self._run_one_shot()

    def _run_continuous(self) -> None:
        """Continuous mode: listen for wake word, then process."""
        # Set up wake word detector.
        self._wake_detector = WakeWordDetector(
            wake_word=self.config.wake_word,
            sensitivity=self.config.wake_word_sensitivity,
        )

        if not self._wake_detector.available:
            logger.warning(
                "Wake word detection unavailable. "
                "Falling back to direct input mode."
            )
            self._run_direct_input()
            return

        # Start wake word detection with a callback.
        wake_event = threading.Event()

        def on_wake() -> None:
            wake_event.set()

        self._wake_detector.start_listening(on_wake)

        try:
            while not self._stop_event.is_set():
                # Wait for wake word or stop signal.
                wake_event.wait(timeout=0.5)
                if self._stop_event.is_set():
                    break

                if wake_event.is_set():
                    wake_event.clear()
                    self._emit(VoiceEvent.WAKE_WORD_DETECTED)
                    self.process_utterance()
        finally:
            if self._wake_detector is not None:
                self._wake_detector.stop_listening()

    def _run_one_shot(self) -> None:
        """One-shot mode: single interaction then stop."""
        self.process_utterance()

    def _run_direct_input(self) -> None:
        """Fallback: prompt for text input when wake word is unavailable."""
        while not self._stop_event.is_set():
            try:
                user_input = input("\n Speak (or 'quit' to stop): ").strip()
                if user_input.lower() in ("quit", "exit", "stop"):
                    break
                if user_input:
                    # Create a fake transcription and process it.
                    transcription = PipelineTranscriptionResult(
                        success=True, text=user_input
                    )
                    self.state.last_transcription = transcription
                    response_text = self._handle_request(user_input)
                    if response_text:
                        self._emit(VoiceEvent.SPEAKING)
                        self._speak(response_text)
                    self.state.total_interactions += 1
            except (EOFError, KeyboardInterrupt):
                break

    def _record_audio(self) -> bytes | None:
        """Record audio from the microphone.

        Returns:
            Audio bytes (WAV format), or None on failure.
        """
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            logger.error(
                "sounddevice/numpy not installed. "
                "Cannot record audio."
            )
            return None

        try:
            sample_rate = 16000
            duration = self.config.max_recording_seconds

            logger.info("Recording for up to %d seconds...", duration)
            audio_data = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
            )
            sd.wait()  # Block until recording is complete.

            # Convert to WAV bytes.
            import wave
            import io

            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data.tobytes())

            return buffer.getvalue()

        except Exception as exc:
            logger.error("Audio recording failed: %s", exc)
            return None

    def _transcribe(
        self, audio: bytes | str
    ) -> PipelineTranscriptionResult:
        """Transcribe audio using the configured STT engine.

        Args:
            audio: Audio bytes or file path.

        Returns:
            The transcription result.
        """
        if self.stt_engine is None:
            return PipelineTranscriptionResult(
                success=False, error="No STT engine configured."
            )

        try:
            return self.stt_engine.transcribe(audio)
        except Exception as exc:
            return PipelineTranscriptionResult(
                success=False, error=f"STT engine error: {exc}"
            )

    def _handle_request(self, text: str) -> str | None:
        """Send transcribed text to the orchestrator and get a response.

        Args:
            text: The user's transcribed request.

        Returns:
            The response text, or None if no response.
        """
        if self.orchestrator is None:
            logger.warning("No orchestrator configured; cannot handle request.")
            return None

        try:
            response = self.orchestrator.handle_request(text)
            # Extract text from the JarvisResponse.
            if hasattr(response, "message"):
                return response.message
            if hasattr(response, "text"):
                return response.text
            return str(response)
        except Exception as exc:
            logger.error("Orchestrator error: %s", exc)
            return f"Sorry, I encountered an error: {exc}"

    def _speak(self, text: str) -> SpeechResult:
        """Speak text using the configured TTS engine.

        Args:
            text: The text to speak.

        Returns:
            The speech result.
        """
        if self.tts_engine is None:
            logger.warning("No TTS engine configured; cannot speak.")
            return SpeechResult(success=False, error="No TTS engine.")

        try:
            return self.tts_engine.speak(text)
        except Exception as exc:
            return SpeechResult(success=False, error=f"TTS error: {exc}")

    def _emit(self, event: VoiceEvent) -> None:
        """Emit a pipeline event.

        Args:
            event: The event to emit.
        """
        self.state.current_event = event
        if self.on_event is not None:
            try:
                self.on_event(event, self.state)
            except Exception:
                pass  # Event callback failure must never break the pipeline.

    def get_status(self) -> dict[str, Any]:
        """Return the current pipeline status.

        Returns:
            A dict with status information.
        """
        return {
            "is_running": self.is_running,
            "current_event": self.state.current_event.value,
            "total_interactions": self.state.total_interactions,
            "last_transcription": (
                self.state.last_transcription.text
                if self.state.last_transcription
                else None
            ),
            "recent_errors": self.state.errors[-5:],
            "config": self.config.to_dict(),
        }
