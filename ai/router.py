"""
router.py

AI request routing for the Jarvis AI Operating System.

Responsibilities:
    - Accept a request for AI assistance and route it to a provider.
    - Route through available providers in order, falling back to the next
      on retryable errors (connection, timeout, and API errors).
    - Parse model strings in "provider:model" format (e.g. "openai:gpt-4o")
      and route directly to the named provider.
    - Handle "auto" model strings by trying providers in configured order.
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
from ai.cost_tracker import CostTracker, estimate_cost
from ai.prompt_builder import PromptBuilder
from ai.providers.base import AIProvider, AIProviderError, AIResponse
from ai.response_validator import ResponseValidationError, ResponseValidator
from config.constants import EventOutcome
from config.settings import Settings
from observability.logger import EventLogger

_SOURCE = "ai_router"
_ACTION_TYPE = "ai_call"


def parse_model_string(
    model: str, providers: tuple[AIProvider, ...]
) -> tuple[AIProvider, str]:
    """Parse a model string into a provider and model identifier.

    Supported formats:
        - "provider:model" (e.g. "openai:gpt-4o") routes directly to
          the named provider, using the part after the colon as the model.
        - "auto" returns the first provider, letting the caller fall
          back through providers.
        - Any other string is treated as a plain model name for the
          first provider (legacy behaviour).

    Args:
        model: The model string to parse.
        providers: The ordered tuple of available providers.

    Returns:
        A tuple of (provider, model_name) where provider is the matched
        provider and model_name is the model identifier to pass to it.
    """
    if ":" in model:
        provider_name, model_name = model.split(":", 1)
        provider_name = provider_name.strip().lower()
        model_name = model_name.strip()
        for provider in providers:
            if provider.name == provider_name:
                return provider, model_name
        raise AIProviderError(
            f"No provider named '{provider_name}' is configured. "
            f"Available providers: {[p.name for p in providers]}"
        )

    if model.strip().lower() == "auto":
        if not providers:
            raise AIProviderError("No providers are configured.")
        return providers[0], providers[0].name

    # Plain model name: use the first provider.
    if not providers:
        raise AIProviderError("No providers are configured.")
    return providers[0], model


class AIRouter:
    """Routes AI requests to providers with automatic fallback.

    When multiple providers are configured, the router tries each one in
    order. Retryable errors (connection, timeout, API errors) trigger
    fallback to the next available provider.

    Attributes:
        _providers: The ordered tuple of providers to try.
        _prompt_builder: Builds structured prompts from request components.
        _validator: Validates provider responses.
        _logger: Emits a structured event for every AI call.
        _settings: Application settings supplying the default model and
            token limit.
    """

    def __init__(
        self,
        *,
        provider: AIProvider | None = None,
        providers: tuple[AIProvider, ...] | None = None,
        prompt_builder: PromptBuilder,
        validator: ResponseValidator,
        logger: EventLogger,
        settings: Settings,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        """Initialise the router with its collaborators.

        Args:
            provider: A single provider (backward-compatible alias for
                providers=(provider,)). Ignored if providers is given.
            providers: An ordered tuple of providers to try. When given,
                takes precedence over the provider parameter.
            prompt_builder: The builder used to assemble structured prompts.
            validator: The validator used to check responses.
            logger: The event logger used to record every AI call.
            settings: Application settings supplying default model and tokens.
            cost_tracker: Optional CostTracker for recording API costs.
        """
        if providers is not None:
            self._providers = providers
        elif provider is not None:
            self._providers = (provider,)
        else:
            raise TypeError(
                'AIRouter requires either "provider" or "providers" argument.'
            )
        self._prompt_builder = prompt_builder
        self._validator = validator
        self._logger = logger
        self._settings = settings
        self._cost_tracker = cost_tracker

    def route(
        self,
        *,
        system_instruction: str,
        user_message: str,
        context: AIContextBlock | None = None,
        session_id: int | None = None,
    ) -> AIResponse:
        """Route a request through available providers with fallback.

        Parses the model string from settings to determine which provider(s)
        to try, then attempts each in order. Retryable errors trigger
        fallback to the next provider.

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
            AIProviderError: If all providers fail or no provider is available.
            ResponseValidationError: If the response fails validation.
        """
        # Parse the model string to determine routing order.
        requested_provider, resolved_model = parse_model_string(
            self._settings.ai_model, self._providers
        )

        # Build provider queue: requested provider first, then remaining.
        provider_queue = self._build_provider_queue(requested_provider)

        last_error: Exception | None = None

        for current_provider in provider_queue:
            request = self._prompt_builder.build(
                system_instruction=system_instruction,
                user_message=user_message,
                model=resolved_model,
                max_tokens=self._settings.ai_max_tokens,
                context=context,
            )

            start = time.monotonic()
            try:
                response = current_provider.generate(request)
                validated = self._validator.validate(response)
            except AIProviderError as exc:
                duration_ms = self._elapsed_ms(start)
                self._emit_audit_event(
                    outcome=EventOutcome.FAILURE,
                    detail=f"provider={current_provider.name} error={exc}",
                    duration_ms=duration_ms,
                    session_id=session_id,
                )
                last_error = exc
                # Fall through to the next provider.
                continue
            except ResponseValidationError as exc:
                duration_ms = self._elapsed_ms(start)
                self._emit_audit_event(
                    outcome=EventOutcome.FAILURE,
                    detail=f"provider={current_provider.name} validation_error={exc}",
                    duration_ms=duration_ms,
                    session_id=session_id,
                )
                # Validation errors are not retryable: the provider worked
                # but the response was invalid.
                raise

            duration_ms = self._elapsed_ms(start)
            self._emit_audit_event(
                outcome=EventOutcome.SUCCESS,
                detail=(
                    f"provider={validated.provider or current_provider.name} "
                    f"model={validated.model} "
                    f"in={validated.input_tokens} out={validated.output_tokens}"
                ),
                duration_ms=duration_ms,
                session_id=session_id,
            )
            return validated

        # All providers exhausted.
        if last_error is not None:
            raise last_error
        raise AIProviderError("No providers are available.")

    def _build_provider_queue(
        self, requested_provider: AIProvider
    ) -> list[AIProvider]:
        """Build an ordered list of providers to try.

        The requested provider comes first, followed by any remaining
        providers from the configured tuple (skipping the requested one
        if it appears later).

        Args:
            requested_provider: The provider to try first.

        Returns:
            An ordered list of providers to attempt.
        """
        queue: list[AIProvider] = [requested_provider]
        for provider in self._providers:
            if provider is not requested_provider:
                queue.append(provider)
        return queue

    def _emit_audit_event(
        self,
        *,
        outcome: EventOutcome,
        detail: str,
        duration_ms: int,
        session_id: int | None,
    ) -> None:
        """Emit this router's own ai_call audit event, isolating a failing logger.

        Only this logging/reporting boundary is isolated. It never affects
        provider selection, request construction, validation, or exception
        propagation: the bare raise in the caller's except block always
        re-raises the original AIProviderError/ResponseValidationError
        untouched, regardless of whether this method's own emit() call
        succeeded or was swallowed here.

        Args:
            outcome: The outcome to record for this call.
            detail: The detail string describing the call.
            duration_ms: The elapsed time of the call, in milliseconds.
            session_id: Optional session identifier for the event.
        """
        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=_ACTION_TYPE,
                outcome=outcome,
                detail=detail,
                duration_ms=duration_ms,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never alter
            # routing success/failure semantics.
            pass

    def is_available(self) -> bool:
        """Report whether any routed provider is currently usable.

        This checks if at least one provider is available.

        Returns:
            True if any provider reports itself available, False otherwise
            (including if the availability check itself raises).
        """
        try:
            return any(provider.is_available() for provider in self._providers)
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
