"""
test_structured_output.py

Unit tests for intelligence/structured_output.py (Phase 90, Batches
2/3): the strict, deterministic parser for "ask jarvis to: <request>"
model output (contracts fixed by docs/phase_90_implementation_plan.md,
Sections 25.B, 26.A/B/D, and the Batch 3 planning prompt).

Run with:
    pytest tests/unit/test_structured_output.py
"""

from __future__ import annotations

import json

import pytest

from intelligence.capability_catalog import (
    CAPABILITY_CATALOG,
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


# ---------------------------------------------------------------------------
# Batch 3: real CAPABILITY_CATALOG (project_state_show,
# project_state_update_focus, project_state_verify_focus)
# ---------------------------------------------------------------------------

_UPDATE_FOCUS_EXECUTE_TEXT = json.dumps(
    {
        "decision": "execute",
        "capability_id": "project_state_update_focus",
        "arguments": {"value": "a brand new focus"},
    }
)


def test_project_state_show_remains_valid_against_real_catalog() -> None:
    result = parse_tool_selection(_EXECUTE_TEXT, CAPABILITY_CATALOG)
    assert result.decision is ToolSelectionDecision.EXECUTE
    assert result.capability_id is CapabilityId.PROJECT_STATE_SHOW


def test_update_focus_valid_selection() -> None:
    result = parse_tool_selection(_UPDATE_FOCUS_EXECUTE_TEXT, CAPABILITY_CATALOG)
    assert result.decision is ToolSelectionDecision.EXECUTE
    assert result.capability_id is CapabilityId.PROJECT_STATE_UPDATE_FOCUS
    assert result.arguments == {"value": "a brand new focus"}


def test_unsupported_remains_valid_against_real_catalog() -> None:
    result = parse_tool_selection(_UNSUPPORTED_TEXT, CAPABILITY_CATALOG)
    assert result.decision is ToolSelectionDecision.UNSUPPORTED


def test_verify_focus_is_rejected_from_ai_output_even_though_catalogued() -> None:
    """PROJECT_STATE_VERIFY_FOCUS is a real catalog entry (so the fixed
    two-step workflow can resolve it internally) but must never be
    selectable through AI output."""
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_verify_focus",
            "arguments": {},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "capability is internal-only and cannot be selected"


def test_update_focus_missing_value_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {},
        }
    )
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_update_focus_extra_argument_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "x", "extra": "y"},
        }
    )
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_update_focus_non_string_value_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": 5},
        }
    )
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_update_focus_empty_value_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": ""},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "empty or whitespace-only string argument"


def test_update_focus_whitespace_only_value_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "   \t  "},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "empty or whitespace-only string argument"


def test_update_focus_over_500_chars_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "x" * 501},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "oversized string argument"


def test_update_focus_exactly_500_chars_is_accepted() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "x" * 500},
        }
    )
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert len(result.arguments["value"]) == 500


def test_update_focus_nul_character_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "hello\x00world"},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "string argument contains a NUL character"


def test_update_focus_leading_control_character_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "\x01leading control char"},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "string argument has a leading or trailing control character"


def test_update_focus_trailing_control_character_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "trailing control char\x1f"},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "string argument has a leading or trailing control character"


def test_update_focus_leading_or_trailing_plain_space_is_not_a_control_character() -> (
    None
):
    """A plain space (0x20) is printable, not a C0 control character or
    DEL - it is not specifically rejected by the leading/trailing
    control-character check."""
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": " padded with spaces "},
        }
    )
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert result.arguments["value"] == " padded with spaces "


def test_update_focus_value_is_never_normalized_or_rewritten() -> None:
    """The validated value is preserved verbatim - no trimming, no
    case-folding, no collapsing of internal whitespace."""
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": "Mixed CASE   with   spacing"},
        }
    )
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert result.arguments["value"] == "Mixed CASE   with   spacing"


def test_rejected_value_is_never_echoed_in_the_error() -> None:
    marker = "UNIQUE_SECRET_TO_NEVER_LEAK_ABCDEF"
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "project_state_update_focus",
            "arguments": {"value": marker + ("x" * 501)},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert marker not in reason


# ---------------------------------------------------------------------------
# Phase 91, Batch 2: memory_search - one required, bounded string argument
# ---------------------------------------------------------------------------


def _memory_search_text(value: object) -> str:
    return json.dumps(
        {
            "decision": "execute",
            "capability_id": "memory_search",
            "arguments": {"value": value},
        }
    )


def test_memory_search_valid_selection() -> None:
    text = _memory_search_text("the deployment checklist")
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert result.decision is ToolSelectionDecision.EXECUTE
    assert result.capability_id is CapabilityId.MEMORY_SEARCH
    assert result.arguments == {"value": "the deployment checklist"}


def test_memory_search_missing_value_is_rejected() -> None:
    text = json.dumps(
        {"decision": "execute", "capability_id": "memory_search", "arguments": {}}
    )
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_extra_argument_is_rejected() -> None:
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "memory_search",
            "arguments": {"value": "x", "extra": "y"},
        }
    )
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_internal_operation_field_is_rejected() -> None:
    """The model can never supply "operation" itself - memory_search
    declares only "value" as an argument, so any attempt to also name
    the internal selector is rejected as an unknown argument, before
    build_tool_input()'s own fixed operation="search" is ever reached."""
    text = json.dumps(
        {
            "decision": "execute",
            "capability_id": "memory_search",
            "arguments": {"value": "x", "operation": "save"},
        }
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "unknown argument name in model output"


def test_memory_search_null_value_is_rejected() -> None:
    text = _memory_search_text(None)
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_numeric_value_is_rejected() -> None:
    text = _memory_search_text(5)
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_boolean_value_is_rejected() -> None:
    text = _memory_search_text(True)
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_array_value_is_rejected() -> None:
    text = _memory_search_text(["a search query"])
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_object_value_is_rejected() -> None:
    text = _memory_search_text({"query": "a search query"})
    _fails(text, catalog=CAPABILITY_CATALOG)


def test_memory_search_empty_value_is_rejected() -> None:
    text = _memory_search_text("")
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "empty or whitespace-only string argument"


def test_memory_search_whitespace_only_value_is_rejected() -> None:
    text = _memory_search_text("   \t  ")
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "empty or whitespace-only string argument"


def test_memory_search_single_character_value_is_accepted() -> None:
    """The accepted minimum is one non-whitespace character - there is
    no separate numeric minimum-length threshold beyond the existing
    non-empty/non-whitespace-only rule."""
    text = _memory_search_text("x")
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert result.arguments["value"] == "x"


def test_memory_search_over_500_chars_is_rejected() -> None:
    text = _memory_search_text("x" * 501)
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "oversized string argument"


def test_memory_search_exactly_500_chars_is_accepted() -> None:
    text = _memory_search_text("x" * 500)
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert len(result.arguments["value"]) == 500


def test_memory_search_nul_character_is_rejected() -> None:
    text = _memory_search_text("hello\x00world")
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "string argument contains a NUL character"


def test_memory_search_leading_control_character_is_rejected() -> None:
    text = _memory_search_text("\x01leading control char")
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "string argument has a leading or trailing control character"


def test_memory_search_trailing_control_character_is_rejected() -> None:
    text = _memory_search_text("trailing control char\x1f")
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "string argument has a leading or trailing control character"


def test_memory_search_value_is_never_normalized_or_rewritten() -> None:
    text = _memory_search_text("Mixed CASE   with   spacing")
    result = parse_tool_selection(text, CAPABILITY_CATALOG)
    assert result.arguments["value"] == "Mixed CASE   with   spacing"


def test_memory_search_rejected_value_is_never_echoed_in_the_error() -> None:
    marker = "UNIQUE_SECRET_TO_NEVER_LEAK_MEMSEARCH"
    text = _memory_search_text(marker + ("x" * 501))
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert marker not in reason


# --- Phase 93, Batch 1: approval_history / workflow_history validation -----


def _history_text(capability_id: str, arguments: object) -> str:
    return json.dumps(
        {
            "decision": "execute",
            "capability_id": capability_id,
            "arguments": arguments,
        }
    )


@pytest.mark.parametrize("capability_id", ["approval_history", "workflow_history"])
def test_history_capability_valid_selection(capability_id: str) -> None:
    result = parse_tool_selection(
        _history_text(capability_id, {}), CAPABILITY_CATALOG
    )
    assert result.decision is ToolSelectionDecision.EXECUTE
    assert result.capability_id is CapabilityId(capability_id)
    assert result.arguments == {}


@pytest.mark.parametrize("capability_id", ["approval_history", "workflow_history"])
@pytest.mark.parametrize(
    "stray_arguments",
    [
        {"operation": "history"},
        {"operation": "recent"},
        {"limit": 20},
        {"status": "approved"},
        {"request_id": "abc"},
        {"workflow_id": "abc"},
        {"id": "abc"},
        {"filter": "declined"},
    ],
)
def test_history_capability_rejects_any_extra_argument(
    capability_id: str, stray_arguments: dict[str, object]
) -> None:
    reason = _fails(
        _history_text(capability_id, stray_arguments), catalog=CAPABILITY_CATALOG
    )
    assert reason == "unknown argument name in model output"


@pytest.mark.parametrize("capability_id", ["approval_history", "workflow_history"])
@pytest.mark.parametrize(
    "malformed_arguments_json",
    ['"not an object"', "[]", "null", "42", "true", "false"],
)
def test_history_capability_rejects_malformed_arguments_container(
    capability_id: str, malformed_arguments_json: str
) -> None:
    text = (
        '{"decision": "execute", "capability_id": "'
        + capability_id
        + '", "arguments": '
        + malformed_arguments_json
        + "}"
    )
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "arguments must be a JSON object"


def test_history_like_unsupported_capability_name_is_rejected() -> None:
    """A plausible-sounding but non-catalogued capability name (never
    invented as a real CapabilityId) is rejected exactly like any other
    unknown capability id - proving no implicit or fuzzy name matching
    exists for the new history capabilities."""
    text = _history_text("history", {})
    reason = _fails(text, catalog=CAPABILITY_CATALOG)
    assert reason == "unknown capability id"


def test_approval_history_and_workflow_history_declare_zero_arguments() -> None:
    assert CAPABILITY_CATALOG[CapabilityId.APPROVAL_HISTORY].arguments == ()
    assert CAPABILITY_CATALOG[CapabilityId.WORKFLOW_HISTORY].arguments == ()


def test_history_capabilities_are_not_internal_only() -> None:
    assert CAPABILITY_CATALOG[CapabilityId.APPROVAL_HISTORY].internal_only is False
    assert CAPABILITY_CATALOG[CapabilityId.WORKFLOW_HISTORY].internal_only is False
