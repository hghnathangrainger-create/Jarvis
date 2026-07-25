"""
test_peek_compound_decision.py

Unit tests for intelligence.compound_structured_output.peek_compound_decision()
(Phase 98, Batch 2, Foundation A -
docs/phase_98_live_compound_reentry_plan.md).

Dormant: not called by any live path (see
test_phase98_batch2_dormant_isolation.py for the structural proof) -
these tests exercise it directly.
"""

from __future__ import annotations

import json

from intelligence.compound_structured_output import (
    _MAX_RAW_OUTPUT_CHARS,
    peek_compound_decision,
)


class TestExecuteSequenceIdentified:
    def test_exact_execute_sequence_returns_true(self) -> None:
        text = json.dumps({"decision": "execute_sequence", "steps": []})
        assert peek_compound_decision(text) is True

    def test_execute_sequence_with_extra_valid_shape_still_true(self) -> None:
        text = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [
                    {"capability_id": "a", "arguments": {}},
                    {"capability_id": "b", "arguments": {}},
                ],
            }
        )
        assert peek_compound_decision(text) is True

    def test_fenced_execute_sequence_still_true(self) -> None:
        text = "```json\n" + json.dumps({"decision": "execute_sequence", "steps": []}) + "\n```"
        assert peek_compound_decision(text) is True


class TestSingleDiscriminatorValuesUnchanged:
    def test_execute_decision_returns_false(self) -> None:
        text = json.dumps(
            {"decision": "execute", "capability_id": "project_state_show", "arguments": {}}
        )
        assert peek_compound_decision(text) is False

    def test_unsupported_decision_returns_false(self) -> None:
        text = json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        assert peek_compound_decision(text) is False

    def test_unknown_decision_value_returns_false(self) -> None:
        text = json.dumps({"decision": "something_else", "capability_id": None, "arguments": {}})
        assert peek_compound_decision(text) is False

    def test_missing_decision_key_returns_false(self) -> None:
        text = json.dumps({"capability_id": "x", "arguments": {}})
        assert peek_compound_decision(text) is False


class TestMalformedInputRejected:
    def test_malformed_json_returns_false(self) -> None:
        assert peek_compound_decision("not json at all") is False

    def test_non_object_json_returns_false(self) -> None:
        assert peek_compound_decision("[1, 2, 3]") is False

    def test_empty_string_returns_false(self) -> None:
        assert peek_compound_decision("") is False

    def test_oversized_text_returns_false(self) -> None:
        oversized = json.dumps(
            {"decision": "execute_sequence", "steps": [], "padding": "x" * _MAX_RAW_OUTPUT_CHARS}
        )
        assert len(oversized) > _MAX_RAW_OUTPUT_CHARS
        assert peek_compound_decision(oversized) is False

    def test_unterminated_fence_returns_false(self) -> None:
        assert peek_compound_decision("```json\n{\"decision\": \"execute_sequence\"}") is False


class TestDuplicateKeysRejected:
    def test_duplicate_decision_key_returns_false(self) -> None:
        # A raw duplicate top-level key - json.dumps can't produce this,
        # so it is hand-written, mirroring the compound parser's own
        # existing duplicate-key test convention.
        text = '{"decision": "execute_sequence", "decision": "execute", "steps": []}'
        assert peek_compound_decision(text) is False

    def test_duplicate_nested_key_returns_false(self) -> None:
        text = (
            '{"decision": "execute_sequence", "steps": [{"capability_id": "a", '
            '"capability_id": "b", "arguments": {}}]}'
        )
        assert peek_compound_decision(text) is False


class TestNoParsingFallback:
    def test_peek_never_raises_for_any_input(self) -> None:
        """A pure routing decision - never raises, regardless of how
        malformed the input is, so a caller can always safely call it
        before choosing which parser to invoke."""
        for candidate in (
            "",
            "null",
            "{}",
            "{",
            "[1,2]",
            "```\nnot json\n```",
            '{"decision": 123}',
            '{"decision": ["execute_sequence"]}',
        ):
            assert peek_compound_decision(candidate) in (True, False)

    def test_peek_does_not_validate_full_compound_shape(self) -> None:
        """peek_compound_decision() only ever inspects the top-level
        "decision" key - it is not a second, shadow parser. A shape
        that would fail parse_compound_tool_selection() (wrong step
        count) still peeks True, since routing and full validation are
        deliberately separate concerns."""
        text = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [{"capability_id": "a", "arguments": {}}],
            }
        )
        assert peek_compound_decision(text) is True
