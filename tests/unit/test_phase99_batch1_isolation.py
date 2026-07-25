"""
test_phase99_batch1_isolation.py

Structural proof that Phase 99, Batch 1's second compound foundation
(docs/phase_99_second_compound_template_planning.md) added zero live
compound wiring and zero change to Phase 98's own ProjectState compound
AT THE TIME - and, now that Phase 99, Batch 3 has atomically activated
the schedule compound live, that every reference this batch's own
modules/functions gained is confined exactly to the intended call
sites, never a broader, uncontrolled sprawl.

Every assertion below that concerned a module Batch 3 legitimately
wired (intelligence/planning.py, core/orchestrator.py, main.py) is
revised, not removed, to prove the reference is confined exactly there
- mirroring test_phase98_batch1_isolation.py's own revision when Phase
98's Batch 3 activated its compound the same way. ui/cli.py and
core/command_router.py remain fully unaffected (the schedule compound
is only ever reachable through the existing "ask jarvis to:" AI path,
never a new CLI/router grammar) and keep their original, unchanged
"must never reference this" bar.

Deliberately avoids fragile blanket assertions like "the symbol name
appears nowhere" - every check here either (a) proves a specific,
named function/method is the only live call site referencing a given
name (AST-based), or (b) behaviourally exercises the real, live,
generic single-capability dispatch to prove genuine reachability.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Phase 99, Batch 3: the only functions/methods in each live module
#: allowed to reference the schedule-compound machinery by name.
_PLANNING_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS = frozenset(
    {
        "_select_compound_tool_sequence",
        "_build_schedule_compound_outcome",
        "_build_schedule_enable_verify_show_workflow_plan",
    }
)
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


class TestProjectStateCompoundUnchanged:
    """Phase 98's own, already-closed ProjectState compound must be
    completely unaffected by this batch."""

    def test_live_allowlist_still_has_exactly_one_entry(self) -> None:
        from intelligence.compound_grounding import _ALLOWED_COMPOUND_TEMPLATES

        assert len(_ALLOWED_COMPOUND_TEMPLATES) == 1

    def test_live_allowlist_entry_is_still_the_project_state_pair(self) -> None:
        from intelligence.capability_catalog import CapabilityId
        from intelligence.compound_grounding import _ALLOWED_COMPOUND_TEMPLATES

        (template,) = _ALLOWED_COMPOUND_TEMPLATES
        assert template.steps == (
            CapabilityId.PROJECT_STATE_UPDATE_PHASE,
            CapabilityId.PROJECT_STATE_SHOW,
        )

    def test_trusted_instruction_now_describes_exactly_two_compound_shapes(
        self,
    ) -> None:
        """Phase 99, Batch 3 activation: the trusted instruction's own
        compound paragraph is revised, not merely left alone - it now
        legitimately names both the ProjectState pair and the schedule
        pair, and no other capability pairing, inside its own bounded
        execute_sequence description."""
        from intelligence.planning import _TRUSTED_PLANNING_INSTRUCTION

        assert (
            "Exactly two compound decisions exist, for exactly two fixed"
            in _TRUSTED_PLANNING_INSTRUCTION
        )
        compound_paragraph_start = _TRUSTED_PLANNING_INSTRUCTION.index(
            "Exactly two compound decisions exist"
        )
        compound_paragraph_end = _TRUSTED_PLANNING_INSTRUCTION.index(
            "If no capability above can satisfy"
        )
        compound_paragraph = _TRUSTED_PLANNING_INSTRUCTION[
            compound_paragraph_start:compound_paragraph_end
        ]
        assert "project_state_update_phase" in compound_paragraph
        assert "project_state_show" in compound_paragraph
        assert "schedule_enable" in compound_paragraph
        assert "schedule_show_enabled_state" in compound_paragraph
        # Never a third pairing, never SCHEDULE_DISABLE, never SCHEDULE_LIST.
        assert "schedule_disable" not in compound_paragraph
        assert "schedule_list" not in compound_paragraph


class TestScheduleCompoundReferencesConfinedToExpectedCallSites:
    """Phase 99, Batch 3 activation: intelligence/planning.py,
    core/orchestrator.py, and main.py now legitimately reference the
    schedule-compound modules - proven confined to exactly the intended
    functions/methods, never a broader, uncontrolled sprawl. ui/cli.py
    and core/command_router.py remain fully unaffected."""

    @pytest.mark.parametrize("relative_path", ("ui/cli.py", "core/command_router.py"))
    def test_schedule_compound_grounding_module_never_imported(
        self, relative_path: str
    ) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert "schedule_compound_grounding" not in referenced

    @pytest.mark.parametrize("relative_path", ("ui/cli.py", "core/command_router.py"))
    def test_schedule_compound_workflow_module_never_imported(
        self, relative_path: str
    ) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert "schedule_compound_workflow" not in referenced

    def test_intelligence_compound_grounding_never_imports_the_schedule_module(
        self,
    ) -> None:
        """The two allowlists stay wholly separate - the live
        ProjectState grounding module never merges in, or reads from,
        the schedule allowlist."""
        source = _module_source("intelligence/compound_grounding.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_grounding" not in referenced

    def test_core_compound_workflow_never_imports_the_schedule_module(self) -> None:
        source = _module_source("core/compound_workflow.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_workflow" not in referenced

    def test_planning_module_imports_schedule_compound_grounding(self) -> None:
        source = _module_source("intelligence/planning.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_grounding" in referenced

    def test_planning_schedule_compound_reference_confined_to_named_functions(
        self,
    ) -> None:
        source = _module_source("intelligence/planning.py")
        hits = _functions_referencing(source, "ground_schedule_compound_decision") | (
            _functions_referencing(source, "_build_schedule_enable_verify_show_workflow_plan")
        )
        assert hits <= _PLANNING_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS, (
            f"unexpected schedule-compound reference inside: "
            f"{hits - _PLANNING_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS}"
        )

    def test_orchestrator_imports_schedule_compound_workflow(self) -> None:
        source = _module_source("core/orchestrator.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_workflow" in referenced

    def test_orchestrator_schedule_compound_reference_confined_to_named_methods(
        self,
    ) -> None:
        source = _module_source("core/orchestrator.py")
        hits = _functions_referencing(source, "schedule_compound_workflow") | (
            _functions_referencing(source, "ScheduleCompoundStepObserver")
        )
        assert hits <= _ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS, (
            f"unexpected schedule-compound reference inside: "
            f"{hits - _ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS}"
        )

    def test_main_imports_schedule_compound_workflow(self) -> None:
        source = _module_source("main.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_workflow" in referenced

    def test_main_schedule_compound_reference_confined_to_named_functions(self) -> None:
        source = _module_source("main.py")
        hits = _functions_referencing(source, "schedule_compound")
        assert hits <= _MAIN_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS, (
            f"unexpected schedule_compound reference inside: "
            f"{hits - _MAIN_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS}"
        )


class TestDormantBuilderNowCalledOnlyThroughItsOwnDelegate:
    def test_select_tool_never_calls_the_schedule_builder_directly(self) -> None:
        """select_tool() itself must never call
        _build_schedule_enable_verify_show_workflow_plan() directly -
        only _select_compound_tool_sequence() (via its own
        _build_schedule_compound_outcome() delegate) may, keeping the
        delegation chain exactly as deep as the ProjectState template's
        own."""
        import intelligence.planning as module

        source = inspect.getsource(module.select_tool)
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_build_schedule_enable_verify_show_workflow_plan" not in called_names
        assert "_select_compound_tool_sequence" in called_names

    def test_no_live_function_outside_the_expected_set_references_the_builder(
        self,
    ) -> None:
        """Only the dormant builder's own definition, and its one
        expected caller, may reference its name."""
        import intelligence.planning as module

        source = inspect.getsource(module)
        tree = ast.parse(source)
        referencing_functions: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name == "_build_schedule_enable_verify_show_workflow_plan":
                continue
            segment = ast.get_source_segment(source, node) or ""
            if "_build_schedule_enable_verify_show_workflow_plan" in segment:
                referencing_functions.add(node.name)
        assert referencing_functions <= _PLANNING_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS


class TestLiveProgressApprovalObserverAndDispatchWiring:
    """Phase 99, Batch 3 activation: the schedule compound now
    legitimately creates progress, shows an approval, attaches an
    observer, and dispatches through its own named start-method -
    proven confined to exactly the intended call sites."""

    def test_schedule_compound_progress_store_confined_to_named_call_sites(
        self,
    ) -> None:
        import workflow.schedule_compound_workflow_progress_store as module

        assert hasattr(module, "ScheduleCompoundWorkflowProgressStore")
        for relative_path, allowed in (
            ("core/orchestrator.py", _ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS),
            ("main.py", _MAIN_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS),
        ):
            source = _module_source(relative_path)
            hits = _functions_referencing(source, "ScheduleCompoundWorkflowProgressStore")
            assert hits <= allowed, f"{relative_path}: unexpected hits {hits - allowed}"
        for relative_path in ("ui/cli.py", "core/command_router.py"):
            source = _module_source(relative_path)
            referenced = _referenced_module_names(source)
            assert "schedule_compound_workflow_progress_store" not in referenced

    def test_schedule_compound_progress_observer_confined_to_named_call_sites(
        self,
    ) -> None:
        import workflow.schedule_compound_progress_observer as module

        assert hasattr(module, "ScheduleCompoundStepObserver")
        source = _module_source("core/orchestrator.py")
        hits = _functions_referencing(source, "ScheduleCompoundStepObserver")
        assert hits <= _ORCHESTRATOR_ALLOWED_SCHEDULE_COMPOUND_FUNCTIONS
        for relative_path in ("ui/cli.py", "core/command_router.py"):
            source = _module_source(relative_path)
            referenced = _referenced_module_names(source)
            assert "schedule_compound_progress_observer" not in referenced

    def test_orchestrator_now_has_the_schedule_compound_start_method(self) -> None:
        from core.orchestrator import JarvisOrchestrator

        assert hasattr(JarvisOrchestrator, "_start_schedule_enable_and_show_workflow")

    def test_orchestrator_constructor_gains_exactly_one_new_schedule_compound_param(
        self,
    ) -> None:
        import inspect as _inspect

        from core.orchestrator import JarvisOrchestrator

        params = _inspect.signature(JarvisOrchestrator.__init__).parameters
        schedule_params = {name for name in params if "schedule_compound" in name}
        assert schedule_params == {"schedule_compound_progress_store"}

    def test_reconcile_claimed_handoffs_now_mentions_schedule_compound(self) -> None:
        source = inspect.getsource(__import__("main").reconcile_claimed_handoffs)
        assert "schedule_compound" in source.casefold()

    def test_ui_cli_source_remains_unaffected(self) -> None:
        source = _module_source("ui/cli.py")
        assert "schedule_compound" not in source.casefold()
        # SCHEDULE_SHOW_ENABLED_STATE itself (Batch 1's own standalone
        # capability) was never a CLI/router concern either - unaffected.
        assert "schedule_show_enabled_state" not in source

    def test_command_router_source_remains_unaffected(self) -> None:
        source = _module_source("core/command_router.py")
        assert "schedule_compound" not in source.casefold()
        assert "schedule_show_enabled_state" not in source


class TestNewCapabilityIsGenuinelyReachableNotAccidentallyHidden:
    """Behavioural, not merely structural, proof: the new standalone
    capability really is selectable through the existing, unmodified
    generic single-capability "ask jarvis to:" dispatch - it must never
    be described as inaccessible when it is not."""

    def test_a_standalone_execute_decision_for_the_new_capability_is_accepted(
        self,
    ) -> None:
        from intelligence.capability_catalog import CAPABILITY_CATALOG
        from intelligence.structured_output import parse_tool_selection

        raw = json.dumps(
            {
                "decision": "execute",
                "capability_id": "schedule_show_enabled_state",
                "arguments": {"schedule_id": 5},
            }
        )
        parsed = parse_tool_selection(raw, CAPABILITY_CATALOG)
        assert parsed.capability_id.value == "schedule_show_enabled_state"

    def test_the_new_capability_grounds_from_real_request_text(self) -> None:
        from intelligence.capability_catalog import CapabilityId
        from intelligence.grounding import ground_decision

        result = ground_decision(
            request_text="check the enabled state of schedule 5",
            capability_id=CapabilityId.SCHEDULE_SHOW_ENABLED_STATE,
            arguments={"schedule_id": 5},
        )
        assert result.grounded is True

    def test_the_new_capability_preflights_green_through_the_real_registry(
        self,
    ) -> None:
        """End-to-end proof through select_tool() itself, using a real
        ToolRegistry/SecurityManager/ScheduleStore and a fake AI
        provider whose response names only this one, real, standalone
        capability - never a compound decision."""
        pytest.importorskip("sqlalchemy")
        from sqlalchemy import create_engine

        from ai.prompt_builder import PromptBuilder
        from ai.providers.base import AIProvider, AIRequest, AIResponse
        from ai.response_validator import ResponseValidator
        from ai.router import AIRouter
        from config.settings import Settings
        from intelligence.context import AssembledContext
        from intelligence.planning import PlanningOutcomeKind, select_tool
        from scheduling.schedule_store import ScheduleStore
        from security.security_manager import SecurityManager
        from storage.database import create_session_factory, initialize_database
        from tools.builtin.schedule_show_enabled_state_tool import (
            ScheduleShowEnabledStateTool,
        )
        from tools.registry import ToolRegistry

        class _FakeProvider(AIProvider):
            @property
            def name(self) -> str:
                return "fake"

            def generate(self, request: AIRequest) -> AIResponse:
                return AIResponse(
                    text=json.dumps(
                        {
                            "decision": "execute",
                            "capability_id": "schedule_show_enabled_state",
                            "arguments": {"schedule_id": 5},
                        }
                    ),
                    model="fake-model",
                    provider="fake",
                )

            def is_available(self) -> bool:
                return True

        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        session_factory = create_session_factory(engine)
        store = ScheduleStore(session_factory)
        store.create(query="q", time_of_day="09:00")  # id 1
        for _ in range(3):
            store.create(query="q", time_of_day="09:00")
        record = store.create(query="q", time_of_day="09:00")
        assert record.id == 5

        registry = ToolRegistry()
        registry.register_tool(ScheduleShowEnabledStateTool(store))
        security = SecurityManager()
        router = AIRouter(
            provider=_FakeProvider(),
            prompt_builder=PromptBuilder(),
            validator=ResponseValidator(),
            logger=None,
            settings=Settings(
                anthropic_api_key="test-key-not-real",
                ai_model="test-model",
                ai_max_tokens=1024,
                database_path=Path("unused.db"),
                log_level="INFO",
                approval_timeout_seconds=60,
                debug=False,
                ai_reasoning_enabled=True,
            ),
        )

        outcome = select_tool(
            request_text="check the enabled state of schedule 5",
            assembled_context=AssembledContext(
                request_text="check the enabled state of schedule 5",
                items=(),
                total_chars=0,
                truncated=False,
                notes=(),
            ),
            router=router,
            tool_registry=registry,
            security_manager=security,
        )

        assert outcome.kind is PlanningOutcomeKind.EXECUTABLE
        assert outcome.plan is not None
        assert outcome.plan.steps[0].tool_name == "schedule_show_enabled_state"
        assert outcome.plan.steps[0].security_tier.name == "GREEN"
