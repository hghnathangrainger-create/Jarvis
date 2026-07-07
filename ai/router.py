"""
router.py

AI request routing for the Jarvis AI Operating System.

Responsibilities:
    - Accept a request for AI assistance and route it to a provider.
    - In Phase 1, always route to the Claude provider.
    - Build the structured prompt, invoke the provider, validate the response,
      and log every call through Observability.

Does NOT:
    - Implement memory, planning, workflow, or tool logic.
    - Decide what the prompt should contain; callers supply the system
      instruction, user message, and optional context.

The router is the single entry point through which the rest of Jarvis obtains
AI completions. Routing every call through one place is what makes
observability, cost tracking, and future multi-provider routing possible
without changing any caller.
"""

from __future__ import annotations

import time

from ai.context_models import AIContextBlock
from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIResponse
from ai.response_validator import ResponseValidationError, ResponseValidator
from config.constants import EventOutcome
from config.settings import Settings
from observability.logger import EventLogger

_SOURCE = "ai_router"
_ACTION_TYPE = "ai_call"


class AIRouter:
    """Routes AI requests to a provider and logs every call.

    In Phase 1 the routing policy is intentionally simple: every request is
    sent to the single configured Claude provider. The interface is designed
    so that multi-provider routing can be added later without changing callers.

    Attributes:
        _provider: The provider all requests are routed to in Phase 1.
        _prompt_builder: Builds structured prompts from request components.
        _validator: Validates provider responses.
        _logger: Emits a structured event for every AI call.
        _settings: Application settings supplying the model and token limit.
    """

    def __init__(
        self,
        *,
        provider: AIProvider,
        prompt_builder: PromptBuilder,
        validator: ResponseValidator,
        logger: EventLogger,
        settings: Settings,
    ) -> None:
        """Initialise the router with its collaborators.

        Args:
            provider: The AI provider to route requests to.
            prompt_builder: The builder used to assemble structured prompts.
            validator: The validator used to check responses.
            logger: The event logger used to record every AI call.
            settings: Application settings supplying default model and tokens.
        """
        self._provider = provider
        self._prompt_builder = prompt_builder
        self._validator = validator
        self._logger = logger
        self._settings = settings

    def route(
        self,
        *,
        system_instruction: str,
        user_message: str,
        context: AIContextBlock | None = None,
        session_id: int | None = None,
    ) -> AIResponse:
        """Route a request to the provider and return a validated response.

        This builds the prompt, sends it to the provider, validates the
        result, and logs the outcome through Observability. Both success and
        failure are recorded.

        Args:
            system_instruction: The trusted instruction framing the model.
            user_message: The user's request.
            context: Optional typed context block (see ai/context_models.py).
                Its trust origin determines how PromptBuilder frames it.
                Defaults to None.
            session_id: Optional session identifier for the audit trail.
                Defaults to None.

        Returns:
            A validated, provider-neutral AIResponse.

        Raises:
            AIProviderError: If the provider fails to produce a response.
            ResponseValidationError: If the response fails validation.
        """
        request = self._prompt_builder.build(
            system_instruction=system_instruction,
            user_message=user_message,
            model=self._settings.ai_model,
            max_tokens=self._settings.ai_max_tokens,
            context=context,
        )

        start = time.monotonic()
        try:
            response = self._provider.generate(request)
            validated = self._validator.validate(response)
        except (AIProviderError, ResponseValidationError) as exc:
            duration_ms = self._elapsed_ms(start)
            self._logger.emit(
                source=_SOURCE,
                action_type=_ACTION_TYPE,
                outcome=EventOutcome.FAILURE,
                detail=f"provider={self._provider.name} error={exc}",
                duration_ms=duration_ms,
                session_id=session_id,
            )
            raise

        duration_ms = self._elapsed_ms(start)
        self._logger.emit(
            source=_SOURCE,
            action_type=_ACTION_TYPE,
            outcome=EventOutcome.SUCCESS,
            detail=(
                f"provider={validated.provider or self._provider.name} "
                f"model={validated.model} "
                f"in={validated.input_tokens} out={validated.output_tokens}"
            ),
            duration_ms=duration_ms,
            session_id=session_id,
        )
        return validated

    def is_available(self) -> bool:
        """Report whether the routed provider is currently usable.

        This is a lightweight passthrough to the underlying provider's own
        availability check, so callers (such as AIReasoningEngine) never need
        to hold a direct reference to a provider - only to the router.

        Returns:
            True if the provider reports itself available, False otherwise
            (including if the availability check itself raises).
        """
        try:
            return self._provider.is_available()
        except Exception:  # noqa: BLE001 - availability checks must never raise out
            return False

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        """Compute elapsed milliseconds since a monotonic start time.

        Args:
            start: The monotonic start time captured before the call.

        Returns:
            The elapsed time in whole milliseconds.
        """
        return int((time.monotonic() - start) * 1000)