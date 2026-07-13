"""
cli.py

Terminal interface for the Jarvis AI Operating System.

Responsibilities:
    - Start an interactive read-eval-print loop on the terminal.
    - Pass each typed request to JarvisOrchestrator.handle_request()
      through _handle_text_request() - the single, shared entry point
      every request source in this CLI uses, regardless of origin.
    - Format and print the response, clearly distinguishing OK, NEEDS
      CONFIRMATION, BLOCKED, and NOT HANDLED outcomes.
    - When a response carries an approval request (a YELLOW action), present
      the approval prompt and record the user's approve/decline decision.
    - Recognise exit commands and end the session cleanly.
    - Print one optional, pre-built, content-free startup notice line
      (Phase 22) immediately after the banner, if one was supplied.
    - Optionally speak a response's message through an injected
      VoiceOutputService (Phase 41, Batch 2), best-effort, if both a
      service was supplied and speak_responses is True. Off by default.
    - Optionally produce one request string via an injected
      VoiceInputService (Phase 41, Batch 4, fake provider only) through
      _handle_voice_input_once(), then hand it to the exact same
      _handle_text_request() typed input uses - never a shortcut, never
      a separate execution path. Not reachable from the interactive
      typed-input loop yet; this exists so voice-originated routing can
      be proven safe now, ahead of a future batch's real push-to-talk
      trigger.

Does NOT:
    - Call the Claude API, add phone support, add a microphone, or
      capture real audio of any kind. No real speech-to-text or
      text-to-speech engine is wired in anywhere in this project yet.
    - Execute approved actions itself (that is handled in a later step) or
      bypass the Core or ToolExecutor.
    - Implement orchestration, planning, or security logic.
    - Let a voice-output failure change the printed text response or
      crash the loop - speak() is always best-effort and its result is
      never surfaced as an error to keep this first integration minimal
      (see voice/output.py; a provider failure already returns a safe,
      non-raising SpeechResult).
    - Treat spoken text as anything other than the exact response
      message already decided and printed - it is never re-interpreted,
      routed to CommandRouter, or passed to ToolExecutor/ApprovalManager/
      any AI component. Speaking happens strictly after the response is
      already fully decided.
    - Treat a voice-originated transcription as anything other than an
      ordinary request string. It is never trusted more or less than
      typed input, never given a shortcut around CommandRouter/
      SecurityManager/ApprovalManager, and never executed directly by
      voice code - _handle_voice_input_once() only ever produces a
      string and forwards it to _handle_text_request(), the exact same
      method the typed-input loop calls.

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
from voice.input import VoiceInputService
from voice.output import VoiceOutputService

#: Commands that end the session, matched case-insensitively.
_EXIT_COMMANDS: frozenset[str] = frozenset({"exit", "quit", "bye"})

#: Status labels shown to the user for each kind of response.
_STATUS_OK = "OK"
_STATUS_APPROVAL = "NEEDS APPROVAL"
_STATUS_BLOCKED = "BLOCKED"
_STATUS_FAILED = "FAILED"
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

    The checks are ordered by severity and specificity so the clearest status
    is shown: blocked first (RED), then needs-approval (YELLOW), then success
    (GREEN/OK). For an unsuccessful response, a tool that ran but errored is
    reported as FAILED, while a request nothing could handle is NOT HANDLED.

    Args:
        response: The response to label.

    Returns:
        One of the status label strings.
    """
    if response.blocked:
        return _STATUS_BLOCKED
    if response.requires_confirmation:
        return _STATUS_APPROVAL
    if response.success:
        return _STATUS_OK
    # Unsuccessful: distinguish a tool that ran and failed from a request that
    # nothing could handle. A present tool_result means a tool actually ran.
    if response.tool_result is not None:
        return _STATUS_FAILED
    return _STATUS_NOT_HANDLED


def format_response(response: JarvisResponse) -> str:
    """Format a response for display in the terminal.

    The first line shows the status and the response message. If the response
    includes a plan, each step is listed beneath it with its security tier. If
    the response carries an advisory AI suggestion, it is shown last, clearly
    labelled as advisory - it is informational only and never changes what runs.

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

    # Phase 15, Batch 4: an honest, post-run execution trace for a workflow
    # response - every step here already ran (or is now waiting) by the time
    # this response was built. This is never a live or streaming progress
    # feed; it is rendered once, after WorkflowEngine.run()/resume() has
    # already returned, exactly like the plan section above it.
    if response.workflow_trace:
        lines.append("        workflow steps:")
        for step in response.workflow_trace:
            lines.append(
                f"          {step.step_number}/{step.total_steps} "
                f"[{step.status}] {step.description} - {step.message}"
            )

    # Advisory only: the AI suggestion is shown for the user's information. It
    # is produced after the outcome is already decided and never affects it.
    if response.ai_suggestion:
        lines.append(f"        {response.ai_suggestion}")

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
        _voice_output: Optional VoiceOutputService to speak a response's
            message through (Phase 41, Batch 2). None by default - no
            voice output occurs unless one is explicitly supplied.
        _speak_responses: Whether to actually attempt speaking each
            response through _voice_output. False by default (opt-in,
            matching Nathan's own "not every response by default"
            decision) - even when a service is supplied, nothing is
            spoken unless this is also True. VoiceOutputService's own
            `enabled` flag is a second, independent gate on top of this
            one; both must allow it for a provider to actually be
            called.
        _voice_input: Optional VoiceInputService to produce a request
            string through (Phase 41, Batch 4, fake provider only).
            None by default - no transcription is ever attempted unless
            one is explicitly supplied. Entirely independent of
            _voice_output/_speak_responses: enabling one never enables
            or requires the other.
    """

    def __init__(
        self,
        orchestrator: JarvisOrchestrator,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        startup_notice: str | None = None,
        voice_output: VoiceOutputService | None = None,
        speak_responses: bool = False,
        voice_input: VoiceInputService | None = None,
    ) -> None:
        """Initialise the CLI.

        Args:
            orchestrator: The Core orchestrator to forward requests to.
            input_fn: Function used to read input. Defaults to input.
            output_fn: Function used to write output. Defaults to print.
            startup_notice: An optional, pre-built, content-free notice
                line (Phase 22) to print once, immediately after the
                banner - for example, a count of new scheduled Inbox
                entries. None (the default) prints nothing extra,
                exactly matching every prior phase's own startup output.
            voice_output: Optional VoiceOutputService to speak a
                response's message through. Defaults to None, in which
                case nothing is ever spoken, matching every prior
                phase's own text-only behaviour exactly.
            speak_responses: Whether to actually attempt speaking each
                response. Defaults to False (opt-in) - even with a
                voice_output supplied, nothing is spoken unless this is
                also explicitly True.
            voice_input: Optional VoiceInputService to produce a
                request string through _handle_voice_input_once().
                Defaults to None, in which case that method is a safe
                no-op. Independent of voice_output/speak_responses -
                neither setting affects the other.
        """
        self._orchestrator = orchestrator
        self._input = input_fn
        self._output = output_fn
        self._startup_notice = startup_notice
        self._voice_output = voice_output
        self._speak_responses = speak_responses
        self._voice_input = voice_input

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

            self._handle_text_request(text)

    def _handle_text_request(self, text: str) -> None:
        """Handle one already-produced request string through the Core.

        This is the single, shared entry point every request source in
        this CLI uses - the typed-input loop above calls it directly,
        and _handle_voice_input_once() (Phase 41, Batch 4) calls it with
        a transcribed string, with no separate or shortened path for
        either origin. The text is forwarded to
        JarvisOrchestrator.handle_request() exactly as received - it is
        never re-interpreted or treated differently based on where it
        came from.

        Args:
            text: The request text to handle - typed, or, since Batch
                4, transcribed by a (currently fake-only) voice input
                provider.
        """
        response = self._orchestrator.handle_request(text)
        self._output(format_response(response))
        self._speak_if_enabled(response.message)

        if response.approval_request is not None:
            self._handle_approval(response)

    def _handle_voice_input_once(self) -> None:
        """Transcribe once via _voice_input, if active, and route the
        result through _handle_text_request() - the exact same path
        typed input uses.

        Not reachable from the interactive typed-input loop yet; this
        exists so voice-originated routing can be proven safe now (see
        tests/unit/test_cli.py's adversarial approval-bypass proofs),
        ahead of a future batch's real push-to-talk trigger, which will
        call this method (or an equivalent) once a real recording
        mechanism exists. Only ever produces a plain string and hands
        it to _handle_text_request() - this method never constructs a
        ToolRequest, never calls CommandRouter/ToolExecutor/
        ApprovalManager directly, and never executes anything itself.

        Safe no-op when _voice_input is None, inactive (disabled or
        provider-less), or produces no usable transcription - nothing
        is handled in any of those cases.
        """
        if self._voice_input is None:
            return

        result = self._voice_input.transcribe()
        if not result.success or not result.text.strip():
            return

        self._handle_text_request(result.text)

    def _speak_if_enabled(self, text: str) -> None:
        """Best-effort speak the given text, if voice output is opted in.

        This is the only place voice output is ever attempted, and it
        always runs strictly after the text response has already been
        decided and printed - text is treated purely as data to
        vocalise, never re-interpreted, routed to CommandRouter, or
        passed to ToolExecutor/ApprovalManager/any AI component.

        Two independent gates must both allow it: this CLI's own
        speak_responses flag (opt-in, off by default) and
        VoiceOutputService's own `enabled` flag plus a supplied
        provider (also off/absent by default) - either one being off is
        enough to keep this a safe no-op. A voice failure of any kind
        never raises, never changes the already-printed text response,
        and is not itself surfaced - speaking is strictly best-effort.

        Args:
            text: The response message to speak, exactly as already
                shown in the printed text response.
        """
        if not self._speak_responses or self._voice_output is None:
            return
        self._voice_output.speak(text)

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
        """Print the startup banner, a short usage hint, and any
        pre-built startup notice (Phase 22)."""
        self._output(STARTUP_BANNER)
        self._output(f"{APP_NAME} interactive CLI.")
        self._output("Type only your request after the prompt.")
        self._output("Do not type the 'you>' prompt text itself.")
        self._output("Type 'exit', 'quit', or 'bye' to leave.")
        self._output("")
        if self._startup_notice is not None:
            self._output(self._startup_notice)
            self._output("")