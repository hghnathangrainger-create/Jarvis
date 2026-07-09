"""
test_ai_memory_read_only_invariant.py

Formalises, as a checkable test rather than repeated prose reasoning, the
one concrete architectural debt the Phase 10-13 retrieval-family
architecture checkpoint identified (Phase 14, Batch 3):

    "AI memory ingestion and deterministic memory selection code may
    directly call only explicitly known read-only MemoryManager methods.
    No mutation or deletion method may become reachable through these
    direct bypassing paths."

Both ai/memory_ingestion.py and ai/memory_selection.py call MemoryManager
directly, bypassing ToolExecutor/SecurityManager.classify_action() entirely
- a disclosed, accepted architectural bypass reviewed and reconfirmed
across Phases 9-14 (docs/phase_9_implementation_plan.md through
docs/phase_14_implementation_plan.md, each phase's own Security Review
section). That bypass has only ever been safe because every direct call
site happens to call one of a small, known set of read-only methods
(get/search/list_by_category/list_recent) - a rule that, until now, was
enforced only by careful, repeated, manual review, not by anything
mechanical.

This module parses the actual source of both files via Python's built-in
ast module (no new dependency) and proves, structurally, that every direct
method call on a MemoryManager-annotated function parameter in either
module is a member of the approved read-only allowlist.

What this proves:
    Every syntactically-direct `<param>.<method>(...)` call, where <param>
    is a function parameter whose type annotation is MemoryManager,
    anywhere in ai/memory_ingestion.py or ai/memory_selection.py
    (including this phase's own select_recent_memory_ids_by_count()), is
    one of get/search/list_by_category/list_recent.

What this does NOT prove:
    - The absence of dynamic dispatch (e.g. getattr(memory_manager,
      some_variable_name)(...)) - no such pattern exists in either module
      today, confirmed by direct source inspection below, but this test
      would not catch one if it were introduced.
    - The absence of monkey-patching a MemoryManager instance at runtime.
    - The absence of an indirect call routed through a differently-named
      local alias this walker does not recognise as the same parameter
      (for example, reassigning the parameter to a new local name before
      calling a method on it) - no such pattern exists in either module
      today.
    - Anything about a third file this test does not scan.

This is a narrow, additive test only. It does not change SecurityManager,
does not route any existing call through ToolExecutor, and does not
introduce a runtime allowlist or facade - it is closure documentation made
checkable, nothing more.

Run with:
    pytest tests/unit/test_ai_memory_read_only_invariant.py
"""

from __future__ import annotations

import ast
import inspect

import ai.memory_ingestion as memory_ingestion_module
import ai.memory_selection as memory_selection_module

#: The complete, current, approved set of read-only MemoryManager methods
#: any direct AI-ingestion/selection call site may invoke
#: (docs/phase_14_implementation_plan.md, Section 9). Confirmed by direct
#: repository inspection before writing this test: these are the only
#: methods called directly on a memory_manager parameter anywhere in
#: ai/memory_ingestion.py or ai/memory_selection.py today.
_ALLOWED_READ_ONLY_METHODS = frozenset(
    {"get", "search", "list_by_category", "list_recent"}
)


def _is_memory_manager_annotation(node: ast.expr) -> bool:
    """Return whether an annotation node names the MemoryManager type.

    Recognises both a plain `MemoryManager` name (how both target modules
    import and annotate it) and a `module.MemoryManager` attribute form,
    so the check is not brittle against either import style.
    """
    if isinstance(node, ast.Name):
        return node.id == "MemoryManager"
    if isinstance(node, ast.Attribute):
        return node.attr == "MemoryManager"
    return False


def _memory_manager_parameter_names(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Return the names of a function's parameters annotated as MemoryManager.

    Checks positional, positional-or-keyword, and keyword-only parameters -
    every parameter-passing shape actually used across the two target
    modules (e.g. select_memory_ids_by_category's keyword-only `limit`
    alongside its positional `memory_manager`).
    """
    names: set[str] = set()
    candidates = list(func.args.args) + list(func.args.kwonlyargs)
    if func.args.vararg is not None:
        candidates.append(func.args.vararg)
    for arg in candidates:
        if arg.annotation is not None and _is_memory_manager_annotation(
            arg.annotation
        ):
            names.add(arg.arg)
    return names


def _direct_memory_manager_calls(source: str) -> set[str]:
    """Parse source and return every method name directly invoked on a
    MemoryManager-annotated parameter, anywhere in the source.

    Structural, not string-based: walks the real parsed AST, considering
    only genuine `ast.Call` nodes whose function is an `ast.Attribute`
    accessed on an `ast.Name` matching a recognised MemoryManager
    parameter within the enclosing function's own scope. Prose mentioning
    a method name in a docstring or comment is never picked up, since
    docstrings parse as `ast.Expr(value=ast.Constant)` nodes, not calls.
    """
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        mm_params = _memory_manager_parameter_names(node)
        if not mm_params:
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id in mm_params
            ):
                called.add(inner.func.attr)
    return called


# --- The invariant, proven against the actual current source ---------------


def test_memory_ingestion_direct_calls_are_all_read_only() -> None:
    source = inspect.getsource(memory_ingestion_module)

    called = _direct_memory_manager_calls(source)

    assert called, (
        "expected at least one direct MemoryManager call in "
        "ai/memory_ingestion.py - if this now fails empty, the module's "
        "own architecture changed and this test's own assumptions need "
        "re-review, not silent adjustment"
    )
    assert called <= _ALLOWED_READ_ONLY_METHODS
    # Proves the current observed set is exactly the expected read-only
    # set - not merely a subset - so a future removal is also visible.
    assert called == {"get"}


def test_memory_selection_direct_calls_are_all_read_only() -> None:
    source = inspect.getsource(memory_selection_module)

    called = _direct_memory_manager_calls(source)

    assert called, (
        "expected at least one direct MemoryManager call in "
        "ai/memory_selection.py"
    )
    assert called <= _ALLOWED_READ_ONLY_METHODS
    # Covers all four selectors, including Phase 14's own
    # select_recent_memory_ids_by_count() - which itself makes no direct
    # MemoryManager call at all (it delegates to
    # select_recent_memory_ids()), so its presence changes nothing here;
    # this assertion would catch it immediately if that ever changed.
    assert called == {"search", "list_by_category", "list_recent"}


def test_select_recent_memory_ids_by_count_makes_no_direct_memory_manager_call() -> (
    None
):
    """Narrower, function-scoped proof for Phase 14's own new selector
    specifically: confirms it contributes zero direct MemoryManager calls
    of its own, because it delegates entirely to the existing, unmodified
    select_recent_memory_ids()."""
    source = inspect.getsource(
        memory_selection_module.select_recent_memory_ids_by_count
    )
    tree = ast.parse(source)
    func_def = tree.body[0]
    assert isinstance(func_def, ast.FunctionDef)

    called = _direct_memory_manager_calls(source)

    assert called == set()


# --- Proving the mechanism itself, not merely its current result ----------


def test_invariant_mechanism_detects_a_mutation_method_in_representative_source() -> (
    None
):
    """Proves the checking mechanism itself would reject a violation: a
    small, representative snippet with a MemoryManager-typed parameter
    calling a mutation method (forget) is correctly identified as outside
    the approved allowlist. This is not a test of real repository code -
    it is a test of the test."""
    representative_source = (
        "def bad_function(memory_manager: MemoryManager, memory_id: int) -> None:\n"
        "    memory_manager.forget(memory_id)\n"
    )

    called = _direct_memory_manager_calls(representative_source)

    assert called == {"forget"}
    assert not called <= _ALLOWED_READ_ONLY_METHODS


def test_invariant_mechanism_detects_an_update_method_in_representative_source() -> (
    None
):
    representative_source = (
        "def bad_function(memory_manager: MemoryManager, memory_id: int, text: str) -> None:\n"
        "    memory_manager.update_content(memory_id, text)\n"
    )

    called = _direct_memory_manager_calls(representative_source)

    assert called == {"update_content"}
    assert not called <= _ALLOWED_READ_ONLY_METHODS


def test_invariant_mechanism_ignores_docstring_prose_mentioning_a_mutation_method() -> (
    None
):
    """Proves this is a structural AST check, not a string search: a
    docstring mentioning a mutation method by name in prose must not be
    mistaken for an actual call."""
    representative_source = (
        'def documented_function(memory_manager: MemoryManager) -> None:\n'
        '    """This function never calls memory_manager.forget() or '
        'memory_manager.update_content() - see the module docstring."""\n'
        "    memory_manager.get(1)\n"
    )

    called = _direct_memory_manager_calls(representative_source)

    assert called == {"get"}


def test_invariant_mechanism_ignores_calls_on_unrelated_parameters() -> None:
    """A same-named method called on a parameter that is NOT
    MemoryManager-annotated must not be picked up - the check is scoped to
    recognised MemoryManager parameters specifically, not any parameter
    with a matching method name."""
    representative_source = (
        "def unrelated_function(some_other_object: object) -> None:\n"
        "    some_other_object.forget()\n"
    )

    called = _direct_memory_manager_calls(representative_source)

    assert called == set()


# --- Confirming the test's own disclosed blind spots do not currently apply


def test_no_dynamic_dispatch_pattern_exists_in_either_module() -> None:
    """Confirms, by direct source inspection, that neither target module
    uses getattr()-based dynamic dispatch to call a MemoryManager method -
    the one class of bypass this AST-based test cannot itself detect. Its
    absence is verified directly here instead, so the disclosed blind spot
    in this test's own docstring is not a silent, unverified assumption."""
    for module in (memory_ingestion_module, memory_selection_module):
        source = inspect.getsource(module)
        assert "getattr(memory_manager" not in source
        assert "getattr(self._memory" not in source
