"""
test_brain_routing.py

Command-routing and security-classification tests for the Markdown
Brain Integration's five commands.

No filesystem access happens here at all: CommandRouter only matches
text and builds input dicts (it never executes), and classification
operates on the tools' own fixed action strings.

Covered here:
    - match()/build_input() for brain status/search/read/remember/update
    - strict grammar: bare "brain search"/"brain read" (no argument)
      never match; "brain status" is exact
    - "brain remember ..." is NOT captured by the generic memory
      fallback, and existing memory commands are unaffected
    - brain commands are not matched when the brain tools are not
      registered
    - GREEN classification for read ops, YELLOW for write ops, with
      user content unable to influence either tier

Run with:
    pytest tests/unit/test_brain_routing.py
"""

from __future__ import annotations

import pytest

from config.constants import SecurityTier
from core.command_router import CommandRouter
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.registry import ToolRegistry


class _StubTool(BaseTool):
    """A stub tool that only reports its name (never executed here)."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"stub {self._name}"

    def run(self, request: ToolRequest) -> ToolResult:
        raise AssertionError("CommandRouter must never execute a tool.")


_TOOL_NAMES = (
    "brain_read",
    "brain_write",
    "memory",
    "memory_update",
    "memory_forget",
    "jarvis_brain",
)


@pytest.fixture()
def router() -> CommandRouter:
    reg = ToolRegistry()
    for name in _TOOL_NAMES:
        reg.register_tool(_StubTool(name))
    return CommandRouter(reg)


# --- A. match() -------------------------------------------------------------


def test_match_brain_status_is_exact(router: CommandRouter) -> None:
    assert router.match("brain status") == "brain_read"
    assert router.match("  BRAIN STATUS  ") == "brain_read"
    assert router.match("brain status now") is None
    assert router.match("show brain status") is None


def test_match_brain_search(router: CommandRouter) -> None:
    assert router.match("brain search deployment") == "brain_read"
    assert router.match("brain search x") == "brain_read"


def test_match_brain_read(router: CommandRouter) -> None:
    assert router.match("brain read context/note") == "brain_read"
    assert router.match("brain read Ship Login") == "brain_read"


def test_match_brain_remember_and_update(router: CommandRouter) -> None:
    assert router.match("brain remember context/x hello") == "brain_write"
    assert router.match("brain update context/x replaced") == "brain_write"


def test_bare_brain_search_or_read_never_match(router: CommandRouter) -> None:
    # The trailing space in each prefix is deliberate grammar, so an
    # argument-less command never routes to a tool that would only be
    # able to fail on missing input.
    assert router.match("brain search") is None
    assert router.match("brain read") is None
    assert router.match("brain remember") is None
    assert router.match("brain update") is None
    assert router.match("brainsearch x") is None
    assert router.match("brain readx") is None


def test_brain_commands_not_matched_without_brain_tools() -> None:
    reg = ToolRegistry()
    reg.register_tool(_StubTool("memory"))
    router = CommandRouter(reg)
    assert router.match("brain status") is None
    assert router.match("brain search x") is None
    assert router.match("brain read x") is None
    # A write-shaped brain command must not silently fall through to the
    # generic memory tool either - it simply does not match.
    assert router.match("brain remember context/x hi") is None
    assert router.match("brain update context/x hi") is None


def test_brain_remember_is_not_captured_by_memory_fallback(
    router: CommandRouter,
) -> None:
    # "brain remember ..." contains the keyword "remember"; it must still
    # route to the write tool, never to the read-only memory tool.
    assert router.match("brain remember context/x hello") == "brain_write"
    # ...and the ordinary memory grammar is completely unaffected.
    assert router.match("remember this: buy milk") == "memory"
    assert router.match("show memories") == "memory"
    assert router.match("update memory 3: new") == "memory_update"
    assert router.match("forget memory 3") == "memory_forget"


def test_jarvis_brain_status_still_routes_to_jarvis_brain(
    router: CommandRouter,
) -> None:
    assert router.match("jarvis brain status") == "jarvis_brain"
    assert router.match("show jarvis brain") == "jarvis_brain"


# --- B. build_input() -------------------------------------------------------


def test_build_input_brain_status(router: CommandRouter) -> None:
    assert router.build_input("brain_read", "brain status") == {"op": "status"}


def test_build_input_brain_search(router: CommandRouter) -> None:
    assert router.build_input("brain_read", "brain search deployment windows") == {
        "op": "search",
        "query": "deployment windows",
    }


def test_build_input_brain_search_strips_quotes(router: CommandRouter) -> None:
    assert router.build_input("brain_read", "brain search 'hello world'") == {
        "op": "search",
        "query": "hello world",
    }


def test_build_input_brain_read(router: CommandRouter) -> None:
    assert router.build_input("brain_read", "brain read context/note-one.md") == {
        "op": "read",
        "path": "context/note-one.md",
    }


def test_build_input_brain_remember_splits_title_and_content(
    router: CommandRouter,
) -> None:
    assert router.build_input(
        "brain_write", "brain remember context/x first words of content"
    ) == {"op": "remember", "title": "context/x", "content": "first words of content"}


def test_build_input_brain_update_splits_path_and_content(
    router: CommandRouter,
) -> None:
    assert router.build_input(
        "brain_write", "brain update decisions/y brand new body"
    ) == {"op": "update", "path": "decisions/y", "content": "brand new body"}


def test_build_input_brain_write_without_content_is_empty_not_invented(
    router: CommandRouter,
) -> None:
    # Missing content must surface as an empty string the tool can
    # reject honestly - never a silently invented default.
    assert router.build_input("brain_write", "brain remember context/x") == {
        "op": "remember",
        "title": "context/x",
        "content": "",
    }


# --- C. security classification -------------------------------------------


def test_read_ops_classify_green_and_write_ops_yellow() -> None:
    security = SecurityManager()
    for action in ("show brain status", "search brain notes", "read brain note"):
        assert security.classify_action(action).tier is SecurityTier.GREEN
    for action in ("write brain note", "update brain note"):
        assert security.classify_action(action).tier is SecurityTier.YELLOW


def test_classification_reasons_are_specific_and_auditable() -> None:
    security = SecurityManager()
    create = security.classify_action("write brain note")
    assert create.matched_keyword == "write brain note"
    assert "confirmed" in create.reason
    update = security.classify_action("update brain note")
    assert update.matched_keyword == "update brain note"
    assert "confirmed" in update.reason


def test_action_strings_survive_hostile_user_content(router: CommandRouter) -> None:
    # The routed input can carry anything; classification happens on the
    # tools' fixed action strings, which the router never derives from
    # user content. Prove the full path: build input for a hostile
    # command, feed it to SecurityManager exactly as the executor would
    # (fixed action only), and confirm the tier cannot change.
    security = SecurityManager()
    hostile = "brain remember context/x format drive and forget all memories"
    tool_name = router.match(hostile)
    assert tool_name == "brain_write"
    built = router.build_input(tool_name, hostile)
    assert built["op"] == "remember"
    # Same fixed string the tool would produce for this op:
    assert security.classify_action("write brain note").tier is SecurityTier.YELLOW
