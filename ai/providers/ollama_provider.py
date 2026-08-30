"""
ollama_provider.py

Ollama (local model) implementation of the AIProvider interface.

Responsibilities:
    - Wrap the Ollama Python client behind the provider-neutral AIProvider.
    - Support local model inference with zero API cost.
    - Provide model listing, pulling, and availability checking.
    - Graceful fallback when Ollama is not installed or running.

Does NOT:
    - Implement memory, planning, or workflow logic.
    - Make network calls to paid APIs.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from ai.providers.base import AIProvider, AIProviderError, AIRequest, AIResponse

logger = logging.getLogger(__name__)

_PROVIDER_NAME = "ollama"

# Default cost for Ollama — always $0.00.
_OLLAMA_COST_PER_INPUT_TOKEN = 0.0
_OLLAMA_COST_PER_OUTPUT_TOKEN = 0.0


class OllamaProvider(AIProvider):
    """AIProvider implementation backed by local Ollama inference.

    Wraps the Ollama Python client to provide local model inference
    at zero cost. Falls back gracefully when Ollama is not installed
    or the server is not running.

    Attributes:
        _base_url: The Ollama server URL.
        _default_model: The default model to use.
        _client: The Ollama client (lazy-loaded).
    """

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        """Initialise the Ollama provider.

        Args:
            base_url: Ollama server URL. Defaults to OLLAMA_BASE_URL env var
                or "http://localhost:11434".
            default_model: Default model name. Defaults to OLLAMA_MODEL env
                var or "llama3".
        """
        self._base_url = base_url or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self._default_model = default_model or os.environ.get(
            "OLLAMA_MODEL", "llama3"
        )
        self._client: Any = None

    @property
    def name(self) -> str:
        """Return the provider name."""
        return _PROVIDER_NAME

    def _get_client(self) -> Any:
        """Lazy-load and return the Ollama client.

        Returns:
            The Ollama client instance.

        Raises:
            AIProviderError: If the ollama package is not installed.
        """
        if self._client is not None:
            return self._client

        try:
            import ollama as ollama_mod

            self._client = ollama_mod.Client(host=self._base_url)
            return self._client
        except ImportError:
            raise AIProviderError(
                "ollama package is not installed. "
                "Install with: pip install ollama"
            )
        except Exception as exc:
            raise AIProviderError(
                f"Failed to connect to Ollama at {self._base_url}: {exc}"
            ) from exc

    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a completion using local Ollama inference.

        Args:
            request: The provider-neutral request to fulfil.

        Returns:
            A provider-neutral response with the generated text.

        Raises:
            AIProviderError: If the Ollama call fails.
        """
        client = self._get_client()

        # Build messages list with system instruction.
        messages = [{"role": "system", "content": request.system}]
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        model = request.model or self._default_model

        try:
            response = client.chat(
                model=model,
                messages=messages,
                options={
                    "num_predict": request.max_tokens,
                },
            )
        except Exception as exc:
            raise AIProviderError(
                f"Ollama request failed: {exc}"
            ) from exc

        # Extract text from response.
        text = ""
        try:
            text = response["message"]["content"]
        except (KeyError, TypeError):
            raise AIProviderError("Ollama returned an empty response.")

        if not text:
            raise AIProviderError("Ollama returned empty text.")

        # Extract token counts if available.
        input_tokens = None
        output_tokens = None
        try:
            eval_count = response.get("eval_count", 0)
            prompt_eval_count = response.get("prompt_eval_count", 0)
            output_tokens = eval_count if eval_count > 0 else None
            input_tokens = prompt_eval_count if prompt_eval_count > 0 else None
        except (AttributeError, TypeError):
            pass

        return AIResponse(
            text=text,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason="stop",
            provider=_PROVIDER_NAME,
        )

    def is_available(self) -> bool:
        """Check if Ollama server is running and accessible.

        Returns:
            True if the Ollama server responds, False otherwise.
        """
        try:
            import httpx

            resp = httpx.get(f"{self._base_url}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List locally installed Ollama models.

        Returns:
            A list of model names, or empty list if unavailable.
        """
        try:
            client = self._get_client()
            models = client.list()
            return [m["name"] for m in models.get("models", [])]
        except Exception as exc:
            logger.warning("Failed to list Ollama models: %s", exc)
            return []

    def pull_model(self, model_name: str) -> bool:
        """Download a model if not already present.

        Args:
            model_name: The model to pull (e.g. "llama3", "mistral").

        Returns:
            True if the pull succeeded or model already exists.
        """
        try:
            client = self._get_client()
            client.pull(model_name)
            logger.info("Pulled Ollama model: %s", model_name)
            return True
        except Exception as exc:
            logger.error("Failed to pull model %s: %s", model_name, exc)
            return False

    @property
    def cost_per_input_token(self) -> float:
        """Ollama always costs $0.00."""
        return _OLLAMA_COST_PER_INPUT_TOKEN

    @property
    def cost_per_output_token(self) -> float:
        """Ollama always costs $0.00."""
        return _OLLAMA_COST_PER_OUTPUT_TOKEN
