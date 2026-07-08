"""
reasoning_engine.py

The AI reasoning engine for the Jarvis AI Operating System (Phase 4, Batch 1;
routed through AIRouter since Phase 7, Batch 2).

The engine turns a user's request into an *advisory* AIReasoningResult: a short
summary and a list of suggested actions. It is deliberately powerless: it holds
no reference to the ToolExecutor, ToolRegistry, ApprovalManager, or
SecurityManager, so it cannot run a tool, approve an action, or change a
classification. It can only produce advice for the Core to attach to a response.

Responsibilities:
    - When enabled and a usable AIRouter is available, ask the router to
      reason about a request and parse the reply into an AIReasoningResult.
    - When disabled, or when no router is available, return None so Jarvis
      behaves exactly as it did before AI reasoning existed.
    - Never raise into the caller: any routing or provider failure results in
      None.

Does NOT:
    - Execute tools or actions of any kind.
    - Bypass, replace, or influence the SecurityManager, ToolExecutor, or
      ApprovalManager. Its output is advice, never a decision.
    - Require an API key or credits unless AI reasoning is explicitly enabled
      and a live router is supplied.
    - Construct an AIRequest/AIMessage directly, or call any AIProvider
      directly. Every AI call goes through AIRouter.route(), which is the
      only path in the codebase permitted to build a prompt (Phase 7,
      Batch 2) - this is what makes the router's prompt-injection defence
      apply to this engine's calls too.
    - Construct, reconstruct, or relabel an AIContextBlock (Phase 8, Batch 1).
      A request's context_block, if supplied, was already built - with its
      trust and provenance already attached - by whoever legitimately
      produced it (for example, ai/file_ingestion.py). This engine only ever
      forwards that object, unchanged, to AIRouter.route(); it never guesses
      or hardcodes a source label for content it did not itself originate.

Safety design:
    The single most important property of this class is that it *cannot act*.
    "The AI cannot execute a tool" is not enforced by a check that might be
    bypassed; it is true by construction, because the engine is never given
    anything capable of execution.
"""

from __future__ import annotations

from ai.providers.base import AIProviderError
from ai.reasoning_models import (
    AIReasoningRequest,
    AIReasoningResult,
    AISuggestedAction,
)
from ai.response_validator import ResponseValidationError
from ai.router import AIRouter

#: The system instruction framing the AI as an advisor that never executes.
_SYSTEM_INSTRUCTION = (
    "You are the reasoning assistant inside Jarvis, a personal AI operating "
    "system. Your job is to help interpret the user's request: briefly explain "
    "what they seem to want, and suggest a short plan of steps. You do NOT run "
    "anything and you have no ability to act. Every real action is decided and "
    "executed by Jarvis's own security and approval systems, not by you. "
    "Respond with a short summary line, then optionally a few numbered steps."
)


class AIReasoningEngine:
    """Produces advisory reasoning results. It cannot execute anything.

    Attributes:
        enabled: Whether AI reasoning is switched on. When False, the engine
            always returns None and no router is ever called.
    """

    def __init__(
        self,
        *,
        router: AIRouter | None = None,
        enabled: bool = False,
        model: str = "",
        max_tokens: int = 1024,
    ) -> None:
        """Initialise the reasoning engine.

        Args:
            router: The AIRouter to route reasoning calls through when
                enabled. May be None, in which case the engine behaves as if
                disabled. Every AI call this engine makes goes through
                router.route() - it never constructs a provider request
                itself and never holds a provider reference directly.
            enabled: Whether AI reasoning is switched on.
            model: Unused by routing (the AIRouter selects the model from its
                own configured Settings); retained only so existing callers
                that pass a model identifier do not need to change. Kept for
                interface stability, not consulted by reason().
            max_tokens: Unused by routing, for the same reason as model.
        """
        self._router = router
        self.enabled = enabled
        self._model = model
        self._max_tokens = max_tokens

    def is_active(self) -> bool:
        """Report whether the engine will actually produce reasoning.

        The engine is active only when it is enabled, has a router, and that
        router's provider reports itself available. When inactive, reason()
        returns None.

        Returns:
            True if a reasoning call would be attempted, False otherwise.
        """
        if not self.enabled or self._router is None:
            return False
        try:
            return self._router.is_available()
        except Exception:  # noqa: BLE001 - availability checks must never raise out
            return False

    def reason(self, request: AIReasoningRequest) -> AIReasoningResult | None:
        """Produce an advisory reasoning result for a request.

        This never raises into the caller and never executes anything. If the
        engine is inactive, or the router/provider fails for any reason, None
        is returned and Jarvis continues exactly as it would without AI
        reasoning.

        Args:
            request: The reasoning request describing the user's input.

        Returns:
            An advisory AIReasoningResult, or None when reasoning is
            unavailable, or when the provider's response was empty or
            otherwise failed validation.
        """
        if not self.is_active():
            return None

        assert self._router is not None  # guaranteed by is_active()

        try:
            response = self._router.route(
                system_instruction=_SYSTEM_INSTRUCTION,
                user_message=self._build_prompt(request),
                # Forwarded exactly as supplied - see Does NOT above. This
                # engine never constructs, reconstructs, or relabels an
                # AIContextBlock; trust and provenance were already decided,
                # together, by whoever built request.context_block.
                context=request.context_block,
                session_id=request.session_id,
            )
        except (AIProviderError, ResponseValidationError):
            return None
        except Exception:  # noqa: BLE001 - any routing failure degrades to None
            return None

        return self._parse(response.text, response.provider)

    @staticmethod
    def _build_prompt(request: AIReasoningRequest) -> str:
        """Build the user-message text sent through the router.

        Args:
            request: The reasoning request.

        Returns:
            The prompt string.
        """
        parts = [
            f"User request: {request.user_input}",
            "Briefly summarise what they want, then suggest a short plan.",
        ]
        return "\n".join(parts)

    @staticmethod
    def _parse(text: str, provider_name: str) -> AIReasoningResult:
        """Parse raw provider text into an advisory reasoning result.

        The parsing is intentionally simple and forgiving: the first non-empty
        line is treated as the summary, and any subsequent non-empty lines are
        treated as suggested steps. No tier is inferred here; suggested actions
        default to an advisory "UNKNOWN" tier because classification belongs to
        the SecurityManager, not to the AI.

        Args:
            text: The raw text returned by the provider.
            provider_name: The name of the provider that produced the text.

        Returns:
            An AIReasoningResult built from the text.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return AIReasoningResult(
                summary="(The assistant did not return a suggestion.)",
                raw_text=text,
                provider_name=provider_name,
            )

        summary = lines[0]
        actions = tuple(
            AISuggestedAction(description=line) for line in lines[1:]
        )
        return AIReasoningResult(
            summary=summary,
            suggested_actions=actions,
            raw_text=text,
            provider_name=provider_name,
        )