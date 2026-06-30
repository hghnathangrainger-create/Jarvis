"""
base_tool.py

Core abstractions for the Jarvis tool system.

Responsibilities:
    - Define the ToolRequest and ToolResult data structures that flow into and
      out of every tool.
    - Define the BaseTool abstract class that every concrete tool implements.

Does NOT:
    - Implement any concrete tool (see tools/builtin/).
    - Execute tools or enforce security (see executor.py).
    - Register or look up tools (see registry.py).

These abstractions are intentionally minimal. A tool declares its name, a
description, and the action string used for security classification, and it
implements a single run method. Everything else - safety, logging, lookup -
is handled by the layers around it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """Input passed to a tool when it is executed.

    Attributes:
        tool_name: The registered name of the tool being invoked.
        input_data: Arbitrary keyword inputs for the tool. The accepted keys
            are defined by each tool's documentation.
        session_id: Optional session identifier for the audit trail.
    """

    tool_name: str
    input_data: dict[str, Any] = field(default_factory=dict)
    session_id: int | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Outcome of attempting to execute a tool.

    A result is always returned; tools and the executor signal problems
    through this structure rather than by raising, so callers can handle every
    outcome uniformly.

    Attributes:
        tool_name: The name of the tool the result is for.
        success: True if the tool ran and completed successfully.
        output: The tool's output text on success, or an empty string.
        error: A human-readable error or status message when not successful.
        requires_confirmation: True when the action was withheld because it
            needs user confirmation (a YELLOW action in Phase 1).
        blocked: True when the action was blocked outright (a RED action).
    """

    tool_name: str
    success: bool
    output: str = ""
    error: str | None = None
    requires_confirmation: bool = False
    blocked: bool = False


class BaseTool(ABC):
    """Abstract base class that every Jarvis tool implements.

    A concrete tool exposes a stable name, a human-readable description, and an
    action string that the Security Manager classifies. The run method performs
    the tool's work and returns a ToolResult.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique, stable name used to register and invoke the tool.

        Returns:
            A short identifier such as "echo".
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Return a short human-readable description of what the tool does.

        Returns:
            A one-line description.
        """
        raise NotImplementedError

    def action_for(self, request: ToolRequest) -> str:
        """Return the action string used for security classification.

        By default this is the tool's name. Tools whose risk depends on their
        input may override this to produce a more specific action string for
        the Security Manager to evaluate.

        Args:
            request: The request the tool is about to handle.

        Returns:
            The action string to be classified by the Security Manager.
        """
        return self.name

    @abstractmethod
    def run(self, request: ToolRequest) -> ToolResult:
        """Execute the tool and return its result.

        Implementations should never raise for predictable problems (such as
        missing input); they should return a ToolResult with success set to
        False and a helpful error message instead.

        Args:
            request: The request describing the inputs for this invocation.

        Returns:
            A ToolResult describing the outcome.
        """
        raise NotImplementedError

    def ok(self, output: str) -> ToolResult:
        """Build a successful ToolResult for this tool.

        Args:
            output: The output text to return.

        Returns:
            A successful ToolResult.
        """
        return ToolResult(tool_name=self.name, success=True, output=output)

    def fail(self, error: str) -> ToolResult:
        """Build a failed ToolResult for this tool.

        Args:
            error: A human-readable error message.

        Returns:
            A failed ToolResult.
        """
        return ToolResult(tool_name=self.name, success=False, error=error)