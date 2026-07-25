"""
test_schedule_compound_grounding.py

Focused tests for intelligence/schedule_compound_grounding.py (Phase
99, Batch 1 - docs/phase_99_second_compound_template_planning.md):
the second, dormant, trusted compound template
(SCHEDULE_ENABLE -> SCHEDULE_SHOW_ENABLED_STATE), mirroring
test_compound_grounding.py's own established structure for the first
template.

Covers: the template allowlist stays a single, separate entry never
merged into intelligence.compound_grounding's own live allowlist;
connector/clause splitting; per-clause signature and numeric-argument
grounding; and the one requirement unique to this template - the two
steps' own declared schedule_id values must agree exactly, refused
otherwise, never resolved by inference or substitution.
"""

from __future__ import annotations

import inspect
import json

from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId
from intelligence.compound_grounding import (
    CompoundGroundingResult,
    CompoundUngroundedReason,
)
from intelligence.compound_structured_output import (
    CompoundToolSelectionDecision,
    CompoundToolSelectionStep,
    ParsedCompoundToolSelection,
    parse_compound_tool_selection,
)
from intelligence.schedule_compound_grounding import (
    _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES,
    ground_schedule_compound_decision,
)

_ENABLE_STEP = {"capability_id": "schedule_enable", "arguments": {"schedule_id": 5}}
_SHOW_STEP = {
    "capability_id": "schedule_show_enabled_state",
    "arguments": {"schedule_id": 5},
}


def _parsed(steps: list[object]) -> ParsedCompoundToolSelection:
    raw = json.dumps({"decision": "execute_sequence", "steps": steps})
    return parse_compound_tool_selection(raw, CAPABILITY_CATALOG)


def _manual(
    step1_capability: CapabilityId,
    step1_arguments: dict[str, object],
    step2_capability: CapabilityId,
    step2_arguments: dict[str, object],
) -> ParsedCompoundToolSelection:
    return ParsedCompoundToolSelection(
        decision=CompoundToolSelectionDecision.EXECUTE_SEQUENCE,
        steps=(
            CompoundToolSelectionStep(
                capability_id=step1_capability, arguments=step1_arguments
            ),
            CompoundToolSelectionStep(
                capability_id=step2_capability, arguments=step2_arguments
            ),
        ),
    )


_VALID_TEXT = "enable schedule 5 and then check the enabled state of schedule 5"


class TestTemplateAllowlist:
    def test_only_one_ordered_pair_is_allowlisted(self) -> None:
        assert len(_ALLOWED_SCHEDULE_COMPOUND_TEMPLATES) == 1
        (template,) = _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES
        assert template.steps == (
            CapabilityId.SCHEDULE_ENABLE,
            CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
        )

    def test_reversed_pair_is_rejected(self) -> None:
        parsed = _manual(
            CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
            {"schedule_id": 5},
            CapabilityId.SCHEDULE_ENABLE,
            {"schedule_id": 5},
        )
        result = ground_schedule_compound_decision(
            request_text="check the enabled state of schedule 5 and then enable schedule 5",
            parsed=parsed,
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_disallowed_pair_is_rejected(self) -> None:
        parsed = _manual(
            CapabilityId.SCHEDULE_DISABLE,
            {"schedule_id": 5},
            CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
            {"schedule_id": 5},
        )
        result = ground_schedule_compound_decision(
            request_text="disable schedule 5 and then check the enabled state of schedule 5",
            parsed=parsed,
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_project_state_pair_is_rejected_by_this_template_too(self) -> None:
        """This module recognizes only its own one pair - the
        ProjectState template's pair is not accidentally accepted."""
        parsed = _manual(
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            {"value": "97"},
            CapabilityId.PROJECT_STATE_SHOW,
            {},
        )
        result = ground_schedule_compound_decision(
            request_text="update phase to 97 and then show project state",
            parsed=parsed,
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_never_merged_into_the_live_compound_grounding_allowlist(self) -> None:
        from intelligence.compound_grounding import _ALLOWED_COMPOUND_TEMPLATES

        schedule_template_ids = {
            t.template_id for t in _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES
        }
        live_template_ids = {t.template_id for t in _ALLOWED_COMPOUND_TEMPLATES}
        assert schedule_template_ids.isdisjoint(live_template_ids)
        assert len(_ALLOWED_COMPOUND_TEMPLATES) == 1  # unchanged by this batch


class TestConnectorAndClauses:
    def test_valid_request_grounds(self) -> None:
        result = ground_schedule_compound_decision(
            request_text=_VALID_TEXT, parsed=_parsed([_ENABLE_STEP, _SHOW_STEP])
        )
        assert result.grounded is True

    def test_missing_connector_refuses(self) -> None:
        result = ground_schedule_compound_decision(
            request_text="enable schedule 5 then check the enabled state of schedule 5",
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_repeated_connector_refuses(self) -> None:
        result = ground_schedule_compound_decision(
            request_text=(
                "enable schedule 5 and then enable schedule 5 and then "
                "check the enabled state of schedule 5"
            ),
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.CONNECTOR_REPEATED

    def test_negated_request_refuses_before_any_other_check(self) -> None:
        result = ground_schedule_compound_decision(
            request_text="do not " + _VALID_TEXT,
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


class TestClauseGrounding:
    def test_clause_1_wrong_signature_refuses(self) -> None:
        result = ground_schedule_compound_decision(
            request_text="disable schedule 5 and then check the enabled state of schedule 5",
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason in (
            CompoundUngroundedReason.CLAUSE_NO_SIGNATURE_MATCHED,
            CompoundUngroundedReason.CLAUSE_CAPABILITY_MISMATCH,
        )

    def test_clause_2_wrong_signature_refuses(self) -> None:
        result = ground_schedule_compound_decision(
            request_text="enable schedule 5 and then show my schedules",
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason in (
            CompoundUngroundedReason.CLAUSE_NO_SIGNATURE_MATCHED,
            CompoundUngroundedReason.CLAUSE_CAPABILITY_MISMATCH,
        )

    def test_clause_1_wrong_id_refuses(self) -> None:
        """Clause 1's own text says schedule 6, but the model declared
        schedule_id=5 for step 1 - refused as a clause-argument
        mismatch, never guessed at."""
        result = ground_schedule_compound_decision(
            request_text="enable schedule 6 and then check the enabled state of schedule 5",
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    def test_clause_2_wrong_id_refuses(self) -> None:
        result = ground_schedule_compound_decision(
            request_text="enable schedule 5 and then check the enabled state of schedule 6",
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    def test_ambiguous_numeric_span_in_clause_refuses(self) -> None:
        result = ground_schedule_compound_decision(
            request_text=(
                "enable schedule 5 and then check the enabled state of "
                "schedule 5 please"
            ),
            parsed=_parsed([_ENABLE_STEP, _SHOW_STEP]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH


class TestSameScheduleIdRequirement:
    """The one requirement unique to this template (Phase 99, Batch 1):
    the two steps' own declared schedule_id values must agree exactly -
    the AI must never invent or substitute a different id for step 2.
    No pronoun inference, no general variable-passing/result-propagation
    mechanism - a single, narrow, hardcoded equality check."""

    def test_matching_ids_across_both_steps_grounds(self) -> None:
        result = ground_schedule_compound_decision(
            request_text=_VALID_TEXT, parsed=_parsed([_ENABLE_STEP, _SHOW_STEP])
        )
        assert result.grounded is True

    def test_differing_declared_ids_across_steps_is_refused(self) -> None:
        """Both clauses' own text legitimately supports their own
        respective declared value (5 and 6) - grounded per-clause - but
        the two steps disagree with *each other*, which must still be
        refused: the AI is never trusted to silently target two
        different schedules under one approval."""
        mismatched_show_step = {
            "capability_id": "schedule_show_enabled_state",
            "arguments": {"schedule_id": 6},
        }
        result = ground_schedule_compound_decision(
            request_text=(
                "enable schedule 5 and then check the enabled state of schedule 6"
            ),
            parsed=_parsed([_ENABLE_STEP, mismatched_show_step]),
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    def test_same_id_requirement_is_never_satisfied_by_inference_from_one_clause_alone(
        self,
    ) -> None:
        """Structural proof: ground_schedule_compound_decision()'s own
        body reads both steps' already-parsed
        `arguments["schedule_id"]` values directly and compares them
        with `!=` - never the live request_text a second time (no
        second call to any _extract_*/normalize helper after the
        per-clause loop), never a reference-resolution helper, and
        never a generic "copy the prior step's output" mechanism."""
        from intelligence.schedule_compound_grounding import (
            ground_schedule_compound_decision,
        )

        source = inspect.getsource(ground_schedule_compound_decision)
        # The orchestrating function itself never calls the low-level
        # numeric-span extractor directly - that only ever happens
        # inside _ground_schedule_clause_argument()'s own body, called
        # once per clause; the cross-step check that follows reads only
        # each step's own already-parsed arguments dict.
        assert "_extract_numeric_argument_span" not in source
        for forbidden in (
            "it_refers_to",
            "result_from_previous_step",
            "propagate",
            "input_from_previous_step",
        ):
            assert forbidden not in source.casefold()


class TestNoArbitraryStepCountOrCapability:
    def test_a_third_step_is_never_accepted_by_this_module_either(self) -> None:
        """parse_compound_tool_selection() itself already rejects a
        three-step declaration (Phase 97, unchanged) - this test proves
        that remains true for this template's own two capabilities."""
        import pytest

        from intelligence.compound_structured_output import (
            CompoundToolSelectionParseError,
        )

        raw = json.dumps(
            {
                "decision": "execute_sequence",
                "steps": [_ENABLE_STEP, _SHOW_STEP, _SHOW_STEP],
            }
        )
        with pytest.raises(CompoundToolSelectionParseError):
            parse_compound_tool_selection(raw, CAPABILITY_CATALOG)


def test_grounded_result_never_carries_a_reason() -> None:
    result = ground_schedule_compound_decision(
        request_text=_VALID_TEXT, parsed=_parsed([_ENABLE_STEP, _SHOW_STEP])
    )
    assert result == CompoundGroundingResult(grounded=True)
