"""
tts.py

Text-to-speech provider abstraction for Jarvis's voice output foundation
(Phase 41, Batch 1).

Responsibilities:
    - Define TextToSpeechProvider, the abstract interface every concrete
      TTS engine (local, OS-provided, or cloud - see
      docs/phase_41_implementation_plan.md, Section 6) will eventually
      implement.
    - Define SpeechResult, the provider-neutral outcome every provider
      (and VoiceOutputService, in voice/output.py) returns, so the rest
      of Jarvis never depends on any single TTS vendor's own result or
      exception shape.
    - Define FakeTextToSpeechProvider, a test/wiring-only provider for
      use in tests and any future wiring before a real provider is
      chosen.

Does NOT:
    - Implement any real TTS engine. No local model, no OS API, no cloud
      API is called anywhere in this module - Nathan has not yet chosen
      one, and no dependency has been added to support one.
    - Play, save, or transmit audio anywhere. Nothing in this module can
      produce a sound.
    - Access a microphone or implement any speech-to-text behaviour.
    - Execute, route, or interpret the text it is asked to speak in any
      way - text handed to speak() is always treated as data to
      (eventually) vocalise, never as a command. This module never
      imports CommandRouter, ToolExecutor, ApprovalManager, or any AI
      component.
    - Call the network. FakeTextToSpeechProvider never does; a future
      real provider that does would be a distinct, separately-reviewed
      addition, not something added by this module.

This mirrors tools/web_search_provider.py's own established provider-
abstraction pattern: an ABC plus a provider-neutral result type, so a
real TTS engine can be added later by implementing this interface,
without changing VoiceOutputService or anything that depends on it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SpeechResult:
    """The provider-neutral outcome of one speak attempt.

    Returned by both a TextToSpeechProvider's speak() call and by
    VoiceOutputService.speak() (voice/output.py) - the same shape either
    way, so a caller never needs to distinguish "the provider failed"
    from "the service declined to call the provider at all".

    Attributes:
        success: True if the text was (or, for a fake/test provider,
            would have been) spoken successfully.
        error: A human-readable failure reason when success is False, or
            None when success is True.
        truncated: True if the text actually spoken was shortened before
            being handed to the provider (VoiceOutputService's own
            length guard - see voice/output.py). Always False for a
            provider's own direct result, since truncation is a service-
            level decision, not a provider one.
    """

    success: bool
    error: str | None = None
    truncated: bool = False


class TextToSpeechProvider(ABC):
    """Abstract interface every concrete text-to-speech engine implements.

    A provider's only responsibility is to accept already-decided text
    and report whether it was spoken successfully. It never decides
    whether speaking should happen at all (that is VoiceOutputService's
    job) and never interprets the text it is given - text is always
    vocalised verbatim, never executed, routed, or examined for
    commands.
    """

    @abstractmethod
    def speak(self, text: str) -> SpeechResult:
        """Speak the given text and report the outcome.

        Args:
            text: The already-validated, non-empty text to speak.

        Returns:
            A SpeechResult describing whether speaking succeeded.
        """
        raise NotImplementedError


class FakeTextToSpeechProvider(TextToSpeechProvider):
    """A test/wiring-only provider that never produces real audio.

    Never touches a microphone or the network, and never plays, saves,
    or transmits sound. It exists purely so VoiceOutputService (and,
    later, any CLI wiring) can be developed and tested before a real TTS
    engine is chosen (docs/phase_41_implementation_plan.md, Section 6).

    Attributes:
        spoken_texts: Every text this provider was asked to speak, in
            call order - recorded regardless of whether the call
            succeeded or was configured to fail, so tests can assert
            exactly what was requested.
        fail_with: Optional error message. When set, every call to
            speak() returns a failure result with this message instead
            of succeeding - used to simulate provider failure in tests.
    """

    def __init__(self, *, fail_with: str | None = None) -> None:
        """Initialise the fake provider.

        Args:
            fail_with: Optional error message to simulate every future
                speak() call failing with. Defaults to None, in which
                case every call succeeds.
        """
        self.spoken_texts: list[str] = []
        self.fail_with = fail_with

    def speak(self, text: str) -> SpeechResult:
        """Record the text and return success, or a simulated failure.

        Never produces audio, never touches a microphone, and never
        makes a network call - this is a pure, in-memory recording of
        what it was asked to speak.

        Args:
            text: The text this fake provider is "asked" to speak.

        Returns:
            A successful SpeechResult (recording the text in
            spoken_texts), or a failed SpeechResult with self.fail_with
            as the error, if this instance was constructed to simulate
            failure.
        """
        self.spoken_texts.append(text)
        if self.fail_with is not None:
            return SpeechResult(success=False, error=self.fail_with)
        return SpeechResult(success=True)
