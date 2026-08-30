"""
test_voice_pipeline.py

Unit tests for the Jarvis voice pipeline.

Covers:
    - VoiceConfig, VoiceEvent, PipelineTranscriptionResult, TTSRequest models
    - VoicePipeline state machine (start, stop, status)
    - PipelineTranscriptionResult parsing and construction
    - WakeWordDetector availability checking
    - WhisperSpeechToText availability checking
    - Pyttsx3TextToSpeech availability checking
    - VoiceControlTool operations
    - Pipeline process_utterance with mocked engines

Run with:
    pytest tests/unit/test_voice_pipeline.py
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from voice.models import (
    PipelineState,
    PipelineTranscriptionResult,
    TTSRequest,
    VoiceConfig,
    VoiceEvent,
)
from voice.pipeline import VoicePipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def config():
    """Default VoiceConfig for testing."""
    return VoiceConfig()


@pytest.fixture()
def mock_orchestrator():
    """Mock orchestrator that returns a fixed response."""
    mock = MagicMock()
    response = MagicMock()
    response.message = "Hello from Jarvis!"
    mock.handle_request.return_value = response
    return mock


@pytest.fixture()
def mock_stt():
    """Mock STT engine."""
    mock = MagicMock()
    mock.transcribe.return_value = PipelineTranscriptionResult(
        success=True, text="hello jarvis", confidence=0.95, language="en"
    )
    return mock


@pytest.fixture()
def mock_tts():
    """Mock TTS engine."""
    from voice.tts import SpeechResult

    mock = MagicMock()
    mock.speak.return_value = SpeechResult(success=True)
    return mock


@pytest.fixture()
def pipeline(mock_orchestrator, mock_stt, mock_tts, config):
    """VoicePipeline with mocked dependencies."""
    return VoicePipeline(
        config=config,
        orchestrator=mock_orchestrator,
        stt_engine=mock_stt,
        tts_engine=mock_tts,
    )


# ---------------------------------------------------------------------------
# VoiceConfig tests
# ---------------------------------------------------------------------------


class TestVoiceConfig:
    """Tests for VoiceConfig model."""

    def test_defaults(self):
        """Default config has sensible values."""
        config = VoiceConfig()
        assert config.wake_word == "jarvis"
        assert config.stt_provider == "whisper"
        assert config.tts_provider == "pyttsx3"
        assert config.language == "en"
        assert config.wake_word_sensitivity == 0.5
        assert config.continuous is True
        assert config.stt_model_size == "base"
        assert config.tts_voice is None
        assert config.tts_speed == 1.0
        assert config.max_recording_seconds == 30

    def test_custom_values(self):
        """Config accepts custom values."""
        config = VoiceConfig(
            wake_word="hey jarvis",
            stt_provider="fake",
            tts_provider="fake",
            language="fr",
            wake_word_sensitivity=0.8,
            continuous=False,
        )
        assert config.wake_word == "hey jarvis"
        assert config.stt_provider == "fake"
        assert config.language == "fr"
        assert config.continuous is False

    def test_to_dict(self, config):
        """to_dict produces expected keys."""
        d = config.to_dict()
        assert "wake_word" in d
        assert "stt_provider" in d
        assert "tts_provider" in d
        assert "language" in d
        assert "continuous" in d
        assert d["wake_word"] == "jarvis"

    def test_frozen(self, config):
        """Config is frozen (immutable)."""
        with pytest.raises(AttributeError):
            config.wake_word = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# VoiceEvent tests
# ---------------------------------------------------------------------------


class TestVoiceEvent:
    """Tests for VoiceEvent enum."""

    def test_all_events_exist(self):
        """All expected events are defined."""
        expected = {
            "wake_word_detected",
            "listening",
            "transcribing",
            "speaking",
            "idle",
            "error",
            "pipeline_started",
            "pipeline_stopped",
        }
        actual = {e.value for e in VoiceEvent}
        assert expected == actual

    def test_event_is_string(self):
        """Events can be used as strings."""
        assert VoiceEvent.IDLE == "idle"
        assert VoiceEvent.ERROR == "error"


# ---------------------------------------------------------------------------
# PipelineTranscriptionResult tests
# ---------------------------------------------------------------------------


class TestPipelineTranscriptionResult:
    """Tests for PipelineTranscriptionResult model."""

    def test_success_result(self):
        """Successful result has text and optional fields."""
        result = PipelineTranscriptionResult(
            success=True,
            text="hello world",
            confidence=0.9,
            language="en",
            duration_ms=5000,
        )
        assert result.success is True
        assert result.text == "hello world"
        assert result.confidence == 0.9
        assert result.language == "en"
        assert result.duration_ms == 5000
        assert result.error is None

    def test_failure_result(self):
        """Failed result has error and empty text."""
        result = PipelineTranscriptionResult(
            success=False,
            error="No speech detected.",
        )
        assert result.success is False
        assert result.text == ""
        assert result.error == "No speech detected."

    def test_minimal_result(self):
        """Minimal result has just success flag."""
        result = PipelineTranscriptionResult(success=True)
        assert result.success is True
        assert result.text == ""
        assert result.confidence is None


# ---------------------------------------------------------------------------
# TTSRequest tests
# ---------------------------------------------------------------------------


class TestTTSRequest:
    """Tests for TTSRequest model."""

    def test_defaults(self):
        """Default request has sensible values."""
        req = TTSRequest(text="hello")
        assert req.text == "hello"
        assert req.voice is None
        assert req.speed == 1.0
        assert req.output_format == "wav"

    def test_custom_values(self):
        """Custom request values are preserved."""
        req = TTSRequest(
            text="hello",
            voice="en-US-AriaNeural",
            speed=1.5,
            output_format="mp3",
        )
        assert req.voice == "en-US-AriaNeural"
        assert req.speed == 1.5
        assert req.output_format == "mp3"


# ---------------------------------------------------------------------------
# PipelineState tests
# ---------------------------------------------------------------------------


class TestPipelineState:
    """Tests for PipelineState."""

    def test_initial_state(self):
        """Initial state is idle with no interactions."""
        state = PipelineState()
        assert state.current_event == VoiceEvent.IDLE
        assert state.last_transcription is None
        assert state.total_interactions == 0
        assert state.errors == []

    def test_record_error(self):
        """Recording an error updates event and error list."""
        state = PipelineState()
        state.record_error("Something went wrong")
        assert state.current_event == VoiceEvent.ERROR
        assert len(state.errors) == 1
        assert "Something went wrong" in state.errors[0]

    def test_error_limit(self):
        """Error list is capped at 20 entries."""
        state = PipelineState()
        for i in range(25):
            state.record_error(f"Error {i}")
        assert len(state.errors) == 20
        assert "Error 24" in state.errors[-1]


# ---------------------------------------------------------------------------
# VoicePipeline tests
# ---------------------------------------------------------------------------


class TestVoicePipeline:
    """Tests for VoicePipeline state machine and orchestration."""

    def test_initial_status(self, pipeline):
        """Pipeline starts in a clean state."""
        status = pipeline.get_status()
        assert status["is_running"] is False
        assert status["current_event"] == "idle"
        assert status["total_interactions"] == 0
        assert status["config"]["wake_word"] == "jarvis"

    def test_start_and_stop(self, pipeline):
        """Pipeline can be started and stopped."""
        pipeline.start()
        assert pipeline.is_running is True

        pipeline.stop()
        assert pipeline.is_running is False

    def test_double_start_raises(self, pipeline):
        """Starting an already-running pipeline raises."""
        pipeline.start()
        with pytest.raises(RuntimeError, match="already running"):
            pipeline.start()
        pipeline.stop()

    def test_stop_when_not_running(self, pipeline):
        """Stopping a non-running pipeline is a no-op."""
        pipeline.stop()  # Should not raise
        assert pipeline.is_running is False

    def test_process_utterance(self, pipeline, mock_stt, mock_orchestrator):
        """process_utterance chains transcribe → handle → speak."""
        result = pipeline.process_utterance(audio=b"fake_audio")

        assert result.success is True
        assert result.text == "hello jarvis"
        mock_stt.transcribe.assert_called_once_with(b"fake_audio")
        mock_orchestrator.handle_request.assert_called_once_with("hello jarvis")
        assert pipeline.state.total_interactions == 1

    def test_process_utterance_stt_failure(self, pipeline, mock_stt):
        """STT failure is handled gracefully."""
        mock_stt.transcribe.return_value = PipelineTranscriptionResult(
            success=False, error="Transcription failed."
        )

        result = pipeline.process_utterance(audio=b"bad_audio")
        assert result.success is False
        assert "Transcription failed" in result.error
        assert pipeline.state.total_interactions == 0
        assert len(pipeline.state.errors) > 0

    def test_process_utterance_no_stt(self):
        """Pipeline without STT engine fails gracefully."""
        pipeline = VoicePipeline(stt_engine=None)
        result = pipeline.process_utterance(audio=b"audio")
        assert result.success is False
        assert "No STT engine" in result.error

    def test_process_utterance_no_audio(self, pipeline):
        """No audio recorded is handled gracefully."""
        pipeline._record_audio = MagicMock(return_value=None)
        result = pipeline.process_utterance(audio=None)
        # With no audio captured, pipeline reports an error.
        assert result.success is False
        assert "No audio" in result.error

    def test_event_callback(self, mock_orchestrator, mock_stt, mock_tts):
        """Event callback is called during pipeline events."""
        events = []

        def on_event(event, state):
            events.append(event)

        pipeline = VoicePipeline(
            orchestrator=mock_orchestrator,
            stt_engine=mock_stt,
            tts_engine=mock_tts,
            on_event=on_event,
        )

        pipeline.process_utterance(audio=b"audio")

        assert VoiceEvent.TRANSCRIBING in events
        assert VoiceEvent.SPEAKING in events
        assert VoiceEvent.IDLE in events

    def test_event_callback_exception_is_swallowed(self, mock_orchestrator, mock_stt, mock_tts):
        """Exceptions in event callbacks don't break the pipeline."""
        def bad_callback(event, state):
            raise RuntimeError("Callback broke!")

        pipeline = VoicePipeline(
            orchestrator=mock_orchestrator,
            stt_engine=mock_stt,
            tts_engine=mock_tts,
            on_event=bad_callback,
        )

        # Should not raise
        result = pipeline.process_utterance(audio=b"audio")
        assert result.success is True

    def test_orchestrator_exception(self, pipeline, mock_orchestrator):
        """Orchestrator exceptions are handled gracefully."""
        mock_orchestrator.handle_request.side_effect = RuntimeError("Boom!")

        result = pipeline.process_utterance(audio=b"audio")
        assert result.success is True  # Transcription succeeded
        assert pipeline.state.total_interactions == 1

    def test_tts_failure(self, pipeline, mock_tts):
        """TTS failure is handled gracefully."""
        from voice.tts import SpeechResult

        mock_tts.speak.return_value = SpeechResult(
            success=False, error="TTS broke"
        )

        result = pipeline.process_utterance(audio=b"audio")
        assert result.success is True  # Transcription still succeeded


# ---------------------------------------------------------------------------
# WakeWordDetector tests
# ---------------------------------------------------------------------------


class TestWakeWordDetector:
    """Tests for WakeWordDetector (availability and configuration)."""

    def test_default_config(self):
        """Default wake word is 'jarvis'."""
        from voice.wake_word import WakeWordDetector

        detector = WakeWordDetector()
        assert detector.wake_word == "jarvis"
        assert detector.sensitivity == 0.5
        assert detector.is_listening is False

    def test_custom_config(self):
        """Custom wake word and sensitivity."""
        from voice.wake_word import WakeWordDetector

        detector = WakeWordDetector(wake_word="hey computer", sensitivity=0.8)
        assert detector.wake_word == "hey computer"
        assert detector.sensitivity == 0.8

    def test_sensitivity_clamped(self):
        """Sensitivity is clamped to 0.0-1.0."""
        from voice.wake_word import WakeWordDetector

        assert WakeWordDetector(sensitivity=-0.5).sensitivity == 0.0
        assert WakeWordDetector(sensitivity=1.5).sensitivity == 1.0

    def test_stop_when_not_running(self):
        """Stop when not running is safe."""
        from voice.wake_word import WakeWordDetector

        detector = WakeWordDetector()
        detector.stop_listening()  # Should not raise

    def test_double_start_raises(self):
        """Starting twice raises RuntimeError."""
        from voice.wake_word import WakeWordDetector

        detector = WakeWordDetector()
        # Mock the availability check so it doesn't try to import.
        detector._available = True
        detector.is_running = True
        with pytest.raises(RuntimeError, match="already running"):
            detector.start_listening(lambda: None)


# ---------------------------------------------------------------------------
# WhisperSpeechToText tests
# ---------------------------------------------------------------------------


class TestWhisperSpeechToText:
    """Tests for WhisperSpeechToText (availability and configuration)."""

    def test_default_config(self):
        """Default model size is 'base'."""
        from voice.whisper_stt import WhisperSpeechToText

        stt = WhisperSpeechToText()
        assert stt.model_size == "base"
        assert stt.language == "en"
        assert stt._model is None

    def test_custom_config(self):
        """Custom model size and language."""
        from voice.whisper_stt import WhisperSpeechToText

        stt = WhisperSpeechToText(model_size="small", language="fr")
        assert stt.model_size == "small"
        assert stt.language == "fr"


# ---------------------------------------------------------------------------
# Pyttsx3TextToSpeech tests
# ---------------------------------------------------------------------------


class TestPyttsx3TextToSpeech:
    """Tests for Pyttsx3TextToSpeech (configuration)."""

    def test_default_config(self):
        """Default config uses OS defaults."""
        from voice.pyttsx3_tts import Pyttsx3TextToSpeech

        tts = Pyttsx3TextToSpeech()
        assert tts.voice is None
        assert tts.speed == 1.0

    def test_custom_config(self):
        """Custom voice and speed."""
        from voice.pyttsx3_tts import Pyttsx3TextToSpeech

        tts = Pyttsx3TextToSpeech(voice="en-US", speed=1.5)
        assert tts.voice == "en-US"
        assert tts.speed == 1.5

    def test_speed_clamped(self):
        """Speed is clamped to 0.1-5.0."""
        from voice.pyttsx3_tts import Pyttsx3TextToSpeech

        assert Pyttsx3TextToSpeech(speed=0.0).speed == 0.1
        assert Pyttsx3TextToSpeech(speed=10.0).speed == 5.0


# ---------------------------------------------------------------------------
# VoiceControlTool tests
# ---------------------------------------------------------------------------


class TestVoiceControlTool:
    """Tests for VoiceControlTool."""

    def _make_tool(self, pipeline=None):
        from tools.builtin.voice_control_tool import VoiceControlTool
        return VoiceControlTool(pipeline=pipeline)

    def test_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "voice_control"
        assert "voice" in tool.description.lower()

    def test_status_no_pipeline(self):
        tool = self._make_tool()
        from tools.base_tool import ToolRequest
        result = tool.run(ToolRequest(tool_name="voice_control", input_data={}))
        assert result.success is True
        assert "not configured" in result.output

    def test_status_with_pipeline(self, pipeline):
        tool = self._make_tool(pipeline)
        from tools.base_tool import ToolRequest
        result = tool.run(ToolRequest(tool_name="voice_control", input_data={}))
        assert result.success is True
        assert "Running: False" in result.output

    def test_start_pipeline(self, pipeline):
        tool = self._make_tool(pipeline)
        from tools.base_tool import ToolRequest
        result = tool.run(ToolRequest(
            tool_name="voice_control",
            input_data={"action": "start"},
        ))
        assert result.success is True
        assert "started" in result.output.lower()
        pipeline.stop()  # Clean up

    def test_stop_pipeline(self, pipeline):
        tool = self._make_tool(pipeline)
        from tools.base_tool import ToolRequest
        pipeline.start()
        result = tool.run(ToolRequest(
            tool_name="voice_control",
            input_data={"action": "stop"},
        ))
        assert result.success is True
        assert "stopped" in result.output.lower()

    def test_change_wake_word(self, pipeline):
        tool = self._make_tool(pipeline)
        from tools.base_tool import ToolRequest
        result = tool.run(ToolRequest(
            tool_name="voice_control",
            input_data={"action": "wake_word", "wake_word": "hey jarvis"},
        ))
        assert result.success is True
        assert "hey jarvis" in result.output
        assert pipeline.config.wake_word == "hey jarvis"

    def test_change_wake_word_empty(self, pipeline):
        tool = self._make_tool(pipeline)
        from tools.base_tool import ToolRequest
        result = tool.run(ToolRequest(
            tool_name="voice_control",
            input_data={"action": "wake_word", "wake_word": ""},
        ))
        assert result.success is False

    def test_unknown_action(self):
        tool = self._make_tool()
        from tools.base_tool import ToolRequest
        result = tool.run(ToolRequest(
            tool_name="voice_control",
            input_data={"action": "bogus"},
        ))
        assert result.success is False
        assert "Unknown action" in result.error


# ---------------------------------------------------------------------------
# Settings integration tests
# ---------------------------------------------------------------------------


class TestVoiceSettings:
    """Tests for voice-related settings in config/settings.py."""

    def test_settings_has_wake_word(self):
        """Settings dataclass has wake_word field."""
        from config.settings import Settings
        assert hasattr(Settings, "wake_word")

    def test_settings_has_stt_provider(self):
        """Settings dataclass has stt_provider field."""
        from config.settings import Settings
        assert hasattr(Settings, "stt_provider")

    def test_settings_has_tts_provider(self):
        """Settings dataclass has tts_provider field."""
        from config.settings import Settings
        assert hasattr(Settings, "tts_provider")

    def test_settings_has_voice_language(self):
        """Settings dataclass has voice_language field."""
        from config.settings import Settings
        assert hasattr(Settings, "voice_language")
