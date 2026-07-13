"""
test_logging_setup.py

Unit tests for observability/logging_setup.py (Phase 54, Batch 1).

These prove: configure_console_logging() attaches exactly one console
handler to the "jarvis" app logger, regardless of how many times it is
called in the same process; and the logger's level follows
settings.log_level for every value config.settings.load_settings()
already accepts (Phase 46). The autouse fixture below saves and restores
the real "jarvis" logger's handlers/level around every test in this
file, so nothing here ever leaks a handler into any other test file in
the same pytest session.

Run with:
    pytest tests/unit/test_logging_setup.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from config.constants import APP_NAME
from config.settings import Settings
from observability.logging_setup import configure_console_logging


def _settings(log_level: str = "INFO") -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-real",
        ai_model="m",
        ai_max_tokens=1,
        database_path=Path("x.db"),
        log_level=log_level,
        approval_timeout_seconds=10,
        debug=False,
    )


@pytest.fixture(autouse=True)
def _isolated_jarvis_logger():
    """Save and restore the real "jarvis" app logger's handlers/level
    around each test in this file, so nothing here ever leaks a handler
    into any other test file sharing the same process-wide logger."""
    logger = logging.getLogger(APP_NAME)
    original_handlers = list(logger.handlers)
    original_level = logger.level
    logger.handlers = []
    yield logger
    logger.handlers = original_handlers
    logger.setLevel(original_level)


def test_attaches_exactly_one_handler(_isolated_jarvis_logger) -> None:
    configure_console_logging(_settings())
    assert len(_isolated_jarvis_logger.handlers) == 1


def test_attached_handler_is_a_stream_handler(_isolated_jarvis_logger) -> None:
    configure_console_logging(_settings())
    assert isinstance(_isolated_jarvis_logger.handlers[0], logging.StreamHandler)


def test_calling_twice_does_not_attach_a_second_handler(
    _isolated_jarvis_logger,
) -> None:
    configure_console_logging(_settings())
    configure_console_logging(_settings())
    assert len(_isolated_jarvis_logger.handlers) == 1


def test_calling_many_times_never_attaches_more_than_one_handler(
    _isolated_jarvis_logger,
) -> None:
    for _ in range(10):
        configure_console_logging(_settings())
    assert len(_isolated_jarvis_logger.handlers) == 1


@pytest.mark.parametrize(
    "level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
)
def test_logger_level_follows_settings_log_level(
    _isolated_jarvis_logger, level: str
) -> None:
    configure_console_logging(_settings(log_level=level))
    assert _isolated_jarvis_logger.level == getattr(logging, level)


def test_repeated_calls_with_a_different_level_update_the_level_but_not_handlers(
    _isolated_jarvis_logger,
) -> None:
    """The idempotency guarantee is specifically about handlers, not the
    level - the level is safe to update on every call since setLevel()
    is itself idempotent and has no accumulation risk."""
    configure_console_logging(_settings(log_level="DEBUG"))
    configure_console_logging(_settings(log_level="ERROR"))
    assert _isolated_jarvis_logger.level == logging.ERROR
    assert len(_isolated_jarvis_logger.handlers) == 1
