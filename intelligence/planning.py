"""
planning.py

Ties Batch 2's Context Intelligence, trusted planning instruction,
strict structured-output parsing, capability catalog, and deterministic
security preflight together into a single, testable function:
select_tool() (Phase 90, Batch 2; contracts fixed by
docs/phase_90_implementation_plan.md, Sections 25/26).

Responsibilities:
    - Own the one fixed, Jarvis-authored trusted planning instruction
      (Section 26.C) - never mixed into memory, ProjectState, or any
      other untrusted ContextItem.
    - Call the real, already-constructed AIRouter.route() directly
      (Section 26.C's own inspection finding: AIReasoningEngine.reason()
      hardcodes one shared system instruction with no field for a
      per-request addition, but AIRouter.route(system_instruction=...)
      already accepts an arbitrary trusted instruction per call,
      without touching any trust-boundary enforcement code).
    - Parse and validate the response via
      intelligence.structured_output.parse_tool_selection().
    - For a valid "execute" decision: resolve the CapabilityAdapter,
      confirm its real tool is still registered, build its
      deterministic tool input, call the real tool's own action_for(),
      classify it through the real SecurityManager, and require GREEN
      before returning an executable StructuredPlan.
    - For a valid "unsupported" decision: return that outcome directly,
      with no plan, no preflight, and no tool involvement of any kind.

Does NOT:
    - Call ToolExecutor.execute() or tool.run() itself. This module
      only ever prepares a StructuredPlan for the caller (the
      orchestrator) to execute through the real, unmodified
      ToolExecutor - exactly the same division of responsibility
      Batch 1 already established between intelligence/context.py
      (assembly) and core/orchestrator.py (execution/response).
    - Create an approval, retry, replan, or touch WorkflowEngine.
    - Modify Batch 1's ContextAssembler, its budgets, or its
      memory-selection algorithm - this module only ever consumes an
      already-assembled AssembledContext, unchanged.
    - Modify ai/reasoning_engine.py, ai/router.py, or
      ai/prompt_builder.py. AIRouter is used exactly as already built,
      through its existing, public route()/is_available() methods.
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
    build_tool_input,
)
from intelligence.context import AssembledContext, build_ai_context_block
from intelligence.structured_output import (
    ToolSelectionDecision,
    ToolSelectionParseError,
    parse_tool_selection,
)
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest
from tools.registry import ToolRegistry

#: The one fixed, Jarvis-authored trusted planning instruction (Section
#: 26.C). Supplied only through AIRouter.route()'s own
#: system_instruction parameter - never mixed into any ContextItem, and
#: never derived from, or influenced by, memory or ProjectState text.
#: Echoes both valid response shapes verbatim, per Section 26.C's own
#: requirement that the trusted instruction include the exact two valid
#: objects.
_TRUSTED_PLANNING_INSTRUCTION = (
    "You are Jarvis's tool-selection planner. Exactly one capability is "
    "available to you: capability id \"project_state_show\", which shows "
    "the current manually-recorded Jarvis project state (branch, phase, "
    "commit, test-suite result, focus). Select it only when showing that "
    "record can satisfy the user's request below. Otherwise, you must "
    "return the exact unsupported object.\n"
    "\n"
    "Respond with exactly one of these two JSON objects, and nothing "
    "else:\n"
    "\n"
    "Execute:\n"
    '{"decision": "execute", "capability_id": "project_state_show", '
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

    #: A valid "execute" decision, GREEN preflight passed - plan is set.
    EXECUTABLE = "executable"
    #: A valid "unsupported" decision - no plan, no tool involvement.
    UNSUPPORTED = "unsupported"
    #: The router's provider reported itself unavailable; route() was
    #: never called.
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    #: route() itself raised (AIProviderError/ResponseValidationError).
    PROVIDER_FAILED = "provider_failed"
    #: Parsing/validation failed, or the selected capability failed its
    #: registry/security preflight - detail carries a bounded reason.
    INVALID_OUTPUT = "invalid_output"


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
        plan: Set only when kind is EXECUTABLE.
        detail: A short, bounded, non-sensitive reason, set only when
            kind is INVALID_OUTPUT - never the raw model output.
    """

    kind: PlanningOutcomeKind
    plan: StructuredPlan | None = None
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

    if not tool_registry.has_tool(adapter.tool_name):
        return PlanningOutcome(
            kind=PlanningOutcomeKind.INVALID_OUTPUT,
            detail="the selected capability's tool is no longer registered",
        )

    tool = tool_registry.get_tool(adapter.tool_name)
    assert tool is not None  # guaranteed by has_tool() above

    tool_input = build_tool_input(adapter, parsed.arguments)
    preflight_request = ToolRequest(
        tool_name=adapter.tool_name, input_data=tool_input, session_id=session_id
    )
    action = tool.action_for(preflight_request)
    preflight_decision = security_manager.classify_action(action)

    if preflight_decision.tier is not SecurityTier.GREEN:
        return PlanningOutcome(
            kind=PlanningOutcomeKind.INVALID_OUTPUT,
            detail=(
                "the selected capability is not GREEN and cannot run "
                "without approval"
            ),
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
