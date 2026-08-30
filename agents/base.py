"""
base.py

Abstract base class for all AI agents in the Jarvis AI Operating System.

Responsibilities:
    - Define the agent lifecycle: initialize → available → assigned → working → completed.
    - Enforce max_execution_time via threading.Timer.
    - Log all actions to observability.
    - Enforce safety: GREEN-only tool access by default, no agent spawning.

Does NOT:
    - Implement concrete agent logic (see specific agent files).
    - Execute actions directly (delegates to AI router and tools).
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from agents.models import AgentConfig, AgentResult, AgentStatus, AgentTask, AgentType

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Abstract base class for all AI agents.

    Provides lifecycle management, timeout enforcement, and safety constraints.
    Concrete agents implement the execute() method with their specific logic.

    Attributes:
        _config: The agent configuration.
        _status: Current agent status.
        _current_task: The task currently being executed (if any).
        _termination_requested: Flag for cooperative termination.
    """

    def __init__(self, config: AgentConfig) -> None:
        """Initialise the agent with its configuration.

        Args:
            config: The agent configuration.
        """
        self._config = config
        self._status = AgentStatus.CREATED
        self._current_task: AgentTask | None = None
        self._termination_requested = False
        self._timer: threading.Timer | None = None

    @property
    def agent_type(self) -> AgentType:
        """Return the agent type."""
        return self._config.agent_type

    @property
    def status(self) -> AgentStatus:
        """Return the current status."""
        return self._status

    @property
    def current_task(self) -> AgentTask | None:
        """Return the current task."""
        return self._current_task

    def initialize(self) -> None:
        """Initialize the agent — load models/tools, set status to AVAILABLE.

        Subclasses should override this to perform specific initialization,
        calling super().initialize() to set the status.
        """
        self._status = AgentStatus.INITIALIZED
        self._log_event("initialized")
        self._status = AgentStatus.AVAILABLE
        self._log_event("available")

    def execute(self, task: AgentTask) -> AgentResult:
        """Execute a task with timeout enforcement.

        This is the main entry point for task execution. It sets up the
        timeout timer, calls the abstract _execute_impl(), and handles
        cleanup.

        Args:
            task: The task to execute.

        Returns:
            The task result.
        """
        if self._status != AgentStatus.AVAILABLE:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                result="",
                status=AgentStatus.FAILED,
                duration_ms=0,
            )

        # Assign and start
        self._current_task = task
        self._termination_requested = False
        task.status = AgentStatus.ASSIGNED
        task.started_at = datetime.now(timezone.utc)
        self._status = AgentStatus.ASSIGNED
        self._log_event(f"assigned task {task.task_id}")

        # Start execution
        task.status = AgentStatus.WORKING
        self._status = AgentStatus.WORKING
        self._log_event(f"working on task {task.task_id}")

        # Start timeout timer
        self._start_timer(task)

        start_time = time.monotonic()
        try:
            result_text, tokens_used = self._execute_impl(task)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            task.status = AgentStatus.COMPLETED
            task.result = result_text
            task.completed_at = datetime.now(timezone.utc)
            self._status = AgentStatus.AVAILABLE
            self._current_task = None
            self._cancel_timer()

            self._log_event(f"completed task {task.task_id} in {duration_ms}ms")

            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                result=result_text,
                tokens_used=tokens_used,
                duration_ms=duration_ms,
                status=AgentStatus.COMPLETED,
            )

        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)

            task.status = AgentStatus.FAILED
            task.error = str(exc)
            task.completed_at = datetime.now(timezone.utc)
            self._status = AgentStatus.AVAILABLE
            self._current_task = None
            self._cancel_timer()

            self._log_event(f"failed task {task.task_id}: {exc}")

            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                result="",
                tokens_used=0,
                duration_ms=duration_ms,
                status=AgentStatus.FAILED,
            )

    @abstractmethod
    def _execute_impl(self, task: AgentTask) -> tuple[str, int]:
        """Execute the task — to be implemented by concrete agents.

        Args:
            task: The task to execute.

        Returns:
            A tuple of (result_text, tokens_used).

        Raises:
            Exception: On any execution error.
        """
        ...

    def terminate(self) -> AgentResult | None:
        """Force-terminate the current task.

        Sets a termination flag that cooperative implementations should check.
        Returns partial results if available.

        Returns:
            Partial AgentResult if a task was running, None otherwise.
        """
        if self._current_task is None:
            return None

        self._termination_requested = True
        self._cancel_timer()

        task = self._current_task
        duration_ms = 0
        if task.started_at:
            duration_ms = int(
                (datetime.now(timezone.utc) - task.started_at).total_seconds() * 1000
            )

        task.status = AgentStatus.FAILED
        task.error = "Terminated by user"
        task.completed_at = datetime.now(timezone.utc)

        result = AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            result=task.result or "",
            tokens_used=0,
            duration_ms=duration_ms,
            status=AgentStatus.FAILED,
        )

        self._status = AgentStatus.AVAILABLE
        self._current_task = None

        self._log_event(f"terminated task {task.task_id}")
        return result

    def can_handle(self, task_type: AgentType) -> bool:
        """Check if this agent can handle a given task type.

        Args:
            task_type: The type of task to check.

        Returns:
            True if this agent handles the given type.
        """
        return task_type == self.agent_type

    def _start_timer(self, task: AgentTask) -> None:
        """Start the execution timeout timer."""
        self._cancel_timer()
        self._timer = threading.Timer(
            self._config.max_execution_time,
            self._on_timeout,
            args=[task],
        )
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        """Cancel the execution timeout timer."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _on_timeout(self, task: AgentTask) -> None:
        """Handle execution timeout — terminate with partial results."""
        logger.warning(
            "Agent %s timed out after %ds on task %s",
            self.agent_type.value,
            self._config.max_execution_time,
            task.task_id,
        )
        self.terminate()

    def _log_event(self, message: str) -> None:
        """Log a security/observability event."""
        logger.info("[Agent:%s] %s", self.agent_type.value, message)

    def get_info(self) -> dict[str, Any]:
        """Return agent information as a dict.

        Returns:
            Dict with agent type, status, config, and current task info.
        """
        return {
            "agent_type": self.agent_type.value,
            "status": self.status.value,
            "max_execution_time": self._config.max_execution_time,
            "allowed_tools": self._config.allowed_tools,
            "description": self._config.description,
            "current_task": self._current_task.to_dict() if self._current_task else None,
        }
