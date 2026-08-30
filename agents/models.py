"""
models.py

Agent data models for the Jarvis AI Operating System.

Responsibilities:
    - Define AgentType enum (RESEARCH, CODING, CONTENT, LEARNING, TRADING, PLANNER_SUPPORT).
    - Define AgentStatus enum (CREATED → INITIALIZED → AVAILABLE → ASSIGNED → WORKING → COMPLETED/FAILED/WAITING).
    - Define AgentConfig for agent configuration.
    - Define AgentTask for task assignments.
    - Define AgentResult for task outcomes.

Does NOT:
    - Implement agent logic (see base.py and concrete agents).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import uuid


class AgentType(Enum):
    """The type of specialised agent.

    Attributes:
        RESEARCH: Research and information gathering.
        CODING: Code generation and validation.
        CONTENT: Content creation and formatting.
        LEARNING: Educational content and study plans.
        TRADING: Market research and analysis (education only, no trades).
        PLANNER_SUPPORT: Workflow planning suggestions.
    """

    RESEARCH = "research"
    CODING = "coding"
    CONTENT = "content"
    LEARNING = "learning"
    TRADING = "trading"
    PLANNER_SUPPORT = "planner_support"


class AgentStatus(Enum):
    """Lifecycle status of an agent or task.

    Attributes:
        CREATED: Agent instance created but not yet initialized.
        INITIALIZED: Agent loaded models/tools, ready to become available.
        AVAILABLE: Agent is idle and ready to accept tasks.
        ASSIGNED: Agent has been assigned a task but hasn't started.
        WORKING: Agent is actively executing a task.
        COMPLETED: Agent finished the task successfully.
        FAILED: Agent encountered an error during execution.
        WAITING: Agent is waiting for external input or resource.
    """

    CREATED = "created"
    INITIALIZED = "initialized"
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING = "waiting"


@dataclass
class AgentConfig:
    """Configuration for an agent instance.

    Attributes:
        agent_type: The type of agent.
        max_execution_time: Maximum seconds before forced termination (default 300).
        allowed_tools: List of tool access tiers (default ["GREEN"]).
        description: Human-readable description.
        system_prompt: System prompt for the agent's AI interactions.
    """

    agent_type: AgentType
    max_execution_time: int = 300
    allowed_tools: list[str] = field(default_factory=lambda: ["GREEN"])
    description: str = ""
    system_prompt: str = ""


@dataclass
class AgentTask:
    """A task assigned to an agent.

    Attributes:
        task_id: Unique task identifier.
        agent_type: The agent type to handle this task.
        prompt: The task description/prompt.
        context: Additional context data.
        assigned_at: When the task was assigned.
        started_at: When execution began.
        completed_at: When execution finished.
        status: Current task status.
        result: The task result text.
        error: Error message if failed.
    """

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: AgentType = AgentType.RESEARCH
    prompt: str = ""
    context: dict = field(default_factory=dict)
    assigned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: AgentStatus = AgentStatus.CREATED
    result: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "task_id": self.task_id,
            "agent_type": self.agent_type.value,
            "prompt": self.prompt,
            "context": self.context,
            "assigned_at": self.assigned_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class AgentResult:
    """The outcome of an agent task execution.

    Attributes:
        task_id: The task identifier.
        agent_type: The agent that executed the task.
        result: The result text.
        tokens_used: Number of tokens consumed.
        duration_ms: Execution duration in milliseconds.
        status: Final task status.
    """

    task_id: str = ""
    agent_type: AgentType = AgentType.RESEARCH
    result: str = ""
    tokens_used: int = 0
    duration_ms: int = 0
    status: AgentStatus = AgentStatus.COMPLETED

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dict."""
        return {
            "task_id": self.task_id,
            "agent_type": self.agent_type.value,
            "result": self.result,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
            "status": self.status.value,
        }
