"""
test_schedule_compound_workflow_progress_store.py

Unit tests for ScheduleCompoundWorkflowProgressStore and
reconcile_schedule_enable (Phase 99, Batch 2 -
docs/phase_99_second_compound_template_planning.md), mirroring
test_compound_workflow_progress_store.py's own established pattern.

These use a real, in-memory SQLite database (not a fake), exercising
the same storage layer this future foundation would use at runtime,
including its real, single-statement compare-and-set transitions.

No live wiring exists anywhere in this file -
ScheduleCompoundWorkflowProgressStore is not called from any restart/
execution path in this batch; these are its own, dedicated,
foundation-proving tests.
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from storage.database import create_session_factory, initialize_database  # noqa: E402
from storage.models import (  # noqa: E402
    CompoundWorkflowProgress,
    ScheduleCompoundWorkflowProgress,
    ScheduleEntry,
)
from workflow.schedule_compound_workflow_progress_store import (  # noqa: E402
    ALLOWED_SCHEDULE_TEMPLATE_ID,
    ScheduleCompoundOverallStatus,
    ScheduleCompoundStepStatus,
    ScheduleCompoundVerificationOutcome,
    ScheduleCompoundWorkflowProgressError,
    ScheduleCompoundWorkflowProgressStore,
    ScheduleReconciliationConfidence,
    reconcile_schedule_enable,
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
def store(session_factory) -> ScheduleCompoundWorkflowProgressStore:
    return ScheduleCompoundWorkflowProgressStore(session_factory)


def _create(
    store: ScheduleCompoundWorkflowProgressStore, workflow_id: str = "wf-1"
):
    return store.create(
        workflow_id=workflow_id,
        template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
        request_id="req-1",
        schedule_id=42,
    )


class TestTableCreationAndIsolation:
    def test_table_is_created_additively(self, session_factory) -> None:
        with session_factory() as db:
            assert db.query(ScheduleCompoundWorkflowProgress).count() == 0

    def test_existing_tables_remain_untouched(self, session_factory) -> None:
        with session_factory() as db:
            assert db.query(CompoundWorkflowProgress).count() == 0
            assert db.query(ScheduleEntry).count() == 0


class TestFixedTemplateIdentity:
    def test_allowed_template_id_is_accepted(self, store) -> None:
        record = _create(store)
        assert record.template_id == ALLOWED_SCHEDULE_TEMPLATE_ID

    def test_a_different_template_id_is_rejected(self, store) -> None:
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.create(
                workflow_id="wf-x",
                template_id="not_the_real_template",
                request_id="req-x",
                schedule_id=1,
            )


class TestCreateAndGet:
    def test_create_returns_all_pending_initial_state(self, store) -> None:
        record = _create(store)
        assert record.schedule_id == 42
        assert record.request_id == "req-1"
        assert record.pre_execution_enabled is None
        assert record.step_1_status is ScheduleCompoundStepStatus.PENDING
        assert record.step_2_status is ScheduleCompoundStepStatus.PENDING
        assert record.step_2_verification_outcome is None
        assert record.step_3_status is ScheduleCompoundStepStatus.PENDING
        assert record.overall_status is ScheduleCompoundOverallStatus.PENDING

    def test_get_returns_none_for_unknown_workflow(self, store) -> None:
        assert store.get("nonexistent") is None

    def test_duplicate_workflow_id_is_rejected(self, store) -> None:
        """create() has no special duplicate-workflow_id handling of
        its own - the table's unique constraint on workflow_id is what
        actually rejects a second row, raising a raw
        sqlalchemy.exc.IntegrityError (never silently overwriting or
        duplicating), exactly mirroring
        ScheduleCompoundWorkflowProgress's own established shape."""
        _create(store, workflow_id="wf-dup")
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            _create(store, workflow_id="wf-dup")

    def test_exact_schedule_id_persists(self, store) -> None:
        record = store.create(
            workflow_id="wf-2",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-2",
            schedule_id=999,
        )
        assert record.schedule_id == 999

    def test_list_all_returns_oldest_first(self, store) -> None:
        _create(store, workflow_id="wf-a")
        _create(store, workflow_id="wf-b")
        rows = store.list_all()
        assert [r.workflow_id for r in rows] == ["wf-a", "wf-b"]

    def test_reload_from_new_store_instance_sees_same_row(
        self, store, session_factory
    ) -> None:
        _create(store, workflow_id="wf-reload")
        second_store = ScheduleCompoundWorkflowProgressStore(session_factory)
        record = second_store.get("wf-reload")
        assert record is not None
        assert record.schedule_id == 42


class TestHappyPathTransitions:
    def test_full_success_progression(self, store) -> None:
        _create(store, workflow_id="wf-ok")
        record = store.record_pre_execution_observation("wf-ok", enabled=False)
        assert record.step_1_status is ScheduleCompoundStepStatus.IN_PROGRESS
        assert record.overall_status is ScheduleCompoundOverallStatus.IN_PROGRESS
        assert record.pre_execution_enabled is False

        record = store.mark_step_1_completed("wf-ok")
        assert record.step_1_status is ScheduleCompoundStepStatus.COMPLETED

        record = store.start_step_2("wf-ok")
        assert record.step_2_status is ScheduleCompoundStepStatus.IN_PROGRESS

        record = store.mark_step_2_completed(
            "wf-ok",
            verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
        )
        assert record.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.VERIFIED
        )
        assert record.overall_status is ScheduleCompoundOverallStatus.IN_PROGRESS

        record = store.start_step_3("wf-ok")
        assert record.step_3_status is ScheduleCompoundStepStatus.IN_PROGRESS

        record = store.mark_step_3_completed("wf-ok")
        assert record.step_3_status is ScheduleCompoundStepStatus.COMPLETED
        assert record.overall_status is ScheduleCompoundOverallStatus.COMPLETED

    def test_step_1_failure_sets_overall_failed(self, store) -> None:
        _create(store, workflow_id="wf-1fail")
        store.record_pre_execution_observation("wf-1fail", enabled=False)
        record = store.mark_step_1_failed("wf-1fail")
        assert record.step_1_status is ScheduleCompoundStepStatus.FAILED
        assert record.overall_status is ScheduleCompoundOverallStatus.FAILED

    def test_step_2_non_verified_outcome_sets_overall_failed(self, store) -> None:
        _create(store, workflow_id="wf-2fail")
        store.record_pre_execution_observation("wf-2fail", enabled=False)
        store.mark_step_1_completed("wf-2fail")
        store.start_step_2("wf-2fail")
        record = store.mark_step_2_completed(
            "wf-2fail",
            verification_outcome=ScheduleCompoundVerificationOutcome.FAILED,
        )
        assert record.overall_status is ScheduleCompoundOverallStatus.FAILED

        record2 = store.mark_step_2_completed  # sanity: cannot call twice
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            record2(
                "wf-2fail",
                verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
            )

    def test_step_3_failure_sets_overall_failed_but_preserves_step_1_2(
        self, store
    ) -> None:
        _create(store, workflow_id="wf-3fail")
        store.record_pre_execution_observation("wf-3fail", enabled=False)
        store.mark_step_1_completed("wf-3fail")
        store.start_step_2("wf-3fail")
        store.mark_step_2_completed(
            "wf-3fail",
            verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
        )
        store.start_step_3("wf-3fail")
        record = store.mark_step_3_failed("wf-3fail")
        assert record.step_3_status is ScheduleCompoundStepStatus.FAILED
        assert record.overall_status is ScheduleCompoundOverallStatus.FAILED
        assert record.step_1_status is ScheduleCompoundStepStatus.COMPLETED
        assert record.step_2_verification_outcome is (
            ScheduleCompoundVerificationOutcome.VERIFIED
        )


class TestIllegalTransitionsRejected:
    def test_start_step_2_before_step_1_completed_is_rejected(self, store) -> None:
        _create(store, workflow_id="wf-illegal-1")
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.start_step_2("wf-illegal-1")

    def test_start_step_3_before_step_2_verified_is_rejected(self, store) -> None:
        _create(store, workflow_id="wf-illegal-2")
        store.record_pre_execution_observation("wf-illegal-2", enabled=False)
        store.mark_step_1_completed("wf-illegal-2")
        store.start_step_2("wf-illegal-2")
        store.mark_step_2_completed(
            "wf-illegal-2",
            verification_outcome=ScheduleCompoundVerificationOutcome.FAILED,
        )
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.start_step_3("wf-illegal-2")

    def test_mark_step_1_failed_before_in_progress_is_rejected(self, store) -> None:
        _create(store, workflow_id="wf-illegal-3")
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_step_1_failed("wf-illegal-3")

    def test_double_completion_is_rejected(self, store) -> None:
        _create(store, workflow_id="wf-illegal-4")
        store.record_pre_execution_observation("wf-illegal-4", enabled=False)
        store.mark_step_1_completed("wf-illegal-4")
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_step_1_completed("wf-illegal-4")

    def test_transition_on_unknown_workflow_is_rejected(self, store) -> None:
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_step_1_completed("does-not-exist")


class TestConcurrentCasRejection:
    def test_concurrent_step_1_completion_only_one_succeeds(self, store) -> None:
        _create(store, workflow_id="wf-race")
        store.record_pre_execution_observation("wf-race", enabled=False)
        store.mark_step_1_completed("wf-race")
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_step_1_completed("wf-race")


class TestNotExecutedTerminalization:
    def test_pristine_row_becomes_not_executed(self, store) -> None:
        _create(store, workflow_id="wf-decline")
        record = store.mark_not_executed_before_start("wf-decline")
        assert record.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED
        assert record.step_1_status is ScheduleCompoundStepStatus.PENDING
        assert record.step_2_status is ScheduleCompoundStepStatus.PENDING
        assert record.step_3_status is ScheduleCompoundStepStatus.PENDING

    def test_idempotent_repeat_call(self, store) -> None:
        _create(store, workflow_id="wf-decline2")
        store.mark_not_executed_before_start("wf-decline2")
        record = store.mark_not_executed_before_start("wf-decline2")
        assert record.overall_status is ScheduleCompoundOverallStatus.NOT_EXECUTED

    def test_rejected_after_step_1_has_started(self, store) -> None:
        _create(store, workflow_id="wf-started")
        store.record_pre_execution_observation("wf-started", enabled=False)
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_not_executed_before_start("wf-started")

    def test_unknown_workflow_raises(self, store) -> None:
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_not_executed_before_start("does-not-exist")


class TestNeedsReconciliation:
    def test_marks_needs_reconciliation_from_in_progress(self, store) -> None:
        _create(store, workflow_id="wf-needs")
        store.record_pre_execution_observation("wf-needs", enabled=False)
        record = store.mark_needs_reconciliation("wf-needs")
        assert record.overall_status is (
            ScheduleCompoundOverallStatus.NEEDS_RECONCILIATION
        )

    def test_rejected_once_terminal(self, store) -> None:
        _create(store, workflow_id="wf-needs2")
        store.record_pre_execution_observation("wf-needs2", enabled=False)
        store.mark_step_1_failed("wf-needs2")
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_needs_reconciliation("wf-needs2")

    def test_unknown_workflow_raises(self, store) -> None:
        with pytest.raises(ScheduleCompoundWorkflowProgressError):
            store.mark_needs_reconciliation("does-not-exist")


class TestReconcileScheduleEnable:
    def test_current_not_enabled_is_not_satisfied(self) -> None:
        result = reconcile_schedule_enable(
            pre_execution_enabled=False, current_enabled=False
        )
        assert result.confidence is (
            ScheduleReconciliationConfidence.POSTCONDITION_NOT_SATISFIED
        )

    def test_current_none_is_not_satisfied(self) -> None:
        result = reconcile_schedule_enable(
            pre_execution_enabled=False, current_enabled=None
        )
        assert result.confidence is (
            ScheduleReconciliationConfidence.POSTCONDITION_NOT_SATISFIED
        )

    def test_pre_false_current_true_is_state_changed(self) -> None:
        result = reconcile_schedule_enable(
            pre_execution_enabled=False, current_enabled=True
        )
        assert result.confidence is (
            ScheduleReconciliationConfidence.POSTCONDITION_SATISFIED_STATE_CHANGED
        )

    def test_pre_true_current_true_is_execution_unconfirmed(self) -> None:
        result = reconcile_schedule_enable(
            pre_execution_enabled=True, current_enabled=True
        )
        assert result.confidence is (
            ScheduleReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED
        )

    def test_pre_none_current_true_is_execution_unconfirmed(self) -> None:
        """No pre-execution observation was ever recorded - honestly
        unconfirmed, exactly mirroring reconcile_phase_update()'s own
        equivalent 'no pre-execution value recorded' case."""
        result = reconcile_schedule_enable(
            pre_execution_enabled=None, current_enabled=True
        )
        assert result.confidence is (
            ScheduleReconciliationConfidence.POSTCONDITION_SATISFIED_EXECUTION_UNCONFIRMED
        )


class TestCrossModuleTemplateIdConsistency:
    def test_allowed_template_id_matches_the_grounding_module(self) -> None:
        """Cross-module consistency is proven by a dedicated test, not
        by a shared import - mirrors the equivalent Phase 98 proof for
        ALLOWED_TEMPLATE_ID."""
        from intelligence.schedule_compound_grounding import (
            _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES,
        )

        assert len(_ALLOWED_SCHEDULE_COMPOUND_TEMPLATES) == 1
        assert (
            _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES[0].template_id
            == ALLOWED_SCHEDULE_TEMPLATE_ID
        )


class TestBoundedCategoryReads:
    """Phase 100, Batch 1 bounded-read correction
    (docs/phase_100_intelligence_core_gap_audit.md): direct, store-level
    proof that each of the four new list_recent_*() methods is a real,
    hard-limited SQL query - mirrors
    test_compound_workflow_progress_store.py's own equivalent class
    exactly.
    """

    def _drive_to_verified(
        self, store: ScheduleCompoundWorkflowProgressStore, workflow_id: str
    ) -> None:
        store.record_pre_execution_observation(workflow_id, enabled=False)
        store.mark_step_1_completed(workflow_id)
        store.start_step_2(workflow_id)
        store.mark_step_2_completed(
            workflow_id,
            verification_outcome=ScheduleCompoundVerificationOutcome.VERIFIED,
        )

    def test_list_recent_verified_is_hard_limited_below_true_row_count(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        for i in range(30):
            store.create(
                workflow_id=f"wf-{i}",
                template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
                request_id=f"req-{i}",
                schedule_id=i,
            )
            self._drive_to_verified(store, f"wf-{i}")

        result = store.list_recent_verified(limit=5)
        assert len(result) == 5

    def test_list_recent_verified_returns_the_newest_rows_first(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        for i in range(10):
            store.create(
                workflow_id=f"wf-{i}",
                template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
                request_id=f"req-{i}",
                schedule_id=i,
            )
            self._drive_to_verified(store, f"wf-{i}")

        result = store.list_recent_verified(limit=5)
        assert [record.workflow_id for record in result] == [
            "wf-9", "wf-8", "wf-7", "wf-6", "wf-5",
        ]

    def test_requested_limit_beyond_the_hard_ceiling_is_clamped(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        for i in range(30):
            store.create(
                workflow_id=f"wf-{i}",
                template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
                request_id=f"req-{i}",
                schedule_id=i,
            )
            self._drive_to_verified(store, f"wf-{i}")

        result = store.list_recent_verified(limit=10_000)
        assert len(result) <= 25  # _MAX_CATEGORY_QUERY_LIMIT

    def test_list_recent_pending_verification_excludes_verified_rows(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        _create(store, "wf-pending")
        store.create(
            workflow_id="wf-verified",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-verified",
            schedule_id=99,
        )
        self._drive_to_verified(store, "wf-verified")

        result = store.list_recent_pending_verification(limit=5)
        assert [record.workflow_id for record in result] == ["wf-pending"]

    def test_list_recent_verification_problems_excludes_verified_rows(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        store.create(
            workflow_id="wf-mismatch",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-mismatch",
            schedule_id=1,
        )
        store.record_pre_execution_observation("wf-mismatch", enabled=False)
        store.mark_step_1_completed("wf-mismatch")
        store.start_step_2("wf-mismatch")
        store.mark_step_2_completed(
            "wf-mismatch",
            verification_outcome=ScheduleCompoundVerificationOutcome.FAILED,
        )
        store.create(
            workflow_id="wf-verified",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-verified",
            schedule_id=2,
        )
        self._drive_to_verified(store, "wf-verified")

        result = store.list_recent_verification_problems(limit=5)
        assert [record.workflow_id for record in result] == ["wf-mismatch"]

    def test_list_recent_not_executed_only_returns_not_executed_rows(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        store.create(
            workflow_id="wf-not-executed",
            template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
            request_id="req-1",
            schedule_id=1,
        )
        store.mark_not_executed_before_start("wf-not-executed")
        _create(store, "wf-pending")

        result = store.list_recent_not_executed(limit=5)
        assert [record.workflow_id for record in result] == ["wf-not-executed"]

    def test_list_all_is_unchanged_and_still_unbounded(
        self, store: ScheduleCompoundWorkflowProgressStore
    ) -> None:
        """The bounded-read correction adds new methods; it must never
        change list_all()'s own existing, documented behaviour."""
        for i in range(12):
            store.create(
                workflow_id=f"wf-{i}",
                template_id=ALLOWED_SCHEDULE_TEMPLATE_ID,
                request_id=f"req-{i}",
                schedule_id=i,
            )
        assert len(store.list_all()) == 12
