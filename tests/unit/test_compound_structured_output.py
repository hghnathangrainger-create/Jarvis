"""
test_compound_structured_output.py

Focused tests for intelligence/compound_structured_output.py (Phase 97
- docs/phase_97_implementation_plan.md). Covers the "Compound parser
tests" (items 7-25) from the Phase 97 implementation task.

These tests exercise only the new, isolated compound parser - never
intelligence.structured_output's own live parser (see
test_compound_isolation.py for the isolation proof itself).
"""

from __future__ import annotations

import json

import pytest

from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId
from intelligence.compound_structured_output import (
    CompoundToolSelectionDecision,
    CompoundToolSelectionParseError,
    CompoundToolSelectionStep,
    ParsedCompoundToolSelection,
    parse_compound_tool_selection,
)

_PHASE_STEP = {
    "capability_id": "project_state_update_phase",
    "arguments": {"value": "97"},
}
_SHOW_STEP = {
    "capability_id": "project_state_show",
    "arguments": {},
}


def _payload(steps: list[object]) -> str:
    return json.dumps({"decision": "execute_sequence", "steps": steps})


def _parse(raw_text: str) -> ParsedCompoundToolSelection:
    return parse_compound_tool_selection(raw_text, CAPABILITY_CATALOG)


class TestExactAllowedSchema:
    def test_exact_allowed_schema_parses(self) -> None:
        raw = _payload([_PHASE_STEP, _SHOW_STEP])
        parsed = _parse(raw)

        assert parsed.decision is CompoundToolSelectionDecision.EXECUTE_SEQUENCE
        assert parsed.steps == (
            CompoundToolSelectionStep(
                capability_id=CapabilityId.PROJECT_STATE_UPDATE_PHASE,
                arguments={"value": "97"},
            ),
            CompoundToolSelectionStep(
                capability_id=CapabilityId.PROJECT_STATE_SHOW, arguments={}
            ),
        )

    def test_order_is_preserved_not_reinterpreted(self) -> None:
        raw = _payload([_SHOW_STEP, _PHASE_STEP])
        parsed = _parse(raw)

        assert parsed.steps[0].capability_id is CapabilityId.PROJECT_STATE_SHOW
        assert parsed.steps[1].capability_id is CapabilityId.PROJECT_STATE_UPDATE_PHASE


class TestStepCount:
    def test_exactly_two_steps_required(self) -> None:
        _parse(_payload([_PHASE_STEP, _SHOW_STEP]))  # does not raise

    def test_fewer_steps_rejects(self) -> None:
        with pytest.raises(CompoundToolSelectionParseError, match="exactly two"):
            _parse(_payload([_PHASE_STEP]))

    def test_zero_steps_rejects(self) -> None:
        with pytest.raises(CompoundToolSelectionParseError, match="exactly two"):
            _parse(_payload([]))

    def test_additional_steps_reject(self) -> None:
        with pytest.raises(CompoundToolSelectionParseError, match="exactly two"):
            _parse(_payload([_PHASE_STEP, _SHOW_STEP, _SHOW_STEP]))

    def test_non_list_steps_reject(self) -> None:
        raw = json.dumps({"decision": "execute_sequence", "steps": "not-a-list"})
        with pytest.raises(CompoundToolSelectionParseError, match="JSON array"):
            _parse(raw)


class TestStepShape:
    def test_non_object_step_rejects(self) -> None:
        with pytest.raises(CompoundToolSelectionParseError, match="JSON object"):
            _parse(_payload(["not-a-step", _SHOW_STEP]))

    def test_missing_capability_rejects(self) -> None:
        bad_step = {"arguments": {}}
        with pytest.raises(CompoundToolSelectionParseError, match="unexpected or missing"):
            _parse(_payload([bad_step, _SHOW_STEP]))

    def test_missing_arguments_rejects(self) -> None:
        bad_step = {"capability_id": "project_state_show"}
        with pytest.raises(CompoundToolSelectionParseError, match="unexpected or missing"):
            _parse(_payload([_PHASE_STEP, bad_step]))

    def test_non_object_arguments_reject(self) -> None:
        bad_step = {"capability_id": "project_state_show", "arguments": "nope"}
        with pytest.raises(CompoundToolSelectionParseError, match="arguments must be"):
            _parse(_payload([_PHASE_STEP, bad_step]))

    def test_extra_step_field_rejects(self) -> None:
        bad_step = {
            "capability_id": "project_state_show",
            "arguments": {},
            "tool_name": "project_state_show",
        }
        with pytest.raises(CompoundToolSelectionParseError, match="unexpected or missing"):
            _parse(_payload([_PHASE_STEP, bad_step]))


class TestCapabilityValidity:
    def test_unknown_capability_rejects(self) -> None:
        bad_step = {"capability_id": "not_a_real_capability", "arguments": {}}
        with pytest.raises(CompoundToolSelectionParseError, match="unknown capability"):
            _parse(_payload([_PHASE_STEP, bad_step]))

    def test_internal_only_capability_rejects(self) -> None:
        bad_step = {"capability_id": "project_state_verify_focus", "arguments": {}}
        with pytest.raises(CompoundToolSelectionParseError, match="internal-only"):
            _parse(_payload([_PHASE_STEP, bad_step]))

    def test_schedule_internal_verifier_rejects(self) -> None:
        bad_step = {"capability_id": "schedule_verify_enabled_state", "arguments": {}}
        with pytest.raises(CompoundToolSelectionParseError, match="internal-only"):
            _parse(_payload([bad_step, _SHOW_STEP]))

    def test_duplicate_capability_rejects(self) -> None:
        with pytest.raises(CompoundToolSelectionParseError, match="duplicate"):
            _parse(_payload([_PHASE_STEP, _PHASE_STEP]))


class TestTopLevelShape:
    def test_extra_top_level_field_rejects(self) -> None:
        raw = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [_PHASE_STEP, _SHOW_STEP],
                "context": "extra",
            }
        )
        with pytest.raises(CompoundToolSelectionParseError, match="unexpected or missing"):
            _parse(raw)

    def test_missing_decision_rejects(self) -> None:
        raw = json.dumps({"steps": [_PHASE_STEP, _SHOW_STEP]})
        with pytest.raises(CompoundToolSelectionParseError, match="unexpected or missing"):
            _parse(raw)

    def test_missing_steps_rejects(self) -> None:
        raw = json.dumps({"decision": "execute_sequence"})
        with pytest.raises(CompoundToolSelectionParseError, match="unexpected or missing"):
            _parse(raw)

    def test_wrong_decision_value_rejects(self) -> None:
        raw = json.dumps({"decision": "execute", "steps": [_PHASE_STEP, _SHOW_STEP]})
        with pytest.raises(CompoundToolSelectionParseError, match="unknown or missing"):
            _parse(raw)

    def test_execute_sequence_literal_itself_is_accepted(self) -> None:
        raw = json.dumps(
            {"decision": "execute_sequence", "steps": [_PHASE_STEP, _SHOW_STEP]}
        )
        _parse(raw)  # does not raise


class TestArgumentReuse:
    """Proves strict, existing catalogue argument validation is reused,
    not duplicated (task requirement: "Existing catalogue argument
    constraints are honoured")."""

    def test_wrong_phase_value_type_rejects(self) -> None:
        bad_step = {
            "capability_id": "project_state_update_phase",
            "arguments": {"value": 97},
        }
        with pytest.raises(CompoundToolSelectionParseError):
            _parse(_payload([bad_step, _SHOW_STEP]))

    def test_missing_phase_value_rejects(self) -> None:
        bad_step = {"capability_id": "project_state_update_phase", "arguments": {}}
        with pytest.raises(CompoundToolSelectionParseError, match="missing required"):
            _parse(_payload([bad_step, _SHOW_STEP]))

    def test_unsupported_argument_name_rejects(self) -> None:
        bad_step = {
            "capability_id": "project_state_update_phase",
            "arguments": {"value": "97", "verifier_id": "x"},
        }
        with pytest.raises(CompoundToolSelectionParseError, match="unknown argument"):
            _parse(_payload([bad_step, _SHOW_STEP]))

    def test_empty_phase_value_rejects(self) -> None:
        bad_step = {
            "capability_id": "project_state_update_phase",
            "arguments": {"value": "   "},
        }
        with pytest.raises(CompoundToolSelectionParseError):
            _parse(_payload([bad_step, _SHOW_STEP]))

    def test_project_state_show_requires_empty_arguments(self) -> None:
        bad_step = {
            "capability_id": "project_state_show",
            "arguments": {"value": "unexpected"},
        }
        with pytest.raises(CompoundToolSelectionParseError, match="unknown argument"):
            _parse(_payload([_PHASE_STEP, bad_step]))

    def test_model_supplied_tier_or_workflow_metadata_rejects(self) -> None:
        bad_step = {
            "capability_id": "project_state_update_phase",
            "arguments": {
                "value": "97",
                "security_tier": "YELLOW",
                "approval_required": False,
            },
        }
        with pytest.raises(CompoundToolSelectionParseError, match="unknown argument"):
            _parse(_payload([bad_step, _SHOW_STEP]))


class TestHygiene:
    def test_oversized_output_rejects(self) -> None:
        huge_value = "x" * 3000
        with pytest.raises(CompoundToolSelectionParseError, match="too long"):
            _parse(huge_value)

    def test_malformed_json_rejects(self) -> None:
        with pytest.raises(CompoundToolSelectionParseError):
            _parse("{not valid json")

    def test_duplicate_top_level_key_rejects(self) -> None:
        raw = (
            '{"decision": "execute_sequence", "decision": "execute_sequence", '
            '"steps": []}'
        )
        with pytest.raises(CompoundToolSelectionParseError):
            _parse(raw)

    def test_single_outer_fence_is_stripped(self) -> None:
        raw = "```json\n" + _payload([_PHASE_STEP, _SHOW_STEP]) + "\n```"
        _parse(raw)  # does not raise
