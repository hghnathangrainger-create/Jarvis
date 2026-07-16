"""
test_memory_cli_end_to_end.py

End-to-end integration tests for the memory commands through the live CLI
(Phase 5, Batch 2; extended Phase 71, Batch 2 with the read-only
category-breakdown command).

These drive the real CLI with scripted input, wiring together the real Security
Manager, Planner, Tool Registry, Tool Executor, MemoryTool, and a real
in-memory SQLite-backed Memory Manager. They prove the full journeys:

    - "remember this: X" saves, and a following "show memories" lists it.
    - "remember this as project: Y" files Y under project, and
      "show memories in project" finds it while a personal listing does not.
    - "search memories for X" and "search memories in <cat> for X" work.
    - "show memory categories"/"list memory categories" report a real,
      honest per-category count across multiple saved memories, in
      KNOWN_CATEGORIES' own fixed order, never sorted by count.
    - Every memory command runs GREEN, with no approval prompt.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable in the current environment.

Run with:
    pytest tests/integration/test_memory_cli_end_to_end.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")


class _SpyLogger:
    def emit(self, **kwargs: object) -> str:
        return "1"


@pytest.fixture()
def cli_factory():
    """Return a factory that builds a CLI driven by a scripted input list."""
    from sqlalchemy import create_engine

    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from memory.episodic_memory import EpisodicMemoryStore
    from memory.memory_manager import MemoryManager
    from planner.planner import Planner
    from security.security_manager import SecurityManager
    from storage.database import create_session_factory, initialize_database
    from tools.builtin import MemoryTool
    from tools.executor import ToolExecutor
    from tools.registry import ToolRegistry
    from ui.cli import JarvisCLI

    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    memory = MemoryManager(EpisodicMemoryStore(factory))

    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(MemoryTool(memory))
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_SpyLogger()
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )

    def build(inputs: list[str]) -> str:
        outputs: list[str] = []
        scripted = iter(inputs)
        cli = JarvisCLI(
            orchestrator,
            input_fn=lambda _prompt: next(scripted),
            output_fn=outputs.append,
        )
        cli.run()
        return "\n".join(outputs)

    return build


# --- Save then list ----------------------------------------------------------


def test_remember_then_show(cli_factory) -> None:
    output = cli_factory(
        ["remember this: buy milk on Friday", "show memories", "exit"]
    )
    assert "buy milk on Friday" in output
    # Saved under the default category.
    assert "(general)" in output
    # GREEN throughout: no approval prompt appeared.
    assert "approval required" not in output.lower()


def test_remember_as_category_then_show_in_category(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this as project: the API deadline is Tuesday",
            "show memories in project",
            "exit",
        ]
    )
    assert "API deadline" in output
    assert "(project)" in output


def test_category_listing_excludes_other_categories(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this as project: project note here",
            "remember this as personal: personal note here",
            "show memories in personal",
            "exit",
        ]
    )
    # The personal listing shows the personal note but not the project one.
    lines_after = output.split("memories in 'personal'")[-1]
    assert "personal note here" in lines_after
    assert "project note here" not in lines_after


# --- Search ------------------------------------------------------------------


def test_search_memories(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this: Nathan likes Python",
            "remember this: the sky is blue",
            "search memories for python",
            "exit",
        ]
    )
    assert "Nathan likes Python" in output


def test_search_in_category(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this as project: shared keyword in project",
            "remember this as personal: shared keyword in personal",
            "search memories in personal for shared keyword",
            "exit",
        ]
    )
    tail = output.split("matching 'shared keyword'")[-1]
    assert "in personal" in tail


# --- result limit grammar (Phase 83, Batch 2) --------------------------------


def test_show_memories_respects_custom_limit(cli_factory) -> None:
    """The CLI's "limit <N>" grammar must actually reach MemoryTool
    through the real CommandRouter -> ToolExecutor path and change how
    many memories are shown - not just be parsed and dropped."""
    output = cli_factory(
        [
            "remember this: memory one",
            "remember this: memory two",
            "remember this: memory three",
            "show memories limit 2",
            "exit",
        ]
    )
    assert "[showing 2 of 3 memories; more memories exist]" in output


def test_search_memories_respects_custom_limit(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this: jarvis one",
            "remember this: jarvis two",
            "remember this: jarvis three",
            "search memories for jarvis limit 2",
            "exit",
        ]
    )
    assert "[showing 2 of 3 matches; more matches exist]" in output


# --- do not remember, and GREEN throughout -----------------------------------


def test_do_not_remember_through_cli(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this: do not remember my password",
            "show memories",
            "exit",
        ]
    )
    assert "did not save" in output.lower()
    assert "my password" not in output.split("did not save")[-1]


def test_all_memory_commands_are_green(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this: alpha",
            "remember this as note: beta",
            "show memories",
            "show memories in note",
            "search memories for alpha",
            "search memories in note for beta",
            "exit",
        ]
    )
    # Not one of the six commands should have required approval.
    assert "approval required" not in output.lower()
    assert "[NEEDS APPROVAL]" not in output


# --- Category breakdown (Phase 71, Batch 2) -----------------------------------


def test_show_memory_categories_reports_real_counts_across_categories(
    cli_factory,
) -> None:
    """Full, real, end-to-end path: a real CommandRouter, SecurityManager,
    ToolExecutor, MemoryTool, and an in-memory-SQLite-backed MemoryManager,
    driven through the real JarvisCLI - proving the command works with real
    saved memories across multiple categories, not just in isolation."""
    from memory.memory_models import KNOWN_CATEGORIES

    output = cli_factory(
        [
            "remember this as project: ship the release",
            "remember this as project: fix the bug",
            "remember this as personal: buy milk",
            "show memory categories",
            "exit",
        ]
    )
    assert "Memory categories:" in output
    assert "project: 2" in output
    assert "personal: 1" in output
    # Honest zeros for every known category that received nothing.
    for category in KNOWN_CATEGORIES:
        if category not in ("project", "personal"):
            assert f"{category}: 0" in output

    # Fixed KNOWN_CATEGORIES order, never sorted by count (project has the
    # highest count here, but must not be reordered to the front).
    breakdown_block = output.split("Memory categories:")[-1]
    rendered_order = [
        line.strip().split(":")[0]
        for line in breakdown_block.splitlines()
        if ":" in line and line.strip().split(":")[0] in KNOWN_CATEGORIES
    ]
    assert rendered_order == list(KNOWN_CATEGORIES)


def test_list_memory_categories_alias_also_works(cli_factory) -> None:
    output = cli_factory(
        [
            "remember this as preference: prefers dark mode",
            "list memory categories",
            "exit",
        ]
    )
    assert "Memory categories:" in output
    assert "preference: 1" in output


def test_memory_categories_command_is_green(cli_factory) -> None:
    output = cli_factory(["show memory categories", "exit"])
    assert "approval required" not in output.lower()
    assert "[NEEDS APPROVAL]" not in output


def test_memory_categories_uses_no_ai(cli_factory) -> None:
    """Structural sanity check: the category breakdown never involves AI -
    no advisory suggestion marker ever appears for this command."""
    output = cli_factory(
        ["remember this: a note", "show memory categories", "exit"]
    )
    tail = output.split("Memory categories:")[-1]
    assert "[AI suggestion" not in tail
    assert "advisory only" not in tail.lower()