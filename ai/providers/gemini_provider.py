"""
gemini_provider.py

Google Gemini implementation of the AIProvider interface.

Responsibilities:
    - Wrap the official google-genai SDK behind the provider-neutral
      AIProvider interface.
    - Translate AIRequest into a Gemini generate_content call and translate
      the Gemini response back into a provider-neutral AIResponse.
    - Surface all provider failures as AIProviderError.

Does NOT:
    - Implement memory, planning, workflow, or tool logic.
    - Build prompts or validate responses.
    - Decide when it is called (that is the AI Router's responsibility).

This is the only module permitted to import the google-genai SDK. Keeping
the vendor dependency isolated here is what makes the rest of Jarvis
provider independent.
"""

from __future__ import annotations

from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse

_PROVIDER_NAME = "gemini"


class GeminiProvider(AIProvider):
    """AIProvider implementation backed by the Google Gemini API.

    Attributes:
        _client: The google-genai Client used to make API calls.
        _api_key: The API key the client was configured with.
    """

    def __init__(self, api_key: str = "") -> None:
        """Initialise the Gemini provider with an optional API key.

        Args:
            api_key: The Google API key. An empty string indicates no
                key is configured and is_available() will return False.
        """
        self._api_key = api_key
        self._client = None
        self._gemini_available = False
        try:
            from google import genai as _genai

            self._gemini_available = True
            if api_key:
                self._client = _genai.Client(api_key=api_key)
        except ImportError:
            pass

    @property
    def name(self) -> str:
        """Return the provider name.

        Returns:
            The string "gemini".
        """
        return _PROVIDER_NAME

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a completion using the Gemini API.

        Args:
            request: The provider-neutral request to fulfil.

        Returns:
            A provider-neutral response containing the generated text and
            token and stop-reason metadata when the SDK reports them.

        Raises:
            AIProviderError: If the API call fails, times out, returns no
                usable text, or if the provider is not configured.
        """
        if not self._client or not self._gemini_available:
            raise AIProviderError(
                "Gemini provider is not configured: no API key provided "
                "or google-genai package not installed."
            )

        from google.genai import types

        try:
            response = self._client.models.generate_content(
                model=request.model,
                contents=self._build_contents(request),
                config=types.GenerateContentConfig(
                    max_output_tokens=request.max_tokens,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - surface any SDK failure uniformly
            raise AIProviderError(
                f"Unexpected error calling the Gemini API: {exc}"
            ) from exc

        text = self._extract_text(response)

        usage = getattr(response, "usage_metadata", None)
        return AIResponse(
            text=text,
            model=request.model,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
            stop_reason=None,
            provider=_PROVIDER_NAME,
        )

    def is_available(self) -> bool:
        """Report whether the provider is configured to accept requests.

        This performs a lightweight local check only; it does not make a
        network call. A configured API key and installed SDK indicate the
        provider is ready to attempt requests.

        Returns:
            True if an API key is configured and the SDK is installed,
            False otherwise.
        """
        return bool(self._api_key) and self._gemini_available

    def _build_contents(self, request: AIRequest) -> list[dict[str, str]]:
        """Build the contents list for a Gemini generate_content call.

        The Gemini API does not have a separate system instruction
        parameter; the system instruction is prepended as the first
        user message.

        Args:
            request: The provider-neutral request to translate.

        Returns:
            A list of content dicts for the Gemini API.
        """
        contents: list[dict[str, str]] = [
            {"role": "user", "parts": [{"text": request.system}]},
        ]
        for message in request.messages:
            role = "model" if message.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        return contents

    @staticmethod
    def _extract_text(response: object) -> str:
        """Extract text from a Gemini generate_content response.

        Args:
            response: The raw response object returned by the SDK.

        Returns:
            The text content of the response.

        Raises:
            AIProviderError: If the response contains no text content.
        """
        # The new SDK provides response.text directly.
        text = getattr(response, "text", None)
        if text:
            return text.strip()

        # Fallback: manually extract from candidates/parts.
        candidates = getattr(response, "candidates", None)
        if not candidates:
            raise AIProviderError("Gemini API returned an empty response.")

        parts: list[str] = []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content is not None:
                for part in getattr(content, "parts", []):
                    part_text = getattr(part, "text", None)
                    if part_text:
                        parts.append(part_text)

        text = "".join(parts).strip()
        if not text:
            raise AIProviderError("Gemini API response contained no text content.")

        return text
