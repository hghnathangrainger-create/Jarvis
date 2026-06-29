"""
response_validator.py

Validates AI responses for the Jarvis AI Operating System.

Responsibilities:
    - Confirm that a provider response contains usable, non-empty text.
    - Reject responses that are empty, whitespace-only, or truncated in a way
      that makes them unusable.

Does NOT:
    - Call any AI provider.
    - Interpret or act on the response content.
    - Implement memory, planning, workflow, or tool logic.

Validation here is intentionally minimal and provider neutral. It guarantees
that any response passed onward to the rest of Jarvis is at least structurally
usable, so downstream subsystems do not have to repeat this check.
"""

from __future__ import annotations

from ai.providers.base import AIResponse

#: Stop reasons that indicate the response may be incomplete or unusable.
_UNUSABLE_STOP_REASONS = frozenset({"max_tokens"})


class ResponseValidationError(Exception):
    """Raised when an AI response is empty or otherwise unusable."""


class ResponseValidator:
    """Validates that AI responses are non-empty and usable.

    The validator is stateless; a single instance can be shared across the
    application.
    """

    def validate(self, response: AIResponse) -> AIResponse:
        """Validate a response and return it unchanged if it is usable.

        Args:
            response: The provider-neutral response to validate.

        Returns:
            The same response, unchanged, when it passes validation.

        Raises:
            ResponseValidationError: If the response text is empty or
                whitespace-only.
        """
        if response.text is None or not response.text.strip():
            raise ResponseValidationError(
                "AI response is empty or contains only whitespace."
            )

        return response

    def is_complete(self, response: AIResponse) -> bool:
        """Report whether a response appears complete.

        A response is considered incomplete when its stop reason indicates the
        model was cut off before finishing (for example, by hitting the token
        limit). This is advisory; it does not raise.

        Args:
            response: The response to inspect.

        Returns:
            False if the stop reason indicates truncation, True otherwise.
        """
        if response.stop_reason is None:
            return True
        return response.stop_reason not in _UNUSABLE_STOP_REASONS