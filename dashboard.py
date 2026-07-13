"""
dashboard.py

Entry point for the local, read-only Jarvis dashboard (Phase 19; extended
Phase 21 with the Schedules tab's read path).

Responsibilities:
    - Load configuration and open the same configured SQLite-backed
      Jarvis database main.py uses, independently.
    - Construct MemoryManager, ApprovalHistoryStore,
      WorkflowHistoryStore, InboxStore, ScheduleStore, and
      QuarantineStore (Phase 39, Batch 1), and compose them into a
      DashboardReadModel.
    - Start the tkinter/ttk dashboard window.

Does NOT:
    - Import or depend on main.py, JarvisOrchestrator, JarvisCLI,
      CommandRouter, ToolExecutor, the live ApprovalManager,
      WorkflowEngine, AIReasoningEngine, AIRouter, or scheduler.py.
    - Require the Jarvis CLI process or scheduler.py to be running. This
      is a wholly separate local process that shares only the SQLite
      database file on disk - no IPC, no socket, no shared Python
      objects.
    - Write to the database in any way beyond the same idempotent
      initialize_database() call main.py itself already makes on every
      startup. In particular, this module never calls
      ScheduleStore.create/enable/disable/claim_due.

Run with:
    poetry run python dashboard.py
"""

from __future__ import annotations

import tkinter as tk

from approval.approval_history_store import ApprovalHistoryStore
from config.settings import load_settings
from dashboard.read_model import DashboardReadModel
from inbox.inbox_store import InboxStore
from memory.episodic_memory import EpisodicMemoryStore
from memory.memory_manager import MemoryManager
from quarantine.quarantine_store import QuarantineStore
from scheduling.schedule_store import ScheduleStore
from storage.database import (
    create_database_engine,
    create_session_factory,
    initialize_database,
)
from ui.dashboard_app import DashboardApp
from workflow.workflow_history_store import WorkflowHistoryStore


def build_read_model() -> DashboardReadModel:
    """Assemble a DashboardReadModel over the same configured database.

    This mirrors main.py's own composition-root pattern
    (create_database_engine -> initialize_database ->
    create_session_factory) independently - no object built here is
    shared with, or depends on, main.py's own instances.

    Returns:
        A ready-to-use DashboardReadModel.
    """
    settings = load_settings()
    engine = create_database_engine(settings)
    initialize_database(engine)
    session_factory = create_session_factory(engine)

    memory = MemoryManager(EpisodicMemoryStore(session_factory))
    approvals = ApprovalHistoryStore(session_factory)
    workflows = WorkflowHistoryStore(session_factory)
    inbox = InboxStore(session_factory)
    schedules = ScheduleStore(session_factory)
    quarantine = QuarantineStore(session_factory)
    return DashboardReadModel(
        memory, approvals, workflows, inbox, schedules, quarantine
    )


def main() -> None:
    """Build the read model and start the dashboard window."""
    read_model = build_read_model()
    root = tk.Tk()
    DashboardApp(root, read_model)
    root.mainloop()


if __name__ == "__main__":
    main()
