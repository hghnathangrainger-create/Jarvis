"""
input.py

Voice input (transcription) service for Jarvis's speech-to-text
foundation (Phase 41, Batch 3).

Responsibilities:
    - Wrap a single SpeechToTextProvider (voice/stt.py) and decide
      whether a given call to transcribe() should actually reach it -
      a disabled service, or one with no provider, is always a safe
      no-op.
    - Guard against a provider reporting success with empty or
      whitespace-only text - treated as "no speech detected", not a
      usable transcription.
    - Never let a provider failure raise into the caller - every
      outcome, success or failure, is reported as a TranscriptionResult.

Does NOT:
    - Capture audio, access a microphone, or implement any recording,
      push-to-talk, always-listening, or wake-word behaviour. Nothing
      in this module can start or stop listening for anything - that
      is a distinct, later, separately-reviewed decision (see
      docs/phase_41_implementation_plan.md, Section 12).
    - Route, execute, or interpret the transcribed text it produces in
      any way. **This is the single most important property of this
      class**: a TranscriptionResult's text is returned to the caller
      as plain data only - this service never constructs a ToolRequest,
      never calls CommandRouter.match()/build_input(), never calls
      ToolExecutor.execute(), never calls ApprovalManager, and never
      calls any AI component. It has no reference to any of them and
      cannot reach them even by accident.
    - Decide *whether* a future caller should treat transcribed text as
      a command at all. That is an explicit, separate, later decision
      (deferred to a batch after Batch 3 - see the trust/origin note
      below) - this service's only job is producing text safely, never
      acting on it.
    - Mutate a file, a memory, a schedule, an Inbox entry, a quarantine
      record, a workflow, or anything shown on the dashboard - it has
      no dependency on any of those modules at all.
    - Change Jarvis's default runtime behaviour. main.py and ui/cli.py
      do construct and call this service (Phase 41, Batch 4), but only
      through an opt-in, disabled-by-default path with the fake
      provider - never enabled, never reachable from the interactive
      typed-input loop, and never a default behaviour change, exactly
      mirroring how voice/output.py's VoiceOutputService was wired into
      the CLI in Batch 2.

Trust/origin design (read before ever wiring this service into
anything that can execute a command):
    A transcription produced by this service is inert - it is a string,
    nothing more, until some future caller chooses to do something with
    it. When a future batch does route transcribed text toward
    execution, the following must all hold, and should be explicitly
    tested when that batch is built:

    1. Transcribed text must flow through the *exact same*
       CommandRouter -> SecurityManager -> ApprovalManager ->
       ToolExecutor path typed text already uses today - never a
       parallel or shortened path, and never a voice-specific bypass.
    2. An action that would require YELLOW/RED approval when typed must
       require exactly the same approval when it arrived as a
       transcription - the classification and approval gate must never
       depend on which input modality produced the text.
    3. A bad or garbled transcription must never become a hidden write
       action. Because SecurityManager classifies the resulting text
       the same way regardless of origin, a mis-transcribed word that
       happens to resolve to a YELLOW/RED action is still stopped for
       approval/blocked, exactly as a typo'd typed command would be -
       it is never silently executed just because it arrived as
       speech.
    4. Voice-originated commands may need explicit origin tracking in
       a future batch (for example, in audit/history display, so a
       reviewer can tell "typed" apart from "transcribed, then typed
       equivalent"), separate from - and never a substitute for - the
       trust/approval rules above. No such tracking exists yet; this
       service does not label its output's origin anywhere today
       because nothing downstream of it exists yet to read that label.

    No new AIContextBlock trust level, and no change to
    ai/context_models.py, was needed or made to state any of the above -
    this service does not construct an AIContextBlock at all, and
    transcribed text is not AI-facing content in the first place.

Safety design:
    The single most important property of this class is that it
    *cannot act* on the text it produces - it can only report a
    transcription, or safely decline to. This mirrors
    ai/reasoning_engine.py's own established "cannot execute anything"
    design, and voice/output.py's own "cannot act" design, precisely.
"""

from __future__ import annotations

from voice.stt import SpeechToTextProvider, TranscriptionResult


class VoiceInputService:
    """Wraps a SpeechToTextProvider, deciding whether/how to call it.

    Attributes:
        enabled: Whether this service will actually call its provider.
            Defaults to False (opt-in) - matching
            VoiceOutputService.enabled's own established default in
            this codebase.
    """

    def __init__(
        self,
        *,
        provider: SpeechToTextProvider | None = None,
        enabled: bool = False,
    ) -> None:
        """Initialise the service.

        Args:
            provider: The SpeechToTextProvider to transcribe through.
                Defaults to None, in which case transcribe() always
                returns a safe, inactive failure result, regardless of
                enabled.
            enabled: Whether this service is switched on. Defaults to
                False (opt-in), matching VoiceOutputService's own
                default.
        """
        self._provider = provider
        self.enabled = enabled

    def is_active(self) -> bool:
        """Report whether transcribe() will actually reach the provider.

        Returns:
            True only when this service is enabled and a provider was
            supplied.
        """
        return self.enabled and self._provider is not None

    def transcribe(self) -> TranscriptionResult:
        """Transcribe, if this service is active.

        Returns:
            A TranscriptionResult. Never raises: a disabled service, a
            missing provider, a provider failure (including an
            unexpected exception), and a provider reporting success
            with empty/whitespace-only text all produce a failed
            TranscriptionResult rather than propagating an error or
            reporting an unusable "successful" empty transcription.
        """
        if not self.is_active():
            return TranscriptionResult(success=False, error="Voice input is disabled.")

        try:
            result = self._provider.transcribe()
        except Exception as exc:  # noqa: BLE001 - isolate any provider failure
            return TranscriptionResult(
                success=False, error=f"Voice input provider failed: {exc}"
            )

        if result.success and not result.text.strip():
            return TranscriptionResult(success=False, error="No speech detected.")
        return result
