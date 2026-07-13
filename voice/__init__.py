"""
voice package

Text-to-speech output foundation for Jarvis (Phase 41, Batch 1).

This package contains only the voice *output* foundation: a provider
abstraction (voice.tts), a fake/test provider that never produces real
audio, and a small service (voice.output) that decides whether a given
call to speak() actually reaches a provider. No real TTS engine is
implemented here yet - see docs/phase_41_implementation_plan.md for the
decisions still pending before one is chosen and wired in.

Does NOT:
    - Access a microphone, implement speech-to-text, or implement any
      listening/push-to-talk/always-listening/wake-word behaviour. That
      is explicitly deferred to a later batch (STT) or a separate future
      review (always-listening/wake-word) - see the implementation plan.
    - Call any external API or the network. Every provider in this
      package today is local and synchronous.
    - Execute, route, or interpret the text it is asked to speak in any
      way. Text is always treated as data to vocalise, never a command.
    - Import CommandRouter, ToolExecutor, ApprovalManager, WorkflowEngine,
      AIReasoningEngine, AIRouter, WebSearchTool, or any ai/workflow/
      scheduler/dashboard/inbox module.
    - Change Jarvis's default runtime behaviour. Nothing outside this
      package's own tests constructs or calls anything here yet.
"""
