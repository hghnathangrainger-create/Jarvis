"""
test_ask_jarvis_to_routing.py

Unit tests for CommandRouter.match_ask_jarvis_to() (Phase 90, Batch 2):
the exact "ask jarvis to: <request>" grammar.

Mirrors tests/unit/test_context_query_routing.py's own established
shape for Batch 1's sibling matcher.

Run with:
    pytest tests/unit/test_ask_jarvis_to_routing.py
"""

from __future__ import annotations

import pytest

from core.command_router import CommandRouter
from tools.registry import ToolRegistry


@pytest.fixture()
def router() -> CommandRouter:
    return CommandRouter(ToolRegistry())


# --- exact grammar -----------------------------------------------------------


def test_exact_phrase_matches_and_extracts_trailing_request(router: CommandRouter) -> None:
    assert (
        router.match_ask_jarvis_to("ask jarvis to: show my project state")
        == "show my project state"
    )


def test_case_insensitive_prefix_match(router: CommandRouter) -> None:
    assert (
        router.match_ask_jarvis_to("Ask Jarvis To: Show my project state")
        == "Show my project state"
    )
    assert (
        router.match_ask_jarvis_to("ASK JARVIS TO: SHOW MY PROJECT STATE")
        == "SHOW MY PROJECT STATE"
    )


def test_arbitrary_trailing_request_text_preserved_verbatim(router: CommandRouter) -> None:
    request = "  Show my state, please?!  "
    result = router.match_ask_jarvis_to(f"ask jarvis to:{request}")
    assert result == request.strip()


def test_leading_and_trailing_whitespace_around_request_is_stripped(
    router: CommandRouter,
) -> None:
    assert (
        router.match_ask_jarvis_to("ask jarvis to:    hello there   ")
        == "hello there"
    )


def test_empty_request_after_colon_returns_empty_string(router: CommandRouter) -> None:
    assert router.match_ask_jarvis_to("ask jarvis to:") == ""


def test_whitespace_only_request_after_colon_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert router.match_ask_jarvis_to("ask jarvis to:    ") == ""


# --- near misses must not match -----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "ask jarvis to",
        "ask jarvis",
        "jarvis, ask to: X",
        "please ask jarvis to: X",
        "askjarvis to: X",
        "ask jarvis too: X",
        "tell jarvis to: X",
    ],
)
def test_near_misses_do_not_match(router: CommandRouter, text: str) -> None:
    assert router.match_ask_jarvis_to(text) is None


def test_unrelated_text_does_not_match(router: CommandRouter) -> None:
    assert router.match_ask_jarvis_to("show jarvis project state") is None
    assert router.match_ask_jarvis_to("jarvis brain status") is None
    assert router.match_ask_jarvis_to("remember this: buy milk") is None


# --- collision with the Batch 1 "ask jarvis:" matcher -------------------------


def test_ask_jarvis_to_is_not_matched_by_batch_1_ask_jarvis(router: CommandRouter) -> None:
    """A Batch 2 request must never be swallowed by the Batch 1 matcher."""
    assert router.match_ask_jarvis("ask jarvis to: show my project state") is None


def test_batch_1_request_containing_the_word_to_is_not_matched_by_batch_2(
    router: CommandRouter,
) -> None:
    """"ask jarvis: to X" is a legitimate Batch 1 request whose own text
    happens to start with the word "to" - it must never match the
    Batch 2 grammar."""
    assert router.match_ask_jarvis_to("ask jarvis: to X") is None
    assert router.match_ask_jarvis("ask jarvis: to X") == "to X"
