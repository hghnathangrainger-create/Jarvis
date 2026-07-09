"""
test_workflow_engine.py

Focused unit tests for the Phase 15, Batch 2 Sequential Workflow Engine
(workflow/engine.py).

These prove the engine's own narrow responsibilities - sequencing,
delegation to the real ToolExecutor/SecurityManager/ApprovalManager,
STOP-only failure semantics, pause/resume, previous-step propagation, and
audit events - using fake tools (not the concrete MemoryTool/
MemoryForgetTool implementations, which already have their own tests).
No CommandRouter, Orchestrator, or CLI test is included here (Phase 15
Batch 2 scope only).

Run with:
    pytest tests/unit/test_workflow_engine.py
"""

from __future__ import annotations

import ast
import inspect

import pytest

from approval.approval_manager import ApprovalManager
from config.constants import EventOutcome, SecurityTier, StepStatus
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine, WorkflowError
from workflow.workflow_models import WorkflowStepOutcome

# --- Fake tools (deliberately not the concrete MemoryTool implementation) ---


class _GreenTool(BaseTool):
    """A GREEN tool ("read..." is classified GREEN by the real
    SecurityManager) that always succeeds, optionally producing metadata."""

    def __init__(self, name: str = "green_tool", metadata: dict[str, str] | None = None) -> None:
        self._name = name
        self._metadata = metadata or {}
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake GREEN tool for engine tests."

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(
            tool_name=self.name, success=True, output="ok", metadata=dict(self._metadata)
        )


class _FailingGreenTool(BaseTool):
    """A GREEN tool whose run() always reports a genuine (non-security)
    failure."""

    def __init__(self, name: str = "failing_tool") -> None:
        self._name = name
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake GREEN tool that always fails."

    def action_for(self, request: ToolRequest) -> str:
        return "read something that fails"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=False, error="Simulated failure.")


class _YellowTool(BaseTool):
    """A YELLOW tool ("delete..." is classified YELLOW by the real
    SecurityManager) that only truly runs once approved."""

    def __init__(self, name: str = "yellow_tool") -> None:
        self._name = name
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake YELLOW tool for engine tests."

    def action_for(self, request: ToolRequest) -> str:
        return "delete something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="deleted")


class _RedTool(BaseTool):
    """A RED tool ("format drive..." is classified RED and always
    blocked - run() should never be reached)."""

    def __init__(self, name: str = "red_tool") -> None:
        self._name = name
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake RED tool for engine tests."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive C"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="should never run")


class _ProducerTool(BaseTool):
    """A GREEN tool that produces the one Phase 15 propagated field."""

    def __init__(self, name: str = "producer", memory_id: str | None = "42") -> None:
        self._name = name
        self._memory_id = memory_id
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake tool producing memory_id metadata."

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        metadata = {"memory_id": self._memory_id} if self._memory_id is not None else {}
        return ToolResult(tool_name=self.name, success=True, output="produced", metadata=metadata)


class _ConsumerTool(BaseTool):
    """A GREEN tool that records the input_data it actually received, so
    tests can assert exactly what propagated."""

    def __init__(self, name: str = "consumer") -> None:
        self._name = name
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake tool recording its received input."

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="consumed")


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FailingLogger:
    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("simulated logger failure")


# --- Fixtures/helpers ---------------------------------------------------------


def _security() -> SecurityManager:
    return SecurityManager()


def _registry(*tools: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register_tool(tool)
    return registry


def _executor(registry: ToolRegistry, logger: object, security: SecurityManager) -> ToolExecutor:
    return ToolExecutor(registry=registry, security_manager=security, logger=logger)  # type: ignore[arg-type]


def _approvals(logger: object | None = None) -> ApprovalManager:
    return ApprovalManager(audit_logger=logger)  # type: ignore[arg-type]


def _step(
    number: int,
    tool_name: str | None,
    *,
    tool_input: dict[str, object] | None = None,
    input_from_previous_step: bool = False,
) -> PlanStep:
    return PlanStep(
        number=number,
        description=f"Step {number}.",
        action="placeholder",
        tier=SecurityTier.GREEN,
        reason="placeholder",
        tool_name=tool_name,
        tool_input=tool_input or {},
        input_from_previous_step=input_from_previous_step,
    )


def _plan(*steps: PlanStep) -> Plan:
    return Plan(user_request="a workflow request", steps=steps)


def _engine(
    *tools: BaseTool, logger: object | None = None
) -> tuple[WorkflowEngine, ToolExecutor, ApprovalManager]:
    """Build an engine wired to real collaborators.

    `logger`, when supplied, is used only as WorkflowEngine's own
    workflow_* audit logger - ToolExecutor/ApprovalManager always get
    their own separate, working _RecordingLogger, exactly as a real
    composition root would wire two independently-configured collaborators
    (both happen to point at the same real EventLogger in production, but
    nothing here requires that, and a test proving WorkflowEngine's own
    logger-failure isolation must not be confounded by ToolExecutor's own,
    separately-owned, already-tested-elsewhere logger behaviour).
    """
    security = _security()
    registry = _registry(*tools)
    executor = _executor(registry, _RecordingLogger(), security)
    approvals = _approvals(_RecordingLogger())
    return (
        WorkflowEngine(executor=executor, approvals=approvals, logger=logger),
        executor,
        approvals,
    )


# --- Plan validation ----------------------------------------------------------


def test_valid_two_step_linear_plan_is_accepted() -> None:
    green_a, green_b = _GreenTool("a"), _GreenTool("b")
    engine, _, approvals = _engine(green_a, green_b)
    plan = _plan(_step(1, "a"), _step(2, "b"))
    result = engine.run(plan)
    assert result.overall_status is StepStatus.COMPLETED


def test_zero_step_plan_is_rejected() -> None:
    engine, _, approvals = _engine()
    with pytest.raises(WorkflowError):
        engine.run(_plan())


def test_duplicate_step_number_is_rejected() -> None:
    tool = _GreenTool("a")
    engine, _, approvals = _engine(tool)
    plan = _plan(_step(1, "a"), _step(1, "a"))
    with pytest.raises(WorkflowError):
        engine.run(plan)
    assert tool.calls == []


def test_unordered_step_numbers_are_rejected() -> None:
    tool = _GreenTool("a")
    engine, _, approvals = _engine(tool)
    plan = _plan(_step(1, "a"), _step(3, "a"))
    with pytest.raises(WorkflowError):
        engine.run(plan)
    assert tool.calls == []


def test_first_step_input_from_previous_step_is_rejected() -> None:
    tool = _GreenTool("a")
    engine, _, approvals = _engine(tool)
    plan = _plan(_step(1, "a", input_from_previous_step=True))
    with pytest.raises(WorkflowError):
        engine.run(plan)
    assert tool.calls == []


def test_missing_tool_name_is_rejected() -> None:
    engine, _, approvals = _engine()
    plan = _plan(_step(1, None))
    with pytest.raises(WorkflowError):
        engine.run(plan)


def test_blank_tool_name_is_rejected() -> None:
    engine, _, approvals = _engine()
    plan = _plan(_step(1, "   "))
    with pytest.raises(WorkflowError):
        engine.run(plan)


def test_invalid_plan_never_partially_executes() -> None:
    first, second = _GreenTool("a"), _GreenTool("b")
    engine, _, approvals = _engine(first, second)
    # step 2's number is wrong (should be 2, is 5) -> whole plan rejected
    plan = _plan(_step(1, "a"), _step(5, "b"))
    with pytest.raises(WorkflowError):
        engine.run(plan)
    assert first.calls == []
    assert second.calls == []


# --- All-GREEN sequencing ------------------------------------------------------


def test_two_green_steps_execute_in_order() -> None:
    first, second = _GreenTool("a"), _GreenTool("b")
    engine, _, approvals = _engine(first, second)
    plan = _plan(_step(1, "a"), _step(2, "b"))

    result = engine.run(plan)

    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert [o.status for o in result.step_outcomes] == [
        StepStatus.COMPLETED,
        StepStatus.COMPLETED,
    ]
    assert result.overall_status is StepStatus.COMPLETED
    assert not engine.has_paused(result.workflow_id)


def test_workflow_completed_audit_emitted_after_second_success() -> None:
    logger = _RecordingLogger()
    engine, _, approvals = _engine(_GreenTool("a"), _GreenTool("b"), logger=logger)
    plan = _plan(_step(1, "a"), _step(2, "b"))

    engine.run(plan)

    action_types = [c["action_type"] for c in logger.calls]
    assert action_types.count("workflow_completed") == 1
    assert action_types[-1] == "workflow_completed"


# --- Failure/blocked -----------------------------------------------------------


def test_first_step_failure_stops_second() -> None:
    failing, second = _FailingGreenTool("f"), _GreenTool("b")
    engine, _, approvals = _engine(failing, second)
    plan = _plan(_step(1, "f"), _step(2, "b"))

    result = engine.run(plan)

    assert len(second.calls) == 0
    assert result.overall_status is StepStatus.FAILED
    assert len(result.step_outcomes) == 1
    assert result.step_outcomes[0].status is StepStatus.FAILED


def test_second_step_failure_preserves_first_completed_outcome() -> None:
    first, failing = _GreenTool("a"), _FailingGreenTool("f")
    engine, _, approvals = _engine(first, failing)
    plan = _plan(_step(1, "a"), _step(2, "f"))

    result = engine.run(plan)

    assert len(result.step_outcomes) == 2
    assert result.step_outcomes[0].status is StepStatus.COMPLETED
    assert result.step_outcomes[1].status is StepStatus.FAILED
    assert result.overall_status is StepStatus.FAILED


def test_red_blocked_result_maps_to_failed_status() -> None:
    red_tool = _RedTool("r")
    engine, _, approvals = _engine(red_tool)
    plan = _plan(_step(1, "r"))

    result = engine.run(plan)

    assert red_tool.calls == []  # RED is blocked before run() by ToolExecutor
    assert result.overall_status is StepStatus.FAILED
    assert result.step_outcomes[0].tool_result.blocked is True


def test_red_block_stops_later_steps() -> None:
    red_tool, later = _RedTool("r"), _GreenTool("later")
    engine, _, approvals = _engine(red_tool, later)
    plan = _plan(_step(1, "r"), _step(2, "later"))

    result = engine.run(plan)

    assert later.calls == []
    assert len(result.step_outcomes) == 1


def test_no_retry_on_failure() -> None:
    failing = _FailingGreenTool("f")
    engine, _, approvals = _engine(failing)
    engine.run(_plan(_step(1, "f")))
    assert len(failing.calls) == 1


# --- Approval / pause -----------------------------------------------------------


def test_yellow_step_returns_waiting() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    plan = _plan(_step(1, "y"))

    result = engine.run(plan)

    assert result.overall_status is StepStatus.WAITING
    assert yellow.calls == []  # not truly run yet - only classified/paused
    assert result.pending_approval_request is not None


def test_real_approval_request_is_preserved() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    result = engine.run(_plan(_step(1, "y")))

    request = result.pending_approval_request
    assert request is not None
    assert request.security_tier is SecurityTier.YELLOW
    assert request.action == "placeholder"  # PlanStep.action, unchanged


def test_later_steps_not_executed_while_waiting() -> None:
    yellow, later = _YellowTool("y"), _GreenTool("later")
    engine, _, approvals = _engine(yellow, later)
    plan = _plan(_step(1, "y"), _step(2, "later"))

    engine.run(plan)

    assert later.calls == []


def test_has_paused_true_while_waiting() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    result = engine.run(_plan(_step(1, "y")))
    assert engine.has_paused(result.workflow_id) is True


def test_run_rejected_while_another_workflow_paused() -> None:
    yellow = _YellowTool("y")
    green = _GreenTool("g")
    engine, _, approvals = _engine(yellow, green)
    engine.run(_plan(_step(1, "y")))

    with pytest.raises(WorkflowError):
        engine.run(_plan(_step(1, "g")))


# --- Resume ----------------------------------------------------------------


def test_approved_resume_executes_exactly_once() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    result = engine.run(_plan(_step(1, "y")))
    request = result.pending_approval_request
    decision = approvals.approve(request.request_id)

    resumed = engine.resume(result.workflow_id, decision)

    assert len(yellow.calls) == 1
    assert resumed.overall_status is StepStatus.COMPLETED
    assert resumed.step_outcomes[0].status is StepStatus.COMPLETED


def test_waiting_step_becomes_completed_and_later_step_runs() -> None:
    yellow, later = _YellowTool("y"), _GreenTool("later")
    engine, _, approvals = _engine(yellow, later)
    result = engine.run(_plan(_step(1, "y"), _step(2, "later")))
    decision = approvals.approve(result.pending_approval_request.request_id)

    resumed = engine.resume(result.workflow_id, decision)

    assert len(later.calls) == 1
    assert resumed.overall_status is StepStatus.COMPLETED
    assert len(resumed.step_outcomes) == 2


def test_declined_decision_stops_workflow_without_running_tool() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    result = engine.run(_plan(_step(1, "y")))
    decision = approvals.decline(result.pending_approval_request.request_id)

    resumed = engine.resume(result.workflow_id, decision)

    assert yellow.calls == []
    assert resumed.overall_status is StepStatus.FAILED


def test_declined_decision_does_not_run_later_steps() -> None:
    yellow, later = _YellowTool("y"), _GreenTool("later")
    engine, _, approvals = _engine(yellow, later)
    result = engine.run(_plan(_step(1, "y"), _step(2, "later")))
    decision = approvals.decline(result.pending_approval_request.request_id)

    engine.resume(result.workflow_id, decision)

    assert later.calls == []


def test_second_resume_of_same_workflow_id_raises_and_does_not_reexecute() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    result = engine.run(_plan(_step(1, "y")))
    decision = approvals.approve(result.pending_approval_request.request_id)

    engine.resume(result.workflow_id, decision)
    assert len(yellow.calls) == 1

    with pytest.raises(WorkflowError):
        engine.resume(result.workflow_id, decision)
    assert len(yellow.calls) == 1  # not called again


def test_resume_of_unknown_workflow_id_raises_and_executes_nothing() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    from approval.approval_models import ApprovalRequest

    fake_request = ApprovalRequest(
        action="placeholder", reason="r", security_tier=SecurityTier.YELLOW
    )
    decision = fake_request.decide(approved=True, decided_by="test")

    with pytest.raises(WorkflowError):
        engine.resume("unknown-workflow-id", decision)
    assert yellow.calls == []


def test_has_paused_false_after_terminal_resume() -> None:
    yellow = _YellowTool("y")
    engine, _, approvals = _engine(yellow)
    result = engine.run(_plan(_step(1, "y")))
    decision = approvals.approve(result.pending_approval_request.request_id)

    engine.resume(result.workflow_id, decision)

    assert engine.has_paused(result.workflow_id) is False


def test_failed_approved_execution_stops_workflow() -> None:
    class _FailsWhenApproved(BaseTool):
        def __init__(self) -> None:
            self._name = "fails_when_approved"
            self.calls: list[ToolRequest] = []

        @property
        def name(self) -> str:
            return self._name

        @property
        def description(self) -> str:
            return "Fails once truly run."

        def action_for(self, request: ToolRequest) -> str:
            return "delete something"

        def run(self, request: ToolRequest) -> ToolResult:
            self.calls.append(request)
            return ToolResult(tool_name=self.name, success=False, error="boom")

    tool = _FailsWhenApproved()
    engine, _, approvals = _engine(tool)
    result = engine.run(_plan(_step(1, "fails_when_approved")))
    decision = approvals.approve(result.pending_approval_request.request_id)

    resumed = engine.resume(result.workflow_id, decision)

    assert resumed.overall_status is StepStatus.FAILED
    assert len(tool.calls) == 1


def test_terminal_workflow_allows_a_later_run() -> None:
    engine, _, approvals = _engine(_GreenTool("a"))
    first = engine.run(_plan(_step(1, "a")))
    assert first.overall_status is StepStatus.COMPLETED

    second = engine.run(_plan(_step(1, "a")))
    assert second.overall_status is StepStatus.COMPLETED
    assert second.workflow_id != first.workflow_id


def test_new_engine_instance_cannot_resume_another_instances_workflow() -> None:
    yellow = _YellowTool("y")
    engine_a, _, approvals = _engine(yellow)
    approvals = engine_a._approvals
    result = engine_a.run(_plan(_step(1, "y")))
    decision = approvals.approve(result.pending_approval_request.request_id)

    engine_b, _, approvals = _engine(yellow)
    with pytest.raises(WorkflowError):
        engine_b.resume(result.workflow_id, decision)


# --- Previous-step propagation --------------------------------------------------


def test_propagation_copies_memory_id_into_next_step_input() -> None:
    producer, consumer = _ProducerTool("p", memory_id="42"), _ConsumerTool("c")
    engine, _, approvals = _engine(producer, consumer)
    plan = _plan(
        _step(1, "p"),
        _step(2, "c", input_from_previous_step=True),
    )

    engine.run(plan)

    assert consumer.calls[0].input_data.get("memory_id") == "42"


def test_static_tool_input_is_preserved_alongside_propagated_field() -> None:
    producer, consumer = _ProducerTool("p", memory_id="7"), _ConsumerTool("c")
    engine, _, approvals = _engine(producer, consumer)
    plan = _plan(
        _step(1, "p"),
        _step(2, "c", tool_input={"operation": "get"}, input_from_previous_step=True),
    )

    engine.run(plan)

    assert consumer.calls[0].input_data == {"operation": "get", "memory_id": "7"}


def test_missing_structured_previous_output_fails_honestly() -> None:
    producer, consumer = _ProducerTool("p", memory_id=None), _ConsumerTool("c")
    engine, _, approvals = _engine(producer, consumer)
    plan = _plan(_step(1, "p"), _step(2, "c", input_from_previous_step=True))

    result = engine.run(plan)

    assert consumer.calls == []
    assert result.overall_status is StepStatus.FAILED
    assert len(result.step_outcomes) == 2
    assert result.step_outcomes[1].status is StepStatus.FAILED


def test_no_message_text_parsing_for_propagation() -> None:
    """A memory_id-shaped substring in .output must never be picked up -
    only tool_result.metadata is read."""

    class _MessageOnlyTool(BaseTool):
        @property
        def name(self) -> str:
            return "message_only"

        @property
        def description(self) -> str:
            return "Produces a memory_id-looking output string, no metadata."

        def action_for(self, request: ToolRequest) -> str:
            return "read something"

        def run(self, request: ToolRequest) -> ToolResult:
            return ToolResult(
                tool_name=self.name, success=True, output="Memory 99 saved."
            )

    consumer = _ConsumerTool("c")
    engine, _, approvals = _engine(_MessageOnlyTool(), consumer)
    plan = _plan(_step(1, "message_only"), _step(2, "c", input_from_previous_step=True))

    result = engine.run(plan)

    assert consumer.calls == []
    assert result.overall_status is StepStatus.FAILED


def test_propagation_only_from_immediately_previous_step() -> None:
    """A third step cannot reach back to the first step's output - only
    the second (immediately previous) step's result is ever consulted."""
    producer = _ProducerTool("p", memory_id="1")
    middle = _GreenTool("m")  # produces no memory_id metadata
    consumer = _ConsumerTool("c")
    engine, _, approvals = _engine(producer, middle, consumer)
    plan = _plan(
        _step(1, "p"),
        _step(2, "m"),
        _step(3, "c", input_from_previous_step=True),
    )

    result = engine.run(plan)

    # Step 3 looks only at step 2's result (no memory_id there), not step 1's.
    assert consumer.calls == []
    assert result.overall_status is StepStatus.FAILED


# --- Audit ---------------------------------------------------------------------


def test_exact_event_family_and_order_for_all_green_workflow() -> None:
    logger = _RecordingLogger()
    engine, _, approvals = _engine(_GreenTool("a"), _GreenTool("b"), logger=logger)
    engine.run(_plan(_step(1, "a"), _step(2, "b")))

    action_types = [c["action_type"] for c in logger.calls]
    assert action_types == [
        "workflow_started",
        "workflow_step_started",
        "workflow_step_completed",
        "workflow_step_started",
        "workflow_step_completed",
        "workflow_completed",
    ]


def test_no_tool_input_or_content_logged() -> None:
    logger = _RecordingLogger()
    engine, _, approvals = _engine(_GreenTool("a"), logger=logger)
    plan = _plan(_step(1, "a", tool_input={"content": "a secret memory value"}))

    engine.run(plan)

    for call in logger.calls:
        assert "secret" not in str(call.get("detail", ""))


def test_logger_failure_does_not_alter_green_completion() -> None:
    engine, _, approvals = _engine(_GreenTool("a"), logger=_FailingLogger())
    result = engine.run(_plan(_step(1, "a")))
    assert result.overall_status is StepStatus.COMPLETED


def test_logger_failure_does_not_alter_waiting() -> None:
    engine, _, approvals = _engine(_YellowTool("y"), logger=_FailingLogger())
    result = engine.run(_plan(_step(1, "y")))
    assert result.overall_status is StepStatus.WAITING


def test_logger_failure_does_not_alter_failed() -> None:
    engine, _, approvals = _engine(_FailingGreenTool("f"), logger=_FailingLogger())
    result = engine.run(_plan(_step(1, "f")))
    assert result.overall_status is StepStatus.FAILED


def test_logger_failure_does_not_alter_resume_result() -> None:
    yellow = _YellowTool("y")
    security = _security()
    registry = _registry(yellow)
    executor = _executor(registry, _RecordingLogger(), security)
    approvals = ApprovalManager()  # no audit logger needed for approve()
    engine = WorkflowEngine(
        executor=executor, approvals=approvals, logger=_FailingLogger()
    )

    result = engine.run(_plan(_step(1, "y")))
    decision = approvals.approve(result.pending_approval_request.request_id)
    resumed = engine.resume(result.workflow_id, decision)

    assert resumed.overall_status is StepStatus.COMPLETED


# --- Authority boundaries -----------------------------------------------------


def test_tool_executor_called_once_per_newly_executed_step() -> None:
    a, b = _GreenTool("a"), _GreenTool("b")
    engine, _, approvals = _engine(a, b)
    engine.run(_plan(_step(1, "a"), _step(2, "b")))
    assert len(a.calls) == 1
    assert len(b.calls) == 1


def test_plan_step_tier_is_ignored_for_execution() -> None:
    """Even a step whose display-only tier says RED still runs if the
    real, live SecurityManager classification (via ToolExecutor) says
    GREEN - proving the engine never trusts PlanStep.tier."""
    tool = _GreenTool("a")
    engine, _, approvals = _engine(tool)
    red_labelled_green_step = PlanStep(
        number=1,
        description="Looks scary but isn't.",
        action="placeholder",
        tier=SecurityTier.RED,  # deliberately wrong/stale display metadata
        reason="placeholder",
        tool_name="a",
    )
    result = engine.run(_plan(red_labelled_green_step))
    assert len(tool.calls) == 1
    assert result.overall_status is StepStatus.COMPLETED


def test_engine_module_imports_no_security_manager_or_tool_registry() -> None:
    import workflow.engine as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    assert "SecurityManager" not in imported_names
    assert "ToolRegistry" not in imported_names
    assert "AIReasoningEngine" not in imported_names
    assert "AIRouter" not in imported_names
    assert "AIReasoningResult" not in imported_names
    assert "PromptBuilder" not in imported_names
    assert "Planner" not in imported_names
    assert "CommandRouter" not in imported_names
    assert "JarvisOrchestrator" not in imported_names


def test_engine_never_calls_classify_action_or_tool_run_directly() -> None:
    """Structural proof, via real AST call-site inspection (not substring
    search, which would also match this module's own prose docstrings):
    workflow/engine.py contains no call whose method name is
    classify_action or run, only calls to executor.execute(...)."""
    import workflow.engine as module

    with open(module.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    called_method_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "classify_action" not in called_method_names
    assert "run" not in called_method_names
    assert "execute" in called_method_names


def test_engine_has_no_async_threading_or_persistence_code() -> None:
    import workflow.engine as module

    with open(module.__file__, encoding="utf-8") as f:
        source = f.read()

    for forbidden in ("asyncio", "threading", "async def", "await ", "sqlite3", "session_factory"):
        assert forbidden not in source


def test_every_except_exception_wraps_only_emit() -> None:
    import workflow.engine as module

    tree = ast.parse(inspect.getsource(module))
    except_bodies = [
        node.body
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and getattr(node.type, "id", None) == "Exception"
    ]
    assert len(except_bodies) == 1
    body = except_bodies[0]
    # A single Pass statement (after the comment, which is not an AST node).
    assert len(body) == 1
    assert isinstance(body[0], ast.Pass)
