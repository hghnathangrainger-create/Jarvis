"""
test_phase101_batch1_actionable_decision_issue.py

Focused tests for Phase 101, Batch 1 - the dormant Actionable
Required-Argument foundation
(docs/phase_101_actionable_ambiguity_planning.md). Covers the typed
issue model, the five-capability allowlist, missing-versus-invalid
classification, the independent-current-request-evidence safety rule
(the binding clarification), negation/conflict/compound safety,
Verified Action Context isolation, PlanningOutcome backward
compatibility, the deterministic formatter, and dormancy (zero live
user-facing behaviour change).

Run with:
    pytest tests/unit/test_phase101_batch1_actionable_decision_issue.py
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path

import pytest

from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIRequest, AIResponse
from ai.response_validator import ResponseValidator
from ai.router import AIRouter
from config.settings import Settings
from intelligence.actionable_decision_issue import (
    ACTIONABLE_GUIDANCE_ALLOWLIST,
    ActionableDecisionIssue,
    ActionableIssueKind,
    classify_actionable_issue_from_invalid_output,
    classify_actionable_issue_from_ungrounded_selection,
    classify_actionable_issue_from_unsupported,
    format_actionable_decision_issue,
)
from intelligence.capability_catalog import CapabilityId
from intelligence.context import AssembledContext
from intelligence.grounding import UngroundedReason
from intelligence.structured_output import ToolSelectionParseErrorKind
from intelligence.planning import PlanningOutcome, PlanningOutcomeKind, select_tool

_REPO_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Issue model
# --------------------------------------------------------------------------


class TestIssueModel:
    def test_valid_missing_integer_issue(self) -> None:
        issue = ActionableDecisionIssue(
            kind=ActionableIssueKind.MISSING_REQUIRED_ARGUMENT,
            capability_id=CapabilityId.SCHEDULE_ENABLE,
            argument_name="schedule_id",
            argument_type_name="int",
            action_label="schedule ID",
            retry_example="ask jarvis to: enable schedule <schedule id>",
            requires_approval=True,
        )
        assert issue.kind is ActionableIssueKind.MISSING_REQUIRED_ARGUMENT

    def test_valid_invalid_integer_issue(self) -> None:
        issue = ActionableDecisionIssue(
            kind=ActionableIssueKind.INVALID_ARGUMENT_FORMAT,
            capability_id=CapabilityId.SCHEDULE_ENABLE,
            argument_name="schedule_id",
            argument_type_name="int",
            action_label="schedule ID",
            retry_example="ask jarvis to: enable schedule <schedule id>",
            requires_approval=True,
        )
        assert issue.kind is ActionableIssueKind.INVALID_ARGUMENT_FORMAT

    def test_valid_missing_string_issue(self) -> None:
        issue = ActionableDecisionIssue(
            kind=ActionableIssueKind.MISSING_REQUIRED_ARGUMENT,
            capability_id=CapabilityId.MEMORY_SEARCH,
            argument_name="value",
            argument_type_name="str",
            action_label="search text",
            retry_example="ask jarvis to: search memories for <search text>",
            requires_approval=False,
        )
        assert issue.argument_type_name == "str"

    def test_unsupported_capability_rejected(self) -> None:
        with pytest.raises(ValueError):
            ActionableDecisionIssue(
                kind=ActionableIssueKind.MISSING_REQUIRED_ARGUMENT,
                capability_id=CapabilityId.PROJECT_STATE_SHOW,
                argument_name="x",
                argument_type_name="str",
                action_label="x",
                retry_example="x",
                requires_approval=False,
            )

    def test_unsupported_argument_type_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            ActionableDecisionIssue(
                kind=ActionableIssueKind.MISSING_REQUIRED_ARGUMENT,
                capability_id=CapabilityId.SCHEDULE_ENABLE,
                argument_name="schedule_id",
                argument_type_name="float",
                action_label="schedule ID",
                retry_example="ask jarvis to: enable schedule <schedule id>",
                requires_approval=True,
            )

    def test_missing_retry_template_rejected(self) -> None:
        with pytest.raises(ValueError):
            ActionableDecisionIssue(
                kind=ActionableIssueKind.MISSING_REQUIRED_ARGUMENT,
                capability_id=CapabilityId.SCHEDULE_ENABLE,
                argument_name="schedule_id",
                argument_type_name="int",
                action_label="schedule ID",
                retry_example="",
                requires_approval=True,
            )

    def test_dataclass_has_no_field_capable_of_storing_a_guessed_value(self) -> None:
        """Structural proof: ActionableDecisionIssue has no field named
        or shaped to hold an actual argument *value* - only its name,
        type, and a fixed placeholder-bearing template."""
        field_names = {f.name for f in dataclasses.fields(ActionableDecisionIssue)}
        assert field_names == {
            "kind", "capability_id", "argument_name", "argument_type_name",
            "action_label", "retry_example", "requires_approval",
        }
        assert "value" not in field_names
        assert "argument_value" not in field_names

    def test_immutable(self) -> None:
        issue = ActionableDecisionIssue(
            kind=ActionableIssueKind.MISSING_REQUIRED_ARGUMENT,
            capability_id=CapabilityId.SCHEDULE_ENABLE,
            argument_name="schedule_id",
            argument_type_name="int",
            action_label="schedule ID",
            retry_example="ask jarvis to: enable schedule <schedule id>",
            requires_approval=True,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            issue.capability_id = CapabilityId.MEMORY_SEARCH  # type: ignore[misc]

    def test_issue_kind_has_exactly_two_members(self) -> None:
        assert {member.value for member in ActionableIssueKind} == {
            "missing_required_argument", "invalid_argument_format",
        }

    def test_allowlist_has_exactly_the_five_accepted_capabilities(self) -> None:
        assert ACTIONABLE_GUIDANCE_ALLOWLIST == frozenset(
            {
                CapabilityId.SCHEDULE_ENABLE,
                CapabilityId.SCHEDULE_DISABLE,
                CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
                CapabilityId.MEMORY_SEARCH,
                CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            }
        )


# --------------------------------------------------------------------------
# All five capabilities - missing required argument
# --------------------------------------------------------------------------


class TestAllFiveCapabilitiesMissingArgument:
    @pytest.mark.parametrize(
        "request_text,expected_capability",
        [
            ("enable schedule", CapabilityId.SCHEDULE_ENABLE),
            ("disable schedule", CapabilityId.SCHEDULE_DISABLE),
            ("check the enabled state of schedule", CapabilityId.SCHEDULE_SHOW_ENABLED_STATE),
            ("search memories for", CapabilityId.MEMORY_SEARCH),
            ("update my project phase to", CapabilityId.PROJECT_STATE_UPDATE_PHASE),
        ],
    )
    def test_missing_argument_classified_via_unsupported(
        self, request_text, expected_capability
    ) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text=request_text)
        assert issue is not None
        assert issue.capability_id is expected_capability
        assert issue.kind is ActionableIssueKind.MISSING_REQUIRED_ARGUMENT

    @pytest.mark.parametrize(
        "request_text,capability_id",
        [
            ("enable schedule", CapabilityId.SCHEDULE_ENABLE),
            ("disable schedule", CapabilityId.SCHEDULE_DISABLE),
            ("check the enabled state of schedule", CapabilityId.SCHEDULE_SHOW_ENABLED_STATE),
            ("search memories for", CapabilityId.MEMORY_SEARCH),
            ("update my project phase to", CapabilityId.PROJECT_STATE_UPDATE_PHASE),
        ],
    )
    def test_missing_argument_classified_via_ungrounded_selection(
        self, request_text, capability_id
    ) -> None:
        # Mirrors the real, already-computed grounding evidence that
        # would exist at select_tool()'s own UNGROUNDED_SELECTION call
        # site for this exact request.
        issue = classify_actionable_issue_from_ungrounded_selection(
            capability_id=capability_id,
            reason=UngroundedReason.MISSING_ARGUMENT_SPAN,
        )
        assert issue is not None
        assert issue.capability_id is capability_id
        assert issue.kind is ActionableIssueKind.MISSING_REQUIRED_ARGUMENT


# --------------------------------------------------------------------------
# Invalid format
# --------------------------------------------------------------------------


class TestInvalidFormat:
    def test_non_integer_schedule_id(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="enable schedule twelve"
        )
        assert issue is not None
        assert issue.kind is ActionableIssueKind.INVALID_ARGUMENT_FORMAT
        assert issue.capability_id is CapabilityId.SCHEDULE_ENABLE

    def test_decimal_schedule_id(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="disable schedule 4.5"
        )
        assert issue is not None
        assert issue.kind is ActionableIssueKind.INVALID_ARGUMENT_FORMAT

    def test_negative_schedule_id(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="enable schedule -5"
        )
        assert issue is not None
        assert issue.kind is ActionableIssueKind.INVALID_ARGUMENT_FORMAT

    def test_empty_whitespace_string_treated_as_missing(self) -> None:
        # "search memories for   " normalizes (trailing whitespace
        # stripped) to no trailing content at all after the marker -
        # the existing grounding evidence classifies this as missing,
        # not invalid (Section 6 of the accepted planning amendment).
        issue = classify_actionable_issue_from_unsupported(
            request_text="search memories for   "
        )
        assert issue is not None
        assert issue.kind is ActionableIssueKind.MISSING_REQUIRED_ARGUMENT

    def test_valid_schedule_id_produces_no_issue(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="enable schedule 5"
        )
        assert issue is None

    def test_valid_search_query_produces_no_issue(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="search memories for budget planning"
        )
        assert issue is None


# --------------------------------------------------------------------------
# Independent evidence (the binding safety clarification)
# --------------------------------------------------------------------------


class TestIndependentEvidence:
    def test_request_and_model_capability_agree(self) -> None:
        raw = json.dumps(
            {"decision": "execute", "capability_id": "schedule_enable", "arguments": {}}
        )
        issue = classify_actionable_issue_from_invalid_output(
            raw_text=raw,
            request_text="enable schedule",
            kind=ToolSelectionParseErrorKind.MISSING_REQUIRED_ARGUMENT,
        )
        assert issue is not None
        assert issue.capability_id is CapabilityId.SCHEDULE_ENABLE

    def test_model_selects_allowlisted_capability_but_request_does_not_identify_it(
        self,
    ) -> None:
        raw = json.dumps(
            {"decision": "execute", "capability_id": "schedule_enable", "arguments": {}}
        )
        issue = classify_actionable_issue_from_invalid_output(
            raw_text=raw,
            request_text="do something with my schedules",
            kind=ToolSelectionParseErrorKind.MISSING_REQUIRED_ARGUMENT,
        )
        assert issue is None

    def test_request_identifies_capability_but_model_selects_another(self) -> None:
        raw = json.dumps(
            {"decision": "execute", "capability_id": "memory_search", "arguments": {}}
        )
        issue = classify_actionable_issue_from_invalid_output(
            raw_text=raw,
            request_text="enable schedule",
            kind=ToolSelectionParseErrorKind.MISSING_REQUIRED_ARGUMENT,
        )
        assert issue is None

    def test_unsupported_with_independently_provable_missing_argument(self) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        assert issue is not None
        assert issue.capability_id is CapabilityId.SCHEDULE_ENABLE

    def test_malformed_provider_output_remains_generic(self) -> None:
        issue = classify_actionable_issue_from_invalid_output(
            raw_text="not even json{{{",
            request_text="enable schedule",
            kind=ToolSelectionParseErrorKind.OTHER,
        )
        assert issue is None

    def test_unknown_capability_remains_generic(self) -> None:
        raw = json.dumps(
            {"decision": "execute", "capability_id": "not_a_real_capability", "arguments": {}}
        )
        issue = classify_actionable_issue_from_invalid_output(
            raw_text=raw,
            request_text="enable schedule",
            kind=ToolSelectionParseErrorKind.MISSING_REQUIRED_ARGUMENT,
        )
        assert issue is None

    def test_unrelated_kind_never_reinterpreted(self) -> None:
        """A capability_id that peeks successfully must not be enough
        on its own - the original failure must actually have been
        about the argument (kind must be one of the eligible three,
        never OTHER)."""
        raw = json.dumps(
            {"decision": "bogus", "capability_id": "schedule_enable", "arguments": {}}
        )
        issue = classify_actionable_issue_from_invalid_output(
            raw_text=raw,
            request_text="enable schedule",
            kind=ToolSelectionParseErrorKind.OTHER,
        )
        assert issue is None

    def test_non_allowlisted_capability_never_receives_guidance(self) -> None:
        raw = json.dumps(
            {"decision": "execute", "capability_id": "project_state_show", "arguments": {}}
        )
        issue = classify_actionable_issue_from_invalid_output(
            raw_text=raw,
            request_text="show my project state",
            kind=ToolSelectionParseErrorKind.MISSING_REQUIRED_ARGUMENT,
        )
        assert issue is None


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------


class TestSafety:
    def test_negated_request_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text="do not enable schedule"
        ) is None

    def test_negated_request_with_contraction_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text="don't update my project phase"
        ) is None

    def test_conflicting_request_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text="enable and disable schedule 5"
        ) is None

    def test_vague_request_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text="do something with my schedules"
        ) is None

    def test_ambiguous_signature_match_gets_no_issue(self) -> None:
        # A request that plausibly touches more than one capability's
        # own signature at once must never be narrowed to just the
        # allowlisted one.
        issue = classify_actionable_issue_from_unsupported(
            request_text="enable schedule and disable schedule"
        )
        assert issue is None

    def test_compound_request_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text=(
                "enable schedule 5 and then check the enabled state of schedule 5"
            )
        ) is None

    def test_compound_request_with_missing_ids_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text=(
                "enable schedule and then check the enabled state of schedule"
            )
        ) is None

    def test_project_state_compound_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text=(
                "update my project phase to Phase 100 and then show my project state"
            )
        ) is None

    def test_unsupported_capability_outside_allowlist_gets_no_issue(self) -> None:
        assert classify_actionable_issue_from_unsupported(
            request_text="show my project state"
        ) is None

    def test_internal_parser_failure_gets_no_issue(self) -> None:
        issue = classify_actionable_issue_from_invalid_output(
            raw_text="{completely malformed",
            request_text="enable schedule",
            kind=ToolSelectionParseErrorKind.OTHER,
        )
        assert issue is None


# --------------------------------------------------------------------------
# Context isolation (Verified Action Context boundary)
# --------------------------------------------------------------------------


class TestContextIsolation:
    def test_historical_schedule_id_not_copied(self) -> None:
        """Historical schedule 12 is never consulted at all - the
        classifier has no context parameter to receive it through."""
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        assert issue is not None
        assert "12" not in issue.retry_example
        assert issue.retry_example == "ask jarvis to: enable schedule <schedule id>"

    def test_historical_project_state_value_not_copied(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="update my project phase to"
        )
        assert issue is not None
        assert "<phase value>" in issue.retry_example

    def test_retry_examples_always_contain_placeholders(self) -> None:
        for capability_id in ACTIONABLE_GUIDANCE_ALLOWLIST:
            issue = None
            for text in (
                "enable schedule",
                "disable schedule",
                "check the enabled state of schedule",
                "search memories for",
                "update my project phase to",
            ):
                candidate = classify_actionable_issue_from_unsupported(request_text=text)
                if candidate is not None and candidate.capability_id is capability_id:
                    issue = candidate
                    break
            assert issue is not None
            assert "<" in issue.retry_example and ">" in issue.retry_example

    def test_module_has_no_reference_to_verified_action_context(self) -> None:
        source = (_REPO_ROOT / "intelligence/actionable_decision_issue.py").read_text(
            encoding="utf-8"
        )
        assert "verified_action_context" not in source
        assert "VerifiedAction" not in source
        assert "ContextAssembler" not in source
        assert "AssembledContext" not in source

    def test_classifier_functions_have_no_context_parameter(self) -> None:
        import inspect

        from intelligence import actionable_decision_issue as module

        for fn in (
            module.classify_actionable_issue_from_ungrounded_selection,
            module.classify_actionable_issue_from_invalid_output,
            module.classify_actionable_issue_from_unsupported,
        ):
            params = set(inspect.signature(fn).parameters)
            assert "context" not in params
            assert "assembled_context" not in params
            assert "verified_action_context" not in params


# --------------------------------------------------------------------------
# PlanningOutcome compatibility
# --------------------------------------------------------------------------


class TestPlanningOutcomeCompatibility:
    def test_default_actionable_issue_is_none(self) -> None:
        outcome = PlanningOutcome(kind=PlanningOutcomeKind.EXECUTABLE)
        assert outcome.actionable_issue is None

    def test_existing_construction_without_the_field_still_works(self) -> None:
        outcome = PlanningOutcome(
            kind=PlanningOutcomeKind.UNGROUNDED_SELECTION, detail="no_signature_matched"
        )
        assert outcome.actionable_issue is None
        assert outcome.detail == "no_signature_matched"

    def test_field_present_on_the_dataclass(self) -> None:
        field_names = {f.name for f in dataclasses.fields(PlanningOutcome)}
        assert "actionable_issue" in field_names

    def test_executable_outcomes_never_carry_an_issue(self) -> None:
        outcome = PlanningOutcome(kind=PlanningOutcomeKind.EXECUTABLE)
        assert outcome.actionable_issue is None
        outcome2 = PlanningOutcome(kind=PlanningOutcomeKind.EXECUTABLE_WORKFLOW)
        assert outcome2.actionable_issue is None


# --------------------------------------------------------------------------
# Formatter
# --------------------------------------------------------------------------


class TestFormatter:
    def test_exact_wording_missing_schedule_enable(self) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        assert format_actionable_decision_issue(issue) == (
            "I need the schedule ID before I can prepare this action. "
            "Try: ask jarvis to: enable schedule <schedule id>. "
            "Enabling a schedule will still require approval."
        )

    def test_exact_wording_missing_schedule_show(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="check the enabled state of schedule"
        )
        assert format_actionable_decision_issue(issue) == (
            "I need the schedule ID before I can prepare this action. "
            "Try: ask jarvis to: check the enabled state of schedule <schedule id>."
        )

    def test_exact_wording_invalid_integer(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="enable schedule twelve"
        )
        assert format_actionable_decision_issue(issue) == (
            "The schedule ID must be a whole number. "
            "Try: ask jarvis to: enable schedule <schedule id>. "
            "Enabling a schedule will still require approval."
        )

    def test_yellow_capability_has_approval_warning(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="update my project phase to"
        )
        text = format_actionable_decision_issue(issue)
        assert "still require approval" in text

    def test_green_capability_has_no_approval_warning(self) -> None:
        issue = classify_actionable_issue_from_unsupported(
            request_text="search memories for"
        )
        text = format_actionable_decision_issue(issue)
        assert "approval" not in text.lower()

    def test_placeholders_preserved_never_real_values(self) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        text = format_actionable_decision_issue(issue)
        assert "<schedule id>" in text

    def test_no_internal_identifiers_in_output(self) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        text = format_actionable_decision_issue(issue)
        for leaky in (
            "CapabilityId", "schedule_enable", "MISSING_REQUIRED_ARGUMENT",
            "UngroundedReason", "MISSING_ARGUMENT_SPAN",
        ):
            assert leaky not in text

    def test_no_ai_generated_phrasing(self) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        text = format_actionable_decision_issue(issue)
        for phrase in ("I think you meant", "probably", "maybe", "it seems"):
            assert phrase.lower() not in text.lower()

    def test_stable_repeated_output(self) -> None:
        issue = classify_actionable_issue_from_unsupported(request_text="enable schedule")
        first = format_actionable_decision_issue(issue)
        second = format_actionable_decision_issue(issue)
        assert first == second


# --------------------------------------------------------------------------
# Dormancy
# --------------------------------------------------------------------------


class _FakeAIProvider(AIProvider):
    def __init__(self, text: str) -> None:
        self._text = text
        self.received_requests: list[AIRequest] = []

    @property
    def name(self) -> str:
        return "fake"

    def generate(self, request: AIRequest) -> AIResponse:
        self.received_requests.append(request)
        return AIResponse(text=self._text, model="fake-model", provider="fake")

    def is_available(self) -> bool:
        return True


class _RecordingLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


def _settings() -> Settings:
    return Settings(
        anthropic_api_key="test-key-not-real",
        ai_model="test-model",
        ai_max_tokens=1024,
        database_path=Path("unused.db"),
        log_level="INFO",
        approval_timeout_seconds=60,
        debug=False,
        ai_reasoning_enabled=True,
    )


def _empty_context() -> AssembledContext:
    return AssembledContext(
        request_text="", items=(), total_chars=0, truncated=False, notes=()
    )


class TestDormancy:
    def test_select_tool_itself_populates_actionable_issue_but_changes_nothing_else(
        self,
    ) -> None:
        """select_tool() populates actionable_issue for an eligible
        unsupported decision, but this has zero effect on the
        outcome's own kind or on select_tool()'s own behaviour - the
        substitution into a different user-facing message string is
        entirely core/orchestrator.py's own responsibility (Phase 101,
        Batch 2), proven separately in
        test_phase101_batch2_live_actionable_guidance_integration.py."""
        provider = _FakeAIProvider(
            json.dumps({"decision": "unsupported", "capability_id": None, "arguments": {}})
        )
        router = AIRouter(
            provider=provider,
            prompt_builder=PromptBuilder(),
            validator=ResponseValidator(),
            logger=_RecordingLogger(),  # type: ignore[arg-type]
            settings=_settings(),
        )
        from tools.registry import ToolRegistry
        from security.security_manager import SecurityManager

        outcome = select_tool(
            request_text="enable schedule",
            assembled_context=_empty_context(),
            router=router,
            tool_registry=ToolRegistry(),
            security_manager=SecurityManager(),
        )
        assert outcome.kind is PlanningOutcomeKind.UNSUPPORTED
        assert outcome.actionable_issue is not None
        assert outcome.actionable_issue.capability_id is CapabilityId.SCHEDULE_ENABLE

    def test_orchestrator_reference_confined_to_the_three_named_branches(self) -> None:
        """Phase 101, Batch 2 activated exactly one legitimate live
        consumer of this module: core/orchestrator.py's own
        INVALID_OUTPUT/UNSUPPORTED/UNGROUNDED_SELECTION message
        construction. Proves the reference is confined there - never
        spread into approval, execution, workflow, or recovery code -
        the same confinement-not-absence convention already
        established for Phase 98/99/100's own live activations."""
        source = (_REPO_ROOT / "core/orchestrator.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions_referencing: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                segment = ast.get_source_segment(source, node) or ""
                if "actionable_issue" in segment or "actionable_decision_issue" in segment:
                    functions_referencing.add(node.name)
        assert functions_referencing == {"_handle_ask_jarvis_to_request"}

    def test_prompt_studio_does_not_reference_actionable_issue(self) -> None:
        source = (_REPO_ROOT / "ai/prompt_studio.py").read_text(encoding="utf-8")
        assert "actionable_decision_issue" not in source

    def test_command_router_does_not_reference_actionable_issue(self) -> None:
        source = (_REPO_ROOT / "core/command_router.py").read_text(encoding="utf-8")
        assert "actionable_decision_issue" not in source

    def test_no_module_imports_verified_action_context_transitively(self) -> None:
        source = (_REPO_ROOT / "intelligence/actionable_decision_issue.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
        assert "intelligence.verified_action_context" not in imported_modules
        assert "intelligence.context" not in imported_modules

    def test_ground_decision_signature_unchanged(self) -> None:
        import inspect

        from intelligence.grounding import ground_decision

        params = list(inspect.signature(ground_decision).parameters)
        assert params == ["request_text", "capability_id", "arguments"]

    def test_no_second_ai_call_reference(self) -> None:
        source = (_REPO_ROOT / "intelligence/actionable_decision_issue.py").read_text(
            encoding="utf-8"
        )
        assert "AIRouter" not in source
        assert "route(" not in source
        assert ".generate(" not in source

    def test_no_persistence_reference(self) -> None:
        source = (_REPO_ROOT / "intelligence/actionable_decision_issue.py").read_text(
            encoding="utf-8"
        )
        for leaky in ("session_scope", "sessionmaker", "storage.models", "Store("):
            assert leaky not in source


# --------------------------------------------------------------------------
# Regression: existing outcomes for non-eligible cases remain unchanged
# --------------------------------------------------------------------------


class TestRegressionNonEligibleOutcomesUnchanged:
    def test_ungrounded_selection_detail_still_the_raw_reason_value(self) -> None:
        outcome = PlanningOutcome(
            kind=PlanningOutcomeKind.UNGROUNDED_SELECTION,
            detail=UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST.value,
        )
        assert outcome.detail == "negated_or_conflicting_request"
        assert outcome.actionable_issue is None

    def test_argument_value_mismatch_never_produces_an_issue(self) -> None:
        issue = classify_actionable_issue_from_ungrounded_selection(
            capability_id=CapabilityId.SCHEDULE_ENABLE,
            reason=UngroundedReason.ARGUMENT_VALUE_MISMATCH,
        )
        assert issue is None

    def test_no_signature_matched_never_produces_an_issue(self) -> None:
        issue = classify_actionable_issue_from_ungrounded_selection(
            capability_id=CapabilityId.SCHEDULE_ENABLE,
            reason=UngroundedReason.NO_SIGNATURE_MATCHED,
        )
        assert issue is None

    def test_selected_capability_not_unique_match_never_produces_an_issue(self) -> None:
        issue = classify_actionable_issue_from_ungrounded_selection(
            capability_id=CapabilityId.SCHEDULE_ENABLE,
            reason=UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH,
        )
        assert issue is None
