"""
planning.py

Ties Context Intelligence, the trusted planning instruction, strict
structured-output parsing, the capability catalog, and deterministic
security preflight together into a single, testable function:
select_tool() (Phase 90, Batches 2/3; Phase 91, Batches 1/2; contracts
fixed by docs/phase_90_implementation_plan.md, Sections 25/26, the
Batch 3 planning prompt, and docs/phase_91_implementation_plan.md).

Responsibilities:
    - Own the one fixed, Jarvis-authored trusted planning instruction
      (Section 26.C) - never mixed into memory, ProjectState, or any
      other untrusted ContextItem. Batch 3 extends it to describe both
      model-selectable capabilities and explicitly forbids the
      internal verifier from ever being offered.
    - Call the real, already-constructed AIRouter.route() directly
      (Section 26.C's own inspection finding: AIReasoningEngine.reason()
      hardcodes one shared system instruction with no field for a
      per-request addition, but AIRouter.route(system_instruction=...)
      already accepts an arbitrary trusted instruction per call,
      without touching any trust-boundary enforcement code).
    - Parse and validate the response via
      intelligence.structured_output.parse_tool_selection().
    - For a valid "execute" decision naming a SINGLE_TOOL capability
      (project_state_show): resolve the CapabilityAdapter, confirm its
      real tool is still registered, build its deterministic tool
      input, call the real tool's own action_for(), classify it
      through the real SecurityManager, and require its preflight tier
      to exactly match the catalog's declared max_execution_tier
      before returning an executable, flat StructuredPlan.
    - For a valid "execute" decision naming a TWO_STEP_WORKFLOW
      capability (project_state_update_focus, Batch 3): perform the
      same preflight for the write step (expecting exactly YELLOW),
      additionally preflight the fixed internal verifier capability
      (expecting exactly GREEN), and deterministically construct a
      real, exactly-two-step planner.plan_models.Plan for the caller
      to run through the real, unmodified WorkflowEngine. The AI never
      selects, orders, or configures the verifier step - it is always
      the second, fixed step of this one workflow shape.
    - For a valid "unsupported" decision: return that outcome directly,
      with no plan, no preflight, and no tool involvement of any kind.

Does NOT:
    - Call ToolExecutor.execute(), WorkflowEngine.run()/resume(), or
      tool.run() itself. This module only ever prepares a plan for the
      caller (core/orchestrator.py) to execute through the real,
      unmodified ToolExecutor/WorkflowEngine - exactly the same
      division of responsibility Batch 1 already established between
      intelligence/context.py (assembly) and core/orchestrator.py
      (execution/response).
    - Create an approval, retry, or replan. WorkflowEngine's own,
      unmodified ApprovalManager integration is the sole approval
      authority for the two-step workflow this module constructs.
    - Modify Batch 1's ContextAssembler, its budgets, or its
      memory-selection algorithm - this module only ever consumes an
      already-assembled AssembledContext, unchanged.
    - Modify ai/reasoning_engine.py, ai/router.py, ai/prompt_builder.py,
      workflow/engine.py, or planner/plan_models.py. AIRouter and
      Plan/PlanStep are used exactly as already built.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from ai.providers.base import AIProviderError
from ai.response_validator import ResponseValidationError
from ai.router import AIRouter
from config.constants import SecurityTier
from intelligence.capability_catalog import (
    CAPABILITY_CATALOG,
    CapabilityAdapter,
    CapabilityId,
    ExecutionStrategy,
    build_tool_input,
)
from intelligence.context import AssembledContext, build_ai_context_block
from intelligence.grounding import ground_decision
from intelligence.structured_output import (
    ToolSelectionDecision,
    ToolSelectionParseError,
    parse_tool_selection,
)
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityDecision, SecurityManager
from tools.base_tool import ToolRequest
from tools.registry import ToolRegistry

#: The one fixed, Jarvis-authored trusted planning instruction (Section
#: 26.C; extended for Batch 3; extended for Phase 91, Batch 1). Supplied
#: only through AIRouter.route()'s own system_instruction parameter -
#: never mixed into any ContextItem, and never derived from, or
#: influenced by, memory or ProjectState text. Echoes every valid
#: response shape verbatim, per Section 26.C's own requirement that the
#: trusted instruction include the exact valid objects. Explicitly
#: names project_state_verify_focus as internal-only and forbidden from
#: ever being offered - the parser (intelligence/structured_output.py)
#: independently enforces this too, so a model that ignores this
#: instruction is still rejected.
_TRUSTED_PLANNING_INSTRUCTION = (
    "You are Jarvis's tool-selection planner. Exactly eight capabilities "
    "are available to you:\n"
    "\n"
    '1. capability id "project_state_show" - shows the current '
    "manually-recorded Jarvis project state (branch, phase, commit, "
    "test-suite result, focus). Use this only when the request asks to "
    "show or read the manually-maintained project state.\n"
    "\n"
    '2. capability id "project_state_update_focus" - updates only the '
    "manually-maintained project state's focus field. Use this only "
    "when the request explicitly asks to update the project state's "
    "focus. Include the requested new focus text in "
    'arguments.value (a non-empty string). This action requires your '
    "explicit approval and will be verified with a structured read-back "
    "after it runs.\n"
    "\n"
    '3. capability id "health_check" - reports basic Jarvis system '
    "health. Use this only when the request asks about Jarvis's health "
    "or status. Takes no arguments.\n"
    "\n"
    '4. capability id "schedule_list" - lists your configured '
    "web-search-summary schedules. Use this only when the request asks "
    "to see or list schedules. Takes no arguments.\n"
    "\n"
    '5. capability id "memory_list_recent" - lists your most recently '
    "stored memories. Use this only when the request asks to see or "
    "list recently stored memories. Takes no arguments.\n"
    "\n"
    '6. capability id "memory_search" - searches your stored memories '
    "for text matching a query. Use this only when the request asks to "
    "search or find stored memories matching some text. Include the "
    "search text in arguments.value (a non-empty string, at most 500 "
    "characters).\n"
    "\n"
    '7. capability id "approval_history" - shows your recent approval '
    "history (up to 20 most recent entries). Use this only when the "
    "request asks to show or list your approval history. Takes no "
    "arguments.\n"
    "\n"
    '8. capability id "workflow_history" - shows your recent workflow '
    "history (up to 20 most recent entries). Use this only when the "
    "request asks to show or list your workflow history. Takes no "
    "arguments.\n"
    "\n"
    'A ninth capability id, "project_state_verify_focus", exists only '
    "internally - it is never a valid selection, is never selectable "
    "through your output, and must never appear in your response under "
    "any circumstances.\n"
    "\n"
    "If no capability above can satisfy the request, you must return "
    "the exact unsupported object.\n"
    "\n"
    "Respond with exactly one of these JSON objects, and nothing else:\n"
    "\n"
    "Execute (show):\n"
    '{"decision": "execute", "capability_id": "project_state_show", '
    '"arguments": {}}\n'
    "\n"
    "Execute (update focus):\n"
    '{"decision": "execute", "capability_id": '
    '"project_state_update_focus", "arguments": {"value": "the '
    'requested new focus"}}\n'
    "\n"
    "Execute (health check):\n"
    '{"decision": "execute", "capability_id": "health_check", '
    '"arguments": {}}\n'
    "\n"
    "Execute (schedule list):\n"
    '{"decision": "execute", "capability_id": "schedule_list", '
    '"arguments": {}}\n'
    "\n"
    "Execute (recent memories):\n"
    '{"decision": "execute", "capability_id": "memory_list_recent", '
    '"arguments": {}}\n'
    "\n"
    "Execute (search memories):\n"
    '{"decision": "execute", "capability_id": "memory_search", '
    '"arguments": {"value": "the search text"}}\n'
    "\n"
    "Execute (approval history):\n"
    '{"decision": "execute", "capability_id": "approval_history", '
    '"arguments": {}}\n'
    "\n"
    "Execute (workflow history):\n"
    '{"decision": "execute", "capability_id": "workflow_history", '
    '"arguments": {}}\n'
    "\n"
    "Unsupported:\n"
    '{"decision": "unsupported", "capability_id": null, "arguments": {}}\n'
    "\n"
    "Return JSON only. Do not include any explanation or extra prose. Do "
    "not use Markdown formatting except one optional outer ```json code "
    "fence around the JSON object."
)

#: The fixed, honest message returned for a valid "unsupported" decision
#: (Section 26.A/F) - never varied by request content or model wording.
UNSUPPORTED_CAPABILITY_MESSAGE = (
    "Jarvis could not find an allowlisted capability that can safely "
    "complete that request."
)


class PlanningOutcomeKind(Enum):
    """The distinct outcomes select_tool() may report - never collapsed
    into a single generic result, so a caller can honestly distinguish
    each one (Section 26's own "AI enablement gate" requirement)."""

    #: A valid "execute" decision selecting a SINGLE_TOOL capability,
    #: preflight passed - `plan` is set.
    EXECUTABLE = "executable"
    #: A valid "execute" decision selecting the TWO_STEP_WORKFLOW
    #: capability (Batch 3), both steps' preflights passed -
    #: `workflow_plan` is set, ready for WorkflowEngine.run().
    EXECUTABLE_WORKFLOW = "executable_workflow"
    #: A valid "unsupported" decision - no plan, no tool involvement.
    UNSUPPORTED = "unsupported"
    #: The router's provider reported itself unavailable; route() was
    #: never called.
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    #: route() itself raised (AIProviderError/ResponseValidationError).
    PROVIDER_FAILED = "provider_failed"
    #: Parsing/validation failed, or a selected capability failed its
    #: registry/security preflight - detail carries a bounded reason.
    INVALID_OUTPUT = "invalid_output"
    #: A structurally valid "execute" decision that intelligence.
    #: grounding.ground_decision() could not attribute to the live
    #: request - detail carries one of UngroundedReason's bounded
    #: values (Phase 92, Batch 1). No preflight, approval, execution,
    #: or verification of any kind is ever attempted for this outcome.
    UNGROUNDED_SELECTION = "ungrounded_selection"


@dataclass(frozen=True, slots=True)
class StructuredPlanStep:
    """One executable step of a Batch 2 StructuredPlan.

    Batch 2 ever produces at most one of these - there is no loop, and
    no mechanism to construct more than one step.

    Attributes:
        step_number: Always 1 in Batch 2.
        description: The capability's own user-facing description.
        capability_id: The selected capability.
        tool_name: The real, registered ToolRegistry name to execute.
        arguments: The already-validated, freshly-built tool input.
        security_tier: The real tier SecurityManager.classify_action()
            returned during preflight - a recorded fact, never a guess.
    """

    step_number: int
    description: str
    capability_id: CapabilityId
    tool_name: str
    arguments: dict[str, object]
    security_tier: SecurityTier


@dataclass(frozen=True, slots=True)
class StructuredPlan:
    """A Batch 2 executable plan: at most one step.

    Attributes:
        goal: The verbatim natural request text (never an AI-derived
            paraphrase).
        context_ids_supplied: The real ContextItem.context_id values
            that were supplied to the planning prompt for this request
            - populated directly from the real AssembledContext, never
            parsed from prompt text or model output, and never implying
            the model actually "used" any particular item.
        steps: Exactly one StructuredPlanStep.
    """

    goal: str
    context_ids_supplied: tuple[str, ...]
    steps: tuple[StructuredPlanStep, ...]


@dataclass(frozen=True, slots=True)
class PlanningOutcome:
    """The result of a single select_tool() call.

    Attributes:
        kind: Which distinct outcome occurred.
        plan: Set only when kind is EXECUTABLE - a flat, single-step
            StructuredPlan for the caller to run directly through
            ToolExecutor.
        workflow_plan: Set only when kind is EXECUTABLE_WORKFLOW - a
            real, exactly-two-step planner.plan_models.Plan for the
            caller to run through WorkflowEngine.
        detail: A short, bounded, non-sensitive reason, set when kind
            is INVALID_OUTPUT (a raw ToolSelectionParseError.reason or
            preflight-mismatch string) or UNGROUNDED_SELECTION (one of
            UngroundedReason's bounded values) - never the raw model
            output, the live request, a candidate argument span, or a
            rejected value.
    """

    kind: PlanningOutcomeKind
    plan: StructuredPlan | None = None
    workflow_plan: Plan | None = None
    detail: str | None = None


def select_tool(
    *,
    request_text: str,
    assembled_context: AssembledContext,
    router: AIRouter,
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    session_id: int | None = None,
    catalog: Mapping[CapabilityId, CapabilityAdapter] | None = None,
) -> PlanningOutcome:
    """Ask the model to select a capability, then deterministically
    validate and preflight its response.

    Callers must already have confirmed AI reasoning is enabled (a
    real AIRouter instance exists at all) before calling this function
    - that is a distinct, prior gate this function does not itself
    perform, mirroring how AIReasoningEngine.is_active() also checks
    enablement before ever consulting its own router.

    Args:
        request_text: The live request text (already stripped of the
            "ask jarvis to:" prefix and surrounding whitespace).
        assembled_context: The already-assembled Batch 1 context for
            this request (unchanged - built by the same
            ContextAssembler.assemble() Batch 1 already uses).
        router: The real, already-constructed AIRouter to call
            directly (never a second instance).
        tool_registry: Used only for has_tool()/get_tool() during
            preflight - never to execute anything.
        security_manager: Used only for classify_action() during
            preflight - never to approve or execute anything.
        session_id: Optional session identifier for the audit trail.
        catalog: The capability catalog to validate against. Defaults
            to the real, production CAPABILITY_CATALOG; production
            callers should never override this - it exists as a
            parameter only so tests can exercise a forced-YELLOW/RED
            preflight scenario with a substitute catalog entry, mirroring
            this codebase's own established "parameter exists only for
            test use" convention (e.g. ai/memory_selection.py's own
            selection-limit parameters).

    Returns:
        A PlanningOutcome describing exactly what happened - never a
        collapsed, ambiguous result.
    """
    active_catalog = catalog if catalog is not None else CAPABILITY_CATALOG

    if not router.is_available():
        return PlanningOutcome(kind=PlanningOutcomeKind.PROVIDER_UNAVAILABLE)

    context_block = build_ai_context_block(assembled_context)

    try:
        response = router.route(
            system_instruction=_TRUSTED_PLANNING_INSTRUCTION,
            user_message=request_text,
            context=context_block,
            session_id=session_id,
        )
    except (AIProviderError, ResponseValidationError):
        return PlanningOutcome(kind=PlanningOutcomeKind.PROVIDER_FAILED)

    try:
        parsed = parse_tool_selection(response.text, active_catalog)
    except ToolSelectionParseError as exc:
        return PlanningOutcome(
            kind=PlanningOutcomeKind.INVALID_OUTPUT, detail=exc.reason
        )

    if parsed.decision is ToolSelectionDecision.UNSUPPORTED:
        return PlanningOutcome(kind=PlanningOutcomeKind.UNSUPPORTED)

    assert parsed.capability_id is not None  # guaranteed for EXECUTE
    adapter = active_catalog[parsed.capability_id]

    # Phase 92, Batch 1: the deterministic, deny-only grounding gate
    # runs after parsing/argument validation and before any preflight,
    # approval, execution, or verification - see intelligence/
    # grounding.py's own module docstring for the full contract. This
    # can only refuse an otherwise-proceeding decision; it never makes
    # an invalid one valid, never touches SecurityManager/ApprovalManager/
    # ToolExecutor, and consults only request_text and the already-
    # validated arguments - never AssembledContext or any other
    # retrieved/assembled content.
    grounding = ground_decision(
        request_text=request_text,
        capability_id=parsed.capability_id,
        arguments=parsed.arguments,
    )
    if not grounding.grounded:
        assert grounding.reason is not None  # guaranteed when not grounded
        return PlanningOutcome(
            kind=PlanningOutcomeKind.UNGROUNDED_SELECTION,
            detail=grounding.reason.value,
        )

    preflight = _preflight_capability(
        adapter,
        arguments=parsed.arguments,
        tool_registry=tool_registry,
        security_manager=security_manager,
        session_id=session_id,
    )
    if isinstance(preflight, str):
        return PlanningOutcome(kind=PlanningOutcomeKind.INVALID_OUTPUT, detail=preflight)
    tool_input, preflight_decision = preflight

    if adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW:
        workflow_outcome = _build_update_focus_workflow_plan(
            request_text,
            tool_input=tool_input,
            write_adapter=adapter,
            write_tier=preflight_decision.tier,
            tool_registry=tool_registry,
            security_manager=security_manager,
            session_id=session_id,
            catalog=active_catalog,
        )
        if isinstance(workflow_outcome, str):
            return PlanningOutcome(
                kind=PlanningOutcomeKind.INVALID_OUTPUT, detail=workflow_outcome
            )
        return PlanningOutcome(
            kind=PlanningOutcomeKind.EXECUTABLE_WORKFLOW, workflow_plan=workflow_outcome
        )

    step = StructuredPlanStep(
        step_number=1,
        description=adapter.description,
        capability_id=adapter.capability_id,
        tool_name=adapter.tool_name,
        arguments=tool_input,
        security_tier=preflight_decision.tier,
    )
    plan = StructuredPlan(
        goal=request_text,
        context_ids_supplied=tuple(
            item.context_id for item in assembled_context.items
        ),
        steps=(step,),
    )
    return PlanningOutcome(kind=PlanningOutcomeKind.EXECUTABLE, plan=plan)


def _preflight_capability(
    adapter: CapabilityAdapter,
    *,
    arguments: dict[str, object],
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    session_id: int | None,
) -> tuple[dict[str, object], SecurityDecision] | str:
    """Resolve, build input for, and preflight-classify one capability.

    Shared by every capability this module ever preflights (the
    directly-executed SINGLE_TOOL capability, and each step of the
    TWO_STEP_WORKFLOW capability) - a single, reused implementation
    rather than one copy per capability.

    Args:
        adapter: The capability's catalog entry.
        arguments: The already-validated arguments to build tool input
            from (empty for a capability that declares none).
        tool_registry: Used only for has_tool()/get_tool().
        security_manager: Used only for classify_action().
        session_id: Optional session identifier, forwarded only into
            the preflight ToolRequest - never executed.

    Returns:
        A tuple of (tool_input, preflight_decision) on success, where
        preflight_decision.tier exactly matches
        adapter.max_execution_tier. A short, bounded reason string on
        any failure (unregistered tool, or a tier mismatch in either
        direction) - never an exception, since this is an expected,
        describable outcome, not a programming error.
    """
    if not tool_registry.has_tool(adapter.tool_name):
        return "the selected capability's tool is no longer registered"

    tool = tool_registry.get_tool(adapter.tool_name)
    assert tool is not None  # guaranteed by has_tool() above

    tool_input = build_tool_input(adapter, arguments)
    preflight_request = ToolRequest(
        tool_name=adapter.tool_name, input_data=tool_input, session_id=session_id
    )
    action = tool.action_for(preflight_request)
    preflight_decision = security_manager.classify_action(action)

    if preflight_decision.tier is not adapter.max_execution_tier:
        return (
            "the selected capability's real security classification "
            f"({preflight_decision.tier.value}) does not match what is "
            f"required ({adapter.max_execution_tier.value}) - refusing as "
            "a safety mismatch"
        )

    return tool_input, preflight_decision


def _build_update_focus_workflow_plan(
    request_text: str,
    *,
    tool_input: dict[str, object],
    write_adapter: CapabilityAdapter,
    write_tier: SecurityTier,
    tool_registry: ToolRegistry,
    security_manager: SecurityManager,
    session_id: int | None,
    catalog: Mapping[CapabilityId, CapabilityAdapter],
) -> Plan | str:
    """Deterministically construct the fixed, exactly-two-step Plan for
    the update-focus-and-verify workflow (Batch 3).

    The AI never selects, orders, or configures the verifier step: this
    function always pairs PROJECT_STATE_UPDATE_FOCUS with the fixed
    internal PROJECT_STATE_VERIFY_FOCUS capability, in this fixed order,
    with no model-controlled data in step 2's input.

    Args:
        request_text: The verbatim natural request (becomes Plan.user_request).
        tool_input: The write step's already-validated, already-built
            tool input (``{"field": "focus", "value": ...}``).
        write_adapter: PROJECT_STATE_UPDATE_FOCUS's catalog entry.
        write_tier: The write step's real, already-confirmed preflight
            tier (always YELLOW, per _preflight_capability's own check).
        tool_registry: Used only for has_tool()/get_tool() for the
            verifier capability.
        security_manager: Used only for classify_action() for the
            verifier capability.
        session_id: Optional session identifier for the preflight
            ToolRequest only.
        catalog: The capability catalog to resolve the fixed verifier
            capability from.

    Returns:
        A real, two-step Plan ready for WorkflowEngine.run(), or a
        short, bounded failure reason string if the internal verifier
        capability itself fails its own preflight (an internal
        configuration problem, never exposed as if it were the user's
        own mistake).
    """
    verify_adapter = catalog.get(CapabilityId.PROJECT_STATE_VERIFY_FOCUS)
    if verify_adapter is None:
        return "the internal verification capability is not configured"

    verify_preflight = _preflight_capability(
        verify_adapter,
        arguments={},
        tool_registry=tool_registry,
        security_manager=security_manager,
        session_id=session_id,
    )
    if isinstance(verify_preflight, str):
        return f"internal verification capability preflight failed: {verify_preflight}"
    verify_tool_input, verify_decision = verify_preflight

    write_tool = tool_registry.get_tool(write_adapter.tool_name)
    assert write_tool is not None  # guaranteed by the caller's own preflight
    write_action = write_tool.action_for(
        ToolRequest(
            tool_name=write_adapter.tool_name,
            input_data=tool_input,
            session_id=session_id,
        )
    )
    write_reason = security_manager.classify_action(write_action).reason

    verify_tool = tool_registry.get_tool(verify_adapter.tool_name)
    assert verify_tool is not None
    verify_action = verify_tool.action_for(
        ToolRequest(
            tool_name=verify_adapter.tool_name,
            input_data=verify_tool_input,
            session_id=session_id,
        )
    )

    steps = (
        PlanStep(
            number=1,
            description=write_adapter.description,
            action=write_action,
            tier=write_tier,
            reason=write_reason,
            tool_name=write_adapter.tool_name,
            tool_input=tool_input,
        ),
        PlanStep(
            number=2,
            description=verify_adapter.description,
            action=verify_action,
            tier=verify_decision.tier,
            reason=verify_decision.reason,
            tool_name=verify_adapter.tool_name,
            tool_input=verify_tool_input,
        ),
    )
    return Plan(user_request=request_text, steps=steps)
