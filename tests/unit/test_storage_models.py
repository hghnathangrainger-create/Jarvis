"""
test_storage_models.py

Unit tests for SQLAlchemy ORM model definitions (storage/models.py).

Run with:
    pytest tests/unit/test_storage_models.py
"""

from __future__ import annotations

from storage.models import ApprovalHistoryEntry


def test_approval_history_entry_repr_is_a_class_method() -> None:
    """__repr__ must be a method on the class, not a stray module-level
    function that happens to share its name and sit right after it."""
    assert "__repr__" in ApprovalHistoryEntry.__dict__


def test_approval_history_entry_repr_returns_expected_representation() -> None:
    # status is set explicitly here because its "pending" default is applied
    # by SQLAlchemy at flush time, not at construction - ApprovalHistoryStore
    # (the only real caller) always sets it explicitly for the same reason.
    entry = ApprovalHistoryEntry(
        request_id="req-1",
        action="a",
        reason="r",
        security_tier="yellow",
        status="pending",
    )
    assert repr(entry) == "<ApprovalHistoryEntry request_id='req-1' status='pending'>"
