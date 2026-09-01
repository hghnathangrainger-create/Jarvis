"""
test_main_voice_input_wiring.py

Composition tests for the Phase 41, Batch 4 voice input wiring in
main.py: main.build_voice_input_service() and its use inside
main.main().

These confirm the voice input wiring is correct, never blocks startup
on failure, defaults to fully disabled/inactive, only ever constructs
voice/stt.py's own silent FakeSpeechToTextProvider (never a real
microphone or STT engine), and - critically - that
main.build_orchestrator()'s own return type and behavior are completely
unchanged.

Run with:
    pytest tests/unit/test_main_voice_input_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main
from core.orchestrator import JarvisOrchestrator
from voice.input import VoiceInputService
from voice.stt import FakeSpeechToTextProvider


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    and build_voice_input_service() never touch the real .env file or
    the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_SPEAK_MODE", raising=False)
    monkeypatch.delenv("VOICE_PROVIDER", raising=False)
    monkeypatch.delenv("VOICE_INPUT_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_INPUT_PROVIDER", raising=False)


# --- build_orchestrator() is unchanged ------------------------------------------


def test_build_orchestrator_still_returns_a_bare_orchestrator() -> None:
    """The widely-depended-on return type must not change for this
    narrow, unrelated addition."""
    result = main.build_orchestrator()
    assert isinstance(result, JarvisOrchestrator)


# --- build_voice_input_service() ------------------------------------------------


def test_build_voice_input_service_defaults_to_disabled_with_no_provider() -> None:
    service = main.build_voice_input_service()
    assert isinstance(service, VoiceInputService)
    assert service.is_active() is False


def test_build_voice_input_service_respects_voice_input_enabled_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_INPUT_ENABLED", "true")
    monkeypatch.setenv("VOICE_INPUT_PROVIDER", "fake")
    service = main.build_voice_input_service()
    assert service.enabled is True
    assert service.is_active() is True


def test_build_voice_input_service_stays_inactive_with_provider_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with VOICE_INPUT_ENABLED=true, VOICE_INPUT_PROVIDER's
    default "none" means no provider is constructed and the service
    stays inactive."""
    monkeypatch.setenv("VOICE_INPUT_ENABLED", "true")
    service = main.build_voice_input_service()
    assert service.is_active() is False


def test_build_voice_input_service_constructs_fake_provider_only_when_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_INPUT_ENABLED", "true")
    monkeypatch.setenv("VOICE_INPUT_PROVIDER", "fake")
    service = main.build_voice_input_service()

    result = service.transcribe()
    # An empty fake transcription is honestly reported as "no speech
    # detected" - proving the real fake provider was actually reached,
    # not that the service silently no-op'd.
    assert result.success is False
    assert result.error == "No speech detected."


def test_build_voice_input_service_never_raises_when_settings_are_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure while loading settings must never propagate - it must
    fall back to a disabled, provider-less service."""
    monkeypatch.setenv("DATABASE_PATH", "")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    service = main.build_voice_input_service()
    assert service.is_active() is False


# --- main() wiring: JarvisCLI receives the voice input service -----------------


def test_main_passes_voice_input_into_jarvis_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _FakeCLI:
        def __init__(
            self,
            orchestrator,
            *,
            startup_notice=None,
            voice_output=None,
            speak_responses=False,
            voice_input=None,
        ) -> None:
            captured["orchestrator"] = orchestrator
            captured["voice_input"] = voice_input

        def run(self) -> None:
            captured["ran"] = True

    fake_service = VoiceInputService(
        provider=FakeSpeechToTextProvider(text="hi"), enabled=True
    )
    monkeypatch.setattr(main, "JarvisCLI", _FakeCLI)
    monkeypatch.setattr(main, "build_startup_notice", lambda: None)
    monkeypatch.setattr(main, "build_voice_input_service", lambda: fake_service)

    main.main(argv=[])

    assert captured["voice_input"] is fake_service
    assert captured["ran"] is True
    assert isinstance(captured["orchestrator"], JarvisOrchestrator)


# --- structural: no real audio/microphone/network dependency -------------------


def test_main_never_constructs_a_real_stt_provider() -> None:
    """VOICE_INPUT_PROVIDER's only non-default accepted value is "fake"
    - there is no real STT engine choice yet, and main.py cannot
    construct one that does not exist."""
    import ast
    import inspect

    source = inspect.getsource(main)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    forbidden = {
        "pyttsx3",
        "win32com",
        "whisper",
        "sounddevice",
        "pyaudio",
        "speech_recognition",
    }
    assert not (imported_names & forbidden), imported_names
