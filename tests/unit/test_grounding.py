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
