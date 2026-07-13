"""
voice package

Text-to-speech output foundation for Jarvis (Phase 41, Batch 1; CLI
wiring in Batch 2), and a speech-to-text input foundation (Phase 41,
Batch 3).

This package contains: a TTS provider abstraction (voice.tts) plus a
fake/test provider that never produces real audio, a service
(voice.output) that decides whether a given call to speak() actually
reaches a provider (wired into ui/cli.py, opt-in and disabled by
default, since Batch 2); and an STT provider abstraction (voice.stt)
plus a fake/test provider that never accesses a microphone, and a
service (voice.input) that decides whether a given call to
transcribe() actually reaches a provider (not wired into anything yet
- Batch 3 is foundation only). No real TTS or STT engine is implemented
here yet, and no microphone or recording mechanism of any kind exists -
see docs/phase_41_implementation_plan.md for the decisions still
pending before either is chosen and wired in.

Does NOT:
    - Access a microphone, capture audio, or implement any
      listening/push-to-talk/always-listening/wake-word behaviour.
      Push-to-talk is explicitly deferred to a later batch;
      always-listening/wake-word is deferred to a separate future
      review - see the implementation plan.
    - Call any external API or the network. Every provider in this
      package today is local and synchronous.
    - Execute, route, or interpret the text it is asked to speak, or
      the text it produces from a transcription, in any way. Text is
      always treated as plain data, never a command - transcribed text
      is not automatically executed or routed anywhere by this package
      (see voice/input.py's own trust/origin design note for the full
      reasoning behind this boundary and what a future batch must
      still prove before that changes).
    - Import CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine,
      AIReasoningEngine, AIRouter, WebSearchTool, or any ai/workflow/
      scheduler/dashboard/inbox module.
    - Change Jarvis's default runtime behaviour beyond the Batch 2 CLI
      voice-output wiring (opt-in, disabled by default). Nothing
      outside this package's own tests constructs or calls
      voice.input's VoiceInputService yet.
"""
