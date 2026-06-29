"""Entry point for the Jarvis AI Operating System."""

from config.constants import APP_NAME, APP_VERSION, STARTUP_BANNER
from config.settings import ConfigError, load_settings


def main() -> None:
    """Start Jarvis."""
    print(f"{APP_NAME} v{APP_VERSION}")

    try:
        settings = load_settings()
    except ConfigError as error:
        print(f"Configuration error: {error}")
        return

    print(f"Configuration loaded. Model: {settings.ai_model}")
    print(STARTUP_BANNER)


if __name__ == "__main__":
    main() 