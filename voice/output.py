"""
output.py

Voice output service for Jarvis's text-to-speech foundation (Phase 41,
Batch 1).

Responsibilities:
    - Wrap a single TextToSpeechProvider (voice/tts.py) and decide
      whether a given call to speak() should actually reach it - a
      disabled service, or one with no provider, is always a safe
      no-op.
    - Guard against empty/whitespace-only text and unreasonably long
      text before ever calling the provider.
    - Never let a provider failure raise into the caller - every
      outcome, success or failure, is reported as a SpeechResult.

Does NOT:
    - Decide *when* Jarvis should speak a response, or make Jarvis speak
      automatically in normal use. That is a future, separate
      integration decision (later Phase 41 batches, per
      docs/phase_41_implementation_plan.md) - this service only speaks
      the exact text it is given, when explicitly called, and only when
      enabled.
    - Access a microphone or implement any speech-to-text behaviour.
    - Interpret, execute, route, or classify the text it is given in any
      way. Text handed to speak() is always treated as data to
      vocalise, never as a command - this service never imports
      CommandRouter, ToolExecutor, ApprovalManager, or any AI component,
      and holds no reference to any of them.
    - Call any AI provider, tool, or approval component. It cannot
      mutate a file, a memory, a schedule, an Inbox entry, a workflow,
      or anything shown on the dashboard - it has no dependency on any
      of those modules at all.
    - Produce real audio itself - that is the provider's job (today,
      only FakeTextToSpeechProvider exists; no real engine is wired in
      yet).
    - Change Jarvis's default runtime behaviour. Nothing in main.py or
      ui/cli.py constructs or calls this service yet - it exists only to
      be tested directly and wired in later, once Nathan has chosen a
      real provider and opted in.

Safety design:
    The single most important property of this class is that it
    *cannot act* on the text it is given - it can only ask a provider to
    vocalise it, or safely decline to. This mirrors
    ai/reasoning_engine.py's own established "cannot execute anything"
    design precisely.
"""

from __future__ import annotations

from voice.tts import SpeechResult, TextToSpeechProvider

#: The maximum number of characters this service will ever hand to a
#: provider in one call. Text longer than this is truncated before
#: speaking, never silently spoken in full - a defensive guard against
#: accidentally trying to "speak" an entire file dump or memory listing.
#: A starting, adjustable default, not a precisely researched figure.
_MAX_SPEAKABLE_CHARS = 2000


class VoiceOutputService:
    """Wraps a TextToSpeechProvider, deciding whether/how to call it.

    Attributes:
        enabled: Whether this service will actually call its provider.
            Defaults to False (opt-in) - matching
            AIReasoningEngine.enabled's own established default in this
            codebase.
    """

    def __init__(
        self,
        *,
        provider: TextToSpeechProvider | None = None,
        enabled: bool = False,
    ) -> None:
        """Initialise the service.

        Args:
            provider: The TextToSpeechProvider to speak through.
                Defaults to None, in which case speak() always returns
                a safe, inactive failure result, regardless of enabled.
            enabled: Whether this service is switched on. Defaults to
                False (opt-in), matching AIReasoningEngine's own
                default.
        """
        self._provider = provider
        self.enabled = enabled

    def is_active(self) -> bool:
        """Report whether speak() will actually reach the provider.

        Returns:
            True only when this service is enabled and a provider was
            supplied.
        """
        return self.enabled and self._provider is not None

    def speak(self, text: str) -> SpeechResult:
        """Speak the given text, if this service is active.

        Args:
            text: The text to speak. Treated as plain data only - never
                interpreted, executed, or routed anywhere.

        Returns:
            A SpeechResult. Never raises: a disabled service, a missing
            provider, empty/whitespace-only text, and any provider
            failure (including an unexpected exception) all produce a
            failed SpeechResult rather than propagating an error, so a
            future caller's normal text output is never at risk of
            breaking because of a voice failure.
        """
        if not self.is_active():
            return SpeechResult(success=False, error="Voice output is disabled.")

        if not isinstance(text, str) or not text.strip():
            return SpeechResult(success=False, error="No text to speak.")

        speakable = text
        truncated = False
        if len(speakable) > _MAX_SPEAKABLE_CHARS:
            speakable = speakable[:_MAX_SPEAKABLE_CHARS]
            truncated = True

        try:
            result = self._provider.speak(speakable)
        except Exception as exc:  # noqa: BLE001 - isolate any provider failure
            return SpeechResult(success=False, error=f"Voice provider failed: {exc}")

        if truncated and result.success:
            return SpeechResult(success=True, truncated=True)
        return result
