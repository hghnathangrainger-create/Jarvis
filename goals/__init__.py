"""
goals

Goal and milestone tracking for the Jarvis AI Operating System.

Public API:
    - Goal, Milestone, Task: Data models.
    - GoalStore: SQLite-backed persistence.
    - GoalManager: High-level interface.
"""

from goals.manager import GoalManager
from goals.models import Goal, Milestone, Task
from goals.store import GoalStore

__all__ = [
    "Goal",
    "GoalManager",
    "GoalStore",
    "Milestone",
    "Task",
]
