"""
test_settings.py

Unit tests for config/settings.py's voice-related fields (Phase 41,
Batch 2: voice_enabled, voice_speak_mode, voice_provider; Phase 41,
Batch 4: voice_input_enabled, voice_input_provider), and for LOG_LEVEL
validation (Phase 46: log_level is now validated against
config.constants.LogLevel, case-insensitively, instead of accepting any
string).

No dedicated unit test file existed for config/settings.py before Batch
2 (load_settings() was previously only exercised indirectly, via
main.build_orchestrator() and various integration tests) - this file
remains scoped narrowly to fields with their own dedicated validation
logic worth testing directly, not a general audit of every existing
setting.

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
    monkeypatch.delenv("VOICE_INPUT_ENABLED", raising=False)
    monkeypatch.delenv("VOICE_INPUT_PROVIDER", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)


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


# --- voice input fields (Phase 41, Batch 4) -------------------------------------


def test_voice_input_enabled_defaults_to_false() -> None:
    assert load_settings().voice_input_enabled is False


def test_voice_input_provider_defaults_to_none() -> None:
    assert load_settings().voice_input_provider == "none"


def test_voice_input_enabled_true_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_INPUT_ENABLED", "true")
    assert load_settings().voice_input_enabled is True


def test_voice_input_provider_fake_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_INPUT_PROVIDER", "fake")
    assert load_settings().voice_input_provider == "fake"


def test_invalid_voice_input_provider_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_INPUT_PROVIDER", "whisper")
    with pytest.raises(ConfigError):
        load_settings()


def test_voice_input_enabled_is_independent_of_voice_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enabling voice output must never implicitly enable voice input,
    and vice versa - they are two separate settings."""
    monkeypatch.setenv("VOICE_ENABLED", "true")
    settings = load_settings()
    assert settings.voice_enabled is True
    assert settings.voice_input_enabled is False


def test_voice_enabled_is_independent_of_voice_input_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOICE_INPUT_ENABLED", "true")
    settings = load_settings()
    assert settings.voice_input_enabled is True
    assert settings.voice_enabled is False


# --- no secret voice fields exist -----------------------------------------------


def test_no_voice_field_is_treated_as_a_secret() -> None:
    """Structural: none of the five voice settings is a credential or
    API key - none should ever need redaction the way
    anthropic_api_key does."""
    settings = load_settings()
    for forbidden_name in (
        "voice_api_key",
        "voice_secret",
        "voice_token",
        "voice_input_api_key",
        "voice_input_secret",
        "voice_input_token",
    ):
        assert not hasattr(settings, forbidden_name)


# --- LOG_LEVEL validation (Phase 46) --------------------------------------------


def test_log_level_defaults_to_info_when_unset() -> None:
    assert load_settings().log_level == "INFO"


@pytest.mark.parametrize(
    "level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
)
def test_log_level_accepts_every_valid_uppercase_level(
    monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    monkeypatch.setenv("LOG_LEVEL", level)
    assert load_settings().log_level == level


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("debug", "DEBUG"),
        ("Debug", "DEBUG"),
        ("info", "INFO"),
        ("Info", "INFO"),
        ("warning", "WARNING"),
        ("error", "ERROR"),
        ("critical", "CRITICAL"),
    ],
)
def test_log_level_normalises_lowercase_and_mixed_case(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    """Preserves LOG_LEVEL's pre-existing case-insensitive behaviour -
    only genuinely invalid values are now rejected, not a different case
    spelling of an otherwise-valid level."""
    monkeypatch.setenv("LOG_LEVEL", raw)
    assert load_settings().log_level == expected


def test_invalid_log_level_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "banana")
    with pytest.raises(ConfigError):
        load_settings()


def test_empty_log_level_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty/whitespace-only value is treated as unset, matching every
    other optional setting's own established behaviour - not a
    validation error."""
    monkeypatch.setenv("LOG_LEVEL", "   ")
    assert load_settings().log_level == "INFO"


def test_settings_module_actually_uses_log_level_enum() -> None:
    """Structural: confirms config/settings.py genuinely imports and uses
    LogLevel (Phase 46), rather than validating against a second,
    separately-maintained hardcoded list - closing the exact gap where
    LogLevel previously existed as unused dead code with a docstring
    falsely claiming it validated LOG_LEVEL."""
    import ast
    import inspect

    import config.settings as module

    tree = ast.parse(inspect.getsource(module))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_names.add(f"{node.module}.{alias.name}")

    assert "config.constants.LogLevel" in imported_names
