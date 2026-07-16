"""
test_help_output_routing_consistency.py

Phase 51: locks HelpTool's static, hand-maintained output (tools/builtin/
help_tool.py's _HELP_LINES) against CommandRouter's/JarvisOrchestrator's
actual routing behaviour, using a real, fully-wired orchestrator built the
same way main.py builds one - no fakes, no stubs.

Why this exists: HelpTool's text is deliberately a hand-maintained
constant, not derived from CommandRouter at runtime (chosen in Phase 43 to
avoid a larger, riskier "introspectable command registry" refactor). Phase
43's own plan document named the resulting risk explicitly: the help text
and CommandRouter's actual grammar could drift apart over time, with
nothing to catch it. This file is that catch.

One representative canonical phrase is exercised per command family listed
in _HELP_LINES (not every alias/synonym - that would overbuild for a
consistency check whose only job is catching realistic drift, not
proving CommandRouter's full grammar, which tests/unit/test_command_
router.py already does exhaustively). Each phrase is run through the real
orchestrator's handle_request() end-to-end (not just CommandRouter.match()
alone), since several families - AI-summary commands and the five fixed
workflows - are intercepted by JarvisOrchestrator's own dedicated matchers
before ever reaching the generic tool-routing path; only an end-to-end
call reflects how they are truly handled.

The single assertion for every phrase is the same: the response must NOT
be the generic "unmatched-GREEN" fallback message ("...does not yet have a
tool to carry it out..."), which is what a genuinely unrecognised request
produces (see core/orchestrator.py's _unrecognised_green_response()). A
YELLOW confirmation-required response, a RED blocked response, a
successful response, or even a response that failed for an unrelated
reason (a missing file, AI reasoning disabled) all count as "recognised" -
only the generic not-handled fallback would indicate real drift between
what HelpTool claims exists and what the router actually recognises.

Known blind spot (found in Phase 58): this file can only prove that a
phrase already listed in _HELP_LINES still routes correctly. It has no
way to prove the converse - that every real, registered command is
actually listed in _HELP_LINES in the first place. Phase 57 added the
health-check command to CommandRouter/main.py/SecurityManager without
ever adding it to _HELP_LINES, and every test in this file kept passing
throughout, because none of them iterate over CommandRouter's own
grammar - only over _REPRESENTATIVE_PHRASES below, which is itself
derived from _HELP_LINES. Closing that specific gap for the
health-check command is tests/unit/test_help_tool.py's own
test_output_documents_health_check_command_and_its_aliases (Phase 58);
a general mechanism to catch every future case of this class would
mean deriving _HELP_LINES from CommandRouter's own grammar - the
introspectable-registry approach this module's own Phase 43 origin
explicitly rejected as too large a refactor for a narrow discoverability
goal - so it is not undertaken here either.

Each phrase gets a fresh orchestrator (a function-scoped fixture is
created anew per parametrised case): Phase 15's Workflow Engine allows
only one paused, awaiting-approval workflow at a time process-wide, so
reusing a single orchestrator across the two-step workflow phrases below
would raise a spurious WorkflowError unrelated to what this file tests.

Run with:
    pytest tests/unit/test_help_output_routing_consistency.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main

_FALLBACK_MESSAGE = "does not yet have a tool to carry it out"

#: One representative canonical phrase per command family in
#: tools/builtin/help_tool.py's _HELP_LINES, in the same order/grouping.
_REPRESENTATIVE_PHRASES: tuple[tuple[str, str], ...] = (
    # Basic
    ("Basic: echo", "echo hello"),
    ("Basic: system info", "system info"),
    ("Basic: show config", "show config"),
    ("Basic: help", "help"),
    ("Basic: health check", "health check"),
    ("Basic: jarvis brain status", "jarvis brain status"),
    # Memory
    ("Memory: remember this", "remember this: buy milk"),
    ("Memory: show memories", "show memories"),
    ("Memory: show memory categories", "show memory categories"),
    ("Memory: search memories", "search memories for milk"),
    ("Memory: update memory", "update memory 1: new text"),
    ("Memory: move memory", "move memory 1 to personal"),
    ("Memory: forget memory", "forget memory 1"),
    ("Memory: forget all", "forget all memories"),
    ("Memory: summarise memory family", "summarise recent memories"),
    # Files
    ("Files: list files", "list files"),
    ("Files: read file", "read file notes.txt"),
    ("Files: search files by name", "search files for notes"),
    ("Files: find files containing", "find files containing hello"),
    ("Files: create file", "create file phase51_scratch.txt with hello"),
    ("Files: append", "append hello to file notes.txt"),
    ("Files: copy file", "copy file a.txt to b.txt"),
    ("Files: move file", "move file a.txt to b.txt"),
    ("Files: delete file", "delete file notes.txt"),
    ("Files: list quarantine", "list quarantine"),
    ("Files: restore file", "restore file notes.txt"),
    ("Files: summarise file", "summarise file notes.txt"),
    # Web
    ("Web: search the web", "search the web for cats"),
    ("Web: summarise web search", "summarise web search for cats"),
    ("Web: read webpage", "read webpage https://example.com"),
    ("Web: summarize webpage", "summarize webpage https://example.com"),
    (
        "Web: summarize webpage and save to inbox",
        "summarize webpage https://example.com and save to inbox",
    ),
    # Schedules
    (
        "Schedules: schedule create",
        "schedule web search summary for cats at 09:00",
    ),
    ("Schedules: list schedules", "list schedules"),
    ("Schedules: enable schedule", "enable schedule 1"),
    ("Schedules: disable schedule", "disable schedule 1"),
    # Workflows
    (
        "Workflows: remember and show back",
        "remember this and show it back: hi",
    ),
    (
        "Workflows: remember and forget",
        "remember this and forget it: hi",
    ),
    (
        "Workflows: create and read",
        "create file phase51_scratch2.txt with hi and show it",
    ),
    (
        "Workflows: update and show back",
        "update memory 1: hi and show it back",
    ),
    (
        "Workflows: search and copy",
        "search files for phase51_nonexistent_pattern and copy first to c.txt",
    ),
    # History
    ("History: approval history", "show approval history"),
    ("History: workflow history", "show workflow history"),
    # Claude Prompt Studio
    (
        "Claude Prompt Studio: prepare implementation prompt",
        "prepare implementation prompt for a better memory search",
    ),
)


@pytest.fixture()
def orchestrator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A fresh, fully-wired orchestrator per test, matching main.py's own
    real composition (every built-in tool registered), pointed at an
    isolated database so no real .env/data file is ever touched."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)
    return main.build_orchestrator()


@pytest.mark.parametrize(
    ("family", "text"),
    _REPRESENTATIVE_PHRASES,
    ids=[family for family, _ in _REPRESENTATIVE_PHRASES],
)
def test_representative_phrase_is_recognised(
    orchestrator, family: str, text: str
) -> None:
    response = orchestrator.handle_request(text)
    assert _FALLBACK_MESSAGE not in response.message, (
        f"{family!r} phrase {text!r} hit the generic unmatched-GREEN "
        "fallback - HelpTool's text and CommandRouter's actual grammar "
        "have drifted apart."
    )
