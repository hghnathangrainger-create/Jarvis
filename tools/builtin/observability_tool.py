"""
observability_tool.py

A GREEN tool that exposes Jarvis observability data.

Returns metrics summaries, recent traces, provider stats, or tool
usage stats. Read-only and safe — never mutates any state.

Supported operations (via the 'query' input):
    - "metrics": Full metrics summary (default).
    - "traces": Recent traces.
    - "providers": Per-provider stats.
    - "tools": Per-tool stats.
"""

from __future__ import annotations

from observability.metrics import MetricsCollector
from observability.store import ObservabilityStore
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class ObservabilityTool(BaseTool):
    """Returns observability data: metrics, traces, provider/tool stats.

    Attributes:
        _store: The observability store for reading traces/spans.
        _metrics: The in-memory metrics collector.
    """

    def __init__(
        self,
        store: ObservabilityStore,
        metrics: MetricsCollector,
    ) -> None:
        """Initialise the tool with observability collaborators.

        Args:
            store: The ObservabilityStore for reading traces/spans.
            metrics: The MetricsCollector for reading metrics.
        """
        self._store = store
        self._metrics = metrics

    @property
    def name(self) -> str:
        """Return the tool name."""
        return "observability"

    @property
    def description(self) -> str:
        """Return a short description of the tool."""
        return "Shows Jarvis observability data: metrics, traces, provider stats, tool stats. Read-only and safe."

    def run(self, request: ToolRequest) -> ToolResult:
        """Handle an observability query.

        Args:
            request: The request. Recognised input keys:
                query: "metrics", "traces", "providers", or "tools".
                limit: Max items for traces (default: 10).

        Returns:
            A ToolResult with formatted observability data.
        """
        query = str(request.input_data.get("query", "metrics")).strip().lower()

        if query == "metrics":
            return self._format_metrics()
        elif query == "traces":
            return self._format_traces(request)
        elif query == "providers":
            return self._format_providers()
        elif query == "tools":
            return self._format_tools()
        else:
            return self.fail(
                f"Unknown observability query '{query}'. "
                "Use 'metrics', 'traces', 'providers', or 'tools'."
            )

    def _format_metrics(self) -> ToolResult:
        """Format the full metrics summary."""
        summary = self._metrics.get_summary()
        lines = ["Observability Metrics Summary", "=" * 35, ""]
        lines.append(f"Total requests: {summary['total_requests']}")
        lines.append("")

        # Provider summary
        providers = summary.get("provider_stats", {})
        if providers:
            lines.append("AI Providers:")
            for name, stats in providers.items():
                lines.append(
                    f"  {name}: {stats['call_count']} calls, "
                    f"{stats['input_tokens']} in / {stats['output_tokens']} out tokens, "
                    f"avg {stats['avg_duration_ms']}ms, "
                    f"error rate {stats['error_rate']:.1%}"
                )
        else:
            lines.append("AI Providers: No calls recorded yet.")
        lines.append("")

        # Tool summary
        tools = summary.get("tool_stats", {})
        if tools:
            lines.append("Tool Usage:")
            for name, stats in sorted(tools.items()):
                lines.append(
                    f"  {name}: {stats['call_count']} calls, "
                    f"avg {stats['avg_duration_ms']}ms, "
                    f"{stats['error_count']} errors"
                )
        else:
            lines.append("Tool Usage: No calls recorded yet.")
        lines.append("")

        # Error summary
        errors = summary.get("subsystem_errors", {})
        if errors:
            lines.append("Subsystem Errors:")
            for subsystem, count in sorted(errors.items()):
                lines.append(f"  {subsystem}: {count}")
        else:
            lines.append("Subsystem Errors: None recorded.")

        return self.ok("\n".join(lines))

    def _format_traces(self, request: ToolRequest) -> ToolResult:
        """Format recent traces."""
        limit = request.input_data.get("limit", 10)
        if not isinstance(limit, int) or limit < 1:
            limit = 10
        limit = min(limit, 50)

        traces = self._store.list_recent_traces(limit=limit)
        if not traces:
            return self.ok("No traces recorded yet.")

        lines = [f"Recent Traces (last {len(traces)}):", ""]
        for t in traces:
            duration = ""
            if t.end_time and t.start_time:
                dur = int((t.end_time - t.start_time).total_seconds() * 1000)
                duration = f" [{dur}ms]"
            error = f" ERROR: {t.error}" if t.error else ""
            lines.append(
                f"  [{t.status}]{duration} {t.trace_id[:8]}... "
                f"\"{t.user_input[:60]}\"{error}"
            )

        return self.ok("\n".join(lines))

    def _format_providers(self) -> ToolResult:
        """Format per-provider stats."""
        stats = self._metrics.get_provider_stats()
        if not stats:
            return self.ok("No provider stats recorded yet.")

        lines = ["AI Provider Stats:", ""]
        for name, s in sorted(stats.items()):
            lines.append(f"  {name}:")
            lines.append(f"    Calls: {s['call_count']}")
            lines.append(f"    Input tokens: {s['input_tokens']:,}")
            lines.append(f"    Output tokens: {s['output_tokens']:,}")
            lines.append(f"    Avg duration: {s['avg_duration_ms']}ms")
            lines.append(f"    Error rate: {s['error_rate']:.1%}")
            lines.append("")

        return self.ok("\n".join(lines))

    def _format_tools(self) -> ToolResult:
        """Format per-tool usage stats."""
        stats = self._metrics.get_tool_stats()
        if not stats:
            return self.ok("No tool stats recorded yet.")

        lines = ["Tool Usage Stats:", ""]
        for name, s in sorted(stats.items()):
            lines.append(
                f"  {name}: {s['call_count']} calls, "
                f"avg {s['avg_duration_ms']}ms, "
                f"{s['error_count']} errors"
            )

        return self.ok("\n".join(lines))
