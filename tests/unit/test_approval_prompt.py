"""
test_approval_prompt.py

Unit tests for the Jarvis CLI approval prompts (ui/approval_prompt.py).

The formatting and parsing functions are pure and are tested directly. The
interactive prompt is tested with injected input and output callables, so no
real terminal is needed.

Run with:
    pytest tests/unit/test_approval_prompt.py
"""

from __future__ import annotations

import pytest

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier
from ui.approval_prompt import (
    format_approval_request,
    parse_approval_input,
    prompt_for_approval,
)


def _request(**overrides: object) -> ApprovalRequest:
    """Build a valid YELLOW request, with optional field overrides."""
    kwargs: dict[str, object] = {
        "action": "send email to Alex",
        "reason": "Sending an email communicates on your behalf.",
        "security_tier": SecurityTier.YELLOW,
    }
    kwargs.update(overrides)
    return ApprovalRequest(**kwargs)  # type: ignore[arg-type]


# --- Formatting --------------------------------------------------------------


def test_format_shows_core_fields() -> None:
    request = _request()
    text = format_approval_request(request)
    assert request.request_id in text
    assert "send email to Alex" in text
    assert "Sending an email" in text
    assert "YELLOW" in text


def test_format_includes_request_id() -> None:
    request = _request()
    assert request.request_id in format_approval_request(request)


def test_format_includes_action() -> None:
    request = _request(action="delete a calendar event")
    assert "delete a calendar event" in format_approval_request(request)


def test_format_includes_reason() -> None:
    request = _request(reason="This changes your calendar.")
    assert "This changes your calendar." in format_approval_request(request)


def test_format_includes_risk_tier() -> None:
    request = _request()
    text = format_approval_request(request)
    assert "YELLOW" in text
    # A plain-language hint helps a beginner understand the tier.
    assert "sensitive" in text.lower()


def test_format_makes_it_obvious_this_is_an_approval() -> None:
    request = _request()
    text = format_approval_request(request)
    assert "approval required" in text.lower()


def test_format_labels_are_present_and_readable() -> None:
    request = _request()
    text = format_approval_request(request)
    for label in ("Request ID:", "Action:", "Reason:", "Risk tier:"):
        assert label in text
    # The output is multi-line, one field per line, so it reads clearly.
    assert len(text.splitlines()) >= 6


def test_format_shows_metadata() -> None:
    request = _request(metadata={"to": "alex@example.com"})
    text = format_approval_request(request)
    assert "to: alex@example.com" in text


def test_format_shows_multiple_metadata_sorted() -> None:
    request = _request(metadata={"to": "alex@example.com", "subject": "Update"})
    text = format_approval_request(request)
    assert "to: alex@example.com" in text
    assert "subject: Update" in text
    # Keys are shown in sorted order: 'subject' before 'to'.
    assert text.index("subject:") < text.index("to:")


def test_format_omits_details_when_no_metadata() -> None:
    request = _request()
    assert "Details" not in format_approval_request(request)


# --- Parsing -----------------------------------------------------------------


@pytest.mark.parametrize("text", ["y", "yes", "approve", "YES", "  Approve  "])
def test_parse_approve_inputs(text: str) -> None:
    assert parse_approval_input(text) is True


@pytest.mark.parametrize("text", ["n", "no", "decline", "cancel", "NO", "  Cancel "])
def test_parse_decline_inputs(text: str) -> None:
    assert parse_approval_input(text) is False


@pytest.mark.parametrize("text", ["maybe", "", "asdf", "ok", "yep"])
def test_parse_invalid_returns_none(text: str) -> None:
    assert parse_approval_input(text) is None


# --- Interactive prompt ------------------------------------------------------


def test_prompt_returns_approved_decision() -> None:
    request = _request()
    decision = prompt_for_approval(
        request,
        input_func=lambda _prompt: "yes",
        output_func=lambda _line: None,
    )
    assert decision.is_approved is True
    assert decision.request_id == request.request_id


def test_prompt_returns_declined_decision() -> None:
    request = _request()
    decision = prompt_for_approval(
        request,
        input_func=lambda _prompt: "no",
        output_func=lambda _line: None,
    )
    assert decision.is_declined is True
    assert decision.request_id == request.request_id


def test_prompt_reprompts_after_invalid_input() -> None:
    request = _request()
    answers = iter(["huh", "maybe", "approve"])
    outputs: list[str] = []
    decision = prompt_for_approval(
        request,
        input_func=lambda _prompt: next(answers),
        output_func=outputs.append,
    )
    assert decision.is_approved is True
    # The invalid hint should have been shown for each of the two bad answers.
    assert sum("Please answer" in line for line in outputs) == 2


def test_prompt_decision_keeps_request_id() -> None:
    request = _request()
    decision = prompt_for_approval(
        request,
        input_func=lambda _prompt: "y",
        output_func=lambda _line: None,
    )
    assert decision.request_id == request.request_id


def test_prompt_preserves_decided_by() -> None:
    request = _request()
    decision = prompt_for_approval(
        request,
        input_func=lambda _prompt: "y",
        output_func=lambda _line: None,
        decided_by="nathan",
    )
    assert decision.decided_by == "nathan"


def test_prompt_displays_request_before_asking() -> None:
    request = _request()
    events: list[tuple[str, str]] = []

    def _out(line: str) -> None:
        events.append(("out", line))

    def _in(prompt: str) -> str:
        events.append(("in", prompt))
        return "y"

    prompt_for_approval(request, input_func=_in, output_func=_out)
    assert events[0][0] == "out"
    assert "approval required" in events[0][1].lower()