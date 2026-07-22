"""
test_compound_grounding.py

Focused tests for intelligence/compound_grounding.py (Phase 97 -
docs/phase_97_implementation_plan.md). Covers "Template and order
tests" (26-31), "Connector and clause tests" (32-40), and "Clause
grounding and attribution tests" (41-57) from the Phase 97
implementation task.
"""

from __future__ import annotations

import inspect
import json

from intelligence.capability_catalog import CAPABILITY_CATALOG, CapabilityId
from intelligence.compound_grounding import (
    CompoundGroundingResult,
    CompoundUngroundedReason,
    _ALLOWED_COMPOUND_TEMPLATES,
    ground_compound_decision,
)
from intelligence.compound_structured_output import (
    CompoundToolSelectionDecision,
    CompoundToolSelectionStep,
    ParsedCompoundToolSelection,
    parse_compound_tool_selection,
)

_PHASE_STEP = {
    "capability_id": "project_state_update_phase",
    "arguments": {"value": "97"},
}
_SHOW_STEP = {"capability_id": "project_state_show", "arguments": {}}


def _parsed(steps: list[object]) -> ParsedCompoundToolSelection:
    raw = json.dumps({"decision": "execute_sequence", "steps": steps})
    return parse_compound_tool_selection(raw, CAPABILITY_CATALOG)


def _manual(
    step1_capability: CapabilityId,
    step1_arguments: dict[str, object],
    step2_capability: CapabilityId,
    step2_arguments: dict[str, object],
) -> ParsedCompoundToolSelection:
    """Build a ParsedCompoundToolSelection directly, bypassing the
    parser, so a test can exercise a declared pair the real parser
    itself never accepts (e.g. an internal-only or duplicate
    capability), isolating grounding's own, independent defense from
    the parser's own rejection of the same shape."""
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


_VALID_TEXT = "update phase to 97 and then show project state"


class TestTemplateAllowlist:
    def test_only_one_ordered_pair_is_allowlisted(self) -> None:
        assert len(_ALLOWED_COMPOUND_TEMPLATES) == 1
        template = _ALLOWED_COMPOUND_TEMPLATES[0]
        assert template.steps == (
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            CapabilityId.PROJECT_STATE_SHOW,
        )

    def test_allowlist_uses_a_tuple_never_a_set(self) -> None:
        assert isinstance(_ALLOWED_COMPOUND_TEMPLATES, tuple)
        for template in _ALLOWED_COMPOUND_TEMPLATES:
            assert isinstance(template.steps, tuple)
            assert not isinstance(template.steps, (set, frozenset))

    def test_exact_ordered_pair_is_accepted(self) -> None:
        parsed = _parsed([_PHASE_STEP, _SHOW_STEP])
        result = ground_compound_decision(request_text=_VALID_TEXT, parsed=parsed)
        assert result == CompoundGroundingResult(grounded=True)

    def test_reversed_structured_pair_is_not_accepted(self) -> None:
        # (SHOW, PHASE) is a validly-parseable pair from the real
        # parser's own perspective (no duplicate, neither internal-only)
        # - it must still be refused by grounding's own allowlist check.
        parsed = _parsed(
            [
                _SHOW_STEP,
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "97"},
                },
            ]
        )
        result = ground_compound_decision(
            request_text="show project state and then update phase to 97",
            parsed=parsed,
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_a_different_pair_is_not_accepted(self) -> None:
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_focus",
                    "arguments": {"value": "testing"},
                },
                _SHOW_STEP,
            ]
        )
        result = ground_compound_decision(
            request_text="update focus to testing and then show project state",
            parsed=parsed,
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_duplicate_pair_is_not_accepted(self) -> None:
        parsed = _manual(
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            {"value": "97"},
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            {"value": "97"},
        )
        result = ground_compound_decision(
            request_text="update phase to 97 and then update phase to 97",
            parsed=parsed,
        )
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_internal_verifier_pair_is_not_accepted(self) -> None:
        parsed = _manual(
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            {"value": "97"},
            CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
            {},
        )
        result = ground_compound_decision(request_text=_VALID_TEXT, parsed=parsed)
        assert result.grounded is False
        assert result.reason is CompoundUngroundedReason.TEMPLATE_NOT_ALLOWED

    def test_no_second_production_template_exists(self) -> None:
        template_ids = {t.template_id for t in _ALLOWED_COMPOUND_TEMPLATES}
        assert template_ids == {"project_state_update_phase_then_show"}


class TestConnectorAndClauses:
    def _ground(self, text: str) -> CompoundGroundingResult:
        parsed = _parsed([_PHASE_STEP, _SHOW_STEP])
        return ground_compound_decision(request_text=text, parsed=parsed)

    def test_exact_and_then_connector_accepted(self) -> None:
        assert self._ground(_VALID_TEXT) == CompoundGroundingResult(grounded=True)

    def test_missing_connector_rejects(self) -> None:
        result = self._ground("update phase to 97 show project state")
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_repeated_connector_rejects(self) -> None:
        result = self._ground(
            "update phase to 97 and then show project state and then again"
        )
        assert result.reason is CompoundUngroundedReason.CONNECTOR_REPEATED

    def test_empty_first_clause_rejects(self) -> None:
        result = self._ground("and then show project state")
        assert result.reason is CompoundUngroundedReason.EMPTY_CLAUSE

    def test_empty_second_clause_rejects(self) -> None:
        result = self._ground("update phase to 97 and then")
        assert result.reason is CompoundUngroundedReason.EMPTY_CLAUSE

    def test_plain_and_rejects(self) -> None:
        result = self._ground("update phase to 97 and show project state")
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_plain_then_rejects(self) -> None:
        result = self._ground("update phase to 97 then show project state")
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_comma_connector_rejects(self) -> None:
        result = self._ground("update phase to 97, show project state")
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_semicolon_connector_rejects(self) -> None:
        result = self._ground("update phase to 97; show project state")
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_after_that_connector_rejects(self) -> None:
        result = self._ground("update phase to 97 after that show project state")
        assert result.reason is CompoundUngroundedReason.CONNECTOR_MISSING

    def test_reversed_textual_order_rejects(self) -> None:
        result = self._ground("show project state and then update phase to 97")
        assert result.reason is CompoundUngroundedReason.CLAUSE_CAPABILITY_MISMATCH


class TestClauseGrounding:
    def _ground(self, text: str) -> CompoundGroundingResult:
        parsed = _parsed([_PHASE_STEP, _SHOW_STEP])
        return ground_compound_decision(request_text=text, parsed=parsed)

    def test_clause_1_uniquely_grounds_update_phase(self) -> None:
        assert self._ground(_VALID_TEXT).grounded is True

    def test_clause_2_uniquely_grounds_show(self) -> None:
        assert self._ground(_VALID_TEXT).grounded is True

    def test_exact_phase_value_matches(self) -> None:
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "implementation"},
                },
                _SHOW_STEP,
            ]
        )
        result = ground_compound_decision(
            request_text="update phase to implementation and then show project state",
            parsed=parsed,
        )
        assert result.grounded is True

    def test_wrong_phase_value_rejects(self) -> None:
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "different"},
                },
                _SHOW_STEP,
            ]
        )
        result = ground_compound_decision(request_text=_VALID_TEXT, parsed=parsed)
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    def test_expanded_phase_value_rejects(self) -> None:
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "97 and extra text"},
                },
                _SHOW_STEP,
            ]
        )
        result = ground_compound_decision(request_text=_VALID_TEXT, parsed=parsed)
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    def test_clause_2_cannot_supply_clause_1_value(self) -> None:
        # Clause 1's own text has no "to" marker at all - if clause 2's
        # text could ever leak into clause 1's attribution, this would
        # incorrectly find a value; it must not.
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "97"},
                },
                _SHOW_STEP,
            ]
        )
        result = ground_compound_decision(
            request_text="update phase and then show project state to 97",
            parsed=parsed,
        )
        assert result.grounded is False

    def test_clause_1_cannot_use_clause_2_text_for_attribution(self) -> None:
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "97"},
                },
                _SHOW_STEP,
            ]
        )
        # clause 1 text alone ("update phase to 42") does not equal the
        # declared value "97" - clause 2's own text must never rescue this.
        result = ground_compound_decision(
            request_text="update phase to 42 and then show project state to 97",
            parsed=parsed,
        )
        assert result.reason in (
            CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH,
            CompoundUngroundedReason.CLAUSE_MULTIPLE_SIGNATURES_MATCHED,
        )

    def test_clause_2_requires_zero_arguments_enforced_by_parser(self) -> None:
        # Grounding itself never receives a non-empty clause-2 arguments
        # dict in production, since the parser already rejects it - this
        # test proves the parser-level enforcement this relies on.
        import pytest

        from intelligence.compound_structured_output import (
            CompoundToolSelectionParseError,
        )

        bad_show_step = {
            "capability_id": "project_state_show",
            "arguments": {"value": "unexpected"},
        }
        with pytest.raises(CompoundToolSelectionParseError):
            _parsed([_PHASE_STEP, bad_show_step])

    def test_update_focus_clause_rejects(self) -> None:
        parsed = _manual(
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            {"value": "97"},
            CapabilityId.PROJECT_STATE_SHOW,
            {},
        )
        result = ground_compound_decision(
            request_text="update focus to testing and then show project state",
            parsed=parsed,
        )
        # Clause 1 text ("update focus to testing") uniquely grounds
        # PROJECT_STATE_UPDATE_FOCUS, not the expected PHASE capability.
        assert result.reason is CompoundUngroundedReason.CLAUSE_CAPABILITY_MISMATCH

    def test_show_schedules_clause_rejects(self) -> None:
        parsed = _parsed([_PHASE_STEP, _SHOW_STEP])
        result = ground_compound_decision(
            request_text="update phase to 97 and then show schedules",
            parsed=parsed,
        )
        assert result.reason is CompoundUngroundedReason.CLAUSE_CAPABILITY_MISMATCH

    def test_negated_clause_rejects(self) -> None:
        result = self._ground(
            "do not update phase to 97 and then show project state"
        )
        assert result.reason is CompoundUngroundedReason.NEGATED_OR_CONFLICTING_REQUEST

    def test_conflicting_clause_rejects(self) -> None:
        result = self._ground(
            "update phase to 97 instead of showing and then show project state"
        )
        assert result.reason is CompoundUngroundedReason.NEGATED_OR_CONFLICTING_REQUEST

    def test_or_alternative_rejects(self) -> None:
        parsed = _parsed(
            [
                {
                    "capability_id": "project_state_update_phase",
                    "arguments": {"value": "97"},
                },
                _SHOW_STEP,
            ]
        )
        result = ground_compound_decision(
            request_text="update phase to 97 or 98 and then show project state",
            parsed=parsed,
        )
        assert result.reason is CompoundUngroundedReason.CLAUSE_ARGUMENT_MISMATCH

    def test_multiple_signature_clause_rejects(self) -> None:
        result = self._ground(
            "update phase to 97 and then show project state and list schedules"
        )
        assert result.reason is CompoundUngroundedReason.CLAUSE_MULTIPLE_SIGNATURES_MATCHED

    def test_third_supported_action_rejects_memories_variant(self) -> None:
        result = self._ground(
            "update phase to 97 and then show project state and show recent memories"
        )
        assert result.reason is CompoundUngroundedReason.CLAUSE_MULTIPLE_SIGNATURES_MATCHED

    def test_assembled_context_is_not_accepted(self) -> None:
        signature = inspect.signature(ground_compound_decision)
        assert "assembled_context" not in signature.parameters
        assert set(signature.parameters) == {"request_text", "parsed"}
