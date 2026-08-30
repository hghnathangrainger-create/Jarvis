"""
agent_tool.py

YELLOW-tier tool for managing AI agents in the Jarvis AI Operating System.

Provides actions:
  - run: Assign and execute a task with a specific agent type
  - status: Show all agents and their current state
  - results: Show recent completed agent tasks
  - terminate: Stop a running agent task
"""

from __future__ import annotations

from typing import Any

from agents.manager import AgentManager
from agents.models import AgentType
from tools.base_tool import BaseTool, ToolRequest, ToolResult


class AgentTool(BaseTool):
    """Tool for managing AI agent tasks."""

    @property
    def name(self) -> str:
        return "agent"

    @property
    def description(self) -> str:
        return "Manage AI agents: run tasks, check status, view results, terminate"

    tier = "YELLOW"

    def __init__(self, agent_manager: AgentManager | None = None) -> None:
        """Initialise the agent tool.

        Args:
            agent_manager: The AgentManager instance.
        """
        self._manager = agent_manager

    def run(self, request: ToolRequest) -> ToolResult:
        """Execute an agent management action.

        Args:
            request: The tool request with input_data containing action, etc.

        Returns:
            ToolResult with agent information.
        """
        kwargs = request.input_data
        action = kwargs.get("action", "status")

        if self._manager is None:
            return self.fail("Agent manager not available.")

        try:
            if action == "run":
                return self._handle_run(kwargs)
            elif action == "status":
                return self._handle_status()
            elif action == "results":
                return self._handle_results(kwargs)
            elif action == "terminate":
                return self._handle_terminate(kwargs)
            else:
                return self.fail(f"Unknown action: {action}. Supported: run, status, results, terminate")
        except Exception as e:
            return self.fail(f"Error: {e}")

    def _handle_run(self, kwargs: dict) -> ToolResult:
        """Handle run action — assign and execute a task."""
        agent_type_str = kwargs.get("agent_type", "")
        prompt = kwargs.get("prompt", "")
        context = kwargs.get("context", {})

        if not agent_type_str:
            return self.fail("No agent_type provided. Use: research, coding, content, learning, trading, planner_support")
        if not prompt:
            return self.fail("No prompt provided.")

        try:
            agent_type = AgentType(agent_type_str)
        except ValueError:
            valid = ", ".join(t.value for t in AgentType)
            return self.fail(f"Invalid agent_type: {agent_type_str}. Valid: {valid}")

        # Assign and execute
        task = self._manager.assign_task(agent_type, prompt, context)
        if task is None:
            return self.fail(f"No available agent of type {agent_type_str}.")

        result = self._manager.execute_task(task)

        lines = [
            f"=== Agent Task Result ===",
            f"  Task ID:    {result.task_id}",
            f"  Agent:      {result.agent_type.value}",
            f"  Status:     {result.status.value}",
            f"  Duration:   {result.duration_ms}ms",
            f"  Tokens:     {result.tokens_used}",
            "",
            "  Result:",
        ]

        # Indent result text
        for line in result.result.split("\n")[:50]:  # Limit to 50 lines
            lines.append(f"    {line}")

        if result.status.value == "failed":
            lines.append("")
            lines.append(f"  Error: {task.error or 'Unknown error'}")

        return self.ok("\n".join(lines))

    def _handle_status(self) -> ToolResult:
        """Handle status action — show all agents."""
        status = self._manager.get_status()

        lines = [
            "=== Agent Status ===",
            f"  Total Agents:    {status['total_agents']}",
            f"  Available:       {status['available_agents']}",
            f"  Busy:            {status['busy_agents']}",
            f"  Completed Tasks: {status['completed_tasks']}",
            "",
        ]

        for agent_type, info in status["agents"].items():
            status_icon = {
                "available": "🟢",
                "working": "🟡",
                "assigned": "🟠",
                "failed": "🔴",
            }.get(info["status"], "⚪")

            lines.append(f"  {status_icon} {agent_type.upper()}")
            lines.append(f"    Status: {info['status']}")
            lines.append(f"    Max Time: {info['max_execution_time']}s")
            if info["current_task"]:
                lines.append(f"    Current Task: {info['current_task']['task_id'][:8]}...")
            lines.append("")

        return self.ok("\n".join(lines))

    def _handle_results(self, kwargs: dict) -> ToolResult:
        """Handle results action — show recent completed tasks."""
        limit = kwargs.get("limit", 10)
        results = self._manager.list_completed(limit=limit)

        if not results:
            return self.ok("No completed tasks yet.")

        lines = ["=== Recent Agent Tasks ===", ""]

        for result in results:
            status_icon = "✅" if result.status.value == "completed" else "❌"
            lines.append(f"  {status_icon} [{result.agent_type.value}] {result.task_id[:8]}...")
            lines.append(f"    Status: {result.status.value} | Duration: {result.duration_ms}ms | Tokens: {result.tokens_used}")
            if result.result:
                preview = result.result[:100].replace("\n", " ")
                lines.append(f"    Preview: {preview}...")
            lines.append("")

        return self.ok("\n".join(lines))

    def _handle_terminate(self, kwargs: dict) -> ToolResult:
        """Handle terminate action — stop a running task."""
        task_id = kwargs.get("task_id", "")

        if not task_id:
            return self.fail("No task_id provided.")

        success = self._manager.terminate_task(task_id)
        if success:
            return self.ok(f"Task {task_id} terminated.")
        else:
            return self.fail(f"No running task found with ID: {task_id}")
