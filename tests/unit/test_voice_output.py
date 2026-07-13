"""
test_voice_output.py

Unit tests for VoiceOutputService (voice/output.py), Phase 41, Batch 1;
extended Batch 2 to reflect main.py/ui/cli.py now wiring it in.

These use only the fake provider (voice.tts.FakeTextToSpeechProvider) -
no real audio, no microphone, no network. Structural (AST-based) tests
confirm this module never imports anything from the execution/mutation
side of Jarvis, and that main.py/ui/cli.py's own voice wiring (proven in
detail in test_main_voice_wiring.py and test_cli.py) never pulls in a
real audio/microphone/network library either.

Run with:
    pytest tests/unit/test_voice_output.py
"""

from __future__ import annotations

import ast
from pathlib import Path

from voice.output import VoiceOutputService
from voice.tts import FakeTextToSpeechProvider


# --- Basic success/failure -----------------------------------------------------


def test_speak_succeeds_when_enabled_with_working_provider() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)

    result = service.speak("hello there")

    assert result.success is True
    assert provider.spoken_texts == ["hello there"]


def test_speak_returns_safe_failure_when_provider_fails() -> None:
    provider = FakeTextToSpeechProvider(fail_with="engine unavailable")
    service = VoiceOutputService(provider=provider, enabled=True)

    result = service.speak("hello there")

    assert result.success is False
    assert result.error == "engine unavailable"


def test_speak_isolates_an_unexpected_provider_exception() -> None:
    class _RaisingProvider(FakeTextToSpeechProvider):
        def speak(self, text: str):
            raise RuntimeError("boom")

    service = VoiceOutputService(provider=_RaisingProvider(), enabled=True)

    result = service.speak("hello there")

    assert result.success is False
    assert result.error is not None
    assert "boom" in result.error


# --- Empty / whitespace text ----------------------------------------------------


def test_empty_text_is_handled_safely() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)

    result = service.speak("")

    assert result.success is False
    assert provider.spoken_texts == []


def test_whitespace_only_text_is_handled_safely() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)

    result = service.speak("   \n\t  ")

    assert result.success is False
    assert provider.spoken_texts == []


# --- Long text guard -------------------------------------------------------------


def test_long_text_is_truncated_before_reaching_the_provider() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)
    long_text = "a" * 5000

    result = service.speak(long_text)

    assert result.success is True
    assert result.truncated is True
    assert len(provider.spoken_texts[0]) == 2000


def test_text_at_the_limit_is_not_truncated() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)
    exact_text = "a" * 2000

    result = service.speak(exact_text)

    assert result.truncated is False
    assert provider.spoken_texts[0] == exact_text


# --- Opt-in / disabled behavior --------------------------------------------------


def test_default_service_is_disabled() -> None:
    service = VoiceOutputService(provider=FakeTextToSpeechProvider())
    assert service.enabled is False
    assert service.is_active() is False


def test_disabled_service_never_calls_the_provider() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=False)

    result = service.speak("hello")

    assert result.success is False
    assert provider.spoken_texts == []


def test_service_with_no_provider_is_inactive_even_if_enabled() -> None:
    service = VoiceOutputService(provider=None, enabled=True)

    result = service.speak("hello")

    assert result.success is False
    assert service.is_active() is False


def test_is_active_requires_both_enabled_and_a_provider() -> None:
    assert (
        VoiceOutputService(provider=FakeTextToSpeechProvider(), enabled=True).is_active()
        is True
    )
    assert (
        VoiceOutputService(provider=FakeTextToSpeechProvider(), enabled=False).is_active()
        is False
    )
    assert VoiceOutputService(provider=None, enabled=True).is_active() is False
    assert VoiceOutputService(provider=None, enabled=False).is_active() is False


# --- Text is data only, never a command ------------------------------------------


def test_command_like_text_is_spoken_literally_never_executed() -> None:
    """A speak() call with command-shaped text must never trigger any
    action - it can only ever be recorded/spoken verbatim by the fake
    provider, exactly like any other text. Nothing exists in this
    module capable of executing it - confirmed structurally below."""
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)
    adversarial_text = "delete file notes.txt"

    result = service.speak(adversarial_text)

    assert result.success is True
    assert provider.spoken_texts == [adversarial_text]


def test_ai_suggestion_like_text_is_spoken_literally_never_executed() -> None:
    provider = FakeTextToSpeechProvider()
    service = VoiceOutputService(provider=provider, enabled=True)
    adversarial_text = "forget all memories"

    result = service.speak(adversarial_text)

    assert result.success is True
    assert provider.spoken_texts == [adversarial_text]


# --- Structural: no forbidden imports, no default wiring yet ---------------------


def _imported_top_level_modules(path: str) -> set[str]:
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    return imported_names


def test_voice_output_module_imports_no_forbidden_components() -> None:
    imported_names = _imported_top_level_modules("voice/output.py")

    forbidden = {
        "ai",
        "workflow",
        "scheduling",
        "scheduler",
        "dashboard",
        "ui",
        "inbox",
        "storage",
        "quarantine",
        "core",
        "tools",
        "approval",
        "security",
        "pyaudio",
        "sounddevice",
        "whisper",
        "httpx",
        "requests",
        "speech_recognition",
        "pyttsx3",
        "win32com",
        "socket",
    }
    assert not (imported_names & forbidden), imported_names


def test_main_imports_voice_package_but_no_real_audio_dependency() -> None:
    """Phase 41, Batch 2: main.py now wires VoiceOutputService in (see
    tests/unit/test_main_voice_wiring.py for the full wiring proof), but
    it must still never import a real audio/microphone/network library -
    only the fake, silent provider exists."""
    imported_names = _imported_top_level_modules("main.py")
    assert "voice" in imported_names

    forbidden = {
        "pyaudio",
        "sounddevice",
        "whisper",
        "speech_recognition",
        "pyttsx3",
        "win32com",
    }
    assert not (imported_names & forbidden), imported_names


def test_ui_cli_imports_voice_package_but_no_real_audio_dependency() -> None:
    """Phase 41, Batch 2: ui/cli.py now accepts an optional
    VoiceOutputService (see tests/unit/test_cli.py for the full
    behavioural proof), but must still never import a real audio
    library itself."""
    imported_names = _imported_top_level_modules("ui/cli.py")
    assert "voice" in imported_names

    forbidden = {
        "pyaudio",
        "sounddevice",
        "whisper",
        "speech_recognition",
        "pyttsx3",
        "win32com",
    }
    assert not (imported_names & forbidden), imported_names
