"""
planner.py

Rule-based planning for the Jarvis AI Operating System (Phase 1).

Responsibilities:
    - Turn a user request string into a simple, structured Plan.
    - Derive one or more planned actions from the request using straightforward
      rules (no AI calls in Phase 1).
    - Delegate the security classification of every step to the existing
      Security Manager, so the Planner never decides tiers itself.

Does NOT:
    - Execute any step or perform any action.
    - Call the Claude API or any AI provider.
    - Connect to the Workflow Engine.
    - Classify security tiers directly (that is the Security Manager's job).

The Planner is the strategic layer: it decides what should happen. It does not
make it happen. Keeping the Planner free of execution and of its own security
rules keeps it simple, predictable, and easy to test.
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager


@dataclass(frozen=True, slots=True)
class _DraftStep:
    """An intermediate step before security classification.

    Attributes:
        description: Human-readable description of the step.
        action: The action string to be classified by the Security Manager.
    """

    description: str
    action: str


# Keyword groups used to recognise the kind of request. These drive only the
# step description and wording; the security tier always comes from the
# Security Manager, never from this table.
_MEMORY_KEYWORDS: tuple[str, ...] = ("memory", "memories", "remember", "recall")
_READ_KEYWORDS: tuple[str, ...] = ("read", "list", "show", "view", "open", "get")
_SEARCH_KEYWORDS: tuple[str, ...] = ("search", "find", "look up", "lookup")
_SUMMARISE_KEYWORDS: tuple[str, ...] = ("summarise", "summarize", "summary")


class Planner:
    """Builds simple structured plans from user requests.

    The Planner is stateless aside from its Security Manager collaborator; a
    single instance can be shared across the application.

    Attributes:
        _security: The Security Manager used to classify every planned step.
    """

    def __init__(self, security_manager: SecurityManager) -> None:
        """Initialise the planner with a Security Manager.

        Args:
            security_manager: The Security Manager used to classify each step.
        """
        self._security = security_manager

    def create_plan(self, user_request: str) -> Plan:
        """Turn a user request into a structured plan.

        The request is interpreted with simple rules to produce one or more
        draft steps. Each draft step is then classified by the Security
        Manager, which assigns its tier and reason. The Planner does not
        execute anything; it only describes what would happen.

        Args:
            user_request: The user's request in natural language.

        Returns:
            A Plan containing the classified steps.

        Raises:
            ValueError: If the request is empty or whitespace-only.
        """
        request = user_request.strip()
        if not request:
            raise ValueError("user_request must not be empty.")

        drafts = self._draft_steps(request)
        steps = tuple(
            self._classify(number, draft)
            for number, draft in enumerate(drafts, start=1)
        )
        return Plan(user_request=request, steps=steps)

    def _draft_steps(self, request: str) -> list[_DraftStep]:
        """Produce draft steps from a request using simple rules.

        Phase 1 planning is intentionally lightweight: most requests map to a
        single draft step whose action mirrors the request. The wording of the
        description is tuned to the recognised request type, but the security
        outcome is determined later by the Security Manager.

        Args:
            request: The stripped user request.

        Returns:
            A non-empty list of draft steps.
        """
        lowered = request.casefold()

        if self._contains(lowered, _SEARCH_KEYWORDS) and self._contains(
            lowered, _MEMORY_KEYWORDS
        ):
            return [
                _DraftStep(
                    description="Search stored memories for the request.",
                    action=request,
                )
            ]

        if self._contains(lowered, _MEMORY_KEYWORDS):
            return [
                _DraftStep(
                    description="Access stored memories for the request.",
                    action=request,
                )
            ]

        if self._contains(lowered, _SUMMARISE_KEYWORDS):
            return [
                _DraftStep(
                    description="Summarise the requested content.",
                    action=request,
                )
            ]

        if self._contains(lowered, _SEARCH_KEYWORDS):
            return [
                _DraftStep(
                    description="Perform the requested search.",
                    action=request,
                )
            ]

        if self._contains(lowered, _READ_KEYWORDS):
            return [
                _DraftStep(
                    description="Retrieve the requested information.",
                    action=request,
                )
            ]

        # Default: a single step that mirrors the request. Its tier is decided
        # by the Security Manager, which applies the cautious YELLOW default to
        # anything it does not recognise.
        return [
            _DraftStep(
                description="Carry out the requested action.",
                action=request,
            )
        ]

    def _classify(self, number: int, draft: _DraftStep) -> PlanStep:
        """Classify a draft step into a fully populated PlanStep.

        Args:
            number: The 1-based position of the step within the plan.
            draft: The draft step to classify.

        Returns:
            A PlanStep with its tier and reason set by the Security Manager.
        """
        decision = self._security.classify_action(draft.action)
        return PlanStep(
            number=number,
            description=draft.description,
            action=draft.action,
            tier=decision.tier,
            reason=decision.reason,
        )

    @staticmethod
    def _contains(text: str, keywords: tuple[str, ...]) -> bool:
        """Report whether any keyword appears in the text.

        Args:
            text: The already-lowercased text to search.
            keywords: The keywords to look for.

        Returns:
            True if any keyword is present, False otherwise.
        """
        return any(keyword in text for keyword in keywords)