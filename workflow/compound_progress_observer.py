"""
compound_progress_observer.py

The one concrete implementation of workflow.engine's optional,
structural `_CompoundStepObserver` Protocol, trusted application
infrastructure for exactly the Phase 98 compound template (Phase 98,
Batch 2 - docs/phase_98_live_compound_reentry_plan.md, Foundation E):
PROJECT_STATE_UPDATE_PHASE -> internal phase verification ->
PROJECT_STATE_SHOW.

Responsibilities:
    - Implement before_step()/after_step() exactly per
      workflow.engine._CompoundStepObserver's own structural contract -
      never inheriting from it (a pure duck-typed implementation, so
      this module never needs to import workflow.engine's private
      Protocol type at all).
    - Persist durable per-step checkpoints into a real
      CompoundWorkflowProgressStore at the exact moments
      before_step()/after_step() are called by WorkflowEngine - never
      deferred to a post-hoc batch.
    - Capture the pre-execution ProjectState observation via one
      additional, real, audited "project_state_verify" ToolExecutor
      call - never a raw store read - before Step 1's own write tool
      is ever invoked.
    - Compute the real VerificationOutcome for Step 2 by comparing its
      own ToolResult.metadata against the exact trusted
      verification_field_name/verification_expected_value already
      carried on the Plan's own Step 3 (never a second AI call, never
      a fuzzy comparison).

Does NOT:
    - Get constructed or attached by any live request path in Batch 2.
      Only this module's own dedicated tests, and a future,
      separately-approved Batch 3 wiring inside JarvisOrchestrator,
      ever construct this class.
    - Call ApprovalManager, SecurityManager, or WorkflowEngine.resume()
      itself. This class is only ever the passive `step_observer`
      argument a caller supplies to an already-in-progress resume()
      call.
    - Persist unrestricted tool output. Only the bounded fields
      CompoundWorkflowProgressStore itself declares are ever written.
    - Raise past its own boundary. Every checkpoint call is wrapped so
      an unexpected failure becomes a bounded, honest reason string,
      matching workflow.engine._observer_before_step/_observer_after_step's
      own fail-closed contract (which also independently catches any
      exception this class might still raise, as defense in depth).
"""

from __future__ import annotations

from dataclasses import dataclass

from planner.plan_models import Plan
from tools.base_tool import ToolResult
from tools.executor import ToolExecutor
from workflow.compound_workflow_progress_store import (
    CompoundVerificationOutcome,
    CompoundWorkflowProgressStore,
)

#: The one real, registered, GREEN, read-only tool used both for the
#: pre-execution observation (Step 0's before_step) and for computing
#: Step 2's own verification outcome (Step 1's after_step) - the exact
#: same tool intelligence.planning.py's own trusted plan builder
#: selects as Step 2 (PROJECT_STATE_VERIFY_FOCUS's real tool_name).
_VERIFY_TOOL_NAME = "project_state_verify"

#: The trusted, fixed metadata key this template's verification always
#: compares - matches PlanStep.verification_field_name for this one
#: template exactly (never read from model output).
_DEFAULT_VERIFICATION_FIELD = "phase"


@dataclass(frozen=True, slots=True)
class CompoundStepObserver:
    """The trusted, per-workflow-attempt observer instance a caller
    constructs immediately before calling WorkflowEngine.resume() for a
    plan it has already, independently recognized as the one trusted
    compound template.

    A new instance must be constructed for each resume() call (it is
    frozen and carries no mutable state of its own beyond its
    collaborators) - never reused across two different workflow ids or
    two different Plans.

    Attributes:
        plan: The exact trusted Plan being resumed - used only to read
            Step 3's own already-durable verification_field_name/
            verification_expected_value, never to execute anything
            itself.
        progress_store: The real CompoundWorkflowProgressStore to
            persist every checkpoint into.
        executor: The real, unmodified ToolExecutor used for the one
            extra, audited pre-execution observation read - never a
            raw ProjectStateStore read.
        session_id: Optional session identifier, forwarded only into
            the observation read's own ToolRequest.
    """

    plan: Plan
    progress_store: CompoundWorkflowProgressStore
    executor: ToolExecutor
    session_id: int | None = None

    def before_step(self, workflow_id: str, step_index: int) -> str | None:
        """See workflow.engine._CompoundStepObserver.before_step's own
        contract. Handles exactly the three step indices this one
        template ever has (0, 1, 2); any other index is a no-op (never
        expected for this template, but never raises either).

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
            return f"compound progress checkpoint failed: {exc}"

    def after_step(
        self, workflow_id: str, step_index: int, tool_result: ToolResult
    ) -> str | None:
        """See workflow.engine._CompoundStepObserver.after_step's own
        contract.

        Args:
            workflow_id: The workflow being resumed.
            step_index: The zero-based index of the step whose outcome
                is now known.
            tool_result: The real ToolResult for that step (including a
                synthetic declined/gate-failure/checkpoint-failure
                result for those cases).

        Returns:
            None on success, or a short, bounded reason if the
            checkpoint could not be durably recorded.
        """
        if tool_result.requires_confirmation:
            # Never reached in practice - this observer is only ever
            # attached to resume() (never run()), and this template's
            # only YELLOW step is Step 1, already approved by the time
            # resume() runs it. Kept as a defensive no-op: nothing
            # executed yet, so nothing to persist.
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
            return f"compound progress checkpoint failed: {exc}"

    def _checkpoint_pre_execution_observation(self, workflow_id: str) -> str | None:
        """Read the real, current ProjectState phase/last_updated via
        one extra, audited project_state_verify call, then persist it
        as the pre-execution observation - the single call that also
        atomically marks Step 1 active (Batch 1's own
        record_pre_execution_observation() already sets
        step_1_status -> IN_PROGRESS in the same transaction).

        Args:
            workflow_id: The workflow being resumed.

        Returns:
            None on success, or a short, bounded reason on failure.
        """
        pre_read = self.executor.execute(
            _VERIFY_TOOL_NAME, {}, session_id=self.session_id
        )
        if not pre_read.success:
            return "pre-execution observation could not be read"

        phase_value = pre_read.metadata.get("phase")
        if not isinstance(phase_value, str):
            return "pre-execution observation returned no usable phase value"

        last_updated_at = pre_read.metadata.get("last_updated_at")

        self.progress_store.record_pre_execution_observation(
            workflow_id, phase_value=phase_value, last_updated=last_updated_at
        )
        return None

    def _verification_outcome(
        self, tool_result: ToolResult
    ) -> CompoundVerificationOutcome:
        """Compute the real, exact-match VerificationOutcome for Step
        2's own result, comparing against Step 3's own trusted,
        already-durable verification_field_name/verification_expected_value
        - never a raw model-supplied value, never a second AI call.

        Args:
            tool_result: Step 2's own real ToolResult.

        Returns:
            VERIFIED, FAILED, or UNAVAILABLE - never fabricated from a
            bare success flag alone.
        """
        if not tool_result.success:
            return CompoundVerificationOutcome.UNAVAILABLE

        step_3 = self.plan.steps[2]
        field_name = step_3.verification_field_name or _DEFAULT_VERIFICATION_FIELD
        expected_value = step_3.verification_expected_value

        actual = tool_result.metadata.get(field_name)
        if not isinstance(actual, str) or expected_value is None:
            return CompoundVerificationOutcome.UNAVAILABLE
        if actual == expected_value:
            return CompoundVerificationOutcome.VERIFIED
        return CompoundVerificationOutcome.FAILED
