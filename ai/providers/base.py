"""
base.py

Abstract provider interface for the Jarvis AI Operating System.

Responsibilities:
    - Define the AIProvider abstract base class that every concrete provider
      (Claude, and future providers) must implement.
    - Define the provider-neutral data structures used to request a completion
      and return a response, so the rest of Jarvis never depends on any single
      vendor's SDK types.

Does NOT:
    - Implement any specific provider (see claude.py).
    - Implement memory, planning, workflow, or tool logic.
    - Build prompts (see prompt_builder.py) or validate responses
      (see response_validator.py).

By depending only on this interface, the AI Router and the wider system remain
provider independent: a new provider can be added by implementing AIProvider
without changing any other module.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AIMessage:
    """A single message in a provider-neutral conversation.

    Attributes:
        role: The role of the speaker, either "user" or "assistant".
        content: The text content of the message.
    """

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class AIRequest:
    """A provider-neutral request for a model completion.

    Attributes:
        system: The system instruction that frames the model's behaviour.
        messages: The ordered conversation history, ending with the latest
            user message.
        model: The model identifier to use for this request.
        max_tokens: The maximum number of tokens to generate.
    """

    system: str
    messages: tuple[AIMessage, ...]
    model: str
    max_tokens: int


@dataclass(frozen=True, slots=True)
class AIResponse:
    """A provider-neutral response from a model completion.

    Attributes:
        text: The generated text content of the response.
        model: The model identifier that produced the response.
        input_tokens: Number of tokens consumed by the request, if reported.
        output_tokens: Number of tokens produced in the response, if reported.
        stop_reason: The reason the model stopped generating, if reported.
        provider: The name of the provider that produced this response.
    """

    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    provider: str = field(default="")


class AIProviderError(Exception):
    """Raised when a provider fails to produce a usable response.

    This is the single exception type for provider-level failures (network
    errors, authentication errors, API errors) so that callers can handle
    provider failures distinctly from other errors.
    """


class AIProvider(ABC):
    """Abstract interface that every AI provider must implement.

    Concrete providers wrap a specific vendor SDK and translate between that
    SDK's types and the provider-neutral AIRequest and AIResponse types.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique, human-readable name of this provider.

        Returns:
            A short identifier such as "claude".
        """
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: AIRequest) -> AIResponse:
        """Generate a completion for the given request.

        Args:
            request: The provider-neutral request describing the system
                instruction, conversation, model, and token limit.

        Returns:
            A provider-neutral response containing the generated text and
            associated metadata.

        Raises:
            AIProviderError: If the provider cannot produce a usable response.
        """
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """Report whether the provider is currently usable.

        Returns:
            True if the provider is configured and ready to accept requests,
            False otherwise.
        """
        raise NotImplementedError