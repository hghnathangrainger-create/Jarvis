"""
cli.py

Terminal interface for the Jarvis AI Operating System.

Responsibilities:
    - Start an interactive read-eval-print loop on the terminal.
    - Pass each typed request to JarvisOrchestrator.handle_request().
    - Format and print the response, clearly distinguishing OK, NEEDS
      CONFIRMATION, BLOCKED, and NOT HANDLED outcomes.
    - When a response carries an approval request (a YELLOW action), present
      the approval prompt and record the user's approve/decline decision.
    - Recognise exit commands and end the session cleanly.

Does NOT:
    - Call the Claude API, add voice, or add phone support.
    - Execute approved actions itself (that is handled in a later step) or
      bypass the Core or ToolExecutor.
    - Implement orchestration, planning, or security logic.

The CLI is a thin presentation layer. All decisions about risk are made by the
Core and Security Manager; the CLI only reads input, forwards it, prints what
comes back, and - for sensitive actions - asks the user to approve or decline.
The formatting and exit-detection logic is kept as pure functions so it can be
tested without a terminal, and input/output are injected for the same reason.
"""

from __future__ import annotations

from collections.abc import Callable

from approval.approval_models import ApprovalDecision
from config.constants import APP_NAME, STARTUP_BANNER
from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse
from ui.approval_prompt import prompt_for_approval

#: Commands that end the session, matched case-insensitively.
_EXIT_COMMANDS: frozenset[str] = frozenset({"exit", "quit", "bye"})

#: Status labels shown to the user for each kind of response.
_STATUS_OK = "OK"
_STATUS_CONFIRM = "NEEDS CONFIRMATION"
_STATUS_BLOCKED = "BLOCKED"
_STATUS_NOT_HANDLED = "NOT HANDLED"

_PROMPT = "you> "
_GOODBYE = "Jarvis Offline. Goodbye."

#: Prompt prefixes that may be accidentally pasted at the start of a request.
#: Both the full prompt ("you> ") and its trimmed form ("you>") are handled.
_PROMPT_PREFIXES: tuple[str, ...] = ("you>", "jarvis>")


def strip_prompt_prefix(text: str) -> str:
    """Remove an accidentally pasted prompt prefix from the start of input.

    When a user copies a whole line from the terminal, the leading prompt
    (for example "you> ") can end up in the pasted text. This removes a single
    such prefix so that "you> exit" behaves exactly like "exit". Only one
    prefix is removed, and only when it appears at the very start.

    Args:
        text: The raw user input.

    Returns:
        The input with a single leading prompt prefix removed, if present, and
        with surrounding whitespace stripped.
    """
    cleaned = text.strip()
    lowered = cleaned.casefold()
    for prefix in _PROMPT_PREFIXES:
        if lowered.startswith(prefix):
            return cleaned[len(prefix) :].strip()
    return cleaned


def is_exit_command(text: str) -> bool:
    """Report whether the given input is an exit command.

    Args:
        text: The raw user input.

    Returns:
        True if the input, trimmed and lowercased, is an exit command.
    """
    return text.strip().casefold() in _EXIT_COMMANDS


def status_for(response: JarvisResponse) -> str:
    """Return the status label that describes a response.

    The checks are ordered by severity so the most important status is shown:
    blocked first, then needs-confirmation, then success, then not-handled.

    Args:
        response: The response to label.

    Returns:
        One of the status label strings.
    """
    if response.blocked:
        return _STATUS_BLOCKED
    if response.requires_confirmation:
        return _STATUS_CONFIRM
    if response.success:
        return _STATUS_OK
    return _STATUS_NOT_HANDLED


def format_response(response: JarvisResponse) -> str:
    """Format a response for display in the terminal.

    The first line shows the status and the response message. If the response
    includes a plan, each step is listed beneath it with its security tier.

    Args:
        response: The response to format.

    Returns:
        A multi-line string ready to print.
    """
    status = status_for(response)
    message_lines = response.message.splitlines() or [""]

    lines = [f"jarvis> [{status}] {message_lines[0]}"]
    lines.extend(f"        {line}" for line in message_lines[1:])

    if response.plan is not None and response.plan.steps:
        lines.append("        plan:")
        for step in response.plan.steps:
            lines.append(
                f"          {step.number}. [{step.tier.name}] {step.description}"
            )

    return "\n".join(lines)


def format_decision(
    decision: ApprovalDecision, action: str | None = None
) -> str:
    """Format the feedback shown after the user approves or declines.

    Args:
        decision: The recorded approval decision.
        action: The action the decision applies to. When provided, it is named
            in the feedback so the user sees exactly what was approved or
            cancelled.

    Returns:
        A single line clearly stating the outcome. An approval notes that the
        action will run; a decline notes it was cancelled and did not run.
    """
    subject = f" '{action}'" if action else " this action"
    if decision.is_approved:
        return f"jarvis> [APPROVED] You approved{subject}."
    return (
        f"jarvis> [DECLINED] You declined{subject}. "
        "It has been cancelled and will not run."
    )


class JarvisCLI:
    """Drives an interactive terminal session backed by the Core.

    Input and output are injected so the loop can be tested without a real
    terminal. By default they are the built-in input and print.

    Attributes:
        _orchestrator: The Core orchestrator that handles each request.
        _input: Callable used to read a line of input given a prompt.
        _output: Callable used to write a line of output.
    """

    def __init__(
        self,
        orchestrator: JarvisOrchestrator,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        """Initialise the CLI.

        Args:
            orchestrator: The Core orchestrator to forward requests to.
            input_fn: Function used to read input. Defaults to input.
            output_fn: Function used to write output. Defaults to print.
        """
        self._orchestrator = orchestrator
        self._input = input_fn
        self._output = output_fn

    def run(self) -> None:
        """Run the interactive loop until an exit command or end of input.

        The loop prints the startup banner, then repeatedly reads a request,
        forwards it to the Core, and prints the formatted response. It ends on
        an exit command, or cleanly on end-of-input (EOF) or interruption.
        """
        self._print_banner()

        while True:
            try:
                raw = self._input(_PROMPT)
            except (EOFError, KeyboardInterrupt):
                self._output("")
                self._output(_GOODBYE)
                return

            text = strip_prompt_prefix(raw)
            if not text:
                continue

            if is_exit_command(text):
                self._output(_GOODBYE)
                return

            response = self._orchestrator.handle_request(text)
            self._output(format_response(response))

            if response.approval_request is not None:
                self._handle_approval(response)

    def _handle_approval(self, response: JarvisResponse) -> None:
        """Present the approval prompt for a YELLOW action and act on the answer.

        The pending request carried on the response is shown to the user via the
        existing approval prompt. The decision is recorded through the Core's
        ApprovalManager so it is stored and audited. If the user approves, the
        action is then executed through the Core, which re-runs the original
        tool through the ToolExecutor with the approval decision. If the user
        declines, nothing is executed.

        Args:
            response: The response carrying a pending approval_request.
        """
        request = response.approval_request
        if request is None:  # Defensive: caller checks, but keep this safe.
            return

        answer = prompt_for_approval(
            request,
            input_func=self._input,
            output_func=self._output,
        )

        # Record the decision through the Core's ApprovalManager so it is stored
        # and written to the audit log. The manager returns the authoritative
        # decision.
        try:
            if answer.is_approved:
                decision = self._orchestrator.approvals.approve(
                    request.request_id, decided_by=answer.decided_by
                )
            else:
                decision = self._orchestrator.approvals.decline(
                    request.request_id, decided_by=answer.decided_by
                )
        except Exception:  # noqa: BLE001 - never let recording crash the loop
            self._output(
                "jarvis> [ERROR] Could not record the approval decision."
            )
            return

        self._output(format_decision(decision, request.action))

        # If approved, run the action now through the Core (which re-runs the
        # tool through the ToolExecutor with the decision). Declined actions do
        # nothing further.
        if decision.is_approved:
            executed = self._orchestrator.execute_approved(response, decision)
            self._output(format_response(executed))

    def _print_banner(self) -> None:
        """Print the startup banner and a short usage hint."""
        self._output(STARTUP_BANNER)
        self._output(f"{APP_NAME} interactive CLI.")
        self._output("Type only your request after the prompt.")
        self._output("Do not type the 'you>' prompt text itself.")
        self._output("Type 'exit', 'quit', or 'bye' to leave.")
        self._output("")