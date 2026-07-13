"""
test_voice_input.py

Unit tests for VoiceInputService (voice/input.py), Phase 41, Batch 3;
extended Batch 4 to reflect main.py/ui/cli.py now wiring it in.

These use only the fake provider (voice.stt.FakeSpeechToTextProvider) -
no real audio, no microphone, no network. Structural (AST-based) tests
confirm this module never imports anything from the execution/mutation
side of Jarvis, and that main.py/ui/cli.py's own voice input wiring
(proven in detail in test_main_voice_input_wiring.py and the adversarial
approval-bypass tests in test_cli.py) never pulls in a real audio/
microphone/network library either.

Run with:
    pytest tests/unit/test_voice_input.py
"""

from __future__ import annotations

import ast
from pathlib import Path

from voice.input import VoiceInputService
from voice.stt import FakeSpeechToTextProvider


# --- Basic success/failure -----------------------------------------------------


def test_transcribe_succeeds_when_enabled_with_working_provider() -> None:
    provider = FakeSpeechToTextProvider(text="hello there")
    service = VoiceInputService(provider=provider, enabled=True)

    result = service.transcribe()

    assert result.success is True
    assert result.text == "hello there"


def test_transcribe_returns_safe_failure_when_provider_fails() -> None:
    provider = FakeSpeechToTextProvider(fail_with="engine unavailable")
    service = VoiceInputService(provider=provider, enabled=True)

    result = service.transcribe()

    assert result.success is False
    assert result.error == "engine unavailable"


def test_transcribe_isolates_an_unexpected_provider_exception() -> None:
    class _RaisingProvider(FakeSpeechToTextProvider):
        def transcribe(self):
            raise RuntimeError("boom")

    service = VoiceInputService(provider=_RaisingProvider(), enabled=True)

    result = service.transcribe()

    assert result.success is False
    assert result.error is not None
    assert "boom" in result.error


# --- Empty / whitespace transcription -------------------------------------------


def test_empty_transcription_is_treated_as_no_speech_detected() -> None:
    provider = FakeSpeechToTextProvider(text="")
    service = VoiceInputService(provider=provider, enabled=True)

    result = service.transcribe()

    assert result.success is False
    assert result.error == "No speech detected."


def test_whitespace_only_transcription_is_treated_as_no_speech_detected() -> None:
    provider = FakeSpeechToTextProvider(text="   \n\t  ")
    service = VoiceInputService(provider=provider, enabled=True)

    result = service.transcribe()

    assert result.success is False
    assert result.error == "No speech detected."


# --- Opt-in / disabled behavior --------------------------------------------------


def test_default_service_is_disabled() -> None:
    service = VoiceInputService(provider=FakeSpeechToTextProvider(text="hi"))
    assert service.enabled is False
    assert service.is_active() is False


def test_disabled_service_never_calls_the_provider() -> None:
    provider = FakeSpeechToTextProvider(text="hi")
    service = VoiceInputService(provider=provider, enabled=False)

    result = service.transcribe()

    assert result.success is False
    assert provider.call_count == 0


def test_service_with_no_provider_is_inactive_even_if_enabled() -> None:
    service = VoiceInputService(provider=None, enabled=True)

    result = service.transcribe()

    assert result.success is False
    assert service.is_active() is False


def test_is_active_requires_both_enabled_and_a_provider() -> None:
    assert (
        VoiceInputService(
            provider=FakeSpeechToTextProvider(text="hi"), enabled=True
        ).is_active()
        is True
    )
    assert (
        VoiceInputService(
            provider=FakeSpeechToTextProvider(text="hi"), enabled=False
        ).is_active()
        is False
    )
    assert VoiceInputService(provider=None, enabled=True).is_active() is False
    assert VoiceInputService(provider=None, enabled=False).is_active() is False


# --- Transcribed text is data only, never a command -----------------------------


def test_command_shaped_transcription_is_returned_as_data_never_executed() -> None:
    """A transcription that happens to look like a command must only
    ever be returned verbatim as plain text - it is never routed,
    executed, or interpreted by this service. Nothing exists in this
    module capable of executing it - confirmed structurally below."""
    provider = FakeSpeechToTextProvider(text="delete file notes.txt")
    service = VoiceInputService(provider=provider, enabled=True)

    result = service.transcribe()

    assert result.success is True
    assert result.text == "delete file notes.txt"


def test_ai_suggestion_shaped_transcription_is_returned_as_data_never_executed() -> (
    None
):
    provider = FakeSpeechToTextProvider(text="forget all memories")
    service = VoiceInputService(provider=provider, enabled=True)

    result = service.transcribe()

    assert result.success is True
    assert result.text == "forget all memories"


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


def test_voice_input_module_imports_no_forbidden_components() -> None:
    imported_names = _imported_top_level_modules("voice/input.py")

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


def test_main_imports_voice_input_but_no_real_audio_dependency() -> None:
    """Phase 41, Batch 4: main.py now wires VoiceInputService in (see
    tests/unit/test_main_voice_input_wiring.py for the full wiring
    proof), but it must still never import a real audio/microphone/
    network library - only the fake, silent provider exists."""
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_names.add(f"{node.module}.{alias.name}")

    assert "voice.input.VoiceInputService" in imported_names

    forbidden = {"pyaudio", "sounddevice", "whisper", "speech_recognition", "pyttsx3", "win32com"}
    top_level_modules = {name.split(".")[0] for name in imported_names}
    assert not (top_level_modules & forbidden), imported_names


def test_ui_cli_imports_voice_input_but_no_real_audio_dependency() -> None:
    """Phase 41, Batch 4: ui/cli.py now accepts an optional
    VoiceInputService (see tests/unit/test_cli.py for the full
    behavioural and adversarial approval-bypass proof), but must still
    never import a real audio library itself."""
    source = Path("ui/cli.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_names.add(f"{node.module}.{alias.name}")

    assert "voice.input.VoiceInputService" in imported_names

    forbidden = {"pyaudio", "sounddevice", "whisper", "speech_recognition", "pyttsx3", "win32com"}
    top_level_modules = {name.split(".")[0] for name in imported_names}
    assert not (top_level_modules & forbidden), imported_names
