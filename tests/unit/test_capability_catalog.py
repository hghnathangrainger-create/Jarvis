"""
test_capability_catalog.py

Unit tests for intelligence/capability_catalog.py (Phase 90, Batches
2/3): the hand-maintained tool-selection allowlist for "ask jarvis to:
<request>".

Run with:
    pytest tests/unit/test_capability_catalog.py
"""

from __future__ import annotations

import dataclasses

import pytest

from config.constants import SecurityTier
from intelligence.capability_catalog import (
    CAPABILITY_CATALOG,
    CapabilityAdapter,
    CapabilityArgumentSpec,
    CapabilityId,
    ExecutionStrategy,
    build_tool_input,
    fixed_arguments_for,
    get_adapter,
)


def test_catalog_contains_exactly_the_fourteen_phase_99_batch1_entries() -> None:
    assert set(CAPABILITY_CATALOG) == {
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
        CapabilityId.HEALTH_CHECK,
        CapabilityId.SCHEDULE_LIST,
        CapabilityId.MEMORY_LIST_RECENT,
        CapabilityId.MEMORY_SEARCH,
        CapabilityId.APPROVAL_HISTORY,
        CapabilityId.WORKFLOW_HISTORY,
        CapabilityId.SCHEDULE_ENABLE,
        CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE,
        CapabilityId.SCHEDULE_DISABLE,
        CapabilityId.PROJECT_STATE_UPDATE_PHASE,
        CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
    }


def test_no_other_capability_id_exists() -> None:
    assert {member.value for member in CapabilityId} == {
        "project_state_show",
        "project_state_update_focus",
        "project_state_verify_focus",
        "health_check",
        "schedule_list",
        "memory_list_recent",
        "memory_search",
        "approval_history",
        "workflow_history",
        "schedule_enable",
        "schedule_verify_enabled_state",
        "schedule_disable",
        "project_state_update_phase",
        "schedule_show_enabled_state",
    }


def test_update_focus_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    assert adapter.capability_id is CapabilityId.PROJECT_STATE_UPDATE_FOCUS
    assert adapter.tool_name == "project_state_update"
    assert [spec.name for spec in adapter.arguments] == ["value"]
    assert adapter.arguments[0].type_name == "str"
    assert adapter.arguments[0].required is True
    assert adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW
    assert adapter.max_execution_tier is SecurityTier.YELLOW
    assert adapter.verification_strategy_id == "project_state_focus_exact_match"
    assert adapter.internal_only is False


def test_verify_focus_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_VERIFY_FOCUS]
    assert adapter.capability_id is CapabilityId.PROJECT_STATE_VERIFY_FOCUS
    assert adapter.tool_name == "project_state_verify"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is True


def test_only_twelve_capabilities_are_model_selectable() -> None:
    selectable = {
        capability_id
        for capability_id, adapter in CAPABILITY_CATALOG.items()
        if not adapter.internal_only
    }
    assert selectable == {
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.HEALTH_CHECK,
        CapabilityId.SCHEDULE_LIST,
        CapabilityId.MEMORY_LIST_RECENT,
        CapabilityId.MEMORY_SEARCH,
        CapabilityId.APPROVAL_HISTORY,
        CapabilityId.WORKFLOW_HISTORY,
        CapabilityId.SCHEDULE_ENABLE,
        CapabilityId.SCHEDULE_DISABLE,
        CapabilityId.PROJECT_STATE_UPDATE_PHASE,
        CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
    }


def test_project_state_show_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_SHOW]
    assert adapter.capability_id is CapabilityId.PROJECT_STATE_SHOW
    assert adapter.tool_name == "project_state_show"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_health_check_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.HEALTH_CHECK]
    assert adapter.capability_id is CapabilityId.HEALTH_CHECK
    assert adapter.tool_name == "health_check"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_schedule_list_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_LIST]
    assert adapter.capability_id is CapabilityId.SCHEDULE_LIST
    assert adapter.tool_name == "schedule_list"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_memory_list_recent_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_LIST_RECENT]
    assert adapter.capability_id is CapabilityId.MEMORY_LIST_RECENT
    assert adapter.tool_name == "memory"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_memory_search_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_SEARCH]
    assert adapter.capability_id is CapabilityId.MEMORY_SEARCH
    assert adapter.tool_name == "memory"
    assert [spec.name for spec in adapter.arguments] == ["value"]
    assert adapter.arguments[0].type_name == "str"
    assert adapter.arguments[0].required is True
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_approval_history_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.APPROVAL_HISTORY]
    assert adapter.capability_id is CapabilityId.APPROVAL_HISTORY
    assert adapter.tool_name == "approval_history"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_workflow_history_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.WORKFLOW_HISTORY]
    assert adapter.capability_id is CapabilityId.WORKFLOW_HISTORY
    assert adapter.tool_name == "workflow_history"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False


def test_get_adapter_returns_the_catalog_entry() -> None:
    adapter = get_adapter(CapabilityId.PROJECT_STATE_SHOW)
    assert adapter is CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_SHOW]


def test_get_adapter_returns_none_for_a_capability_id_not_in_the_catalog() -> None:
    # CAPABILITY_CATALOG is a plain dict; a lookup miss returns None
    # regardless of key type, proving get_adapter never fabricates an
    # adapter for anything not actually present.
    assert get_adapter("not_a_real_capability") is None  # type: ignore[arg-type]


def test_build_tool_input_returns_a_fresh_copy() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_SHOW]
    original: dict[str, object] = {}
    result = build_tool_input(adapter, original)
    assert result == {}
    assert result is not original


def test_build_tool_input_copies_arbitrary_arguments() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_SHOW]
    original = {"value": "x"}
    result = build_tool_input(adapter, original)
    assert result == original
    assert result is not original
    original["value"] = "mutated"
    assert result["value"] == "x"


def test_build_tool_input_adds_fixed_field_for_update_focus() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    result = build_tool_input(adapter, {"value": "new focus"})
    assert result == {"field": "focus", "value": "new focus"}


def test_build_tool_input_never_lets_model_choose_the_field() -> None:
    """The "field" key is always the fixed literal "focus" - never
    derived from, or overridable by, model-supplied arguments."""
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    result = build_tool_input(adapter, {"value": "x", "field": "branch"})
    assert result["field"] == "focus"


def test_build_tool_input_adds_no_fixed_arguments_for_health_check() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.HEALTH_CHECK]
    assert build_tool_input(adapter, {}) == {}


def test_build_tool_input_adds_no_fixed_arguments_for_schedule_list() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_LIST]
    assert build_tool_input(adapter, {}) == {}


def test_build_tool_input_adds_fixed_operation_for_memory_list_recent() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_LIST_RECENT]
    assert build_tool_input(adapter, {}) == {"operation": "list"}


def test_build_tool_input_never_lets_model_choose_the_operation() -> None:
    """The "operation" key is always the fixed literal "list" for
    memory_list_recent - never derived from, or overridable by, model-
    supplied arguments (memory_list_recent declares zero arguments, so
    this also proves a stray "operation" key smuggled through
    somehow - e.g. by a bug elsewhere - could never override it)."""
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_LIST_RECENT]
    result = build_tool_input(adapter, {"operation": "save"})
    assert result["operation"] == "list"


def test_build_tool_input_renames_value_to_query_and_fixes_operation_for_memory_search() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_SEARCH]
    result = build_tool_input(adapter, {"value": "deployment checklist"})
    assert result == {"query": "deployment checklist", "operation": "search"}


def test_build_tool_input_never_lets_model_choose_the_search_operation() -> None:
    """The "operation" key is always the fixed literal "search" for
    memory_search - never derived from, or overridable by, model-
    supplied arguments. memory_search declares only "value" as an
    argument, so a stray "operation" key could only ever reach
    build_tool_input() via a bug elsewhere in the pipeline - this proves
    even then it could never override the fixed value."""
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_SEARCH]
    result = build_tool_input(adapter, {"value": "x", "operation": "save"})
    assert result["operation"] == "search"


def test_build_tool_input_memory_search_never_leaves_a_stray_value_key() -> None:
    """The rename fully replaces "value" with "query" - the real
    MemoryTool input never carries both keys, and never carries the
    model-facing "value" key name at all."""
    adapter = CAPABILITY_CATALOG[CapabilityId.MEMORY_SEARCH]
    result = build_tool_input(adapter, {"value": "x"})
    assert "value" not in result
    assert result["query"] == "x"


def test_build_tool_input_adds_fixed_operation_for_approval_history() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.APPROVAL_HISTORY]
    assert build_tool_input(adapter, {}) == {"operation": "history"}


def test_build_tool_input_never_lets_model_choose_approval_history_operation() -> None:
    """approval_history declares zero arguments, so a stray "operation"
    key could only ever reach build_tool_input() via a bug elsewhere in
    the pipeline - this proves even then it could never override the
    fixed "history" value."""
    adapter = CAPABILITY_CATALOG[CapabilityId.APPROVAL_HISTORY]
    result = build_tool_input(adapter, {"operation": "declined"})
    assert result["operation"] == "history"


def test_build_tool_input_adds_fixed_operation_for_workflow_history() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.WORKFLOW_HISTORY]
    assert build_tool_input(adapter, {}) == {"operation": "history"}


def test_build_tool_input_never_lets_model_choose_workflow_history_operation() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.WORKFLOW_HISTORY]
    result = build_tool_input(adapter, {"operation": "get"})
    assert result["operation"] == "history"


def test_build_tool_input_rename_does_not_affect_other_capabilities() -> None:
    """The key-rename mechanism is opt-in per capability - every
    capability without an _ARGUMENT_KEY_RENAMES_BY_CAPABILITY entry
    keeps its arguments' key names completely unchanged, exactly as
    before this mechanism existed."""
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    result = build_tool_input(adapter, {"value": "new focus"})
    assert result == {"field": "focus", "value": "new focus"}


# --- Contract shape tests --------------------------------------------------


def test_capability_argument_spec_is_frozen_and_slotted() -> None:
    spec = CapabilityArgumentSpec(name="value", type_name="str", required=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.name = "changed"  # type: ignore[misc]
    assert not hasattr(spec, "__dict__")


def test_capability_adapter_is_frozen_and_slotted() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_SHOW]
    with pytest.raises(dataclasses.FrozenInstanceError):
        adapter.tool_name = "changed"  # type: ignore[misc]
    assert not hasattr(adapter, "__dict__")


def test_capability_adapter_has_exact_fields() -> None:
    field_names = {f.name for f in dataclasses.fields(CapabilityAdapter)}
    assert field_names == {
        "capability_id",
        "tool_name",
        "description",
        "arguments",
        "allowed_strategy",
        "max_execution_tier",
        "verification_strategy_id",
        "internal_only",
        "paired_verify_capability_id",
        "paired_verify_input_keys",
    }


def test_paired_verify_input_keys_defaults_to_empty_except_for_schedule_write_capabilities() -> (
    None
):
    """Every capability except SCHEDULE_ENABLE/SCHEDULE_DISABLE needs no
    data threaded from its write step into its verifier
    (PROJECT_STATE_UPDATE_FOCUS's verifier reads a singleton row and
    needs nothing) - the field defaults to an empty tuple for all of
    them."""
    schedule_write_capabilities = {
        CapabilityId.SCHEDULE_ENABLE,
        CapabilityId.SCHEDULE_DISABLE,
    }
    for capability_id, adapter in CAPABILITY_CATALOG.items():
        if capability_id in schedule_write_capabilities:
            assert adapter.paired_verify_input_keys == ("schedule_id",)
        else:
            assert adapter.paired_verify_input_keys == ()


def test_paired_verify_capability_id_defaults_to_none_except_for_the_four_write_workflows() -> (
    None
):
    """Every capability that declares no paired verifier of its own
    (everything except the four real TWO_STEP_WORKFLOW capabilities)
    still defaults to None - the field was added in Phase 94, Batch 1
    and needed no change for any of them; Phase 94, Batch 2 adds the
    second real pairing, SCHEDULE_ENABLE -> SCHEDULE_VERIFY_ENABLED_STATE;
    Phase 95 adds the third, SCHEDULE_DISABLE -> the *same*
    SCHEDULE_VERIFY_ENABLED_STATE (reused, never duplicated); Phase 96
    adds the fourth, PROJECT_STATE_UPDATE_PHASE -> the *same*
    PROJECT_STATE_VERIFY_FOCUS PROJECT_STATE_UPDATE_FOCUS already uses
    (reused, never duplicated)."""
    capabilities_with_a_paired_verifier = {
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.SCHEDULE_ENABLE,
        CapabilityId.SCHEDULE_DISABLE,
        CapabilityId.PROJECT_STATE_UPDATE_PHASE,
    }
    for capability_id, adapter in CAPABILITY_CATALOG.items():
        if capability_id in capabilities_with_a_paired_verifier:
            continue
        assert adapter.paired_verify_capability_id is None


def test_update_focus_paired_verify_capability_id_is_the_internal_verifier() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    assert (
        adapter.paired_verify_capability_id
        is CapabilityId.PROJECT_STATE_VERIFY_FOCUS
    )


def test_execution_strategy_has_exactly_two_members() -> None:
    assert {member.value for member in ExecutionStrategy} == {
        "single_tool",
        "two_step_workflow",
    }


# --- Phase 94, Batch 2: SCHEDULE_ENABLE / SCHEDULE_VERIFY_ENABLED_STATE -----


def test_schedule_enable_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_ENABLE]
    assert adapter.capability_id is CapabilityId.SCHEDULE_ENABLE
    assert adapter.tool_name == "schedule_enable"
    assert [spec.name for spec in adapter.arguments] == ["schedule_id"]
    assert adapter.arguments[0].type_name == "int"
    assert adapter.arguments[0].required is True
    assert adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW
    assert adapter.max_execution_tier is SecurityTier.YELLOW
    assert adapter.verification_strategy_id == "schedule_enabled_exact_match"
    assert adapter.internal_only is False
    assert (
        adapter.paired_verify_capability_id
        is CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
    )


def test_schedule_verify_enabled_state_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE]
    assert adapter.capability_id is CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
    assert adapter.tool_name == "schedule_verify_enabled_state"
    assert adapter.arguments == ()
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is True
    assert adapter.paired_verify_capability_id is None


# --- Phase 95: SCHEDULE_DISABLE -----------------------------------------


def test_schedule_disable_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_DISABLE]
    assert adapter.capability_id is CapabilityId.SCHEDULE_DISABLE
    assert adapter.tool_name == "schedule_disable"
    assert [spec.name for spec in adapter.arguments] == ["schedule_id"]
    assert adapter.arguments[0].type_name == "int"
    assert adapter.arguments[0].required is True
    assert adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW
    assert adapter.max_execution_tier is SecurityTier.YELLOW
    assert adapter.verification_strategy_id == "schedule_disabled_exact_match"
    assert adapter.internal_only is False
    assert (
        adapter.paired_verify_capability_id
        is CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
    )
    assert adapter.paired_verify_input_keys == ("schedule_id",)


# --- Phase 99, Batch 1: SCHEDULE_SHOW_ENABLED_STATE -------------------------


def test_schedule_show_enabled_state_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_SHOW_ENABLED_STATE]
    assert adapter.capability_id is CapabilityId.SCHEDULE_SHOW_ENABLED_STATE
    assert adapter.tool_name == "schedule_show_enabled_state"
    assert [spec.name for spec in adapter.arguments] == ["schedule_id"]
    assert adapter.arguments[0].type_name == "int"
    assert adapter.arguments[0].required is True
    assert adapter.allowed_strategy is ExecutionStrategy.SINGLE_TOOL
    assert adapter.max_execution_tier is SecurityTier.GREEN
    assert adapter.verification_strategy_id is None
    assert adapter.internal_only is False
    assert adapter.paired_verify_capability_id is None
    assert adapter.paired_verify_input_keys == ()


def test_schedule_show_enabled_state_has_no_fixed_arguments_or_key_renames() -> None:
    """Unlike memory_search/project_state_update_focus/etc., this
    capability's real tool input matches its own declared schedule_id
    argument one-to-one - no fixed literal, no key rename."""
    assert fixed_arguments_for(CapabilityId.SCHEDULE_SHOW_ENABLED_STATE) == {}


def test_schedule_enable_still_expects_true_and_disable_expects_false_by_construction() -> (
    None
):
    """The catalog itself carries no boolean expected-state field at
    all - both SCHEDULE_ENABLE and SCHEDULE_DISABLE declare only a
    verification_strategy_id label; the trusted True/False literal
    lives only in core/orchestrator.py's own two distinct response-
    builder methods, confirmed by direct source inspection."""
    import inspect

    import core.orchestrator as orchestrator_module

    enable_source = inspect.getsource(
        orchestrator_module.JarvisOrchestrator._schedule_enable_workflow_result_to_response
    )
    disable_source = inspect.getsource(
        orchestrator_module.JarvisOrchestrator._schedule_disable_workflow_result_to_response
    )
    assert "expected_enabled=True" in enable_source
    assert "expected_enabled=False" in disable_source


def test_schedule_disable_does_not_duplicate_the_verifier_tool_name() -> None:
    """SCHEDULE_DISABLE's paired verifier resolves to the identical
    real tool_name SCHEDULE_ENABLE already uses - never a second,
    differently-named verifier tool."""
    enable_adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_ENABLE]
    disable_adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_DISABLE]
    assert (
        enable_adapter.paired_verify_capability_id
        == disable_adapter.paired_verify_capability_id
    )
    verifier_adapter = CAPABILITY_CATALOG[
        CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
    ]
    assert verifier_adapter.tool_name == "schedule_verify_enabled_state"


def test_schedule_enable_and_disable_are_the_only_two_capabilities_pairing_with_the_schedule_verifier() -> (
    None
):
    """Exactly SCHEDULE_ENABLE and SCHEDULE_DISABLE name
    SCHEDULE_VERIFY_ENABLED_STATE as their own paired verifier
    (Phase 95 reuses the existing internal verifier rather than
    duplicating it) - no other capability does."""
    pairing_capabilities = {
        capability_id
        for capability_id, adapter in CAPABILITY_CATALOG.items()
        if adapter.paired_verify_capability_id
        is CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE
    }
    assert pairing_capabilities == {
        CapabilityId.SCHEDULE_ENABLE,
        CapabilityId.SCHEDULE_DISABLE,
    }


def test_project_state_update_focus_and_phase_are_the_only_two_capabilities_pairing_with_the_project_state_verifier() -> (
    None
):
    """Exactly PROJECT_STATE_UPDATE_FOCUS and PROJECT_STATE_UPDATE_PHASE
    name PROJECT_STATE_VERIFY_FOCUS as their own paired verifier (Phase
    96 reuses the existing internal verifier rather than duplicating
    it) - no other capability does."""
    pairing_capabilities = {
        capability_id
        for capability_id, adapter in CAPABILITY_CATALOG.items()
        if adapter.paired_verify_capability_id
        is CapabilityId.PROJECT_STATE_VERIFY_FOCUS
    }
    assert pairing_capabilities == {
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.PROJECT_STATE_UPDATE_PHASE,
    }


def test_no_fifth_user_facing_write_capability_was_added() -> None:
    """Exactly four capabilities are TWO_STEP_WORKFLOW (the only
    execution strategy that implies a write): PROJECT_STATE_UPDATE_FOCUS,
    SCHEDULE_ENABLE, SCHEDULE_DISABLE, and PROJECT_STATE_UPDATE_PHASE -
    no SCHEDULE_CREATE, schedule update/delete,
    PROJECT_STATE_UPDATE_BRANCH/COMMIT/SUITE, or any other write
    capability exists."""
    two_step_capabilities = {
        capability_id
        for capability_id, adapter in CAPABILITY_CATALOG.items()
        if adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW
    }
    assert two_step_capabilities == {
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.SCHEDULE_ENABLE,
        CapabilityId.SCHEDULE_DISABLE,
        CapabilityId.PROJECT_STATE_UPDATE_PHASE,
    }


def test_no_other_project_state_field_capability_exists() -> None:
    assert not any("PROJECT_STATE_UPDATE_BRANCH" in member.name for member in CapabilityId)
    assert not any("PROJECT_STATE_UPDATE_COMMIT" in member.name for member in CapabilityId)
    assert not any("PROJECT_STATE_UPDATE_SUITE" in member.name for member in CapabilityId)


def test_no_schedule_create_update_or_delete_capability_exists() -> None:
    assert not any("SCHEDULE_CREATE" in member.name for member in CapabilityId)
    assert not any("SCHEDULE_UPDATE" in member.name for member in CapabilityId)
    assert not any("SCHEDULE_DELETE" in member.name for member in CapabilityId)
    assert not any("SCHEDULE_VERIFY_DISABLED_STATE" in member.name for member in CapabilityId)


def test_build_tool_input_adds_no_fixed_arguments_for_schedule_enable() -> None:
    """schedule_enable's own real tool input key ("schedule_id")
    already matches its one declared argument's name one-to-one - no
    rename, no fixed literal merge needed, unlike memory_search's
    "value"->"query" rename or project_state_update_focus's fixed
    "field" key."""
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_ENABLE]
    assert build_tool_input(adapter, {"schedule_id": 5}) == {"schedule_id": 5}


def test_build_tool_input_adds_no_fixed_arguments_for_schedule_verify_enabled_state() -> (
    None
):
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE]
    assert build_tool_input(adapter, {}) == {}


def test_build_tool_input_adds_no_fixed_arguments_for_schedule_disable() -> None:
    """schedule_disable's own real tool input key ("schedule_id")
    already matches its one declared argument's name one-to-one,
    identical to schedule_enable's own shape."""
    adapter = CAPABILITY_CATALOG[CapabilityId.SCHEDULE_DISABLE]
    assert build_tool_input(adapter, {"schedule_id": 5}) == {"schedule_id": 5}


# --- Phase 96: PROJECT_STATE_UPDATE_PHASE ------------------------------------


def test_project_state_update_phase_adapter_fields_are_exact() -> None:
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_PHASE]
    assert adapter.capability_id is CapabilityId.PROJECT_STATE_UPDATE_PHASE
    assert adapter.tool_name == "project_state_update"
    assert [spec.name for spec in adapter.arguments] == ["value"]
    assert adapter.arguments[0].type_name == "str"
    assert adapter.arguments[0].required is True
    assert adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW
    assert adapter.max_execution_tier is SecurityTier.YELLOW
    assert adapter.verification_strategy_id == "project_state_phase_exact_match"
    assert adapter.internal_only is False
    assert (
        adapter.paired_verify_capability_id
        is CapabilityId.PROJECT_STATE_VERIFY_FOCUS
    )
    assert adapter.paired_verify_input_keys == ()


def test_project_state_update_phase_does_not_duplicate_the_verifier_capability() -> (
    None
):
    """PROJECT_STATE_UPDATE_PHASE's paired verifier resolves to the
    identical real CapabilityId/tool_name PROJECT_STATE_UPDATE_FOCUS
    already uses - never a second, differently-named verifier
    capability."""
    focus_adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    phase_adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_PHASE]
    assert (
        focus_adapter.paired_verify_capability_id
        == phase_adapter.paired_verify_capability_id
    )
    verifier_adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_VERIFY_FOCUS]
    assert verifier_adapter.tool_name == "project_state_verify"


def test_build_tool_input_fixes_field_to_phase_and_model_cannot_override_it() -> None:
    """The model's own arguments dict can never smuggle in a different
    "field" value - build_tool_input's fixed-argument merge always
    wins, mirroring project_state_update_focus's own established
    contract exactly."""
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_PHASE]
    assert build_tool_input(adapter, {"value": "Phase 96"}) == {
        "field": "phase",
        "value": "Phase 96",
    }
    # Even a stray "field" key in the model's own arguments (which
    # intelligence/structured_output.py would already reject before
    # this function is ever reached) could never override the fixed
    # literal, since fixed arguments are merged in last.
    assert build_tool_input(adapter, {"value": "Phase 96", "field": "focus"}) == {
        "field": "phase",
        "value": "Phase 96",
    }


def test_project_state_update_focus_and_phase_use_different_fixed_fields() -> None:
    focus_adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    phase_adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_PHASE]
    assert build_tool_input(focus_adapter, {"value": "x"}) == {
        "field": "focus",
        "value": "x",
    }
    assert build_tool_input(phase_adapter, {"value": "x"}) == {
        "field": "phase",
        "value": "x",
    }


def test_fixed_arguments_for_returns_a_copy_never_the_live_dict() -> None:
    """fixed_arguments_for() is a public accessor - mutating its return
    value must never affect the real, private
    _FIXED_ARGUMENTS_BY_CAPABILITY table."""
    from intelligence.capability_catalog import fixed_arguments_for

    first_call = fixed_arguments_for(CapabilityId.PROJECT_STATE_UPDATE_PHASE)
    first_call["field"] = "tampered"
    second_call = fixed_arguments_for(CapabilityId.PROJECT_STATE_UPDATE_PHASE)
    assert second_call == {"field": "phase"}


def test_fixed_arguments_for_returns_empty_dict_for_capability_with_none_declared() -> (
    None
):
    from intelligence.capability_catalog import fixed_arguments_for

    assert fixed_arguments_for(CapabilityId.PROJECT_STATE_SHOW) == {}
    assert fixed_arguments_for(CapabilityId.SCHEDULE_ENABLE) == {}
