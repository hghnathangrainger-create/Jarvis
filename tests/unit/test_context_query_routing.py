"""
test_context_query_routing.py

Unit tests for CommandRouter.match_ask_jarvis() (Phase 90, Batch 1 -
Context Intelligence): the exact "ask jarvis: <request>" grammar.

Mirrors match_web_search_summary's own established test shape: this is
a distinct, narrow matcher, never part of match()/build_input(), so
these tests exercise it directly rather than through a registered
tool.

Run with:
    pytest tests/unit/test_context_query_routing.py
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
        router.match_ask_jarvis("ask jarvis: what is my current focus")
        == "what is my current focus"
    )


def test_case_insensitive_prefix_match(router: CommandRouter) -> None:
    assert (
        router.match_ask_jarvis("Ask Jarvis: What is my focus")
        == "What is my focus"
    )
    assert (
        router.match_ask_jarvis("ASK JARVIS: WHAT IS MY FOCUS")
        == "WHAT IS MY FOCUS"
    )


def test_arbitrary_trailing_request_text_preserved_verbatim(router: CommandRouter) -> None:
    request = "  What is my focus, exactly?!  "
    result = router.match_ask_jarvis(f"ask jarvis:{request}")
    assert result == request.strip()


def test_leading_and_trailing_whitespace_around_request_is_stripped(
    router: CommandRouter,
) -> None:
    assert router.match_ask_jarvis("ask jarvis:    hello there   ") == "hello there"


def test_empty_request_after_colon_returns_empty_string(router: CommandRouter) -> None:
    assert router.match_ask_jarvis("ask jarvis:") == ""


def test_whitespace_only_request_after_colon_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert router.match_ask_jarvis("ask jarvis:    ") == ""


# --- near misses must not match -----------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "ask jarvis",
        "ask jarvis about X",
        "jarvis, ask: X",
        "please ask jarvis: X",
        "askjarvis: X",
        "ask jarvi: X",
        "tell jarvis: X",
    ],
)
def test_near_misses_do_not_match(router: CommandRouter, text: str) -> None:
    assert router.match_ask_jarvis(text) is None


def test_unrelated_text_does_not_match(router: CommandRouter) -> None:
    assert router.match_ask_jarvis("show jarvis project state") is None
    assert router.match_ask_jarvis("jarvis brain status") is None
    assert router.match_ask_jarvis("remember this: buy milk") is None
