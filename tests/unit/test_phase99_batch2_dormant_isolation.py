"""
test_phase99_batch2_dormant_isolation.py

Structural proof that Phase 99, Batch 2's schedule-compound durable
lifecycle (docs/phase_99_second_compound_template_planning.md) - the
progress table/store, the observer, and the Foundation F/G/H/I
additions to core/schedule_compound_workflow.py - added zero live
compound wiring and zero user-visible behavior AT THE TIME.

Phase 99, Batch 3 formally, atomically activated this lifecycle
through exactly two call sites - intelligence/planning.py's
select_tool() (the live two-template dispatch) and core/orchestrator.py
(consumes core/schedule_compound_workflow.py's functions and
workflow/schedule_compound_progress_observer.py's ScheduleCompoundStepObserver,
through its own new, narrow set of methods) - plus main.py's schedule-
compound-first startup recovery wiring. Every assertion below that
concerned those specific modules/functions is revised, not removed, to
prove the activation is confined exactly there - mirroring
test_phase98_batch2_dormant_isolation.py's own revision when Phase 98's
equivalent lifecycle was activated the same way.

Uses direct imports and module-source AST inspection - never brittle
raw-text search where a structural check is possible.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LIVE_RUNTIME_MODULES_UNAFFECTED = (
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

#: Phase 99, Batch 3: the only functions/methods in core/orchestrator.py
#: and main.py legitimately referencing the schedule-compound lifecycle.
_ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS = frozenset(
    {
        "__init__",
        "validate_pending_approval_for_transition",
        "_claim_and_resume_workflow",
        "_compound_step_observer_for",
        "_terminalize_declined_schedule_compound_progress",
        "_start_schedule_enable_and_show_workflow",
    }
)
_MAIN_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS = frozenset(
    {"build_orchestrator", "reconcile_claimed_handoffs"}
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


def _functions_referencing(source: str, needle: str) -> set[str]:
    tree = ast.parse(source)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if needle in segment:
            hits.add(node.name)
    return hits


class TestNewBatch2ModulesNeverImportedByUnaffectedModules:
    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES_UNAFFECTED)
    def test_module_does_not_import_batch2_internals(self, relative_path: str) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert not (referenced & _NEW_BATCH2_MODULE_NAMES), (
            f"{relative_path} must not import {referenced & _NEW_BATCH2_MODULE_NAMES}"
        )

    def test_schedule_compound_workflow_module_never_imported_by_unaffected_modules(
        self,
    ) -> None:
        for relative_path in _LIVE_RUNTIME_MODULES_UNAFFECTED:
            source = _module_source(relative_path)
            referenced = _referenced_module_names(source)
            assert "schedule_compound_workflow" not in referenced


class TestNewFunctionsConfinedToExpectedCallSites:
    """Every Foundation F/G/H/I function this batch added is referenced
    only by the exact, named live call sites Phase 99, Batch 3 wired -
    never a broader sprawl - and never at all by the unaffected
    modules."""

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

    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES_UNAFFECTED)
    def test_no_new_function_name_appears_in_unaffected_modules(
        self, relative_path: str
    ) -> None:
        source = _module_source(relative_path)
        for name in self._NEW_FUNCTION_NAMES:
            assert name not in source, f"{relative_path} unexpectedly references {name}"

    def test_orchestrator_reference_confined_to_named_methods(self) -> None:
        source = _module_source("core/orchestrator.py")
        hits: set[str] = set()
        for name in self._NEW_FUNCTION_NAMES:
            hits |= _functions_referencing(source, name)
        assert hits <= _ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS, (
            f"unexpected reference inside: {hits - _ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS}"
        )

    def test_main_reference_confined_to_named_functions(self) -> None:
        source = _module_source("main.py")
        hits: set[str] = set()
        for name in self._NEW_FUNCTION_NAMES:
            hits |= _functions_referencing(source, name)
        assert hits <= _MAIN_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS, (
            f"unexpected reference inside: {hits - _MAIN_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS}"
        )


class TestNoUserFacingInternalsExposure:
    def test_help_tool_has_no_internal_lifecycle_reference(self) -> None:
        source = _module_source("tools/builtin/help_tool.py")
        assert "ScheduleCompoundWorkflowProgress" not in source

    def test_user_guide_has_no_internal_lifecycle_reference(self) -> None:
        source = _module_source("docs/user_guide.md")
        assert "ScheduleCompoundWorkflowProgress" not in source


class TestOrchestratorAndMainScheduleCompoundWiring:
    """Phase 99, Batch 3 activation: core/orchestrator.py and main.py
    now legitimately reference the schedule-compound lifecycle -
    proven confined to exactly the intended methods/functions, never a
    broader, uncontrolled sprawl through either module."""

    def test_orchestrator_gains_exactly_one_new_schedule_compound_param(self) -> None:
        from core.orchestrator import JarvisOrchestrator

        params = inspect.signature(JarvisOrchestrator.__init__).parameters
        schedule_params = {name for name in params if "schedule_compound" in name}
        assert schedule_params == {"schedule_compound_progress_store"}

    def test_main_reconcile_claimed_handoffs_now_wires_schedule_compound(self) -> None:
        source = inspect.getsource(__import__("main").reconcile_claimed_handoffs)
        assert "schedule_compound" in source.casefold()

    def test_main_build_orchestrator_now_constructs_the_schedule_progress_store(
        self,
    ) -> None:
        source = inspect.getsource(__import__("main").build_orchestrator)
        assert "ScheduleCompoundWorkflowProgressStore" in source


class TestProjectStateCompoundStillUnaffected:
    """Phase 98's own, already-closed, live ProjectState compound
    remains completely unaffected by this batch."""

    def test_live_allowlist_still_has_exactly_one_entry(self) -> None:
        from intelligence.compound_grounding import _ALLOWED_COMPOUND_TEMPLATES

        assert len(_ALLOWED_COMPOUND_TEMPLATES) == 1

    def test_project_state_progress_table_untouched(self) -> None:
        from workflow.compound_workflow_progress_store import ALLOWED_TEMPLATE_ID

        assert ALLOWED_TEMPLATE_ID == "project_state_update_phase_then_show"


class TestScheduleCompoundGroundingAllowlistStillSingular:
    """The schedule-compound grounding allowlist is still exactly one
    entry, and still a wholly separate object from the ProjectState
    allowlist - the two-template dispatch reads from both, but neither
    allowlist is ever merged into the other."""

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


class TestObserverAttachmentBoundary:
    """WorkflowEngine.run() must structurally be unable to accept a
    step_observer - only resume()/_run_from() may - exactly as Phase
    98's own equivalent boundary requires. Shared, generic engine
    behaviour; not schedule-specific, but re-verified here since the
    schedule observer now depends on it being true."""

    def test_run_signature_has_no_step_observer_parameter(self) -> None:
        import workflow.engine as module

        tree = ast.parse(inspect.getsource(module))
        run_node = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "run"
        )
        arg_names = {arg.arg for arg in run_node.args.args} | {
            arg.arg for arg in run_node.args.kwonlyargs
        }
        assert "step_observer" not in arg_names


class TestNoNormalRequestCreatesScheduleCompoundStateWithoutTheOrchestrator:
    """A normal, real schedule_enable YELLOW pause through a raw
    WorkflowEngine (constructed directly, bypassing JarvisOrchestrator
    entirely - never attaching an observer or calling
    establish_schedule_compound_progress_or_isolate()) must create zero
    rows in the schedule-compound progress table - proving progress
    creation is exclusively the orchestrator's own
    _start_schedule_enable_and_show_workflow()'s responsibility, never
    an implicit side effect of running any schedule_enable plan through
    the engine."""

    def test_ordinary_schedule_enable_pause_creates_no_schedule_compound_progress(
        self,
    ) -> None:
        pytest.importorskip("sqlalchemy")
        from sqlalchemy import create_engine

        from approval.approval_manager import ApprovalManager
        from approval.pending_approval_store import PendingApprovalStore
        from config.constants import SecurityTier
        from planner.plan_models import Plan, PlanStep
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
