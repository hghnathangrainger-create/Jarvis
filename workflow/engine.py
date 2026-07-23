"""
engine.py

Sequential Workflow Engine for the Jarvis AI Operating System (Phase 15,
Batch 2: Sequential Workflow Engine).

Responsibilities:
    - Execute a Plan's steps, one at a time, strictly in Plan.steps order.
    - Delegate every single step's execution to the existing, unmodified
      ToolExecutor.execute() - the sole security gate. This engine never
      classifies an action itself and never trusts PlanStep.tier for
      execution.
    - Pause a workflow when a step returns requires_confirmation, using the
      existing, unmodified ApprovalManager to create the approval request,
      and resume it later via resume() once a decision exists.
    - Enforce Phase 15's STOP-only failure policy: the first step that does
      not cleanly succeed ends the workflow; no later step ever runs.
    - Emit a small, orchestration-only audit event family, distinct from
      (and never duplicating) ToolExecutor's/ApprovalManager's own existing
      tool_call/approval events.
    - Optionally record the same lifecycle transitions durably via a
      WorkflowHistoryStore (Durable Workflow Lifecycle Foundation - a
      prerequisite turn, not a numbered phase), so a workflow's history
      remains queryable across a restart. This is additive only: it never
      replaces the existing audit events above, and it never makes any
      workflow resumable, replayable, or exactly-once - see
      workflow.workflow_history_store's own module docstring.

Does NOT:
    - Construct its own ToolRegistry, SecurityManager, ToolExecutor, or
      ApprovalManager - all are injected.
    - Call SecurityManager.classify_action() or read ToolRegistry to
      decide whether a step may execute - that remains solely
      ToolExecutor.execute()'s job, for every step, every time (proven by
      test_execution_path_never_calls_classify_action_or_tool_run_directly
      in tests/unit/test_workflow_engine.py). Phase 27, Batch 2 added one
      narrow exception, confined entirely to the optional reload-safety
      path: reload_paused() (via _try_reconstruct_paused_workflow) calls
      both, purely to decide whether a *persisted* paused workflow may be
      safely treated as pending again after a restart - never to decide
      whether a live step may run, and never executing anything itself
      (see test_classify_action_and_get_tool_appear_only_in_reload_revalidation,
      same file, which proves this confinement structurally).
    - Support retries, depends_on, branching, parallel steps, or concurrent
      workflows.
    - Persist anything by default. A freshly constructed WorkflowEngine
      with no paused_store behaves exactly as Phase 15 originally
      specified: paused-workflow state lives only in this instance's own
      memory and is lost on process exit. Phase 27, Batch 2 added an
      optional paused_store collaborator: when configured, a paused
      workflow's plan/progress is additionally persisted to
      paused_workflow_state and can be safely reloaded (reload_paused())
      after a restart, independently re-validated against live code
      before being trusted - see workflow/paused_workflow_store.py's own
      module docstring for the full trust-boundary reasoning. This is
      still not a general crash-recovery or exactly-once guarantee: see
      docs/phase_27_completion_report.md and
      docs/phase_28_completion_report.md for what remains explicitly out
      of scope.
    - Match commands, dispatch requests, or return JarvisResponse. This
      engine executes a Plan and returns a WorkflowResult; command routing,
      Plan construction, and CLI presentation remain later Phase 15
      batches' responsibility (Batch 3/4), not this module's.
    - Depend on AIReasoningEngine, AIRouter, or any AI provider. Every
      executable step, in every workflow this engine has ever run
      (Phases 15, 17, 29), is a deterministic tool call.

This is a plain, synchronous, single-threaded engine: no callbacks, no
generators/iterators, no async, no threads, no background loop. run() and
resume() each execute steps until the workflow stops, pauses, or completes,
then return one WorkflowResult.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

from approval.approval_manager import ApprovalManager
from approval.approval_models import (
    ApprovalDecision,
    ApprovalError,
    PendingApprovalHandoffStatus,
)
from config.constants import EventOutcome, SecurityTier, StepStatus
from planner.plan_models import Plan, PlanStep
from security.security_manager import SecurityManager
from tools.base_tool import ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry
from workflow.paused_workflow_store import SCHEMA_VERSION, PausedWorkflowRecord
from workflow.workflow_history_store import WorkflowHistoryStore
from workflow.workflow_models import WorkflowResult, WorkflowStepOutcome

_SOURCE = "workflow_engine"

_EVENT_WORKFLOW_STARTED = "workflow_started"
_EVENT_STEP_STARTED = "workflow_step_started"
_EVENT_STEP_COMPLETED = "workflow_step_completed"
_EVENT_STEP_WAITING = "workflow_step_waiting"
_EVENT_STEP_FAILED = "workflow_step_failed"
_EVENT_WORKFLOW_COMPLETED = "workflow_completed"
_EVENT_WORKFLOW_STOPPED = "workflow_stopped"

#: The fixed, repository-defined previous-step propagation fields.
#: Deliberately a small, explicitly-enumerated list of (metadata_key,
#: tool_input_key) pairs, not a generic templating/variable/data-flow
#: language: each entry is its own named, justified special case, reused
#: exactly as-is by every step that declares input_from_previous_step,
#: never combined, never dynamically selected by AI or by a step's own
#: description text.
#:
#: - ("memory_id", "memory_id") - Phase 15: tools/builtin/memory_tool.py's
#:   own save operation already returns metadata["memory_id"], and both
#:   MemoryTool's "get" operation and MemoryForgetTool already accept
#:   "memory_id" as their own tool_input key.
#: - ("matched_path", "source") - Phase 29: tools/builtin/file_search_tool.py
#:   sets metadata["matched_path"] only when a search finds exactly one
#:   match (never for zero or multiple matches), and file_copy accepts
#:   "source" as its own tool_input key. A search with zero or multiple
#:   matches therefore has no "matched_path" entry, so the same "usable"
#:   check below already stops the workflow honestly - no separate
#:   zero/multiple-match handling exists anywhere in this engine.
#:
#: Checked in this fixed order; the first metadata key found is used. In
#: practice the two never coexist on one tool_result, since no tool sets
#: both, so order has no effect on correctness today. Generalising this
#: beyond these two named fields is explicitly out of scope pending real
#: evidence of another need.
_PROPAGATED_FIELDS: tuple[tuple[str, str], ...] = (
    ("memory_id", "memory_id"),
    ("matched_path", "source"),
)

#: Sentinel returned by _try_reconstruct_paused_workflow() (Approval-to-
#: Resume Handoff Interlock, Batch 2 -
#: docs/phase_98_approval_handoff_plan.md) meaning: this paused
#: workflow's own row must be neither invalidated/deleted nor
#: reconstructed into self._paused right now - its linked approval is
#: durably APPROVED_UNCONSUMED or CLAIMED (decided or already claimed,
#: but not yet resumed/consumed), so it must survive this reload
#: untouched, pending either the exclusive startup-recovery
#: reconciliation pass (for CLAIMED specifically) or a future explicit
#: claim. A distinct identity (never equal to a real _PausedWorkflow or
#: to None) so reload_paused()'s own loop can tell all three outcomes
#: apart unambiguously.
_RETAIN_WITHOUT_RESUME = object()


class _AuditLogger(Protocol):
    """The minimal logging interface WorkflowEngine depends on. Mirrors
    core.orchestrator._AuditLogger / approval.approval_manager's own
    equivalent protocol - decoupled from the concrete EventLogger class."""

    def emit(
        self,
        *,
        source: str,
        action_type: str,
        outcome: EventOutcome,
        detail: str | None = ...,
        duration_ms: int | None = ...,
        security_tier: SecurityTier | None = ...,
        session_id: int | None = ...,
    ) -> str:
        """Emit a structured event. See EventLogger.emit for details."""
        ...


class _PausedWorkflowStateStore(Protocol):
    """The minimal paused-workflow-state interface WorkflowEngine depends
    on. Matches the write/read-side methods of
    workflow.paused_workflow_store.PausedWorkflowStore. Declaring it as a
    Protocol keeps the engine decoupled from the concrete store (Phase
    27, Batch 2), mirroring approval.approval_manager's own
    _PendingApprovalStateStore Protocol.

    Unlike WorkflowHistoryStore, this interface's whole purpose is to let
    a paused workflow's own plan and resolved step input survive a
    restart - that is explicitly authorized for *this* table only (see
    paused_workflow_store.py's own module docstring), never for
    workflow_history, which remains completely untouched by this
    feature.
    """

    def save(
        self,
        *,
        workflow_id: str,
        session_id: int | None,
        request_id: str,
        user_request: str,
        plan_steps: list[dict[str, object]],
        completed_outcomes: list[dict[str, object]],
        waiting_step_index: int,
        resolved_tool_input: dict[str, object],
    ) -> object:
        """Persist (or replace) the paused state for one workflow_id."""
        ...

    def delete(self, workflow_id: str) -> None:
        """Remove the persisted paused state for one workflow_id, if any."""
        ...

    def list_all(self) -> list[PausedWorkflowRecord]:
        """Return every currently persisted paused-workflow row."""
        ...


@dataclass(frozen=True, slots=True)
class WorkflowReloadReport:
    """A small, honest summary of what reload_paused() did (Phase 27,
    Batch 2). Mirrors approval.approval_manager.ApprovalReloadReport.

    Attributes:
        resumed: Number of persisted paused workflows that passed
            revalidation and are now genuinely paused again, exactly as
            if the process had never restarted.
        invalidated: Number of persisted paused workflows that failed
            revalidation and were removed, with a terminal entry
            recorded in workflow history explaining why - never
            resumed, and their linked pending approval (if still
            present) invalidated too.
    """

    resumed: int
    invalidated: int


class WorkflowError(Exception):
    """Raised for a WorkflowEngine usage error: an invalid executable plan,
    an unknown workflow id, a workflow id that is not currently paused, or
    (Phase 28) a resume() call whose decision.request_id does not match
    the specific paused workflow being resumed.

    Never raised for an ordinary step outcome (a tool failure, a RED
    block, or a declined approval) - those are always represented
    honestly as a FAILED WorkflowResult instead, matching this
    repository's existing convention that expected, describable outcomes
    are returned as data, not raised as exceptions (ApprovalError is the
    nearest existing precedent for a small, subsystem-specific exception
    reserved for genuine misuse). A request-id mismatch is exactly this
    kind of misuse - not a decision the workflow itself made about its
    own step - so it is raised, not returned as a FAILED WorkflowResult.
    """


@dataclass(frozen=True, slots=True)
class _PausedWorkflow:
    """Private, in-memory record of a workflow paused for approval.

    Never exposed as a public workflow model (workflow.workflow_models
    stays limited to WorkflowStepOutcome/WorkflowResult, per the approved
    Phase 15 plan). Phase 15 never persisted this anywhere; Phase 27,
    Batch 2 optionally mirrors it durably (see _paused_store) so it can
    survive a restart - but this in-memory dataclass itself is never
    written to or read from a database directly; WorkflowEngine converts
    to and from plain dict/JSON shapes at its own persistence boundary
    (_persist_paused_state / _try_reconstruct_paused_workflow).
    """

    plan: Plan
    session_id: int | None
    completed_outcomes: tuple[WorkflowStepOutcome, ...]
    waiting_step_index: int
    resolved_tool_input: dict[str, object]
    request_id: str


class WorkflowEngine:
    """Executes a Plan's steps sequentially, reusing the existing security
    and approval authorities unchanged.

    Attributes:
        _executor: The existing ToolExecutor - the sole security gate.
            Injected, never constructed here.
        _approvals: The existing ApprovalManager - used only to create an
            approval request when a step pauses. Injected, never
            constructed here. This engine never approves, declines, or
            expires anything itself.
        _logger: Optional audit logger for the new, orchestration-only
            workflow_* event family. When omitted, nothing is recorded -
            matching how every other optional-audit collaborator in this
            codebase already behaves without one.
        _history: Optional durable WorkflowHistoryStore. When omitted,
            no lifecycle transition is ever recorded durably - Phase 15's
            original in-memory-only behaviour is fully preserved. When
            present, it is written to additively, alongside (never
            instead of) _logger, using the same narrow isolation pattern.
        _paused: The at-most-one currently paused workflow, keyed by its
            own workflow_id. Phase 15's concurrency model is exactly one
            active/paused workflow at a time - enforced by run()
            rejecting a second workflow while one is already paused.
        _paused_store: Optional durable paused-workflow-state store
            (Phase 27, Batch 2). When provided, a paused workflow's plan
            and resolved step input are additionally persisted there, so
            it can survive a restart. __init__ never reads from this
            store - exactly like _history, a freshly constructed engine
            always starts with an empty _paused; a caller must explicitly
            call reload_paused() to repopulate it from what was
            persisted, after independently revalidating every row.
    """

    def __init__(
        self,
        *,
        executor: ToolExecutor,
        approvals: ApprovalManager,
        logger: _AuditLogger | None = None,
        history: WorkflowHistoryStore | None = None,
        paused_store: _PausedWorkflowStateStore | None = None,
    ) -> None:
        """Initialise the engine with its collaborators.

        Args:
            executor: The existing ToolExecutor used for every executable
                step. Never constructed by this class.
            approvals: The existing ApprovalManager used to create a
                pending approval request when a step pauses. Never
                constructed by this class.
            logger: Optional audit logger for the new workflow_* event
                family. When omitted, no workflow event is ever recorded.
            history: Optional durable WorkflowHistoryStore. When omitted
                (the default), fully backward compatible with every
                pre-existing Phase 15 caller: no lifecycle transition is
                ever recorded durably.
            paused_store: Optional durable paused-workflow-state store
                (such as a PausedWorkflowStore) used to persist a paused
                workflow's plan and resolved step input (Phase 27, Batch
                2). When omitted, the engine behaves exactly as it did
                before this feature existed - purely in memory, and a
                restart always loses every paused workflow, exactly as
                today. This parameter only ever causes writes during
                pause/resume/reap; reload_paused() must be called
                explicitly to read anything back.
        """
        self._executor = executor
        self._approvals = approvals
        self._logger = logger
        self._history = history
        self._paused: dict[str, _PausedWorkflow] = {}
        self._paused_store = paused_store

    def has_paused(self, workflow_id: str) -> bool:
        """Report whether workflow_id refers to a currently paused workflow.

        Args:
            workflow_id: The workflow identifier to check.

        Returns:
            True only if that exact id is this instance's own currently
            paused workflow, and its approval request is still genuinely
            pending. A different WorkflowEngine instance's paused
            workflow, an unknown id, a terminal (completed/failed) id, or
            a paused id whose approval window has since expired (Phase
            15, Batch 4) are all reported as False.
        """
        self._reap_stale_paused()
        return workflow_id in self._paused

    def _reap_stale_paused(self) -> None:
        """Clear a paused workflow whose approval request has genuinely
        expired (Phase 15, Batch 4).

        Closes an in-memory leak directly caused by Phase 15's own
        integration: ApprovalManager's existing YELLOW timeout policy
        already expires an unanswered approval request on its own, but
        nothing previously told WorkflowEngine to give up its own paused
        state when that happened. Since Phase 15 permits only one
        active/paused workflow at a time, an expired approval would
        otherwise permanently block every future run() call for the
        remaining lifetime of this instance.

        Careful distinction: ApprovalManager.has_pending() also returns
        False the moment a request is legitimately approved/declined
        (Approval Manager's own _decide() removes it from pending
        immediately, before resume() is ever called) - reaping on
        has_pending() alone would incorrectly discard a paused workflow
        exactly when resume() is about to use it. A request is only
        genuinely stale here if it is neither still pending NOR has a
        recorded decision at all - true expiry never creates a decision
        (ApprovalManager._sweep_expired()'s own contract: "Expiry never
        creates an ApprovalDecision"). This never fabricates a decision or
        executes anything - it only forgets a paused workflow whose
        approval window is genuinely gone.
        """
        stale_ids = []
        for workflow_id, paused in self._paused.items():
            if self._approvals.has_pending(paused.request_id):
                continue
            try:
                self._approvals.get_decision(paused.request_id)
            except ApprovalError:
                stale_ids.append(workflow_id)
        for workflow_id in stale_ids:
            del self._paused[workflow_id]
            self._remove_paused_state(workflow_id)

    def run(self, plan: Plan, *, session_id: int | None = None) -> WorkflowResult:
        """Execute plan.steps in order, starting from the first step.

        Validates the plan's executable shape first (see
        _validate_executable_plan) - an invalid plan raises WorkflowError
        before any step is attempted, any workflow_id is generated, or any
        event is emitted.

        Args:
            plan: The Plan to execute. Every step must carry a non-blank
                tool_name; step numbers must be exactly 1, 2, 3, ... with
                no gaps or duplicates; only a step after the first may set
                input_from_previous_step.
            session_id: Optional session identifier for the audit trail.

        Returns:
            A WorkflowResult. Its overall_status is COMPLETED if every
            step succeeded, WAITING if a step is now paused for approval,
            or FAILED if a step failed, was blocked, or could not obtain
            usable previous-step input.

        Raises:
            WorkflowError: If another workflow is already paused (Phase
                15's one-workflow-at-a-time contract), or if the plan does
                not have a valid executable shape.
        """
        self._reap_stale_paused()
        if self._paused:
            raise WorkflowError(
                "Another workflow is already paused awaiting approval; "
                "only one workflow may be active at a time in Phase 15."
            )
        self._validate_executable_plan(plan)

        workflow_id = self._new_workflow_id()
        self._emit(
            _EVENT_WORKFLOW_STARTED,
            EventOutcome.SUCCESS,
            detail=f"workflow_id={workflow_id} steps={len(plan.steps)}",
            session_id=session_id,
        )
        self._record_history(
            _EVENT_WORKFLOW_STARTED,
            workflow_id=workflow_id,
            session_id=session_id,
            step_total=len(plan.steps),
        )
        return self._run_from(
            plan,
            workflow_id=workflow_id,
            session_id=session_id,
            start_index=0,
            completed_outcomes=(),
        )

    def resume(
        self,
        workflow_id: str,
        decision: ApprovalDecision,
        *,
        session_id: int | None = None,
    ) -> WorkflowResult:
        """Continue a previously paused workflow after an approval decision.

        This engine never approves, declines, or expires anything itself -
        `decision` must already be the real, recorded ApprovalDecision
        obtained from the same ApprovalManager instance (via its own
        approve()/decline()). The paused state is removed from this
        instance before the approved tool call is attempted, so a second
        resume() call for the same workflow_id - with the same or a
        different decision - always raises WorkflowError and can never
        execute anything: there is nothing left to resume.

        Args:
            workflow_id: The identifier of the paused workflow to resume.
            decision: The already-recorded ApprovalDecision for the step
                that was waiting.
            session_id: Optional session identifier. When omitted, the
                session_id the workflow was originally run with is reused.

        Returns:
            A new WorkflowResult representing the progressed workflow
            state. The original paused WorkflowResult is never mutated.

        Raises:
            WorkflowError: If workflow_id does not refer to a currently
                paused workflow (unknown id, already resumed, or already
                terminal); or (Phase 28) if decision.request_id does not
                match the request_id this exact paused workflow is
                actually waiting on.
        """
        paused = self._paused.pop(workflow_id, None)
        if paused is None:
            raise WorkflowError(
                f"No paused workflow with id '{workflow_id}'. It may not "
                "exist, or it may already have been resumed."
            )
        # Phase 27, Batch 2: the durable row's job is done the moment
        # resume() is called, whether this step now completes, fails, or
        # pauses again on a later step (which re-persists a fresh row via
        # the pause site in _run_from() below).
        self._remove_paused_state(workflow_id)

        # Phase 28: the supplied decision must be the one this exact
        # paused workflow is actually waiting on - never a different,
        # unrelated decision, even one that is itself a real, validly
        # approved ApprovalDecision for something else entirely. Every
        # legitimate caller already satisfies this by construction
        # (core.orchestrator.execute_approved() derives workflow_id from
        # the same approval_request whose decision it then supplies), so
        # this only ever rejects a genuinely mismatched pair. This
        # workflow is treated as permanently, terminally done - never put
        # back into self._paused for a later retry with a different
        # decision, which would otherwise let a caller probe for a
        # matching id.
        if decision.request_id != paused.request_id:
            self._emit(
                _EVENT_WORKFLOW_STOPPED,
                EventOutcome.FAILURE,
                detail=(
                    f"workflow_id={workflow_id} resume_request_id_mismatch "
                    f"expected={paused.request_id} got={decision.request_id}"
                ),
                session_id=paused.session_id,
            )
            self._record_history(
                _EVENT_WORKFLOW_STOPPED,
                workflow_id=workflow_id,
                session_id=paused.session_id,
                detail=(
                    "resume() called with a decision for a different "
                    f"request (expected request_id={paused.request_id})"
                ),
            )
            raise WorkflowError(
                f"The supplied decision does not belong to workflow "
                f"'{workflow_id}': expected request_id '{paused.request_id}', "
                f"got '{decision.request_id}'. This workflow cannot be "
                "resumed with a decision that is not the one it is "
                "actually waiting on."
            )

        resolved_session_id = (
            session_id if session_id is not None else paused.session_id
        )
        step = paused.plan.steps[paused.waiting_step_index]

        if not decision.is_approved:
            tool_result = ToolResult(
                tool_name=step.tool_name or "",
                success=False,
                error="This action was declined and was not run.",
            )
            return self._stop(
                paused.plan,
                workflow_id=workflow_id,
                session_id=resolved_session_id,
                completed_outcomes=paused.completed_outcomes,
                step=step,
                tool_result=tool_result,
            )

        self._emit_step_event(
            _EVENT_STEP_STARTED,
            EventOutcome.PENDING,
            workflow_id=workflow_id,
            plan=paused.plan,
            step=step,
            session_id=resolved_session_id,
        )
        self._record_history(
            _EVENT_STEP_STARTED,
            workflow_id=workflow_id,
            session_id=resolved_session_id,
            step_number=step.number,
            step_total=len(paused.plan.steps),
            tool_name=step.tool_name,
        )
        tool_result = self._executor.execute(
            step.tool_name,
            paused.resolved_tool_input,
            session_id=resolved_session_id,
            approval_decision=decision,
        )

        if not tool_result.success or tool_result.blocked:
            return self._stop(
                paused.plan,
                workflow_id=workflow_id,
                session_id=resolved_session_id,
                completed_outcomes=paused.completed_outcomes,
                step=step,
                tool_result=tool_result,
            )

        outcome = WorkflowStepOutcome(
            step=step, status=StepStatus.COMPLETED, tool_result=tool_result
        )
        self._emit_step_event(
            _EVENT_STEP_COMPLETED,
            EventOutcome.SUCCESS,
            workflow_id=workflow_id,
            plan=paused.plan,
            step=step,
            session_id=resolved_session_id,
        )
        self._record_history(
            _EVENT_STEP_COMPLETED,
            workflow_id=workflow_id,
            session_id=resolved_session_id,
            step_number=step.number,
            step_total=len(paused.plan.steps),
            tool_name=step.tool_name,
        )
        return self._run_from(
            paused.plan,
            workflow_id=workflow_id,
            session_id=resolved_session_id,
            start_index=paused.waiting_step_index + 1,
            completed_outcomes=paused.completed_outcomes + (outcome,),
        )

    # ----- internal sequential loop ------------------------------------------

    def _run_from(
        self,
        plan: Plan,
        *,
        workflow_id: str,
        session_id: int | None,
        start_index: int,
        completed_outcomes: tuple[WorkflowStepOutcome, ...],
    ) -> WorkflowResult:
        """Execute plan.steps[start_index:] in order until the workflow
        stops, pauses, or completes.

        Never executes a step twice: each call only ever advances forward
        from start_index. Never pre-executes a later step: the loop
        returns immediately the moment a step does not cleanly succeed, or
        pauses.

        Args:
            plan: The Plan being executed.
            workflow_id: This workflow's correlation id.
            session_id: Optional session identifier.
            start_index: The plan.steps index to begin at.
            completed_outcomes: Outcomes already recorded for steps before
                start_index.

        Returns:
            A WorkflowResult - COMPLETED, WAITING, or FAILED.
        """
        outcomes = list(completed_outcomes)

        for index in range(start_index, len(plan.steps)):
            step = plan.steps[index]

            self._emit_step_event(
                _EVENT_STEP_STARTED,
                EventOutcome.PENDING,
                workflow_id=workflow_id,
                plan=plan,
                step=step,
                session_id=session_id,
            )
            self._record_history(
                _EVENT_STEP_STARTED,
                workflow_id=workflow_id,
                session_id=session_id,
                step_number=step.number,
                step_total=len(plan.steps),
                tool_name=step.tool_name,
            )

            tool_input, usable = self._resolve_tool_input(step, tuple(outcomes))
            if not usable:
                tool_result = ToolResult(
                    tool_name=step.tool_name or "",
                    success=False,
                    error=(
                        "Cannot execute this step: the immediately previous "
                        "step did not produce the required result data."
                    ),
                )
                return self._stop(
                    plan,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    completed_outcomes=tuple(outcomes),
                    step=step,
                    tool_result=tool_result,
                )

            gate_failure_reason = self._verification_gate_failure_reason(
                step, tuple(outcomes)
            )
            if gate_failure_reason is not None:
                tool_result = ToolResult(
                    tool_name=step.tool_name or "",
                    success=False,
                    error=gate_failure_reason,
                )
                return self._stop(
                    plan,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    completed_outcomes=tuple(outcomes),
                    step=step,
                    tool_result=tool_result,
                )

            tool_result = self._executor.execute(
                step.tool_name, tool_input, session_id=session_id
            )

            if tool_result.requires_confirmation:
                approval_request = self._approvals.create_request(
                    action=step.action,
                    reason=tool_result.error
                    or "This action requires your confirmation.",
                    security_tier=SecurityTier.YELLOW,
                    session_id=session_id,
                    metadata={
                        "workflow_id": workflow_id,
                        "step_number": str(step.number),
                    },
                )
                outcome = WorkflowStepOutcome(
                    step=step,
                    status=StepStatus.WAITING,
                    tool_result=tool_result,
                    approval_request=approval_request,
                )
                outcomes.append(outcome)
                self._emit_step_event(
                    _EVENT_STEP_WAITING,
                    EventOutcome.PENDING,
                    workflow_id=workflow_id,
                    plan=plan,
                    step=step,
                    session_id=session_id,
                )
                self._record_history(
                    _EVENT_STEP_WAITING,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    step_number=step.number,
                    step_total=len(plan.steps),
                    tool_name=step.tool_name,
                    approval_request_id=approval_request.request_id,
                    detail=tool_result.error or "Awaiting your confirmation.",
                )
                paused = _PausedWorkflow(
                    plan=plan,
                    session_id=session_id,
                    completed_outcomes=tuple(outcomes[:-1]),
                    waiting_step_index=index,
                    resolved_tool_input=tool_input,
                    request_id=approval_request.request_id,
                )
                self._paused[workflow_id] = paused
                self._persist_paused_state(workflow_id, paused)
                return WorkflowResult(
                    plan=plan,
                    workflow_id=workflow_id,
                    step_outcomes=tuple(outcomes),
                    session_id=session_id,
                    message=tool_result.error or "Awaiting your confirmation.",
                )

            if not tool_result.success or tool_result.blocked:
                return self._stop(
                    plan,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    completed_outcomes=tuple(outcomes),
                    step=step,
                    tool_result=tool_result,
                )

            outcome = WorkflowStepOutcome(
                step=step, status=StepStatus.COMPLETED, tool_result=tool_result
            )
            outcomes.append(outcome)
            self._emit_step_event(
                _EVENT_STEP_COMPLETED,
                EventOutcome.SUCCESS,
                workflow_id=workflow_id,
                plan=plan,
                step=step,
                session_id=session_id,
            )
            self._record_history(
                _EVENT_STEP_COMPLETED,
                workflow_id=workflow_id,
                session_id=session_id,
                step_number=step.number,
                step_total=len(plan.steps),
                tool_name=step.tool_name,
            )

        self._emit(
            _EVENT_WORKFLOW_COMPLETED,
            EventOutcome.SUCCESS,
            detail=f"workflow_id={workflow_id} steps_completed={len(outcomes)}",
            session_id=session_id,
        )
        self._record_history(
            _EVENT_WORKFLOW_COMPLETED,
            workflow_id=workflow_id,
            session_id=session_id,
            step_total=len(plan.steps),
            detail=f"steps_completed={len(outcomes)}",
        )
        return WorkflowResult(
            plan=plan,
            workflow_id=workflow_id,
            step_outcomes=tuple(outcomes),
            session_id=session_id,
            message="Workflow completed.",
        )

    def _stop(
        self,
        plan: Plan,
        *,
        workflow_id: str,
        session_id: int | None,
        completed_outcomes: tuple[WorkflowStepOutcome, ...],
        step: PlanStep,
        tool_result: ToolResult,
    ) -> WorkflowResult:
        """Record a FAILED outcome for `step` and stop the workflow.

        STOP-only policy (Phase 15): no later step is ever attempted after
        this call. No retry, no rollback of already-completed steps' real
        side effects, no SKIPPED outcome synthesised for later steps -
        they are simply absent from the returned step_outcomes.

        Args:
            plan: The Plan being executed.
            workflow_id: This workflow's correlation id.
            session_id: Optional session identifier.
            completed_outcomes: Outcomes already recorded before this step.
            step: The step that did not cleanly succeed.
            tool_result: The unsuccessful/blocked/declined/unusable result.

        Returns:
            A WorkflowResult with overall_status FAILED.
        """
        outcome = WorkflowStepOutcome(
            step=step, status=StepStatus.FAILED, tool_result=tool_result
        )
        outcomes = completed_outcomes + (outcome,)

        self._emit_step_event(
            _EVENT_STEP_FAILED,
            EventOutcome.BLOCKED if tool_result.blocked else EventOutcome.FAILURE,
            workflow_id=workflow_id,
            plan=plan,
            step=step,
            session_id=session_id,
        )
        self._record_history(
            _EVENT_STEP_FAILED,
            workflow_id=workflow_id,
            session_id=session_id,
            step_number=step.number,
            step_total=len(plan.steps),
            tool_name=step.tool_name,
            detail=tool_result.error,
        )
        self._emit(
            _EVENT_WORKFLOW_STOPPED,
            EventOutcome.BLOCKED if tool_result.blocked else EventOutcome.FAILURE,
            detail=f"workflow_id={workflow_id} stopped_at_step={step.number}",
            session_id=session_id,
        )
        self._record_history(
            _EVENT_WORKFLOW_STOPPED,
            workflow_id=workflow_id,
            session_id=session_id,
            step_number=step.number,
            step_total=len(plan.steps),
            detail=f"stopped_at_step={step.number}",
        )
        return WorkflowResult(
            plan=plan,
            workflow_id=workflow_id,
            step_outcomes=outcomes,
            session_id=session_id,
            message=tool_result.error or "The workflow was stopped.",
        )

    # ----- previous-step propagation (narrow, fixed field list) --------------

    @staticmethod
    def _resolve_tool_input(
        step: PlanStep, prior_outcomes: tuple[WorkflowStepOutcome, ...]
    ) -> tuple[dict[str, object], bool]:
        """Build this step's tool_input, applying one of the narrow,
        fixed previous-step propagation rules in _PROPAGATED_FIELDS if
        the step declares it.

        Static step.tool_input is always the base - never replaced, only
        extended. When input_from_previous_step is True, the immediately
        previous outcome's tool_result.metadata is checked against each
        (metadata_key, tool_input_key) pair in _PROPAGATED_FIELDS, in
        order; the first metadata key found present is copied into
        tool_input[tool_input_key], overwriting any static value there.
        No ToolResult.message text is ever parsed, and no field outside
        this fixed list is ever propagated.

        Args:
            step: The step whose input is being resolved.
            prior_outcomes: Every outcome recorded so far, in order.

        Returns:
            A tuple of (tool_input, usable). usable is False only when
            input_from_previous_step is True but the immediately previous
            outcome did not complete successfully, or its tool_result has
            none of the known metadata keys - in which case tool_input is
            returned unmodified and the caller must not execute the step.
            This is also how a file-search-then-copy workflow (Phase 29)
            stops honestly on zero or multiple matches: FileSearchTool
            only ever sets "matched_path" for exactly one match, so
            "usable" is False for either zero or multiple matches, with
            no separate handling needed here.
        """
        tool_input = dict(step.tool_input)
        if not step.input_from_previous_step:
            return tool_input, True

        if not prior_outcomes:
            return tool_input, False

        previous = prior_outcomes[-1]
        if previous.status is not StepStatus.COMPLETED or previous.tool_result is None:
            return tool_input, False

        for metadata_key, tool_input_key in _PROPAGATED_FIELDS:
            value = previous.tool_result.metadata.get(metadata_key)
            if value is not None:
                tool_input[tool_input_key] = value
                return tool_input, True

        return tool_input, False

    # ----- trusted verification-continuation gate (Phase 98, Batch 1) --------

    @staticmethod
    def _verification_gate_failure_reason(
        step: PlanStep, prior_outcomes: tuple[WorkflowStepOutcome, ...]
    ) -> str | None:
        """Decide whether a step whose requires_verified_predecessor is
        True may proceed, and return an honest, bounded stop reason if
        not (Phase 98, Batch 1 - docs/phase_98_implementation_plan.md).

        A no-op (returns None immediately) for any step that does not
        set requires_verified_predecessor - this is the exact condition
        that keeps every existing plan's behavior byte-for-byte
        unchanged, since no live plan-construction code sets this field
        yet.

        This method never consults ToolResult.success alone, a
        verifier's own exit status, free-text output, or a fuzzy
        metadata-string check: it performs the same exact-value
        comparison intelligence.verification.verify_project_state_field()
        already performs (workflow/ has no import dependency on
        intelligence/, so this is a deliberate, generic, engine-native
        re-implementation of the identical comparison, not a duplicate
        philosophy) against the immediately preceding step's own real,
        structured ToolResult.metadata - never AI output, never a
        second AI call, never a generic expression or callback. A
        genuinely successful read whose observed value differs from
        the expected one is reported as a verification mismatch, kept
        honestly distinct from a verifier read failure or an
        unavailable value - never conflated with either, and never
        capable of being satisfied by the gated step's own tool
        succeeding or failing (this check runs before the gated step's
        tool is ever invoked).

        Args:
            step: The step about to be attempted.
            prior_outcomes: Every outcome recorded so far, in order.

        Returns:
            None if step does not require a verified predecessor, or
            the immediately preceding outcome's real metadata exactly
            matches step's own trusted expected value. Otherwise a
            short, bounded, honest reason string describing exactly
            why continuation is refused - the caller must not execute
            the step.
        """
        if not step.requires_verified_predecessor:
            return None

        if not prior_outcomes:
            return (
                "Cannot execute this step: it requires a verified "
                "preceding step, but there is no preceding step."
            )

        previous = prior_outcomes[-1]
        if previous.status is not StepStatus.COMPLETED or previous.tool_result is None:
            return (
                "Cannot execute this step: the preceding verification "
                "step did not complete, so verification is unavailable."
            )

        if not previous.tool_result.success:
            return (
                "Cannot execute this step: the preceding verification "
                "step did not succeed, so verification is unavailable."
            )

        field_name = step.verification_field_name
        expected_value = step.verification_expected_value
        if field_name is None or expected_value is None:
            return (
                "Cannot execute this step: it requires a verified "
                "preceding step, but no trusted verification field/value "
                "is configured."
            )

        actual_value = previous.tool_result.metadata.get(field_name)
        if actual_value is None or not isinstance(actual_value, str):
            return (
                "Cannot execute this step: the preceding verification "
                "step returned no usable value, so verification is "
                "unavailable."
            )

        if actual_value != expected_value:
            return (
                "Cannot execute this step: the preceding verification "
                "did not confirm the expected value - this is a "
                "verification mismatch, not a verifier failure."
            )

        return None

    # ----- executable-plan precondition validation ---------------------------

    @staticmethod
    def _validate_executable_plan(plan: Plan) -> None:
        """Reject a Plan that is not a valid Phase 15 executable workflow.

        This is a small, narrow precondition check - not a generic
        PlanValidator class, and not a security classification pass. No
        step is classified here; SecurityManager.classify_action() remains
        exclusively ToolExecutor's own, called fresh for every step at the
        moment it actually runs.

        Args:
            plan: The Plan to validate.

        Raises:
            WorkflowError: If the plan has no steps; if any step number is
                duplicated or the sequence is not exactly 1, 2, 3, ... with
                no gaps; if any step has a blank or missing tool_name; or
                if the first step declares input_from_previous_step.
        """
        if plan.is_empty:
            raise WorkflowError("A workflow plan must contain at least one step.")

        seen_numbers: set[int] = set()
        for index, step in enumerate(plan.steps):
            if step.number in seen_numbers:
                raise WorkflowError(
                    f"Duplicate step number {step.number} in workflow plan."
                )
            seen_numbers.add(step.number)

            if step.number != index + 1:
                raise WorkflowError(
                    "Workflow plan steps must be numbered sequentially "
                    "starting at 1, with no gaps - "
                    f"found step number {step.number} at position {index + 1}."
                )

            if step.tool_name is None or not step.tool_name.strip():
                raise WorkflowError(
                    f"Step {step.number} has no tool_name - every executable "
                    "workflow step must name a real, registered tool."
                )

            if index == 0 and step.input_from_previous_step:
                raise WorkflowError(
                    "The first workflow step cannot use "
                    "input_from_previous_step - there is no previous step."
                )

            if index == 0 and step.requires_verified_predecessor:
                raise WorkflowError(
                    "The first workflow step cannot use "
                    "requires_verified_predecessor - there is no previous step."
                )

            if step.requires_verified_predecessor and (
                step.verification_field_name is None
                or step.verification_expected_value is None
            ):
                raise WorkflowError(
                    f"Step {step.number} sets requires_verified_predecessor "
                    "but does not configure both verification_field_name "
                    "and verification_expected_value."
                )

    # ----- workflow id ---------------------------------------------------------

    @staticmethod
    def _new_workflow_id() -> str:
        """Generate a fresh workflow correlation id.

        A UUID, generated fresh per run() call - only needs to correlate
        one in-memory run/resume lifecycle and this workflow's own audit
        events within Phase 15; it implies no cross-restart identity and
        is never derived from a Plan id (Plan has no id field) or from
        Python's own id(...).

        Returns:
            A new, essentially-collision-free identifier string.
        """
        return str(uuid.uuid4())

    # ----- audit -----------------------------------------------------------

    def _emit_step_event(
        self,
        event: str,
        outcome: EventOutcome,
        *,
        workflow_id: str,
        plan: Plan,
        step: PlanStep,
        session_id: int | None,
    ) -> None:
        """Emit a per-step orchestration event.

        Never logs tool_input content, memory text, or file contents -
        only the workflow id, this step's position/total, and its tool
        name (a plain identifier, not user content).

        Args:
            event: One of the module's _EVENT_* constants.
            outcome: The EventOutcome to record.
            workflow_id: This workflow's correlation id.
            plan: The Plan being executed, used only for its step count.
            step: The step this event describes.
            session_id: Optional session identifier.
        """
        detail = (
            f"workflow_id={workflow_id} step={step.number}/{len(plan.steps)} "
            f"tool={step.tool_name}"
        )
        self._emit(event, outcome, detail=detail, session_id=session_id)

    def _emit(
        self,
        event: str,
        outcome: EventOutcome,
        *,
        detail: str,
        session_id: int | None,
    ) -> None:
        """Emit one workflow-level audit event, if a logger is configured.

        A raising logger is caught here, scoped only around the emit()
        call itself, so a failing audit logger can never alter execution,
        pause, resume, or the final WorkflowResult already computed -
        matching the existing narrow observability-isolation pattern used
        throughout this codebase (e.g.
        core.orchestrator._emit_memory_acquisition_event).

        Args:
            event: The action_type to record.
            outcome: The EventOutcome to record.
            detail: The already-built, content-free detail string.
            session_id: Optional session identifier.
        """
        if self._logger is None:
            return
        try:
            self._logger.emit(
                source=_SOURCE,
                action_type=event,
                outcome=outcome,
                detail=detail,
                session_id=session_id,
            )
        except Exception:
            # Observability-only: a failing audit logger must never break
            # the authoritative workflow already in progress.
            pass

    # ----- durable history (Durable Workflow Lifecycle Foundation) ----------

    def _record_history(
        self,
        status: str,
        *,
        workflow_id: str,
        session_id: int | None,
        step_number: int | None = None,
        step_total: int | None = None,
        tool_name: str | None = None,
        approval_request_id: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Durably record one workflow lifecycle transition, if configured.

        A raising history store is caught here, scoped only around the
        record_transition() call itself, so a failing durable-history
        write can never alter execution, pause, resume, or the final
        WorkflowResult already computed - the identical narrow
        observability-isolation pattern already used by _emit() above.
        This is additive: it never replaces the existing workflow_* audit
        events, and never stores enough to reconstruct an executable
        resumption point (no tool_input, no resolved step input, no plan).

        Args:
            status: One of the module's _EVENT_* constants.
            workflow_id: This workflow's correlation id.
            session_id: Optional session identifier.
            step_number: Optional 1-based step this transition concerns.
            step_total: Optional total number of steps in the plan.
            tool_name: Optional step tool name (never its input).
            approval_request_id: Optional correlated approval request id,
                set only for a workflow_step_waiting transition.
            detail: Optional short, content-free human-readable text.
        """
        if self._history is None:
            return
        try:
            self._history.record_transition(
                workflow_id=workflow_id,
                status=status,
                session_id=session_id,
                step_number=step_number,
                step_total=step_total,
                tool_name=tool_name,
                approval_request_id=approval_request_id,
                detail=detail,
            )
        except Exception:
            # Observability-only: a failing durable history write must
            # never break the authoritative workflow already in progress.
            pass

    # ----- durable paused-workflow state (Phase 27, Batch 2) -----------------

    def _persist_paused_state(self, workflow_id: str, paused: _PausedWorkflow) -> None:
        """Durably persist this workflow's paused state, if a
        paused_store is configured.

        When no paused_store is configured, this is a no-op and the
        engine behaves purely in memory, exactly as before this feature
        existed. Not isolated in a try/except - mirrors
        ApprovalManager._record_pending_state's own reasoning: a failing
        durable write here is a real problem worth surfacing, not a
        purely observational one.

        Args:
            workflow_id: This workflow's correlation id.
            paused: The in-memory paused-workflow record to persist.
        """
        if self._paused_store is None:
            return
        self._paused_store.save(
            workflow_id=workflow_id,
            session_id=paused.session_id,
            request_id=paused.request_id,
            user_request=paused.plan.user_request,
            plan_steps=[self._plan_step_to_dict(s) for s in paused.plan.steps],
            completed_outcomes=[
                self._completed_outcome_to_dict(o) for o in paused.completed_outcomes
            ],
            waiting_step_index=paused.waiting_step_index,
            resolved_tool_input=dict(paused.resolved_tool_input),
        )

    def _remove_paused_state(self, workflow_id: str) -> None:
        """Remove this workflow's durable paused-state row, if a
        paused_store is configured.

        Args:
            workflow_id: The identifier of the workflow that just
                resumed or was reaped as stale.
        """
        if self._paused_store is None:
            return
        self._paused_store.delete(workflow_id)

    @staticmethod
    def _plan_step_to_dict(step: PlanStep) -> dict[str, object]:
        """Convert one PlanStep into a plain, JSON-safe dict.

        Args:
            step: The step to convert.

        Returns:
            A plain dict with every field PlanStep declares.
        """
        return {
            "number": step.number,
            "description": step.description,
            "action": step.action,
            "tier": step.tier.value,
            "reason": step.reason,
            "tool_name": step.tool_name,
            "tool_input": dict(step.tool_input),
            "input_from_previous_step": step.input_from_previous_step,
            "requires_verified_predecessor": step.requires_verified_predecessor,
            "verification_field_name": step.verification_field_name,
            "verification_expected_value": step.verification_expected_value,
        }

    @staticmethod
    def _completed_outcome_to_dict(
        outcome: WorkflowStepOutcome,
    ) -> dict[str, object]:
        """Convert one completed WorkflowStepOutcome into a plain,
        JSON-safe dict.

        Every entry in _PausedWorkflow.completed_outcomes is always
        StepStatus.COMPLETED with a real, successful tool_result (see
        _run_from's own construction: completed_outcomes is always
        outcomes[:-1], sliced before the WAITING entry, and
        WorkflowResult.__post_init__ already enforces that only the
        final outcome may be non-COMPLETED) - so this never needs to
        represent a WAITING/FAILED shape.

        Args:
            outcome: The completed step outcome to convert.

        Returns:
            A plain dict naming the step number and a plain view of its
            ToolResult.
        """
        result = outcome.tool_result
        assert result is not None  # guaranteed by WorkflowStepOutcome's own validation
        return {
            "step_number": outcome.step.number,
            "tool_result": {
                "tool_name": result.tool_name,
                "success": result.success,
                "output": result.output,
                "error": result.error,
                "requires_confirmation": result.requires_confirmation,
                "blocked": result.blocked,
                "metadata": dict(result.metadata),
            },
        }

    def reload_paused(
        self,
        *,
        registry: ToolRegistry,
        security_manager: SecurityManager | None = None,
    ) -> WorkflowReloadReport:
        """Reload every persisted paused workflow, revalidating each
        against live code - and against this engine's own already-
        reloaded ApprovalManager - before treating it as genuinely paused
        again (Phase 27, Batch 2).

        This is never called from __init__ - a freshly constructed
        WorkflowEngine always starts with an empty _paused, exactly as
        before this feature existed. A caller (the composition root,
        main.py) calls this explicitly, once, AFTER
        ApprovalManager.reload_pending() has already run on the same
        `approvals` instance this engine was constructed with - this
        engine's own revalidation depends on that having already
        happened (see _try_reconstruct_paused_workflow's own has_pending
        check).

        A persisted row is only ever treated as resumable if ALL of the
        following hold:
            - its plan_steps_json/completed_outcomes_json/
              resolved_tool_input_json decoded without error
              (PausedWorkflowRecord.corrupt is False);
            - its schema_version is one this code recognises;
            - it has at least one plan step, and waiting_step_index is a
              valid index into it;
            - its linked approval (request_id) is still genuinely
              pending in self._approvals, right now - this reuses
              ApprovalManager.reload_pending()'s own outcome rather than
              re-deriving approval validity here, so a linked approval
              that was itself invalidated (missing, decided, expired, or
              corrupt) always fails this workflow closed too;
            - the waiting step's tool_name (if any) is still registered
              in `registry`, and classifying its fixed action_for()
              output (or the step's own stored action text, if it has no
              tool) still returns SecurityTier.YELLOW right now;
            - every completed-outcome entry refers to a real step number
              in the reconstructed plan, and its stored ToolResult shape
              is well-formed enough to reconstruct a real
              WorkflowStepOutcome (which re-validates the combination
              itself via its own __post_init__).

        A row that fails any check is never resumed and never executed:
        it is removed from the durable paused-workflow table, a terminal
        "workflow_stopped"-shaped entry is recorded in workflow history
        (via the existing, unchanged record_transition() event
        vocabulary), and its own linked pending-approval row - if still
        present - is invalidated too via
        ApprovalManager.invalidate_pending(), so that approval's mere
        existence can never imply this workflow is still resumable.
        Nothing here ever auto-approves, auto-resumes, or auto-executes
        anything; a row that passes every check is only ever added back
        to self._paused - a caller must still explicitly approve its
        linked approval and call resume(), exactly as for a live pause.

        Args:
            registry: The live ToolRegistry to check the waiting step's
                tool_name against. Should already have every tool
                registered.
            security_manager: The live SecurityManager to reclassify the
                waiting step's action against. Defaults to a new
                SecurityManager() if omitted (it is stateless, so this is
                equivalent to sharing the application's own instance).

        Returns:
            A WorkflowReloadReport summarising how many paused workflows
            were resumed versus invalidated.
        """
        if self._paused_store is None:
            return WorkflowReloadReport(resumed=0, invalidated=0)

        security = security_manager or SecurityManager()
        resumed = 0
        invalidated = 0

        for record in self._paused_store.list_all():
            paused, rejection = self._try_reconstruct_paused_workflow(
                record, registry=registry, security=security
            )
            # Approval-to-Resume Handoff Interlock, Batch 2: a row whose
            # linked approval is durably APPROVED_UNCONSUMED or CLAIMED
            # is neither "resumed" (nothing calls resume() for it here)
            # nor "invalidated" (it must not be deleted or have its
            # approval invalidated) - it is simply left alone, retained
            # for the exclusive startup-recovery reconciliation pass (for
            # CLAIMED) or a future explicit claim (for
            # APPROVED_UNCONSUMED). Neither counter is incremented for it.
            if paused is _RETAIN_WITHOUT_RESUME:
                continue
            if paused is None:
                self._invalidate_reloaded_paused_workflow(
                    record, reason=rejection or "Could not be revalidated."
                )
                invalidated += 1
                continue

            self._paused[record.workflow_id] = paused
            resumed += 1

        return WorkflowReloadReport(resumed=resumed, invalidated=invalidated)

    def _try_reconstruct_paused_workflow(
        self,
        record: PausedWorkflowRecord,
        *,
        registry: ToolRegistry,
        security: SecurityManager,
    ) -> tuple[_PausedWorkflow | object | None, str | None]:
        """Attempt to safely reconstruct one persisted paused-workflow row.

        Args:
            record: The persisted row being considered for reload.
            registry: The live ToolRegistry to resolve the waiting step's
                tool_name against.
            security: The live SecurityManager to reclassify against.

        Returns:
            A tuple of (paused, None) if the row passes every check and
            was reconstructed successfully; (_RETAIN_WITHOUT_RESUME,
            None) if its linked approval is durably APPROVED_UNCONSUMED
            or CLAIMED (Approval-to-Resume Handoff Interlock, Batch 2) -
            retained untouched, neither resumed nor invalidated; or
            (None, reason) if it must fail closed.
        """
        if record.corrupt:
            return None, "Persisted state could not be parsed."
        if record.schema_version != SCHEMA_VERSION:
            return None, (
                "Persisted state uses an unsupported schema version "
                f"({record.schema_version})."
            )
        if not record.plan_steps:
            return None, "Persisted state has no plan steps."
        if not (0 <= record.waiting_step_index < len(record.plan_steps)):
            return None, "Persisted waiting_step_index is out of range."

        # The linked approval must itself already be genuinely pending -
        # this reuses ApprovalManager.reload_pending()'s own outcome
        # directly rather than re-implementing approval validation here.
        # main.py's own composition order guarantees reload_pending() has
        # already run on this exact `self._approvals` instance.
        if not self._approvals.has_pending(record.request_id):
            # Approval-to-Resume Handoff Interlock, Batch 2: an approval
            # that is no longer "pending" is not automatically
            # unresumable any more - it may instead be durably
            # APPROVED_UNCONSUMED (decided, not yet claimed) or CLAIMED
            # (claimed by a now-terminated prior process, awaiting the
            # exclusive startup-recovery reconciliation pass). Both must
            # be retained untouched, never invalidated on this basis
            # alone - only DECLINED/EXPIRED/CONSUMED/CLAIM_INTERRUPTED
            # (or a missing row entirely) mean this workflow's own
            # approval will truly never be resumed again.
            handoff_status = self._approvals.handoff_status_for(record.request_id)
            if handoff_status in (
                PendingApprovalHandoffStatus.APPROVED_UNCONSUMED,
                PendingApprovalHandoffStatus.CLAIMED,
            ):
                return _RETAIN_WITHOUT_RESUME, None
            return None, (
                f"Linked approval '{record.request_id}' is not pending "
                "(missing, already decided, or invalidated on its own "
                "reload)."
            )

        try:
            steps = tuple(
                PlanStep(
                    number=s["number"],
                    description=s["description"],
                    action=s["action"],
                    tier=SecurityTier(s["tier"]),
                    reason=s["reason"],
                    tool_name=s.get("tool_name"),
                    tool_input=dict(s.get("tool_input") or {}),
                    input_from_previous_step=bool(
                        s.get("input_from_previous_step", False)
                    ),
                    requires_verified_predecessor=bool(
                        s.get("requires_verified_predecessor", False)
                    ),
                    verification_field_name=s.get("verification_field_name"),
                    verification_expected_value=s.get(
                        "verification_expected_value"
                    ),
                )
                for s in record.plan_steps
            )
            plan = Plan(user_request=record.user_request or "", steps=steps)
        except (KeyError, TypeError, ValueError) as exc:
            return None, f"Persisted plan could not be reconstructed: {exc}"

        waiting_step = plan.steps[record.waiting_step_index]
        tool = (
            registry.get_tool(waiting_step.tool_name)
            if waiting_step.tool_name is not None
            else None
        )
        if waiting_step.tool_name is not None and tool is None:
            return None, f"Tool '{waiting_step.tool_name}' is no longer registered."

        classify_text = (
            tool.action_for(
                ToolRequest(
                    tool_name=waiting_step.tool_name,
                    input_data=dict(record.resolved_tool_input or {}),
                )
            )
            if tool is not None
            else waiting_step.action
        )
        try:
            decision = security.classify_action(classify_text)
        except ValueError:
            return None, "Persisted waiting-step action is empty and cannot be reclassified."
        if decision.tier is not SecurityTier.YELLOW:
            return None, (
                "Waiting step no longer classifies as YELLOW "
                f"(now {decision.tier.value})."
            )

        try:
            completed_outcomes = []
            for entry in record.completed_outcomes or []:
                step_number = entry["step_number"]
                matching = [s for s in steps if s.number == step_number]
                if not matching:
                    return None, (
                        f"Completed-outcome step {step_number} not found "
                        "in the reconstructed plan."
                    )
                tr = entry["tool_result"]
                tool_result = ToolResult(
                    tool_name=tr["tool_name"],
                    success=tr["success"],
                    output=tr.get("output", ""),
                    error=tr.get("error"),
                    requires_confirmation=tr.get("requires_confirmation", False),
                    blocked=tr.get("blocked", False),
                    metadata=dict(tr.get("metadata") or {}),
                )
                completed_outcomes.append(
                    WorkflowStepOutcome(
                        step=matching[0],
                        status=StepStatus.COMPLETED,
                        tool_result=tool_result,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            return None, f"Persisted completed outcomes could not be reconstructed: {exc}"

        paused = _PausedWorkflow(
            plan=plan,
            session_id=record.session_id,
            completed_outcomes=tuple(completed_outcomes),
            waiting_step_index=record.waiting_step_index,
            resolved_tool_input=dict(record.resolved_tool_input or {}),
            request_id=record.request_id,
        )
        return paused, None

    def _invalidate_reloaded_paused_workflow(
        self, record: PausedWorkflowRecord, *, reason: str
    ) -> None:
        """Remove a persisted paused-workflow row that failed reload
        revalidation, record an honest terminal entry in workflow
        history, and invalidate its linked pending approval too - so
        neither the workflow nor its approval can ever imply this is
        still resumable.

        Args:
            record: The persisted row that failed revalidation.
            reason: The human-readable rejection reason.
        """
        if self._paused_store is not None:
            self._paused_store.delete(record.workflow_id)

        self._approvals.invalidate_pending(
            record.request_id,
            reason=f"paused workflow could not be resumed after restart: {reason}",
        )

        self._emit(
            _EVENT_WORKFLOW_STOPPED,
            EventOutcome.FAILURE,
            detail=(
                f"workflow_id={record.workflow_id} "
                f"stopped_at_reload reason={reason}"
            ),
            session_id=record.session_id,
        )
        self._record_history(
            _EVENT_WORKFLOW_STOPPED,
            workflow_id=record.workflow_id,
            session_id=record.session_id,
            detail=f"Could not be resumed after restart: {reason}",
        )
