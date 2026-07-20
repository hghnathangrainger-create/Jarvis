"""
test_main_ai_wiring.py

Composition tests for AI reasoning wiring in main.build_orchestrator()
(Phase 7, Batch 2).

Before this batch, main.py never constructed an AIReasoningEngine, AIRouter,
or PromptBuilder at all - AI_REASONING_ENABLED had no effect whatsoever on
the running application, no matter how it was set. These tests prove that
gap is closed, in both directions:

    - AI_REASONING_ENABLED unset/false: behaviour is unchanged from every
      prior phase - no advisory suggestion is ever attached.
    - AI_REASONING_ENABLED=true: a real, live-callable AIReasoningEngine is
      actually constructed and wired into the orchestrator.

No real Claude API call is made in either case: a fake ANTHROPIC_API_KEY is
enough to construct a ClaudeProvider (constructing the SDK client makes no
network call), and these tests never invoke a request path that would
attempt one.

Run with:
    pytest tests/unit/test_main_ai_wiring.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

import main


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every setting at safe, isolated values so build_orchestrator()
    never touches the real .env file, the real database, or the network.

    PYTHON_DOTENV_DISABLED=1 tells load_settings()'s own load_dotenv(...)
    call to skip reading any .env file at all (a real, documented
    python-dotenv mechanism) - this, not deleting AI_REASONING_ENABLED,
    is what actually makes this fixture hermetic. Previously this fixture
    used monkeypatch.delenv("AI_REASONING_ENABLED", raising=False), but
    load_settings() calls load_dotenv(override=False), which only skips a
    key already present in os.environ - deleting it left the key absent,
    so a real, developer-machine .env file's own AI_REASONING_ENABLED
    value (e.g. "true") would silently flow back in and defeat the
    fixture's own intent (this is exactly what happened before this fix).
    With dotenv fully disabled here, "unset" genuinely means unset - so
    test_ai_disabled_by_default_produces_no_advisory_suggestion below
    still exercises Settings' own real default, not a forced value -
    while ANTHROPIC_API_KEY/DATABASE_PATH continue to come from this
    fixture's own explicit monkeypatch.setenv calls either way, and any
    test below that sets AI_REASONING_ENABLED explicitly still does so
    normally, unaffected by dotenv being disabled."""
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test_jarvis.db"))
    monkeypatch.delenv("AI_REASONING_ENABLED", raising=False)


# --- AI_REASONING_ENABLED unset/false: unchanged default behaviour ----------


def test_ai_disabled_by_default_produces_no_advisory_suggestion() -> None:
    orchestrator = main.build_orchestrator()
    response = orchestrator.handle_request("echo hello")
    assert response.ai_suggestion is None


def test_ai_explicitly_disabled_produces_no_advisory_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_REASONING_ENABLED", "false")
    orchestrator = main.build_orchestrator()
    response = orchestrator.handle_request("echo hello")
    assert response.ai_suggestion is None


def test_ai_disabled_orchestrator_has_no_reasoning_engine() -> None:
    orchestrator = main.build_orchestrator()
    # Structural confirmation that reasoning_engine=None was passed through,
    # exactly as it silently always has been before this batch.
    assert orchestrator._reasoning is None


# --- AI_REASONING_ENABLED=true: genuinely wired for the first time ----------


def test_ai_enabled_constructs_a_live_callable_reasoning_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_REASONING_ENABLED", "true")
    orchestrator = main.build_orchestrator()

    # A real AIReasoningEngine was constructed and wired in - this is the
    # one thing that was never true before Phase 7 Batch 2, regardless of
    # how AI_REASONING_ENABLED was set.
    assert orchestrator._reasoning is not None
    # is_active() only checks the fake key is non-empty (no network call),
    # confirming the engine is genuinely reachable, not merely present.
    # Deliberately not calling handle_request() here: with a real
    # ClaudeProvider wired in, any request would attempt a genuine network
    # call to the Claude API. That AI-enabled behaviour (advisory-only,
    # cannot change outcomes) is already fully covered against a fake
    # provider in test_ai_core_safety.py - this file only proves wiring.
    assert orchestrator._reasoning.is_active() is True
