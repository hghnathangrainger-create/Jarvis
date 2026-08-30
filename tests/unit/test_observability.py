"""
test_observability.py

Unit tests for the observability subsystem: store, tracer, metrics, and tool.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from observability.metrics import MetricsCollector, ProviderStats, ToolStats
from observability.store import ObservabilityStore
from observability.tracer import Tracer
from storage.database import initialize_database
from storage.models import Base
from tools.base_tool import ToolRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session_factory():
    """Create an in-memory SQLite session factory."""
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory


@pytest.fixture()
def obs_store(session_factory):
    """Create an ObservabilityStore backed by in-memory SQLite."""
    return ObservabilityStore(session_factory)


@pytest.fixture()
def tracer(obs_store):
    """Create a Tracer with the in-memory store."""
    return Tracer(obs_store)


@pytest.fixture()
def metrics():
    """Create a fresh MetricsCollector."""
    return MetricsCollector()


# ---------------------------------------------------------------------------
# Store tests
# ---------------------------------------------------------------------------


class TestObservabilityStore:
    """Tests for ObservabilityStore persistence."""

    def test_start_and_end_trace(self, obs_store):
        """Traces can be started and ended."""
        obs_store.start_trace(trace_id="t1", user_input="hello")
        record = obs_store.get_trace("t1")
        assert record is not None
        assert record.trace_id == "t1"
        assert record.user_input == "hello"
        assert record.status == "running"

        obs_store.end_trace(trace_id="t1", status="completed")
        record = obs_store.get_trace("t1")
        assert record.status == "completed"
        assert record.end_time is not None

    def test_end_trace_with_error(self, obs_store):
        """Traces can be ended with an error."""
        obs_store.start_trace(trace_id="t2", user_input="fail")
        obs_store.end_trace(trace_id="t2", status="failed", error="boom")
        record = obs_store.get_trace("t2")
        assert record.status == "failed"
        assert record.error == "boom"

    def test_list_recent_traces(self, obs_store):
        """Recent traces are returned newest first."""
        obs_store.start_trace(trace_id="t1", user_input="first")
        obs_store.start_trace(trace_id="t2", user_input="second")
        traces = obs_store.list_recent_traces(limit=10)
        assert len(traces) == 2
        assert traces[0].trace_id == "t2"
        assert traces[1].trace_id == "t1"

    def test_list_recent_traces_limit(self, obs_store):
        """Limit parameter works."""
        for i in range(5):
            obs_store.start_trace(trace_id=f"t{i}", user_input=f"msg{i}")
        traces = obs_store.list_recent_traces(limit=2)
        assert len(traces) == 2

    def test_get_trace_not_found(self, obs_store):
        """Non-existent trace returns None."""
        assert obs_store.get_trace("nonexistent") is None

    def test_record_span(self, obs_store):
        """Spans can be recorded and retrieved."""
        obs_store.start_trace(trace_id="t1", user_input="test")
        obs_store.record_span(
            trace_id="t1",
            span_name="ai_call",
            subsystem="router",
            duration_ms=150,
            status="ok",
            metadata={"provider": "claude", "tokens": 100},
        )
        spans = obs_store.list_spans_for_trace("t1")
        assert len(spans) == 1
        assert spans[0].span_name == "ai_call"
        assert spans[0].duration_ms == 150
        assert spans[0].metadata["provider"] == "claude"

    def test_list_recent_spans(self, obs_store):
        """Recent spans are returned newest first."""
        obs_store.start_trace(trace_id="t1", user_input="test")
        obs_store.record_span(
            trace_id="t1", span_name="span_a", subsystem="router", status="ok"
        )
        obs_store.record_span(
            trace_id="t1", span_name="span_b", subsystem="workflow", status="ok"
        )
        spans = obs_store.list_recent_spans(limit=10)
        assert len(spans) == 2
        # Newest first (span_b was recorded second)
        assert spans[0].span_name == "span_b"

    def test_save_metrics_snapshot(self, obs_store):
        """Metrics snapshots can be saved and retrieved."""
        obs_store.save_metrics_snapshot({"total_requests": 42, "providers": {}})
        snapshots = obs_store.list_recent_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0].metrics["total_requests"] == 42

    def test_trace_with_session_id(self, obs_store):
        """Traces can have a session_id."""
        obs_store.start_trace(trace_id="t1", user_input="test", session_id=7)
        record = obs_store.get_trace("t1")
        assert record.session_id == 7


# ---------------------------------------------------------------------------
# Tracer tests
# ---------------------------------------------------------------------------


class TestTracer:
    """Tests for Tracer request tracing."""

    def test_start_and_end_trace(self, tracer, obs_store):
        """Tracer starts and ends traces through the store."""
        trace_id = tracer.start_trace("hello world")
        assert trace_id is not None
        record = obs_store.get_trace(trace_id)
        assert record is not None
        assert record.user_input == "hello world"
        assert record.status == "running"

        tracer.end_trace(trace_id, status="completed")
        record = obs_store.get_trace(trace_id)
        assert record.status == "completed"

    def test_custom_trace_id(self, tracer):
        """Tracer accepts a custom trace_id."""
        trace_id = tracer.start_trace("test", trace_id="custom-id")
        assert trace_id == "custom-id"

    def test_span_context_manager(self, tracer, obs_store):
        """The span context manager records spans with timing."""
        trace_id = tracer.start_trace("test")
        with tracer.span(trace_id, "ai_call", "router", metadata={"model": "claude"}):
            time.sleep(0.01)
        spans = obs_store.list_spans_for_trace(trace_id)
        assert len(spans) == 1
        assert spans[0].span_name == "ai_call"
        assert spans[0].subsystem == "router"
        assert spans[0].duration_ms >= 10
        assert spans[0].status == "ok"
        assert spans[0].metadata["model"] == "claude"

    def test_span_records_error_on_exception(self, tracer, obs_store):
        """The span context manager records error status on exception."""
        trace_id = tracer.start_trace("test")
        with pytest.raises(ValueError):
            with tracer.span(trace_id, "tool_exec", "tools"):
                raise ValueError("boom")
        spans = obs_store.list_spans_for_trace(trace_id)
        assert len(spans) == 1
        assert spans[0].status == "error"
        assert spans[0].metadata.get("error") is True

    def test_record_span_manually(self, tracer, obs_store):
        """Tracer can record spans without the context manager."""
        trace_id = tracer.start_trace("test")
        tracer.record_span(
            trace_id=trace_id,
            span_name="security_check",
            subsystem="security",
            duration_ms=5,
            status="ok",
        )
        spans = obs_store.list_spans_for_trace(trace_id)
        assert len(spans) == 1
        assert spans[0].span_name == "security_check"

    def test_tracer_handles_store_failure(self):
        """Tracer gracefully handles store errors."""
        failing_store = MagicMock()
        failing_store.start_trace.side_effect = RuntimeError("db down")
        tracer = Tracer(failing_store)
        # Should not raise
        trace_id = tracer.start_trace("test")
        assert trace_id is not None


# ---------------------------------------------------------------------------
# Metrics tests
# ---------------------------------------------------------------------------


class TestMetricsCollector:
    """Tests for MetricsCollector."""

    def test_record_request(self, metrics):
        """record_request increments total_requests."""
        assert metrics.get_summary()["total_requests"] == 0
        metrics.record_request()
        metrics.record_request()
        metrics.record_request()
        assert metrics.get_summary()["total_requests"] == 3

    def test_record_provider_call(self, metrics):
        """Provider calls are tracked with token counts."""
        metrics.record_provider_call(
            provider="claude", input_tokens=100, output_tokens=50, duration_ms=200
        )
        stats = metrics.get_provider_stats()
        assert "claude" in stats
        assert stats["claude"]["call_count"] == 1
        assert stats["claude"]["input_tokens"] == 100
        assert stats["claude"]["output_tokens"] == 50
        assert stats["claude"]["avg_duration_ms"] == 200.0

    def test_record_provider_call_error(self, metrics):
        """Provider errors are tracked."""
        metrics.record_provider_call(provider="openai", error=True, duration_ms=50)
        stats = metrics.get_provider_stats()
        assert stats["openai"]["error_count"] == 1
        assert stats["openai"]["error_rate"] == 1.0

    def test_record_tool_call(self, metrics):
        """Tool calls are tracked."""
        metrics.record_tool_call(tool_name="memory_tool", duration_ms=30)
        metrics.record_tool_call(tool_name="memory_tool", duration_ms=10)
        stats = metrics.get_tool_stats()
        assert stats["memory_tool"]["call_count"] == 2
        assert stats["memory_tool"]["avg_duration_ms"] == 20.0

    def test_record_tool_call_error(self, metrics):
        """Tool errors are tracked."""
        metrics.record_tool_call(tool_name="file_tool", error=True)
        stats = metrics.get_tool_stats()
        assert stats["file_tool"]["error_count"] == 1

    def test_record_subsystem_error(self, metrics):
        """Subsystem errors are counted."""
        metrics.record_subsystem_error("router")
        metrics.record_subsystem_error("router")
        metrics.record_subsystem_error("workflow")
        summary = metrics.get_summary()
        assert summary["subsystem_errors"]["router"] == 2
        assert summary["subsystem_errors"]["workflow"] == 1

    def test_get_summary(self, metrics):
        """Full summary contains all sections."""
        metrics.record_request()
        metrics.record_provider_call(provider="gemini", input_tokens=50)
        metrics.record_tool_call(tool_name="echo")
        summary = metrics.get_summary()
        assert "total_requests" in summary
        assert "provider_stats" in summary
        assert "tool_stats" in summary
        assert "subsystem_errors" in summary

    def test_provider_stats_to_dict(self):
        """ProviderStats serialises correctly."""
        stats = ProviderStats(
            call_count=5, input_tokens=1000, output_tokens=500,
            total_duration_ms=2500, error_count=1
        )
        d = stats.to_dict()
        assert d["call_count"] == 5
        assert d["avg_duration_ms"] == 500.0
        assert d["error_rate"] == 0.2

    def test_tool_stats_to_dict(self):
        """ToolStats serialises correctly."""
        stats = ToolStats(call_count=10, error_count=2, total_duration_ms=100)
        d = stats.to_dict()
        assert d["call_count"] == 10
        assert d["avg_duration_ms"] == 10.0

    def test_empty_provider_stats(self):
        """Empty ProviderStats returns zeros."""
        stats = ProviderStats()
        assert stats.avg_duration_ms == 0.0
        assert stats.error_rate == 0.0


# ---------------------------------------------------------------------------
# Tool tests
# ---------------------------------------------------------------------------


class TestObservabilityTool:
    """Tests for ObservabilityTool."""

    def _make_tool(self, obs_store, metrics):
        from tools.builtin.observability_tool import ObservabilityTool
        return ObservabilityTool(obs_store, metrics)

    def test_name_and_description(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        assert tool.name == "observability"
        assert "read-only" in tool.description.lower() or "safe" in tool.description.lower()

    def test_metrics_query(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        metrics.record_request()
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "metrics"}))
        assert result.success
        assert "Total requests: 1" in result.output

    def test_traces_query_empty(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "traces"}))
        assert result.success
        assert "No traces recorded yet" in result.output

    def test_traces_query_with_data(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        obs_store.start_trace(trace_id="t1", user_input="hello")
        obs_store.end_trace(trace_id="t1", status="completed")
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "traces"}))
        assert result.success
        assert "t1" in result.output

    def test_providers_query(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        metrics.record_provider_call(provider="claude", input_tokens=100)
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "providers"}))
        assert result.success
        assert "claude" in result.output

    def test_tools_query(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        metrics.record_tool_call(tool_name="echo")
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "tools"}))
        assert result.success
        assert "echo" in result.output

    def test_unknown_query(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "bogus"}))
        assert not result.success
        assert "Unknown" in result.error

    def test_default_query_is_metrics(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        result = tool.run(ToolRequest(tool_name="observability", input_data={}))
        assert result.success
        assert "Metrics Summary" in result.output

    def test_providers_empty(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "providers"}))
        assert result.success
        assert "No provider stats" in result.output

    def test_tools_empty(self, obs_store, metrics):
        tool = self._make_tool(obs_store, metrics)
        result = tool.run(ToolRequest(tool_name="observability", input_data={"query": "tools"}))
        assert result.success
        assert "No tool stats" in result.output
