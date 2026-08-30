"""
tracer.py

Request tracing for the Jarvis AI Operating System.

Responsibilities:
    - Assign a unique trace_id to each user interaction.
    - Track every subsystem call within that interaction as a span
      (which tools were called, which AI providers were tried, how long
      each took, whether it succeeded or failed).
    - Persist traces and spans to SQLite via ObservabilityStore.
    - Expose start_trace(), span(), end_trace() for callers.

Does NOT:
    - Compute aggregate metrics (see observability/metrics.py).
    - Emit structured audit events (see observability/logger.py).
    - Configure console logging (see observability/logging_setup.py).

The tracer is the single entry point for request-level tracing. Every
subsystem that needs to record a span does so through this interface,
keeping tracing logic centralised and the rest of the codebase free of
span-management concerns.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator

from observability.store import ObservabilityStore

logger = logging.getLogger(__name__)


@dataclass
class SpanContext:
    """Mutable context for a span being recorded.

    Attributes:
        trace_id: The trace this span belongs to.
        span_name: A short label for the span.
        subsystem: The subsystem performing the work.
        metadata: Key-value context attached to the span.
        start_time: When the span started.
    """

    trace_id: str
    span_name: str
    subsystem: str
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=lambda: __import__("time").monotonic())


class Tracer:
    """Request-level tracing for user interactions.

    Each user interaction gets a trace_id. The tracer tracks every
    subsystem call within that interaction as a span, and persists
    both to SQLite.

    Attributes:
        _store: The observability store for persistence.
    """

    def __init__(self, store: ObservabilityStore) -> None:
        """Initialise the tracer with its persistence store.

        Args:
            store: The ObservabilityStore used to persist traces and spans.
        """
        self._store = store

    def start_trace(
        self,
        user_input: str,
        *,
        session_id: int | None = None,
        trace_id: str | None = None,
    ) -> str:
        """Begin a new trace for a user interaction.

        Args:
            user_input: The original user request text.
            session_id: Optional session identifier.
            trace_id: Optional trace id (generated if not provided).

        Returns:
            The trace_id for this interaction.
        """
        tid = trace_id or str(uuid.uuid4())
        try:
            self._store.start_trace(
                trace_id=tid,
                user_input=user_input,
                session_id=session_id,
            )
        except Exception:
            logger.warning("Failed to persist trace start for %s", tid)
        return tid

    def end_trace(
        self,
        trace_id: str,
        *,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        """Mark a trace as complete.

        Args:
            trace_id: The trace to end.
            status: Final status ("completed", "failed").
            error: Optional error message.
        """
        try:
            self._store.end_trace(
                trace_id=trace_id,
                status=status,
                error=error,
            )
        except Exception:
            logger.warning("Failed to persist trace end for %s", trace_id)

    @contextmanager
    def span(
        self,
        trace_id: str,
        span_name: str,
        subsystem: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> Generator[SpanContext, None, None]:
        """Context manager that records a span within a trace.

        Measures the duration automatically and persists the span
        when the context manager exits.

        Args:
            trace_id: The trace this span belongs to.
            span_name: A short label (e.g. "ai_call", "tool_exec").
            subsystem: The subsystem performing the work.
            metadata: Optional key-value context.

        Yields:
            A SpanContext that callers can attach metadata to during
            execution.
        """
        import time

        ctx = SpanContext(
            trace_id=trace_id,
            span_name=span_name,
            subsystem=subsystem,
            metadata=dict(metadata) if metadata else {},
        )
        start = time.monotonic()
        error_occurred = False
        try:
            yield ctx
        except Exception:
            error_occurred = True
            ctx.metadata["error"] = True
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            status = "error" if error_occurred else "ok"
            try:
                self._store.record_span(
                    trace_id=trace_id,
                    span_name=span_name,
                    subsystem=subsystem,
                    duration_ms=duration_ms,
                    status=status,
                    metadata=ctx.metadata,
                )
            except Exception:
                logger.warning(
                    "Failed to persist span %s for trace %s",
                    span_name, trace_id,
                )

    def record_span(
        self,
        *,
        trace_id: str,
        span_name: str,
        subsystem: str,
        duration_ms: int | None = None,
        status: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a completed span without using the context manager.

        For callers that manage timing themselves.

        Args:
            trace_id: The trace this span belongs to.
            span_name: A short label.
            subsystem: The subsystem that produced the span.
            duration_ms: Duration in milliseconds.
            status: "ok" or "error".
            metadata: Optional key-value context.
        """
        try:
            self._store.record_span(
                trace_id=trace_id,
                span_name=span_name,
                subsystem=subsystem,
                duration_ms=duration_ms,
                status=status,
                metadata=metadata,
            )
        except Exception:
            logger.warning(
                "Failed to persist span %s for trace %s",
                span_name, trace_id,
            )
