"""
workflow_models.py

Runtime data models for sequential workflow execution (Phase 15, Batch 1:
Minimal Multi-Step Plan and Workflow Models).

Responsibilities:
    - Define WorkflowStepOutcome: the runtime outcome of one attempted
      PlanStep.
    - Define WorkflowResult: the ordered outcome of running (or resuming) a
      whole workflow.

Does NOT:
    - Execute anything (see workflow/engine.py, Phase 15 Batch 2 - not yet
      implemented).
    - Classify security tiers, call ToolExecutor, or call SecurityManager.
    - Create, approve, or expire approval requests.
    - Persist anything, or represent a paused/resumable registry of active
      workflows.

These are pure data models, exactly like planner/plan_models.py. They
describe the shape of a workflow's runtime outcome; they contain no
execution, security, or approval logic themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from approval.approval_models import ApprovalRequest
from config.constants import StepStatus
from planner.plan_models import Plan, PlanStep
from tools.base_tool import ToolResult

#: StepStatus values Phase 15 actually produces. PAUSED and SKIPPED are not
#: used in Phase 15 (no user-initiated pause exists; no step is ever marked
#: optional/skippable) - constructing a WorkflowStepOutcome with either value
#: is rejected below, so the boundary is enforced, not merely documented.
_UNSUPPORTED_STEP_STATUSES = frozenset({StepStatus.PAUSED, StepStatus.SKIPPED})


@dataclass(frozen=True, slots=True)
class WorkflowStepOutcome:
    """The runtime outcome of one attempted PlanStep.

    Attributes:
        step: The PlanStep this outcome describes. Never mutated or
            rebuilt - the exact same object produced by whatever built the
            Plan.
        status: The step's execution state, using only the existing
            StepStatus enum (no new value is added). Phase 15 only ever
            produces PENDING, RUNNING, WAITING, COMPLETED, or FAILED for a
            step that was actually attempted; RUNNING is transient and is
            not expected to appear in a WorkflowResult a synchronous
            run()/resume() call has already returned (Phase 15 Batch 2 is
            wholly synchronous), but is not rejected here since this model
            makes no assumption about who constructs it or when.
        tool_result: The result of executing this step's tool, if any was
            produced. Required (non-None) for WAITING, COMPLETED, and
            FAILED; must be None for PENDING and RUNNING (see
            __post_init__).
        approval_request: The pending approval request for this step, set
            only when status is WAITING. This is the exact same
            ApprovalRequest object ApprovalManager.create_request() already
            returns today - no second, workflow-owned approval id or
            correlation mechanism is introduced. Must be None for every
            other status.

    Does NOT:
        - Represent a RED-blocked step with a new StepStatus value. A
          blocked step is represented as FAILED, with
          tool_result.blocked=True distinguishing it from an ordinary tool
          failure - reusing the ToolResult.blocked flag that already
          exists, rather than adding an eighth StepStatus value.
        - Approve, decline, or expire anything. It only ever holds a
          reference to an ApprovalRequest someone else created.
    """

    step: PlanStep
    status: StepStatus
    tool_result: ToolResult | None = None
    approval_request: ApprovalRequest | None = None

    def __post_init__(self) -> None:
        """Reject any construction that does not represent a coherent outcome.

        Raises:
            ValueError: If status is PAUSED or SKIPPED (not used in Phase
                15); if PENDING or RUNNING carries a tool_result or
                approval_request; if WAITING lacks a tool_result whose
                requires_confirmation is True, or lacks an
                approval_request; if COMPLETED lacks a tool_result, or
                that tool_result is not a genuine success, or an
                approval_request is present; if FAILED lacks a
                tool_result, or that tool_result reports success, or an
                approval_request is present.
        """
        if self.status in _UNSUPPORTED_STEP_STATUSES:
            raise ValueError(
                f"WorkflowStepOutcome does not support status {self.status} "
                "in Phase 15 - only PENDING, RUNNING, WAITING, COMPLETED, "
                "and FAILED are produced."
            )

        if self.status in (StepStatus.PENDING, StepStatus.RUNNING):
            if self.tool_result is not None:
                raise ValueError(
                    f"A {self.status} step must not carry a tool_result - "
                    "it has not produced one yet."
                )
            if self.approval_request is not None:
                raise ValueError(
                    f"A {self.status} step must not carry an "
                    "approval_request - nothing is pending approval yet."
                )
            return

        if self.status is StepStatus.WAITING:
            if self.tool_result is None or not self.tool_result.requires_confirmation:
                raise ValueError(
                    "A WAITING step must carry a tool_result whose "
                    "requires_confirmation is True."
                )
            if self.approval_request is None:
                raise ValueError(
                    "A WAITING step must carry the ApprovalRequest it is "
                    "waiting on."
                )
            return

        # COMPLETED and FAILED must never carry an approval_request - once a
        # step has finished (either way), it is no longer awaiting anything.
        if self.approval_request is not None:
            raise ValueError(
                f"A {self.status} step must not carry an approval_request - "
                "only a WAITING step may."
            )

        if self.status is StepStatus.COMPLETED:
            if self.tool_result is None or not self.tool_result.success:
                raise ValueError(
                    "A COMPLETED step must carry a tool_result reporting "
                    "success."
                )
            return

        # StepStatus.FAILED.
        if self.tool_result is None or self.tool_result.success:
            raise ValueError(
                "A FAILED step must carry a tool_result that did not "
                "report success."
            )


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """The ordered outcome of running (or resuming) a whole workflow.

    Attributes:
        plan: The Plan that was executed.
        workflow_id: A correlation identifier for this workflow run,
            generated by whatever runs it (Phase 15 Batch 2). Reused,
            unchanged, as the ApprovalRequest metadata key/value a paused
            step's approval request carries - no separate correlation
            mechanism is introduced by this model.
        step_outcomes: The outcomes of every step actually attempted, in
            the exact order they were attempted. Only the *last* entry may
            have a status other than COMPLETED - once a step is WAITING or
            FAILED, execution stops (Phase 15's STOP-only policy), so no
            later entry can exist. Steps never reached are simply absent
            from this tuple, never represented as synthesised PENDING
            placeholders. Never sorted, never deduplicated: exactly as
            constructed.
        session_id: Optional session identifier for the audit trail.
        message: A human-readable summary of the outcome.

    Does NOT:
        - Store timestamps, a persistence/restart token, scheduler
          metadata, agent metadata, or UI/dashboard-oriented fields - none
          of these exist in Phase 15.
        - Infer, rebuild, or reorder PlanSteps.
    """

    plan: Plan
    workflow_id: str
    step_outcomes: tuple[WorkflowStepOutcome, ...] = field(default_factory=tuple)
    session_id: int | None = None
    message: str = ""

    def __post_init__(self) -> None:
        """Reject a step_outcomes sequence that violates STOP-only ordering.

        Raises:
            ValueError: If any outcome before the last one is not
                COMPLETED - under Phase 15's STOP-only failure policy, a
                WAITING or FAILED outcome must always be the final entry.
        """
        for outcome in self.step_outcomes[:-1]:
            if outcome.status is not StepStatus.COMPLETED:
                raise ValueError(
                    "Only the last step_outcome may have a status other "
                    f"than COMPLETED - found {outcome.status} before the "
                    "end of step_outcomes."
                )

    @property
    def overall_status(self) -> StepStatus:
        """The workflow's overall status, derived from its step outcomes.

        Uses only the existing StepStatus enum - no new status type is
        introduced.

        Returns:
            StepStatus.PENDING if no step has been attempted yet (an empty
            step_outcomes - nothing has run).
            StepStatus.WAITING if the last attempted step is awaiting
            approval.
            StepStatus.FAILED if the last attempted step failed or was
            blocked.
            StepStatus.COMPLETED if every attempted step completed
            successfully.
        """
        if not self.step_outcomes:
            return StepStatus.PENDING

        last = self.step_outcomes[-1]
        if last.status is StepStatus.WAITING:
            return StepStatus.WAITING
        if last.status is StepStatus.FAILED:
            return StepStatus.FAILED
        return StepStatus.COMPLETED

    @property
    def pending_approval_request(self) -> ApprovalRequest | None:
        """The approval request the workflow is currently paused on, if any.

        Derived directly from the last step outcome rather than stored
        separately, so it can never disagree with step_outcomes itself -
        no second correlation mechanism exists.

        Returns:
            The ApprovalRequest of the last step outcome, if its status is
            WAITING; otherwise None.
        """
        if not self.step_outcomes:
            return None
        last = self.step_outcomes[-1]
        return last.approval_request if last.status is StepStatus.WAITING else None
