"""
dag_models.py

Data models for N-step DAG workflow execution (Phase: DAG Workflow Engine).

Responsibilities:
    - Define DAGStepStatus: per-step execution status within a DAG workflow.
    - Define DAGWorkflowStatus: overall workflow status.
    - Define DAGStepResult: result of executing one DAG step.
    - Define DAGWorkflowResult: the outcome of a complete DAG workflow run.

Does NOT:
    - Execute anything (see workflow/dag_engine.py).
    - Persist anything (see workflow/checkpoint_store.py).
    - Replace or modify workflow.workflow_models.WorkflowResult.  The
      existing sequential WorkflowResult stays untouched and is still
      used by the existing WorkflowEngine for all pre-DAG workflows.

These are pure data models describing the shape of DAG workflow outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from config.constants import StepStatus
from tools.base_tool import ToolResult


class DAGStepStatus(Enum):
    """Execution status of a single step within a DAG workflow.

    Extends the existing StepStatus with values needed for DAG-specific
    lifecycle tracking.  The existing StepStatus is kept for backward
    compatibility with the sequential engine.
    """

    PENDING = "pending"
    WAITING_DEPS = "waiting_deps"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLING_BACK = "rolling_back"
    COMPENSATED = "compensated"


class DAGWorkflowStatus(Enum):
    """Overall status of a DAG workflow."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    WAITING_APPROVAL = "waiting_approval"


@dataclass(frozen=True, slots=True)
class DAGStepResult:
    """The result of executing one step within a DAG workflow.

    Attributes:
        step_id: The step's stable identifier.
        step_number: The 1-based step number.
        status: The step's final status after execution.
        tool_result: The ToolResult from the step's execution, if any.
        error: A short error message if the step failed.
        retries_used: How many retries were consumed.
    """

    step_id: str
    step_number: int
    status: DAGStepStatus
    tool_result: ToolResult | None = None
    error: str | None = None
    retries_used: int = 0


@dataclass(frozen=True, slots=True)
class DAGWorkflowResult:
    """The outcome of running (or resuming) a complete DAG workflow.

    Attributes:
        workflow_id: A correlation identifier for this workflow run.
        status: The overall workflow status.
        step_results: Outcomes of every step actually attempted, keyed
            by step_id.
        ordered_results: Outcomes in step_number order (for display).
        message: A human-readable summary.
        session_id: Optional session identifier for the audit trail.
    """

    workflow_id: str
    status: DAGWorkflowStatus
    step_results: dict[str, DAGStepResult] = field(default_factory=dict)
    ordered_results: tuple[DAGStepResult, ...] = field(default_factory=tuple)
    message: str = ""
    session_id: int | None = None

    @property
    def completed_count(self) -> int:
        """Number of steps that completed successfully."""
        return sum(
            1 for r in self.step_results.values()
            if r.status is DAGStepStatus.COMPLETED
        )

    @property
    def failed_count(self) -> int:
        """Number of steps that failed."""
        return sum(
            1 for r in self.step_results.values()
            if r.status is DAGStepStatus.FAILED
        )

    @property
    def skipped_count(self) -> int:
        """Number of steps that were skipped."""
        return sum(
            1 for r in self.step_results.values()
            if r.status is DAGStepStatus.SKIPPED
        )


@dataclass(frozen=True, slots=True)
class DAGWorkflowStatusInfo:
    """Status snapshot returned by get_status().

    Provides a structured view of where a workflow is in its execution,
    which steps are done, which are pending, and which failed.

    Attributes:
        workflow_id: The workflow's correlation id.
        status: The overall workflow status.
        step_statuses: Mapping of step_id -> DAGStepStatus for every
            step in the plan.
        total_steps: Total number of steps in the plan.
        completed_steps: Number of completed steps.
        failed_steps: Number of failed steps.
        pending_steps: Number of steps still pending or waiting.
    """

    workflow_id: str
    status: DAGWorkflowStatus
    step_statuses: dict[str, DAGStepStatus] = field(default_factory=dict)
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    pending_steps: int = 0
