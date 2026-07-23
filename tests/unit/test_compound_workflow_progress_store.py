"""
test_compound_workflow_progress_store.py

Unit tests for CompoundWorkflowProgressStore and reconcile_phase_update
(Phase 98, Batch 1 - docs/phase_98_implementation_plan.md).

These use a real, in-memory SQLite database (not a fake), exactly like
tests/unit/test_paused_workflow_store.py's own established pattern -
exercising the same storage layer this future foundation would use at
runtime, including its real, single-statement compare-and-set
transitions.

No live wiring exists anywhere in this file - CompoundWorkflowProgressStore
is not called from any restart/execution path in this batch; these are
its own, dedicated, foundation-proving tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

# These three imports must follow the importorskip() guard above -
# moving them above it would import sqlalchemy-dependent modules
# directly, causing a hard collection failure instead of a clean skip
# when sqlalchemy is not installed. Matches the same, already-accepted
# pattern in tests/unit/test_paused_workflow_store.py.
from storage.database import create_session_factory, initialize_database  # noqa: E402
from storage.models import CompoundWorkflowProgress, PausedWorkflowState, ProjectState  # noqa: E402
from workflow.compound_workflow_progress_store import (  # noqa: E402
    ALLOWED_TEMPLATE_ID,
    CompoundOverallStatus,
    CompoundStepStatus,
    CompoundVerificationOutcome,
    CompoundWorkflowProgressError,
    CompoundWorkflowProgressStore,
    ReconciliationConfidence,
    reconcile_phase_update,
)


@pytest.fixture()
def engine():
    from sqlalchemy import create_engine

    eng = create_engine("sqlite:///:memory:")
    initialize_database(eng)
    return eng


@pytest.fixture()
def session_factory(engine):
    return create_session_factory(engine)


@pytest.fixture()
def store(session_factory) -> CompoundWorkflowProgressStore:
    return CompoundWorkflowProgressStore(session_factory)


def _create(store: CompoundWorkflowProgressStore, workflow_id: str = "wf-1"):
    return store.create(
        workflow_id=workflow_id,
        template_id=ALLOWED_TEMPLATE_ID,
        request_id="req-1",
        approved_phase_value="implementation",
    )


class TestTableCreationAndIsolation:
    def test_table_is_created_additively(self, session_factory) -> None:
        with session_factory() as db:
            # Querying the new table directly proves create_all() built it.
            assert db.query(CompoundWorkflowProgress).count() == 0

    def test_existing_tables_remain_untouched(self, session_factory) -> None:
        with session_factory() as db:
            assert db.query(PausedWorkflowState).count() == 0
            assert db.query(ProjectState).count() == 0


class TestFixedTemplateIdentity:
    def test_allowed_template_id_is_accepted(self, store) -> None:
        record = _create(store)
        assert record.template_id == ALLOWED_TEMPLATE_ID

    def test_a_different_template_id_is_rejected(self, store) -> None:
        with pytest.raises(CompoundWorkflowProgressError, match="Unsupported"):
            store.create(
                workflow_id="wf-2",
                template_id="some_other_template",
                request_id=None,
                approved_phase_value="x",
            )

    def test_no_second_template_can_be_stored(self, store) -> None:
        _create(store, "wf-1")
        with pytest.raises(CompoundWorkflowProgressError):
            store.create(
                workflow_id="wf-2",
                template_id="project_state_update_focus_then_show",
                request_id=None,
                approved_phase_value="x",
            )


class TestImmutableApprovedValue:
    def test_approved_phase_value_is_not_exposed_for_mutation(self, store) -> None:
        record = _create(store)
        assert record.approved_phase_value == "implementation"
        # No store method accepts approved_phase_value as an update
        # target anywhere - confirmed by inspecting the store's own
        # public API surface.
        import inspect

        public_methods = [
            name
            for name, _ in inspect.getmembers(
                CompoundWorkflowProgressStore, predicate=inspect.isfunction
            )
            if not name.startswith("_")
        ]
        for name in public_methods:
            method = getattr(CompoundWorkflowProgressStore, name)
            params = inspect.signature(method).parameters
            assert "approved_phase_value" not in params or name == "create"


class TestInitialState:
    def test_initial_state_is_valid(self, store) -> None:
        record = _create(store)
        assert record.step_1_status is CompoundStepStatus.PENDING
        assert record.step_2_status is CompoundStepStatus.PENDING
        assert record.step_3_status is CompoundStepStatus.PENDING
        assert record.step_2_verification_outcome is None
        assert record.overall_status is CompoundOverallStatus.PENDING
        assert record.pre_execution_phase_value is None


class TestLegalTransitions:
    def test_full_success_path_succeeds(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
        )
        store.start_step_3("wf-1")
        final = store.mark_step_3_completed("wf-1")
        assert final.overall_status is CompoundOverallStatus.COMPLETED
        assert final.step_1_status is CompoundStepStatus.COMPLETED
        assert final.step_2_status is CompoundStepStatus.COMPLETED
        assert final.step_3_status is CompoundStepStatus.COMPLETED

    def test_verification_failure_path_reaches_failed_terminal_state(
        self, store
    ) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        final = store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.FAILED
        )
        assert final.overall_status is CompoundOverallStatus.FAILED
        assert final.step_3_status is CompoundStepStatus.PENDING  # never started

    def test_show_failure_after_verified_update_is_genuine_partial_completion(
        self, store
    ) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
        )
        store.start_step_3("wf-1")
        final = store.mark_step_3_failed("wf-1")
        assert final.step_1_status is CompoundStepStatus.COMPLETED
        assert final.step_2_verification_outcome is CompoundVerificationOutcome.VERIFIED
        assert final.step_3_status is CompoundStepStatus.FAILED
        assert final.overall_status is CompoundOverallStatus.FAILED


class TestIllegalTransitions:
    def test_step_2_cannot_start_before_step_1_completes(self, store) -> None:
        _create(store)
        with pytest.raises(CompoundWorkflowProgressError):
            store.start_step_2("wf-1")

    def test_step_3_cannot_start_before_step_2_verified(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.UNAVAILABLE
        )
        with pytest.raises(CompoundWorkflowProgressError):
            store.start_step_3("wf-1")

    def test_step_order_cannot_reverse(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
        )
        store.start_step_3("wf-1")
        store.mark_step_3_completed("wf-1")
        # Attempting to "go back" to step 1 or step 2 after completion:
        with pytest.raises(CompoundWorkflowProgressError):
            store.record_pre_execution_observation(
                "wf-1", phase_value="x", last_updated=None
            )
        with pytest.raises(CompoundWorkflowProgressError):
            store.start_step_2("wf-1")

    def test_completed_progress_cannot_restart(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
        )
        store.start_step_3("wf-1")
        store.mark_step_3_completed("wf-1")
        with pytest.raises(CompoundWorkflowProgressError):
            store.mark_step_3_completed("wf-1")

    def test_failed_terminal_progress_cannot_silently_reactivate(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.FAILED
        )
        with pytest.raises(CompoundWorkflowProgressError):
            store.start_step_3("wf-1")
        with pytest.raises(CompoundWorkflowProgressError):
            store.mark_needs_reconciliation("wf-1")

    def test_needs_reconciliation_illegal_after_completion(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        store.mark_step_1_completed("wf-1")
        store.start_step_2("wf-1")
        store.mark_step_2_completed(
            "wf-1", verification_outcome=CompoundVerificationOutcome.VERIFIED
        )
        store.start_step_3("wf-1")
        store.mark_step_3_completed("wf-1")
        with pytest.raises(CompoundWorkflowProgressError):
            store.mark_needs_reconciliation("wf-1")


class TestConcurrentAdvancement:
    def test_duplicate_concurrent_advancement_is_detected(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        # Two independent "callers" both believe step_1_status is
        # IN_PROGRESS and both attempt to complete it - only one may
        # succeed; the second must be rejected, never silently
        # duplicated or silently ignored.
        store.mark_step_1_completed("wf-1")
        with pytest.raises(CompoundWorkflowProgressError):
            store.mark_step_1_completed("wf-1")

    def test_two_pre_execution_observations_cannot_both_apply(self, store) -> None:
        _create(store)
        store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )
        with pytest.raises(CompoundWorkflowProgressError):
            store.record_pre_execution_observation(
                "wf-1", phase_value="planning", last_updated=None
            )


class TestNoArbitraryPayload:
    def test_model_declares_only_bounded_columns(self) -> None:
        columns = {c.name for c in CompoundWorkflowProgress.__table__.columns}
        assert columns == {
            "id",
            "workflow_id",
            "template_id",
            "request_id",
            "approved_phase_value",
            "pre_execution_phase_value",
            "pre_execution_last_updated",
            "step_1_status",
            "step_2_status",
            "step_2_verification_outcome",
            "step_3_status",
            "overall_status",
            "created_at",
            "updated_at",
        }


class TestRestartSurvival:
    def test_store_reload_survives_process_restart(self, engine) -> None:
        first_factory = create_session_factory(engine)
        first_store = CompoundWorkflowProgressStore(first_factory)
        _create(first_store)
        first_store.record_pre_execution_observation(
            "wf-1", phase_value="planning", last_updated=None
        )

        # A fresh store instance, built from a fresh session factory
        # against the same underlying database, simulating a restart.
        second_factory = create_session_factory(engine)
        second_store = CompoundWorkflowProgressStore(second_factory)
        reloaded = second_store.get("wf-1")

        assert reloaded is not None
        assert reloaded.step_1_status is CompoundStepStatus.IN_PROGRESS
        assert reloaded.pre_execution_phase_value == "planning"

    def test_list_all_returns_every_row(self, store) -> None:
        _create(store, "wf-1")
        _create(store, "wf-2")
        records = store.list_all()
        assert {r.workflow_id for r in records} == {"wf-1", "wf-2"}


class TestReconciliation:
    _T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _T1 = _T0 + timedelta(minutes=1)

    def test_differing_pre_state_plus_matching_post_state_is_state_changed(
        self,
    ) -> None:
        result = reconcile_phase_update(
            approved_phase_value="implementation",
            pre_execution_phase_value="planning",
            pre_execution_last_updated=self._T0,
            current_phase_value="implementation",
            current_last_updated=self._T1,
        )
        assert (
            result.confidence
            is ReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED
        )

    def test_already_matching_pre_state_without_timestamp_evidence_is_unconfirmed(
        self,
    ) -> None:
        result = reconcile_phase_update(
            approved_phase_value="implementation",
            pre_execution_phase_value="implementation",
            pre_execution_last_updated=self._T0,
            current_phase_value="implementation",
            current_last_updated=self._T0,
        )
        assert (
            result.confidence
            is ReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED
        )
        assert "cannot be confirmed" in result.detail

    def test_already_matching_pre_state_with_timestamp_evidence_is_state_changed(
        self,
    ) -> None:
        result = reconcile_phase_update(
            approved_phase_value="implementation",
            pre_execution_phase_value="implementation",
            pre_execution_last_updated=self._T0,
            current_phase_value="implementation",
            current_last_updated=self._T1,
        )
        assert (
            result.confidence
            is ReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED
        )

    def test_missing_project_state_is_not_satisfied(self) -> None:
        result = reconcile_phase_update(
            approved_phase_value="implementation",
            pre_execution_phase_value=None,
            pre_execution_last_updated=None,
            current_phase_value=None,
            current_last_updated=None,
        )
        assert result.confidence is ReconciliationConfidence.POSTCONDITION_NOT_SATISFIED

    def test_independently_changed_unexpected_state_is_not_satisfied(self) -> None:
        result = reconcile_phase_update(
            approved_phase_value="implementation",
            pre_execution_phase_value="planning",
            pre_execution_last_updated=self._T0,
            current_phase_value="some_other_value_entirely",
            current_last_updated=self._T1,
        )
        assert result.confidence is ReconciliationConfidence.POSTCONDITION_NOT_SATISFIED
        assert "independently" in result.detail

    def test_no_pre_execution_observation_recorded_is_unconfirmed(self) -> None:
        result = reconcile_phase_update(
            approved_phase_value="implementation",
            pre_execution_phase_value=None,
            pre_execution_last_updated=None,
            current_phase_value="implementation",
            current_last_updated=None,
        )
        assert (
            result.confidence
            is ReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED
        )

    @staticmethod
    def _referenced_identifiers(func: object) -> set[str]:
        """Return every real ast.Name/ast.Attribute/import identifier a
        function's own code body references - deliberately excluding
        its docstring (an ast.Constant, never an ast.Name), which may
        legitimately *name* a class while explaining what is not
        called."""
        import ast
        import inspect
        import textwrap

        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
        identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                identifiers.add(node.attr)
            elif isinstance(node, ast.Import):
                identifiers.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                identifiers.update(node.module.split("."))
        return identifiers

    def test_reconciliation_never_calls_the_write_tool(self) -> None:
        identifiers = self._referenced_identifiers(reconcile_phase_update)
        assert "ToolExecutor" not in identifiers
        assert "ProjectStateStore" not in identifiers
        assert "run" not in identifiers

    def test_reconciliation_never_creates_approval(self) -> None:
        identifiers = self._referenced_identifiers(reconcile_phase_update)
        assert "ApprovalManager" not in identifiers
        assert "approve" not in identifiers

    def test_reconciliation_never_fabricates_audit_execution(self) -> None:
        identifiers = self._referenced_identifiers(reconcile_phase_update)
        assert "workflow_history" not in identifiers
        assert "record_transition" not in identifiers

    def test_reconciliation_never_claims_exactly_once(self) -> None:
        for member in ReconciliationConfidence:
            assert "exactly" not in member.value
