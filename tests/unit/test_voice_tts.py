"""
test_voice_tts.py

Unit tests for the voice output provider abstraction and fake provider
(voice/tts.py), Phase 41, Batch 1.

These are pure, in-memory tests - no audio, no microphone, no network,
and no real TTS engine of any kind is involved. Structural (AST-based)
tests confirm this module never imports anything from the execution/
mutation side of Jarvis (CommandRouter, ToolExecutor, ApprovalManager,
any AI component, or any storage/memory/scheduling/inbox/dashboard/
workflow module) and never calls an audio/microphone/network API.

Run with:
    pytest tests/unit/test_voice_tts.py
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import voice.tts as voice_tts_module
from voice.tts import FakeTextToSpeechProvider, SpeechResult, TextToSpeechProvider


# --- SpeechResult -------------------------------------------------------------


def test_speech_result_defaults() -> None:
    result = SpeechResult(success=True)
    assert result.success is True
    assert result.error is None
    assert result.truncated is False


def test_speech_result_failure_carries_error() -> None:
    result = SpeechResult(success=False, error="boom")
    assert result.success is False
    assert result.error == "boom"


# --- TextToSpeechProvider (abstract) ------------------------------------------


def test_text_to_speech_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        TextToSpeechProvider()  # type: ignore[abstract]


# --- FakeTextToSpeechProvider --------------------------------------------------


def test_fake_provider_records_spoken_text() -> None:
    provider = FakeTextToSpeechProvider()
    provider.speak("hello")
    provider.speak("world")
    assert provider.spoken_texts == ["hello", "world"]


def test_fake_provider_succeeds_by_default() -> None:
    provider = FakeTextToSpeechProvider()
    result = provider.speak("hello")
    assert result.success is True
    assert result.error is None


def test_fake_provider_can_simulate_failure() -> None:
    provider = FakeTextToSpeechProvider(fail_with="simulated engine failure")
    result = provider.speak("hello")
    assert result.success is False
    assert result.error == "simulated engine failure"


def test_fake_provider_records_text_even_on_simulated_failure() -> None:
    provider = FakeTextToSpeechProvider(fail_with="boom")
    provider.speak("still recorded")
    assert provider.spoken_texts == ["still recorded"]


def test_fake_provider_defaults_to_no_simulated_failure() -> None:
    provider = FakeTextToSpeechProvider()
    assert provider.fail_with is None


# --- Structural: no audio/microphone/network, no forbidden imports ------------


def test_fake_provider_never_calls_audio_microphone_or_network_apis() -> None:
    """Structural: no audio/microphone/network-shaped call exists
    anywhere in this module."""
    source = inspect.getsource(voice_tts_module)
    tree = ast.parse(source)

    forbidden_calls = {
        "record",
        "listen",
        "playsound",
        "play",
        "Popen",
        "system",
        "urlopen",
        "post",
        "request",
        "connect",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls, (
                f"forbidden call found: {node.func.attr}"
            )


def test_voice_tts_module_imports_no_forbidden_components() -> None:
    """Structural: voice/tts.py must never import CommandRouter,
    ToolExecutor, ApprovalManager, any AI component, any storage/
    memory/scheduling/inbox/dashboard/workflow module, or any audio/
    microphone/network library."""
    source = Path("voice/tts.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])

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
        # No audio/microphone/STT/network library exists in this
        # project yet - confirming none was accidentally introduced.
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
