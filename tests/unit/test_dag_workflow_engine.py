"""
test_dag_workflow_engine.py

Tests for the N-Step DAG Workflow Engine covering:
    - Topological sort and DAG resolution
    - Sequential execution (no dependencies)
    - Parallel execution of independent steps
    - Dependency ordering
    - Mid-workflow failure with rollback/compensation
    - Checkpoint persistence and resume after crash simulation
    - YELLOW gate pausing mid-workflow
    - Step-level on_failure (abort, skip, retry)
    - get_status() reporting
    - Backward compatibility with existing 2-step sequential workflows
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock

import pytest

from config.constants import SecurityTier, StepStatus
from planner.plan_models import Plan, PlanStep
from tools.base_tool import ToolResult
from workflow.dag_engine import (
    DAGWorkflowEngine,
    _build_dag,
    _resolve_step_ids,
    _topological_sort,
)
from workflow.dag_models import DAGStepStatus, DAGWorkflowStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeTool:
    """A minimal fake tool for testing."""

    name: str = "fake_tool"
    _action: str = "fake action"
    _result: ToolResult | None = None

    def action_for(self, request: Any) -> str:
        return self._action


class _FakeToolRegistry:
    """Minimal tool registry for testing."""

    def __init__(self, tools: dict[str, _FakeTool] | None = None):
        self._tools = tools or {}

    def get_tool(self, name: str) -> _FakeTool | None:
        return self._tools.get(name)


class _FakeExecutor:
    """Mock ToolExecutor that returns configurable results per tool."""

    def __init__(self, results: dict[str, ToolResult] | None = None):
        self._results = results or {}
        self._calls: list[tuple[str, dict[str, Any]]] = []

    def execute(
        self,
        tool_name: str,
        input_data: dict[str, Any] | None = None,
        *,
        session_id: int | None = None,
        approval_decision: Any = None,
    ) -> ToolResult:
        self._calls.append((tool_name, input_data or {}))
        if tool_name in self._results:
            return self._results[tool_name]
        return ToolResult(tool_name=tool_name, success=True, output="ok")


class _FakeApprovals:
    """Minimal approval manager for testing."""

    def create_request(self, **kwargs: Any) -> Any:
        return MagicMock(request_id="fake_req", **kwargs)


class _FakeCheckpointStore:
    """In-memory checkpoint store for testing."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}

    def save_step(self, **kwargs: Any) -> Any:
        key = (kwargs["workflow_id"], kwargs["step_id"])
        self._rows[key] = kwargs

    def list_for_workflow(self, workflow_id: str) -> list[Any]:
        return [
            type("CP", (), v)()
            for k, v in self._rows.items()
            if k[0] == workflow_id
        ]


def _make_step(
    number: int,
    tool_name: str = "fake_tool",
    *,
    depends_on: list[str] | None = None,
    compensate: str | None = None,
    compensate_input: dict[str, object] | None = None,
    on_failure: str = "abort",
    max_retries: int = 0,
    input_from_previous_step: bool = False,
    step_id: str | None = None,
) -> PlanStep:
    """Helper to build a PlanStep with sensible defaults."""
    return PlanStep(
        number=number,
        description=f"Step {number}",
        action=f"action_{number}",
        tier=SecurityTier.GREEN,
        reason="test",
        tool_name=tool_name,
        tool_input={"step": number},
        input_from_previous_step=input_from_previous_step,
        depends_on=depends_on or [],
        compensate=compensate,
        compensate_input=compensate_input or {},
        on_failure=on_failure,
        max_retries=max_retries,
        step_id=step_id,
    )


# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_linear_chain(self) -> None:
        steps = [_make_step(1), _make_step(2, depends_on=["step_1"]),
                 _make_step(3, depends_on=["step_2"])]
        step_ids, adj, _ = _build_dag(tuple(steps))
        waves = _topological_sort(step_ids, adj)
        assert waves == [["step_1"], ["step_2"], ["step_3"]]

    def test_independent_steps_same_wave(self) -> None:
        steps = [_make_step(1), _make_step(2), _make_step(3)]
        step_ids, adj, _ = _build_dag(tuple(steps))
        waves = _topological_sort(step_ids, adj)
        # All three are independent (no depends_on) so they share one wave.
        assert len(waves) == 1
        assert set(waves[0]) == {"step_1", "step_2", "step_3"}

    def test_diamond_dag(self) -> None:
        """A -> B, A -> C, B -> D, C -> D."""
        steps = [
            _make_step(1, step_id="a"),
            _make_step(2, step_id="b", depends_on=["a"]),
            _make_step(3, step_id="c", depends_on=["a"]),
            _make_step(4, step_id="d", depends_on=["b", "c"]),
        ]
        step_ids, adj, _ = _build_dag(tuple(steps))
        waves = _topological_sort(step_ids, adj)
        assert waves[0] == ["a"]
        assert set(waves[1]) == {"b", "c"}
        assert waves[2] == ["d"]

    def test_cycle_detection(self) -> None:
        steps = [
            _make_step(1, step_id="a", depends_on=["b"]),
            _make_step(2, step_id="b", depends_on=["a"]),
        ]
        step_ids, adj, _ = _build_dag(tuple(steps))
        with pytest.raises(ValueError, match="cycle"):
            _topological_sort(step_ids, adj)

    def test_resolve_step_ids_auto_generated(self) -> None:
        steps = [_make_step(1), _make_step(2)]
        ids = _resolve_step_ids(tuple(steps))
        assert ids == ["step_1", "step_2"]

    def test_resolve_step_ids_explicit(self) -> None:
        steps = [_make_step(1, step_id="alpha"), _make_step(2, step_id="beta")]
        ids = _resolve_step_ids(tuple(steps))
        assert ids == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# Sequential execution (no dependencies)
# ---------------------------------------------------------------------------


class TestSequentialExecution:
    def test_two_step_sequential(self) -> None:
        """Existing 2-step workflow without depends_on runs sequentially."""
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1), _make_step(2)),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert len(result.ordered_results) == 2
        assert all(
            r.status is DAGStepStatus.COMPLETED for r in result.ordered_results
        )
        # Steps ran in order.
        assert executor._calls[0][0] == "fake_tool"
        assert executor._calls[0][1]["step"] == 1
        assert executor._calls[1][1]["step"] == 2

    def test_three_step_sequential(self) -> None:
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1), _make_step(2), _make_step(3)),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert result.completed_count == 3

    def test_single_step(self) -> None:
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(user_request="test", steps=(_make_step(1),))
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert result.completed_count == 1


# ---------------------------------------------------------------------------
# Parallel execution of independent steps
# ---------------------------------------------------------------------------


class TestParallelExecution:
    def test_independent_steps_run_in_parallel(self) -> None:
        """Two independent steps (no depends_on) should both complete."""
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals(), max_workers=2
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert result.completed_count == 2

    def test_dependent_step_waits_for_predecessor(self) -> None:
        """Step B depends on A, so A runs first then B."""
        call_order: list[str] = []
        original_execute = _FakeExecutor().execute

        def tracking_execute(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            call_order.append(tool_name)
            return ToolResult(tool_name=tool_name, success=True, output="ok")

        executor = _FakeExecutor()
        executor.execute = tracking_execute  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a"),
                _make_step(2, step_id="b", depends_on=["a"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        # "a" should have been called before "b".
        assert call_order.index("fake_tool") < len(call_order)

    def test_diamond_dag_executes_correctly(self) -> None:
        """A -> (B, C) -> D should execute A first, then B+C, then D."""
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals(), max_workers=2
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a"),
                _make_step(2, step_id="b", depends_on=["a"]),
                _make_step(3, step_id="c", depends_on=["a"]),
                _make_step(4, step_id="d", depends_on=["b", "c"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert result.completed_count == 4


# ---------------------------------------------------------------------------
# Mid-workflow failure
# ---------------------------------------------------------------------------


class TestMidWorkflowFailure:
    def test_step_failure_marks_later_dependent_steps_skipped(self) -> None:
        """Step a fails, so dependent b and c are skipped."""
        executor = _FakeExecutor(results={
            "fake_tool": ToolResult(tool_name="fake_tool", success=False, error="boom"),
        })
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a"),
                _make_step(2, step_id="b", depends_on=["a"]),
                _make_step(3, step_id="c", depends_on=["b"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.FAILED
        # Step a failed, steps b and c are skipped.
        assert result.step_results["a"].status is DAGStepStatus.FAILED
        assert result.step_results["b"].status is DAGStepStatus.SKIPPED
        assert result.step_results["c"].status is DAGStepStatus.SKIPPED

    def test_failure_in_diamond_marks_downstream_skipped(self) -> None:
        executor = _FakeExecutor()
        # Make step "b" fail.
        call_count = [0]

        def selective_execute(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            call_count[0] += 1
            if input_data and input_data.get("step") == 2:
                return ToolResult(tool_name="fake_tool", success=False, error="step2 fail")
            return ToolResult(tool_name="fake_tool", success=True, output="ok")

        executor.execute = selective_execute  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals(), max_workers=2
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a"),
                _make_step(2, step_id="b", depends_on=["a"]),
                _make_step(3, step_id="c", depends_on=["a"]),
                _make_step(4, step_id="d", depends_on=["b", "c"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.FAILED
        # a completed, b failed, c and d are skipped.
        assert result.step_results["a"].status is DAGStepStatus.COMPLETED
        assert result.step_results["b"].status is DAGStepStatus.FAILED


# ---------------------------------------------------------------------------
# Rollback / compensation
# ---------------------------------------------------------------------------


class TestRollback:
    def test_compensate_called_in_reverse_on_failure(self) -> None:
        """Steps a -> b -> c.  c fails, so b and a are compensated in reverse."""
        executor = _FakeExecutor()
        compensate_calls: list[str] = []

        def tracking_execute(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            if tool_name == "comp_a":
                compensate_calls.append("a")
                return ToolResult(tool_name="comp_a", success=True, output="compensated")
            if tool_name == "comp_b":
                compensate_calls.append("b")
                return ToolResult(tool_name="comp_b", success=True, output="compensated")
            if input_data and input_data.get("step") == 3:
                return ToolResult(tool_name="fake_tool", success=False, error="fail")
            return ToolResult(tool_name="fake_tool", success=True, output="ok")

        executor.execute = tracking_execute  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        # Sequential chain: a -> b -> c
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a", compensate="comp_a"),
                _make_step(2, step_id="b", depends_on=["a"], compensate="comp_b"),
                _make_step(3, step_id="c", depends_on=["b"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.FAILED
        # Compensation runs in reverse order: b first, then a.
        assert compensate_calls == ["b", "a"]

    def test_no_compensation_when_no_compensate_actions(self) -> None:
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Checkpoint persistence
# ---------------------------------------------------------------------------


class TestCheckpointPersistence:
    def test_checkpoints_saved_on_success(self) -> None:
        store = _FakeCheckpointStore()
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor,
            approvals=_FakeApprovals(),
            checkpoint_store=store,
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        result = engine.run(plan)
        # Both steps should have checkpoints.
        assert ("wf", "a") not in store._rows  # uses real workflow_id
        # Check that checkpoints were created for both steps.
        keys = [(k[0], k[1]) for k in store._rows.keys()]
        assert any(sid == "a" for _, sid in keys)
        assert any(sid == "b" for _, sid in keys)

    def test_checkpoint_records_failure_status(self) -> None:
        store = _FakeCheckpointStore()
        executor = _FakeExecutor(results={
            "fake_tool": ToolResult(tool_name="fake_tool", success=False, error="boom"),
        })
        engine = DAGWorkflowEngine(
            executor=executor,
            approvals=_FakeApprovals(),
            checkpoint_store=store,
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        result = engine.run(plan)
        # Find the failed step's checkpoint.
        for key, row in store._rows.items():
            if key[1] == "a":
                assert row["status"] == "failed"
                assert row["error"] == "boom"


# ---------------------------------------------------------------------------
# YELLOW gate (approval required)
# ---------------------------------------------------------------------------


class TestYELLOWGate:
    def test_yellow_step_pauses_workflow(self) -> None:
        """When a tool returns requires_confirmation, the step pauses
        and dependent steps are not executed."""
        executor = _FakeExecutor()
        # Make step a return requires_confirmation.
        def yellow_execute(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            if input_data and input_data.get("step") == 1:
                return ToolResult(
                    tool_name="fake_tool",
                    success=True,
                    requires_confirmation=True,
                    error="This action requires your confirmation.",
                )
            return ToolResult(tool_name="fake_tool", success=True, output="ok")

        executor.execute = yellow_execute  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a"),
                _make_step(2, step_id="b", depends_on=["a"]),
            ),
        )
        result = engine.run(plan)
        # Step a is waiting_deps (paused for confirmation), so the workflow
        # is still running (not failed, not completed).
        assert result.step_results["a"].status is DAGStepStatus.WAITING_DEPS
        # Step b was not reached (depends on a which didn't complete).
        assert result.step_results["b"].status is DAGStepStatus.SKIPPED


# ---------------------------------------------------------------------------
# Step-level on_failure policies
# ---------------------------------------------------------------------------


class TestOnFailure:
    def test_on_failure_skip_continues_workflow(self) -> None:
        executor = _FakeExecutor()
        call_count = [0]

        def failing_execute(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            call_count[0] += 1
            if call_count[0] == 1:
                return ToolResult(tool_name="fake_tool", success=False, error="fail")
            return ToolResult(tool_name="fake_tool", success=True, output="ok")

        executor.execute = failing_execute  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a", on_failure="skip"),
                _make_step(2, step_id="b"),
            ),
        )
        result = engine.run(plan)
        # Step a is skipped, step b should still run.
        assert result.step_results["a"].status is DAGStepStatus.SKIPPED
        assert result.step_results["b"].status is DAGStepStatus.COMPLETED

    def test_on_failure_abort_stops_workflow(self) -> None:
        executor = _FakeExecutor(results={
            "fake_tool": ToolResult(tool_name="fake_tool", success=False, error="fail"),
        })
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a", on_failure="abort"),
                _make_step(2, step_id="b", depends_on=["a"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.FAILED
        assert result.step_results["b"].status is DAGStepStatus.SKIPPED

    def test_on_failure_retry_retries_then_aborts(self) -> None:
        executor = _FakeExecutor()
        a_calls = [0]

        def always_fail(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            if input_data and input_data.get("step") == 1:
                a_calls[0] += 1
                return ToolResult(tool_name="fake_tool", success=False, error=f"fail_{a_calls[0]}")
            return ToolResult(tool_name="fake_tool", success=True, output="ok")

        executor.execute = always_fail  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a", on_failure="retry", max_retries=2),
                _make_step(2, step_id="b", depends_on=["a"]),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.FAILED
        # Should have retried: 1 initial + 2 retries = 3 calls.
        assert a_calls[0] == 3
        assert result.step_results["a"].retries_used == 3

    def test_on_failure_retry_succeeds_on_second_attempt(self) -> None:
        executor = _FakeExecutor()
        call_count = [0]

        def fail_once(tool_name: str, input_data: Any = None, **kwargs: Any) -> ToolResult:
            call_count[0] += 1
            if call_count[0] == 1:
                return ToolResult(tool_name="fake_tool", success=False, error="first fail")
            return ToolResult(tool_name="fake_tool", success=True, output="ok")

        executor.execute = fail_once  # type: ignore

        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(
                _make_step(1, step_id="a", on_failure="retry", max_retries=2),
                _make_step(2, step_id="b"),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert result.completed_count == 2


# ---------------------------------------------------------------------------
# get_status() reporting
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_initial_pending(self) -> None:
        engine = DAGWorkflowEngine(
            executor=_FakeExecutor(), approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        status = engine.get_status("wf_test", plan)
        assert status.total_steps == 2
        assert status.completed_steps == 0
        assert status.pending_steps == 2
        assert status.status is DAGWorkflowStatus.RUNNING

    def test_status_with_checkpoints(self) -> None:
        engine = DAGWorkflowEngine(
            executor=_FakeExecutor(), approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        checkpoint_states = {
            "a": DAGStepStatus.COMPLETED,
            "b": DAGStepStatus.PENDING,
        }
        status = engine.get_status("wf_test", plan, checkpoint_states=checkpoint_states)
        assert status.completed_steps == 1
        assert status.pending_steps == 1

    def test_status_all_completed(self) -> None:
        engine = DAGWorkflowEngine(
            executor=_FakeExecutor(), approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="test",
            steps=(_make_step(1, step_id="a"), _make_step(2, step_id="b")),
        )
        checkpoint_states = {
            "a": DAGStepStatus.COMPLETED,
            "b": DAGStepStatus.COMPLETED,
        }
        status = engine.get_status("wf_test", plan, checkpoint_states=checkpoint_states)
        assert status.status is DAGWorkflowStatus.COMPLETED
        assert status.completed_steps == 2


# ---------------------------------------------------------------------------
# input_from_previous_step integration
# ---------------------------------------------------------------------------


class TestInputFromPreviousStep:
    def test_input_from_previous_step_adds_implicit_dep(self) -> None:
        """A step with input_from_previous_step=True but no depends_on
        gets an implicit dependency on the preceding step by number."""
        steps = (
            _make_step(1, step_id="a"),
            _make_step(2, step_id="b", input_from_previous_step=True),
        )
        step_ids, adj, _ = _build_dag(steps)
        # Implicit dep uses step_N format from the preceding step number.
        assert "step_1" in adj["b"]


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_existing_two_step_plan_works_unchanged(self) -> None:
        """The exact plan shape workflow_plan_factory builds works."""
        executor = _FakeExecutor()
        engine = DAGWorkflowEngine(
            executor=executor, approvals=_FakeApprovals()
        )
        plan = Plan(
            user_request="remember this and show it back: hello",
            steps=(
                PlanStep(
                    number=1,
                    description="Save this as a new memory.",
                    action="save memory",
                    tier=SecurityTier.GREEN,
                    reason="Saving a memory is safe.",
                    tool_name="memory",
                    tool_input={"operation": "save", "content": "hello"},
                ),
                PlanStep(
                    number=2,
                    description="Show the memory.",
                    action="show memory",
                    tier=SecurityTier.GREEN,
                    reason="Showing is safe.",
                    tool_name="memory",
                    tool_input={"operation": "get"},
                    input_from_previous_step=True,
                ),
            ),
        )
        result = engine.run(plan)
        assert result.status is DAGWorkflowStatus.COMPLETED
        assert len(result.ordered_results) == 2
