"""
workflow_plan_factory.py

Deterministic Plan construction for the two approved Phase 15 fixed
workflow commands (Batch 3: Deterministic Workflow Commands and
Planner/Orchestrator Wiring):

    remember this and show it back: <text>
    remember this and forget it: <text>

Responsibilities:
    - Build an exact, fixed, two-step Plan for each of the two approved
      workflow commands, using only already-registered tool names
      ("memory", "memory_forget") and the exact input shapes those tools
      already require.

Does NOT:
    - Parse general natural language, or accept any tool name/argument
      derived from user input beyond the free-text content to remember.
    - Call AIReasoningEngine, Planner.create_plan(), SecurityManager,
      ToolExecutor, or ToolRegistry. This module has none of those
      dependencies.
    - Execute anything, or create an approval request.
    - Access the result of any step. WorkflowEngine (Phase 15, Batch 2)
      owns the runtime previous-step propagation seam entirely; this
      factory only ever marks step 2's input_from_previous_step=True and
      never inspects or guesses what step 1 will actually produce.

This is a narrow, fixed-shape factory - not a general Plan-building
framework. It creates Plans only for the two workflow types named above,
each always exactly two steps, in a fixed order, using fixed tool names.
"""

from __future__ import annotations

from config.constants import SecurityTier
from planner.plan_models import Plan, PlanStep

_MEMORY_TOOL_NAME = "memory"
_MEMORY_FORGET_TOOL_NAME = "memory_forget"

#: Display-only classification metadata, reused here only for PlanStep.tier
#: transparency (matching planner.planner.Planner._classify's own existing
#: use of SecurityManager.classify_action() for the same display purpose).
#: These are the exact, already-established, unconditional classifications
#: security.security_manager's own rule table already assigns to these
#: exact action strings ("save memory" -> GREEN, "show memory" -> GREEN,
#: "forget memory" -> YELLOW) - confirmed by direct inspection, not
#: guessed. This module never imports or calls SecurityManager itself:
#: PlanStep.tier remains non-authoritative metadata regardless, and
#: ToolExecutor re-classifies the real action fresh, at execution time,
#: every time - this is true whether or not these values are populated at
#: all.
_SAVE_TIER = SecurityTier.GREEN
_SAVE_REASON = "Saving a memory the user explicitly asked to store is safe."
_SHOW_TIER = SecurityTier.GREEN
_SHOW_REASON = "Showing information is read-only and safe."
_FORGET_TIER = SecurityTier.YELLOW
_FORGET_REASON = "Forgetting a memory removes it and must be confirmed."


def build_remember_and_show_plan(content: str) -> Plan:
    """Build the fixed, two-step Plan for "remember this and show it back".

    Step 1 saves `content` as a new memory. Step 2 shows the memory just
    saved - its input_from_previous_step=True marks that its "memory_id"
    input must come from step 1's own result; this factory never computes,
    guesses, or reads that value itself.

    Args:
        content: The raw, unvalidated free text to remember. Emptiness is
            not checked here - the underlying memory tool already rejects
            empty content honestly at execution time.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Save this as a new memory.",
        action="save memory",
        tier=_SAVE_TIER,
        reason=_SAVE_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "save", "content": content},
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Show the memory that was just saved.",
        action="show memory",
        tier=_SHOW_TIER,
        reason=_SHOW_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "get"},
        input_from_previous_step=True,
    )
    return Plan(
        user_request=f"remember this and show it back: {content}",
        steps=(step_1, step_2),
    )


def build_remember_and_forget_plan(content: str) -> Plan:
    """Build the fixed, two-step Plan for "remember this and forget it".

    Step 1 saves `content` as a new memory. Step 2 forgets the memory
    just saved - its input_from_previous_step=True marks that its
    "memory_id" input must come from step 1's own result; this factory
    never computes, guesses, or reads that value itself, and never
    creates an approval request (WorkflowEngine's existing, unmodified
    pause/ApprovalManager path handles that when step 2 is classified
    YELLOW at execution time).

    Args:
        content: The raw, unvalidated free text to remember.

    Returns:
        A two-step Plan ready for WorkflowEngine.run().
    """
    step_1 = PlanStep(
        number=1,
        description="Save this as a new memory.",
        action="save memory",
        tier=_SAVE_TIER,
        reason=_SAVE_REASON,
        tool_name=_MEMORY_TOOL_NAME,
        tool_input={"operation": "save", "content": content},
        input_from_previous_step=False,
    )
    step_2 = PlanStep(
        number=2,
        description="Forget the memory that was just saved.",
        action="forget memory",
        tier=_FORGET_TIER,
        reason=_FORGET_REASON,
        tool_name=_MEMORY_FORGET_TOOL_NAME,
        tool_input={},
        input_from_previous_step=True,
    )
    return Plan(
        user_request=f"remember this and forget it: {content}",
        steps=(step_1, step_2),
    )
