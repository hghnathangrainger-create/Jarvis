"""
stt.py

Speech-to-text provider abstraction for Jarvis's voice input foundation
(Phase 41, Batch 3).

Responsibilities:
    - Define SpeechToTextProvider, the abstract interface every concrete
      STT engine (local, OS-provided, or cloud - see
      docs/phase_41_implementation_plan.md, Section 7) will eventually
      implement.
    - Define TranscriptionResult, the provider-neutral outcome every
      provider (and VoiceInputService, in voice/input.py) returns, so
      the rest of Jarvis never depends on any single STT vendor's own
      result or exception shape.
    - Define FakeSpeechToTextProvider, a test/wiring-only provider for
      use in tests and any future wiring before a real provider is
      chosen or a real recording mechanism exists.

Does NOT:
    - Implement any real STT engine. No local model, no OS API, no
      cloud API is called anywhere in this module - Nathan has not yet
      chosen one, and no dependency has been added to support one.
    - Access a microphone, an audio device, or any recording mechanism
      of any kind. There is no push-to-talk, no always-listening, and
      no wake-word behaviour anywhere in this project yet - this module
      only models what a provider reports back once given something to
      transcribe, never how audio is captured.
    - Call the network. FakeSpeechToTextProvider never does; a future
      real provider that does would be a distinct, separately-reviewed
      addition, not something added by this module.
    - Execute, route, or interpret the transcribed text it produces in
      any way. A TranscriptionResult's text is always plain data,
      exactly like typed input is until CommandRouter processes it -
      this module never imports CommandRouter, ToolExecutor,
      ApprovalManager, or any AI component, and nothing in this module
      calls any of them.

This mirrors voice/tts.py's own established provider-abstraction pattern
(itself mirroring tools/web_search_provider.py): an ABC plus a
provider-neutral result type, so a real STT engine can be added later by
implementing this interface, without changing VoiceInputService or
anything that depends on it.

Trust/origin note (see docs/phase_41_implementation_plan.md, Section 8,
and voice/input.py's own module docstring for the full reasoning): a
transcription produced here is not automatically executed by anything in
this module or in voice/input.py. Whenever a future batch does route
transcribed text toward execution, it must flow through the exact same
CommandRouter -> SecurityManager -> ApprovalManager -> ToolExecutor path
typed text already uses - never a shortcut, and never with weaker
approval requirements just because the text arrived as a transcription.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """The provider-neutral outcome of one transcribe attempt.

    Returned by both a SpeechToTextProvider's transcribe() call and by
    VoiceInputService.transcribe() (voice/input.py) - the same shape
    either way, so a caller never needs to distinguish "the provider
    failed" from "the service declined to call the provider at all".

    Attributes:
        success: True if a transcription was (or, for a fake/test
            provider, would have been) produced successfully.
        text: The transcribed text. Always an empty string when success
            is False. Plain data only - never interpreted, executed, or
            routed anywhere by this module.
        error: A human-readable failure reason when success is False, or
            None when success is True.
    """

    success: bool
    text: str = ""
    error: str | None = None


class SpeechToTextProvider(ABC):
    """Abstract interface every concrete speech-to-text engine implements.

    A provider's only responsibility is to report a transcription
    outcome. It never decides whether transcription should happen at
    all (that is VoiceInputService's job), never captures audio itself,
    and never interprets the text it produces - text is always returned
    as plain data, never executed, routed, or examined for commands.

    Deliberately takes no audio input parameter yet: no real provider
    exists, and no recording/capture mechanism (push-to-talk or
    otherwise) has been built yet either (deferred to a later batch -
    docs/phase_41_implementation_plan.md, Section 12). Adding an audio
    parameter now would mean guessing its shape (raw bytes, a file
    path, a stream) before that decision is actually made.
    """

    @abstractmethod
    def transcribe(self) -> TranscriptionResult:
        """Produce one transcription result.

        Returns:
            A TranscriptionResult describing whether a transcription
            was produced, and the transcribed text if so.
        """
        raise NotImplementedError


class FakeSpeechToTextProvider(SpeechToTextProvider):
    """A test/wiring-only provider that never accesses a microphone.

    Never touches an audio device or the network. It exists purely so
    VoiceInputService (and, later, any CLI wiring) can be developed and
    tested before a real STT engine and a real recording mechanism are
    chosen (docs/phase_41_implementation_plan.md, Section 7).

    Attributes:
        text: The pre-configured transcription text this provider
            returns on every successful call.
        fail_with: Optional error message. When set, every call to
            transcribe() returns a failure result with this message
            instead of succeeding - used to simulate provider failure
            in tests.
        call_count: The number of times transcribe() has been called -
            for tests to assert against, since this provider takes no
            per-call input to otherwise record.
    """

    def __init__(self, *, text: str = "", fail_with: str | None = None) -> None:
        """Initialise the fake provider.

        Args:
            text: The transcription text to return on every successful
                call. Defaults to an empty string.
            fail_with: Optional error message to simulate every future
                transcribe() call failing with. Defaults to None, in
                which case every call succeeds.
        """
        self.text = text
        self.fail_with = fail_with
        self.call_count = 0

    def transcribe(self) -> TranscriptionResult:
        """Return the pre-configured text, or a simulated failure.

        Never accesses a microphone, an audio device, or the network -
        this is a pure, in-memory, pre-configured result.

        Returns:
            A successful TranscriptionResult carrying self.text, or a
            failed TranscriptionResult with self.fail_with as the
            error, if this instance was constructed to simulate
            failure.
        """
        self.call_count += 1
        if self.fail_with is not None:
            return TranscriptionResult(success=False, error=self.fail_with)
        return TranscriptionResult(success=True, text=self.text)
