"""
capability_catalog.py

The hand-maintained tool-selection allowlist for Jarvis's "ask jarvis
to: <request>" command (Phase 90, Batches 2/3; contracts fixed by
docs/phase_90_implementation_plan.md, Sections 25.C/25.D/26 and the
Batch 3 planning prompt).

Responsibilities:
    - Define the small, closed set of types describing a selectable
      capability: CapabilityId, CapabilityArgumentSpec,
      ExecutionStrategy, CapabilityAdapter.
    - Provide CAPABILITY_CATALOG, the single source of truth for which
      capabilities the intelligence layer may even consider selecting.
      Batch 3 adds exactly two entries to Batch 2's one:
      PROJECT_STATE_UPDATE_FOCUS (model-selectable, YELLOW, executed
      only via a deterministic two-step WorkflowEngine plan) and
      PROJECT_STATE_VERIFY_FOCUS (internal-only - never selectable
      from AI output, reachable only as the fixed second step of that
      one workflow).
    - Provide a small, deterministic tool-input builder that copies and
      returns only a capability's own declared arguments - never more.

Does NOT:
    - Expose every ToolRegistry tool to the model. ToolRegistry is
      Jarvis's general tool-execution registry, not the intelligence
      allowlist - a real, registered tool absent from
      CAPABILITY_CATALOG is never selectable through this module, no
      matter what a model response names.
    - Call any AI provider, classify security, or execute a tool. This
      module is pure, static data plus one small pure helper function.
    - Validate a parsed model response - that is
      intelligence/structured_output.py's job, which imports the types
      defined here to validate a selected capability's arguments
      against its own declared CapabilityArgumentSpec tuple, and to
      reject any AI-selected capability marked internal_only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.constants import SecurityTier


class CapabilityId(Enum):
    """The bounded set of capabilities the intelligence layer may select
    or construct.

    A future batch may add a new member only when a real, catalogued
    consumer exists for it - never speculatively.
    """

    PROJECT_STATE_SHOW = "project_state_show"
    PROJECT_STATE_UPDATE_FOCUS = "project_state_update_focus"
    PROJECT_STATE_VERIFY_FOCUS = "project_state_verify_focus"


class ExecutionStrategy(Enum):
    """How a selected capability is executed.

    Attributes:
        SINGLE_TOOL: One direct ToolExecutor.execute() call - Batch 2's
            original, unchanged strategy (project_state_show), also
            used for the internal verifier capability itself (it is a
            single real tool call; only its *selectability* is
            restricted, not its execution shape).
        TWO_STEP_WORKFLOW: A deterministic, fixed two-step Plan run
            through the real, unmodified WorkflowEngine - Batch 3's
            new strategy for project_state_update_focus. Never a
            generic N-step or dynamically-sized plan.
    """

    SINGLE_TOOL = "single_tool"
    TWO_STEP_WORKFLOW = "two_step_workflow"


@dataclass(frozen=True, slots=True)
class CapabilityArgumentSpec:
    """One declared argument a capability accepts.

    Attributes:
        name: The argument's name, as it must appear in a model
            response's "arguments" object.
        type_name: One of a small fixed set for V1: "str" | "int" | "bool".
        required: Whether this argument must be present.
    """

    name: str
    type_name: str
    required: bool


@dataclass(frozen=True, slots=True)
class CapabilityAdapter:
    """A single, hand-maintained catalog entry describing one selectable
    capability and the real tool it maps to.

    Attributes:
        capability_id: The bounded identifier a model response selects.
        tool_name: The real, registered ToolRegistry name this
            capability maps to.
        description: A user-facing, non-instructional description.
        arguments: The capability's declared arguments. Empty for
            project_state_show.
        allowed_strategy: The execution strategy permitted for this
            capability.
        max_execution_tier: The highest SecurityTier this capability
            may execute at. GREEN for every Batch 2 entry.
        verification_strategy_id: None until a future batch defines a
            real one.
        internal_only: True only for a capability never reachable via
            CommandRouter's own grammar - False here, since
            project_state_show is already directly reachable via "show
            jarvis project state" (Phase 89).
    """

    capability_id: CapabilityId
    tool_name: str
    description: str
    arguments: tuple[CapabilityArgumentSpec, ...]
    allowed_strategy: ExecutionStrategy
    max_execution_tier: SecurityTier
    verification_strategy_id: str | None
    internal_only: bool


#: The single source of truth for what the intelligence layer may
#: select (Section 25.C). ToolRegistry.has_tool(adapter.tool_name) is
#: still checked at preflight time as a defensive final existence
#: check - this catalog, not the full registry, governs selectability.
#: max_execution_tier is the exact, required preflight tier for this
#: capability - not merely a ceiling: intelligence/planning.py's
#: preflight rejects any real, live classification that differs from
#: it in *either* direction (a YELLOW capability whose live action
#: unexpectedly classifies GREEN is treated as a safety mismatch, not
#: a fortunate downgrade).
CAPABILITY_CATALOG: dict[CapabilityId, CapabilityAdapter] = {
    CapabilityId.PROJECT_STATE_SHOW: CapabilityAdapter(
        capability_id=CapabilityId.PROJECT_STATE_SHOW,
        tool_name="project_state_show",
        description=(
            "Shows the current manually-recorded Jarvis project state "
            "(branch, phase, commit, test-suite result, focus)."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.PROJECT_STATE_UPDATE_FOCUS: CapabilityAdapter(
        capability_id=CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        tool_name="project_state_update",
        description=(
            "Updates the manually-maintained Jarvis project state's focus "
            "field. Requires your explicit approval, and the stored value "
            "is checked with a structured read-back after it runs."
        ),
        arguments=(CapabilityArgumentSpec(name="value", type_name="str", required=True),),
        allowed_strategy=ExecutionStrategy.TWO_STEP_WORKFLOW,
        max_execution_tier=SecurityTier.YELLOW,
        verification_strategy_id="project_state_focus_exact_match",
        internal_only=False,
    ),
    CapabilityId.PROJECT_STATE_VERIFY_FOCUS: CapabilityAdapter(
        capability_id=CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
        tool_name="project_state_verify",
        description=(
            "Internal-only: reads back the current focus value to verify "
            "a prior update. Never selectable by AI, never a user command."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=True,
    ),
}


def get_adapter(capability_id: CapabilityId) -> CapabilityAdapter | None:
    """Return the catalog entry for a capability id, or None.

    Args:
        capability_id: The capability id to look up.

    Returns:
        The CapabilityAdapter for capability_id, or None if it is not
        in CAPABILITY_CATALOG.
    """
    return CAPABILITY_CATALOG.get(capability_id)


#: The one fixed, non-trivial tool-input transformation Batch 3 needs:
#: project_state_update_focus's real tool (ProjectStateUpdateTool)
#: expects {"field": ..., "value": ...}, but the model only ever
#: supplies {"value": ...} - "field" is always the fixed literal
#: "focus", never model-controlled, never any other field name. This
#: is a single, explicitly-named special case, not a generic per-
#: adapter callable: every other capability's real tool input already
#: matches its own validated arguments one-to-one.
_FIXED_FIELD_BY_CAPABILITY: dict[CapabilityId, str] = {
    CapabilityId.PROJECT_STATE_UPDATE_FOCUS: "focus",
}


def build_tool_input(
    adapter: CapabilityAdapter, arguments: dict[str, object]
) -> dict[str, object]:
    """Deterministically build the real tool input for a capability.

    For every capability except project_state_update_focus, this is a
    plain, defensive copy of already-validated arguments - this
    function performs no validation of its own (that already happened
    in intelligence/structured_output.py, against this same adapter's
    own declared arguments); it exists so no code path ever hands a
    decoder-owned or otherwise externally-held dict reference directly
    to a real ToolRequest.

    For project_state_update_focus specifically, the real tool
    (ProjectStateUpdateTool) expects a "field" key the model is never
    asked to supply - this function adds it, fixed to the literal
    "focus", never derived from model output.

    Args:
        adapter: The capability adapter the arguments belong to -
            used to look up the one fixed-field special case above.
        arguments: The already-validated arguments dict.

    Returns:
        A new dict. For most capabilities, the same key/value pairs as
        `arguments`. For project_state_update_focus, `arguments` plus
        a fixed `"field"` key.
    """
    tool_input = dict(arguments)
    fixed_field = _FIXED_FIELD_BY_CAPABILITY.get(adapter.capability_id)
    if fixed_field is not None:
        tool_input["field"] = fixed_field
    return tool_input
