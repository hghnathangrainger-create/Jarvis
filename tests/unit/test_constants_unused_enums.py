"""
test_constants_unused_enums.py

Structural tests locking in Phase 50's corrected docstring claims for
four enums in config/constants.py (IntentType, ActionType, OnFailure,
MemoryType): each is defined but not currently consumed by the specific
production module its old, false docstring claimed to be used by.

These are AST-based import-absence proofs, mirroring the established
pattern already used throughout this project (e.g.
test_settings_module_actually_uses_log_level_enum in
tests/unit/test_settings.py, which proves the opposite - genuine use -
for LogLevel after Phase 46 wired it in). Here, the claim being proven
is non-use, so a future accidental import would correctly make these
tests fail, signalling the docstring needs revisiting rather than
silently drifting back out of sync with reality.

Run with:
    pytest tests/unit/test_constants_unused_enums.py
"""

from __future__ import annotations

import ast
import inspect


def _imported_names(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
    return imported_names


def test_intent_type_not_used_by_command_router() -> None:
    import core.command_router as module

    assert "IntentType" not in _imported_names(module)


def test_action_type_not_used_by_planner_or_workflow_engine() -> None:
    import planner.planner as planner_module
    import workflow.engine as workflow_module

    assert "ActionType" not in _imported_names(planner_module)
    assert "ActionType" not in _imported_names(workflow_module)


def test_on_failure_not_used_by_planner_or_workflow_engine() -> None:
    import planner.planner as planner_module
    import workflow.engine as workflow_module

    assert "OnFailure" not in _imported_names(planner_module)
    assert "OnFailure" not in _imported_names(workflow_module)


def test_memory_type_not_used_by_memory_manager_or_episodic_memory() -> None:
    import memory.episodic_memory as episodic_module
    import memory.memory_manager as manager_module

    assert "MemoryType" not in _imported_names(manager_module)
    assert "MemoryType" not in _imported_names(episodic_module)
