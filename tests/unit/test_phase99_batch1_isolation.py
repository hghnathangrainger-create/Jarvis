"""
test_phase99_batch1_isolation.py

Structural proof that Phase 99, Batch 1's dormant second compound
foundation (docs/phase_99_second_compound_template_planning.md) adds
zero live compound wiring and zero change to Phase 98's own
ProjectState compound - while proving, behaviourally, that the new
SCHEDULE_SHOW_ENABLED_STATE capability genuinely IS reachable through
the existing, unmodified generic "ask jarvis to:" single-capability
path (never claimed inaccessible when it is not).

Deliberately avoids fragile blanket assertions like "the symbol name
appears nowhere" - every check here either (a) proves a specific,
named function is never called from a specific, named live call site
(AST-based, permitting the dormant definition to exist and be directly
tested elsewhere), or (b) behaviourally exercises the real, live,
generic single-capability dispatch to prove genuine reachability,
mirroring test_phase98_batch1_isolation.py's/
test_phase98_batch2_dormant_isolation.py's own established conventions.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


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

    def test_trusted_instruction_still_describes_exactly_one_compound_shape(
        self,
    ) -> None:
        """The trusted instruction's own compound paragraph is
        unchanged: it still names only the ProjectState pair, never
        the new schedule pair, in an execute_sequence context."""
        from intelligence.planning import _TRUSTED_PLANNING_INSTRUCTION

        assert (
            'Exactly one compound decision exists, for exactly one fixed'
            in _TRUSTED_PLANNING_INSTRUCTION
        )
        # The new capability appears only in its own single-capability
        # numbered entry and its own "Execute" example - never inside
        # an execute_sequence-shaped steps array.
        compound_paragraph_start = _TRUSTED_PLANNING_INSTRUCTION.index(
            "Exactly one compound decision exists"
        )
        compound_paragraph_end = _TRUSTED_PLANNING_INSTRUCTION.index(
            "If no capability above can satisfy"
        )
        compound_paragraph = _TRUSTED_PLANNING_INSTRUCTION[
            compound_paragraph_start:compound_paragraph_end
        ]
        assert "schedule_show_enabled_state" not in compound_paragraph
        assert "schedule_enable" not in compound_paragraph


class TestScheduleCompoundModulesAreNeverImportedLive:
    """The three new Batch 1 dormant modules/functions are never
    imported or called by any live runtime module - only their own
    dedicated tests exercise them."""

    @pytest.mark.parametrize(
        "relative_path",
        (
            "intelligence/planning.py",
            "core/orchestrator.py",
            "main.py",
            "ui/cli.py",
        ),
    )
    def test_schedule_compound_grounding_module_never_imported(
        self, relative_path: str
    ) -> None:
        source = _module_source(relative_path)
        referenced = _referenced_module_names(source)
        assert "schedule_compound_grounding" not in referenced

    @pytest.mark.parametrize(
        "relative_path",
        (
            "intelligence/planning.py",
            "core/orchestrator.py",
            "main.py",
            "ui/cli.py",
        ),
    )
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
        the new dormant schedule allowlist."""
        source = _module_source("intelligence/compound_grounding.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_grounding" not in referenced

    def test_core_compound_workflow_never_imports_the_schedule_module(self) -> None:
        source = _module_source("core/compound_workflow.py")
        referenced = _referenced_module_names(source)
        assert "schedule_compound_workflow" not in referenced


class TestDormantBuilderNeverCalledLive:
    def test_select_tool_never_calls_the_dormant_schedule_builder(self) -> None:
        import intelligence.planning as module

        source = inspect.getsource(module.select_tool)
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_build_schedule_enable_verify_show_workflow_plan" not in called_names

    def test_select_compound_tool_sequence_never_calls_the_dormant_schedule_builder(
        self,
    ) -> None:
        import intelligence.planning as module

        source = inspect.getsource(module._select_compound_tool_sequence)
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_build_schedule_enable_verify_show_workflow_plan" not in called_names

    def test_no_live_function_in_planning_module_references_the_dormant_builder(
        self,
    ) -> None:
        """Only the dormant builder's own definition may reference its
        own name (a function does not call itself in this codebase's
        established style) - no other function in the module does."""
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
        assert referencing_functions == set()


class TestNoLiveProgressApprovalObserverOrDispatchWiring:
    """Batch 1 must not create a ScheduleCompoundWorkflowProgress row
    during requests, show a compound approval, attach a compound
    observer, call a new _start_schedule_enable_and_show_workflow()
    path, change JarvisOrchestrator's live dispatch, or change main.py
    startup reconciliation."""

    def test_no_schedule_compound_progress_store_class_exists_yet(self) -> None:
        """Batch 1 deliberately adds no new ORM table/store - proven
        by import failure, not a substring search."""
        with pytest.raises(ImportError):
            import workflow.schedule_compound_workflow_progress_store  # noqa: F401

    def test_no_schedule_compound_progress_observer_module_exists_yet(self) -> None:
        with pytest.raises(ImportError):
            import workflow.schedule_compound_progress_observer  # noqa: F401

    def test_orchestrator_has_no_schedule_compound_start_method(self) -> None:
        from core.orchestrator import JarvisOrchestrator

        assert not hasattr(
            JarvisOrchestrator, "_start_schedule_enable_and_show_workflow"
        )

    def test_orchestrator_constructor_gains_no_new_schedule_compound_collaborator(
        self,
    ) -> None:
        import inspect as _inspect

        from core.orchestrator import JarvisOrchestrator

        params = _inspect.signature(JarvisOrchestrator.__init__).parameters
        assert not any("schedule_compound" in name for name in params)

    def test_reconcile_claimed_handoffs_source_never_mentions_schedule_compound(
        self,
    ) -> None:
        source = inspect.getsource(
            __import__("main").reconcile_claimed_handoffs
        )
        assert "schedule_compound" not in source.casefold()

    def test_ui_cli_source_is_unaffected(self) -> None:
        source = _module_source("ui/cli.py")
        assert "schedule_compound" not in source.casefold()
        assert "schedule_show_enabled_state" not in source


class TestNewCapabilityIsGenuinelyReachableNotAccidentallyHidden:
    """Behavioural, not merely structural, proof: the new capability
    really is selectable through the existing, unmodified generic
    single-capability "ask jarvis to:" dispatch - it must never be
    described as inaccessible when it is not."""

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
