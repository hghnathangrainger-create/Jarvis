"""
openai_provider.py

OpenAI implementation of the AIProvider interface.

Responsibilities:
    - Wrap the official openai SDK behind the provider-neutral AIProvider
      interface.
    - Translate AIRequest into an OpenAI Chat Completions API call and
      translate the OpenAI response back into a provider-neutral AIResponse.
    - Surface all provider failures as AIProviderError.

Does NOT:
    - Implement memory, planning, workflow, or tool logic.
    - Build prompts or validate responses.
    - Decide when it is called (that is the AI Router's responsibility).

This is the only module permitted to import the openai SDK. Keeping the
vendor dependency isolated here is what makes the rest of Jarvis provider
independent.
"""

from __future__ import annotations

from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse

_PROVIDER_NAME = "openai"


class OpenAIProvider(AIProvider):
    """AIProvider implementation backed by the OpenAI API.

    Attributes:
        _client: The OpenAI SDK client used to make API calls.
        _api_key: The API key the client was configured with.
    """

    def __init__(self, api_key: str = "") -> None:
        """Initialise the OpenAI provider with an optional API key.

        Args:
            api_key: The OpenAI API key. An empty string indicates no
                key is configured and is_available() will return False.
        """
        self._api_key = api_key
        self._client = None
        self._openai_available = False
        try:
            import openai as _openai

            self._openai_available = True
            self._client = _openai.OpenAI(api_key=api_key) if api_key else None
        except ImportError:
            pass

    @property
    def name(self) -> str:
        """Return the provider name.

        Returns:
            The string "openai".
        """
        return _PROVIDER_NAME

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a completion using the OpenAI Chat Completions API.

        Args:
            request: The provider-neutral request to fulfil.

        Returns:
            A provider-neutral response containing the generated text and
            token and stop-reason metadata when the SDK reports them.

        Raises:
            AIProviderError: If the API call fails, times out, returns no
                usable text, or if the provider is not configured.
        """
        if not self._client:
            raise AIProviderError(
                "OpenAI provider is not configured: no API key provided."
            )

        import openai as _openai

        try:
            api_response = self._client.chat.completions.create(
                model=request.model,
                max_tokens=request.max_tokens,
                messages=[
                    {"role": "system", "content": request.system},
                    *[
                        {"role": message.role, "content": message.content}
                        for message in request.messages
                    ],
                ],
            )
        except _openai.APIConnectionError as exc:
            raise AIProviderError(
                f"OpenAI connection failed: {exc}"
            ) from exc
        except _openai.APITimeoutError as exc:
            raise AIProviderError(
                f"OpenAI request timed out: {exc}"
            ) from exc
        except _openai.APIError as exc:
            raise AIProviderError(
                f"OpenAI API error: {exc}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surface any SDK failure uniformly
            raise AIProviderError(
                f"Unexpected error calling the OpenAI API: {exc}"
            ) from exc

        text = self._extract_text(api_response)

        usage = getattr(api_response, "usage", None)
        return AIResponse(
            text=text,
            model=getattr(api_response, "model", request.model),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            stop_reason=getattr(
                api_response.choices[0], "finish_reason", None
            ) if api_response.choices else None,
            provider=_PROVIDER_NAME,
        )

    def is_available(self) -> bool:
        """Report whether the provider is configured to accept requests.

        This performs a lightweight local check only; it does not make a
        network call. A configured API key indicates the provider is ready
        to attempt requests.

        Returns:
            True if an API key is configured, False otherwise.
        """
        return bool(self._api_key) and self._openai_available

    @staticmethod
    def _extract_text(api_response: object) -> str:
        """Extract concatenated text from an OpenAI Chat Completions response.

        The Chat Completions API returns a list of choice objects. This
        joins the text of every choice into a single string.

        Args:
            api_response: The raw response object returned by the SDK.

        Returns:
            The concatenated text of all choices.

        Raises:
            AIProviderError: If the response contains no text content.
        """
        choices = getattr(api_response, "choices", None)
        if not choices:
            raise AIProviderError("OpenAI API returned an empty response.")

        parts: list[str] = []
        for choice in choices:
            message = getattr(choice, "message", None)
            if message is not None:
                content = getattr(message, "content", None)
                if content:
                    parts.append(content)

        text = "".join(parts).strip()
        if not text:
            raise AIProviderError("OpenAI API response contained no text content.")

        return text
