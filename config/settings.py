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

from config.constants import LogLevel


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
        log_level: Logging verbosity level. Must be one of LogLevel's own
            values ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            validated at load time (Phase 46); the raw environment value
            is upper-cased before validation, so "debug"/"Debug"/"DEBUG"
            all normalise to the same stored value. Not yet wired into
            any actual logging verbosity - see observability/logger.py;
            this field is currently read, validated, and displayed
            (ConfigTool/"show config") only.
        approval_timeout_seconds: Seconds to wait for a YELLOW-tier approval
            before the action is aborted.
        debug: Whether the application is running in debug mode.
        voice_enabled: Whether the voice output subsystem is switched on
            at all (Phase 41, Batch 2). When False (the default), no
            TTS provider is ever constructed and the CLI never attempts
            to speak a response - Jarvis behaves exactly as it always
            has. There is no real TTS provider yet regardless of this
            flag; see voice_provider.
        voice_speak_mode: Whether the CLI should actually attempt to
            speak a response once voice is enabled. One of "off" (never
            attempt to speak, even if voice_enabled is True - the
            default, matching Nathan's own "opt-in, not every response
            by default" decision) or "all" (attempt to speak every
            response). A separate flag from voice_enabled so that
            turning voice "on" and choosing to actually hear every
            response are two independent, both-required decisions.
        voice_provider: Which TextToSpeechProvider to construct, if any.
            One of "none" (no provider is constructed; voice is
            inactive regardless of voice_enabled/voice_speak_mode - the
            default) or "fake" (constructs FakeTextToSpeechProvider,
            voice/tts.py's own silent, audio-free test/wiring provider -
            never real audio). No real TTS engine value exists yet;
            Nathan has not chosen one (docs/phase_41_implementation_plan.md).
        voice_input_enabled: Whether the voice input subsystem is
            switched on at all (Phase 41, Batch 4). When False (the
            default), no STT provider is ever constructed and nothing
            in the CLI ever attempts to transcribe anything - Jarvis
            behaves exactly as it always has. There is no microphone,
            no audio capture, and no real STT provider yet regardless
            of this flag; see voice_input_provider.
        voice_input_provider: Which SpeechToTextProvider to construct,
            if any. One of "none" (no provider is constructed; voice
            input is inactive regardless of voice_input_enabled - the
            default) or "fake" (constructs FakeSpeechToTextProvider,
            voice/stt.py's own silent, microphone-free test/wiring
            provider - never real audio or a real microphone). No real
            STT engine value exists yet; Nathan has not chosen one
            (docs/phase_41_implementation_plan.md).
        brain_enabled: Whether the external Markdown "3D brain" integration
            is switched on at all (default False). When False, every brain
            command reports honestly that the integration is disabled; no
            filesystem path is ever scanned.
        brain_path: Root directory of the Markdown brain (Windows paths
            accepted, e.g. "C:/Users/NathanGrainger/mi-aios"). Empty when
            not configured. Jarvis never scans outside this root.
        brain_folders: The included Markdown subfolders directly under
            brain_path, in declared order. Validated at load time to be
            single, non-hidden, non-excluded path segments only.
        brain_max_file_bytes: Maximum size of a note scanned during a
            brain search, and the read bound applied when showing a note.
        brain_search_limit: Default maximum number of brain search results
            returned in one search.
        brain_ai_context_chars: Fixed character budget for the combined
            brain excerpts supplied to advisory AI reasoning.
    """

    anthropic_api_key: str
    ai_model: str
    ai_max_tokens: int
    database_path: Path
    log_level: str
    approval_timeout_seconds: int
    debug: bool
    ai_reasoning_enabled: bool = False
    voice_enabled: bool = False
    voice_speak_mode: str = "off"
    voice_provider: str = "none"
    voice_input_enabled: bool = False
    voice_input_provider: str = "none"
    openai_api_key: str = ""
    google_api_key: str = ""
    wake_word: str = "jarvis"
    stt_provider: str = "whisper"
    tts_provider: str = "pyttsx3"
    voice_language: str = "en"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_username: str = "admin"
    api_password: str = "changeme"
    cors_origins: str = "*"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"
    cost_budget_daily: float | None = None
    cost_budget_monthly: float | None = None
    ai_preferred_provider: str | None = None
    security_injection_sensitivity: str = "medium"
    security_approval_ttl_seconds: int = 300
    security_log_all_green: bool = False
    brain_enabled: bool = False
    brain_path: str = ""
    brain_folders: tuple[str, ...] = (
        "context",
        "decisions",
        "references",
        "audits",
        "brainstorms",
    )
    brain_max_file_bytes: int = 262_144
    brain_search_limit: int = 25
    brain_ai_context_chars: int = 4_000


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


def _get_choice(name: str, default: str, choices: tuple[str, ...]) -> str:
    """Read an optional environment variable, restricted to a fixed set
    of accepted values.

    Args:
        name: The name of the environment variable to read.
        default: The value to use when the variable is missing or empty.
        choices: The exact, case-sensitive set of accepted values.

    Returns:
        The variable's stripped value, or the default if unset or empty.

    Raises:
        ConfigError: If the variable is set to a value not in choices.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip()
    if value not in choices:
        raise ConfigError(
            f"Environment variable '{name}' must be one of "
            f"{choices}, got '{value}'."
        )

    return value


def _get_log_level(name: str, default: str) -> str:
    """Read an optional environment variable and validate it as a log level.

    Deliberately not implemented via _get_choice() (Phase 46): that helper
    is case-sensitive, and is shared with several other settings (e.g. the
    voice ones) that must keep their own exact-case behaviour unchanged.
    This helper preserves LOG_LEVEL's own pre-existing, separate
    behaviour instead - the raw value is upper-cased before validation,
    so "debug"/"Debug"/"DEBUG" all normalise to the same accepted value,
    matching what LOG_LEVEL has always accepted (previously without any
    validation at all).

    Args:
        name: The name of the environment variable to read.
        default: The value to use when the variable is missing or empty.
            Must already be one of LogLevel's own values.

    Returns:
        The upper-cased, validated log level string, or the default if
        unset or empty.

    Raises:
        ConfigError: If the variable is set (after upper-casing) to a
            value that is not one of LogLevel's own values.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip().upper()
    valid_levels = tuple(level.value for level in LogLevel)
    if value not in valid_levels:
        raise ConfigError(
            f"Environment variable '{name}' must be one of "
            f"{valid_levels}, got '{raw.strip()}'."
        )

    return value


def _get_brain_folders(name: str, default: str) -> tuple[str, ...]:
    """Read and validate BRAIN_FOLDERS - the included Markdown subfolders.

    The value is a comma-separated list of relative folder names under the
    configured BRAIN_PATH root (for example
    "context,decisions,references,audits,brainstorms"). Each entry must be
    a single, safe path segment: non-empty, not "." or "..", never
    absolute, never containing a path separator, never starting with "."
    (so no hidden folder can be included), and never one of the excluded
    directory names Jarvis refuses to scan ("apps", "node_modules",
    "__pycache__", "venv"). This validation is what guarantees Jarvis can
    never be configured to scan outside the configured root or into a
    hidden/excluded folder.

    Args:
        name: The environment variable to read.
        default: Fallback value used when the variable is unset or empty.

    Returns:
        The validated tuple of folder names, in their declared order.

    Raises:
        ConfigError: If the variable is set but any entry is not a single,
            safe folder name.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return _split_brain_folders(default)

    entries = _split_brain_folders(raw)
    if not entries:
        raise ConfigError(
            f"Environment variable '{name}' must name at least one "
            "included Markdown subfolder, got an empty list."
        )

    forbidden = {"apps", "node_modules", "__pycache__", "venv"}
    for entry in entries:
        if entry in {".", ".."}:
            raise ConfigError(
                f"Environment variable '{name}' contains an invalid "
                f"folder name {entry!r}; '.' and '..' are never allowed."
            )
        if entry.startswith("."):
            raise ConfigError(
                f"Environment variable '{name}' contains a hidden folder "
                f"name {entry!r}; hidden folders are never scanned."
            )
        if "/" in entry or "\\" in entry or ":" in entry:
            raise ConfigError(
                f"Environment variable '{name}' contains {entry!r}; each "
                "entry must be a single folder name directly under the "
                "BRAIN_PATH root, without path separators."
            )
        if entry in forbidden:
            raise ConfigError(
                f"Environment variable '{name}' contains {entry!r}, which "
                "is always excluded from brain scanning."
            )
    return entries


def _split_brain_folders(raw: str) -> tuple[str, ...]:
    """Split a comma-separated folder list, dropping empty entries.

    Args:
        raw: The raw comma-separated value.

    Returns:
        The stripped, non-empty entries in declared order.
    """
    return tuple(
        part.strip() for part in raw.split(",") if part.strip()
    )


def _get_optional_float(name: str, default: float | None) -> float | None:
    """Read an optional environment variable and parse it as a float.

    Args:
        name: The name of the environment variable to read.
        default: The value to use when the variable is missing or empty.

    Returns:
        The parsed float value, or the default if unset or empty.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    try:
        return float(raw.strip())
    except ValueError:
        return default


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
        log_level=_get_log_level("LOG_LEVEL", "INFO"),
        approval_timeout_seconds=_get_int("APPROVAL_TIMEOUT_SECONDS", 60),
        debug=_get_bool("DEBUG", False),
        voice_enabled=_get_bool("VOICE_ENABLED", False),
        voice_speak_mode=_get_choice("VOICE_SPEAK_MODE", "off", ("off", "all")),
        voice_provider=_get_choice("VOICE_PROVIDER", "none", ("none", "fake")),
        voice_input_enabled=_get_bool("VOICE_INPUT_ENABLED", False),
        voice_input_provider=_get_choice(
            "VOICE_INPUT_PROVIDER", "none", ("none", "fake")
        ),
        openai_api_key=_get_optional("OPENAI_API_KEY", ""),
        google_api_key=_get_optional("GOOGLE_API_KEY", ""),
        wake_word=_get_optional("WAKE_WORD", "jarvis"),
        stt_provider=_get_choice("STT_PROVIDER", "whisper", ("whisper", "fake")),
        tts_provider=_get_choice("TTS_PROVIDER", "pyttsx3", ("pyttsx3", "fake")),
        voice_language=_get_optional("VOICE_LANGUAGE", "en"),
        api_host=_get_optional("API_HOST", "0.0.0.0"),
        api_port=_get_int("API_PORT", 8000),
        api_username=_get_optional("API_USERNAME", "admin"),
        api_password=_get_optional("API_PASSWORD", "changeme"),
        cors_origins=_get_optional("CORS_ORIGINS", "*"),
        ollama_base_url=_get_optional("OLLAMA_BASE_URL", "http://localhost:11434"),
        ollama_model=_get_optional("OLLAMA_MODEL", "llama3"),
        cost_budget_daily=_get_optional_float("COST_BUDGET_DAILY", None),
        cost_budget_monthly=_get_optional_float("COST_BUDGET_MONTHLY", None),
        ai_preferred_provider=_get_optional("AI_PREFERRED_PROVIDER", None),
        security_injection_sensitivity=_get_choice(
            "SECURITY_INJECTION_SENSITIVITY", "medium", ("low", "medium", "high")
        ),
        security_approval_ttl_seconds=_get_int("SECURITY_APPROVAL_TTL_SECONDS", 300),
        security_log_all_green=_get_bool("SECURITY_LOG_ALL_GREEN", False),
        brain_enabled=_get_bool("BRAIN_ENABLED", False),
        brain_path=_get_optional("BRAIN_PATH", ""),
        brain_folders=_get_brain_folders(
            "BRAIN_FOLDERS",
            "context,decisions,references,audits,brainstorms",
        ),
        brain_max_file_bytes=_get_int("BRAIN_MAX_FILE_BYTES", 262_144),
        brain_search_limit=_get_int("BRAIN_SEARCH_LIMIT", 25),
        brain_ai_context_chars=_get_int("BRAIN_AI_CONTEXT_CHARS", 4_000),
    )
