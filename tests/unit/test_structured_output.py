"""
test_structured_output.py

Unit tests for intelligence/structured_output.py (Phase 90, Batch 2):
the strict, deterministic parser for "ask jarvis to: <request>" model
output (contracts fixed by docs/phase_90_implementation_plan.md,
Sections 25.B and 26.A/B/D).

Run with:
    pytest tests/unit/test_structured_output.py
"""

from __future__ import annotations

import json

import pytest

from intelligence.capability_catalog import (
    CapabilityAdapter,
    CapabilityArgumentSpec,
    CapabilityId,
    ExecutionStrategy,
)
from intelligence.structured_output import (
    ParsedToolSelection,
    ToolSelectionDecision,
    ToolSelectionParseError,
    parse_tool_selection,
)
from config.constants import SecurityTier

_EXECUTE_TEXT = json.dumps(
    {"decision": "execute", "capability_id": "project_state_show", "arguments": {}}
)
_UNSUPPORTED_TEXT = json.dumps(
    {"decision": "unsupported", "capability_id": None, "arguments": {}}
)

_ZERO_ARG_CATALOG = {
    CapabilityId.PROJECT_STATE_SHOW: CapabilityAdapter(
        capability_id=CapabilityId.PROJECT_STATE_SHOW,
        tool_name="project_state_show",
        description="test",
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    )
}

_WITH_ARG_CATALOG = {
    CapabilityId.PROJECT_STATE_SHOW: CapabilityAdapter(
        capability_id=CapabilityId.PROJECT_STATE_SHOW,
        tool_name="project_state_show",
        description="test",
        arguments=(
            CapabilityArgumentSpec(name="value", type_name="str", required=True),
            CapabilityArgumentSpec(name="flag", type_name="bool", required=False),
        ),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    )
}


def _parse(text: str, catalog=_ZERO_ARG_CATALOG) -> ParsedToolSelection:
    return parse_tool_selection(text, catalog)


def _fails(text: str, catalog=_ZERO_ARG_CATALOG) -> str:
    with pytest.raises(ToolSelectionParseError) as excinfo:
        parse_tool_selection(text, catalog)
    return excinfo.value.reason


# --- Valid inputs ----------------------------------------------------------


def test_valid_bare_execute_json() -> None:
    result = _parse(_EXECUTE_TEXT)
    assert result.decision is ToolSelectionDecision.EXECUTE
    assert result.capability_id is CapabilityId.PROJECT_STATE_SHOW
    assert result.arguments == {}


def test_valid_fenced_execute_json_no_language_tag() -> None:
    result = _parse(f"```\n{_EXECUTE_TEXT}\n```")
    assert result.decision is ToolSelectionDecision.EXECUTE


def test_valid_fenced_execute_json_with_json_language_tag() -> None:
    result = _parse(f"```json\n{_EXECUTE_TEXT}\n```")
    assert result.decision is ToolSelectionDecision.EXECUTE


def test_valid_bare_unsupported_json() -> None:
    result = _parse(_UNSUPPORTED_TEXT)
    assert result.decision is ToolSelectionDecision.UNSUPPORTED
    assert result.capability_id is None
    assert result.arguments == {}


def test_valid_fenced_unsupported_json() -> None:
    result = _parse(f"```json\n{_UNSUPPORTED_TEXT}\n```")
    assert result.decision is ToolSelectionDecision.UNSUPPORTED


def test_returned_argument_dictionary_is_a_fresh_copy() -> None:
    arguments_obj = {"value": "hello", "flag": True}
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": arguments_obj,
        }
    )
    result = _parse(text, catalog=_WITH_ARG_CATALOG)
    assert result.arguments == {"value": "hello", "flag": True}
    assert result.arguments is not arguments_obj


# --- Output-size bound (Section 26.D) --------------------------------------


def test_output_of_exactly_2000_characters_reaches_normal_parsing() -> None:
    # Leading whitespace is trimmed by the parser (not treated as
    # malformed prose), so padding with spaces up to exactly 2000
    # characters still reaches, and passes, normal JSON validation.
    padding = " " * (2000 - len(_UNSUPPORTED_TEXT))
    text = padding + _UNSUPPORTED_TEXT
    assert len(text) == 2000
    result = _parse(text)
    assert result.decision is ToolSelectionDecision.UNSUPPORTED


def test_output_of_2001_characters_is_rejected_before_parsing() -> None:
    text = "x" * 2001
    reason = _fails(text)
    assert reason == "model output too long"


def test_oversized_output_is_not_echoed_in_the_error() -> None:
    marker = "UNIQUE_MARKER_ABC123"
    text = marker + ("x" * 2001)
    reason = _fails(text)
    assert marker not in reason


# --- Malformed JSON / prose / structure ------------------------------------


def test_malformed_json_is_rejected() -> None:
    _fails("{not valid json")


def test_empty_output_is_rejected() -> None:
    reason = _fails("")
    assert reason == "empty model output"


def test_whitespace_only_output_is_rejected() -> None:
    reason = _fails("    \n\t  ")
    assert reason == "empty model output"


def test_leading_prose_is_rejected() -> None:
    _fails(f"Sure, here you go: {_EXECUTE_TEXT}")


def test_trailing_prose_is_rejected() -> None:
    _fails(f"{_EXECUTE_TEXT} Hope that helps!")


def test_multiple_json_objects_is_rejected() -> None:
    _fails(_EXECUTE_TEXT + _EXECUTE_TEXT)


def test_top_level_non_object_is_rejected() -> None:
    _fails("[1, 2, 3]")
    _fails('"just a string"')
    _fails("42")


# --- Top-level key rules ----------------------------------------------------


def test_unknown_top_level_key_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {},
            "extra": "field",
        }
    )
    _fails(text)


def test_missing_decision_key_is_rejected() -> None:
    text = json.dumps({"capability_id": "project_state_show", "arguments": {}})
    _fails(text)


def test_missing_capability_id_key_is_rejected() -> None:
    text = json.dumps({"decision": "execute", "arguments": {}})
    _fails(text)


def test_missing_arguments_key_is_rejected() -> None:
    text = json.dumps({"decision": "execute", "capability_id": "project_state_show"})
    _fails(text)


def test_unknown_decision_value_is_rejected() -> None:
    text = json.dumps(
        {"decision": "delete", "capability_id": "project_state_show", "arguments": {}}
    )
    _fails(text)


# --- Cross-field rules -------------------------------------------------------


def test_execute_with_null_capability_is_rejected() -> None:
    text = json.dumps({"decision": "execute", "capability_id": None, "arguments": {}})
    _fails(text)


def test_execute_with_non_string_capability_is_rejected() -> None:
    text = json.dumps({"decision": "execute", "capability_id": 5, "arguments": {}})
    _fails(text)


def test_unsupported_with_non_null_capability_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "unsupported",
            "capability_id": "project_state_show",
            "arguments": {},
        }
    )
    _fails(text)


def test_unsupported_with_non_empty_arguments_is_rejected() -> None:
    text = json.dumps(
        {"decision": "unsupported", "capability_id": None, "arguments": {"x": 1}}
    )
    _fails(text)


def test_arguments_must_be_an_object() -> None:
    text = json.dumps(
        {"decision": "execute", "capability_id": "project_state_show", "arguments": []}
    )
    _fails(text)


# --- Capability/argument validation ------------------------------------------


def test_unknown_capability_is_rejected() -> None:
    text = json.dumps(
        {"decision": "execute", "capability_id": "delete_everything", "arguments": {}}
    )
    reason = _fails(text)
    assert reason == "unknown capability id"


def test_capability_absent_from_catalog_is_rejected() -> None:
    text = json.dumps(
        {"decision": "execute", "capability_id": "project_state_show", "arguments": {}}
    )
    reason = _fails(text, catalog={})
    assert reason == "capability id not present in catalog"


def test_extra_unrecognized_argument_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"unexpected": "value"},
        }
    )
    reason = _fails(text)
    assert reason == "unknown argument name in model output"


def test_missing_required_argument_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {},
        }
    )
    reason = _fails(text, catalog=_WITH_ARG_CATALOG)
    assert reason == "missing required argument"


def test_wrong_argument_type_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"value": 5},
        }
    )
    _fails(text, catalog=_WITH_ARG_CATALOG)


def test_bool_is_not_silently_accepted_as_int_or_str() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"value": True},
        }
    )
    _fails(text, catalog=_WITH_ARG_CATALOG)


def test_oversized_string_argument_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"value": "x" * 501},
        }
    )
    reason = _fails(text, catalog=_WITH_ARG_CATALOG)
    assert reason == "oversized string argument"


def test_string_argument_at_exactly_500_characters_is_accepted() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"value": "x" * 500},
        }
    )
    result = _parse(text, catalog=_WITH_ARG_CATALOG)
    assert result.arguments["value"] == "x" * 500


def test_optional_argument_may_be_omitted() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"value": "hello"},
        }
    )
    result = _parse(text, catalog=_WITH_ARG_CATALOG)
    assert result.arguments == {"value": "hello"}


def test_zero_coercion_numeric_string_not_cast_to_int() -> None:
    int_catalog = {
        CapabilityId.PROJECT_STATE_SHOW: CapabilityAdapter(
            capability_id=CapabilityId.PROJECT_STATE_SHOW,
            tool_name="project_state_show",
            description="test",
            arguments=(
                CapabilityArgumentSpec(name="count", type_name="int", required=True),
            ),
            allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
            max_execution_tier=SecurityTier.GREEN,
            verification_strategy_id=None,
            internal_only=False,
        )
    }
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_show",
            "arguments": {"count": "5"},
        }
    )
    _fails(text, catalog=int_catalog)


# --- Fence handling ----------------------------------------------------------


def test_unsupported_fence_language_is_rejected() -> None:
    _fails(f"```python\n{_EXECUTE_TEXT}\n```")


def test_multiple_fences_are_rejected() -> None:
    _fails(f"```json\n{_EXECUTE_TEXT}\n```\n```json\n{_EXECUTE_TEXT}\n```")


def test_nested_fence_is_rejected() -> None:
    _fails(f"```json\n```\n{_EXECUTE_TEXT}\n```\n```")


def test_unterminated_fence_is_rejected() -> None:
    _fails(f"```json\n{_EXECUTE_TEXT}")


def test_fence_not_wrapping_the_entire_text_is_rejected() -> None:
    _fails(f"```json\n{_EXECUTE_TEXT}\n```\nextra trailing text")


def test_bare_fence_markers_without_json_content_elsewhere_are_rejected() -> None:
    _fails(f"prefix ``` {_EXECUTE_TEXT}")


# --- Duplicate-key rejection --------------------------------------------------


def test_duplicate_top_level_key_is_rejected() -> None:
    text = (
        '{"decision": "execute", "capability_id": "project_state_show", '
        '"arguments": {}, "decision": "unsupported"}'
    )
    reason = _fails(text)
    assert reason == "duplicate key in model output"


def test_duplicate_arguments_key_is_rejected() -> None:
    text = (
        '{"decision": "execute", "capability_id": "project_state_show", '
        '"arguments": {}, "arguments": {}}'
    )
    _fails(text)


def test_duplicate_nested_key_inside_arguments_is_rejected() -> None:
    text = (
        '{"decision": "execute", "capability_id": "project_state_show", '
        '"arguments": {"value": "a", "value": "b"}}'
    )
    reason = _fails(text, catalog=_WITH_ARG_CATALOG)
    assert reason == "duplicate key in model output"


def test_json_default_behavior_would_have_silently_overwritten_duplicates() -> None:
    """Direct proof that plain json.loads() would NOT have caught this -
    confirming the strict object_pairs_hook is genuinely load-bearing,
    not a redundant extra check."""
    text = '{"a": 1, "a": 2}'
    assert json.loads(text) == {"a": 2}  # plain json.loads silently overwrites
