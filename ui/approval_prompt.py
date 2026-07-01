"""
approval_prompt.py

Terminal prompt for approving or declining a sensitive action (Phase 2).

Responsibilities:
    - Format an ApprovalRequest into clear, readable text.
    - Parse a user's typed answer into approve, decline, or unrecognised.
    - Run an interactive prompt that asks the user to approve or decline,
      re-prompting on unrecognised input, and return an ApprovalDecision.

Does NOT:
    - Connect to the main CLI, the Core, or the Tool Executor.
    - Run the approved action or record it anywhere.
    - Call the Claude API or any AI provider.

The formatting and parsing are pure functions so they can be tested without a
terminal. The interactive prompt takes injected input and output functions,
so the whole flow can be driven by a test with scripted answers.
"""

from __future__ import annotations

from collections.abc import Callable

from approval.approval_models import ApprovalDecision, ApprovalRequest

#: Inputs (lowercased) that mean "approve".
_APPROVE_INPUTS: frozenset[str] = frozenset({"y", "yes", "approve"})

#: Inputs (lowercased) that mean "decline".
_DECLINE_INPUTS: frozenset[str] = frozenset({"n", "no", "decline", "cancel"})

_PROMPT_LINE = "Approve this action? [y]es / [n]o: "
_INVALID_LINE = "Please answer 'y' (yes/approve) or 'n' (no/decline)."


def format_approval_request(request: ApprovalRequest) -> str:
    """Format an approval request into readable, multi-line text.

    The output shows the request id, the action, the reason, the security
    tier, and any metadata, so the user can see exactly what they are being
    asked to approve.

    Args:
        request: The approval request to display.

    Returns:
        A multi-line string ready to print.
    """
    lines = [
        "Approval required",
        "-----------------",
        f"  Request ID: {request.request_id}",
        f"  Action:     {request.action}",
        f"  Reason:     {request.reason}",
        f"  Risk tier:  {request.security_tier.name}",
    ]

    if request.metadata:
        lines.append("  Details:")
        for key in sorted(request.metadata):
            lines.append(f"    - {key}: {request.metadata[key]}")

    return "\n".join(lines)


def parse_approval_input(text: str) -> bool | None:
    """Parse a typed answer into an approve/decline outcome.

    Args:
        text: The raw user input.

    Returns:
        True if the input means approve, False if it means decline, or None if
        the input is not recognised.
    """
    answer = text.strip().casefold()
    if answer in _APPROVE_INPUTS:
        return True
    if answer in _DECLINE_INPUTS:
        return False
    return None


def prompt_for_approval(
    request: ApprovalRequest,
    *,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
    decided_by: str = "user",
) -> ApprovalDecision:
    """Ask the user to approve or decline a request, and return the decision.

    The request is displayed, then the user is prompted for an answer. If the
    answer is not recognised, the prompt explains the valid options and asks
    again. The returned decision is linked to the request by its id.

    Args:
        request: The request to seek approval for.
        input_func: Function used to read a line of input. Defaults to input.
        output_func: Function used to write a line of output. Defaults to print.
        decided_by: Who is making the decision. Defaults to "user".

    Returns:
        An ApprovalDecision (approved or declined) for the request.
    """
    output_func(format_approval_request(request))

    while True:
        raw = input_func(_PROMPT_LINE)
        outcome = parse_approval_input(raw)
        if outcome is None:
            output_func(_INVALID_LINE)
            continue
        return request.decide(approved=outcome, decided_by=decided_by)