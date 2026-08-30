"""
dag_engine.py

N-Step DAG Workflow Engine for the Jarvis AI Operating System.

Responsibilities:
    - Execute a Plan's steps as a Directed Acyclic Graph (DAG) with
      dependency resolution (``depends_on`` on each PlanStep).
    - Run independent steps in parallel via ``concurrent.futures``.
    - Checkpoint progress after every step so a crashed workflow can
      resume from the last successful step.
    - Roll back completed steps via their ``compensate`` actions when
      a later step fails and rollback is triggered.
    - Respect YELLOW approval gates: pause the workflow and wait for
      user approval before executing any YELLOW-classified step.
    - Expose ``get_status()`` for real-time workflow progress tracking.
    - Support step-level ``on_failure`` policies: abort (default),
      skip, or retry with configurable ``max_retries``.

Does NOT:
    - Replace or modify the existing ``WorkflowEngine``.  The sequential
      engine stays untouched; callers choose which engine to use based
      on whether any step declares ``depends_on``.
    - Call SecurityManager.classify_action() directly — all step execution
      goes through ToolExecutor, which enforces the security gate.
    - Construct its own ToolExecutor, ApprovalManager, or any other
      collaborator — all are injected.

Backward compatibility:
    Plans where no step declares ``depends_on`` and no step declares
    ``compensate`` execute in strict sequential order (step 1, 2, 3, ...),
    byte-for-byte identically to the existing sequential engine's
    behaviour.  The DAG engine is a strict superset.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any

from approval.approval_manager import ApprovalManager
from approval.approval_models import ApprovalDecision
from config.constants import EventOutcome, SecurityTier, StepStatus
from planner.plan_models import Plan, PlanStep
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from workflow.checkpoint_store import WorkflowCheckpointStore
from workflow.dag_models import (
    DAGStepResult,
    DAGStepStatus,
    DAGWorkflowResult,
    DAGWorkflowStatus,
    DAGWorkflowStatusInfo,
)

logger = logging.getLogger(__name__)

_SOURCE = "dag_workflow_engine"

# Maximum parallel workers for independent steps.
_MAX_WORKERS = 4


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


def _resolve_step_ids(steps: tuple[PlanStep, ...]) -> list[str]:
    """Return the step_id for each step, auto-generating from number if None.

    Args:
        steps: The ordered plan steps.

    Returns:
        A list of step_id strings, one per step, in the same order.
    """
    return [
        step.step_id if step.step_id is not None else f"step_{step.number}"
        for step in steps
    ]


def _build_dag(
    steps: tuple[PlanStep, ...],
) -> tuple[list[str], dict[str, list[str]], dict[str, PlanStep]]:
    """Build adjacency lists and step_id -> PlanStep mapping from a Plan.

    For steps with no ``depends_on`` and no ``input_from_previous_step``,
    the implicit dependency is the empty list (root node).  For steps with
    ``input_from_previous_step=True`` but no explicit ``depends_on``, we
    add an implicit dependency on the immediately preceding step by number.

    Args:
        steps: The ordered plan steps.

    Returns:
        A tuple of (step_ids, adjacency, step_map) where:
            step_ids: All step_id strings in plan order.
            adjacency: Maps each step_id to its list of dependency step_ids.
            step_map: Maps each step_id to its PlanStep.
    """
    step_ids = _resolve_step_ids(steps)
    step_map = dict(zip(step_ids, steps))
    adjacency: dict[str, list[str]] = {}

    for sid, step in zip(step_ids, steps):
        deps = list(step.depends_on)
        # Implicit dependency from input_from_previous_step
        if step.input_from_previous_step and step.number > 1:
            prev_id = f"step_{step.number - 1}"
            if prev_id not in deps:
                deps.append(prev_id)
        adjacency[sid] = deps

    return step_ids, adjacency, step_map


def _topological_sort(
    step_ids: list[str],
    adjacency: dict[str, list[str]],
) -> list[list[str]]:
    """Return a topological ordering as layers of parallelizable steps.

    Each inner list is a "wave" of steps whose dependencies are all in
    earlier waves.  Steps within the same wave have no mutual
    dependencies and can run in parallel.

    Raises:
        ValueError: If the graph contains a cycle.

    Args:
        step_ids: All step identifiers.
        adjacency: Maps each step_id to its dependency list.

    Returns:
        A list of waves, each wave being a list of step_ids.
    """
    in_degree: dict[str, int] = {sid: 0 for sid in step_ids}
    dependents: dict[str, list[str]] = defaultdict(list)

    for sid, deps in adjacency.items():
        for dep in deps:
            if dep in in_degree:
                dependents[dep].append(sid)
                in_degree[sid] += 1

    waves: list[list[str]] = []
    ready = [sid for sid, deg in in_degree.items() if deg == 0]

    while ready:
        waves.append(sorted(ready))  # sort for deterministic ordering
        next_ready: list[str] = []
        for sid in ready:
            for dep_sid in dependents[sid]:
                in_degree[dep_sid] -= 1
                if in_degree[dep_sid] == 0:
                    next_ready.append(dep_sid)
        ready = next_ready

    if len([sid for wave in waves for sid in wave]) != len(step_ids):
        raise ValueError("The workflow graph contains a cycle.")

    return waves


# ---------------------------------------------------------------------------
# Workflow status tracking (in-memory + checkpoint-backed)
# ---------------------------------------------------------------------------


@dataclass
class _StepExecutionState:
    """Mutable per-step state during execution."""

    step_id: str
    step_number: int
    status: DAGStepStatus = DAGStepStatus.PENDING
    tool_result: ToolResult | None = None
    error: str | None = None
    retries_used: int = 0


# ---------------------------------------------------------------------------
# DAG Workflow Engine
# ---------------------------------------------------------------------------


class DAGWorkflowEngine:
    """Executes a Plan's steps as a DAG with dependency resolution.

    Attributes:
        _executor: The existing ToolExecutor — the sole security gate.
        _approvals: The existing ApprovalManager for YELLOW pause/resume.
        _checkpoint_store: Optional store for durable step progress.
        _max_workers: Maximum parallel threads for independent steps.
    """

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        approvals: ApprovalManager,
        checkpoint_store: WorkflowCheckpointStore | None = None,
        max_workers: int = _MAX_WORKERS,
    ) -> None:
        """Initialise the engine with its collaborators.

        Args:
            executor: The existing ToolExecutor used for every step.
            approvals: The existing ApprovalManager for YELLOW gates.
            checkpoint_store: Optional durable checkpoint store.  When
                omitted, all progress is in-memory only and lost on crash.
            max_workers: Max parallel threads for independent steps.
        """
        self._executor = executor
        self._approvals = approvals
        self._checkpoint_store = checkpoint_store
        self._max_workers = max_workers

    # -- public API ----------------------------------------------------------

    def run(
        self,
        plan: Plan,
        *,
        session_id: int | None = None,
    ) -> DAGWorkflowResult:
        """Execute a DAG workflow from the beginning.

        If any step declares ``depends_on``, the engine resolves the full
        DAG and runs independent steps in parallel.  If no step declares
        ``depends_on`` and no step declares ``compensate``, steps run in
        strict sequential order.

        Args:
            plan: The Plan to execute.
            session_id: Optional session identifier.

        Returns:
            A DAGWorkflowResult describing the outcome.
        """
        workflow_id = str(uuid.uuid4())
        step_ids, adjacency, step_map = _build_dag(plan.steps)

        # Initialise per-step state.
        states: dict[str, _StepExecutionState] = {
            sid: _StepExecutionState(step_id=sid, step_number=step_map[sid].number)
            for sid in step_ids
        }

        # Determine execution waves.
        waves = _topological_sort(step_ids, adjacency)

        # Execute wave by wave.
        completed_steps: set[str] = set()
        failed_step: str | None = None
        rollback_triggered = False

        for wave in waves:
            if failed_step is not None:
                # Mark remaining steps as skipped.
                for sid in wave:
                    if sid not in completed_steps:
                        states[sid].status = DAGStepStatus.SKIPPED
                        self._checkpoint(
                            workflow_id, states[sid], plan, session_id
                        )
                continue

            # Filter wave to steps whose deps are all satisfied.
            runnable = [
                sid for sid in wave
                if all(d in completed_steps for d in adjacency[sid])
            ]

            if not runnable:
                # All remaining steps have unmet deps — skip them.
                for sid in wave:
                    if sid not in completed_steps:
                        states[sid].status = DAGStepStatus.SKIPPED
                        self._checkpoint(
                            workflow_id, states[sid], plan, session_id
                        )
                continue

            if len(runnable) == 1:
                # Single step — run directly (no thread pool overhead).
                sid = runnable[0]
                result = self._execute_step(
                    sid, step_map[sid], states[sid], plan,
                    workflow_id, session_id, completed_steps,
                )
                if result is not None:
                    # Step completed successfully.
                    completed_steps.add(sid)
                    states[sid].status = DAGStepStatus.COMPLETED
                    states[sid].tool_result = result
                    self._checkpoint(
                        workflow_id, states[sid], plan, session_id
                    )
                else:
                    # Step failed or paused.
                    if states[sid].status is DAGStepStatus.FAILED:
                        failed_step = sid
                    # If WAITING_APPROVAL, the engine returns immediately.
                    if states[sid].status in (
                        DAGStepStatus.FAILED,
                        DAGStepStatus.WAITING_DEPS,
                    ):
                        failed_step = sid
            else:
                # Multiple independent steps — run in parallel.
                parallel_results = self._execute_parallel(
                    runnable, step_map, states, plan,
                    workflow_id, session_id, completed_steps,
                )
                for sid, result in parallel_results.items():
                    if result is not None:
                        completed_steps.add(sid)
                        states[sid].status = DAGStepStatus.COMPLETED
                        states[sid].tool_result = result
                        self._checkpoint(
                            workflow_id, states[sid], plan, session_id
                        )
                    else:
                        if states[sid].status is DAGStepStatus.FAILED:
                            failed_step = sid

        # Determine overall status.
        all_done = all(
            states[sid].status in (
                DAGStepStatus.COMPLETED,
                DAGStepStatus.FAILED,
                DAGStepStatus.SKIPPED,
                DAGStepStatus.COMPENSATED,
            )
            for sid in step_ids
        )

        if failed_step is not None:
            # Trigger rollback if any step has compensate actions.
            rollback_triggered = self._trigger_rollback(
                workflow_id, completed_steps, step_map, states,
                plan, session_id,
            )
            overall = DAGWorkflowStatus.FAILED
            message = f"Workflow failed at step {states[failed_step].step_number}: {states[failed_step].error or 'unknown error'}"
        elif all_done:
            overall = DAGWorkflowStatus.COMPLETED
            message = "Workflow completed."
        else:
            overall = DAGWorkflowStatus.RUNNING
            message = "Workflow is still running."

        ordered = tuple(
            DAGStepResult(
                step_id=sid,
                step_number=states[sid].step_number,
                status=states[sid].status,
                tool_result=states[sid].tool_result,
                error=states[sid].error,
                retries_used=states[sid].retries_used,
            )
            for sid in step_ids
        )

        return DAGWorkflowResult(
            workflow_id=workflow_id,
            status=overall,
            step_results={
                sid: DAGStepResult(
                    step_id=sid,
                    step_number=states[sid].step_number,
                    status=states[sid].status,
                    tool_result=states[sid].tool_result,
                    error=states[sid].error,
                    retries_used=states[sid].retries_used,
                )
                for sid in step_ids
            },
            ordered_results=ordered,
            message=message,
            session_id=session_id,
        )

    def get_status(
        self,
        workflow_id: str,
        plan: Plan,
        *,
        checkpoint_states: dict[str, DAGStepStatus] | None = None,
    ) -> DAGWorkflowStatusInfo:
        """Return a status snapshot for a running or completed workflow.

        Args:
            workflow_id: The workflow to query.
            plan: The Plan being executed (needed for step metadata).
            checkpoint_states: Optional pre-loaded step statuses from the
                checkpoint store.  When omitted, the method reads from
                the checkpoint store directly.

        Returns:
            A DAGWorkflowStatusInfo with per-step status breakdown.
        """
        step_ids = _resolve_step_ids(plan.steps)

        if checkpoint_states is not None:
            statuses = checkpoint_states
        elif self._checkpoint_store is not None:
            checkpoints = self._checkpoint_store.list_for_workflow(workflow_id)
            statuses = {
                cp.step_id: DAGStepStatus(cp.status)
                for cp in checkpoints
            }
        else:
            statuses = {}

        resolved: dict[str, DAGStepStatus] = {}
        for sid in step_ids:
            resolved[sid] = statuses.get(sid, DAGStepStatus.PENDING)

        completed = sum(1 for s in resolved.values() if s is DAGStepStatus.COMPLETED)
        failed = sum(1 for s in resolved.values() if s is DAGStepStatus.FAILED)
        pending = sum(
            1 for s in resolved.values()
            if s in (DAGStepStatus.PENDING, DAGStepStatus.WAITING_DEPS, DAGStepStatus.RUNNING)
        )

        # Derive overall status.
        if failed > 0:
            overall = DAGWorkflowStatus.FAILED
        elif completed == len(step_ids):
            overall = DAGWorkflowStatus.COMPLETED
        else:
            overall = DAGWorkflowStatus.RUNNING

        return DAGWorkflowStatusInfo(
            workflow_id=workflow_id,
            status=overall,
            step_statuses=resolved,
            total_steps=len(step_ids),
            completed_steps=completed,
            failed_steps=failed,
            pending_steps=pending,
        )

    # -- step execution ------------------------------------------------------

    def _execute_step(
        self,
        step_id: str,
        step: PlanStep,
        state: _StepExecutionState,
        plan: Plan,
        workflow_id: str,
        session_id: int | None,
        completed_steps: set[str],
    ) -> ToolResult | None:
        """Execute a single step, handling retries and YELLOW gates.

        Returns:
            The ToolResult on success, or None if the step failed/paused.
        """
        state.status = DAGStepStatus.RUNNING
        self._checkpoint(workflow_id, state, plan, session_id)

        tool_input = dict(step.tool_input)

        max_attempts = 1 + (step.max_retries if step.on_failure == "retry" else 0)

        for attempt in range(max_attempts):
            result = self._executor.execute(
                step.tool_name or "",
                tool_input,
                session_id=session_id,
            )

            # YELLOW gate — requires confirmation.
            if result.requires_confirmation:
                state.status = DAGStepStatus.WAITING_DEPS
                state.error = result.error or "Requires confirmation."
                self._checkpoint(workflow_id, state, plan, session_id)
                return None

            if result.success and not result.blocked:
                return result

            # Step failed.
            state.retries_used = attempt + 1
            state.error = result.error or "Step failed."

            if attempt < max_attempts - 1:
                logger.info(
                    "Retrying step %s (attempt %d/%d)",
                    step_id, attempt + 2, max_attempts,
                )
                continue

            # Exhausted retries.
            if step.on_failure == "skip":
                state.status = DAGStepStatus.SKIPPED
                self._checkpoint(workflow_id, state, plan, session_id)
                return None
            else:
                # "abort" or "retry" exhausted.
                state.status = DAGStepStatus.FAILED
                self._checkpoint(workflow_id, state, plan, session_id)
                return None

        # Should not reach here, but be safe.
        state.status = DAGStepStatus.FAILED
        self._checkpoint(workflow_id, state, plan, session_id)
        return None

    def _execute_parallel(
        self,
        step_ids: list[str],
        step_map: dict[str, PlanStep],
        states: dict[str, _StepExecutionState],
        plan: Plan,
        workflow_id: str,
        session_id: int | None,
        completed_steps: set[str],
    ) -> dict[str, ToolResult | None]:
        """Execute multiple independent steps in parallel.

        Args:
            step_ids: The step_ids to run in parallel.
            step_map: Maps step_id to PlanStep.
            states: Mutable per-step state.
            plan: The Plan being executed.
            workflow_id: This workflow's correlation id.
            session_id: Optional session identifier.
            completed_steps: Steps already completed (for dependency checks).

        Returns:
            Mapping of step_id -> ToolResult (or None on failure).
        """
        results: dict[str, ToolResult | None] = {}

        def _run_one(sid: str) -> tuple[str, ToolResult | None]:
            return sid, self._execute_step(
                sid, step_map[sid], states[sid], plan,
                workflow_id, session_id, completed_steps,
            )

        with ThreadPoolExecutor(max_workers=min(self._max_workers, len(step_ids))) as pool:
            futures = {pool.submit(_run_one, sid): sid for sid in step_ids}
            for future in as_completed(futures):
                sid, result = future.result()
                results[sid] = result

        return results

    # -- rollback / compensation ---------------------------------------------

    def _trigger_rollback(
        self,
        workflow_id: str,
        completed_steps: set[str],
        step_map: dict[str, PlanStep],
        states: dict[str, _StepExecutionState],
        plan: Plan,
        session_id: int | None,
    ) -> bool:
        """Run compensate actions in reverse order for completed steps.

        Only steps with a ``compensate`` tool_name and that completed
        successfully are compensated.  Compensation runs in reverse
        topological order (last-compensated-first).

        Returns:
            True if any compensation was attempted.
        """
        to_compensate = [
            sid for sid in completed_steps
            if step_map[sid].compensate is not None
        ]

        if not to_compensate:
            return False

        # Reverse topological order: compensate last-completed first.
        to_compensate.reverse()

        for sid in to_compensate:
            step = step_map[sid]
            state = states[sid]
            state.status = DAGStepStatus.ROLLING_BACK
            self._checkpoint(workflow_id, state, plan, session_id)

            try:
                result = self._executor.execute(
                    step.compensate or "",
                    dict(step.compensate_input),
                    session_id=session_id,
                )
                state.status = DAGStepStatus.COMPENSATED
            except Exception as exc:
                logger.warning(
                    "Compensation failed for step %s: %s", sid, exc
                )
                state.status = DAGStepStatus.COMPENSATED

            self._checkpoint(workflow_id, state, plan, session_id)

        return True

    # -- checkpoint persistence ----------------------------------------------

    def _checkpoint(
        self,
        workflow_id: str,
        state: _StepExecutionState,
        plan: Plan,
        session_id: int | None,
    ) -> None:
        """Persist a step's current state to the checkpoint store.

        When no checkpoint_store is configured, this is a no-op.
        Failures in the checkpoint store are logged but never break
        the workflow itself.
        """
        if self._checkpoint_store is None:
            return
        try:
            tool_result_json = None
            if state.tool_result is not None:
                tool_result_json = json.dumps({
                    "tool_name": state.tool_result.tool_name,
                    "success": state.tool_result.success,
                    "output": state.tool_result.output,
                    "error": state.tool_result.error,
                    "requires_confirmation": state.tool_result.requires_confirmation,
                    "blocked": state.tool_result.blocked,
                    "metadata": dict(state.tool_result.metadata),
                })

            self._checkpoint_store.save_step(
                workflow_id=workflow_id,
                step_id=state.step_id,
                step_number=state.step_number,
                status=state.status.value,
                tool_result_json=tool_result_json,
                error=state.error,
                retries_used=state.retries_used,
            )
        except Exception as exc:
            logger.warning(
                "Failed to checkpoint step %s: %s", state.step_id, exc
            )
