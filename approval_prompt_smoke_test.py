"""
approval_prompt_smoke_test.py

A standalone smoke test for the Jarvis CLI approval prompts.

Run this directly (no pytest needed) to see how an approval request is
displayed and how the prompt handles approval, decline, and invalid-then-valid
input. The answers are scripted, so it runs without any typing.

Place this file in the project root and run it from PowerShell:

    poetry run python approval_prompt_smoke_test.py
"""

from __future__ import annotations

from collections.abc import Iterator

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier
from ui.approval_prompt import prompt_for_approval


def _scripted(answers: list[str]):
    """Return an input function that yields each scripted answer in turn."""
    iterator: Iterator[str] = iter(answers)

    def _input(prompt: str) -> str:
        answer = next(iterator)
        # Echo what the "user" typed so the transcript reads naturally.
        print(f"{prompt}{answer}")
        return answer

    return _input


def _new_request() -> ApprovalRequest:
    """Build a fresh sample YELLOW request."""
    return ApprovalRequest(
        action="send email to Alex",
        reason="Sending an email communicates on your behalf.",
        security_tier=SecurityTier.YELLOW,
        metadata={"to": "alex@example.com", "subject": "Project update"},
    )


def main() -> None:
    """Run three scripted approval scenarios."""
    print("Jarvis Approval Prompt - smoke test")
    print("=" * 70)
    print()

    print("Scenario 1: the user approves")
    decision = prompt_for_approval(_new_request(), input_func=_scripted(["yes"]))
    print(f"  -> decision: {'APPROVED' if decision.is_approved else 'DECLINED'}")
    print()

    print("Scenario 2: the user declines")
    decision = prompt_for_approval(_new_request(), input_func=_scripted(["no"]))
    print(f"  -> decision: {'APPROVED' if decision.is_approved else 'DECLINED'}")
    print()

    print("Scenario 3: invalid input, then approve")
    decision = prompt_for_approval(
        _new_request(), input_func=_scripted(["maybe", "huh?", "approve"])
    )
    print(f"  -> decision: {'APPROVED' if decision.is_approved else 'DECLINED'}")
    print()

    print("=" * 70)
    print("The prompt displays the request, accepts y/yes/approve or")
    print("n/no/decline/cancel, and re-asks on anything it does not recognise.")


if __name__ == "__main__":
    main()