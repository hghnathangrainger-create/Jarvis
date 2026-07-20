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
    get_adapter,
)


def test_catalog_contains_exactly_the_seven_phase_91_batch_2_entries() -> None:
    assert set(CAPABILITY_CATALOG) == {
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
        CapabilityId.HEALTH_CHECK,
        CapabilityId.SCHEDULE_LIST,
        CapabilityId.MEMORY_LIST_RECENT,
        CapabilityId.MEMORY_SEARCH,
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


def test_only_six_capabilities_are_model_selectable() -> None:
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
    }


def test_execution_strategy_has_exactly_two_members() -> None:
    assert {member.value for member in ExecutionStrategy} == {
        "single_tool",
        "two_step_workflow",
    }
