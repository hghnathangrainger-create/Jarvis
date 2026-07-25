"""
test_phase99_batch2_dormant_isolation.py

Structural proof that Phase 99, Batch 2's schedule-compound durable
lifecycle (docs/phase_99_second_compound_template_planning.md) - the
new progress table/store, the new observer, and the new Foundation
F/G/H/I additions to core/schedule_compound_workflow.py - adds zero
live compound wiring and zero user-visible behavior.

Mirrors test_phase98_batch2_dormant_isolation.py's own established
pattern from when the equivalent Phase 98 lifecycle was itself still
dormant (before its own, separately-approved live activation batch).

Uses direct imports and module-source AST inspection - never brittle
raw-text search where a structural check is possible.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LIVE_RUNTIME_MODULES = (
    "intelligence/planning.py",
    "core/orchestrator.py",
    "main.py",
    "ui/cli.py",
    "core/command_router.py",
    "intelligence/compound_grounding.py",
    "intelligence/compound_structured_output.py",
    "intelligence/structured_output.py",
    "core/compound_workflow.py",
    "workflow/compound_workflow_progress_store.py",
    "workflow/compound_progress_observer.py",
)

_NEW_BATCH2_MODULE_NAMES = frozenset(
    {"schedule_compound_workflow_progress_store", "schedule_compound_progress_observer"}
)


def _module_source(relative_path: str) -> str:
    return (_REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _referenced_module_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
    return names


class TestNewBatch2ModulesNeverImportedLive:
    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES)
    def test_module_does_not_import_batch2_internals(self, relative_path: str) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH2_MODULE_NAMES), (
            f"{relative_path} must not import {referenced & _NEW_BATCH2_MODULE_NAMES}"
        )

    def test_schedule_compound_workflow_module_still_never_imported_live(self) -> None:
        """core/schedule_compound_workflow.py itself (Batch 1's own
        module, now extended with Foundation F/G/H/I) must still never
        be imported by any live runtime module."""
        for relative_path in _LIVE_RUNTIME_MODULES:
            source = _module_source(relative_path)
            referenced = _referenced_module_names(source)
            assert "schedule_compound_workflow" not in referenced


class TestNewFunctionsNeverCalledLive:
    """Every Foundation F/G/H/I function this batch added is never
    referenced by name anywhere in the live runtime modules."""

    _NEW_FUNCTION_NAMES = (
        "establish_schedule_compound_progress_or_isolate",
        "repair_or_isolate_pending_schedule_compound_progress",
        "terminalize_declined_or_expired_schedule_compound_progress",
        "validate_schedule_compound_approval_before_transition",
        "resume_claimed_schedule_compound_workflow",
        "reconcile_claimed_schedule_compound_workflows",
        "translate_schedule_compound_workflow_result",
        "ScheduleCompoundStepObserver",
        "ScheduleCompoundWorkflowProgressStore",
    )

    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES)
    def test_no_new_function_name_appears_in_live_modules(
        self, relative_path: str
    ) -> None:
        source = _module_source(relative_path)
        for name in self._NEW_FUNCTION_NAMES:
            assert name not in source, f"{relative_path} unexpectedly references {name}"


class TestNoUserFacingExposure:
    def test_help_tool_has_no_new_lifecycle_reference(self) -> None:
        source = _module_source("tools/builtin/help_tool.py")
        assert "ScheduleCompoundWorkflowProgress" not in source
        assert "schedule compound" not in source.casefold()

    def test_user_guide_has_no_new_lifecycle_reference(self) -> None:
        source = _module_source("docs/user_guide.md")
        assert "ScheduleCompoundWorkflowProgress" not in source
        assert "schedule compound" not in source.casefold()


class TestOrchestratorAndMainUnaffected:
    def test_orchestrator_gains_no_new_schedule_compound_collaborator(self) -> None:
        from core.orchestrator import JarvisOrchestrator

        params = inspect.signature(JarvisOrchestrator.__init__).parameters
        assert not any("schedule_compound" in name for name in params)

    def test_main_reconcile_claimed_handoffs_unaffected(self) -> None:
        source = inspect.getsource(__import__("main").reconcile_claimed_handoffs)
        assert "schedule_compound" not in source.casefold()

    def test_main_build_orchestrator_gains_no_new_schedule_progress_store(self) -> None:
        source = inspect.getsource(__import__("main").build_orchestrator)
        assert "ScheduleCompoundWorkflowProgressStore" not in source


class TestProjectStateCompoundStillUnaffected:
    """Phase 98's own, already-closed, live ProjectState compound
    remains completely unaffected by this batch."""

    def test_live_allowlist_still_has_exactly_one_entry(self) -> None:
        from intelligence.compound_grounding import _ALLOWED_COMPOUND_TEMPLATES

        assert len(_ALLOWED_COMPOUND_TEMPLATES) == 1

    def test_project_state_progress_table_untouched(self) -> None:
        from workflow.compound_workflow_progress_store import ALLOWED_TEMPLATE_ID

        assert ALLOWED_TEMPLATE_ID == "project_state_update_phase_then_show"


class TestScheduleCompoundGroundingAllowlistStillDormantAndSingular:
    """Batch 1's own dormant schedule-compound grounding allowlist is
    unchanged by this batch - still exactly one entry, still never
    merged into the live ProjectState allowlist."""

    def test_schedule_allowlist_still_has_exactly_one_entry(self) -> None:
        from intelligence.schedule_compound_grounding import (
            _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES,
        )

        assert len(_ALLOWED_SCHEDULE_COMPOUND_TEMPLATES) == 1

    def test_two_allowlists_remain_wholly_separate_objects(self) -> None:
        from intelligence.compound_grounding import _ALLOWED_COMPOUND_TEMPLATES
        from intelligence.schedule_compound_grounding import (
            _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES,
        )

        assert _ALLOWED_COMPOUND_TEMPLATES is not _ALLOWED_SCHEDULE_COMPOUND_TEMPLATES


class TestNoLiveProgressCreationDuringOrdinaryRequests:
    """A normal, real schedule_enable YELLOW pause through the real
    WorkflowEngine (with no step_observer attached, exactly as every
    live request today) must create zero rows in the new table -
    proving the new lifecycle is inert unless a caller explicitly,
    separately invokes its own dormant functions (which no live path
    does)."""

    def test_ordinary_schedule_enable_pause_creates_no_schedule_compound_progress(
        self,
    ) -> None:
        pytest.importorskip("sqlalchemy")
        from sqlalchemy import create_engine

        from approval.approval_manager import ApprovalManager
        from approval.pending_approval_store import PendingApprovalStore
        from scheduling.schedule_store import ScheduleStore
        from security.security_manager import SecurityManager
        from storage.database import create_session_factory, initialize_database
        from tools.builtin.schedule_enable_tool import ScheduleEnableTool
        from tools.executor import ToolExecutor
        from tools.registry import ToolRegistry
        from workflow.engine import WorkflowEngine
        from workflow.schedule_compound_workflow_progress_store import (
            ScheduleCompoundWorkflowProgressStore,
        )
        from planner.plan_models import Plan, PlanStep
        from config.constants import SecurityTier

        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        session_factory = create_session_factory(engine)

        schedules = ScheduleStore(session_factory)
        record = schedules.create(query="q", time_of_day="09:00")
        registry = ToolRegistry()
        registry.register_tool(ScheduleEnableTool(schedules))
        security = SecurityManager()
        executor = ToolExecutor(registry=registry, security_manager=security, logger=None)
        pending_store = PendingApprovalStore(session_factory)
        approvals = ApprovalManager(pending_store=pending_store)
        workflow_engine = WorkflowEngine(executor=executor, approvals=approvals)
        progress_store = ScheduleCompoundWorkflowProgressStore(session_factory)

        single_step_plan = Plan(
            user_request="enable schedule",
            steps=(
                PlanStep(
                    number=1,
                    description="enable",
                    action="enable a schedule",
                    tier=SecurityTier.YELLOW,
                    reason="needs approval",
                    tool_name="schedule_enable",
                    tool_input={"schedule_id": record.id},
                ),
            ),
        )
        result = workflow_engine.run(single_step_plan)
        assert result.overall_status.value == "waiting"

        assert progress_store.list_all() == []
