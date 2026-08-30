"""
metrics.py

In-memory metrics collector for the Jarvis AI Operating System.

Responsibilities:
    - Track total requests processed.
    - Track per-provider call counts and token usage (input/output).
    - Track per-provider estimated costs (from token counts).
    - Track average response time per provider.
    - Track error rates per subsystem.
    - Track tool usage counts.
    - Expose record(), get_summary(), get_provider_stats(), get_tool_stats().

Does NOT:
    - Persist metrics (see observability/store.py for snapshots).
    - Emit structured audit events (see observability/logger.py).
    - Start or end traces (see observability/tracer.py).

All counters are in-memory only and reset on process restart. Callers
that need durable metrics should periodically snapshot via
ObservabilityStore.save_metrics_snapshot().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderStats:
    """Stats for a single AI provider.

    Attributes:
        call_count: Total calls made to this provider.
        input_tokens: Total input tokens consumed.
        output_tokens: Total output tokens produced.
        total_duration_ms: Cumulative duration of all calls.
        error_count: Number of failed calls.
    """

    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_duration_ms: int = 0
    error_count: int = 0

    @property
    def avg_duration_ms(self) -> float:
        """Average call duration in milliseconds."""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def error_rate(self) -> float:
        """Error rate as a fraction (0.0 to 1.0)."""
        if self.call_count == 0:
            return 0.0
        return self.error_count / self.call_count

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "call_count": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
        }


@dataclass
class ToolStats:
    """Usage stats for a single tool.

    Attributes:
        call_count: Total calls to this tool.
        error_count: Number of failed calls.
        total_duration_ms: Cumulative duration of all calls.
    """

    call_count: int = 0
    error_count: int = 0
    total_duration_ms: int = 0

    @property
    def avg_duration_ms(self) -> float:
        """Average call duration in milliseconds."""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "call_count": self.call_count,
            "error_count": self.error_count,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": round(self.avg_duration_ms, 1),
        }


class MetricsCollector:
    """In-memory metrics collector for requests, providers, and tools.

    Thread-safe for recording (uses simple integer increments).
    All counters reset on process restart.

    Attributes:
        _total_requests: Total requests processed.
        _provider_stats: Per-provider stats keyed by provider name.
        _tool_stats: Per-tool stats keyed by tool name.
        _subsystem_errors: Per-subsystem error counts.
    """

    def __init__(self) -> None:
        self._total_requests: int = 0
        self._provider_stats: dict[str, ProviderStats] = {}
        self._tool_stats: dict[str, ToolStats] = {}
        self._subsystem_errors: dict[str, int] = {}

    def record_request(self) -> None:
        """Record that a new request has been processed."""
        self._total_requests += 1

    def record_provider_call(
        self,
        *,
        provider: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int = 0,
        error: bool = False,
    ) -> None:
        """Record an AI provider call.

        Args:
            provider: The provider name (e.g. "claude", "openai", "gemini").
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            duration_ms: Call duration in milliseconds.
            error: Whether this call resulted in an error.
        """
        stats = self._provider_stats.setdefault(provider, ProviderStats())
        stats.call_count += 1
        stats.input_tokens += input_tokens
        stats.output_tokens += output_tokens
        stats.total_duration_ms += duration_ms
        if error:
            stats.error_count += 1

    def record_tool_call(
        self,
        *,
        tool_name: str,
        duration_ms: int = 0,
        error: bool = False,
    ) -> None:
        """Record a tool execution.

        Args:
            tool_name: The tool's registered name.
            duration_ms: Execution duration in milliseconds.
            error: Whether this call resulted in an error.
        """
        stats = self._tool_stats.setdefault(tool_name, ToolStats())
        stats.call_count += 1
        stats.total_duration_ms += duration_ms
        if error:
            stats.error_count += 1

    def record_subsystem_error(self, subsystem: str) -> None:
        """Record an error in a subsystem.

        Args:
            subsystem: The subsystem name (e.g. "router", "workflow", "security").
        """
        self._subsystem_errors[subsystem] = (
            self._subsystem_errors.get(subsystem, 0) + 1
        )

    def get_provider_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-provider stats as serialisable dicts.

        Returns:
            A dict mapping provider name to its stats dict.
        """
        return {name: stats.to_dict() for name, stats in self._provider_stats.items()}

    def get_tool_stats(self) -> dict[str, dict[str, Any]]:
        """Return per-tool stats as serialisable dicts.

        Returns:
            A dict mapping tool name to its stats dict.
        """
        return {name: stats.to_dict() for name, stats in self._tool_stats.items()}

    def get_summary(self) -> dict[str, Any]:
        """Return a full summary of all collected metrics.

        Returns:
            A serialisable dict with total_requests, provider_stats,
            tool_stats, and subsystem_errors.
        """
        return {
            "total_requests": self._total_requests,
            "provider_stats": self.get_provider_stats(),
            "tool_stats": self.get_tool_stats(),
            "subsystem_errors": dict(self._subsystem_errors),
        }
