"""
ai package

AI support for the Jarvis AI Operating System.

This package holds the provider-neutral AI layer: the provider interface and
concrete providers (under ai.providers), and the advisory reasoning layer added
in Phase 4. The reasoning layer can only suggest and summarise; it never
executes anything. All real actions continue to flow through the Core,
SecurityManager, ToolExecutor, and ApprovalManager.
"""

from ai.reasoning_engine import AIReasoningEngine
from ai.reasoning_models import (
    AIReasoningRequest,
    AIReasoningResult,
    AISuggestedAction,
)

__all__ = [
    "AIReasoningEngine",
    "AIReasoningRequest",
    "AIReasoningResult",
    "AISuggestedAction",
]