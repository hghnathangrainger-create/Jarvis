"""
test_scheduler_logging_wiring.py

Composition tests for console logging wiring in scheduler.py (Phase 54,
Batch 2).

These confirm: scheduler.main() calls configure_console_logging() exactly
once, before entering its poll loop; repeated scheduler.main() calls
never attach more than one console handler to the real "jarvis" app
logger; and scheduler.build_components() itself remains completely free
of any logging-setup side effect - mirroring tests/unit/test_main_
logging_wiring.py's own identical proof for main.py exactly.

scheduler.main() runs an infinite `while True: ... time.sleep(...)` poll
loop, so it can never be called directly in a test without a way to
escape it. Each test here monkeypatches scheduler.time.sleep to raise a
small sentinel exception the first time it is called, letting main() run
through build_components() -> configure_console_logging() -> one full
loop iteration -> time.sleep(), at which point the test regains control.
run_one_poll_cycle is stubbed out (its own behaviour is already covered
exhaustively by tests/unit/test_scheduler_runner.py) so these tests stay
focused on logging wiring only.

Run with:
    pytest tests/unit/test_scheduler_logging_wiring.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

import scheduler
from config.constants import APP_NAME


class _StopPollLoop(Exception):
    """Raised by the patched time.sleep() to escape scheduler.main()'s
    infinite loop after exactly one iteration, for test purposes only."""


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_components()
    never touches the real .env file or the real database."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)


@pytest.fixture(autouse=True)
def _isolated_jarvis_logger():
    """Save and restore the real "jarvis" app logger's handlers/level
    around each test in this file, so calling the real scheduler.main()
    here never leaks a handler into any other test file's session
    state."""
    logger = logging.getLogger(APP_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    logger.handlers = []
    yield logger
    logger.handlers = original_handlers
    logger.setLevel(original_level)


@pytest.fixture(autouse=True)
def _stub_run_one_poll_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """run_one_poll_cycle's own behaviour is already covered exhaustively
    by tests/unit/test_scheduler_runner.py - stub it here so these tests
    stay focused on logging wiring only."""
    monkeypatch.setattr(scheduler, "run_one_poll_cycle", lambda *a, **k: 0)


def _run_main_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run scheduler.main() through exactly one poll-loop iteration,
    then escape via the patched time.sleep()."""

    def _sleep_and_stop(_seconds: float) -> None:
        raise _StopPollLoop()

    monkeypatch.setattr(scheduler.time, "sleep", _sleep_and_stop)
    with pytest.raises(_StopPollLoop):
        scheduler.main()


def test_scheduler_main_calls_configure_console_logging_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def _spy(settings: object) -> None:
        calls.append(settings)

    monkeypatch.setattr(scheduler, "configure_console_logging", _spy)

    _run_main_once(monkeypatch)

    assert len(calls) == 1


def test_scheduler_main_passes_real_settings_to_configure_console_logging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    captured: list[object] = []

    def _spy(settings: object) -> None:
        captured.append(settings)

    monkeypatch.setattr(scheduler, "configure_console_logging", _spy)

    _run_main_once(monkeypatch)

    assert captured[0].log_level == "WARNING"


def test_repeated_scheduler_main_calls_never_attach_more_than_one_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uses the real configure_console_logging() (not a spy) end to end,
    proving the actual idempotency guarantee holds through
    scheduler.main() itself, mirroring main.py's own Batch 1 proof."""
    _run_main_once(monkeypatch)
    _run_main_once(monkeypatch)
    _run_main_once(monkeypatch)

    logger = logging.getLogger(APP_NAME)
    assert len(logger.handlers) == 1


def test_build_components_attaches_no_logging_handler() -> None:
    logger = logging.getLogger(APP_NAME)
    assert logger.handlers == []

    scheduler.build_components()

    assert logger.handlers == []


def test_build_components_return_shape_is_unchanged() -> None:
    import inspect

    signature = inspect.signature(scheduler.build_components)
    assert list(signature.parameters) == []
