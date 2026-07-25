"""
schedule_compound_progress_observer.py

The second, dormant concrete implementation of workflow.engine's
optional, structural `_CompoundStepObserver` Protocol (Phase 99, Batch
2 - docs/phase_99_second_compound_template_planning.md): a wholly
separate, parallel sibling to workflow/compound_progress_observer.py,
for exactly the schedule-compound template: SCHEDULE_ENABLE ->
SCHEDULE_VERIFY_ENABLED_STATE -> SCHEDULE_SHOW_ENABLED_STATE.

Responsibilities:
    - Implement before_step()/after_step() exactly per
      workflow.engine._CompoundStepObserver's own structural contract -
      never inheriting from it, and never modifying that Protocol or
      workflow.engine.CompoundCheckpointError, both of which are
      reused here exactly as-is (they were already generic, with no
      ProjectState-specific behaviour - see this module's own reuse of
      CompoundCheckpointError only inside its own tests, never inside
      this class itself, which only ever returns a bounded reason
      string, matching CompoundStepObserver's own convention).
    - Persist durable per-step checkpoints into a real
      ScheduleCompoundWorkflowProgressStore at the exact moments
      before_step()/after_step() are called by WorkflowEngine.
    - Capture the pre-execution ScheduleEntry.enabled observation via
      one additional, real, audited "schedule_verify_enabled_state"
      ToolExecutor call (with the plan's own trusted schedule_id) -
      never a raw store read - before Step 1's own write tool is ever
      invoked.
    - Compute the real ScheduleCompoundVerificationOutcome for Step 2 by
      comparing its own ToolResult.metadata against the exact trusted
      verification_field_name/verification_expected_value already
      carried on the Plan's own Step 3 (never a second AI call, never a
      fuzzy comparison) - mirrors CompoundStepObserver's own
      _verification_outcome() exactly, adapted to this module's own
      ScheduleCompoundVerificationOutcome enum.
    - Reject an unrecognised, malformed, or substituted plan (one that
      does not match matches_schedule_compound_plan_shape()) at
      construction time, rather than attempting to track it.

Does NOT:
    - Get constructed or attached by any live request path in Batch 2.
      Only this module's own dedicated tests, and a future, separately-
      approved later batch's wiring inside JarvisOrchestrator, ever
      construct this class.
    - Call ApprovalManager, SecurityManager, or WorkflowEngine.resume()
      itself.
    - Persist unrestricted tool output. Only the bounded fields
      ScheduleCompoundWorkflowProgressStore itself declares are ever
      written.
    - Raise past its own boundary for an ordinary checkpoint failure -
      every checkpoint call is wrapped so an unexpected failure becomes
      a bounded, honest reason string, matching
      workflow.engine._observer_before_step/_observer_after_step's own
      fail-closed contract (which independently catches any exception
      this class might still raise, as defense in depth).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.schedule_compound_workflow import matches_schedule_compound_plan_shape
from planner.plan_models import Plan
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from workflow.schedule_compound_workflow_progress_store import (
    ScheduleCompoundVerificationOutcome,
    ScheduleCompoundWorkflowProgressStore,
)

#: The one real, registered, GREEN, read-only, internal-only tool used
#: both for the pre-execution observation (Step 0's before_step) and
#: for computing Step 2's own verification outcome (Step 1's
#: after_step) - the exact same tool this template's own trusted plan
#: builder selects as Step 2 (SCHEDULE_VERIFY_ENABLED_STATE's real
#: tool_name).
_VERIFY_TOOL_NAME = "schedule_verify_enabled_state"

#: The trusted, fixed metadata key this template's verification always
#: compares - matches PlanStep.verification_field_name for this one
#: template exactly (never read from model output).
_DEFAULT_VERIFICATION_FIELD = "enabled_str"


class ScheduleCompoundPlanMismatchError(Exception):
    """Raised at construction time when the Plan supplied to
    ScheduleCompoundStepObserver does not match the exact trusted
    schedule-compound fingerprint - an unrecognised, malformed, or
    substituted plan is refused outright, rather than attempting to
    track it with the wrong step semantics."""


@dataclass(frozen=True, slots=True)
class ScheduleCompoundStepObserver:
    """The trusted, per-workflow-attempt observer instance a caller
    constructs immediately before calling WorkflowEngine.resume() for a
    plan it has already, independently recognized as the schedule-
    compound template.

    A new instance must be constructed for each resume() call (it is
    frozen and carries no mutable state of its own beyond its
    collaborators) - never reused across two different workflow ids or
    two different Plans.

    Attributes:
        plan: The exact trusted Plan being resumed - used only to read
            Step 1's trusted schedule_id and Step 3's own already-
            durable verification_field_name/verification_expected_value,
            never to execute anything itself. Validated at construction
            time against matches_schedule_compound_plan_shape().
        progress_store: The real ScheduleCompoundWorkflowProgressStore
            to persist every checkpoint into.
        executor: The real, unmodified ToolExecutor used for the one
            extra, audited pre-execution observation read.
        session_id: Optional session identifier, forwarded only into
            the observation read's own ToolRequest.

    Raises:
        ScheduleCompoundPlanMismatchError: If `plan` does not match the
            exact trusted schedule-compound fingerprint.
    """

    plan: Plan
    progress_store: ScheduleCompoundWorkflowProgressStore
    executor: ToolExecutor
    session_id: int | None = None

    def __post_init__(self) -> None:
        """Reject an unrecognised, malformed, or substituted plan
        outright, at construction time.

        Raises:
            ScheduleCompoundPlanMismatchError: If self.plan does not
                match the exact trusted schedule-compound fingerprint.
        """
        if not matches_schedule_compound_plan_shape(self.plan):
            raise ScheduleCompoundPlanMismatchError(
                "ScheduleCompoundStepObserver refuses to track a plan "
                "that does not match the exact trusted schedule-compound "
                "fingerprint."
            )

    def before_step(self, workflow_id: str, step_index: int) -> str | None:
        """See workflow.engine._CompoundStepObserver.before_step's own
        contract. Handles exactly the three step indices this one
        template ever has (0, 1, 2); any other index is a no-op.

        Args:
            workflow_id: The workflow being resumed.
            step_index: The zero-based index of the step about to run.

        Returns:
            None on success, or a short, bounded reason if the
            checkpoint could not be durably recorded.
        """
        try:
            if step_index == 0:
                return self._checkpoint_pre_execution_observation(workflow_id)
            if step_index == 1:
                self.progress_store.start_step_2(workflow_id)
                return None
            if step_index == 2:
                self.progress_store.start_step_3(workflow_id)
                return None
            return None
        except Exception as exc:  # noqa: BLE001 - fail closed; never propagate
            return f"schedule compound progress checkpoint failed: {exc}"

    def after_step(
        self, workflow_id: str, step_index: int, tool_result: ToolResult
    ) -> str | None:
        """See workflow.engine._CompoundStepObserver.after_step's own
        contract.

        Args:
            workflow_id: The workflow being resumed.
            step_index: The zero-based index of the step whose outcome
                is now known.
            tool_result: The real ToolResult for that step.

        Returns:
            None on success, or a short, bounded reason if the
            checkpoint could not be durably recorded.
        """
        if tool_result.requires_confirmation:
            # Never reached in practice - this observer is only ever
            # attached to resume() (never run()), and this template's
            # only YELLOW step is Step 1, already approved by the time
            # resume() runs it.
            return None
        try:
            if step_index == 0:
                if tool_result.success:
                    self.progress_store.mark_step_1_completed(workflow_id)
                else:
                    self.progress_store.mark_step_1_failed(workflow_id)
                return None
            if step_index == 1:
                outcome = self._verification_outcome(tool_result)
                self.progress_store.mark_step_2_completed(
                    workflow_id, verification_outcome=outcome
                )
                return None
            if step_index == 2:
                if tool_result.success:
                    self.progress_store.mark_step_3_completed(workflow_id)
                else:
                    self.progress_store.mark_step_3_failed(workflow_id)
                return None
            return None
        except Exception as exc:  # noqa: BLE001 - fail closed; never propagate
            return f"schedule compound progress checkpoint failed: {exc}"

    def _checkpoint_pre_execution_observation(self, workflow_id: str) -> str | None:
        """Read the real, current ScheduleEntry.enabled value via one
        extra, audited schedule_verify_enabled_state call (using this
        plan's own trusted schedule_id), then persist it as the
        pre-execution observation.

        Args:
            workflow_id: The workflow being resumed.

        Returns:
            None on success, or a short, bounded reason on failure.
        """
        schedule_id = self.plan.steps[0].tool_input.get("schedule_id")
        pre_read = self.executor.execute(
            _VERIFY_TOOL_NAME,
            {"schedule_id": schedule_id},
            session_id=self.session_id,
        )
        if not pre_read.success:
            return "pre-execution observation could not be read"

        enabled_value = pre_read.metadata.get("enabled")
        if not isinstance(enabled_value, bool):
            return "pre-execution observation returned no usable enabled value"

        self.progress_store.record_pre_execution_observation(
            workflow_id, enabled=enabled_value
        )
        return None

    def _verification_outcome(
        self, tool_result: ToolResult
    ) -> ScheduleCompoundVerificationOutcome:
        """Compute the real, exact-match ScheduleCompoundVerificationOutcome
        for Step 2's own result, comparing against Step 3's own trusted,
        already-durable verification_field_name/verification_expected_value.

        Args:
            tool_result: Step 2's own real ToolResult.

        Returns:
            VERIFIED, FAILED, or UNAVAILABLE - never fabricated from a
            bare success flag alone.
        """
        if not tool_result.success:
            return ScheduleCompoundVerificationOutcome.UNAVAILABLE

        step_3 = self.plan.steps[2]
        field_name = step_3.verification_field_name or _DEFAULT_VERIFICATION_FIELD
        expected_value = step_3.verification_expected_value

        actual = tool_result.metadata.get(field_name)
        if not isinstance(actual, str) or expected_value is None:
            return ScheduleCompoundVerificationOutcome.UNAVAILABLE
        if actual == expected_value:
            return ScheduleCompoundVerificationOutcome.VERIFIED
        return ScheduleCompoundVerificationOutcome.FAILED
