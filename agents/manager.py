"""
manager.py

Agent Manager for the Jarvis AI Operating System.

Responsibilities:
    - Register and manage agent instances.
    - Assign tasks to available agents.
    - Execute tasks with timeout enforcement.
    - Track agent status and completed tasks.

Does NOT:
    - Implement agent logic (delegates to BaseAgent subclasses).
    - Override the Planner or Security Manager.
"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import BaseAgent
from agents.models import AgentResult, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)


class AgentManager:
    """Manages all AI agents and their task execution.

    Coordinates agent registration, task assignment, execution, and
    status tracking. Enforces safety constraints and timeout limits.

    Attributes:
        _agents: Dict mapping AgentType to BaseAgent instances.
        _completed_tasks: List of recently completed task results.
        _max_completed: Maximum number of completed tasks to retain.
    """

    def __init__(self, max_completed: int = 100) -> None:
        """Initialise the agent manager.

        Args:
            max_completed: Maximum number of completed tasks to retain in history.
        """
        self._agents: dict[AgentType, BaseAgent] = {}
        self._completed_tasks: list[AgentResult] = []
        self._max_completed = max_completed

    def register_agent(self, agent: BaseAgent) -> None:
        """Register an agent with the manager.

        Args:
            agent: The agent instance to register.
        """
        agent_type = agent.agent_type
        self._agents[agent_type] = agent
        logger.info("Registered agent: %s", agent_type.value)

    def get_agent(self, agent_type: AgentType) -> BaseAgent | None:
        """Get an agent by type.

        Args:
            agent_type: The type of agent to retrieve.

        Returns:
            The agent instance, or None if not registered.
        """
        return self._agents.get(agent_type)

    def get_available_agent(self, agent_type: AgentType) -> BaseAgent | None:
        """Get an available agent of the specified type.

        Args:
            agent_type: The type of agent needed.

        Returns:
            An available agent instance, or None if none available.
        """
        agent = self._agents.get(agent_type)
        if agent is not None and agent.status == AgentStatus.AVAILABLE:
            return agent
        return None

    def assign_task(
        self,
        agent_type: AgentType,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> AgentTask | None:
        """Find an available agent and assign a task.

        Args:
            agent_type: The type of agent needed.
            prompt: The task prompt.
            context: Optional context data.

        Returns:
            The assigned AgentTask, or None if no agent available.
        """
        agent = self.get_available_agent(agent_type)
        if agent is None:
            logger.warning("No available agent of type %s", agent_type.value)
            return None

        task = AgentTask(
            agent_type=agent_type,
            prompt=prompt,
            context=context or {},
        )

        logger.info(
            "Assigned task %s to agent %s",
            task.task_id,
            agent_type.value,
        )
        return task

    def execute_task(self, task: AgentTask) -> AgentResult:
        """Execute a task with the appropriate agent.

        Args:
            task: The task to execute.

        Returns:
            The task result.
        """
        agent = self.get_agent(task.agent_type)
        if agent is None:
            return AgentResult(
                task_id=task.task_id,
                agent_type=task.agent_type,
                result="",
                status=AgentStatus.FAILED,
            )

        result = agent.execute(task)

        # Store completed task
        self._completed_tasks.append(result)
        if len(self._completed_tasks) > self._max_completed:
            self._completed_tasks = self._completed_tasks[-self._max_completed:]

        return result

    def terminate_task(self, task_id: str) -> bool:
        """Terminate a running task.

        Args:
            task_id: The ID of the task to terminate.

        Returns:
            True if a task was terminated.
        """
        for agent in self._agents.values():
            if (
                agent.current_task is not None
                and agent.current_task.task_id == task_id
            ):
                agent.terminate()
                return True
        return False

    def get_status(self) -> dict[str, Any]:
        """Get the status of all agents.

        Returns:
            Dict with agent statuses and summary information.
        """
        agents_info = {}
        for agent_type, agent in self._agents.items():
            agents_info[agent_type.value] = agent.get_info()

        return {
            "agents": agents_info,
            "total_agents": len(self._agents),
            "available_agents": sum(
                1 for a in self._agents.values()
                if a.status == AgentStatus.AVAILABLE
            ),
            "busy_agents": sum(
                1 for a in self._agents.values()
                if a.status in (AgentStatus.WORKING, AgentStatus.ASSIGNED)
            ),
            "completed_tasks": len(self._completed_tasks),
        }

    def list_completed(self, limit: int = 20) -> list[AgentResult]:
        """List recent completed tasks.

        Args:
            limit: Maximum number of results to return.

        Returns:
            List of AgentResult objects, newest first.
        """
        return list(reversed(self._completed_tasks[-limit:]))

    def get_all_agents(self) -> list[BaseAgent]:
        """Get all registered agents.

        Returns:
            List of all agent instances.
        """
        return list(self._agents.values())
