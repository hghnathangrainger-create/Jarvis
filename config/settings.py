"""
settings.py

Centralised configuration loading for the Jarvis AI Operating System.

Responsibilities:
    - Load environment variables from a .env file into the process environment.
    - Validate that all required configuration variables are present and non-empty.
    - Expose a single, immutable Settings object that the rest of Jarvis reads from.
    - Convert and validate typed values (integers, booleans, paths) at load time.

Does NOT:
    - Implement any AI provider logic.
    - Implement any database or storage logic.
    - Implement any application, planning, or workflow logic.

This module is the single source of truth for configuration. No other module
should read os.environ directly; all configuration access goes through the
Settings object returned by load_settings().
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when configuration is missing, empty, or invalid.

    This is the single exception type for all configuration problems so that
    callers can catch configuration failures distinctly from runtime errors.
    """


# Names of variables that MUST be present and non-empty in the environment.
_REQUIRED_VARS: Final[tuple[str, ...]] = ("ANTHROPIC_API_KEY",)


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable container for all Jarvis configuration values.

    Instances are produced exclusively by load_settings(). The frozen dataclass
    guarantees that configuration cannot be mutated after loading, preventing
    accidental changes to configuration during the program's lifetime.

    Attributes:
        anthropic_api_key: API key used to authenticate with the Claude API.
        ai_model: Identifier of the Claude model to use for requests.
        ai_max_tokens: Maximum number of tokens to request in a single AI call.
        ai_reasoning_enabled: Whether live AI reasoning is switched on. When
            False (the default), Jarvis runs entirely rule-based and never calls
            a provider, so no API key or credits are required.
        database_path: Filesystem path to the SQLite database file.
        log_level: Logging verbosity level (e.g. "DEBUG", "INFO", "WARNING").
        approval_timeout_seconds: Seconds to wait for a YELLOW-tier approval
            before the action is aborted.
        debug: Whether the application is running in debug mode.
    """

    anthropic_api_key: str
    ai_model: str
    ai_max_tokens: int
    database_path: Path
    log_level: str
    approval_timeout_seconds: int
    debug: bool
    ai_reasoning_enabled: bool = False


def _get_required(name: str) -> str:
    """Read a required environment variable.

    Args:
        name: The name of the environment variable to read.

    Returns:
        The variable's value with surrounding whitespace stripped.

    Raises:
        ConfigError: If the variable is missing or empty after stripping.
    """
    raw = os.environ.get(name)
    if raw is None:
        raise ConfigError(
            f"Required environment variable '{name}' is not set. "
            f"Add it to your .env file. See .env.example for the expected format."
        )

    value = raw.strip()
    if not value:
        raise ConfigError(
            f"Required environment variable '{name}' is set but empty. "
            f"Provide a non-empty value in your .env file."
        )

    return value


def _get_optional(name: str, default: str) -> str:
    """Read an optional environment variable, falling back to a default.

    Args:
        name: The name of the environment variable to read.
        default: The value to use when the variable is missing or empty.

    Returns:
        The variable's stripped value, or the default if unset or empty.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default

    value = raw.strip()
    return value if value else default


def _get_int(name: str, default: int) -> int:
    """Read an optional environment variable and parse it as an integer.

    Args:
        name: The name of the environment variable to read.
        default: The value to use when the variable is missing or empty.

    Returns:
        The parsed integer value, or the default if unset or empty.

    Raises:
        ConfigError: If the variable is set but cannot be parsed as an integer,
            or if the parsed value is not positive.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigError(
            f"Environment variable '{name}' must be an integer, got '{value}'."
        ) from exc

    if parsed <= 0:
        raise ConfigError(
            f"Environment variable '{name}' must be a positive integer, got {parsed}."
        )

    return parsed


def _get_bool(name: str, default: bool) -> bool:
    """Read an optional environment variable and parse it as a boolean.

    Accepted true values (case-insensitive): "1", "true", "yes", "on".
    Accepted false values (case-insensitive): "0", "false", "no", "off".

    Args:
        name: The name of the environment variable to read.
        default: The value to use when the variable is missing or empty.

    Returns:
        The parsed boolean value, or the default if unset or empty.

    Raises:
        ConfigError: If the variable is set but is not a recognised boolean.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False

    raise ConfigError(
        f"Environment variable '{name}' must be a boolean "
        f"(true/false, yes/no, 1/0, on/off), got '{raw.strip()}'."
    )


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load, validate, and return application configuration.

    This function loads variables from the .env file into the process
    environment, validates that all required variables are present and
    non-empty, parses typed values, and returns an immutable Settings object.

    Existing environment variables are not overwritten by the .env file, so
    values already set in the real environment take precedence. This allows
    deployment environments to override .env without editing the file.

    Args:
        env_file: Optional path to a .env file. When None, python-dotenv
            searches for a .env file starting from the current working
            directory and walking upward. A non-existent path is tolerated;
            configuration may still come from the real environment.

    Returns:
        A fully populated, immutable Settings instance.

    Raises:
        ConfigError: If any required variable is missing, empty, or if any
            typed variable cannot be parsed into its expected type.
    """
    if env_file is None:
        load_dotenv(override=False)
    else:
        load_dotenv(dotenv_path=Path(env_file), override=False)

    return Settings(
        anthropic_api_key=_get_required("ANTHROPIC_API_KEY"),
        ai_model=_get_optional("AI_MODEL", "claude-sonnet-4-6"),
        ai_max_tokens=_get_int("AI_MAX_TOKENS", 4096),
        ai_reasoning_enabled=_get_bool("AI_REASONING_ENABLED", False),
        database_path=Path(_get_optional("DATABASE_PATH", "data/jarvis.db")),
        log_level=_get_optional("LOG_LEVEL", "INFO").upper(),
        approval_timeout_seconds=_get_int("APPROVAL_TIMEOUT_SECONDS", 60),
        debug=_get_bool("DEBUG", False),
    )
