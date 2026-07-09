"""
plan_models.py

Data structures for plans in the Jarvis AI Operating System.

Responsibilities:
    - Define the PlanStep dataclass: a single planned action with its security
      classification.
    - Define the Plan dataclass: an ordered collection of steps produced from a
      user request, with convenience flags describing the plan as a whole.

Does NOT:
    - Create plans (see planner.py).
    - Execute plans or perform any action.
    - Classify security tiers (that is delegated to the Security Manager).

These models are pure data. They describe the shape of a plan and offer simple
derived properties, but contain no planning, execution, or security logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config.constants import SecurityTier


@dataclass(frozen=True, slots=True)
class PlanStep:
    """A single planned action and its security classification.

    Attributes:
        number: The 1-based position of this step within its plan.
        description: A short, human-readable description of what the step does.
        action: The action string that was classified by the Security Manager.
        tier: The security tier assigned to the step (GREEN, YELLOW, or RED).
            This is display/transparency metadata only, produced once at
            planning time - it is never authoritative for execution. Any
            future executable-workflow code (Phase 15, Batch 2) must
            re-classify a step's actual tool action via
            SecurityManager.classify_action() at the moment it runs, exactly
            as ToolExecutor already does today for every single-step
            request; it must never branch on this field.
        reason: The Security Manager's explanation for the assigned tier.
        tool_name: The name of the registered tool this step calls, if this
            step represents an executable workflow step (Phase 15). None for
            every existing Phase 1-14 single-step plan, which continues to
            resolve its tool separately via CommandRouter.match(), exactly as
            before. This field is plain, unvalidated data: it is never
            checked against ToolRegistry and never used to derive a security
            tier here - tool availability and classification are execution-
            time concerns owned by later code (ToolExecutor / a future
            WorkflowEngine), not by this immutable model.
        tool_input: The input this step's tool call should run with, if
            tool_name is set. Empty for every existing Phase 1-14 plan. A
            plain, unvalidated mapping - the same shape as
            tools.base_tool.ToolRequest.input_data - with no schema,
            template language, or expression support.
        input_from_previous_step: Declares only the intent that this step's
            execution input is derived from the immediately preceding
            completed step's result, according to a rule a future
            WorkflowEngine (Phase 15, Batch 2) applies at execution time.
            False for every existing Phase 1-14 plan and for any step with
            no such dependency.

            This field is declarative only. It does not name a variable,
            does not identify a source field, and does not itself move any
            data. Explicit limitations, by design:
                - refers only to the immediately previous step, never an
                  arbitrary earlier one;
                - has no dependency-graph semantics (Plan.steps' own tuple
                  order remains the sole ordering authority);
                - defines no transformation, template, or expression
                  language (no "${step1.result}"-style reference exists
                  anywhere in this model);
                - is never interpreted or populated by an AI - only
                  deterministic, code-owned logic in a future WorkflowEngine
                  may act on it.
    """

    number: int
    description: str
    action: str
    tier: SecurityTier
    reason: str
    tool_name: str | None = None
    tool_input: dict[str, object] = field(default_factory=dict)
    input_from_previous_step: bool = False

    @property
    def is_blocked(self) -> bool:
        """Whether this step is blocked by default.

        Returns:
            True only for RED steps.
        """
        return self.tier is SecurityTier.RED

    @property
    def requires_confirmation(self) -> bool:
        """Whether this step requires user confirmation before proceeding.

        Returns:
            True only for YELLOW steps.
        """
        return self.tier is SecurityTier.YELLOW


@dataclass(frozen=True, slots=True)
class Plan:
    """An ordered set of planned steps produced from a single user request.

    Attributes:
        user_request: The original, unmodified request the plan was built from.
        steps: The ordered steps that make up the plan.
    """

    user_request: str
    steps: tuple[PlanStep, ...] = field(default_factory=tuple)

    @property
    def requires_confirmation(self) -> bool:
        """Whether any step in the plan requires user confirmation.

        Returns:
            True if at least one step is YELLOW.
        """
        return any(step.requires_confirmation for step in self.steps)

    @property
    def has_blocked_steps(self) -> bool:
        """Whether the plan contains any blocked (RED) steps.

        Returns:
            True if at least one step is RED.
        """
        return any(step.is_blocked for step in self.steps)

    @property
    def is_empty(self) -> bool:
        """Whether the plan contains no steps.

        Returns:
            True if the plan has no steps.
        """
        return len(self.steps) == 0

    @property
    def highest_tier(self) -> SecurityTier:
        """The most severe security tier present in the plan.

        RED is the most severe, then YELLOW, then GREEN. An empty plan is
        treated as GREEN.

        Returns:
            The most severe SecurityTier among the plan's steps.
        """
        if self.has_blocked_steps:
            return SecurityTier.RED
        if self.requires_confirmation:
            return SecurityTier.YELLOW
        return SecurityTier.GREEN