"""
test_brain_settings.py

Unit tests for config/settings.py's BRAIN_* fields (Markdown Brain
Integration).

Hermetic: PYTHON_DOTENV_DISABLED=1 plus an explicit fake
ANTHROPIC_API_KEY mean no real .env file is ever read, and BRAIN_PATH is
always pointed at temporary/placeholder values - never at Nathan's real
brain.

Covered here:
    - defaults (disabled, unconfigured, the five knowledge folders, the
      three limits)
    - parsing of each BRAIN_* variable
    - BRAIN_FOLDERS validation: single safe segments only; hidden
      folders, ".", "..", path separators, and excluded directory names
      are rejected with ConfigError at load time - the load-time
      guarantee behind "never scan outside the configured root"

Run with:
    pytest tests/unit/test_brain_settings.py
"""

from __future__ import annotations

import pytest

from config.settings import ConfigError, load_settings


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every BRAIN_* variable from the developer's real .env."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    for name in (
        "BRAIN_ENABLED",
        "BRAIN_PATH",
        "BRAIN_FOLDERS",
        "BRAIN_MAX_FILE_BYTES",
        "BRAIN_SEARCH_LIMIT",
        "BRAIN_AI_CONTEXT_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)


# --- defaults ----------------------------------------------------------------


def test_brain_disabled_by_default() -> None:
    assert load_settings().brain_enabled is False


def test_brain_path_empty_by_default() -> None:
    assert load_settings().brain_path == ""


def test_brain_folders_default_to_the_five_knowledge_folders() -> None:
    assert load_settings().brain_folders == (
        "context",
        "decisions",
        "references",
        "audits",
        "brainstorms",
    )


def test_brain_limits_have_sensible_defaults() -> None:
    settings = load_settings()
    assert settings.brain_max_file_bytes == 262_144
    assert settings.brain_search_limit == 25
    assert settings.brain_ai_context_chars == 4_000


# --- parsing -----------------------------------------------------------------


def test_brain_enabled_true_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_ENABLED", "true")
    assert load_settings().brain_enabled is True


def test_brain_enabled_false_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_ENABLED", "false")
    assert load_settings().brain_enabled is False


def test_invalid_brain_enabled_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAIN_ENABLED", "maybe")
    with pytest.raises(ConfigError):
        load_settings()


def test_windows_brain_path_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_PATH", "C:/Users/NathanGrainger/mi-aios")
    assert load_settings().brain_path == "C:/Users/NathanGrainger/mi-aios"


def test_brain_folders_are_parsed_as_a_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAIN_FOLDERS", "context, decisions ,decisions")
    assert load_settings().brain_folders == ("context", "decisions", "decisions")


def test_brain_limits_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_MAX_FILE_BYTES", "1024")
    monkeypatch.setenv("BRAIN_SEARCH_LIMIT", "7")
    monkeypatch.setenv("BRAIN_AI_CONTEXT_CHARS", "1234")
    settings = load_settings()
    assert settings.brain_max_file_bytes == 1_024
    assert settings.brain_search_limit == 7
    assert settings.brain_ai_context_chars == 1_234


def test_non_positive_brain_limit_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAIN_SEARCH_LIMIT", "0")
    with pytest.raises(ConfigError):
        load_settings()


# --- BRAIN_FOLDERS validation ------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "../outside",
        "context/sub",
        "context\\sub",
        ".hidden",
        "..",
        "apps",
        "node_modules",
        "__pycache__",
        "venv",
    ],
)
def test_unsafe_brain_folder_entry_is_rejected_at_load(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("BRAIN_FOLDERS", raw)
    with pytest.raises(ConfigError):
        load_settings()


def test_empty_brain_folders_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAIN_FOLDERS", " , ,")
    with pytest.raises(ConfigError):
        load_settings()


def test_unsafe_entry_is_rejected_even_alongside_safe_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BRAIN_FOLDERS", "context,../escape,decisions")
    with pytest.raises(ConfigError):
        load_settings()
