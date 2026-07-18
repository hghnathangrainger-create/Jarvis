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


def test_catalog_contains_exactly_the_three_batch_3_entries() -> None:
    assert set(CAPABILITY_CATALOG) == {
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
    }


def test_no_other_capability_id_exists() -> None:
    assert {member.value for member in CapabilityId} == {
        "project_state_show",
        "project_state_update_focus",
        "project_state_verify_focus",
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


def test_only_two_capabilities_are_model_selectable() -> None:
    selectable = {
        capability_id
        for capability_id, adapter in CAPABILITY_CATALOG.items()
        if not adapter.internal_only
    }
    assert selectable == {
        CapabilityId.PROJECT_STATE_SHOW,
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
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
