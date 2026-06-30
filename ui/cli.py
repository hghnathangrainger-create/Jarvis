"""
cli.py

Terminal interface for the Jarvis AI Operating System (Phase 1).

Responsibilities:
    - Start an interactive read-eval-print loop on the terminal.
    - Pass each typed request to JarvisOrchestrator.handle_request().
    - Format and print the response, clearly distinguishing OK, NEEDS
      CONFIRMATION, BLOCKED, and NOT HANDLED outcomes.
    - Recognise exit commands and end the session cleanly.

Does NOT:
    - Call the Claude API, add voice, or add phone support.
    - Execute anything itself or bypass the Core or ToolExecutor.
    - Implement orchestration, planning, or security logic.

The CLI is a thin presentation layer. All decisions are made by the Core; the
CLI only reads input, forwards it, and prints what comes back. The formatting
and exit-detection logic is kept as pure functions so it can be tested without
a terminal.
"""

from __future__ import annotations

from collections.abc import Callable

from config.constants import APP_NAME, STARTUP_BANNER
from core.orchestrator import JarvisOrchestrator
from core.request_models import JarvisResponse

#: Commands that end the session, matched case-insensitively.
_EXIT_COMMANDS: frozenset[str] = frozenset({"exit", "quit", "bye"})

#: Status labels shown to the user for each kind of response.
_STATUS_OK = "OK"
_STATUS_CONFIRM = "NEEDS CONFIRMATION"
_STATUS_BLOCKED = "BLOCKED"
_STATUS_NOT_HANDLED = "NOT HANDLED"

_PROMPT = "you> "
_GOODBYE = "Jarvis Offline. Goodbye."


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

            text = raw.strip()
            if not text:
                continue

            if is_exit_command(text):
                self._output(_GOODBYE)
                return

            response = self._orchestrator.handle_request(text)
            self._output(format_response(response))

    def _print_banner(self) -> None:
        """Print the startup banner and a short usage hint."""
        self._output(STARTUP_BANNER)
        self._output(f"{APP_NAME} Phase 1 CLI. Type 'exit', 'quit', or 'bye' to leave.")
        self._output("")