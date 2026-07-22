"""
test_compound_isolation.py

Structural proof that Phase 97's compound grounding foundation
(intelligence/compound_structured_output.py,
intelligence/compound_grounding.py) has zero live wiring and zero
side effects (docs/phase_97_implementation_plan.md). Covers "Parser
isolation tests" (1-6) and "Structural no-side-effect tests" (58-68)
from the Phase 97 implementation task.

These tests use direct imports, module-source AST inspection, and
signature/behavior assertions - never brittle text matching where a
structural check is possible, per the task's own requirement.
"""

from __future__ import annotations

import ast
import inspect
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
    "intelligence/planning.py",
    "core/orchestrator.py",
    "security/security_manager.py",
    "tools/executor.py",
    "main.py",
)

_COMPOUND_MODULE_NAMES = frozenset(
    {"compound_structured_output", "compound_grounding"}
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

    def test_trusted_instruction_does_not_mention_compound_output(self) -> None:
        instruction = live_planning._TRUSTED_PLANNING_INSTRUCTION
        assert "execute_sequence" not in instruction
        assert "and then" not in instruction.casefold()


class TestNoLiveImportOfCompoundModules:
    """Items 4-6: no live runtime module imports either new compound
    module, proven by parsing each live module's own real source with
    the standard library `ast` module - not by asserting behavior that
    merely happens not to trigger a code path."""

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

    def test_select_tool_source_has_no_compound_reference(self) -> None:
        source = inspect.getsource(live_planning.select_tool)
        assert "compound" not in source.casefold()

    def test_orchestrator_module_source_has_no_compound_reference(self) -> None:
        source = inspect.getsource(live_orchestrator)
        assert "compound" not in source.casefold()

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

    def test_help_tool_and_user_guide_have_no_compound_entry(self) -> None:
        help_source = _module_source_path(
            "tools/builtin/help_tool.py"
        ).read_text(encoding="utf-8")
        guide_source = _module_source_path("docs/user_guide.md").read_text(
            encoding="utf-8"
        )
        assert "execute_sequence" not in help_source
        assert "and then" not in help_source.casefold()
        assert "execute_sequence" not in guide_source

    def test_no_main_wiring(self) -> None:
        source = _module_source_path("main.py").read_text(encoding="utf-8")
        referenced = _referenced_module_names(source)
        assert not (referenced & _COMPOUND_MODULE_NAMES)

    def test_no_package_initializer_export_required(self) -> None:
        init_source = _module_source_path("intelligence/__init__.py").read_text(
            encoding="utf-8"
        )
        assert "compound" not in init_source.casefold()
        # Importing the new modules directly (as this test file already
        # does) requires no change to intelligence/__init__.py at all.
        import intelligence.compound_grounding  # noqa: F401
        import intelligence.compound_structured_output  # noqa: F401
