"""
test_tool_executor_logger_isolation.py

Focused tests for the Phase 15 Batch 4A corrective closure: ToolExecutor's
own logger.emit() calls must never let a failing logger alter an
otherwise-authoritative tool-execution outcome.

Batch 4 (Phase 15) empirically proved that a raising ToolExecutor logger
propagated, uncaught, out of every one of ToolExecutor's five emit call
sites (unknown tool, RED blocked, YELLOW needs-confirmation, tool-raised
failure, and the ordinary success/failure return) - a real, pre-existing
violation of the standing invariant "logger/observability failure must
never alter an authoritative workflow outcome", exposed (not caused) by
Phase 15's additional per-step ToolExecutor.execute() call sites. This
file proves the narrow corrective fix: ToolExecutor._emit_audit_event()
now isolates every one of those five call sites, while tool execution,
security classification, approval semantics, blocking, and genuine tool
exceptions all keep their existing, unchanged behaviour.

Run with:
    pytest tests/unit/test_tool_executor_logger_isolation.py
"""

from __future__ import annotations

import ast
import inspect

import pytest

from approval.approval_models import ApprovalRequest
from config.constants import SecurityTier
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry

# --- Test doubles --------------------------------------------------------------


class _RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return str(len(self.calls))


class _FailingLogger:
    def emit(self, **kwargs: object) -> str:
        raise RuntimeError("simulated logger failure")


class _GreenTool(BaseTool):
    """A GREEN tool ("read..." classifies GREEN) that succeeds once, with
    metadata, recording every call it actually receives."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "green"

    @property
    def description(self) -> str:
        return "A fake GREEN tool."

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(
            tool_name=self.name,
            success=True,
            output="ok",
            metadata={"marker": "green-result"},
        )


class _YellowTool(BaseTool):
    """A YELLOW tool ("delete..." classifies YELLOW) that only truly runs
    once approved."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "yellow"

    @property
    def description(self) -> str:
        return "A fake YELLOW tool."

    def action_for(self, request: ToolRequest) -> str:
        return "delete something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(tool_name=self.name, success=True, output="deleted")


class _RedTool(BaseTool):
    """A RED tool ("format drive..." classifies RED); run() must never be
    reached."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "red"

    @property
    def description(self) -> str:
        return "A fake RED tool."

    def action_for(self, request: ToolRequest) -> str:
        return "format drive C"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        raise AssertionError("A RED action must never run.")


class _GenuinelyFailingTool(BaseTool):
    """A GREEN tool whose run() genuinely raises - the exact exception this
    fix must never mask, even when the logger also fails."""

    def __init__(self) -> None:
        self.calls: list[ToolRequest] = []

    @property
    def name(self) -> str:
        return "genuinely_failing"

    @property
    def description(self) -> str:
        return "A fake tool that genuinely raises."

    def action_for(self, request: ToolRequest) -> str:
        return "read something"

    def run(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        raise ValueError("genuine tool bug")


def _executor(tool: BaseTool, logger: object) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register_tool(tool)
    return ToolExecutor(
        registry=registry, security_manager=SecurityManager(), logger=logger  # type: ignore[arg-type]
    )


def _approved_decision(action: str = "delete something"):
    request = ApprovalRequest(action=action, reason="r", security_tier=SecurityTier.YELLOW)
    return request.decide(approved=True, decided_by="test")


def _declined_decision(action: str = "delete something"):
    request = ApprovalRequest(action=action, reason="r", security_tier=SecurityTier.YELLOW)
    return request.decide(approved=False, decided_by="test")


# --- GREEN path ----------------------------------------------------------------


def test_green_success_survives_raising_logger() -> None:
    tool = _GreenTool()
    executor = _executor(tool, _FailingLogger())
    result = executor.execute("green", {})
    assert result.success is True
    assert len(tool.calls) == 1


def test_green_tool_executes_exactly_once_with_raising_logger() -> None:
    tool = _GreenTool()
    executor = _executor(tool, _FailingLogger())
    executor.execute("green", {})
    assert len(tool.calls) == 1


def test_green_result_field_equivalence_healthy_vs_raising_logger() -> None:
    healthy_result = _executor(_GreenTool(), _RecordingLogger()).execute("green", {})
    failing_result = _executor(_GreenTool(), _FailingLogger()).execute("green", {})
    assert healthy_result == failing_result


def test_green_no_retry_with_raising_logger() -> None:
    tool = _GreenTool()
    executor = _executor(tool, _FailingLogger())
    executor.execute("green", {})
    assert len(tool.calls) == 1


# --- YELLOW confirmation-required path ------------------------------------------


def test_yellow_confirmation_survives_raising_logger() -> None:
    tool = _YellowTool()
    executor = _executor(tool, _FailingLogger())
    result = executor.execute("yellow", {})
    assert result.requires_confirmation is True
    assert result.success is False


def test_yellow_dangerous_tool_not_executed_with_raising_logger() -> None:
    tool = _YellowTool()
    executor = _executor(tool, _FailingLogger())
    executor.execute("yellow", {})
    assert tool.calls == []


def test_yellow_result_field_equivalence_healthy_vs_raising_logger() -> None:
    healthy_result = _executor(_YellowTool(), _RecordingLogger()).execute("yellow", {})
    failing_result = _executor(_YellowTool(), _FailingLogger()).execute("yellow", {})
    assert healthy_result == failing_result


# --- RED block path --------------------------------------------------------------


def test_red_block_survives_raising_logger() -> None:
    tool = _RedTool()
    executor = _executor(tool, _FailingLogger())
    result = executor.execute("red", {})
    assert result.blocked is True
    assert result.success is False


def test_red_tool_never_executes_with_raising_logger() -> None:
    tool = _RedTool()
    executor = _executor(tool, _FailingLogger())
    executor.execute("red", {})
    assert tool.calls == []


def test_red_result_field_equivalence_healthy_vs_raising_logger() -> None:
    healthy_result = _executor(_RedTool(), _RecordingLogger()).execute("red", {})
    failing_result = _executor(_RedTool(), _FailingLogger()).execute("red", {})
    assert healthy_result == failing_result


# --- Approved YELLOW execution ---------------------------------------------------


def test_approved_execution_survives_raising_logger() -> None:
    tool = _YellowTool()
    executor = _executor(tool, _FailingLogger())
    decision = _approved_decision()
    result = executor.execute("yellow", {}, approval_decision=decision)
    assert result.success is True


def test_approved_tool_executes_exactly_once_with_raising_logger() -> None:
    tool = _YellowTool()
    executor = _executor(tool, _FailingLogger())
    decision = _approved_decision()
    executor.execute("yellow", {}, approval_decision=decision)
    assert len(tool.calls) == 1


def test_approved_result_carries_approval_metadata_despite_raising_logger() -> None:
    tool = _YellowTool()
    executor = _executor(tool, _FailingLogger())
    decision = _approved_decision()
    result = executor.execute("yellow", {}, approval_decision=decision)
    assert result.metadata.get("approval_request_id") == decision.request_id


# --- Declined behaviour unchanged ------------------------------------------------


def test_declined_behavior_unchanged_with_raising_logger() -> None:
    tool = _YellowTool()
    executor = _executor(tool, _FailingLogger())
    decision = _declined_decision()
    result = executor.execute("yellow", {}, approval_decision=decision)
    assert result.success is False
    assert result.requires_confirmation is True
    assert tool.calls == []


# --- Genuine tool failure preservation (load-bearing) ---------------------------


def test_genuine_tool_exception_remains_authoritative_with_healthy_logger() -> None:
    tool = _GenuinelyFailingTool()
    executor = _executor(tool, _RecordingLogger())
    result = executor.execute("genuinely_failing", {})
    assert result.success is False
    assert "genuine tool bug" in (result.error or "")


def test_genuine_tool_exception_not_masked_by_raising_logger() -> None:
    """Load-bearing: before the fix, the logger's own RuntimeError replaced
    the genuine ValueError entirely, hiding the real cause from the
    caller."""
    tool = _GenuinelyFailingTool()
    executor = _executor(tool, _FailingLogger())
    result = executor.execute("genuinely_failing", {})
    assert result.success is False
    assert "genuine tool bug" in (result.error or "")
    assert "simulated logger failure" not in (result.error or "")


def test_no_successful_result_fabricated_when_tool_and_logger_both_fail() -> None:
    tool = _GenuinelyFailingTool()
    executor = _executor(tool, _FailingLogger())
    result = executor.execute("genuinely_failing", {})
    assert result.success is False


# --- Helper scoping / structural proof ------------------------------------------


def test_emit_audit_event_helper_exists_and_wraps_only_emit() -> None:
    import tools.executor as module

    tree = ast.parse(inspect.getsource(module))
    except_handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and getattr(node.type, "id", None) == "Exception"
    ]
    # Exactly two bare `except Exception` blocks are expected: the
    # pre-existing tool-exception isolation in _handle_run, and the new
    # logger-emit isolation in _emit_audit_event.
    assert len(except_handlers) == 2


def test_logger_isolation_except_block_body_is_a_single_pass() -> None:
    import textwrap

    import tools.executor as module

    source = textwrap.dedent(inspect.getsource(module.ToolExecutor._emit_audit_event))
    tree = ast.parse(source)
    except_handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is not None
        and getattr(node.type, "id", None) == "Exception"
    ]
    assert len(except_handlers) == 1
    body = except_handlers[0].body
    assert len(body) == 1
    assert isinstance(body[0], ast.Pass)


def test_tool_exception_handler_in_handle_run_is_unchanged_shape() -> None:
    """The pre-existing tool-exception except block in _handle_run still
    catches the tool's own exception (unrelated to and unaffected by the
    new logger-isolation helper) and still returns a failed ToolResult -
    it must not have been altered into swallowing anything silently."""
    import tools.executor as module

    source = inspect.getsource(module.ToolExecutor._handle_run)
    assert "except Exception as exc" in source
    assert "Tool raised an unexpected error" in source


def test_all_five_emit_sites_use_the_shared_helper() -> None:
    """Structural proof via real AST call-site inspection (not substring
    search, which would also match this module's own prose docstrings):
    exactly five calls to self._emit_audit_event(...), and exactly one
    call to self._logger.emit(...) anywhere in the module (inside the
    helper itself)."""
    import tools.executor as module

    tree = ast.parse(inspect.getsource(module))

    def _count_calls(attr_name: str) -> int:
        return sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr_name
        )

    assert _count_calls("_emit_audit_event") == 5
    assert _count_calls("emit") == 1


# --- Ordinary single-action path (pre-Phase-15) proof ---------------------------


def test_ordinary_green_orchestrator_path_survives_raising_toolexecutor_logger() -> (
    None
):
    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from planner.planner import Planner
    from tools.builtin import EchoTool

    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_FailingLogger()  # type: ignore[arg-type]
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )

    response = orchestrator.handle_request("echo hello")
    assert response.success is True


def test_ordinary_yellow_orchestrator_path_surfaces_real_approval_despite_raising_logger() -> (
    None
):
    from core.command_router import CommandRouter
    from core.orchestrator import JarvisOrchestrator
    from planner.planner import Planner
    from tools.builtin import FileCreateTool

    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(FileCreateTool())
    executor = ToolExecutor(
        registry=registry, security_manager=security, logger=_FailingLogger()  # type: ignore[arg-type]
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security),
        executor=executor,
        registry=registry,
        command_router=CommandRouter(registry),
    )

    response = orchestrator.handle_request(
        "create file not_written.txt with content hello"
    )
    assert response.requires_confirmation is True
    assert response.approval_request is not None
