"""Entry point for the Jarvis AI Operating System."""

from config.constants import APP_NAME, APP_VERSION, STARTUP_BANNER


def main() -> None:
    """Start Jarvis."""
    print(f"{APP_NAME} v{APP_VERSION}")
    print(STARTUP_BANNER)


if __name__ == "__main__":
    main() 