"""
security_smoke_test.py

A standalone smoke test for the Jarvis Security Manager.

Run this directly (no pytest needed) to see how a range of sample actions are
classified into GREEN, YELLOW, and RED, along with the reason for each.

Place this file in the project root and run it from PowerShell:

    poetry run python security_smoke_test.py
"""

from __future__ import annotations

from config.constants import SecurityTier
from security.security_manager import SecurityManager

# A representative spread of actions across all three tiers, plus an
# unrecognised action to show the cautious default.
_SAMPLE_ACTIONS: tuple[str, ...] = (
    "search memories",
    "list files",
    "read file report.txt",
    "summarise this document",
    "send email to Alex",
    "install software package",
    "delete file report.txt",
    "download installer.exe",
    "rename project folder",
    "delete all files in folder",
    "format drive C",
    "disable antivirus",
    "steal password from browser",
    "do a barrel roll",
)

# Console symbols for each tier, for quick visual scanning.
_TIER_SYMBOL = {
    SecurityTier.GREEN: "[GREEN ]",
    SecurityTier.YELLOW: "[YELLOW]",
    SecurityTier.RED: "[RED   ]",
}


def main() -> None:
    """Classify each sample action and print the result."""
    manager = SecurityManager()

    print("Jarvis Security Manager - sample classifications")
    print("=" * 70)

    for action in _SAMPLE_ACTIONS:
        decision = manager.classify_action(action)
        symbol = _TIER_SYMBOL[decision.tier]
        print(f"{symbol}  {action}")
        print(f"           reason: {decision.reason}")
        if decision.matched_keyword is not None:
            print(f"           matched: '{decision.matched_keyword}'")
        print()

    print("=" * 70)
    print("GREEN  = allowed automatically")
    print("YELLOW = requires user confirmation")
    print("RED    = blocked by default")


if __name__ == "__main__":
    main()