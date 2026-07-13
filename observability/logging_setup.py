"""
logging_setup.py

Console logging setup for the Jarvis AI Operating System (Phase 54,
Batch 1).

Responsibilities:
    - Attach a single console handler to the "jarvis" app logger - the
      same logger observability.logger.EventLogger already routes every
      structured event through via logging.getLogger(APP_NAME) - so that
      log level actually controls what appears on the console. This
      closes the gap Phase 47/48 documented: LOG_LEVEL was validated in
      Phase 46, but nothing ever attached a handler, so INFO-level
      events were silently swallowed regardless of the setting's value.
    - Set that logger's level from the already-validated
      config.settings.Settings.log_level field. No new setting is
      introduced; LOG_LEVEL's existing validated values (Phase 46) are
      used exactly as they already are.
    - Do so idempotently: calling configure_console_logging() more than
      once in the same process must never attach a second handler.

Does NOT:
    - Configure structured/JSON logging, a log file, or log rotation.
    - Introduce a new setting or a new third-party dependency - only the
      standard library's logging module is used.
    - Get called from main.build_orchestrator(), scheduler.py's
      build_components(), or any other shared construction path - only
      from a real process entry point. main.py's main() is wired in
      Batch 1; scheduler.py's main() is Batch 2, not yet wired.
    - Touch dashboard.py - it has no logging calls of any kind.
"""

from __future__ import annotations

import logging

from config.constants import APP_NAME
from config.settings import Settings


def configure_console_logging(settings: Settings) -> None:
    """Attach a console handler to the Jarvis app logger, exactly once.

    Sets the logger's level from settings.log_level - already validated
    by config.settings.load_settings() against config.constants.LogLevel
    (Phase 46), so every accepted value here is guaranteed to be a real
    logging level name. If a handler is already attached to this logger
    (for example, because this function was already called once earlier
    in the same process), attaching a handler is skipped - this is what
    makes repeated calls safe: they can never result in duplicated
    console output.

    Args:
        settings: The already-loaded Settings object. This function
            never calls load_settings() itself.
    """
    logger = logging.getLogger(APP_NAME)
    logger.setLevel(getattr(logging, settings.log_level))

    if logger.handlers:
        return

    logger.addHandler(logging.StreamHandler())
