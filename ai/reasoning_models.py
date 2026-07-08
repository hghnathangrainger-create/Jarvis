"""
reasoning_models.py

Data models for AI-assisted reasoning in the Jarvis AI Operating System
(Phase 4, Batch 1; context_block replaces the raw context string since
Phase 8, Batch 1).

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
    - Decide trust or provenance for any context supplied. Since Phase 8,
      Batch 1, a caller must supply an already-constructed, already
      trust-tagged AIContextBlock (see ai/context_models.py) - this module
      never accepts a bare string for context, so trust and provenance
      cannot be decided here, or drift apart from each other, by anything
      downstream.

Design note:
    The suggested tier on an AISuggestedAction is ADVISORY ONLY. It is a hint
    about how the AI *thinks* an action might be classified. The real security
    classification is always made by the SecurityManager, and the real
    execution gate is always the ToolExecutor. Nothing in this module is
    authoritative over either.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ai.context_models import AIContextBlock


@dataclass(frozen=True, slots=True)
class AIReasoningRequest:
    """A request for the AI to reason about a user's input.

    Attributes:
        user_input: The user's original request text.
        context_block: Optional, already-constructed, already trust-tagged
            context to help the AI reason (for example, ingested file
            content - see ai/file_ingestion.py). Trust and provenance travel
            together on this object; AIReasoningEngine forwards it unchanged
            and never reconstructs or relabels it. Replaces a previous raw
            `context: str` field (Phase 8, Batch 1) that let a caller supply
            text with no attached trust origin, forcing AIReasoningEngine to
            guess one - it guessed the same, increasingly inaccurate label
            for every caller, which is exactly the defect this field closes.
        session_id: Optional session identifier for the audit trail.
    """

    user_input: str
    context_block: AIContextBlock | None = None
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