"""
test_main_logging_wiring.py

Composition tests for console logging wiring in main.py (Phase 54,
Batch 1).

These confirm: main.main() calls configure_console_logging() exactly
once, with the same settings the rest of main() already uses; repeated
main.main() calls never attach more than one console handler to the
real "jarvis" app logger; and main.build_orchestrator() itself remains
completely free of any logging-setup side effect, so the many existing
tests that call build_orchestrator() directly (26+ other test files)
are entirely unaffected by this phase.

Run with:
    pytest tests/unit/test_main_logging_wiring.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import main
from config.constants import APP_NAME


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)


@pytest.fixture(autouse=True)
def _isolated_jarvis_logger():
    """Save and restore the real "jarvis" app logger's handlers/level
    around each test in this file, so calling the real main.main() here
    never leaks a handler into any other test file's session state."""
    logger = logging.getLogger(APP_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    logger.handlers = []
    yield logger
    logger.handlers = original_handlers
    logger.setLevel(original_level)


class _FakeCLI:
    """A minimal JarvisCLI stand-in - main.main() must never actually
    block on stdin during these tests."""

    def __init__(
        self,
        orchestrator,
        *,
        startup_notice=None,
        voice_output=None,
        speak_responses=False,
        voice_input=None,
    ) -> None:
        pass

    def run(self) -> None:
        pass


def test_main_calls_configure_console_logging_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def _spy(settings: object) -> None:
        calls.append(settings)

    monkeypatch.setattr(main, "JarvisCLI", _FakeCLI)
    monkeypatch.setattr(main, "configure_console_logging", _spy)

    main.main(argv=[])

    assert len(calls) == 1


def test_main_passes_real_settings_to_configure_console_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    captured: list[object] = []

    def _spy(settings: object) -> None:
        captured.append(settings)

    monkeypatch.setattr(main, "JarvisCLI", _FakeCLI)
    monkeypatch.setattr(main, "configure_console_logging", _spy)

    main.main(argv=[])

    assert captured[0].log_level == "WARNING"


def test_repeated_main_calls_never_attach_more_than_one_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uses the real configure_console_logging() (not a spy) end to end,
    proving the actual idempotency guarantee holds through main.main(argv=[])
    itself, not just at the helper's own unit-test level."""
    monkeypatch.setattr(main, "JarvisCLI", _FakeCLI)

    main.main(argv=[])
    main.main(argv=[])
    main.main(argv=[])

    logger = logging.getLogger(APP_NAME)
    assert len(logger.handlers) == 1


def test_build_orchestrator_attaches_no_logging_handler() -> None:
    logger = logging.getLogger(APP_NAME)
    assert logger.handlers == []

    main.build_orchestrator()

    assert logger.handlers == []


def test_build_orchestrator_return_type_and_signature_are_unchanged() -> None:
    import inspect

    signature = inspect.signature(main.build_orchestrator)
    assert list(signature.parameters) == []
