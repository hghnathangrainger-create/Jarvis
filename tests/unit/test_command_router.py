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


# --- match_file_summary(): explicit file-summary command (Phase 8, Batch 2) --


def test_match_file_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_file_summary("summarise file report.txt") == "report.txt"


def test_match_file_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_file_summary("summarize file report.txt") == "report.txt"


def test_match_file_summary_preserves_paths_with_spaces(
    router: CommandRouter,
) -> None:
    assert (
        router.match_file_summary("summarise file my notes/meeting notes.txt")
        == "my notes/meeting notes.txt"
    )


def test_match_file_summary_strips_quotes_and_filler_word(
    router: CommandRouter,
) -> None:
    assert (
        router.match_file_summary('summarise file the "report.txt"') == "report.txt"
    )


def test_match_file_summary_with_no_path_returns_empty_string(
    router: CommandRouter,
) -> None:
    """Recognised as a file-summary command, but with no path - the caller
    (JarvisOrchestrator) is responsible for handling the empty path as a
    normal acquisition failure, exactly like an empty file_read path."""
    assert router.match_file_summary("summarise file") == ""


def test_match_file_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_file_summary("summarise the plan for me") is None
    assert router.match_file_summary("read file report.txt") is None
    assert router.match_file_summary("do a backflip") is None


def test_match_file_summary_returns_none_when_file_read_not_registered() -> None:
    registry = ToolRegistry()
    router = CommandRouter(registry)
    assert router.match_file_summary("summarise file report.txt") is None


def test_match_file_summary_does_not_change_normal_match_behaviour(
    router: CommandRouter,
) -> None:
    """Adding match_file_summary must not change match()'s own routing."""
    assert router.match("read file report.txt") == "file_read"
    assert router.match("echo hello") == "echo"
    assert router.match("summarise file report.txt") is None


# --- match_memory_summary(): explicit memory-summary command (Phase 9, Batch 2)


def test_match_memory_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_memory_summary("summarise memory 42") == "42"


def test_match_memory_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_memory_summary("summarize memory 42") == "42"


def test_match_memory_summary_extracts_raw_unparsed_id_text(
    router: CommandRouter,
) -> None:
    """The router extracts the raw trailing text only - it never parses it
    into an int itself; a non-numeric or malformed id is still returned as
    a string for the orchestrator to reject honestly."""
    assert router.match_memory_summary("summarise memory abc") == "abc"
    assert router.match_memory_summary("summarise memory 4.2") == "4.2"
    assert router.match_memory_summary("summarise memory -5") == "-5"


def test_match_memory_summary_with_no_id_returns_empty_string(
    router: CommandRouter,
) -> None:
    """Recognised as a memory-summary command, but with no id - the caller
    (JarvisOrchestrator) is responsible for handling the empty id as an
    honest invalid-id failure, exactly like an empty file-summary path."""
    assert router.match_memory_summary("summarise memory") == ""


def test_match_memory_summary_strips_surrounding_whitespace(
    router: CommandRouter,
) -> None:
    assert router.match_memory_summary("summarise memory   42   ") == "42"


def test_match_memory_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_summary("summarise the plan for me") is None
    assert router.match_memory_summary("show memory 42") is None
    assert router.match_memory_summary("forget memory 42") is None
    assert router.match_memory_summary("summarise file report.txt") is None
    assert router.match_memory_summary("do a backflip") is None


def test_match_memory_summary_does_not_require_any_registered_tool() -> None:
    """Unlike match_file_summary (gated on file_read being registered),
    memory summarisation never goes through a registered tool at all, so it
    is recognised even with an empty registry."""
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)
    assert router.match_memory_summary("summarise memory 42") == "42"


def test_match_memory_summary_does_not_change_normal_match_behaviour(
    router: CommandRouter,
) -> None:
    """Adding match_memory_summary must not change match()'s own routing,
    including its existing "show memory <id>" and "forget memory <id>"
    behaviour. Note that match() itself already returns "memory" for text
    containing the bare keyword "memory" (pre-existing, unrelated behaviour,
    unchanged here) - this is harmless in practice because JarvisOrchestrator
    checks match_memory_summary first and never falls through to match() for
    a recognised memory-summary command (see test_command_router_orchestrator
    dispatch order proven in test_memory_summary_workflow.py)."""
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match("read file report.txt") == "file_read"
    assert router.match("echo hello") == "echo"


def test_match_memory_summary_does_not_change_file_summary_behaviour(
    router: CommandRouter,
) -> None:
    """Adding match_memory_summary must not change match_file_summary()'s
    own recognition."""
    assert router.match_file_summary("summarise file report.txt") == "report.txt"
    assert router.match_file_summary("summarise memory 42") is None


# --- match_memory_set_summary(): multi-memory-summary command (Phase 10, Batch 2)


def test_match_memory_set_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_memory_set_summary("summarise memories 3, 7, 12") == "3, 7, 12"


def test_match_memory_set_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_memory_set_summary("summarize memories 3, 7, 12") == "3, 7, 12"


def test_match_memory_set_summary_extracts_raw_unparsed_id_text(
    router: CommandRouter,
) -> None:
    """The router extracts the raw trailing text only - parsing, stable
    deduplication, and cardinality validation are the orchestrator's job."""
    assert router.match_memory_set_summary("summarise memories 27, 12, 27, 18") == (
        "27, 12, 27, 18"
    )
    assert router.match_memory_set_summary("summarise memories abc, 2") == "abc, 2"


def test_match_memory_set_summary_with_no_ids_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert router.match_memory_set_summary("summarise memories") == ""


def test_match_memory_set_summary_strips_surrounding_whitespace(
    router: CommandRouter,
) -> None:
    assert router.match_memory_set_summary("summarise memories   3, 7   ") == "3, 7"


def test_match_memory_set_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_set_summary("summarise the plan for me") is None
    assert router.match_memory_set_summary("show memory 42") is None
    assert router.match_memory_set_summary("forget memory 42") is None
    assert router.match_memory_set_summary("summarise file report.txt") is None
    assert router.match_memory_set_summary("do a backflip") is None


def test_match_memory_set_summary_does_not_collide_with_singular_command(
    router: CommandRouter,
) -> None:
    """Plural and singular prefixes diverge at their 5th character ("memory"
    vs "memories") and can never match each other's text."""
    assert router.match_memory_set_summary("summarise memory 42") is None
    assert router.match_memory_summary("summarise memories 3, 7") is None


def test_match_memory_set_summary_does_not_require_any_registered_tool() -> None:
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)
    assert router.match_memory_set_summary("summarise memories 3, 7") == "3, 7"


def test_match_memory_set_summary_does_not_change_existing_routing(
    router: CommandRouter,
) -> None:
    """Adding match_memory_set_summary must not change match()'s own
    routing, match_memory_summary()'s own recognition, or
    match_file_summary()'s own recognition."""
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match_memory_summary("summarise memory 42") == "42"
    assert router.match_file_summary("summarise file report.txt") == "report.txt"


# --- match_memory_query_summary(): query-based memory-summary command (Phase 11, Batch 2)


def test_match_memory_query_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_query_summary("summarise memories about Jarvis security")
        == "Jarvis security"
    )


def test_match_memory_query_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_query_summary("summarize memories about Jarvis security")
        == "Jarvis security"
    )


def test_match_memory_query_summary_extracts_exact_raw_query_text(
    router: CommandRouter,
) -> None:
    """The extracted text is the raw trailing query, unparsed and
    unnormalised beyond the leading/trailing whitespace strip every other
    summary matcher already applies - punctuation, wildcard characters, and
    internal whitespace are all preserved exactly."""
    assert (
        router.match_memory_query_summary("summarise memories about the budget review")
        == "the budget review"
    )
    assert router.match_memory_query_summary("summarise memories about %") == "%"
    assert router.match_memory_query_summary("summarise memories about _at") == "_at"
    assert (
        router.match_memory_query_summary("summarise memories about O'Brien's notes")
        == "O'Brien's notes"
    )
    assert (
        router.match_memory_query_summary(
            "summarise memories about '; DROP TABLE episodic_memories; --"
        )
        == "'; DROP TABLE episodic_memories; --"
    )


def test_match_memory_query_summary_requires_the_about_grammar(
    router: CommandRouter,
) -> None:
    """Without the literal "about" grammar, this is not a query-based
    request at all - it falls through to the plural explicit-id matcher
    (proven in the orchestrator-level workflow tests), never silently
    treated as a query."""
    assert router.match_memory_query_summary("summarise memories") is None
    assert router.match_memory_query_summary("summarise memories 3, 7, 12") is None
    assert router.match_memory_query_summary("summarise memory 42") is None


def test_match_memory_query_summary_with_no_query_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert router.match_memory_query_summary("summarise memories about") == ""
    assert router.match_memory_query_summary("summarise memories about   ") == ""


def test_match_memory_query_summary_strips_surrounding_whitespace(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_query_summary("summarise memories about   security   ")
        == "security"
    )


def test_match_memory_query_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_query_summary("summarise the plan for me") is None
    assert router.match_memory_query_summary("show memory 42") is None
    assert router.match_memory_query_summary("forget memory 42") is None
    assert router.match_memory_query_summary("summarise file report.txt") is None
    assert router.match_memory_query_summary("do a backflip") is None


def test_match_memory_query_summary_does_not_require_any_registered_tool() -> None:
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)
    assert (
        router.match_memory_query_summary("summarise memories about security")
        == "security"
    )


def test_match_memory_query_summary_does_not_collide_with_plural_explicit_id(
    router: CommandRouter,
) -> None:
    """The concrete collision found during planning: without the required
    "about" grammar, the query matcher must return None so the plural
    explicit-id matcher can recognise its own command unchanged."""
    assert router.match_memory_query_summary("summarise memories 27, 12, 18") is None
    assert router.match_memory_set_summary("summarise memories 27, 12, 18") == (
        "27, 12, 18"
    )
    assert (
        router.match_memory_query_summary("summarise memories about Jarvis security")
        == "Jarvis security"
    )


def test_plural_matcher_alone_would_also_match_query_text_proving_the_collision(
    router: CommandRouter,
) -> None:
    """Documents the concrete collision this batch's dispatch-order fix
    resolves: match_memory_set_summary(), considered in isolation, DOES
    also match "summarise memories about <query>" (its prefix is a plain
    string prefix of the whole text), returning the wrong raw text
    ("about Jarvis security", not a valid id list). Disambiguation is not
    performed by either matcher unilaterally - it is the caller
    (JarvisOrchestrator.handle_request) checking the more specific
    query matcher first that resolves this, proven end-to-end in
    test_memory_query_summary_workflow.py."""
    assert router.match_memory_set_summary(
        "summarise memories about Jarvis security"
    ) == "about Jarvis security"


def test_match_memory_query_summary_does_not_collide_with_singular_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_query_summary("summarise memory 42") is None
    assert router.match_memory_summary("summarise memories about security") is None


def test_match_memory_query_summary_does_not_change_existing_routing(
    router: CommandRouter,
) -> None:
    """Adding match_memory_query_summary must not change match()'s own
    routing, match_memory_summary()'s own recognition,
    match_memory_set_summary()'s own recognition, or
    match_file_summary()'s own recognition (broad generic memory path
    compatibility)."""
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match_memory_summary("summarise memory 42") == "42"
    assert router.match_memory_set_summary("summarise memories 3, 7, 12") == "3, 7, 12"
    assert router.match_file_summary("summarise file report.txt") == "report.txt"


# --- match_memory_category_summary(): category-based memory-summary command (Phase 12, Batch 2)


def test_match_memory_category_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_category_summary("summarise memories in project")
        == "project"
    )


def test_match_memory_category_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_category_summary("summarize memories in project")
        == "project"
    )


def test_match_memory_category_summary_extracts_exact_raw_category_text(
    router: CommandRouter,
) -> None:
    """The extracted text is the raw trailing category, unparsed and
    unnormalised beyond the leading/trailing whitespace strip every other
    summary matcher already applies - case and punctuation are preserved
    exactly; validation/canonicalisation happen downstream."""
    assert (
        router.match_memory_category_summary("summarise memories in PROJECT")
        == "PROJECT"
    )
    assert (
        router.match_memory_category_summary("summarise memories in spaceships")
        == "spaceships"
    )
    assert (
        router.match_memory_category_summary("summarise memories in SYSTEM")
        == "SYSTEM"
    )


def test_match_memory_category_summary_requires_the_in_grammar(
    router: CommandRouter,
) -> None:
    """Without the literal "in" grammar, this is not a category-based
    request at all - it falls through to the plural explicit-id matcher
    (proven in the orchestrator-level workflow tests), never silently
    treated as a category."""
    assert router.match_memory_category_summary("summarise memories") is None
    assert router.match_memory_category_summary("summarise memories 3, 7, 12") is None
    assert router.match_memory_category_summary("summarise memory 42") is None
    assert (
        router.match_memory_category_summary("summarise memories about security")
        is None
    )


def test_match_memory_category_summary_with_no_category_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert router.match_memory_category_summary("summarise memories in") == ""
    assert router.match_memory_category_summary("summarise memories in   ") == ""


def test_match_memory_category_summary_strips_surrounding_whitespace(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_category_summary("summarise memories in   project   ")
        == "project"
    )


def test_match_memory_category_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_category_summary("summarise the plan for me") is None
    assert router.match_memory_category_summary("show memory 42") is None
    assert router.match_memory_category_summary("forget memory 42") is None
    assert router.match_memory_category_summary("summarise file report.txt") is None
    assert router.match_memory_category_summary("show memories in project") is None
    assert router.match_memory_category_summary("do a backflip") is None


def test_match_memory_category_summary_does_not_require_any_registered_tool() -> None:
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)
    assert (
        router.match_memory_category_summary("summarise memories in project")
        == "project"
    )


def test_match_memory_category_summary_does_not_collide_with_plural_explicit_id(
    router: CommandRouter,
) -> None:
    """The concrete collision found during planning (the same class Phase
    11 already discovered): without the required "in" grammar, this
    matcher must return None so the plural explicit-id matcher (checked
    afterward by the orchestrator) can recognise its own command
    unchanged."""
    assert router.match_memory_category_summary("summarise memories 27, 12, 18") is None
    assert router.match_memory_set_summary("summarise memories 27, 12, 18") == (
        "27, 12, 18"
    )
    assert (
        router.match_memory_category_summary("summarise memories in project")
        == "project"
    )


def test_plural_matcher_alone_would_also_match_category_text_proving_the_collision(
    router: CommandRouter,
) -> None:
    """Documents the concrete collision this batch's dispatch-order fix
    resolves: match_memory_set_summary(), considered in isolation, DOES
    also match "summarise memories in <category>" (its prefix is a plain
    string prefix of the whole text), returning the wrong raw text
    ("in project", not a valid id list). Disambiguation is not performed
    by either matcher unilaterally - it is the caller
    (JarvisOrchestrator.handle_request) checking the more specific
    category matcher first that resolves this, proven end-to-end in
    test_memory_category_summary_workflow.py."""
    assert router.match_memory_set_summary(
        "summarise memories in project"
    ) == "in project"


def test_match_memory_category_summary_does_not_collide_with_singular_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_category_summary("summarise memory 42") is None
    assert router.match_memory_summary("summarise memories in project") is None


def test_match_memory_category_summary_does_not_collide_with_query_command(
    router: CommandRouter,
) -> None:
    """"summarise memories in" and "summarise memories about" diverge at
    their second word - neither matcher ever swallows the other's
    command."""
    assert (
        router.match_memory_category_summary("summarise memories about security")
        is None
    )
    assert (
        router.match_memory_query_summary("summarise memories in project") is None
    )


def test_match_memory_category_summary_does_not_change_existing_routing(
    router: CommandRouter,
) -> None:
    """Adding match_memory_category_summary must not change match()'s own
    routing, match_memory_summary()'s own recognition,
    match_memory_query_summary()'s own recognition,
    match_memory_set_summary()'s own recognition, or
    match_file_summary()'s own recognition (broad generic memory path
    compatibility, including the pre-existing "show memories in
    <category>" command)."""
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match("show memories in project") == "memory"
    assert router.match_memory_summary("summarise memory 42") == "42"
    assert (
        router.match_memory_query_summary("summarise memories about security")
        == "security"
    )
    assert router.match_memory_set_summary("summarise memories 3, 7, 12") == "3, 7, 12"
    assert router.match_file_summary("summarise file report.txt") == "report.txt"


# --- match_memory_recent_summary(): recent-memory-summary command (Phase 13, Batch 2)


def test_match_memory_recent_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("summarise recent memories") is True


def test_match_memory_recent_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("summarize recent memories") is True


def test_match_memory_recent_summary_is_case_insensitive(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("SUMMARISE RECENT MEMORIES") is True
    assert router.match_memory_recent_summary("Summarise Recent Memories") is True


def test_match_memory_recent_summary_strips_surrounding_whitespace(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("  summarise recent memories  ") is True


def test_match_memory_recent_summary_rejects_extra_trailing_text(
    router: CommandRouter,
) -> None:
    """The exact-match contract (docs/phase_13_implementation_plan.md,
    Section 4.2/11): unlike every prefix-based summary matcher, this
    command has no free-text argument at all, so any extra trailing text
    names a different, unrecognised command - never a Phase 13 request
    with the extra tokens silently ignored."""
    assert router.match_memory_recent_summary(
        "summarise recent memories about security"
    ) is False
    assert router.match_memory_recent_summary(
        "summarise recent memories in project"
    ) is False
    assert router.match_memory_recent_summary("summarise recent memories 5") is False
    assert router.match_memory_recent_summary("summarise recent memory") is False
    assert router.match_memory_recent_summary("summarise very recent memories") is False
    assert router.match_memory_recent_summary("summarise recent memories!") is False


def test_match_memory_recent_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("summarise the plan for me") is False
    assert router.match_memory_recent_summary("show memory 42") is False
    assert router.match_memory_recent_summary("forget memory 42") is False
    assert router.match_memory_recent_summary("summarise file report.txt") is False
    assert router.match_memory_recent_summary("show memories in project") is False
    assert router.match_memory_recent_summary("do a backflip") is False
    assert router.match_memory_recent_summary("summarise memory 27") is False
    assert (
        router.match_memory_recent_summary("summarise memories 27, 12, 18") is False
    )
    assert (
        router.match_memory_recent_summary("summarise memories about Jarvis security")
        is False
    )
    assert router.match_memory_recent_summary("summarise memories in project") is False


def test_match_memory_recent_summary_does_not_require_any_registered_tool() -> None:
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)

    assert router.match_memory_recent_summary("summarise recent memories") is True


def test_match_memory_recent_summary_does_not_collide_with_plural_explicit_id(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("summarise memories 27, 12, 18") is False
    assert router.match_memory_set_summary("summarise memories 27, 12, 18") == (
        "27, 12, 18"
    )
    assert router.match_memory_recent_summary("summarise recent memories") is True
    assert router.match_memory_set_summary("summarise recent memories") is None


def test_match_memory_recent_summary_does_not_collide_with_singular_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("summarise memory 42") is False
    assert router.match_memory_summary("summarise recent memories") is None


def test_match_memory_recent_summary_does_not_collide_with_query_command(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_recent_summary("summarise memories about security")
        is False
    )
    assert router.match_memory_query_summary("summarise recent memories") is None


def test_match_memory_recent_summary_does_not_collide_with_category_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_summary("summarise memories in project") is False
    assert router.match_memory_category_summary("summarise recent memories") is None


def test_match_memory_recent_summary_does_not_change_existing_routing(
    router: CommandRouter,
) -> None:
    """Adding match_memory_recent_summary must not change match()'s own
    routing, or any other matcher's own recognition."""
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match("show memories in project") == "memory"
    assert router.match_memory_summary("summarise memory 42") == "42"
    assert (
        router.match_memory_query_summary("summarise memories about security")
        == "security"
    )
    assert (
        router.match_memory_category_summary("summarise memories in project")
        == "project"
    )
    assert router.match_memory_set_summary("summarise memories 3, 7, 12") == "3, 7, 12"
    assert router.match_file_summary("summarise file report.txt") == "report.txt"


# --- match_memory_recent_count_summary(): count-based recent-memory-summary command (Phase 14, Batch 2)


def test_match_memory_recent_count_summary_recognises_summarise_spelling(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_recent_count_summary("summarise latest 5 memories")
        == "5"
    )


def test_match_memory_recent_count_summary_recognises_summarize_spelling(
    router: CommandRouter,
) -> None:
    assert (
        router.match_memory_recent_count_summary("summarize latest 5 memories")
        == "5"
    )


def test_match_memory_recent_count_summary_extracts_raw_count_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise latest 10 memories"
    ) == "10"


def test_match_memory_recent_count_summary_does_not_normalise_leading_zero(
    router: CommandRouter,
) -> None:
    """The router extracts the raw captured text unchanged - leading-zero
    normalisation, like all numeric validity, belongs to
    select_recent_memory_ids_by_count(), not this matcher."""
    assert router.match_memory_recent_count_summary(
        "summarise latest 05 memories"
    ) == "05"


def test_match_memory_recent_count_summary_matches_structurally_invalid_count_text(
    router: CommandRouter,
) -> None:
    """A grammatically-complete command with a semantically invalid count
    still matches at the router level - numeric/range validity is deferred
    to the selector, never rejected here."""
    assert router.match_memory_recent_count_summary(
        "summarise latest five memories"
    ) == "five"
    assert router.match_memory_recent_count_summary(
        "summarise latest 0 memories"
    ) == "0"
    assert router.match_memory_recent_count_summary(
        "summarise latest 55 memories"
    ) == "55"


def test_match_memory_recent_count_summary_does_not_match_missing_count(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise latest memories"
    ) is None
    assert router.match_memory_recent_count_summary(
        "summarize latest memories"
    ) is None


def test_match_memory_recent_count_summary_does_not_match_singular_memory(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise latest 5 memory"
    ) is None


def test_match_memory_recent_count_summary_does_not_match_other_recency_wording(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise recent 5 memories"
    ) is None
    assert router.match_memory_recent_count_summary(
        "summarise 5 recent memories"
    ) is None
    assert router.match_memory_recent_count_summary(
        "summarise very latest 5 memories"
    ) is None


def test_match_memory_recent_count_summary_does_not_match_extra_qualifier(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise latest 5 stored memories"
    ) is None


def test_match_memory_recent_count_summary_does_not_match_extra_trailing_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise latest 5 memories about security"
    ) is None
    assert router.match_memory_recent_count_summary(
        "summarise latest 5 memories in project"
    ) is None
    assert router.match_memory_recent_count_summary(
        "summarise latest 5 memories!"
    ) is None


def test_match_memory_recent_count_summary_does_not_match_unrelated_text(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise the plan for me"
    ) is None
    assert router.match_memory_recent_count_summary("show memory 42") is None
    assert router.match_memory_recent_count_summary("forget memory 42") is None
    assert router.match_memory_recent_count_summary(
        "summarise file report.txt"
    ) is None
    assert router.match_memory_recent_count_summary(
        "show memories in project"
    ) is None
    assert router.match_memory_recent_count_summary("do a backflip") is None


def test_match_memory_recent_count_summary_does_not_collide_with_recent_exact_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise recent memories"
    ) is None
    assert router.match_memory_recent_summary("summarise latest 5 memories") is False


def test_match_memory_recent_count_summary_does_not_collide_with_plural_explicit_id(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise memories 27, 12, 18"
    ) is None
    assert router.match_memory_set_summary("summarise latest 5 memories") is None
    assert (
        router.match_memory_recent_count_summary("summarise latest 5 memories")
        == "5"
    )


def test_match_memory_recent_count_summary_does_not_collide_with_singular_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary("summarise memory 42") is None
    assert router.match_memory_summary("summarise latest 5 memories") is None


def test_match_memory_recent_count_summary_does_not_collide_with_query_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise memories about security"
    ) is None
    assert (
        router.match_memory_query_summary("summarise latest 5 memories") is None
    )


def test_match_memory_recent_count_summary_does_not_collide_with_category_command(
    router: CommandRouter,
) -> None:
    assert router.match_memory_recent_count_summary(
        "summarise memories in project"
    ) is None
    assert (
        router.match_memory_category_summary("summarise latest 5 memories")
        is None
    )


def test_match_memory_recent_count_summary_does_not_require_any_registered_tool() -> (
    None
):
    empty_registry = ToolRegistry()
    router = CommandRouter(empty_registry)

    assert (
        router.match_memory_recent_count_summary("summarise latest 5 memories")
        == "5"
    )


def test_match_memory_recent_count_summary_does_not_change_existing_routing(
    router: CommandRouter,
) -> None:
    """Adding match_memory_recent_count_summary must not change match()'s
    own routing, or any other matcher's own recognition."""
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match("show memories in project") == "memory"
    assert router.match_memory_summary("summarise memory 42") == "42"
    assert (
        router.match_memory_query_summary("summarise memories about security")
        == "security"
    )
    assert (
        router.match_memory_category_summary("summarise memories in project")
        == "project"
    )
    assert router.match_memory_recent_summary("summarise recent memories") is True
    assert router.match_memory_set_summary("summarise memories 3, 7, 12") == "3, 7, 12"
    assert router.match_file_summary("summarise file report.txt") == "report.txt"


# --- Phase 15, Batch 3: workflow command matchers ----------------------------


def test_match_remember_and_show_back_workflow_exact_command(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_show_back_workflow(
            "remember this and show it back: Buy milk"
        )
        == "Buy milk"
    )


def test_match_remember_and_show_back_workflow_is_case_insensitive(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_show_back_workflow(
            "REMEMBER THIS AND SHOW IT BACK: Buy milk"
        )
        == "Buy milk"
    )


def test_match_remember_and_show_back_workflow_preserves_unicode_text(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_show_back_workflow(
            "remember this and show it back: héllo wörld 你好"
        )
        == "héllo wörld 你好"
    )


def test_match_remember_and_show_back_workflow_strips_surrounding_whitespace(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_show_back_workflow(
            "remember this and show it back:    Buy milk   "
        )
        == "Buy milk"
    )


def test_match_remember_and_show_back_workflow_empty_text_returns_empty_string(
    router: CommandRouter,
) -> None:
    """The prefix matches; the empty trailing text is the orchestrator's own
    responsibility to reject honestly - the router never silently invents
    or rejects content itself."""
    assert router.match_remember_and_show_back_workflow(
        "remember this and show it back:"
    ) == ""


def test_match_remember_and_show_back_workflow_whitespace_only_text_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_show_back_workflow(
            "remember this and show it back:      "
        )
        == ""
    )


@pytest.mark.parametrize(
    "request_text",
    [
        "remember this and show it back",  # missing colon
        "remember and show it back: Buy milk",  # missing "this"
        "remember this then show it back: Buy milk",  # wrong connector
        "remember this and show: Buy milk",  # missing "it back"
        "remember this and show it back and forget it: Buy milk",  # trailing qualifier before colon differs
        "remember this: Buy milk; show it back",  # semicolon-separated
        "remember this and then show it back: Buy milk",  # "and then" syntax
        "show it back: Buy milk",  # missing leading phrase entirely
        "remember this",  # no workflow language at all
        "",
    ],
)
def test_match_remember_and_show_back_workflow_rejects_malformed_grammar(
    router: CommandRouter, request_text: str
) -> None:
    assert router.match_remember_and_show_back_workflow(request_text) is None


def test_match_remember_and_forget_workflow_exact_command(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_forget_workflow(
            "remember this and forget it: Temporary note"
        )
        == "Temporary note"
    )


def test_match_remember_and_forget_workflow_is_case_insensitive(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_forget_workflow(
            "Remember This And Forget It: Temporary note"
        )
        == "Temporary note"
    )


def test_match_remember_and_forget_workflow_preserves_unicode_text(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_forget_workflow(
            "remember this and forget it: héllo wörld 你好"
        )
        == "héllo wörld 你好"
    )


def test_match_remember_and_forget_workflow_empty_text_returns_empty_string(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_forget_workflow("remember this and forget it:")
        == ""
    )


@pytest.mark.parametrize(
    "request_text",
    [
        "remember this and forget it",  # missing colon
        "remember and forget it: Temporary note",  # missing "this"
        "remember this then forget it: Temporary note",  # wrong connector
        "remember this and forget: Temporary note",  # missing "it"
        "remember this: Temporary note; forget it",  # semicolon-separated
        "remember this and then forget it: Temporary note",  # "and then" syntax
        "forget it: Temporary note",  # missing leading phrase entirely
        "remember this",  # no workflow language at all
        "",
    ],
)
def test_match_remember_and_forget_workflow_rejects_malformed_grammar(
    router: CommandRouter, request_text: str
) -> None:
    assert router.match_remember_and_forget_workflow(request_text) is None


def test_workflow_matchers_do_not_collide_with_each_other(
    router: CommandRouter,
) -> None:
    assert (
        router.match_remember_and_forget_workflow(
            "remember this and show it back: Buy milk"
        )
        is None
    )
    assert (
        router.match_remember_and_show_back_workflow(
            "remember this and forget it: Temporary note"
        )
        is None
    )


def test_workflow_matchers_do_not_change_existing_routing(
    router: CommandRouter,
) -> None:
    """Adding the two Phase 15 workflow matchers must not change match()'s
    own routing, any existing summary-family matcher, or the ordinary
    generic "remember this: ..." save command."""
    assert router.match("remember this: Buy milk") == "memory"
    assert router.match("show memory 5") == "memory"
    assert router.match("forget memory 3") == "memory_forget"
    assert router.match_memory_summary("summarise memory 42") == "42"
    assert (
        router.match_memory_query_summary("summarise memories about security")
        == "security"
    )
    assert (
        router.match_memory_category_summary("summarise memories in project")
        == "project"
    )
    assert router.match_memory_recent_summary("summarise recent memories") is True
    assert router.match_memory_set_summary("summarise memories 3, 7, 12") == "3, 7, 12"
    assert router.match_file_summary("summarise file report.txt") == "report.txt"
    assert (
        router.match_memory_recent_count_summary("summarise latest 5 memories")
        == "5"
    )
    # And, critically, the collision this batch's own investigation found:
    # the generic "remember this" save command must still work exactly as
    # before for ordinary requests that are not one of the two new exact
    # workflow phrases.
    assert (
        router.match_remember_and_show_back_workflow("remember this: Buy milk")
        is None
    )
    assert (
        router.match_remember_and_forget_workflow("remember this: Buy milk") is None
    )
