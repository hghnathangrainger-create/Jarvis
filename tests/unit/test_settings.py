"""
test_settings.py

Unit tests for config/settings.py's voice-related fields (Phase 41,
Batch 2): voice_enabled, voice_speak_mode, voice_provider.

No dedicated unit test file existed for config/settings.py before this
batch (load_settings() was previously only exercised indirectly, via
main.build_orchestrator() and various integration tests) - this file is
scoped narrowly to the new voice fields only, not a general audit of
every existing setting.

Run with:
    pytest tests/unit/test_settings.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import ConfigError, load_settings


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so load_settings()
    never touches the real .env file, and clear any voice-related
    variable that might already be set in the real environment."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_SPEAK_MODE", raising=False)
    monkeypatch.delenv("VOICE_PROVIDER", raising=False)


# --- defaults -----------------------------------------------------------------


def test_voice_enabled_defaults_to_false() -> None:
    settings = load_settings()
    assert settings.voice_enabled is False


def test_voice_speak_mode_defaults_to_off() -> None:
    settings = load_settings()
    assert settings.voice_speak_mode == "off"


def test_voice_provider_defaults_to_none() -> None:
    settings = load_settings()
    assert settings.voice_provider == "none"


# --- valid values load correctly -----------------------------------------------


def test_voice_enabled_true_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_ENABLED", "true")
    assert load_settings().voice_enabled is True


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE", "On"])
def test_voice_enabled_accepts_every_established_true_spelling(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("VOICE_ENABLED", raw)
    assert load_settings().voice_enabled is True


def test_voice_speak_mode_all_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_SPEAK_MODE", "all")
    assert load_settings().voice_speak_mode == "all"


def test_voice_provider_fake_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_PROVIDER", "fake")
    assert load_settings().voice_provider == "fake"


# --- invalid values fail safely, consistent with existing config style --------


def test_invalid_voice_speak_mode_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_SPEAK_MODE", "sometimes")
    with pytest.raises(ConfigError):
        load_settings()


def test_invalid_voice_provider_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_PROVIDER", "elevenlabs")
    with pytest.raises(ConfigError):
        load_settings()


def test_empty_voice_speak_mode_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty/whitespace-only value is treated as unset, matching
    every other optional setting's own established behaviour - not a
    validation error."""
    monkeypatch.setenv("VOICE_SPEAK_MODE", "   ")
    assert load_settings().voice_speak_mode == "off"


# --- no secret voice fields exist -----------------------------------------------


def test_no_voice_field_is_treated_as_a_secret() -> None:
    """Structural: none of the three voice settings is a credential or
    API key - none should ever need redaction the way
    anthropic_api_key does."""
    settings = load_settings()
    for forbidden_name in ("voice_api_key", "voice_secret", "voice_token"):
        assert not hasattr(settings, forbidden_name)
