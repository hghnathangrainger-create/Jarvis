"""
reasoning_models.py

Data models for AI-assisted reasoning in the Jarvis AI Operating System
(Phase 4, Batch 1).

These are the provider-neutral, immutable data structures that describe what
the AI reasoning layer is *asked* and what it *suggests*. They deliberately
carry advice only: a summary, and a list of suggested actions with a suggested
risk tier. Nothing here can execute anything.

Responsibilities:
    - Define AIReasoningRequest: the input to the reasoning engine.
    - Define AISuggestedAction: a single advisory step the AI proposes.
    - Define AIReasoningResult: the advisory result the engine returns.

Does NOT:
    - Execute tools, call providers, or touch the Security Manager, Tool
      Executor, or Approval Manager. These are plain data classes.

Design note:
    The suggested tier on an AISuggestedAction is ADVISORY ONLY. It is a hint
    about how the AI *thinks* an action might be classified. The real security
    classification is always made by the SecurityManager, and the real
    execution gate is always the ToolExecutor. Nothing in this module is
    authoritative over either.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AIReasoningRequest:
    """A request for the AI to reason about a user's input.

    Attributes:
        user_input: The user's original request text.
        context: Optional short context to help the AI reason (for example, a
            note about available tools). Purely informational.
        session_id: Optional session identifier for the audit trail.
    """

    user_input: str
    context: str = ""
    session_id: int | None = None


@dataclass(frozen=True, slots=True)
class AISuggestedAction:
    """A single action the AI suggests as part of a plan. Advisory only.

    Attributes:
        description: A human-readable description of the suggested step.
        suggested_tier: The AI's *hint* about the risk tier ("GREEN",
            "YELLOW", or "RED"). This is advisory only and is never used to
            decide whether anything runs; the SecurityManager remains the sole
            authority on classification.
    """

    description: str
    suggested_tier: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AIReasoningResult:
    """The advisory result returned by the AI reasoning engine.

    Attributes:
        summary: A short, plain-language summary of what the AI understood the
            request to mean.
        suggested_actions: An ordered list of advisory steps the AI proposes.
            May be empty.
        raw_text: The raw text the provider returned, kept for transparency and
            debugging. May be empty.
        provider_name: The name of the provider that produced the result, or
            "none" if produced without a live provider.
    """

    summary: str
    suggested_actions: tuple[AISuggestedAction, ...] = field(default_factory=tuple)
    raw_text: str = ""
    provider_name: str = "none"

    @property
    def has_suggestions(self) -> bool:
        """Return whether the result contains any suggested actions.

        Returns:
            True if there is at least one suggested action, False otherwise.
        """
        return len(self.suggested_actions) > 0