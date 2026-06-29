"""
claude.py

Claude (Anthropic) implementation of the AIProvider interface.

Responsibilities:
    - Wrap the official anthropic SDK behind the provider-neutral AIProvider
      interface.
    - Translate AIRequest into an Anthropic Messages API call and translate
      the Anthropic response back into a provider-neutral AIResponse.
    - Surface all provider failures as AIProviderError.

Does NOT:
    - Implement memory, planning, workflow, or tool logic.
    - Build prompts or validate responses.
    - Decide when it is called (that is the AI Router's responsibility).

This is the only module permitted to import the anthropic SDK. Keeping the
vendor dependency isolated here is what makes the rest of Jarvis provider
independent.
"""

from __future__ import annotations

import anthropic

from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse
from config.settings import Settings

_PROVIDER_NAME = "claude"


class ClaudeProvider(AIProvider):
    """AIProvider implementation backed by the Anthropic Claude API.

    Attributes:
        _client: The Anthropic SDK client used to make API calls.
        _api_key: The API key the client was configured with.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialise the Claude provider from application settings.

        Args:
            settings: Application settings supplying the Anthropic API key.
        """
        self._api_key = settings.anthropic_api_key
        self._client = anthropic.Anthropic(api_key=self._api_key)

    @property
    def name(self) -> str:
        """Return the provider name.

        Returns:
            The string "claude".
        """
        return _PROVIDER_NAME

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a completion using the Anthropic Messages API.

        Args:
            request: The provider-neutral request to fulfil.

        Returns:
            A provider-neutral response containing the generated text and
            token and stop-reason metadata when the SDK reports them.

        Raises:
            AIProviderError: If the API call fails or returns no usable text.
        """
        try:
            api_response = self._client.messages.create(
                model=request.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[
                    {"role": message.role, "content": message.content}
                    for message in request.messages
                ],
            )
        except anthropic.APIError as exc:
            raise AIProviderError(
                f"Claude API request failed: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surface any SDK failure uniformly
            raise AIProviderError(
                f"Unexpected error calling the Claude API: {exc}"
            ) from exc

        text = self._extract_text(api_response)

        usage = getattr(api_response, "usage", None)
        return AIResponse(
            text=text,
            model=getattr(api_response, "model", request.model),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            stop_reason=getattr(api_response, "stop_reason", None),
            provider=_PROVIDER_NAME,
        )

    def is_available(self) -> bool:
        """Report whether the provider is configured to accept requests.

        This performs a lightweight local check only; it does not make a
        network call. A configured API key indicates the provider is ready to
        attempt requests.

        Returns:
            True if an API key is configured, False otherwise.
        """
        return bool(self._api_key)

    @staticmethod
    def _extract_text(api_response: object) -> str:
        """Extract concatenated text from an Anthropic Messages response.

        The Messages API returns a list of content blocks. This joins the text
        of every text block into a single string.

        Args:
            api_response: The raw response object returned by the SDK.

        Returns:
            The concatenated text of all text content blocks.

        Raises:
            AIProviderError: If the response contains no text content.
        """
        content = getattr(api_response, "content", None)
        if not content:
            raise AIProviderError("Claude API returned an empty response.")

        parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                parts.append(getattr(block, "text", ""))

        text = "".join(parts).strip()
        if not text:
            raise AIProviderError("Claude API response contained no text content.")

        return text