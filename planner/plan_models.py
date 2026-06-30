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
        reason: The Security Manager's explanation for the assigned tier.
    """

    number: int
    description: str
    action: str
    tier: SecurityTier
    reason: str

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