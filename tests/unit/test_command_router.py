"""
test_command_router.py

Unit tests for CommandRouter (core/command_router.py), Phase 7 Batch 1.

CommandRouter is a mechanical extraction of logic that used to live directly
on JarvisOrchestrator (_match_tool and _build_tool_input). Before this
extraction, the logic was only reachable indirectly, through
JarvisOrchestrator.handle_request(). These tests exercise match() and
build_input() directly for the first time, and confirm the router never
routes to a tool that is not actually registered.

Run with:
    pytest tests/unit/test_command_router.py
"""

from __future__ import annotations

import pytest

from core.command_router import CommandRouter
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.registry import ToolRegistry


class _StubTool(BaseTool):
    """A minimal registerable tool stand-in; CommandRouter never runs it."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"stub tool {self._name}"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("CommandRouter must never execute a tool.")


_ALL_TOOL_NAMES = (
    "echo",
    "info",
    "memory",
    "memory_update",
    "memory_forget",
    "file_list",
    "file_read",
    "file_create",
    "file_append",
    "approval_history",
)


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    for name in _ALL_TOOL_NAMES:
        reg.register_tool(_StubTool(name))
    return reg


@pytest.fixture()
def router(registry: ToolRegistry) -> CommandRouter:
    return CommandRouter(registry)


# --- match(): keyword-based commands -----------------------------------------


def test_match_echo(router: CommandRouter) -> None:
    assert router.match("echo hello") == "echo"


def test_match_info(router: CommandRouter) -> None:
    assert router.match("system info") == "info"


def test_match_memory_keywords(router: CommandRouter) -> None:
    assert router.match("show my memories") == "memory"
    assert router.match("remember this: buy milk") == "memory"


def test_match_unrecognised_text_returns_none(router: CommandRouter) -> None:
    assert router.match("do a backflip") is None


# --- match(): file commands ---------------------------------------------------


def test_match_file_list(router: CommandRouter) -> None:
    assert router.match("list files in .") == "file_list"
    assert router.match("show files") == "file_list"


def test_match_file_read(router: CommandRouter) -> None:
    assert router.match("read file README.md") == "file_read"


def test_match_file_create(router: CommandRouter) -> None:
    assert router.match("create file a.txt with x") == "file_create"


def test_match_file_append(router: CommandRouter) -> None:
    assert router.match("append to file a.txt hello") == "file_append"


# --- match(): workflow aliases -------------------------------------------------


def test_match_workflow_alias_show_project_files(router: CommandRouter) -> None:
    assert router.match("show project files") == "file_list"


def test_match_workflow_alias_read_readme(router: CommandRouter) -> None:
    assert router.match("read readme") == "file_read"


def test_match_workflow_alias_is_case_insensitive(router: CommandRouter) -> None:
    assert router.match("  SHOW PROJECT FILES  ") == "file_list"


# --- match(): approval history ------------------------------------------------


def test_match_approval_history_exact_phrases(router: CommandRouter) -> None:
    assert router.match("show approval history") == "approval_history"
    assert router.match("show recent approvals") == "approval_history"
    assert router.match("show approved actions") == "approval_history"
    assert router.match("show declined actions") == "approval_history"


def test_match_approval_history_detail_lookup(router: CommandRouter) -> None:
    assert router.match("show approval abc-123") == "approval_history"
    assert router.match("view approval abc-123") == "approval_history"


def test_match_approval_history_not_confused_with_history_lookup(
    router: CommandRouter,
) -> None:
    # "show approval history" must match the exact phrase, not be parsed as
    # "show approval <id='history'>".
    assert router.match("show approval history") == "approval_history"


# --- match(): memory change commands ------------------------------------------


def test_match_forget_memory(router: CommandRouter) -> None:
    assert router.match("forget memory 3") == "memory_forget"


def test_match_forget_all_routes_to_forget_tool(router: CommandRouter) -> None:
    # Routed to memory_forget (not the read-only memory tool) so the Security
    # Manager classifies "forget all memories" RED via the forget tool's own
    # action string, and the Tool Executor blocks it.
    assert router.match("forget all memories") == "memory_forget"


def test_match_update_memory(router: CommandRouter) -> None:
    assert router.match("update memory 2: new content") == "memory_update"


def test_match_move_memory(router: CommandRouter) -> None:
    assert router.match("move memory 2 to personal") == "memory_update"


# --- match(): only registered tools are ever returned -------------------------


def test_match_returns_none_when_tool_not_registered() -> None:
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)
    assert router.match("echo hello") is None
    assert router.match("show project files") is None
    assert router.match("show approval history") is None


# --- build_input(): each tool shape --------------------------------------------


def test_build_input_echo(router: CommandRouter) -> None:
    assert router.build_input("echo", "echo hello there") == {
        "text": "echo hello there"
    }


def test_build_input_file_list_direct_path(router: CommandRouter) -> None:
    assert router.build_input("file_list", "list files in docs") == {"path": "docs"}


def test_build_input_file_list_defaults_to_current_dir(
    router: CommandRouter,
) -> None:
    assert router.build_input("file_list", "list files") == {"path": "."}


def test_build_input_file_list_alias(router: CommandRouter) -> None:
    assert router.build_input("file_list", "show project files") == {"path": "."}


def test_build_input_file_read_direct_path(router: CommandRouter) -> None:
    assert router.build_input("file_read", "read file README.md") == {
        "path": "README.md"
    }


def test_build_input_file_read_alias(router: CommandRouter) -> None:
    assert router.build_input("file_read", "read readme") == {"path": "README.md"}


def test_build_input_file_create(router: CommandRouter) -> None:
    assert router.build_input("file_create", "create file a.txt with hello") == {
        "path": "a.txt",
        "content": "hello",
    }


def test_build_input_file_create_without_content(router: CommandRouter) -> None:
    assert router.build_input("file_create", "create file a.txt") == {
        "path": "a.txt",
        "content": "",
    }


def test_build_input_file_append(router: CommandRouter) -> None:
    assert router.build_input(
        "file_append", "append hello to file a.txt"
    ) == {"path": "a.txt", "content": "hello"}


def test_build_input_memory_save(router: CommandRouter) -> None:
    assert router.build_input("memory", "remember this: buy milk") == {
        "operation": "save",
        "content": "buy milk",
    }


def test_build_input_memory_save_with_category(router: CommandRouter) -> None:
    assert router.build_input(
        "memory", "remember this as project: ship phase 7"
    ) == {
        "operation": "save",
        "content": "ship phase 7",
        "category": "project",
    }


def test_build_input_memory_list(router: CommandRouter) -> None:
    assert router.build_input("memory", "show memories") == {"operation": "list"}


def test_build_input_memory_get_by_id(router: CommandRouter) -> None:
    assert router.build_input("memory", "show memory 5") == {
        "operation": "get",
        "memory_id": 5,
    }


def test_build_input_memory_search(router: CommandRouter) -> None:
    assert router.build_input("memory", "search memories for milk") == {
        "operation": "search",
        "query": "milk",
    }


def test_build_input_memory_update(router: CommandRouter) -> None:
    assert router.build_input("memory_update", "update memory 2: new text") == {
        "operation": "update",
        "memory_id": 2,
        "content": "new text",
    }


def test_build_input_memory_move(router: CommandRouter) -> None:
    assert router.build_input("memory_update", "move memory 2 to personal") == {
        "operation": "move",
        "memory_id": 2,
        "category": "personal",
    }


def test_build_input_memory_forget_specific(router: CommandRouter) -> None:
    assert router.build_input("memory_forget", "forget memory 4") == {
        "memory_id": 4
    }


def test_build_input_memory_forget_all(router: CommandRouter) -> None:
    assert router.build_input("memory_forget", "forget all memories") == {
        "all": True
    }


def test_build_input_approval_history_exact(router: CommandRouter) -> None:
    assert router.build_input("approval_history", "show approval history") == {
        "operation": "history"
    }
    assert router.build_input("approval_history", "show recent approvals") == {
        "operation": "recent"
    }


def test_build_input_approval_history_get_by_id(router: CommandRouter) -> None:
    assert router.build_input("approval_history", "show approval abc-123") == {
        "operation": "get",
        "request_id": "abc-123",
    }


def test_build_input_unknown_tool_returns_empty_dict(router: CommandRouter) -> None:
    assert router.build_input("info", "system info") == {}
