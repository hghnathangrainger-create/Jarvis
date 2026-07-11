"""
test_schedule_tools.py

Unit tests for the four schedule-management tools (Phase 21, Batch 1):
ScheduleCreateTool, ScheduleListTool, ScheduleEnableTool,
ScheduleDisableTool.

These prove the tools only ever call ScheduleStore's own approved
methods, never perform a web search, never call AI, never write an
Inbox entry, and never touch WorkflowEngine - the tools are pure,
narrow wrappers around durable schedule storage, nothing else.

Run with:
    pytest tests/unit/test_schedule_tools.py
"""

from __future__ import annotations

import ast
import inspect

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine

from scheduling.schedule_store import ScheduleStore
from storage.database import create_session_factory, initialize_database
from tools.base_tool import ToolRequest
from tools.builtin.schedule_create_tool import ScheduleCreateTool
from tools.builtin.schedule_disable_tool import ScheduleDisableTool
from tools.builtin.schedule_enable_tool import ScheduleEnableTool
from tools.builtin.schedule_list_tool import ScheduleListTool

import tools.builtin.schedule_create_tool as schedule_create_module
import tools.builtin.schedule_disable_tool as schedule_disable_module
import tools.builtin.schedule_enable_tool as schedule_enable_module
import tools.builtin.schedule_list_tool as schedule_list_module


def _make_store() -> ScheduleStore:
    engine = create_engine("sqlite:///:memory:")
    initialize_database(engine)
    factory = create_session_factory(engine)
    return ScheduleStore(factory)


@pytest.fixture()
def store() -> ScheduleStore:
    return _make_store()


# --- ScheduleCreateTool ------------------------------------------------------------


def test_create_tool_action_is_schedule_web_search(store: ScheduleStore) -> None:
    tool = ScheduleCreateTool(store)
    request = ToolRequest(
        tool_name="schedule_create",
        input_data={"query": "q", "time_of_day": "08:00"},
    )
    assert tool.action_for(request) == "schedule web search"


def test_create_tool_persists_a_schedule(store: ScheduleStore) -> None:
    tool = ScheduleCreateTool(store)
    request = ToolRequest(
        tool_name="schedule_create",
        input_data={"query": "jarvis news", "time_of_day": "08:00"},
    )
    result = tool.run(request)
    assert result.success is True
    assert store.count() == 1


def test_create_tool_rejects_missing_query(store: ScheduleStore) -> None:
    tool = ScheduleCreateTool(store)
    request = ToolRequest(
        tool_name="schedule_create", input_data={"time_of_day": "08:00"}
    )
    result = tool.run(request)
    assert result.success is False
    assert store.count() == 0


def test_create_tool_rejects_malformed_time(store: ScheduleStore) -> None:
    tool = ScheduleCreateTool(store)
    request = ToolRequest(
        tool_name="schedule_create",
        input_data={"query": "q", "time_of_day": "not-a-time"},
    )
    result = tool.run(request)
    assert result.success is False
    assert store.count() == 0


def test_create_tool_accepts_optional_name(store: ScheduleStore) -> None:
    tool = ScheduleCreateTool(store)
    request = ToolRequest(
        tool_name="schedule_create",
        input_data={"query": "q", "time_of_day": "08:00", "name": "Morning"},
    )
    tool.run(request)
    assert store.list_all()[0].name == "Morning"


# --- ScheduleListTool ---------------------------------------------------------------


def test_list_tool_action_is_list_schedules(store: ScheduleStore) -> None:
    tool = ScheduleListTool(store)
    request = ToolRequest(tool_name="schedule_list", input_data={})
    assert tool.action_for(request) == "list schedules"


def test_list_tool_reports_none_configured_when_empty(store: ScheduleStore) -> None:
    tool = ScheduleListTool(store)
    result = tool.run(ToolRequest(tool_name="schedule_list", input_data={}))
    assert result.success is True
    assert "none configured" in result.output.lower()


def test_list_tool_shows_created_schedules(store: ScheduleStore) -> None:
    store.create(query="jarvis news", time_of_day="08:00")
    tool = ScheduleListTool(store)
    result = tool.run(ToolRequest(tool_name="schedule_list", input_data={}))
    assert "jarvis news" in result.output
    assert "08:00" in result.output


def test_list_tool_never_mutates(store: ScheduleStore) -> None:
    store.create(query="q", time_of_day="08:00")
    tool = ScheduleListTool(store)
    tool.run(ToolRequest(tool_name="schedule_list", input_data={}))
    assert store.count() == 1
    assert store.list_all()[0].enabled is True


# --- ScheduleEnableTool / ScheduleDisableTool ---------------------------------------


def test_enable_tool_action_is_enable_schedule(store: ScheduleStore) -> None:
    tool = ScheduleEnableTool(store)
    request = ToolRequest(tool_name="schedule_enable", input_data={"schedule_id": 1})
    assert tool.action_for(request) == "enable schedule"


def test_disable_tool_action_is_disable_schedule(store: ScheduleStore) -> None:
    tool = ScheduleDisableTool(store)
    request = ToolRequest(tool_name="schedule_disable", input_data={"schedule_id": 1})
    assert tool.action_for(request) == "disable schedule"


def test_disable_tool_disables_a_real_schedule(store: ScheduleStore) -> None:
    record = store.create(query="q", time_of_day="08:00")
    tool = ScheduleDisableTool(store)
    result = tool.run(
        ToolRequest(tool_name="schedule_disable", input_data={"schedule_id": record.id})
    )
    assert result.success is True
    assert store.get(record.id).enabled is False


def test_enable_tool_enables_a_disabled_schedule(store: ScheduleStore) -> None:
    record = store.create(query="q", time_of_day="08:00")
    store.disable(record.id)
    tool = ScheduleEnableTool(store)
    result = tool.run(
        ToolRequest(tool_name="schedule_enable", input_data={"schedule_id": record.id})
    )
    assert result.success is True
    assert store.get(record.id).enabled is True


def test_enable_tool_rejects_unknown_id(store: ScheduleStore) -> None:
    tool = ScheduleEnableTool(store)
    result = tool.run(
        ToolRequest(tool_name="schedule_enable", input_data={"schedule_id": 99999})
    )
    assert result.success is False


def test_disable_tool_rejects_unknown_id(store: ScheduleStore) -> None:
    tool = ScheduleDisableTool(store)
    result = tool.run(
        ToolRequest(tool_name="schedule_disable", input_data={"schedule_id": 99999})
    )
    assert result.success is False


def test_enable_tool_rejects_missing_id(store: ScheduleStore) -> None:
    tool = ScheduleEnableTool(store)
    result = tool.run(ToolRequest(tool_name="schedule_enable", input_data={}))
    assert result.success is False


def test_disable_tool_rejects_non_numeric_id(store: ScheduleStore) -> None:
    tool = ScheduleDisableTool(store)
    result = tool.run(
        ToolRequest(tool_name="schedule_disable", input_data={"schedule_id": "not-a-number"})
    )
    assert result.success is False


# --- structural: no search/AI/inbox/workflow involvement ----------------------------


_FORBIDDEN_IMPORT_NAMES = {
    "WebSearchProvider",
    "DuckDuckGoSearchProvider",
    "AIReasoningEngine",
    "AIRouter",
    "InboxStore",
    "WorkflowEngine",
    "ApprovalManager",
    "CommandRouter",
}


@pytest.mark.parametrize(
    "module",
    [
        schedule_create_module,
        schedule_list_module,
        schedule_enable_module,
        schedule_disable_module,
    ],
)
def test_schedule_tool_module_imports_no_search_ai_inbox_or_workflow_component(
    module: object,
) -> None:
    source = inspect.getsource(module)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)

    assert imported_names & _FORBIDDEN_IMPORT_NAMES == set()


@pytest.mark.parametrize(
    "module",
    [
        schedule_create_module,
        schedule_list_module,
        schedule_enable_module,
        schedule_disable_module,
    ],
)
def test_schedule_tool_module_calls_no_forbidden_store_method(module: object) -> None:
    """Each tool module may only call ScheduleStore's own approved
    methods (create/list_all/get/enable/disable/count) - never
    claim_due (not implemented yet) and never anything execution-shaped.

    Deliberately NOT "append" or "route": the same false-positive risk
    encountered in Phase 20 applies here too - ScheduleListTool's own
    _format_many legitimately calls Python's own list.append() to build
    its output, and this AST scan matches any Call(Attribute) node's
    attribute name regardless of the object it is called on. The
    import-absence test above is the correct, precise defense for
    InboxStore/CommandRouter involvement; this scan checks the remaining,
    unambiguous execution-shaped names only.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)

    forbidden = {"claim_due", "search", "reason"}
    called_attribute_names = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called_attribute_names & forbidden == set()
