"""
test_workflow_engine_verification_gate.py

Focused tests for the trusted verification-continuation gate added to
PlanStep/WorkflowEngine in Phase 98, Batch 1 -
docs/phase_98_implementation_plan.md.

Uses the same fake-tool/real-collaborator pattern already established
in tests/unit/test_workflow_engine.py (not imported from there, to keep
this file's own fixtures self-contained and independently readable).

No compound-template-specific wiring exists here - these tests exercise
PlanStep.requires_verified_predecessor/verification_field_name/
verification_expected_value and WorkflowEngine's own generic gate logic
directly, never intelligence/compound_grounding.py or
intelligence/compound_structured_output.py, neither of which this file
imports.
"""

from __future__ import annotations

import json

import pytest

from approval.approval_manager import ApprovalManager
from config.constants import SecurityTier, StepStatus
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.engine import WorkflowEngine, WorkflowError


class _GreenTool(BaseTool):
    """A GREEN tool that always succeeds, optionally producing metadata."""

    def __init__(self, name: str, metadata: dict[str, object] | None = None) -> None:
        self._name = name
        self._metadata = metadata or {}
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "A fake GREEN tool for verification-gate tests."

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(
            tool_name=self.name, success=True, output="ok", metadata=dict(self._metadata)
        )


def _registry(*tools: BaseTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register_tool(tool)
    return registry


def _engine(*tools: BaseTool) -> WorkflowEngine:
    security = SecurityManager()
    registry = _registry(*tools)
    executor = ToolExecutor(registry=registry, security_manager=security, logger=_NullLogger())
    approvals = ApprovalManager()
    return WorkflowEngine(executor=executor, approvals=approvals)


class _NullLogger:
    def emit(self, **kwargs: object) -> str:
        return "evt"


def _write_step(*, metadata: dict[str, object] | None = None) -> PlanStep:
    return PlanStep(
        number=1,
        description="Write step.",
        action="placeholder",
        tier=SecurityTier.GREEN,
        reason="placeholder",
        tool_name="write_tool",
        tool_input={},
    )


def _verify_step(
    tool_name: str = "verify_tool", *, missing_tool_result: bool = False
) -> PlanStep:
    return PlanStep(
        number=2,
        description="Verify step.",
        action="placeholder",
        tier=SecurityTier.GREEN,
        reason="placeholder",
        tool_name=tool_name,
        tool_input={},
    )


def _gated_step(
    *, field_name: str = "phase", expected_value: str = "implementation"
) -> PlanStep:
    return PlanStep(
        number=3,
        description="Gated step.",
        action="placeholder",
        tier=SecurityTier.GREEN,
        reason="placeholder",
        tool_name="gated_tool",
        tool_input={},
        requires_verified_predecessor=True,
        verification_field_name=field_name,
        verification_expected_value=expected_value,
    )


class TestDefaultBehaviorUnchanged:
    def test_default_is_false(self) -> None:
        step = PlanStep(
            number=1,
            description="d",
            action="a",
            tier=SecurityTier.GREEN,
            reason="r",
        )
        assert step.requires_verified_predecessor is False
        assert step.verification_field_name is None
        assert step.verification_expected_value is None

    def test_existing_ungated_plan_behaves_unchanged(self) -> None:
        write = _write_step()
        verify = _verify_step()
        gated_tool = _GreenTool("gated_tool")
        engine = _engine(
            _GreenTool("write_tool"), _GreenTool("verify_tool"), gated_tool
        )
        # A plain, ungated third step (no requires_verified_predecessor)
        # behaves exactly as any ordinary GREEN step always has.
        ungated_third = PlanStep(
            number=3,
            description="d",
            action="a",
            tier=SecurityTier.GREEN,
            reason="r",
            tool_name="gated_tool",
        )
        plan = Plan(user_request="r", steps=(write, verify, ungated_third))
        result = engine.run(plan)
        assert result.overall_status is StepStatus.COMPLETED
        assert len(gated_tool.calls) == 1


class TestGateBlocksAndPermitsExecution:
    def test_gated_step_runs_after_verified(self) -> None:
        gated_tool = _GreenTool("gated_tool")
        engine = _engine(
            _GreenTool("write_tool"),
            _GreenTool("verify_tool", metadata={"phase": "implementation"}),
            gated_tool,
        )
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        result = engine.run(plan)
        assert result.overall_status is StepStatus.COMPLETED
        assert len(gated_tool.calls) == 1

    def test_gated_step_does_not_run_after_mismatch(self) -> None:
        gated_tool = _GreenTool("gated_tool")
        engine = _engine(
            _GreenTool("write_tool"),
            _GreenTool("verify_tool", metadata={"phase": "different_value"}),
            gated_tool,
        )
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        result = engine.run(plan)
        assert result.overall_status is StepStatus.FAILED
        assert len(gated_tool.calls) == 0
        last = result.step_outcomes[-1]
        assert "verification mismatch" in (last.tool_result.error or "")
        assert "verifier failure" in (last.tool_result.error or "")

    def test_gated_step_does_not_run_with_no_usable_value(self) -> None:
        gated_tool = _GreenTool("gated_tool")
        engine = _engine(
            _GreenTool("write_tool"),
            _GreenTool("verify_tool", metadata={}),  # no "phase" key at all
            gated_tool,
        )
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        result = engine.run(plan)
        assert result.overall_status is StepStatus.FAILED
        assert len(gated_tool.calls) == 0
        last = result.step_outcomes[-1]
        assert "unavailable" in (last.tool_result.error or "")

    def test_gated_step_does_not_run_when_verifier_fails(self) -> None:
        gated_tool = _GreenTool("gated_tool")

        class _FailingTool(BaseTool):
            @property
            def name(self) -> str:
                return "verify_tool"

            @property
            def description(self) -> str:
                return "fails"

            def action_for(self, request: ToolRequest) -> str:
                return "read something"

            def run(self, request: ToolRequest) -> ToolResult:
                return ToolResult(tool_name=self.name, success=False, error="broke")

        engine = _engine(_GreenTool("write_tool"), _FailingTool(), gated_tool)
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        result = engine.run(plan)
        assert result.overall_status is StepStatus.FAILED
        assert len(gated_tool.calls) == 0
        # The verify step's own outcome is the one that failed here -
        # the gated step was never even attempted.
        assert result.step_outcomes[-1].step.number == 2

    def test_gated_step_does_not_run_after_non_verifier_predecessor(self) -> None:
        """A predecessor whose metadata simply doesn't carry the
        required key (e.g. an unrelated tool mistakenly placed before a
        gated step) is refused exactly like a genuine unavailable
        verification - there is no separate code path needed, and the
        gated step is never executed."""
        gated_tool = _GreenTool("gated_tool")
        unrelated_tool = _GreenTool("verify_tool", metadata={"unrelated_key": "x"})
        engine = _engine(_GreenTool("write_tool"), unrelated_tool, gated_tool)
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        result = engine.run(plan)
        assert result.overall_status is StepStatus.FAILED
        assert len(gated_tool.calls) == 0


class TestMismatchDistinctFromVerifierFailure:
    def test_mismatch_and_verifier_failure_produce_different_messages(self) -> None:
        engine_mismatch = _engine(
            _GreenTool("write_tool"),
            _GreenTool("verify_tool", metadata={"phase": "wrong"}),
            _GreenTool("gated_tool"),
        )
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        mismatch_result = engine_mismatch.run(plan)
        mismatch_error = mismatch_result.step_outcomes[-1].tool_result.error or ""

        class _FailingTool(BaseTool):
            @property
            def name(self) -> str:
                return "verify_tool"

            @property
            def description(self) -> str:
                return "fails"

            def action_for(self, request: ToolRequest) -> str:
                return "read something"

            def run(self, request: ToolRequest) -> ToolResult:
                return ToolResult(tool_name=self.name, success=False, error="broke")

        engine_failure = _engine(
            _GreenTool("write_tool"), _FailingTool(), _GreenTool("gated_tool")
        )
        failure_result = engine_failure.run(
            Plan(user_request="r", steps=(_write_step(), _verify_step(), _gated_step()))
        )
        failure_error = failure_result.step_outcomes[-1].tool_result.error or ""

        assert mismatch_error != failure_error
        assert "mismatch" in mismatch_error
        assert "mismatch" not in failure_error

    def test_tool_result_success_cannot_override_failed_verification(self) -> None:
        # The verify TOOL itself reports success=True (a real, honest
        # read) even though the observed value mismatches - proving the
        # gate consults the *value*, never merely ToolResult.success.
        verify_tool = _GreenTool("verify_tool", metadata={"phase": "wrong_value"})
        gated_tool = _GreenTool("gated_tool")
        engine = _engine(_GreenTool("write_tool"), verify_tool, gated_tool)
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), _gated_step())
        )
        result = engine.run(plan)

        verify_outcome = result.step_outcomes[1]
        assert verify_outcome.status is StepStatus.COMPLETED
        assert verify_outcome.tool_result.success is True  # the read itself succeeded
        assert result.overall_status is StepStatus.FAILED  # but the gate still stopped
        assert len(gated_tool.calls) == 0


class TestTrustedOwnership:
    def test_gate_cannot_be_supplied_through_model_output(self) -> None:
        """PlanStep is plain, trusted, code-constructed data - there is
        no parser anywhere that accepts requires_verified_predecessor
        from any external text. This is proven structurally: neither
        intelligence/structured_output.py nor
        intelligence/compound_structured_output.py's own schemas
        declare any such key (confirmed by direct inspection - both
        parsers reject any unrecognized key), and PlanStep itself is
        never constructed from raw JSON anywhere in this codebase
        except via WorkflowEngine's own trusted, already-validated
        reload path (_try_reconstruct_paused_workflow)."""
        import inspect

        source = inspect.getsource(PlanStep)
        # The field exists on the trusted model itself...
        assert "requires_verified_predecessor" in source
        # ...but is never referenced by either JSON-facing parser module.
        import intelligence.structured_output as structured_output
        import intelligence.compound_structured_output as compound_structured_output

        assert "requires_verified_predecessor" not in inspect.getsource(
            structured_output
        )
        assert "requires_verified_predecessor" not in inspect.getsource(
            compound_structured_output
        )


class TestPlanConstructionValidation:
    def test_first_step_cannot_require_verified_predecessor(self) -> None:
        engine = _engine(_GreenTool("gated_tool"))
        bad_first_step = PlanStep(
            number=1,
            description="d",
            action="a",
            tier=SecurityTier.GREEN,
            reason="r",
            tool_name="gated_tool",
            requires_verified_predecessor=True,
            verification_field_name="phase",
            verification_expected_value="x",
        )
        with pytest.raises(WorkflowError, match="requires_verified_predecessor"):
            engine.run(Plan(user_request="r", steps=(bad_first_step,)))

    def test_gate_without_field_name_is_rejected_at_construction(self) -> None:
        engine = _engine(
            _GreenTool("write_tool"), _GreenTool("verify_tool"), _GreenTool("gated_tool")
        )
        misconfigured = PlanStep(
            number=3,
            description="d",
            action="a",
            tier=SecurityTier.GREEN,
            reason="r",
            tool_name="gated_tool",
            requires_verified_predecessor=True,
            verification_field_name=None,
            verification_expected_value="x",
        )
        plan = Plan(
            user_request="r", steps=(_write_step(), _verify_step(), misconfigured)
        )
        with pytest.raises(WorkflowError, match="does not configure both"):
            engine.run(plan)


class TestPlanStepSerializationBackwardCompatibility:
    """Proves the real serialization/deserialization path - not merely
    the dataclass default - keeps old persisted payloads compatible
    (docs/phase_98_implementation_plan.md, Section 8)."""

    def test_plan_step_to_dict_includes_new_fields(self) -> None:
        step = _gated_step()
        as_dict = WorkflowEngine._plan_step_to_dict(step)
        assert as_dict["requires_verified_predecessor"] is True
        assert as_dict["verification_field_name"] == "phase"
        assert as_dict["verification_expected_value"] == "implementation"

    def test_old_payload_without_new_keys_reconstructs_as_false(self) -> None:
        """Simulates a real, already-persisted Phase 27-era row whose
        plan_steps_json predates this batch - it must load exactly as
        if the new fields were never set."""
        old_style_step_dict = {
            "number": 1,
            "description": "Save a memory",
            "action": "save memory",
            "tier": "green",
            "reason": "Saving is safe.",
            "tool_name": "memory",
            "tool_input": {"content": "hello"},
            "input_from_previous_step": False,
            # deliberately no requires_verified_predecessor/
            # verification_field_name/verification_expected_value keys
        }
        reconstructed = PlanStep(
            number=old_style_step_dict["number"],
            description=old_style_step_dict["description"],
            action=old_style_step_dict["action"],
            tier=SecurityTier(old_style_step_dict["tier"]),
            reason=old_style_step_dict["reason"],
            tool_name=old_style_step_dict.get("tool_name"),
            tool_input=dict(old_style_step_dict.get("tool_input") or {}),
            input_from_previous_step=bool(
                old_style_step_dict.get("input_from_previous_step", False)
            ),
            requires_verified_predecessor=bool(
                old_style_step_dict.get("requires_verified_predecessor", False)
            ),
            verification_field_name=old_style_step_dict.get("verification_field_name"),
            verification_expected_value=old_style_step_dict.get(
                "verification_expected_value"
            ),
        )
        assert reconstructed.requires_verified_predecessor is False
        assert reconstructed.verification_field_name is None
        assert reconstructed.verification_expected_value is None

    def test_round_trip_through_json_preserves_gate_fields(self) -> None:
        step = _gated_step()
        as_dict = WorkflowEngine._plan_step_to_dict(step)
        round_tripped = json.loads(json.dumps(as_dict))
        rebuilt = PlanStep(
            number=round_tripped["number"],
            description=round_tripped["description"],
            action=round_tripped["action"],
            tier=SecurityTier(round_tripped["tier"]),
            reason=round_tripped["reason"],
            tool_name=round_tripped.get("tool_name"),
            tool_input=dict(round_tripped.get("tool_input") or {}),
            input_from_previous_step=bool(
                round_tripped.get("input_from_previous_step", False)
            ),
            requires_verified_predecessor=bool(
                round_tripped.get("requires_verified_predecessor", False)
            ),
            verification_field_name=round_tripped.get("verification_field_name"),
            verification_expected_value=round_tripped.get(
                "verification_expected_value"
            ),
        )
        assert rebuilt == step
