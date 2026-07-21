"""
test_trusted_workflow_foundation.py

Unit tests for the Phase 94, Batch 1 generalization of the trusted,
approval-gated, two-step write-and-verify workflow foundation
(contracts fixed by docs/phase_94_implementation_plan.md, Section 13).

This batch replaces exactly two hardcoded, PROJECT_STATE_UPDATE_FOCUS-
specific pieces with trusted, catalog-driven equivalents:
    - intelligence/planning.py::_build_write_and_verify_workflow_plan()
      (renamed from _build_update_focus_workflow_plan()) now resolves
      its paired verifier capability from
      CapabilityAdapter.paired_verify_capability_id - a new, static,
      trusted catalog field - instead of a literal CapabilityId
      hardcoded inside the function body.
    - core/orchestrator.py::JarvisOrchestrator._is_update_focus_workflow_result()
      now derives its expected tool-name pair from CAPABILITY_CATALOG
      instead of two literal string constants.

No second production workflow capability is added by this batch.
PROJECT_STATE_UPDATE_FOCUS remains the only registered, user-facing
TWO_STEP_WORKFLOW capability - these tests prove the *mechanism* is
now genuinely data-driven (never hardcoded to "focus"/"project_state"
by name), using a test-local trusted workflow specification that is
never registered in CAPABILITY_CATALOG, never added as a real
user-facing capability, and never entered into the real runtime
catalogue - exactly as the Phase 94 Batch 1 task's own explicit
allowance requires.

Run with:
    pytest tests/unit/test_trusted_workflow_foundation.py
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

from config.constants import SecurityTier
from intelligence.capability_catalog import (
    CAPABILITY_CATALOG,
    CapabilityAdapter,
    CapabilityId,
    ExecutionStrategy,
)
from intelligence.planning import _build_write_and_verify_workflow_plan
from planner.plan_models import Plan
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.registry import ToolRegistry
from workflow.workflow_models import WorkflowResult


# --- Test doubles, never registered in production ---------------------------


class _FakeWriteTool(BaseTool):
    """A test-only write tool, registered only in a local ToolRegistry
    instance inside these tests - never in main.py, never in the real
    CAPABILITY_CATALOG."""

    @property
    def name(self) -> str:
        return "test_write_tool"

    @property
    def description(self) -> str:
        return "test-only write tool"

    def action_for(self, request: ToolRequest) -> str:
        # Deliberately matches no real SecurityManager rule keyword, so
        # classification falls through to the real, unmodified default
        # tier (YELLOW) - proving no new SecurityManager rule is needed
        # or added for this test-local capability.
        return "perform test only workflow write"

    def run(self, request: ToolRequest) -> ToolResult:
        return self.ok("test write executed")


class _FakeVerifyTool(BaseTool):
    """A test-only, read-only verify tool - never registered in
    production."""

    @property
    def name(self) -> str:
        return "test_verify_tool"

    @property
    def description(self) -> str:
        return "test-only verify tool"

    def action_for(self, request: ToolRequest) -> str:
        # Contains the existing, unmodified generic "show" GREEN rule's
        # keyword - no new SecurityManager rule needed.
        return "show test verification data"

    def run(self, request: ToolRequest) -> ToolResult:
        return self.ok("test verification data", metadata={"state": "matched"})


def _test_local_write_and_verify_catalog() -> tuple[
    CapabilityAdapter, CapabilityAdapter, dict[CapabilityId, CapabilityAdapter]
]:
    """Builds a test-local write+verify capability pairing that reuses
    two real CapabilityId enum members purely as dict keys/labels -
    this dict is never assigned to, or merged into, the real
    CAPABILITY_CATALOG module-level object, so it never becomes a real
    user-facing capability and never enters the real runtime catalogue.
    It exists solely to prove _build_write_and_verify_workflow_plan()
    is genuinely driven by whatever catalog/adapter it is given, not
    hardcoded to PROJECT_STATE_UPDATE_FOCUS/PROJECT_STATE_VERIFY_FOCUS
    by name.

    HEALTH_CHECK and SCHEDULE_LIST are reused here only as convenient,
    already-existing enum values to key a local dict - their real,
    production meanings are completely irrelevant to, and untouched by,
    this test fixture.
    """
    write_adapter = CapabilityAdapter(
        capability_id=CapabilityId.HEALTH_CHECK,
        tool_name="test_write_tool",
        description="test-only write capability",
        arguments=(),
        allowed_strategy=ExecutionStrategy.TWO_STEP_WORKFLOW,
        max_execution_tier=SecurityTier.YELLOW,
        verification_strategy_id="test_only_exact_match",
        internal_only=False,
        paired_verify_capability_id=CapabilityId.SCHEDULE_LIST,
    )
    verify_adapter = CapabilityAdapter(
        capability_id=CapabilityId.SCHEDULE_LIST,
        tool_name="test_verify_tool",
        description="test-only internal verify capability",
        arguments=(),
        allowed_strategy=ExecutionStrategy.SINGLE_TOOL,
        max_execution_tier=SecurityTier.GREEN,
        verification_strategy_id=None,
        internal_only=True,
    )
    local_catalog = {
        write_adapter.capability_id: write_adapter,
        verify_adapter.capability_id: verify_adapter,
    }
    return write_adapter, verify_adapter, local_catalog


def _test_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_tool(_FakeWriteTool())
    registry.register_tool(_FakeVerifyTool())
    return registry


# --- 1. The generalized workflow-builder is genuinely data-driven -----------


def test_workflow_builder_pairs_a_test_local_write_capability_with_its_own_verifier() -> (
    None
):
    """Direct proof of genericity: a write adapter that is not
    PROJECT_STATE_UPDATE_FOCUS, paired with a verify adapter that is
    not PROJECT_STATE_VERIFY_FOCUS, still produces a correct, real,
    two-step Plan - proving the function is driven entirely by
    write_adapter.paired_verify_capability_id and the supplied catalog,
    never a literal name check."""
    write_adapter, verify_adapter, catalog = _test_local_write_and_verify_catalog()

    plan = _build_write_and_verify_workflow_plan(
        "a test-only request",
        tool_input={"test_field": "test_value"},
        write_adapter=write_adapter,
        write_tier=SecurityTier.YELLOW,
        tool_registry=_test_registry(),
        security_manager=SecurityManager(),
        session_id=None,
        catalog=catalog,
    )

    assert isinstance(plan, Plan)
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "test_write_tool"
    assert plan.steps[0].tool_input == {"test_field": "test_value"}
    assert plan.steps[0].tier is SecurityTier.YELLOW
    assert plan.steps[1].tool_name == "test_verify_tool"
    assert plan.steps[1].tool_input == {}
    assert plan.steps[1].tier is SecurityTier.GREEN


def test_workflow_builder_ignores_tool_input_contents_when_selecting_the_verifier() -> (
    None
):
    """Verifier selection never reads arguments/tool_input, however it
    is shaped - only write_adapter.paired_verify_capability_id, a
    trusted, static catalog value, ever determines which verify
    capability is paired. A tool_input dict containing keys that look
    like they might influence verifier selection has no effect at all."""
    write_adapter, _verify_adapter, catalog = _test_local_write_and_verify_catalog()

    plan = _build_write_and_verify_workflow_plan(
        "a test-only request",
        tool_input={
            "test_field": "x",
            "paired_verify_capability_id": "something_else_entirely",
            "capability_id": "ignored",
            "verifier": "also_ignored",
        },
        write_adapter=write_adapter,
        write_tier=SecurityTier.YELLOW,
        tool_registry=_test_registry(),
        security_manager=SecurityManager(),
        session_id=None,
        catalog=catalog,
    )

    assert isinstance(plan, Plan)
    assert plan.steps[1].tool_name == "test_verify_tool"


def test_workflow_builder_refuses_honestly_when_no_verifier_is_paired() -> None:
    """A TWO_STEP_WORKFLOW capability whose paired_verify_capability_id
    is None (the default for every capability defined before Phase 94)
    is refused with the same honest, pre-existing failure reason -
    never a crash, never a silently-empty verify step."""
    write_adapter, _verify_adapter, catalog = _test_local_write_and_verify_catalog()
    unpaired_write_adapter = dataclasses.replace(
        write_adapter, paired_verify_capability_id=None
    )

    result = _build_write_and_verify_workflow_plan(
        "a test-only request",
        tool_input={},
        write_adapter=unpaired_write_adapter,
        write_tier=SecurityTier.YELLOW,
        tool_registry=_test_registry(),
        security_manager=SecurityManager(),
        session_id=None,
        catalog=catalog,
    )

    assert result == "the internal verification capability is not configured"


def test_workflow_builder_refuses_honestly_when_paired_verifier_is_absent_from_catalog() -> (
    None
):
    """A paired_verify_capability_id naming a capability that is not
    actually present in the supplied catalog is refused the same way -
    never a KeyError, never a fabricated verify step."""
    write_adapter, _verify_adapter, _catalog = _test_local_write_and_verify_catalog()
    only_write_catalog = {write_adapter.capability_id: write_adapter}

    result = _build_write_and_verify_workflow_plan(
        "a test-only request",
        tool_input={},
        write_adapter=write_adapter,
        write_tier=SecurityTier.YELLOW,
        tool_registry=_test_registry(),
        security_manager=SecurityManager(),
        session_id=None,
        catalog=only_write_catalog,
    )

    assert result == "the internal verification capability is not configured"


# --- 2. The real PROJECT_STATE_UPDATE_FOCUS workflow is unaffected ----------


def test_real_update_focus_workflow_still_builds_the_exact_existing_plan() -> None:
    """The one real TWO_STEP_WORKFLOW capability still produces the
    exact same two real tool names and exact same write tool_input,
    proving the generalization changed no observable behavior for it."""
    from tools.builtin.project_state_show_tool import ProjectStateShowTool
    from tools.builtin.project_state_update_tool import ProjectStateUpdateTool
    from tools.builtin.project_state_verify_tool import ProjectStateVerifyTool

    class _FakeProjectStateStore:
        def get(self):
            return None

        def update(self, field, value):
            return None

    registry = ToolRegistry()
    store = _FakeProjectStateStore()
    registry.register_tool(ProjectStateShowTool(store))  # type: ignore[arg-type]
    registry.register_tool(ProjectStateUpdateTool(store))  # type: ignore[arg-type]
    registry.register_tool(ProjectStateVerifyTool(store))  # type: ignore[arg-type]

    write_adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    plan = _build_write_and_verify_workflow_plan(
        "ask jarvis to: update my project focus to batch 94 verification",
        tool_input={"field": "focus", "value": "batch 94 verification"},
        write_adapter=write_adapter,
        write_tier=SecurityTier.YELLOW,
        tool_registry=registry,
        security_manager=SecurityManager(),
        session_id=None,
        catalog=CAPABILITY_CATALOG,
    )

    assert isinstance(plan, Plan)
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "project_state_update"
    assert plan.steps[0].tool_input == {
        "field": "focus",
        "value": "batch 94 verification",
    }
    assert plan.steps[1].tool_name == "project_state_verify"
    assert plan.steps[1].tool_input == {}


def test_paired_verify_capability_id_is_the_sole_source_of_verifier_identity() -> None:
    """The real catalog's own PROJECT_STATE_UPDATE_FOCUS entry names
    PROJECT_STATE_VERIFY_FOCUS as its paired verifier - re-confirmed
    directly, not merely assumed."""
    adapter = CAPABILITY_CATALOG[CapabilityId.PROJECT_STATE_UPDATE_FOCUS]
    assert adapter.paired_verify_capability_id is CapabilityId.PROJECT_STATE_VERIFY_FOCUS


# --- 3. Structural / anti-overgeneralization proofs -------------------------


def test_workflow_builder_never_calls_forbidden_execution_or_ai_apis() -> None:
    """The generalized workflow-builder remains a pure planning
    function: it never calls ToolExecutor, WorkflowEngine, an
    ApprovalManager, or any AI provider - it only ever prepares a Plan
    for the caller to run.

    Uses AST-based real-code-identifier extraction (Name/Attribute
    nodes only, and only from the function body - never the docstring,
    which is itself parsed as a separate ast.Constant string and
    excluded here), so a docstring merely mentioning "WorkflowEngine"
    in prose (as this function's own docstring does, explaining what
    the returned Plan is *for*) never produces a false positive."""
    import intelligence.planning as module

    source = inspect.getsource(module._build_write_and_verify_workflow_plan)
    tree = ast.parse(source)
    function_def = tree.body[0]
    assert isinstance(function_def, ast.FunctionDef)
    body_without_docstring = function_def.body[1:]  # skip the docstring Expr

    identifiers: set[str] = set()
    for node in ast.walk(ast.Module(body=body_without_docstring, type_ignores=[])):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            identifiers.add(node.func.id)

    for forbidden in (
        "ToolExecutor",
        "WorkflowEngine",
        "ApprovalManager",
        "AIRouter",
        "AIProvider",
        "run",
    ):
        assert forbidden not in identifiers


def test_workflow_builder_signature_accepts_no_model_output_parameter() -> None:
    """The function's only inputs are already-validated, already-
    resolved trusted values (request_text, already-built tool_input,
    the resolved write_adapter, the trusted catalog, and
    infrastructure collaborators) - never a raw parsed model decision
    or ToolSelectionDecision object."""
    import intelligence.planning as module

    signature = inspect.signature(module._build_write_and_verify_workflow_plan)
    parameter_names = set(signature.parameters)
    assert parameter_names == {
        "request_text",
        "tool_input",
        "write_adapter",
        "write_tier",
        "tool_registry",
        "security_manager",
        "session_id",
        "catalog",
    }


def test_capability_adapter_field_is_never_exposed_as_a_model_facing_argument() -> None:
    """paired_verify_capability_id can never appear as a model-facing
    CapabilityArgumentSpec - it is a trusted CapabilityAdapter field,
    never a declared argument any capability asks the model to supply."""
    for adapter in CAPABILITY_CATALOG.values():
        declared_argument_names = {spec.name for spec in adapter.arguments}
        assert "paired_verify_capability_id" not in declared_argument_names


def test_exactly_two_two_step_workflow_capabilities_exist_in_the_real_catalog() -> (
    None
):
    """Phase 94, Batch 2 adds exactly one second production workflow
    consumer, SCHEDULE_ENABLE - proving the Batch 1 foundation
    generalization genuinely supports a second TWO_STEP_WORKFLOW
    capability, and confirming no third one exists."""
    two_step_capabilities = {
        capability_id
        for capability_id, adapter in CAPABILITY_CATALOG.items()
        if adapter.allowed_strategy is ExecutionStrategy.TWO_STEP_WORKFLOW
    }
    assert two_step_capabilities == {
        CapabilityId.PROJECT_STATE_UPDATE_FOCUS,
        CapabilityId.SCHEDULE_ENABLE,
    }


def test_schedule_enable_capability_exists_and_no_further_expansion_occurred() -> (
    None
):
    """Confirms Batch 2 added exactly the two capabilities its own
    scope names - SCHEDULE_ENABLE and SCHEDULE_VERIFY_ENABLED_STATE -
    and nothing else: no SCHEDULE_DISABLE, no SCHEDULE_CREATE, and the
    real catalog contains exactly these eleven members."""
    assert any(member is CapabilityId.SCHEDULE_ENABLE for member in CapabilityId)
    assert not any("SCHEDULE_DISABLE" in member.name for member in CapabilityId)
    assert not any("SCHEDULE_CREATE" in member.name for member in CapabilityId)
    assert {member.value for member in CapabilityId} == {
        "project_state_show",
        "project_state_update_focus",
        "project_state_verify_focus",
        "health_check",
        "schedule_list",
        "memory_list_recent",
        "memory_search",
        "approval_history",
        "workflow_history",
        "schedule_enable",
        "schedule_verify_enabled_state",
    }


def test_schedule_verifier_strategy_id_is_the_only_new_one() -> None:
    strategy_ids = {
        adapter.verification_strategy_id
        for adapter in CAPABILITY_CATALOG.values()
        if adapter.verification_strategy_id is not None
    }
    assert strategy_ids == {
        "project_state_focus_exact_match",
        "schedule_enabled_exact_match",
    }


def test_exactly_two_verification_functions_exist_in_verification_module() -> None:
    """intelligence/verification.py now defines exactly two verifier
    functions - the pre-existing focus verifier, unmodified, plus the
    one new schedule-enabled-state verifier Batch 2 adds. No generic
    verifier registry or third function exists."""
    import intelligence.verification as module

    tree = ast.parse(inspect.getsource(module))
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert function_names == {"verify_focus_update", "verify_schedule_enabled_state"}


# --- 4. The orchestrator's structural recognizer is now catalog-driven -----


def _real_code_string_literals_and_names(source: str) -> tuple[set[object], set[str]]:
    """Extract only real ast.Constant string literals and ast.Name
    identifiers from a function's executable body - never its
    docstring, which is parsed as a separate ast.Constant string Expr
    and excluded here (Phase 92's own established false-positive-safe
    structural-test technique, applied to source text rather than an
    already-live function object)."""
    import textwrap

    tree = ast.parse(textwrap.dedent(source))
    function_def = tree.body[0]
    assert isinstance(function_def, ast.FunctionDef)
    body_without_docstring = ast.Module(
        body=function_def.body[1:], type_ignores=[]
    )
    string_literals = {
        node.value
        for node in ast.walk(body_without_docstring)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    names: set[str] = set()
    for node in ast.walk(body_without_docstring):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return string_literals, names


def test_is_update_focus_workflow_result_no_longer_hardcodes_string_literals() -> None:
    """Structural proof: the recognizer no longer contains the literal
    tool-name strings itself - it delegates to the shared
    _matches_two_step_workflow_shape() helper, which reads the exact
    tool-name pair from CAPABILITY_CATALOG (Phase 94, Batch 2 further
    factored the Batch 1 generalization into one shared helper, reused
    by both real recognizers, rather than duplicating the catalog
    lookup in each)."""
    from core.orchestrator import JarvisOrchestrator

    recognizer_literals, recognizer_names = _real_code_string_literals_and_names(
        inspect.getsource(JarvisOrchestrator._is_update_focus_workflow_result)
    )
    assert "project_state_update" not in recognizer_literals
    assert "project_state_verify" not in recognizer_literals
    assert "_matches_two_step_workflow_shape" in recognizer_names

    helper_literals, helper_names = _real_code_string_literals_and_names(
        inspect.getsource(JarvisOrchestrator._matches_two_step_workflow_shape)
    )
    assert "project_state_update" not in helper_literals
    assert "project_state_verify" not in helper_literals
    assert "CAPABILITY_CATALOG" in helper_names


def test_schedule_enable_recognizer_also_delegates_to_the_shared_helper() -> None:
    """The second real recognizer reuses the identical shared helper -
    proving the catalog-driven mechanism, not just its absence of
    literals, is genuinely shared rather than duplicated."""
    from core.orchestrator import JarvisOrchestrator

    _literals, names = _real_code_string_literals_and_names(
        inspect.getsource(JarvisOrchestrator._is_schedule_enable_workflow_result)
    )
    assert "_matches_two_step_workflow_shape" in names


def test_is_update_focus_workflow_result_still_recognises_the_real_shape() -> None:
    from core.orchestrator import JarvisOrchestrator

    plan = Plan(
        user_request="ask jarvis to: update my project focus to x",
        steps=(
            _fake_plan_step(1, "project_state_update"),
            _fake_plan_step(2, "project_state_verify"),
        ),
    )
    result = WorkflowResult(plan=plan, workflow_id="wf-real-shape")
    assert JarvisOrchestrator._is_update_focus_workflow_result(result) is True


def test_is_update_focus_workflow_result_rejects_an_unrelated_shape() -> None:
    from core.orchestrator import JarvisOrchestrator

    plan = Plan(
        user_request="some other two-step workflow",
        steps=(
            _fake_plan_step(1, "test_write_tool"),
            _fake_plan_step(2, "test_verify_tool"),
        ),
    )
    result = WorkflowResult(plan=plan, workflow_id="wf-unrelated-shape")
    assert JarvisOrchestrator._is_update_focus_workflow_result(result) is False


def test_is_update_focus_workflow_result_rejects_wrong_step_count() -> None:
    from core.orchestrator import JarvisOrchestrator

    plan = Plan(
        user_request="a single-step plan",
        steps=(_fake_plan_step(1, "project_state_update"),),
    )
    result = WorkflowResult(plan=plan, workflow_id="wf-one-step")
    assert JarvisOrchestrator._is_update_focus_workflow_result(result) is False


def _fake_plan_step(number: int, tool_name: str):
    from planner.plan_models import PlanStep

    return PlanStep(
        number=number,
        description="test step",
        action="test action",
        tier=SecurityTier.GREEN,
        reason="test reason",
        tool_name=tool_name,
        tool_input={},
    )
