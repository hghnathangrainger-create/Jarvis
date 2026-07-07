"""
test_context_models.py

Unit tests for AIContextBlock and its trust-boundary construction guard
(Phase 7, Batch 2).

These tests prove the conservative trust rule holds in code, not just in
documentation:
    - ContentTrust.JARVIS_TRUSTED is only ever producible through
      from_system() or from_live_user_input() - never by direct
      construction, even when the caller supplies an approved-looking
      source string such as "system" or "user_live_input". A source label
      is descriptive only; it is never proof of origin.
    - Any attempt to construct a JARVIS_TRUSTED block for any other source -
      including every category the Phase 7 plan requires to be treated as
      untrusted: stored memory, file contents, web/network content, tool
      output, AI-generated content, external memory, and historical
      conversation text - is rejected at construction.

Run with:
    pytest tests/unit/test_context_models.py
"""

from __future__ import annotations

import pytest

import ai.context_models as context_models
from ai.context_models import AIContextBlock
from config.constants import ContentTrust


# --- Approved trusted-origin factories ---------------------------------------


def test_from_system_is_jarvis_trusted() -> None:
    block = AIContextBlock.from_system("You are Jarvis's reasoning assistant.")
    assert block.trust is ContentTrust.JARVIS_TRUSTED
    assert block.source == "system"
    assert block.text == "You are Jarvis's reasoning assistant."


def test_from_live_user_input_is_jarvis_trusted() -> None:
    block = AIContextBlock.from_live_user_input("echo hello")
    assert block.trust is ContentTrust.JARVIS_TRUSTED
    assert block.source == "user_live_input"
    assert block.text == "echo hello"


# --- The approved untrusted-content path --------------------------------------


def test_from_untrusted_requires_explicit_source() -> None:
    block = AIContextBlock.from_untrusted("some content", source="memory")
    assert block.trust is ContentTrust.UNTRUSTED
    assert block.source == "memory"
    assert block.text == "some content"


@pytest.mark.parametrize(
    "source",
    [
        "memory",
        "file",
        "web",
        "tool_output",
        "ai_generated",
        "conversation_history",
        "external_memory",
    ],
)
def test_every_required_untrusted_category_is_supported(source: str) -> None:
    """Every category the Phase 7 plan requires to be treated as untrusted -
    stored memory, files, web/network content, tool output, AI-generated
    content, external memory, and historical conversation - is constructible
    only as UNTRUSTED, never JARVIS_TRUSTED."""
    block = AIContextBlock.from_untrusted("content", source=source)
    assert block.trust is ContentTrust.UNTRUSTED
    assert block.trust is not ContentTrust.JARVIS_TRUSTED


# --- The construction guard: arbitrary origins cannot claim trusted ----------


@pytest.mark.parametrize(
    "source",
    [
        "memory",
        "file",
        "web",
        "tool_output",
        "ai_generated",
        "conversation_history",
        "external_memory",
        "anything_else",
        "",
    ],
)
def test_direct_construction_rejects_jarvis_trusted_for_unapproved_source(
    source: str,
) -> None:
    """Bypassing the named factories and constructing AIContextBlock directly
    must not succeed in claiming JARVIS_TRUSTED for an arbitrary source."""
    with pytest.raises(ValueError):
        AIContextBlock(text="malicious", trust=ContentTrust.JARVIS_TRUSTED, source=source)


def test_direct_construction_with_source_system_still_fails() -> None:
    """A caller-supplied source string is never sufficient proof of origin.

    Typing the exact approved label "system" must not be enough to claim
    JARVIS_TRUSTED without having actually gone through from_system().
    """
    with pytest.raises(ValueError):
        AIContextBlock(text="ok", trust=ContentTrust.JARVIS_TRUSTED, source="system")


def test_direct_construction_with_source_user_live_input_still_fails() -> None:
    """Same guard for the other approved-looking source label."""
    with pytest.raises(ValueError):
        AIContextBlock(
            text="ok", trust=ContentTrust.JARVIS_TRUSTED, source="user_live_input"
        )


# --- Realistic alternate bypass attempts --------------------------------------


def test_bypass_via_fresh_sentinel_object_fails() -> None:
    """Supplying some other object as the private origin-key field must not
    work merely because it is truthy or object-typed - only the exact
    module-private singleton satisfies the identity check."""
    with pytest.raises(ValueError):
        AIContextBlock(
            text="ok",
            trust=ContentTrust.JARVIS_TRUSTED,
            source="system",
            _origin_key=object(),  # a different object, not the real sentinel
        )


@pytest.mark.parametrize("forged_key", [True, 1, "system", "_TRUSTED_ORIGIN_KEY"])
def test_bypass_via_plausible_guessed_key_values_fails(forged_key: object) -> None:
    """Common "guess the magic value" attempts - booleans, small ints, and
    the sentinel's own variable name as a string - must all fail, since none
    of them is the actual sentinel object by identity."""
    with pytest.raises(ValueError):
        AIContextBlock(
            text="ok",
            trust=ContentTrust.JARVIS_TRUSTED,
            source="system",
            _origin_key=forged_key,
        )


def test_bypass_via_reproduced_private_sentinel_class_fails() -> None:
    """Even reaching into the module's own private sentinel value and
    constructing a value equal-looking to it does not help if it is not the
    exact singleton instance module-internal code uses - object() has no
    meaningful equality, only identity, so a second call to object() is
    provably a different value from the real internal sentinel."""
    forged = object()
    assert forged is not context_models._TRUSTED_ORIGIN_KEY
    with pytest.raises(ValueError):
        AIContextBlock(
            text="ok",
            trust=ContentTrust.JARVIS_TRUSTED,
            source="system",
            _origin_key=forged,
        )


def test_only_the_real_internal_sentinel_satisfies_the_guard() -> None:
    """Sanity check on the mechanism itself: using the actual private
    sentinel does succeed, confirming the guard checks identity against
    this specific object rather than merely rejecting everything."""
    block = AIContextBlock(
        text="ok",
        trust=ContentTrust.JARVIS_TRUSTED,
        source="system",
        _origin_key=context_models._TRUSTED_ORIGIN_KEY,
    )
    assert block.trust is ContentTrust.JARVIS_TRUSTED


def test_trusted_origin_key_is_not_exported() -> None:
    """The sentinel is not part of the module's public API."""
    assert "_TRUSTED_ORIGIN_KEY" not in context_models.__all__


def test_untrusted_trust_never_requires_an_approved_source() -> None:
    """UNTRUSTED content is never subject to the source guard - any label is
    accepted, since it can never be mistaken for trusted authority."""
    block = AIContextBlock(text="ok", trust=ContentTrust.UNTRUSTED, source="whatever")
    assert block.trust is ContentTrust.UNTRUSTED


# --- Immutability -------------------------------------------------------------


def test_ai_context_block_is_frozen() -> None:
    block = AIContextBlock.from_system("text")
    with pytest.raises(AttributeError):
        block.text = "changed"  # type: ignore[misc]
