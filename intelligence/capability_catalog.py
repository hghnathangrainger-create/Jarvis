"""
capability_catalog.py

The hand-maintained tool-selection allowlist for Jarvis's "ask jarvis
to: <request>" command (Phase 90, Batch 2; contracts fixed by
docs/phase_90_implementation_plan.md, Sections 25.C/25.D/26).

Responsibilities:
    - Define the small, closed set of types describing a selectable
      capability: CapabilityId, CapabilityArgumentSpec,
      ExecutionStrategy, CapabilityAdapter.
    - Provide CAPABILITY_CATALOG, the single source of truth for which
      capabilities the intelligence layer may even consider selecting.
      In Batch 2 this contains exactly one entry: PROJECT_STATE_SHOW.
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
      against its own declared CapabilityArgumentSpec tuple.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config.constants import SecurityTier


class CapabilityId(Enum):
    """The bounded set of capabilities the intelligence layer may select.

    Batch 2 contains exactly one member. A future batch may add a new
    member only when a real, catalogued consumer exists for it - never
    speculatively.
    """

    PROJECT_STATE_SHOW = "project_state_show"


class ExecutionStrategy(Enum):
    """How a selected capability is executed. Batch 2 has exactly one
    strategy: a single real tool call, with no multi-step plan."""

    SINGLE_TOOL = "single_tool"


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


def build_tool_input(
    adapter: CapabilityAdapter, arguments: dict[str, object]
) -> dict[str, object]:
    """Deterministically build the real tool input for a capability.

    A plain, defensive copy of already-validated arguments - this
    function performs no validation of its own (that already happened
    in intelligence/structured_output.py, against this same adapter's
    own declared arguments); it exists so no code path ever hands a
    decoder-owned or otherwise externally-held dict reference directly
    to a real ToolRequest.

    Args:
        adapter: The capability adapter the arguments belong to
            (unused beyond documenting intent for V1, since every
            Batch 2 capability's arguments are already validated
            one-to-one before this is called).
        arguments: The already-validated arguments dict.

    Returns:
        A new dict containing the same key/value pairs.
    """
    return dict(arguments)
