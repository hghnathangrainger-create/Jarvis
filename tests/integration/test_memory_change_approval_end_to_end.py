"""
test_memory_change_approval_end_to_end.py

End-to-end integration tests for the guarded memory-change approval flow
(Phase 5, Batch 3).

These wire the real Security Manager, Planner, Tool Registry, Tool Executor,
Approval Manager, the memory-change tools, and a real in-memory SQLite-backed
Memory Manager, and trace each change through its full journey:

    - An approved update actually changes the stored content.
    - A declined update leaves the memory unchanged.
    - An approved move changes the category.
    - An approved forget removes the specific memory.
    - A declined forget keeps it.
    - "forget all memories" stays blocked (RED), removing nothing.
    - Every applied change is audited.

These tests use a real database, so they are skipped automatically if
SQLAlchemy is not importable.

Run with:
    pytest tests/integration/test_memory_change_approval_end_to_end.py
"""

from __future__ import annotations

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")


class _SpyLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def emit(self, **kwargs: object) -> str:
        self.events.append(kwargs)
        return str(len(self.events))

    def approval_events(self) -> list[dict[str, object]]:
        return [
            e for e in self.events if e.get("action_type") == "approval_decision"
        ]


class _System:
    """The real components wired together with a real SQLite-backed memory."""

    def __init__(self) -> None:
        from sqlalchemy import create_engine

        from approval.approval_manager import ApprovalManager
        from core.orchestrator import JarvisOrchestrator
        from memory.episodic_memory import EpisodicMemoryStore
        from memory.memory_manager import MemoryManager
        from planner.planner import Planner
        from security.security_manager import SecurityManager
        from storage.database import (
            create_session_factory,
            initialize_database,
        )
        from tools.builtin import (
            MemoryForgetTool,
            MemoryTool,
            MemoryUpdateTool,
        )
        from tools.executor import ToolExecutor
        from tools.registry import ToolRegistry

        engine = create_engine("sqlite:///:memory:")
        initialize_database(engine)
        factory = create_session_factory(engine)
        self.memory = MemoryManager(EpisodicMemoryStore(factory))

        self.logger = _SpyLogger()
        self.security = SecurityManager()
        self.registry = ToolRegistry()
        self.registry.register_tool(MemoryTool(self.memory))
        self.registry.register_tool(MemoryUpdateTool(self.memory))
        self.registry.register_tool(MemoryForgetTool(self.memory))
        self.executor = ToolExecutor(
            registry=self.registry,
            security_manager=self.security,
            logger=self.logger,
        )
        self.approvals = ApprovalManager(audit_logger=self.logger)
        self.orchestrator = JarvisOrchestrator(
            planner=Planner(self.security),
            executor=self.executor,
            registry=self.registry,
            approval_manager=self.approvals,
        )

    def remember(self, text: str, category: str = "general") -> int:
        record = self.memory.save(text, category=category)
        assert record is not None
        return record.id


@pytest.fixture()
def system() -> "_System":
    return _System()


# --- Update ------------------------------------------------------------------


def test_approved_update_changes_content(system: "_System") -> None:
    mid = system.remember("deadline is Monday", category="project")
    response = system.orchestrator.handle_request(
        f"update memory {mid}: deadline is Wednesday"
    )
    assert response.requires_confirmation is True
    assert system.memory.get(mid).content == "deadline is Monday"

    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert system.memory.get(mid).content == "deadline is Wednesday"


def test_declined_update_leaves_content_unchanged(system: "_System") -> None:
    mid = system.remember("keep this", category="general")
    response = system.orchestrator.handle_request(
        f"update memory {mid}: should not apply"
    )
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert system.memory.get(mid).content == "keep this"


# --- Move --------------------------------------------------------------------


def test_approved_move_changes_category(system: "_System") -> None:
    mid = system.remember("a note", category="general")
    response = system.orchestrator.handle_request(
        f"move memory {mid} to personal"
    )
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert system.memory.get(mid).category == "personal"


# --- Forget ------------------------------------------------------------------


def test_approved_forget_removes_memory(system: "_System") -> None:
    mid = system.remember("forget me", category="general")
    response = system.orchestrator.handle_request(f"forget memory {mid}")
    decision = system.approvals.approve(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is True
    assert system.memory.get(mid) is None


def test_declined_forget_keeps_memory(system: "_System") -> None:
    mid = system.remember("stay please", category="general")
    response = system.orchestrator.handle_request(f"forget memory {mid}")
    decision = system.approvals.decline(response.approval_request.request_id)
    executed = system.orchestrator.execute_approved(response, decision)

    assert executed.success is False
    assert system.memory.get(mid) is not None


# --- Bulk forget stays blocked, changes are audited --------------------------


def test_forget_all_stays_blocked(system: "_System") -> None:
    system.remember("one")
    system.remember("two")
    response = system.orchestrator.handle_request("forget all memories")
    assert response.blocked is True
    assert system.memory.count() == 2


def test_applied_change_is_audited(system: "_System") -> None:
    mid = system.remember("audit me")
    response = system.orchestrator.handle_request(f"forget memory {mid}")
    decision = system.approvals.approve(response.approval_request.request_id)
    system.orchestrator.execute_approved(response, decision)

    approval_events = system.logger.approval_events()
    assert len(approval_events) == 1
    assert "approved" in str(approval_events[0]["detail"]).lower()


def test_full_update_then_forget_journey(system: "_System") -> None:
    mid = system.remember("draft", category="general")

    update = system.orchestrator.handle_request(f"update memory {mid}: final")
    system.orchestrator.execute_approved(
        update, system.approvals.approve(update.approval_request.request_id)
    )
    assert system.memory.get(mid).content == "final"

    forget = system.orchestrator.handle_request(f"forget memory {mid}")
    system.orchestrator.execute_approved(
        forget, system.approvals.approve(forget.approval_request.request_id)
    )
    assert system.memory.get(mid) is None