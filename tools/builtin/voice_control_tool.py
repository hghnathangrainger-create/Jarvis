"""
voice_control_tool.py

A YELLOW tool that controls the Jarvis voice pipeline.

Starts/stops voice mode, changes the wake word, and reports voice
status. YELLOW because it starts/stops the pipeline (modifies runtime
state).

Supported operations (via the 'action' input):
    - "status": Show current voice pipeline status (default).
    - "start": Start the voice pipeline.
    - "stop": Stop the voice pipeline.
    - "wake_word": Change the wake word (requires 'wake_word' param).
"""

from __future__ import annotations

from typing import Any

from tools.base_tool import BaseTool, ToolRequest, ToolResult


class VoiceControlTool(BaseTool):
    """Controls the Jarvis voice pipeline: start, stop, status, configure.

    Attributes:
        _pipeline: The VoicePipeline instance to control, or None.
    """

    def __init__(self, pipeline: Any = None) -> None:
        """Initialise the tool with a voice pipeline.

        Args:
            pipeline: A VoicePipeline instance, or None if voice
                is not configured.
        """
        self._pipeline = pipeline

    @property
    def name(self) -> str:
        return "voice_control"

    @property
    def description(self) -> str:
        return "Control Jarvis voice pipeline: start, stop, status, change wake word."

    def action_for(self, request: ToolRequest) -> str:
        """Voice control modifies runtime state, so always YELLOW."""
        return "voice_control"

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle a voice control request.

        Args:
            request: The request with input_data containing:
                - action (str): "status", "start", "stop", or "wake_word".
                - wake_word (str): New wake word (for wake_word action).

        Returns:
            A ToolResult with status or confirmation.
        """
        action = str(request.input_data.get("action", "status")).strip().lower()

        if action == "status":
            return self._get_status()
        elif action == "start":
            return self._start_pipeline()
        elif action == "stop":
            return self._stop_pipeline()
        elif action == "wake_word":
            return self._change_wake_word(request)
        else:
            return self.fail(
                f"Unknown action '{action}'. Use 'status', 'start', 'stop', or 'wake_word'."
            )

    def _get_status(self) -> ToolResult:
        """Show current voice pipeline status."""
        if self._pipeline is None:
            return self.ok("Voice pipeline is not configured.")

        status = self._pipeline.get_status()
        lines = ["Voice Pipeline Status", "=" * 30, ""]
        lines.append(f"Running: {status['is_running']}")
        lines.append(f"Current event: {status['current_event']}")
        lines.append(f"Total interactions: {status['total_interactions']}")

        if status["last_transcription"]:
            lines.append(f"Last transcription: \"{status['last_transcription']}\"")

        if status["recent_errors"]:
            lines.append("")
            lines.append("Recent errors:")
            for err in status["recent_errors"]:
                lines.append(f"  - {err}")

        lines.append("")
        lines.append("Configuration:")
        config = status["config"]
        lines.append(f"  Wake word: '{config['wake_word']}'")
        lines.append(f"  STT provider: {config['stt_provider']}")
        lines.append(f"  TTS provider: {config['tts_provider']}")
        lines.append(f"  Language: {config['language']}")
        lines.append(f"  Continuous: {config['continuous']}")

        return self.ok("\n".join(lines))

    def _start_pipeline(self) -> ToolResult:
        """Start the voice pipeline."""
        if self._pipeline is None:
            return self.fail("Voice pipeline is not configured.")

        if self._pipeline.is_running:
            return self.ok("Voice pipeline is already running.")

        try:
            self._pipeline.start()
            return self.ok("Voice pipeline started.")
        except Exception as exc:
            return self.fail(f"Failed to start voice pipeline: {exc}")

    def _stop_pipeline(self) -> ToolResult:
        """Stop the voice pipeline."""
        if self._pipeline is None:
            return self.fail("Voice pipeline is not configured.")

        if not self._pipeline.is_running:
            return self.ok("Voice pipeline is not running.")

        self._pipeline.stop()
        return self.ok("Voice pipeline stopped.")

    def _change_wake_word(self, request: ToolRequest) -> ToolResult:
        """Change the wake word."""
        if self._pipeline is None:
            return self.fail("Voice pipeline is not configured.")

        new_wake_word = str(request.input_data.get("wake_word", "")).strip()
        if not new_wake_word:
            return self.fail("No wake word provided. Usage: wake_word='hey jarvis'")

        old_word = self._pipeline.config.wake_word
        # Create a new config with the updated wake word.
        from voice.models import VoiceConfig

        new_config = VoiceConfig(
            wake_word=new_wake_word,
            stt_provider=self._pipeline.config.stt_provider,
            tts_provider=self._pipeline.config.tts_provider,
            language=self._pipeline.config.language,
            wake_word_sensitivity=self._pipeline.config.wake_word_sensitivity,
            continuous=self._pipeline.config.continuous,
            stt_model_size=self._pipeline.config.stt_model_size,
            tts_voice=self._pipeline.config.tts_voice,
            tts_speed=self._pipeline.config.tts_speed,
            max_recording_seconds=self._pipeline.config.max_recording_seconds,
        )
        self._pipeline.config = new_config

        return self.ok(
            f"Wake word changed from '{old_word}' to '{new_wake_word}'. "
            f"Restart the pipeline for changes to take effect."
        )
