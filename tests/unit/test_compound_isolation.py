"""
test_compound_isolation.py

Structural proof that Phase 97's compound grounding foundation
(intelligence/compound_structured_output.py,
intelligence/compound_grounding.py) itself has zero side effects
(docs/phase_97_implementation_plan.md) - covers "Structural no-side-
effect tests" (58-68) from the Phase 97 implementation task, and these
never changed: neither module's own source has ever been edited since
Phase 97, so every one of these assertions still holds unchanged.

Phase 98, Batch 3 (docs/phase_98_live_compound_reentry_plan.md)
formally, atomically activated live wiring for both modules, through
exactly one entry point: intelligence/planning.py's select_tool(),
which core/orchestrator.py and main.py depend on only indirectly (via
core/compound_workflow.py's own separate, dormant-since-Batch-2
functions - never by importing compound_structured_output/
compound_grounding directly themselves). "Parser isolation" (originally
items 1-6) is therefore revised, not removed: it now proves the wiring
is exactly this narrow - one call site, one discriminator peek, no
fallback - rather than proving no wiring exists at all.

These tests use direct imports, module-source AST inspection, and
signature/behavior assertions - never brittle text matching where a
structural check is possible, per the task's own requirement.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from intelligence.capability_catalog import CAPABILITY_CATALOG
from intelligence.compound_structured_output import CompoundToolSelectionParseError
from intelligence.structured_output import (
    ToolSelectionDecision,
    ToolSelectionParseError,
    parse_tool_selection,
)
from intelligence import planning as live_planning
from core import orchestrator as live_orchestrator

_REPO_ROOT = Path(__file__).resolve().parents[2]

_LIVE_RUNTIME_MODULES = (
    "intelligence/structured_output.py",
    "intelligence/grounding.py",
    "core/orchestrator.py",
    "security/security_manager.py",
    "tools/executor.py",
    "main.py",
)

_COMPOUND_MODULE_NAMES = frozenset(
    {"compound_structured_output", "compound_grounding"}
)

#: Phase 98, Batch 3: intelligence/planning.py's own methods that are
#: allowed to reference a compound identifier - the live discriminator
#: peek plus the one dedicated compound helper it delegates to.
#: Everything else in the module must stay exactly as narrow as it was
#: before Batch 3.
_PLANNING_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS = frozenset(
    {
        "select_tool",
        "_select_compound_tool_sequence",
        "_build_phase_update_verify_show_workflow_plan",
        # Phase 99, Batch 1: the second, dormant compound template's
        # own plan builder - its own docstring names it a "compound
        # template" for documentation purposes, exactly mirroring its
        # ProjectState sibling above; never called live (see
        # test_phase99_batch1_isolation.py's own confinement proof).
        "_build_schedule_enable_verify_show_workflow_plan",
    }
)

#: Phase 98, Batch 3: core/orchestrator.py's own methods that are
#: allowed to reference a compound identifier - proven narrow by
#: test_orchestrator_compound_wiring_is_confined_to_named_methods below.
_ORCHESTRATOR_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS = frozenset(
    {
        "__init__",
        "validate_pending_approval_for_transition",
        "_claim_and_resume_workflow",
        "_compound_step_observer_for",
        "_start_compound_update_phase_and_show_workflow",
        "_handle_ask_jarvis_to_request",
        "_terminalize_declined_compound_progress",
    }
)

#: Phase 98, Batch 3: main.py's own functions/classes that are allowed
#: to reference a compound identifier - proven narrow by
#: test_main_compound_wiring_is_confined_to_named_functions below.
_MAIN_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS = frozenset(
    {
        "build_orchestrator",
        "reconcile_claimed_handoffs",
        "__init__",
        "invalidate_pending",
    }
)


def _module_source_path(relative_path: str) -> Path:
    return _REPO_ROOT / relative_path


def _referenced_module_names(source: str) -> set[str]:
    """Return every module name referenced by any import statement in
    `source`, at any depth (import x, import x.y, from x import y,
    from x.y import z)."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
    return names


def _referenced_identifiers(source: str) -> set[str]:
    """Return every genuine code identifier `source` references - every
    ast.Name.id, every ast.Attribute.attr, and every imported module/
    symbol name - deliberately excluding string literals and
    docstrings (which are ast.Constant nodes, never visited here).

    This is the robust, structural technique the task requires instead
    of brittle raw-text substring search: a module's own docstring may
    legitimately *name* a live class (e.g. "does not call
    ApprovalManager") without that name ever being a real code
    reference - only an actual ast.Name/ast.Attribute/import counts.
    """
    tree = ast.parse(source)
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                identifiers.update(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom) and node.module:
            identifiers.update(node.module.split("."))
            for alias in node.names:
                identifiers.add(alias.name)
    return identifiers


def _has_method_call(source: str, method_name: str) -> bool:
    """Return whether `source` contains a real call of the form
    `<something>.<method_name>(...)` - an actual ast.Call/ast.Attribute
    node, never a docstring mention."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name
        ):
            return True
    return False


_COMPOUND_PRODUCTION_FILES = (
    "intelligence/compound_structured_output.py",
    "intelligence/compound_grounding.py",
)


class TestExistingLiveParserIsolation:
    """Items 1-3: the existing, live single-capability parser and
    trusted instruction are unaffected by the new compound shape."""

    def test_existing_parser_rejects_execute_sequence(self) -> None:
        raw = '{"decision": "execute_sequence", "capability_id": null, "arguments": {}}'
        with pytest.raises(ToolSelectionParseError, match="unknown decision value"):
            parse_tool_selection(raw, CAPABILITY_CATALOG)

    def test_existing_accepted_decision_literals_unchanged(self) -> None:
        assert {member.value for member in ToolSelectionDecision} == {
            "execute",
            "unsupported",
        }

    def test_compound_parse_error_is_not_the_live_parse_error(self) -> None:
        assert not issubclass(CompoundToolSelectionParseError, ToolSelectionParseError)
        assert not issubclass(ToolSelectionParseError, CompoundToolSelectionParseError)

    def test_trusted_instruction_describes_exactly_one_compound_shape(self) -> None:
        """Phase 98, Batch 3: the trusted instruction now teaches
        exactly one compound decision, for exactly one fixed two-step
        sequence, never a general multi-step facility. Proven
        structurally: every "steps" array the instruction's own JSON
        examples contain names exactly these two capability ids, in
        exactly this order - never any other pair, never reversed."""
        instruction = live_planning._TRUSTED_PLANNING_INSTRUCTION
        assert "execute_sequence" in instruction
        assert '"and then"' in instruction
        assert "Exactly one compound decision exists" in instruction
        assert "never invent a third step" in instruction
        assert "never reverse this order" in instruction
        assert 'never use "execute_sequence" for any other pair' in (
            instruction.casefold()
        )

        steps_arrays = re.findall(r'"steps":\s*\[(.*?)\]\}', instruction, re.DOTALL)
        assert steps_arrays, "expected at least one execute_sequence steps array"
        for steps_blob in steps_arrays:
            assert '"project_state_update_phase"' in steps_blob
            assert '"project_state_show"' in steps_blob
            assert steps_blob.index("project_state_update_phase") < steps_blob.index(
                "project_state_show"
            ), "the fixed compound shape must always update phase before showing"


def _functions_referencing(source: str, needle: str) -> set[str]:
    """Return the name of every FunctionDef/AsyncFunctionDef in `source`
    whose own source segment contains `needle` (case-insensitive) -
    used to prove a reference is confined to a known, expected set of
    functions/methods rather than merely asserting it exists at all."""
    tree = ast.parse(source)
    hits: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        segment = ast.get_source_segment(source, node) or ""
        if needle in segment.casefold():
            hits.add(node.name)
    return hits


class TestNoLiveImportOfCompoundModules:
    """Items 4-6, revised for Phase 98, Batch 3: every live runtime
    module still never imports either compound module, EXCEPT
    intelligence/planning.py - the one module Batch 3 atomically wired
    as the live entry point. Proven by parsing each live module's own
    real source with the standard library `ast` module - not by
    asserting behavior that merely happens not to trigger a code path.

    core/orchestrator.py and main.py deliberately stay off this "must
    not import" list's exclusion: Batch 3 wires them only indirectly,
    through core/compound_workflow.py's own separate functions/types -
    neither ever imports compound_structured_output or
    compound_grounding by name - so the blanket check below still
    holds true for both, unchanged."""

    @pytest.mark.parametrize("relative_path", _LIVE_RUNTIME_MODULES)
    def test_live_module_does_not_import_compound_modules(
        self, relative_path: str
    ) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        referenced = _referenced_module_names(source)
        assert not (referenced & _COMPOUND_MODULE_NAMES), (
            f"{relative_path} must not import either compound module; "
            f"found reference(s): {referenced & _COMPOUND_MODULE_NAMES}"
        )

    def test_planning_module_imports_exactly_the_two_compound_modules(self) -> None:
        """Phase 98, Batch 3: intelligence/planning.py is the sole live
        wiring point - it imports both compound modules directly."""
        source = _module_source_path("intelligence/planning.py").read_text(
            encoding="utf-8"
        )
        referenced = _referenced_module_names(source)
        assert _COMPOUND_MODULE_NAMES <= referenced

    def test_select_tool_source_compound_wiring_is_exactly_the_discriminator(
        self,
    ) -> None:
        """Phase 98, Batch 3: select_tool() itself only ever peeks at
        the discriminator and delegates to _select_compound_tool_
        sequence() - it never inlines compound parsing, grounding, or
        plan construction itself. Proven via ast.Call inspection of
        select_tool's own body, not by counting substring occurrences
        (which would also match this function's own explanatory
        comments)."""
        source = inspect.getsource(live_planning.select_tool)
        tree = ast.parse(source)
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "peek_compound_decision" in called_names
        assert "_select_compound_tool_sequence" in called_names
        # Parsing/grounding/building stay confined to
        # _select_compound_tool_sequence's own body, never duplicated
        # or inlined directly inside select_tool.
        assert "parse_compound_tool_selection" not in called_names
        assert "ground_compound_decision" not in called_names
        assert "_build_phase_update_verify_show_workflow_plan" not in called_names

    def test_planning_module_compound_wiring_is_confined_to_named_functions(
        self,
    ) -> None:
        """Phase 98, Batch 3: no function in intelligence/planning.py
        other than select_tool() and its own dedicated
        _select_compound_tool_sequence() helper references a compound
        identifier - proving the atomic activation added exactly one
        narrow wiring point, never a broader sprawl through the
        module's other, unrelated functions (_preflight_capability,
        _build_write_and_verify_workflow_plan, etc.)."""
        source = _module_source_path("intelligence/planning.py").read_text(
            encoding="utf-8"
        )
        hits = _functions_referencing(source, "compound")
        assert hits <= _PLANNING_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS, (
            f"unexpected compound reference inside: "
            f"{hits - _PLANNING_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS}"
        )

    def test_orchestrator_compound_wiring_is_confined_to_named_methods(
        self,
    ) -> None:
        """Phase 98, Batch 3: core/orchestrator.py's compound wiring
        (imports of core.compound_workflow /
        workflow.compound_progress_observer /
        workflow.compound_workflow_progress_store symbols) is confined
        to exactly its intended methods - never a broader, uncontrolled
        sprawl through the rest of the class. Proven by walking the
        module's own AST, not by a blanket substring search."""
        source = inspect.getsource(live_orchestrator)
        referenced_modules = _referenced_module_names(source)
        assert not (referenced_modules & _COMPOUND_MODULE_NAMES)

        hits = _functions_referencing(source, "compound")
        assert hits <= _ORCHESTRATOR_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS, (
            f"unexpected compound reference inside: "
            f"{hits - _ORCHESTRATOR_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS}"
        )

    def test_capability_catalog_module_is_unmodified_by_compound_concerns(
        self,
    ) -> None:
        import intelligence.capability_catalog as live_catalog

        source = inspect.getsource(live_catalog)
        assert "compound" not in source.casefold()


class TestNoSideEffects:
    """Items 58-68: the new modules never reference, import, or call
    any security/approval/workflow/persistence/execution/verification
    machinery, and never construct a live response type.

    Uses AST-based identifier/call detection (see
    _referenced_identifiers/_has_method_call above), never raw
    substring search - a module's own docstring legitimately *names*
    several of these classes when explaining what it does NOT do
    (e.g. "Does NOT: ... call SecurityManager, ApprovalManager,
    ToolExecutor, or verification code"), so a naive text search over
    the whole file would produce false positives on its own
    documentation. Only a genuine ast.Name/ast.Attribute/import
    reference counts as a real dependency."""

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_security_manager_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        assert "SecurityManager" not in identifiers
        assert "classify_action" not in identifiers
        assert "security_manager" not in identifiers

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_approval_manager_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        assert "ApprovalManager" not in identifiers
        assert "approval" not in identifiers
        assert "create_request" not in identifiers

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_workflow_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        assert "WorkflowEngine" not in identifiers
        assert "workflow" not in identifiers
        assert "Plan" not in identifiers
        assert "PlanStep" not in identifiers

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_persistence_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        for forbidden in (
            "PausedWorkflowStore",
            "PendingApprovalStore",
            "ProjectStateStore",
            "sqlite3",
            "save",
            "persist",
        ):
            assert forbidden not in identifiers

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_tool_executor_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        assert "ToolExecutor" not in identifiers
        assert "execute" not in identifiers
        assert not _has_method_call(source, "run")

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_verification_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        assert "VerificationResult" not in identifiers
        assert "verify_project_state_field" not in identifiers
        assert "verify_schedule_enabled_state" not in identifiers

    @pytest.mark.parametrize("relative_path", _COMPOUND_PRODUCTION_FILES)
    def test_no_jarvis_response_reference(self, relative_path: str) -> None:
        source = _module_source_path(relative_path).read_text(encoding="utf-8")
        identifiers = _referenced_identifiers(source)
        assert "JarvisResponse" not in identifiers

    def test_no_help_or_user_guide_reference(self) -> None:
        for relative_path in _COMPOUND_PRODUCTION_FILES:
            source = _module_source_path(relative_path).read_text(encoding="utf-8")
            identifiers = _referenced_identifiers(source)
            assert "help_tool" not in identifiers
            assert "HelpTool" not in identifiers

    def test_help_tool_and_user_guide_expose_exactly_one_narrow_compound_example(
        self,
    ) -> None:
        """Phase 98, Batch 3 requires exposing exactly the one fixed
        two-step exception (update phase, then show project state) to
        users - but never the internal "execute_sequence" decision
        literal, never the internal word "compound" itself, and never
        implying a general multi-step mechanism exists. Proven
        precisely: "and then" appears (the one honest natural-language
        connector), but only ever immediately preceded by "phase to
        <value>"-shaped text and followed by "show" - never any other
        pairing - and the internal jargon never leaks into either
        user-facing surface."""
        help_source = _module_source_path(
            "tools/builtin/help_tool.py"
        ).read_text(encoding="utf-8")
        guide_source = _module_source_path("docs/user_guide.md").read_text(
            encoding="utf-8"
        )
        assert "execute_sequence" not in help_source
        assert "execute_sequence" not in guide_source
        assert "compound" not in help_source.casefold()
        assert "compound_workflow" not in guide_source.casefold()

        assert "and then" in help_source.casefold()
        assert "and then" in guide_source.casefold()
        assert re.search(
            r"phase to [^\n\"]*and then show", help_source, re.IGNORECASE
        ), "help_tool.py's compound example must be exactly phase-update-then-show"
        assert re.search(
            r"phase to [^\n]*and then show", guide_source, re.IGNORECASE
        ), "user_guide.md's compound example must be exactly phase-update-then-show"

    def test_main_compound_wiring_is_confined_to_named_functions(self) -> None:
        """Phase 98, Batch 3: main.py legitimately wires compound-first
        startup recovery (build_orchestrator, reconcile_claimed_
        handoffs, _DurableCompoundApprovalInvalidator) - but, like
        core/orchestrator.py, never imports compound_structured_output
        or compound_grounding directly, and never references a
        compound identifier outside these specific, expected
        functions/methods."""
        source = _module_source_path("main.py").read_text(encoding="utf-8")
        referenced = _referenced_module_names(source)
        assert not (referenced & _COMPOUND_MODULE_NAMES)

        hits = _functions_referencing(source, "compound")
        assert hits <= _MAIN_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS, (
            f"unexpected compound reference inside: "
            f"{hits - _MAIN_ALLOWED_COMPOUND_REFERENCING_FUNCTIONS}"
        )

    def test_no_package_initializer_export_required(self) -> None:
        init_source = _module_source_path("intelligence/__init__.py").read_text(
            encoding="utf-8"
        )
        assert "compound" not in init_source.casefold()
        # Importing the new modules directly (as this test file already
        # does) requires no change to intelligence/__init__.py at all.
        import intelligence.compound_grounding  # noqa: F401
        import intelligence.compound_structured_output  # noqa: F401
