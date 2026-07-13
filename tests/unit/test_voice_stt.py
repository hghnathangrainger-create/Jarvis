"""
test_voice_stt.py

Unit tests for the voice input provider abstraction and fake provider
(voice/stt.py), Phase 41, Batch 3.

These are pure, in-memory tests - no audio, no microphone, no network,
and no real STT engine of any kind is involved. Structural (AST-based)
tests confirm this module never imports anything from the execution/
mutation side of Jarvis (CommandRouter, ToolExecutor, ApprovalManager,
any AI component, or any storage/memory/scheduling/inbox/dashboard/
workflow module) and never calls an audio/microphone/network API.

Run with:
    pytest tests/unit/test_voice_stt.py
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import voice.stt as voice_stt_module
from voice.stt import FakeSpeechToTextProvider, SpeechToTextProvider, TranscriptionResult


# --- TranscriptionResult -------------------------------------------------------


def test_transcription_result_defaults() -> None:
    result = TranscriptionResult(success=True, text="hello")
    assert result.success is True
    assert result.text == "hello"
    assert result.error is None


def test_transcription_result_failure_defaults_to_empty_text() -> None:
    result = TranscriptionResult(success=False, error="boom")
    assert result.success is False
    assert result.text == ""
    assert result.error == "boom"


# --- SpeechToTextProvider (abstract) -------------------------------------------


def test_speech_to_text_provider_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        SpeechToTextProvider()  # type: ignore[abstract]


# --- FakeSpeechToTextProvider ---------------------------------------------------


def test_fake_provider_returns_configured_transcription_text() -> None:
    provider = FakeSpeechToTextProvider(text="hello there")
    result = provider.transcribe()
    assert result.success is True
    assert result.text == "hello there"


def test_fake_provider_defaults_to_empty_text() -> None:
    provider = FakeSpeechToTextProvider()
    result = provider.transcribe()
    assert result.success is True
    assert result.text == ""


def test_fake_provider_can_simulate_failure() -> None:
    provider = FakeSpeechToTextProvider(fail_with="simulated engine failure")
    result = provider.transcribe()
    assert result.success is False
    assert result.error == "simulated engine failure"
    assert result.text == ""


def test_fake_provider_records_call_count() -> None:
    provider = FakeSpeechToTextProvider(text="hi")
    assert provider.call_count == 0
    provider.transcribe()
    provider.transcribe()
    provider.transcribe()
    assert provider.call_count == 3


def test_fake_provider_records_calls_even_on_simulated_failure() -> None:
    provider = FakeSpeechToTextProvider(fail_with="boom")
    provider.transcribe()
    assert provider.call_count == 1


def test_fake_provider_returns_same_text_on_repeated_calls() -> None:
    provider = FakeSpeechToTextProvider(text="repeat me")
    first = provider.transcribe()
    second = provider.transcribe()
    assert first.text == second.text == "repeat me"


# --- Structural: no audio/microphone/network, no forbidden imports ------------


def test_fake_provider_never_calls_audio_microphone_or_network_apis() -> None:
    """Structural: no audio/microphone/network-shaped call exists
    anywhere in this module."""
    source = inspect.getsource(voice_stt_module)
    tree = ast.parse(source)

    forbidden_calls = {
        "record",
        "listen",
        "Popen",
        "system",
        "urlopen",
        "post",
        "request",
        "connect",
        "open_stream",
        "input_stream",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls, (
                f"forbidden call found: {node.func.attr}"
            )


def test_voice_stt_module_imports_no_forbidden_components() -> None:
    """Structural: voice/stt.py must never import CommandRouter,
    ToolExecutor, ApprovalManager, any AI component, any storage/
    memory/scheduling/inbox/dashboard/workflow module, or any audio/
    microphone/network library."""
    source = Path("voice/stt.py").read_text(encoding="utf-8")
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
