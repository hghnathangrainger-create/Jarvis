"""
store.py

SQLite persistence for the Jarvis observability subsystem.

Responsibilities:
    - Persist traces (user-interaction lifecycle) to the ``traces`` table.
    - Persist trace spans (per-subsystem call records) to the
      ``trace_spans`` table.
    - Persist periodic metrics snapshots to the ``metrics_snapshots`` table.
    - Provide read accessors for the observability tool to display recent
      traces, provider stats, and metrics summaries.

Does NOT:
    - Store or compute in-memory metrics (see observability/metrics.py).
    - Start or end traces (see observability/tracer.py).
    - Emit structured audit events (see observability/logger.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from storage.models import MetricsSnapshot, TraceEntry, TraceSpan


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """A serialisable view of a trace row."""

    trace_id: str
    user_input: str
    status: str
    start_time: datetime
    end_time: datetime | None
    error: str | None
    session_id: int | None


@dataclass(frozen=True, slots=True)
class SpanRecord:
    """A serialisable view of a span row."""

    trace_id: str
    span_name: str
    subsystem: str
    duration_ms: int | None
    status: str
    metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MetricsSnapshotRecord:
    """A serialisable view of a metrics snapshot row."""

    snapshot_time: datetime
    metrics: dict[str, Any]


class ObservabilityStore:
    """SQLite-backed persistence for traces, spans, and metrics.

    Attributes:
        _session_factory: Factory used to open database sessions.
    """

    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        """Initialise with a database session factory.

        Args:
            session_factory: Typically produced by
                storage.database.create_session_factory.
        """
        self._session_factory = session_factory

    # -- traces ---------------------------------------------------------------

    def start_trace(
        self,
        *,
        trace_id: str,
        user_input: str,
        session_id: int | None = None,
    ) -> None:
        """Record the start of a new trace.

        Args:
            trace_id: The unique identifier for this trace.
            user_input: The original user request text.
            session_id: Optional session identifier.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = TraceEntry(
                trace_id=trace_id,
                user_input=user_input,
                session_id=session_id,
                status="running",
            )
            session.add(entry)
            session.commit()

    def end_trace(
        self,
        *,
        trace_id: str,
        status: str = "completed",
        error: str | None = None,
    ) -> None:
        """Mark a trace as complete.

        Args:
            trace_id: The trace to end.
            status: Final status (e.g. "completed", "failed").
            error: Optional error message if the trace failed.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(TraceEntry).where(TraceEntry.trace_id == trace_id)
            ).scalar_one_or_none()
            if entry is not None:
                entry.status = status
                entry.end_time = datetime.now(timezone.utc)
                entry.error = error
                session.commit()

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        """Retrieve a single trace by id.

        Args:
            trace_id: The trace to look up.

        Returns:
            A TraceRecord, or None if not found.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            entry = session.execute(
                select(TraceEntry).where(TraceEntry.trace_id == trace_id)
            ).scalar_one_or_none()
            if entry is None:
                return None
            return TraceRecord(
                trace_id=entry.trace_id,
                user_input=entry.user_input,
                status=entry.status,
                start_time=entry.start_time,
                end_time=entry.end_time,
                error=entry.error,
                session_id=entry.session_id,
            )

    def list_recent_traces(self, limit: int = 20) -> list[TraceRecord]:
        """Return the most recent traces, newest first.

        Args:
            limit: Maximum number of traces to return.

        Returns:
            A list of TraceRecord objects.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            rows = session.execute(
                select(TraceEntry)
                .order_by(TraceEntry.start_time.desc())
                .limit(limit)
            ).scalars().all()
            return [
                TraceRecord(
                    trace_id=e.trace_id,
                    user_input=e.user_input,
                    status=e.status,
                    start_time=e.start_time,
                    end_time=e.end_time,
                    error=e.error,
                    session_id=e.session_id,
                )
                for e in rows
            ]

    # -- spans ----------------------------------------------------------------

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
        """Persist a completed span.

        Args:
            trace_id: The trace this span belongs to.
            span_name: A short label (e.g. "ai_call", "tool_exec").
            subsystem: The subsystem that produced the span.
            duration_ms: Duration in milliseconds, if measured.
            status: "ok" or "error".
            metadata: Optional key-value context.
        """
        metadata_json = json.dumps(metadata) if metadata else None
        with self._session_factory() as session:  # type: ignore[call-arg]
            span = TraceSpan(
                trace_id=trace_id,
                span_name=span_name,
                subsystem=subsystem,
                duration_ms=duration_ms,
                status=status,
                metadata_json=metadata_json,
            )
            session.add(span)
            session.commit()

    def list_spans_for_trace(self, trace_id: str) -> list[SpanRecord]:
        """Return all spans for a given trace, in creation order.

        Args:
            trace_id: The trace whose spans to retrieve.

        Returns:
            A list of SpanRecord objects.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            rows = session.execute(
                select(TraceSpan)
                .where(TraceSpan.trace_id == trace_id)
                .order_by(TraceSpan.created_at.asc())
            ).scalars().all()
            return [
                SpanRecord(
                    trace_id=s.trace_id,
                    span_name=s.span_name,
                    subsystem=s.subsystem,
                    duration_ms=s.duration_ms,
                    status=s.status,
                    metadata=json.loads(s.metadata_json) if s.metadata_json else {},
                    created_at=s.created_at,
                )
                for s in rows
            ]

    def list_recent_spans(self, limit: int = 50) -> list[SpanRecord]:
        """Return the most recent spans across all traces, newest first.

        Args:
            limit: Maximum number of spans to return.

        Returns:
            A list of SpanRecord objects.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            rows = session.execute(
                select(TraceSpan)
                .order_by(TraceSpan.created_at.desc())
                .limit(limit)
            ).scalars().all()
            return [
                SpanRecord(
                    trace_id=s.trace_id,
                    span_name=s.span_name,
                    subsystem=s.subsystem,
                    duration_ms=s.duration_ms,
                    status=s.status,
                    metadata=json.loads(s.metadata_json) if s.metadata_json else {},
                    created_at=s.created_at,
                )
                for s in rows
            ]

    # -- metrics snapshots ----------------------------------------------------

    def save_metrics_snapshot(self, metrics: dict[str, Any]) -> None:
        """Persist a metrics snapshot.

        Args:
            metrics: The full metrics dict from MetricsCollector.get_summary().
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            snapshot = MetricsSnapshot(
                metrics_json=json.dumps(metrics),
            )
            session.add(snapshot)
            session.commit()

    def list_recent_snapshots(self, limit: int = 10) -> list[MetricsSnapshotRecord]:
        """Return the most recent metrics snapshots, newest first.

        Args:
            limit: Maximum number of snapshots to return.

        Returns:
            A list of MetricsSnapshotRecord objects.
        """
        with self._session_factory() as session:  # type: ignore[call-arg]
            rows = session.execute(
                select(MetricsSnapshot)
                .order_by(MetricsSnapshot.snapshot_time.desc())
                .limit(limit)
            ).scalars().all()
            return [
                MetricsSnapshotRecord(
                    snapshot_time=s.snapshot_time,
                    metrics=json.loads(s.metrics_json),
                )
                for s in rows
            ]
