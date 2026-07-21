"""
capability_catalog.py

The hand-maintained tool-selection allowlist for Jarvis's "ask jarvis
to: <request>" command (Phase 90, Batches 2/3; Phase 91, Batch 1;
contracts fixed by docs/phase_90_implementation_plan.md, Sections
25.C/25.D/26, the Batch 3 planning prompt, and
docs/phase_91_implementation_plan.md).

Responsibilities:
    - Define the small, closed set of types describing a selectable
      capability: CapabilityId, CapabilityArgumentSpec,
      ExecutionStrategy, CapabilityAdapter.
    - Provide CAPABILITY_CATALOG, the single source of truth for which
      capabilities the intelligence layer may even consider selecting.
      Batch 3 added exactly two entries to Batch 2's one:
      PROJECT_STATE_UPDATE_FOCUS (model-selectable, YELLOW, executed
      only via a deterministic two-step WorkflowEngine plan) and
      PROJECT_STATE_VERIFY_FOCUS (internal-only - never selectable
      from AI output, reachable only as the fixed second step of that
      one workflow). Phase 91, Batch 1 adds three further
      model-selectable, zero-argument, GREEN, SINGLE_TOOL entries:
      HEALTH_CHECK, SCHEDULE_LIST, and MEMORY_LIST_RECENT - each a
      thin, exact-tier-checked wrapper around an already-registered,
      already-tested read-only tool, reusing the exact same
      SINGLE_TOOL execution strategy PROJECT_STATE_SHOW already uses.
      Phase 91, Batch 2 adds one further model-selectable, bounded,
      single-argument, GREEN, SINGLE_TOOL entry: MEMORY_SEARCH.
      Phase 93, Batch 1 adds two further model-selectable, zero-
      argument, GREEN, SINGLE_TOOL entries: APPROVAL_HISTORY and
      WORKFLOW_HISTORY - each a thin wrapper around an already-
      registered, already-tested tool's own existing default
      ("history") operation, hard-bounded at 20 records by that real
      tool itself. Neither exposes the tool's "recent"/"get" (and, for
      approval_history, "approved"/"declined") operations - those
      remain reachable only through the existing deterministic command
      grammar, never through this AI-facing catalog.
      Phase 94, Batch 1 adds no new capability, but adds
      CapabilityAdapter.paired_verify_capability_id (defaulting to None
      for every capability defined before this batch) so that
      intelligence/planning.py's workflow-builder can look up
      PROJECT_STATE_UPDATE_FOCUS's own paired internal verifier
      (PROJECT_STATE_VERIFY_FOCUS) from this catalog's own trusted data
      instead of a hardcoded literal - a small, foundational
      generalization intended to support a second TWO_STEP_WORKFLOW
      capability in a later phase, without adding one yet. Phase 94,
      Batch 2 is that later phase: it adds SCHEDULE_ENABLE
      (model-selectable, YELLOW, single required integer argument
      "schedule_id", executed only via the same deterministic two-step
      WorkflowEngine plan shape PROJECT_STATE_UPDATE_FOCUS already
      uses, now proven genuinely reusable) and
      SCHEDULE_VERIFY_ENABLED_STATE (internal-only, the second
      TWO_STEP_WORKFLOW pairing this catalog now carries, structurally
      identical to PROJECT_STATE_VERIFY_FOCUS).
    - Provide a small, deterministic tool-input builder that copies a
      capability's own declared (model-supplied) arguments, plus - for
      the small number of capabilities that need it - a fixed set of
      non-model-controlled arguments the real tool requires (e.g. the
      literal field name for project_state_update_focus, or the
      literal memory-list/memory-search operation for
      memory_list_recent/memory_search), and, for memory_search only,
      a fixed rename of its one model-facing argument ("value") into
      the real MemoryTool's own input key ("query"). Never more than
      that, and never derived from model output.

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
    HEALTH_CHECK = "health_check"
    SCHEDULE_LIST = "schedule_list"
    MEMORY_LIST_RECENT = "memory_list_recent"
    MEMORY_SEARCH = "memory_search"
    APPROVAL_HISTORY = "approval_history"
    WORKFLOW_HISTORY = "workflow_history"
    SCHEDULE_ENABLE = "schedule_enable"
    SCHEDULE_VERIFY_ENABLED_STATE = "schedule_verify_enabled_state"


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
        paired_verify_capability_id: None for every SINGLE_TOOL
            capability. For a TWO_STEP_WORKFLOW capability, the fixed,
            trusted, internal-only capability id
            intelligence/planning.py's workflow-builder must pair it
            with as the workflow's own fixed second step (Phase 94,
            Batch 1 - generalizing what was previously a literal,
            hardcoded CapabilityId reference inside the workflow-
            builder itself). Never selected, read, or influenced by
            model output - a trusted, static production mapping only.
            Defaults to None so every capability defined before Phase
            94 needs no change at all.
        paired_verify_input_keys: Empty for every capability whose
            paired verifier needs no data from the write step (e.g.
            PROJECT_STATE_UPDATE_FOCUS's verifier reads a singleton
            row, so it needs nothing). For a TWO_STEP_WORKFLOW
            capability whose verifier needs to know *which* record to
            re-read, the fixed, trusted names of keys to copy verbatim
            from the write step's own already-validated tool_input into
            the verify step's own tool_input (Phase 94, Batch 2 -
            SCHEDULE_ENABLE sets this to ("schedule_id",), since its
            verifier must target the exact same schedule the write step
            did). A trusted, static, per-capability declaration only -
            never model-supplied, never derived from parsed output.
            Defaults to an empty tuple.
    """

    capability_id: CapabilityId
    tool_name: str
    description: str
    arguments: tuple[CapabilityArgumentSpec, ...]
    allowed_strategy: ExecutionStrategy
    max_execution_tier: SecurityTier
    verification_strategy_id: str | None
    internal_only: bool
    paired_verify_capability_id: CapabilityId | None = None
    paired_verify_input_keys: tuple[str, ...] = ()


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
        paired_verify_capability_id=CapabilityId.PROJECT_STATE_VERIFY_FOCUS,
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
    CapabilityId.HEALTH_CHECK: CapabilityAdapter(
        capability_id=CapabilityId.HEALTH_CHECK,
        tool_name="health_check",
        description=(
            "Reports basic Jarvis system health (settings, database path, "
            "tool registry, console logging, and store reachability). "
            "Read-only and safe."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.SCHEDULE_LIST: CapabilityAdapter(
        capability_id=CapabilityId.SCHEDULE_LIST,
        tool_name="schedule_list",
        description=(
            "Lists your configured web-search-summary schedules. "
            "Read-only and safe."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.MEMORY_LIST_RECENT: CapabilityAdapter(
        capability_id=CapabilityId.MEMORY_LIST_RECENT,
        tool_name="memory",
        description=(
            "Lists your most recently stored memories. Read-only and safe."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.MEMORY_SEARCH: CapabilityAdapter(
        capability_id=CapabilityId.MEMORY_SEARCH,
        tool_name="memory",
        description=(
            "Searches your stored memories for text matching a query. "
            "Read-only and safe."
        ),
        arguments=(CapabilityArgumentSpec(name="value", type_name="str", required=True),),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.APPROVAL_HISTORY: CapabilityAdapter(
        capability_id=CapabilityId.APPROVAL_HISTORY,
        tool_name="approval_history",
        description=(
            "Shows your recent approval history (up to 20 most recent "
            "entries). Read-only and safe."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.WORKFLOW_HISTORY: CapabilityAdapter(
        capability_id=CapabilityId.WORKFLOW_HISTORY,
        tool_name="workflow_history",
        description=(
            "Shows your recent workflow history (up to 20 most recent "
            "entries). Read-only and safe."
        ),
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=False,
    ),
    CapabilityId.SCHEDULE_ENABLE: CapabilityAdapter(
        capability_id=CapabilityId.SCHEDULE_ENABLE,
        tool_name="schedule_enable",
        description=(
            "Re-enables one of your configured schedules by its exact id. "
            "Requires your explicit approval, and the stored enabled "
            "state is checked with a structured read-back after it runs."
        ),
        arguments=(
            CapabilityArgumentSpec(name="schedule_id", type_name="int", required=True),
        ),
        allowed_strategy=ExecutionStrategy.TWO_STEP_WORKFLOW,
        max_execution_tier=SecurityTier.YELLOW,
        verification_strategy_id="schedule_enabled_exact_match",
        internal_only=False,
        paired_verify_capability_id=CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE,
        paired_verify_input_keys=("schedule_id",),
    ),
    CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE: CapabilityAdapter(
        capability_id=CapabilityId.SCHEDULE_VERIFY_ENABLED_STATE,
        tool_name="schedule_verify_enabled_state",
        description=(
            "Internal-only: reads back one schedule's current enabled "
            "state to verify a prior enable. Never selectable by AI, "
            "never a user command."
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


#: Fixed, non-model-controlled tool-input keys some capabilities need
#: in addition to (never instead of) their own declared, validated
#: arguments. Several real tools are multi-purpose (ProjectStateUpdateTool
#: keys its write on a "field" name; MemoryTool, ApprovalHistoryTool, and
#: WorkflowHistoryTool each key their behaviour on an "operation" name)
#: but the model is only ever asked to supply the capability's own
#: narrow, declared arguments - never the field/operation name itself.
#: Each entry here is a fixed literal, chosen once by this catalog,
#: never derived from or overridable by model output (see
#: build_tool_input's own "never overrides a model-supplied key"
#: contract below). APPROVAL_HISTORY and WORKFLOW_HISTORY (Phase 93,
#: Batch 1) both fix "operation": "history" - the real tools' own
#: default operation, made explicit here rather than relied upon
#: implicitly, since both tools accept "history" as an explicit value.
#: Every other capability's real tool input already matches its own
#: validated arguments one-to-one, so it simply has no entry here.
_FIXED_ARGUMENTS_BY_CAPABILITY: dict[CapabilityId, dict[str, object]] = {
    CapabilityId.PROJECT_STATE_UPDATE_FOCUS: {"field": "focus"},
    CapabilityId.MEMORY_LIST_RECENT: {"operation": "list"},
    CapabilityId.MEMORY_SEARCH: {"operation": "search"},
    CapabilityId.APPROVAL_HISTORY: {"operation": "history"},
    CapabilityId.WORKFLOW_HISTORY: {"operation": "history"},
}

#: Fixed, non-model-controlled renames of a capability's own declared
#: argument name into the real tool's own input key, applied before any
#: fixed arguments are merged in (Phase 91, Batch 2). Only
#: memory_search needs this: its one model-facing argument is named
#: "value" - matching project_state_update_focus's own established
#: single-string-argument convention - but the real MemoryTool expects
#: that same text under the key "query", not "value". This mapping is a
#: fixed literal chosen once by this catalog, never derived from or
#: influenced by model output - the model only ever sees and supplies
#: "value"; it never sees, chooses, or can override "query" as a key
#: name. Every other capability's real tool input already matches its
#: own validated arguments' key names one-to-one, so it simply has no
#: entry here.
_ARGUMENT_KEY_RENAMES_BY_CAPABILITY: dict[CapabilityId, dict[str, str]] = {
    CapabilityId.MEMORY_SEARCH: {"value": "query"},
}


def build_tool_input(
    adapter: CapabilityAdapter, arguments: dict[str, object]
) -> dict[str, object]:
    """Deterministically build the real tool input for a capability.

    This starts as a plain, defensive copy of already-validated
    arguments - this function performs no validation of its own (that
    already happened in intelligence/structured_output.py, against
    this same adapter's own declared arguments); it exists so no code
    path ever hands a decoder-owned or otherwise externally-held dict
    reference directly to a real ToolRequest. For the small number of
    capabilities registered in _ARGUMENT_KEY_RENAMES_BY_CAPABILITY,
    this copy also renames the matching key(s) to the real tool's own
    input key name(s) - e.g. memory_search's validated "value" argument
    becomes "query", the key MemoryTool's real "search" operation
    actually reads.

    For the small number of capabilities registered in
    _FIXED_ARGUMENTS_BY_CAPABILITY, this then merges in that
    capability's own fixed, literal key/value pairs - e.g.
    project_state_update_focus's real tool (ProjectStateUpdateTool)
    expects a "field" key the model is never asked to supply, and
    memory_list_recent's/memory_search's real tool (MemoryTool) expects
    an "operation" key the model is never asked to supply either. These
    fixed values always win: they are applied after the model-supplied
    (and possibly renamed) copy, so a capability's own declared
    arguments can never smuggle in a different key of the same name (in
    practice this never happens, since a capability never simultaneously
    declares an argument with the same name as one of its own fixed
    keys).

    Args:
        adapter: The capability adapter the arguments belong to - used
            to look up any key renames and fixed key/value pairs this
            capability needs.
        arguments: The already-validated arguments dict.

    Returns:
        A new dict: `arguments`' own key/value pairs (renamed per
        _ARGUMENT_KEY_RENAMES_BY_CAPABILITY, if any), plus this
        capability's fixed key/value pairs (if any).
    """
    renames = _ARGUMENT_KEY_RENAMES_BY_CAPABILITY.get(adapter.capability_id)
    if renames is not None:
        tool_input = {
            renames.get(key, key): value for key, value in arguments.items()
        }
    else:
        tool_input = dict(arguments)

    fixed_arguments = _FIXED_ARGUMENTS_BY_CAPABILITY.get(adapter.capability_id)
    if fixed_arguments is not None:
        tool_input.update(fixed_arguments)
    return tool_input
