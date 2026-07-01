"""
test_core_approval.py

Unit tests for the Jarvis Core approval integration (Phase 2, Step 4).

These tests confirm that YELLOW actions create a pending approval request in
the response, while GREEN actions run and RED actions stay blocked, and that
no YELLOW action is executed at this step. The orchestrator is exercised with
the real Planner, Security Manager, Tool Manager, and Approval Manager, plus a
fake memory and spy logger.

Run with:
    pytest tests/unit/test_core_approval.py
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from approval.approval_manager import ApprovalManager
from config.constants import SecurityTier
from core.orchestrator import JarvisOrchestrator
from memory.episodic_memory import MemoryRecord
from planner.planner import Planner
from security.security_manager import SecurityManager
from tools.base_tool import BaseTool, ToolRequest, ToolResult
from tools.builtin import EchoTool, InfoTool, MemoryTool
from tools.executor import ToolExecutor
from tools.registry import ToolRegistry


# --- Test doubles ------------------------------------------------------------


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))


class _FakeMemory:
    def __init__(self) -> None:
        self._data: list[MemoryRecord] = []

    def add(self, content: str) -> None:
        self._data.append(
            MemoryRecord(
                id=len(self._data) + 1,
                content=content,
                source="test",
                session_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )

    def list_recent(self, limit: int = 10) -> list[MemoryRecord]:
        return list(reversed(self._data))[:limit]

    def search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        term = query.lower()
        return [r for r in reversed(self._data) if term in r.content.lower()][:limit]


def _build(approval_manager: ApprovalManager | None = None) -> JarvisOrchestrator:
    memory = _FakeMemory()
    memory.add("Nathan likes Python.")
    security = SecurityManager()
    planner = Planner(security)
    registry = ToolRegistry()
    registry.register_tool(EchoTool())
    registry.register_tool(InfoTool())
    registry.register_tool(MemoryTool(memory))  # type: ignore[arg-type]
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    return JarvisOrchestrator(
        planner=planner,
        executor=executor,
        registry=registry,
        approval_manager=approval_manager,
    )


@pytest.fixture()
def orchestrator() -> JarvisOrchestrator:
    return _build()


# --- GREEN: no approval ------------------------------------------------------


def test_green_request_has_no_approval(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("show me system info")
    assert response.success is True
    assert response.approval_request is None
    assert response.plan is not None


def test_green_echo_still_runs(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("echo hello world")
    assert response.success is True
    assert response.approval_request is None


# --- YELLOW: approval request created ----------------------------------------


def test_yellow_send_email_creates_approval(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("send email to Alex")
    assert response.requires_confirmation is True
    assert response.blocked is False
    assert response.approval_request is not None
    assert response.plan is not None


def test_yellow_install_creates_approval(orchestrator: JarvisOrchestrator) -> None:
    response = orchestrator.handle_request("install software package")
    assert response.requires_confirmation is True
    assert response.approval_request is not None


def test_approval_request_has_expected_fields(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("send email to Bob")
    approval = response.approval_request
    assert approval is not None
    assert approval.action
    assert approval.reason
    assert approval.security_tier is SecurityTier.YELLOW


def test_approval_request_is_pending_in_manager(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("send email to Bob")
    assert response.approval_request is not None
    assert orchestrator.approvals.has_pending(response.approval_request.request_id)


# --- RED: blocked, no approval -----------------------------------------------


def test_red_request_is_blocked_without_approval(
    orchestrator: JarvisOrchestrator,
) -> None:
    response = orchestrator.handle_request("format drive C")
    assert response.blocked is True
    assert response.approval_request is None
    assert response.plan is not None


# --- Plan always present -----------------------------------------------------


@pytest.mark.parametrize(
    "request_text",
    ["echo hi", "send email", "format drive", "show memories", "install software"],
)
def test_plan_always_included(
    orchestrator: JarvisOrchestrator, request_text: str
) -> None:
    assert orchestrator.handle_request(request_text).plan is not None


# --- Approval manager injection ----------------------------------------------


def test_injected_approval_manager_is_used() -> None:
    shared = ApprovalManager()
    orchestrator = _build(approval_manager=shared)
    response = orchestrator.handle_request("send email to Carol")
    assert response.approval_request is not None
    assert shared.has_pending(response.approval_request.request_id)


def test_default_approval_manager_is_created() -> None:
    orchestrator = _build()
    assert orchestrator.approvals is not None


# --- No YELLOW execution at this step ----------------------------------------


class _YellowActionTool(BaseTool):
    """A tool named 'echo' whose action is YELLOW; its run must not be called."""

    ran = False

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "A tool with a sensitive action, for the no-execution test."

    def action_for(self, request: ToolRequest) -> str:
        return "send email"

    def run(self, request: ToolRequest) -> ToolResult:
        _YellowActionTool.ran = True
        raise AssertionError("A YELLOW action must not execute at this step.")


def test_yellow_action_is_not_executed() -> None:
    _YellowActionTool.ran = False
    security = SecurityManager()
    registry = ToolRegistry()
    registry.register_tool(_YellowActionTool())
    executor = ToolExecutor(
        registry=registry,
        security_manager=security,
        logger=_SpyLogger(),  # type: ignore[arg-type]
    )
    orchestrator = JarvisOrchestrator(
        planner=Planner(security), executor=executor, registry=registry
    )

    response = orchestrator.handle_request("echo something")
    assert response.requires_confirmation is True
    assert response.approval_request is not None
    assert _YellowActionTool.ran is False