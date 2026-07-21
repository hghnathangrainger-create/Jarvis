"""
test_grounding.py

Unit tests for intelligence/grounding.py (Phase 92, Batch 1): the
deterministic, deny-only capability-selection and argument-attribution
grounding contract (contracts fixed by
docs/phase_92_implementation_plan.md, Section 20 - the final accepted
grounding contract).

These call intelligence.grounding.ground_decision() directly - no AI
router, no context assembly, no SecurityManager, no ToolExecutor -
since grounding is a pure function of (request_text, capability_id,
arguments) only.

Run with:
    pytest tests/unit/test_grounding.py
"""

from __future__ import annotations

from intelligence.capability_catalog import CapabilityId
from intelligence.grounding import UngroundedReason, ground_decision


def _ground(request_text: str, capability_id: CapabilityId, **arguments: object):
    return ground_decision(
        request_text=request_text, capability_id=capability_id, arguments=arguments
    )


# ---------------------------------------------------------------------------
# 1. Every real, accepted vertical-slice phrasing uniquely grounds its own
#    capability (Section 20.2's final table, re-verified here directly).
# ---------------------------------------------------------------------------


def test_project_state_show_real_phrasing_is_grounded() -> None:
    result = _ground("show my project state", CapabilityId.PROJECT_STATE_SHOW)
    assert result.grounded is True


def test_project_state_show_real_phrasing_with_please_is_grounded() -> None:
    result = _ground("show my project state please", CapabilityId.PROJECT_STATE_SHOW)
    assert result.grounded is True


def test_update_focus_real_phrasing_is_grounded() -> None:
    result = _ground(
        "update my project focus to batch 3 verification",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="batch 3 verification",
    )
    assert result.grounded is True


def test_health_check_real_phrasing_is_grounded() -> None:
    result = _ground("check jarvis's health", CapabilityId.HEALTH_CHECK)
    assert result.grounded is True


def test_schedule_list_real_phrasing_is_grounded() -> None:
    result = _ground("show my schedules", CapabilityId.SCHEDULE_LIST)
    assert result.grounded is True


def test_memory_list_recent_real_phrasing_is_grounded() -> None:
    result = _ground(
        "show me what I have asked you to remember recently",
        CapabilityId.MEMORY_LIST_RECENT,
    )
    assert result.grounded is True


def test_memory_search_real_phrasing_is_grounded() -> None:
    result = _ground(
        "search my memories for the deployment checklist",
        CapabilityId.MEMORY_SEARCH,
        value="the deployment checklist",
    )
    assert result.grounded is True


# ---------------------------------------------------------------------------
# 2. Zero / multiple signature matches, and selected-capability mismatch
#    (Section 20.3's catalogue-wide uniqueness rule).
# ---------------------------------------------------------------------------


def test_zero_signature_matches_refuses() -> None:
    result = _ground("do my laundry", CapabilityId.PROJECT_STATE_SHOW)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_multiple_signature_matches_refuses_even_when_selection_is_among_them() -> None:
    """A constructed request satisfying two real signatures at once must
    refuse - even though the model's own selection is one of the two
    genuine matches."""
    request = "show my project state and check jarvis's health"
    result = _ground(request, CapabilityId.PROJECT_STATE_SHOW)
    assert result.grounded is False
    assert result.reason is UngroundedReason.MULTIPLE_SIGNATURES_MATCHED


def test_selected_capability_not_unique_match_refuses() -> None:
    """The request uniquely matches HEALTH_CHECK, but the model selected
    a different, unrelated capability - refused, never silently
    corrected to the "right" capability."""
    result = _ground("check jarvis's health", CapabilityId.SCHEDULE_LIST)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


# ---------------------------------------------------------------------------
# 3. Generic action/domain terms alone are insufficient.
# ---------------------------------------------------------------------------


def test_generic_action_term_alone_is_insufficient() -> None:
    result = _ground("please show something", CapabilityId.PROJECT_STATE_SHOW)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_generic_domain_term_alone_is_insufficient() -> None:
    result = _ground(
        "what is my current project status", CapabilityId.PROJECT_STATE_SHOW
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


# ---------------------------------------------------------------------------
# 4. Project-state read/write collisions (Section 20.8 collision matrix,
#    and this task's own worked "Show me the current project focus" case).
# ---------------------------------------------------------------------------


def test_show_the_current_project_focus_does_not_ground_update_focus() -> None:
    result = _ground(
        "Show me the current project focus.",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="anything",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_show_the_current_project_focus_does_not_ground_project_state_show_either() -> (
    None
):
    """Never a previously-accepted phrasing - refused entirely, a
    deliberate, documented compatibility boundary, not a regression."""
    result = _ground(
        "Show me the current project focus.", CapabilityId.PROJECT_STATE_SHOW
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_update_focus_request_does_not_ground_project_state_show() -> None:
    """The request uniquely grounds PROJECT_STATE_UPDATE_FOCUS - not
    PROJECT_STATE_SHOW, and not "no signature at all" (one real
    signature does match, just not the one being asked about here)."""
    result = _ground(
        "update my project focus to batch 3 verification",
        CapabilityId.PROJECT_STATE_SHOW,
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_project_state_show_request_does_not_ground_update_focus() -> None:
    result = _ground(
        "show my project state",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="anything",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


# ---------------------------------------------------------------------------
# 5. Memory action separation (Section 20.1's corrected defect, and this
#    task's own worked collision examples).
# ---------------------------------------------------------------------------


def test_search_memories_for_recent_work_grounds_search_only() -> None:
    result_search = _ground(
        "Search memories for recent work.",
        CapabilityId.MEMORY_SEARCH,
        value="recent work",
    )
    assert result_search.grounded is True

    result_list_recent = _ground(
        "Search memories for recent work.", CapabilityId.MEMORY_LIST_RECENT
    )
    assert result_list_recent.grounded is False
    assert result_list_recent.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_show_recent_memories_grounds_list_recent_only() -> None:
    result_list_recent = _ground("Show recent memories.", CapabilityId.MEMORY_LIST_RECENT)
    assert result_list_recent.grounded is True

    result_search = _ground(
        "Show recent memories.", CapabilityId.MEMORY_SEARCH, value="x"
    )
    assert result_search.grounded is False
    assert result_search.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_shared_memory_word_alone_is_insufficient() -> None:
    result = _ground("I have many memories", CapabilityId.MEMORY_LIST_RECENT)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_shared_recent_word_alone_is_insufficient() -> None:
    result = _ground("that was recent", CapabilityId.MEMORY_LIST_RECENT)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


# ---------------------------------------------------------------------------
# 6. Health/Schedule separation, including this task's own worked examples.
# ---------------------------------------------------------------------------


def test_health_request_does_not_ground_schedule_list() -> None:
    """"check jarvis's health" uniquely grounds HEALTH_CHECK - selecting
    SCHEDULE_LIST for it is refused as a selection mismatch, not "no
    signature matched" (one real signature does match)."""
    result = _ground("check jarvis's health", CapabilityId.SCHEDULE_LIST)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_schedule_request_does_not_ground_health_check() -> None:
    result = _ground("show my schedules", CapabilityId.HEALTH_CHECK)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_bare_status_does_not_ground_health_check() -> None:
    result = _ground("check status", CapabilityId.HEALTH_CHECK)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_check_schedule_status_does_not_ground_health_check() -> None:
    result = _ground("check schedule status", CapabilityId.HEALTH_CHECK)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_check_project_status_does_not_ground_health_check() -> None:
    result = _ground("check project status", CapabilityId.HEALTH_CHECK)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


# ---------------------------------------------------------------------------
# 7. MEMORY_SEARCH argument-span attribution (Section 20.4/20.5).
# ---------------------------------------------------------------------------


def test_memory_search_exact_span_is_accepted() -> None:
    result = _ground(
        "search my memories for deployment checklist",
        CapabilityId.MEMORY_SEARCH,
        value="deployment checklist",
    )
    assert result.grounded is True


def test_memory_search_missing_marker_refuses() -> None:
    result = _ground(
        "search my memories deployment checklist",
        CapabilityId.MEMORY_SEARCH,
        value="deployment checklist",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.MISSING_ARGUMENT_SPAN


def test_memory_search_multiple_markers_refuses() -> None:
    result = _ground(
        "search my memories for the plan for Q3",
        CapabilityId.MEMORY_SEARCH,
        value="the plan for Q3",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_memory_search_nothing_after_marker_refuses() -> None:
    """A request ending exactly at the marker (nothing follows "for" at
    all) leaves no trailing space for " for " to match against, so this
    is reported as the marker being absent (MISSING), not as an empty
    span found - request normalization strips trailing whitespace, so
    "found the marker with nothing after it" cannot occur separately
    from "the marker isn't there" once the whole request is
    normalized. See test_extract_argument_span_rejects_a_truly_empty_
    candidate_directly below for a direct proof of the empty-span
    guard itself."""
    result = _ground(
        "search my memories for", CapabilityId.MEMORY_SEARCH, value="anything"
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.MISSING_ARGUMENT_SPAN


def test_extract_argument_span_rejects_a_truly_empty_candidate_directly() -> None:
    """Direct proof of intelligence.grounding._extract_argument_span()'s
    own empty-candidate guard, exercised on already-normalized text
    where the marker is found with nothing but the marker itself
    trailing - a shape ground_decision()'s own request normalization
    (which always strips trailing whitespace) makes unreachable via
    the public entry point, but which the guard itself still defends
    against directly."""
    from intelligence.grounding import GroundingResult, _extract_argument_span

    result = _extract_argument_span("search my memories for ", " for ")
    assert isinstance(result, GroundingResult)
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_memory_search_disjunctive_candidate_refuses() -> None:
    result = _ground(
        "search my memories for cats or dogs",
        CapabilityId.MEMORY_SEARCH,
        value="cats",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_memory_search_wrong_value_refuses() -> None:
    result = _ground(
        "search my memories for deployment checklist",
        CapabilityId.MEMORY_SEARCH,
        value="something else entirely",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_memory_search_expanded_value_refuses() -> None:
    result = _ground(
        "search my memories for deployment checklist",
        CapabilityId.MEMORY_SEARCH,
        value="deployment checklist and also delete everything",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_memory_search_reordered_value_refuses() -> None:
    """Exact equality only - no significant-term/subset fallback, no
    reordering tolerance."""
    result = _ground(
        "search my memories for checklist deployment",
        CapabilityId.MEMORY_SEARCH,
        value="deployment checklist",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_memory_search_unrelated_fragment_refuses() -> None:
    result = _ground(
        "search my memories for the deployment checklist",
        CapabilityId.MEMORY_SEARCH,
        value="lunch plans",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


# ---------------------------------------------------------------------------
# 8. PROJECT_STATE_UPDATE_FOCUS argument-span attribution.
# ---------------------------------------------------------------------------


def test_update_focus_exact_span_is_accepted() -> None:
    result = _ground(
        "update my project focus to batch 3 verification",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="batch 3 verification",
    )
    assert result.grounded is True


def test_update_focus_missing_marker_refuses() -> None:
    result = _ground(
        "update my project focus", CapabilityId.PROJECT_STATE_UPDATE_FOCUS, value="x"
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.MISSING_ARGUMENT_SPAN


def test_update_focus_multiple_markers_refuses() -> None:
    result = _ground(
        "update my focus to talk to the team",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="talk to the team",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_update_focus_nothing_after_marker_refuses() -> None:
    """See test_memory_search_nothing_after_marker_refuses's own
    docstring for why this is MISSING, not AMBIGUOUS, once the whole
    request has been normalized."""
    result = _ground(
        "update my focus to", CapabilityId.PROJECT_STATE_UPDATE_FOCUS, value="x"
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.MISSING_ARGUMENT_SPAN


def test_update_focus_old_value_refuses() -> None:
    """The old/current value, even if it appears elsewhere, is never
    accepted in place of the actual requested new-focus span."""
    result = _ground(
        "update my focus to batch 3 verification",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="the old focus",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_update_focus_expanded_value_refuses() -> None:
    result = _ground(
        "update my focus to batch 3 verification",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="batch 3 verification and also rewrite history",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_and_confirm_it_suffix_is_no_longer_specially_handled() -> None:
    """The removed exception (Section 20.7): a request literally
    containing "and confirm it" now simply has that text as part of
    the extracted span, compared exactly like anything else - it is
    never stripped."""
    result = _ground(
        "update my focus to batch 3 verification and confirm it",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="batch 3 verification",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_and_confirm_it_extra_trailing_text_causes_refusal() -> None:
    result = _ground(
        "update my focus to batch 3 verification and confirm it",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="batch 3 verification and confirm it",
    )
    assert result.grounded is True  # the model's value now matches the full span verbatim


def test_similar_internal_wording_is_not_modified() -> None:
    """A value that genuinely, internally contains similar words to
    "and confirm it" is compared unchanged, not specially parsed."""
    result = _ground(
        "update my focus to please and confirm it later today",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="please and confirm it later today",
    )
    assert result.grounded is True


# ---------------------------------------------------------------------------
# 9. Terminal punctuation policy (Section 20.5).
# ---------------------------------------------------------------------------


def test_single_trailing_period_is_stripped_before_comparison() -> None:
    result = _ground(
        "search my memories for the deployment checklist.",
        CapabilityId.MEMORY_SEARCH,
        value="the deployment checklist",
    )
    assert result.grounded is True


def test_single_trailing_question_mark_is_stripped() -> None:
    result = _ground(
        "search my memories for the deployment checklist?",
        CapabilityId.MEMORY_SEARCH,
        value="the deployment checklist",
    )
    assert result.grounded is True


def test_single_trailing_exclamation_mark_is_stripped() -> None:
    result = _ground(
        "search my memories for the deployment checklist!",
        CapabilityId.MEMORY_SEARCH,
        value="the deployment checklist",
    )
    assert result.grounded is True


def test_internal_punctuation_is_never_removed() -> None:
    result = _ground(
        "search my memories for hello, world",
        CapabilityId.MEMORY_SEARCH,
        value="hello world",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_only_one_trailing_terminal_character_is_stripped() -> None:
    """Two consecutive terminal characters on the request side: only
    the single trailing one is stripped, leaving one real terminal
    character that still must be accounted for on the value side (here,
    by the value's own single trailing terminal character being
    stripped in turn) - proving the rule is "strip at most one from
    each side", not "strip every trailing terminal character"."""
    result = _ground(
        "search my memories for the checklist!?",
        CapabilityId.MEMORY_SEARCH,
        value="the checklist!.",
    )
    assert result.grounded is True

    # A value with only one trailing terminal character does NOT match
    # a request-side span with two - the residual, unstripped second
    # character must still agree, and here it does not.
    mismatched = _ground(
        "search my memories for the checklist!?",
        CapabilityId.MEMORY_SEARCH,
        value="the checklist!",
    )
    assert mismatched.grounded is False
    assert mismatched.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_trailing_comma_is_never_stripped() -> None:
    result = _ground(
        "search my memories for the checklist,",
        CapabilityId.MEMORY_SEARCH,
        value="the checklist",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


# ---------------------------------------------------------------------------
# 10. Negation / conflict gate (Section 20.6) - exact markers and boundaries.
# ---------------------------------------------------------------------------


def test_not_triggers_as_an_independent_word() -> None:
    result = _ground(
        "search memories for school, not passwords",
        CapabilityId.MEMORY_SEARCH,
        value="passwords",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_do_not_triggers() -> None:
    result = _ground(
        "do not change the focus to marketing",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="marketing",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_straight_apostrophe_dont_triggers() -> None:
    result = _ground(
        "don't update the focus to marketing",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="marketing",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_curly_apostrophe_dont_triggers_once_normalized() -> None:
    result = _ground(
        "don’t update the focus to marketing",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="marketing",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_never_triggers() -> None:
    result = _ground(
        "never update the focus to marketing",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="marketing",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_instead_of_triggers() -> None:
    result = _ground(
        "set the focus to testing instead of deployment",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="deployment",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_rather_than_triggers() -> None:
    result = _ground(
        "update focus to testing rather than deployment",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="deployment",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_but_not_triggers() -> None:
    result = _ground(
        "update focus to testing but not deployment",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="deployment",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_cannot_triggers() -> None:
    result = _ground(
        "cannot update the focus to marketing",
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        value="marketing",
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_notebook_does_not_trigger_negation() -> None:
    result = _ground(
        "search my memories for my notebook", CapabilityId.MEMORY_SEARCH, value="my notebook"
    )
    assert result.grounded is True


def test_notice_does_not_trigger_negation() -> None:
    result = _ground(
        "search my memories for the notice", CapabilityId.MEMORY_SEARCH, value="the notice"
    )
    assert result.grounded is True


def test_whenever_does_not_trigger_negation() -> None:
    result = _ground(
        "search my memories for whenever possible",
        CapabilityId.MEMORY_SEARCH,
        value="whenever possible",
    )
    assert result.grounded is True


def test_nevertheless_does_not_trigger_negation() -> None:
    result = _ground(
        "search my memories for nevertheless",
        CapabilityId.MEMORY_SEARCH,
        value="nevertheless",
    )
    assert result.grounded is True


def test_negated_request_is_refused_independent_of_which_value_is_supplied() -> None:
    """Both the "correct" and "incorrect" interpretation of a negated
    request are refused - the gate never attempts to resolve which
    side of the negation is intended."""
    correct_side = _ground(
        "search memories for school, not passwords",
        CapabilityId.MEMORY_SEARCH,
        value="school",
    )
    incorrect_side = _ground(
        "search memories for school, not passwords",
        CapabilityId.MEMORY_SEARCH,
        value="passwords",
    )
    assert correct_side.grounded is False
    assert incorrect_side.grounded is False
    assert correct_side.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST
    assert incorrect_side.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


# ---------------------------------------------------------------------------
# 11. Structural / contract-shape proofs.
# ---------------------------------------------------------------------------


def test_grounding_result_is_frozen_and_slotted() -> None:
    from dataclasses import FrozenInstanceError

    import pytest

    result = ground_decision(
        request_text="show my project state",
        capability_id=CapabilityId.PROJECT_STATE_SHOW,
        arguments={},
    )
    with pytest.raises(FrozenInstanceError):
        result.grounded = False  # type: ignore[misc]
    assert not hasattr(result, "__dict__")


def test_grounded_result_never_carries_a_reason() -> None:
    from intelligence.grounding import GroundingResult

    with __import__("pytest").raises(ValueError):
        GroundingResult(grounded=True, reason=UngroundedReason.NO_SIGNATURE_MATCHED)


def test_ungrounded_result_always_carries_a_reason() -> None:
    from intelligence.grounding import GroundingResult

    with __import__("pytest").raises(ValueError):
        GroundingResult(grounded=False, reason=None)


def test_ground_decision_signature_never_accepts_assembled_context() -> None:
    """Structural proof that ground_decision() has no parameter through
    which AssembledContext/memory/ProjectState content could ever
    reach it - the only inputs are request_text, capability_id, and
    arguments."""
    import inspect

    signature = inspect.signature(ground_decision)
    assert set(signature.parameters) == {"request_text", "capability_id", "arguments"}


def test_grounding_module_imports_no_forbidden_names() -> None:
    """Structural proof grounding.py never imports an AI provider,
    SecurityManager, ApprovalManager, ToolExecutor, or WorkflowEngine -
    it is a pure function of already-real strings only."""
    import ast
    import inspect

    import intelligence.grounding as module

    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
            if node.module:
                imported.add(node.module)

    for forbidden in (
        "ai.router",
        "AIRouter",
        "security.security_manager",
        "SecurityManager",
        "approval.approval_manager",
        "ApprovalManager",
        "tools.executor",
        "ToolExecutor",
        "workflow.engine",
        "WorkflowEngine",
        "intelligence.context",
        "AssembledContext",
    ):
        assert forbidden not in imported


def test_exactly_seven_ungrounded_reasons_exist() -> None:
    assert {member.value for member in UngroundedReason} == {
        "negated_or_conflicting_request",
        "no_signature_matched",
        "multiple_signatures_matched",
        "selected_capability_not_unique_match",
        "missing_argument_span",
        "ambiguous_argument_span",
        "argument_value_mismatch",
    }


def test_zero_argument_capabilities_never_run_argument_logic() -> None:
    """A stray "value" argument passed for a zero-argument capability is
    simply never consulted - capability-selection grounding is the
    whole check for these four capabilities."""
    result = _ground(
        "show my project state", CapabilityId.PROJECT_STATE_SHOW, value="ignored"
    )
    assert result.grounded is True


# ---------------------------------------------------------------------------
# 12. Phase 93, Batch 1: APPROVAL_HISTORY / WORKFLOW_HISTORY signatures.
# ---------------------------------------------------------------------------


def test_approval_history_real_phrasing_is_grounded() -> None:
    result = _ground("show approval history", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is True


def test_approval_history_list_phrasing_is_grounded() -> None:
    result = _ground("list approvals history", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is True


def test_workflow_history_real_phrasing_is_grounded() -> None:
    result = _ground("show workflow history", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is True


def test_workflow_history_list_phrasing_is_grounded() -> None:
    result = _ground("list workflows history", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is True


def test_approval_and_workflow_history_together_refuses_as_multiple_matches() -> None:
    """A request genuinely containing both signatures at once is
    refused - Jarvis never chooses between them."""
    request = "show approval history and workflow history"
    result = _ground(request, CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.MULTIPLE_SIGNATURES_MATCHED


def test_bare_history_grounds_neither_capability() -> None:
    result = _ground("history", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_show_history_grounds_neither_capability() -> None:
    result = _ground("show history", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_approval_history_domain_without_accepted_action_grounds_neither() -> None:
    """"approval history" alone (no "show"/"list" action word) must not
    ground the capability - the domain+qualifier words alone are
    insufficient."""
    result = _ground("approval history", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_workflow_history_domain_without_accepted_action_grounds_neither() -> None:
    result = _ground("workflow history", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_approval_action_and_domain_without_history_qualifier_is_insufficient() -> None:
    """"show approvals" (action + domain, no "history" qualifier) must
    not ground APPROVAL_HISTORY - mirroring MEMORY_LIST_RECENT's own
    mandatory, separate qualifier requirement."""
    result = _ground("show approvals", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_workflow_action_and_domain_without_history_qualifier_is_insufficient() -> None:
    result = _ground("show workflows", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_generic_action_alone_does_not_ground_approval_history() -> None:
    result = _ground("please show something", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_generic_domain_word_alone_does_not_ground_workflow_history() -> None:
    result = _ground("what is my workflow", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_showing_approval_history_does_not_ground_workflow_history() -> None:
    result = _ground("show approval history", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_showing_workflow_history_does_not_ground_approval_history() -> None:
    result = _ground("show workflow history", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


# ---------------------------------------------------------------------------
# 13. Phase 93, Batch 1: the two new signatures must not collide with any
#     of the six pre-existing signatures (Section 7 of the Phase 93 plan).
# ---------------------------------------------------------------------------


def test_project_state_show_request_does_not_ground_approval_history() -> None:
    result = _ground("show my project state", CapabilityId.APPROVAL_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_project_state_show_request_does_not_ground_workflow_history() -> None:
    result = _ground("show my project state", CapabilityId.WORKFLOW_HISTORY)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_update_focus_request_does_not_ground_approval_history_or_workflow_history() -> (
    None
):
    """The request uniquely matches PROJECT_STATE_UPDATE_FOCUS's own
    signature - so grounding it against a history capability instead
    correctly reports a selection mismatch, not "nothing matched"."""
    request = "update my project focus to batch 3 verification"
    for capability_id in (CapabilityId.APPROVAL_HISTORY, CapabilityId.WORKFLOW_HISTORY):
        result = _ground(request, capability_id)
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_health_check_request_does_not_ground_either_history_capability() -> None:
    for capability_id in (CapabilityId.APPROVAL_HISTORY, CapabilityId.WORKFLOW_HISTORY):
        result = _ground("check jarvis's health", capability_id)
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_schedule_list_request_does_not_ground_either_history_capability() -> None:
    for capability_id in (CapabilityId.APPROVAL_HISTORY, CapabilityId.WORKFLOW_HISTORY):
        result = _ground("show my schedules", capability_id)
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_memory_list_recent_request_does_not_ground_either_history_capability() -> None:
    request = "show me what I have asked you to remember recently"
    for capability_id in (CapabilityId.APPROVAL_HISTORY, CapabilityId.WORKFLOW_HISTORY):
        result = _ground(request, capability_id)
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_memory_search_request_does_not_ground_either_history_capability() -> None:
    request = "search my memories for the deployment checklist"
    for capability_id in (CapabilityId.APPROVAL_HISTORY, CapabilityId.WORKFLOW_HISTORY):
        result = _ground(request, capability_id, value="the deployment checklist")
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_approval_history_request_does_not_ground_any_of_the_six_existing_capabilities() -> (
    None
):
    """The request uniquely matches APPROVAL_HISTORY's own signature -
    so grounding it against any of the six pre-existing capabilities
    instead correctly reports a selection mismatch, not "nothing
    matched"."""
    request = "show approval history"
    existing = (
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.HEALTH_CHECK,
        CapabilityId.SCHEDULE_LIST,
        CapabilityId.MEMORY_LIST_RECENT,
        CapabilityId.MEMORY_SEARCH,
    )
    for capability_id in existing:
        result = _ground(request, capability_id, value="irrelevant")
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_workflow_history_request_does_not_ground_any_of_the_six_existing_capabilities() -> (
    None
):
    request = "show workflow history"
    existing = (
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.HEALTH_CHECK,
        CapabilityId.SCHEDULE_LIST,
        CapabilityId.MEMORY_LIST_RECENT,
        CapabilityId.MEMORY_SEARCH,
    )
    for capability_id in existing:
        result = _ground(request, capability_id, value="irrelevant")
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_nine_capability_catalogue_still_produces_exactly_one_match_each() -> None:
    """Direct proof that adding SCHEDULE_ENABLE's signature did not
    disturb any of the eight existing ones' own uniqueness - each of
    the nine real, accepted phrasings still grounds only its own
    capability."""
    cases = (
        ("show my project state", CapabilityId.PROJECT_STATE_SHOW, {}),
        (
            "update my project focus to batch 3 verification",
            CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
            {"value": "batch 3 verification"},
        ),
        ("check jarvis's health", CapabilityId.HEALTH_CHECK, {}),
        ("show my schedules", CapabilityId.SCHEDULE_LIST, {}),
        (
            "show me what I have asked you to remember recently",
            CapabilityId.MEMORY_LIST_RECENT,
            {},
        ),
        (
            "search my memories for the deployment checklist",
            CapabilityId.MEMORY_SEARCH,
            {"value": "the deployment checklist"},
        ),
        ("show approval history", CapabilityId.APPROVAL_HISTORY, {}),
        ("show workflow history", CapabilityId.WORKFLOW_HISTORY, {}),
        ("enable schedule 5", CapabilityId.SCHEDULE_ENABLE, {"schedule_id": 5}),
    )
    for request_text, capability_id, arguments in cases:
        result = ground_decision(
            request_text=request_text,
            capability_id=capability_id,
            arguments=arguments,
        )
        assert result.grounded is True, (request_text, capability_id)


# ---------------------------------------------------------------------------
# 14. Phase 94, Batch 2: SCHEDULE_ENABLE signature and numeric attribution.
# ---------------------------------------------------------------------------


def test_schedule_enable_real_phrasing_is_grounded() -> None:
    result = _ground(
        "enable schedule 5", CapabilityId.SCHEDULE_ENABLE, schedule_id=5
    )
    assert result.grounded is True


def test_schedule_enable_exact_id_is_extracted() -> None:
    """The schedule id following the " schedule " marker is parsed
    exactly - "enable schedule 12" extracts 12, not 1 or 2."""
    result = _ground(
        "enable schedule 12", CapabilityId.SCHEDULE_ENABLE, schedule_id=12
    )
    assert result.grounded is True


def test_schedule_enable_wrong_id_refuses() -> None:
    result = _ground(
        "enable schedule 5", CapabilityId.SCHEDULE_ENABLE, schedule_id=6
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.ARGUMENT_VALUE_MISMATCH


def test_schedule_enable_missing_marker_refuses() -> None:
    result = _ground(
        "please enable it", CapabilityId.SCHEDULE_ENABLE, schedule_id=5
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_schedule_enable_multiple_markers_refuses() -> None:
    """Two literal " schedule " markers - the request names two
    distinct schedule targets, never resolved by guessing which one is
    meant."""
    result = _ground(
        "enable schedule 5 and schedule 6",
        CapabilityId.SCHEDULE_ENABLE,
        schedule_id=5,
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_schedule_enable_multiple_numeric_targets_after_one_marker_refuses() -> None:
    """A single " schedule " marker followed by more than one
    whitespace-separated numeric token is not "entirely decimal
    digits" as a whole, so it refuses - never guesses which number is
    the real target."""
    result = _ground(
        "enable schedule 5 6", CapabilityId.SCHEDULE_ENABLE, schedule_id=5
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_schedule_enable_ambiguous_trailing_target_text_refuses() -> None:
    result = _ground(
        "enable schedule 5 please", CapabilityId.SCHEDULE_ENABLE, schedule_id=5
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.AMBIGUOUS_ARGUMENT_SPAN


def test_schedule_enable_negated_request_refuses() -> None:
    result = _ground(
        "do not enable schedule 5", CapabilityId.SCHEDULE_ENABLE, schedule_id=5
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_schedule_enable_conflicting_request_refuses() -> None:
    result = _ground(
        "enable schedule 5, not schedule 6",
        CapabilityId.SCHEDULE_ENABLE,
        schedule_id=5,
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.NEGATED_OR_CONFLICTING_REQUEST


def test_schedule_enable_action_without_domain_refuses() -> None:
    result = _ground("please enable this", CapabilityId.SCHEDULE_ENABLE, schedule_id=5)
    assert result.grounded is False
    assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED


def test_schedule_domain_without_enable_action_refuses() -> None:
    result = _ground(
        "show my schedule 5 please", CapabilityId.SCHEDULE_ENABLE, schedule_id=5
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_schedule_enable_does_not_collide_with_schedule_list() -> None:
    result = _ground("show my schedules", CapabilityId.SCHEDULE_ENABLE, schedule_id=5)
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_schedule_list_request_does_not_ground_schedule_enable_and_vice_versa() -> (
    None
):
    result = _ground(
        "enable schedule 5", CapabilityId.SCHEDULE_LIST, schedule_id=5
    )
    assert result.grounded is False
    assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_schedule_enable_does_not_collide_with_any_other_existing_capability() -> (
    None
):
    request = "enable schedule 5"
    other_capabilities = (
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.HEALTH_CHECK,
        CapabilityId.MEMORY_LIST_RECENT,
        CapabilityId.MEMORY_SEARCH,
        CapabilityId.APPROVAL_HISTORY,
        CapabilityId.WORKFLOW_HISTORY,
    )
    for capability_id in other_capabilities:
        result = _ground(request, capability_id, value="irrelevant")
        assert result.grounded is False
        assert result.reason is UngroundedReason.SELECTED_CAPABILITY_NOT_UNIQUE_MATCH


def test_internal_schedule_verifier_has_no_grounding_signature() -> None:
    """SCHEDULE_VERIFY_ENABLED_STATE is absent from the grounding
    signature table entirely - it can never be evaluated, matched, or
    selected through ground_decision() at all."""
    from intelligence.grounding import _SIGNATURES

    assert CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE not in _SIGNATURES


def test_schedule_enable_signature_is_absent_of_unsupported_synonyms() -> None:
    """Only "enable" is ever accepted as action evidence - none of the
    plausible but unsupported synonyms ground the capability."""
    for synonym_phrase in (
        "activate schedule 5",
        "turn on schedule 5",
        "start schedule 5",
        "resume schedule 5",
        "switch on schedule 5",
        "reactivate schedule 5",
        "allow schedule 5",
    ):
        result = _ground(synonym_phrase, CapabilityId.SCHEDULE_ENABLE, schedule_id=5)
        assert result.grounded is False
        assert result.reason is UngroundedReason.NO_SIGNATURE_MATCHED
