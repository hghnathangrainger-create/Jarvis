"""
config_tool.py

A safe, read-only tool that reports Jarvis's current configuration
status (Phase 31; extended Phase 41, Batch 2 with voice output
settings; extended Phase 41, Batch 4 with voice input settings).

ConfigTool is a GREEN tool: it only reads the already-loaded Settings
object (never .env or os.environ directly) and reports its fields back
as plain text. It never mutates configuration, never writes a file,
never uses a subprocess, and never calls AI or the web.

The one secret field, anthropic_api_key, is reported only as "set" or
"not set" - never as a value, a masked/partial value, a length, or a
hash/fingerprint. Every other Settings field is plain, non-secret
configuration and is shown in full - including voice_enabled,
voice_speak_mode, voice_provider, voice_input_enabled, and
voice_input_provider (Phase 41), none of which is a secret: no API key
or credential exists for the fake/local-only voice foundation built so
far.
"""

from __future__ import annotations

from config.settings import Settings
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ConfigTool(BaseTool):
    """Reports Jarvis's current configuration status.

    Read-only and safe; the API key's own value is never included in
    the output under any circumstance.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the tool with the application's already-loaded settings.

        Args:
            settings: The already-loaded Settings object. This tool never
                calls load_settings() itself and never reads .env or
                os.environ directly - it only reads the fields already
                validated and loaded once at startup.
        """
        self._settings = settings

    @property
    def name(self) -> str:
        """Return the tool name.

        Returns:
            The string "config".
        """
        return "config"

    @property
    def description(self) -> str:
        """Return a short description of the tool.

        Returns:
            A one-line description.
        """
        return (
            "Reports Jarvis's current configuration status. Read-only "
            "and safe; never shows the API key's value."
        )

    def action_for(self, request: ToolRequest) -> str:
        """Return a fixed, read-only action string for security classification.

        Always the same fixed phrase, regardless of which grammar alias
        ("show config" or "show settings") was used, so classification
        never varies with user input.

        Args:
            request: The request being handled.

        Returns:
            The fixed string "show configuration", classified GREEN.
        """
        return "show configuration"

    def run(self, request: ToolRequest) -> ToolResult:
        """Return the current configuration status.

        Args:
            request: The request. No input is required.

        Returns:
            A successful ToolResult listing every non-secret Settings
            field in full, and the API key's presence only as
            "set"/"not set" - never its value, a masked form, its
            length, or any hash/fingerprint of it.
        """
        key_status = "set" if self._settings.anthropic_api_key.strip() else "not set"
        lines = (
            "Jarvis configuration:",
            f"  AI model: {self._settings.ai_model}",
            f"  AI max tokens: {self._settings.ai_max_tokens}",
            f"  AI reasoning enabled: {self._settings.ai_reasoning_enabled}",
            f"  Anthropic API key: {key_status}",
            f"  Database path: {self._settings.database_path}",
            f"  Log level: {self._settings.log_level}",
            f"  Approval timeout (seconds): {self._settings.approval_timeout_seconds}",
            f"  Debug mode: {self._settings.debug}",
            f"  Voice enabled: {self._settings.voice_enabled}",
            f"  Voice speak mode: {self._settings.voice_speak_mode}",
            f"  Voice provider: {self._settings.voice_provider}",
            f"  Voice input enabled: {self._settings.voice_input_enabled}",
            f"  Voice input provider: {self._settings.voice_input_provider}",
        )
        return self.ok("\n".join(lines))
